"""Webseite: günstigste Angebote je Produkt und Größe, Filter, Preisänderungen und Zustand der Läufe."""
import html
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from scraper import DB_PATH, db_connect

app = FastAPI()

# Reihenfolge = Anzeige-Reihenfolge. Die Shops schreiben die Namen unterschiedlich,
# darum wird jedes Angebot über ein Muster einer Produktgruppe zugeordnet.
PRODUCT_GROUPS = [
    ("Düngetabletten", re.compile(r"tablett|\btabs\b|^bio\s*tabs\b", re.I)),
    ("Bio PK 5-8", re.compile(r"pk\s*5-8", re.I)),
    ("Silicium Flash", re.compile(r"sili[cz]i?um", re.I)),
    ("Bactrex", re.compile(r"bactrex", re.I)),
    ("Orgatrex", re.compile(r"orgatrex", re.I)),
    ("Startrex", re.compile(r"startrex", re.I)),
    ("Mycotrex", re.compile(r"mycotrex", re.I)),
]
GROUP_NAMES = [name for name, _ in PRODUCT_GROUPS]

LATEST_SQL = """
SELECT shop, url, product, variant, price, pack_size, pack_unit, price_per_unit, available, checked_at
FROM prices
WHERE checked_at = (SELECT MAX(checked_at) FROM prices p2 WHERE p2.shop = prices.shop)
"""

# Letzter Preis desselben Angebots vor dem aktuellen Lauf des Shops
PREVIOUS_SQL = """
SELECT shop, product, COALESCE(variant, ''), price
FROM prices p
WHERE checked_at = (
    SELECT MAX(checked_at) FROM prices p2
    WHERE p2.shop = p.shop AND p2.checked_at < (SELECT MAX(checked_at) FROM prices p3 WHERE p3.shop = p.shop)
)
"""

RUNS_SQL = """
SELECT shop, checked_at, pages, offers, errors, warning
FROM runs
WHERE checked_at = (SELECT MAX(checked_at) FROM runs r2 WHERE r2.shop = runs.shop)
ORDER BY warning IS NULL, shop
"""


def product_group(product):
    # Bestandteile zuerst prüfen, sonst landet "BioTabs Bactrex" über "^bio tabs" bei den Tabletten
    for name, pattern in PRODUCT_GROUPS[1:] + PRODUCT_GROUPS[:1]:
        if pattern.search(product or ""):
            return name
    return None


def size_label(amount, unit):
    if amount is None:
        return "–"
    if unit == "kg" and amount < 1:
        return f"{amount * 1000:g} g"
    if unit == "l" and amount < 1:
        return f"{amount * 1000:g} ml"
    return f"{amount:g} {unit}".replace(".", ",")


def load_offers():
    db_connect().close()  # legt Tabellen an, falls noch kein Lauf stattfand
    con = sqlite3.connect(DB_PATH)
    previous = {(s, p, v): price for s, p, v, price in con.execute(PREVIOUS_SQL)}
    offers = []
    for shop, url, product, variant, price, size, unit, per_unit, available, checked in con.execute(LATEST_SQL):
        offers.append({
            "shop": shop,
            "url": url,
            "product": product,
            "group": product_group(product),
            "variant": variant,
            "price": price,
            "size": size,
            "unit": unit,
            "size_label": size_label(size, unit),
            "price_per_unit": per_unit,
            "available": bool(available),
            "checked_at": checked,
            "previous_price": previous.get((shop, product, variant or "")),
        })
    runs = con.execute(RUNS_SQL).fetchall()
    con.close()
    return offers, runs


def filter_offers(offers, produkt=None, groesse=None, verfuegbar=False, sortierung="groesse"):
    result = [
        o for o in offers
        if (not produkt or o["group"] == produkt)
        and (not groesse or o["size_label"] == groesse)
        and (not verfuegbar or o["available"])
    ]
    group = lambda o: GROUP_NAMES.index(o["group"]) if o["group"] in GROUP_NAMES else 99
    if sortierung == "grundpreis":  # größenübergreifend: was ist pro Stück/kg/l am günstigsten
        key = lambda o: (group(o), o["unit"] or "", o["price_per_unit"] is None, o["price_per_unit"] or 0)
    elif sortierung == "preis":
        key = lambda o: (group(o), o["price"])
    else:
        key = lambda o: (group(o), o["unit"] or "", o["size"] or 0, o["price"])
    return sorted(result, key=key)


def best_offers(offers):
    """Je Produktgruppe und Größe das günstigste verfügbare Angebot plus Anzahl der Angebote."""
    buckets = defaultdict(list)
    for o in offers:
        if o["group"] and o["size"] is not None:
            buckets[(o["group"], o["unit"], o["size"])].append(o)
    rows = []
    for (group, unit, size), items in buckets.items():
        available = sorted((o for o in items if o["available"]), key=lambda o: o["price"])
        rows.append({
            "group": group,
            "unit": unit,
            "size": size,
            "size_label": size_label(size, unit),
            "best": available[0] if available else None,
            "second": available[1] if len(available) > 1 else None,
            "count": len(items),
            "count_available": len(available),
        })
    rows.sort(key=lambda r: (GROUP_NAMES.index(r["group"]), r["unit"], r["size"]))
    return rows


# --- JSON-Schnittstelle ---------------------------------------------------------


@app.get("/api/angebote")
def api_offers(produkt: str | None = None, groesse: str | None = None, verfuegbar: bool = False, sortierung: str = "groesse"):
    offers, _ = load_offers()
    return filter_offers(offers, produkt, groesse, verfuegbar, sortierung)


@app.get("/api/bestpreise")
def api_best():
    offers, _ = load_offers()
    return [
        {**{k: r[k] for k in ("group", "size_label", "count", "count_available")}, "best": r["best"]}
        for r in best_offers(offers)
    ]


# --- Webseite -------------------------------------------------------------------


def local_time(iso):
    """UTC-Zeitstempel aus der DB in der Ortszeit des Rechners (auf dem Pi: Europe/Berlin)."""
    return datetime.fromisoformat(iso).astimezone().strftime("%d.%m.%Y %H:%M") if iso else None


def esc(value):
    return html.escape(str(value)) if value is not None else "–"


def euro(value):
    return f"{value:,.2f} €".replace(",", "X").replace(".", ",").replace("X", ".") if value is not None else "–"


def per_unit(o):
    return f"{euro(o['price_per_unit'])}/{o['unit']}" if o["price_per_unit"] is not None else "–"


def change(o):
    prev = o["previous_price"]
    if prev is None or abs(prev - o["price"]) < 0.005:
        return ""
    diff = o["price"] - prev
    cls, arrow = ("up", "▲") if diff > 0 else ("down", "▼")
    return f" <span class={cls} title='vorher {euro(prev)}'>{arrow} {euro(abs(diff))}</span>"


def link(**params):
    return "/?" + urlencode({k: v for k, v in params.items() if v})


def render_best(rows, produkt):
    out, current = [], None
    for r in rows:
        if produkt and r["group"] != produkt:
            continue
        group_cell = ""
        if r["group"] != current:
            current = r["group"]
            group_cell = f"<a href='{esc(link(produkt=r['group']))}'>{esc(r['group'])}</a>"
        b, s = r["best"], r["second"]
        size_link = f"<a href='{esc(link(produkt=r['group'], groesse=r['size_label']))}'>{esc(r['size_label'])}</a>"
        if b:
            if not s:
                saving = "einziges verfügbares Angebot"
            elif s["price"] - b["price"] < 0.005:
                saving = f"gleich teuer wie {esc(s['shop'])}"
            else:
                saving = f"{euro(s['price'] - b['price'])} günstiger als {esc(s['shop'])}"
            out.append(
                f"<tr><td>{group_cell}</td><td>{size_link}</td>"
                f"<td><a href='{esc(b['url'])}'>{esc(b['shop'])}</a></td>"
                f"<td class=num><b>{euro(b['price'])}</b>{change(b)}</td><td class=num>{per_unit(b)}</td>"
                f"<td class=muted>{saving}</td><td class=num>{r['count_available']}/{r['count']}</td></tr>"
            )
        else:
            out.append(
                f"<tr class=na><td>{group_cell}</td><td>{size_link}</td><td colspan=4>überall ausverkauft</td>"
                f"<td class=num>0/{r['count']}</td></tr>"
            )
    return "".join(out)


def render_offers(offers):
    rows = []
    for o in offers:
        rows.append(
            f"<tr{'' if o['available'] else ' class=na'}><td>{esc(o['group'])}</td><td>{esc(o['size_label'])}</td>"
            f"<td>{esc(o['shop'])}</td><td><a href='{esc(o['url'])}'>{esc(o['product'])}</a>"
            f"{' <span class=muted>(' + esc(o['variant']) + ')</span>' if o['variant'] else ''}</td>"
            f"<td class=num>{euro(o['price'])}{change(o)}</td><td class=num>{per_unit(o)}</td>"
            f"<td>{'ja' if o['available'] else 'nein'}</td></tr>"
        )
    return "".join(rows)


def render_runs(runs):
    return "".join(
        f"<tr{' class=warn' if warning else ''}><td>{esc(shop)}</td><td>{esc(local_time(checked))}</td><td class=num>{pages}</td>"
        f"<td class=num>{offers}</td><td class=num>{errors}</td><td>{esc(warning) if warning else 'ok'}</td></tr>"
        for shop, checked, pages, offers, errors, warning in runs
    )


def options(values, selected, empty_label):
    opts = [f"<option value=''>{empty_label}</option>"]
    opts += [f"<option{' selected' if v == selected else ''}>{esc(v)}</option>" for v in values]
    return "".join(opts)


@app.get("/", response_class=HTMLResponse)
def index(produkt: str | None = None, groesse: str | None = None, verfuegbar: bool = False, sortierung: str = "groesse"):
    offers, runs = load_offers()
    produkt = produkt if produkt in GROUP_NAMES else None
    sizes = sorted(
        {(o["unit"] or "", o["size"] or 0, o["size_label"]) for o in offers if o["size"] is not None and (not produkt or o["group"] == produkt)}
    )
    size_labels = list(dict.fromkeys(label for _, _, label in sizes))
    groesse = groesse if groesse in size_labels else None
    shown = filter_offers(offers, produkt, groesse, verfuegbar, sortierung)
    warnings = sum(1 for r in runs if r[5])
    last_run = max((r[1] for r in runs), default=None)

    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Biotabs Preise</title>
<style>
:root{{--bg:#fff;--fg:#111;--line:#ddd;--muted:#777;--warn:#fff3cd;--up:#b42318;--down:#067647;--accent:#f4f6f8}}
@media (prefers-color-scheme: dark){{:root{{--bg:#111;--fg:#eee;--line:#333;--muted:#888;--warn:#4a3b00;--up:#f97066;--down:#47cd89;--accent:#1c1c1c}}}}
body{{font-family:system-ui,sans-serif;margin:16px;background:var(--bg);color:var(--fg);max-width:1200px}}
a{{color:inherit}} .wrap{{overflow-x:auto}} h2{{margin-top:28px}}
table{{border-collapse:collapse;width:100%}}
td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left;font-size:14px;white-space:nowrap}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .na,.muted{{color:var(--muted)}} .warn{{background:var(--warn)}}
.up{{color:var(--up);font-size:12px}} .down{{color:var(--down);font-size:12px}}
form{{display:flex;flex-wrap:wrap;gap:8px 16px;align-items:center;background:var(--accent);padding:12px;border-radius:8px}}
select,button{{font:inherit;padding:4px 8px}}
.chips a{{display:inline-block;margin:0 6px 6px 0;padding:4px 10px;border:1px solid var(--line);border-radius:999px;text-decoration:none}}
.chips a.on{{background:var(--fg);color:var(--bg)}}
details summary{{cursor:pointer;margin-top:28px;font-weight:600}}
</style></head><body>
<h1>Biotabs Preise</h1>
<p class=muted>Letzter Lauf: {esc(local_time(last_run))} · {len(offers)} Angebote aus {len({o['shop'] for o in offers})} Shops
{f" · <b>{warnings} Shop(s) mit Warnung</b>" if warnings else ""} · Preise inkl. MwSt., ohne Versand</p>

<div class=chips><a href='/' class='{'' if produkt else 'on'}'>Alle</a>{''.join(
    f"<a href='{esc(link(produkt=g))}' class='{'on' if g == produkt else ''}'>{esc(g)}</a>" for g in GROUP_NAMES)}</div>

<h2>Günstigste Angebote{' – ' + esc(produkt) if produkt else ''}</h2>
<div class=wrap><table><tr><th>Produkt</th><th>Größe</th><th>Günstigster Shop</th><th>Preis</th><th>Grundpreis</th><th>Ersparnis</th><th>verfügbar</th></tr>
{render_best(best_offers(offers), produkt) or '<tr><td colspan=7>Noch keine Daten.</td></tr>'}</table></div>

<h2>Alle Angebote</h2>
<form method=get>
<label>Produkt <select name=produkt onchange="this.form.groesse.value='';this.form.submit()">{options(GROUP_NAMES, produkt, 'alle')}</select></label>
<label>Größe <select name=groesse onchange="this.form.submit()">{options(size_labels, groesse, 'alle')}</select></label>
<label><input type=checkbox name=verfuegbar value=true{' checked' if verfuegbar else ''} onchange="this.form.submit()"> nur verfügbare</label>
<label>Sortierung <select name=sortierung onchange="this.form.submit()">
{''.join(f"<option value={v}{' selected' if sortierung == v else ''}>{label}</option>" for v, label in
    (("groesse", "Größe, dann Preis"), ("grundpreis", "Grundpreis über alle Größen"), ("preis", "Preis")))}</select></label>
<noscript><button>Anzeigen</button></noscript>
</form>
<div class=wrap><table><tr><th>Produkt</th><th>Größe</th><th>Shop</th><th>Artikel</th><th>Preis</th><th>Grundpreis</th><th>Verfügbar</th></tr>
{render_offers(shown) or '<tr><td colspan=7>Keine Angebote für diese Auswahl.</td></tr>'}</table></div>

<details{' open' if warnings else ''}><summary>Zustand letzter Lauf ({len(runs)} Shops{f', {warnings} Warnung(en)' if warnings else ', alle ok'})</summary>
<div class=wrap><table><tr><th>Shop</th><th>Geprüft</th><th>Seiten</th><th>Preise</th><th>Fehler</th><th>Status</th></tr>
{render_runs(runs) or '<tr><td colspan=6>Noch kein Lauf.</td></tr>'}</table></div></details>
</body></html>"""
