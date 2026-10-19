"""Webseite: günstigste Angebote, Warenkorb-Rechner, Versand und Aktionen je Shop, Filter und Zustand der Läufe."""
import html
import json
import re
import sqlite3
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from urllib.parse import urlencode

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from scraper import DB_PATH, db_connect
from shops import SHIPPING, estimate_weight, shipping_cost

WARENKORB_JS = Path(__file__).with_name("warenkorb.js")

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

# Aktionen aus dem letzten Lauf je Shop (ein Shop ohne Aktion im letzten Lauf zeigt keine alte an)
PROMOS_SQL = """
SELECT shop, text, code, percent, sitewide
FROM promos
WHERE checked_at = (SELECT MAX(checked_at) FROM runs r WHERE r.shop = promos.shop)
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


def load_promos():
    db_connect().close()
    con = sqlite3.connect(DB_PATH)
    promos = defaultdict(list)
    for shop, text, code, percent, sitewide in con.execute(PROMOS_SQL):
        promos[shop].append({"text": text, "code": code, "percent": percent, "sitewide": bool(sitewide)})
    con.close()
    return dict(promos)


def single_price_with_shipping(o):
    """Preis eines einzelnen Artikels inkl. Versand, wenn man nur ihn bestellt."""
    ship = shipping_cost(o["shop"], o["price"], estimate_weight(o["size"], o["unit"]))
    return None if ship is None else o["price"] + ship


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


@app.get("/api/versand")
def api_shipping():
    return SHIPPING


@app.get("/api/aktionen")
def api_promos():
    return load_promos()


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


def coupon_badge(shop, promos):
    best = max((p for p in promos.get(shop, []) if p["sitewide"] and p["percent"]), key=lambda p: p["percent"], default=None)
    return f" <span class=coupon title='{esc(best['text'])}'>−{best['percent']:g} % {esc(best['code'] or '')}</span>" if best else ""


def with_shipping(o):
    total = single_price_with_shipping(o)
    if total is None:
        return "–"
    mark = "<span class=est title='Versand geschätzt'>*</span>" if SHIPPING.get(o["shop"], {}).get("estimated") else ""
    return f"{euro(total)}{mark}"


def render_best(rows, produkt, promos):
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
                f"<td><a href='{esc(b['url'])}'>{esc(b['shop'])}</a>{coupon_badge(b['shop'], promos)}</td>"
                f"<td class=num><b>{euro(b['price'])}</b>{change(b)}</td><td class=num>{with_shipping(b)}</td><td class=num>{per_unit(b)}</td>"
                f"<td class=muted>{saving}</td><td class=num>{r['count_available']}/{r['count']}</td></tr>"
            )
        else:
            out.append(
                f"<tr class=na><td>{group_cell}</td><td>{size_link}</td><td colspan=5>überall ausverkauft</td>"
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


def render_shops(promos):
    rows = []
    for shop, rule in sorted(SHIPPING.items()):
        tiers = rule["weight"]
        cost = euro(tiers[0][1]) if len(tiers) == 1 else f"{euro(tiers[0][1])} – {euro(tiers[-1][1])} nach Gewicht"
        if rule.get("by_value"):
            cost += "".join(f", ab {euro(v)} Warenwert {euro(c)}" for v, c in rule["by_value"])
        est = " <span class=est>geschätzt</span>" if rule.get("estimated") else ""
        note = f" <span class=muted>({esc(rule['note'])})</span>" if rule.get("note") else ""
        minimum = f"<br><span class=muted>Mindestbestellwert {euro(rule['min_order'])}</span>" if rule.get("min_order") else ""
        shop_promos = "<br>".join(
            f"{'<b>' + esc(p['code']) + '</b>: ' if p['code'] else ''}{esc(p['text'])}"
            f"{' <span class=coupon>gilt für alles</span>' if p['sitewide'] else ''}"
            for p in promos.get(shop, [])
        ) or "<span class=muted>keine erkannt</span>"
        rows.append(
            f"<tr><td><a href='{esc(rule['source'])}'>{esc(shop)}</a></td><td>{cost}{est}{note}{minimum}</td>"
            f"<td class=num>{euro(rule['free_from']) if rule.get('free_from') is not None else '–'}</td>"
            f"<td class=wraptext>{shop_promos}</td></tr>"
        )
    return "".join(rows)


def cart_data(offers, promos):
    keys = ("shop", "url", "product", "group", "size", "unit", "size_label", "price", "available")
    data = {
        "groups": GROUP_NAMES,
        "offers": [{k: o[k] for k in keys} for o in offers if o["group"] and o["size"] is not None],
        "shipping": SHIPPING,
        "promos": promos,
    }
    return json.dumps(data, ensure_ascii=False).replace("</", "<\\/")


def options(values, selected, empty_label):
    opts = [f"<option value=''>{empty_label}</option>"]
    opts += [f"<option{' selected' if v == selected else ''}>{esc(v)}</option>" for v in values]
    return "".join(opts)


@app.get("/", response_class=HTMLResponse)
def index(produkt: str | None = None, groesse: str | None = None, verfuegbar: bool = False, sortierung: str = "groesse"):
    offers, runs = load_offers()
    promos = load_promos()
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
.coupon{{font-size:12px;border:1px solid var(--down);color:var(--down);border-radius:4px;padding:0 4px;white-space:nowrap}}
.est{{font-size:12px;color:var(--muted)}} .wraptext{{white-space:normal;min-width:240px}}
.cart{{background:var(--accent);padding:12px;border-radius:8px;display:grid;gap:12px}}
.cart-row{{display:flex;flex-wrap:wrap;gap:8px;align-items:center}}
.cart-row input{{width:4.5em;font:inherit;padding:4px}}
.cart-total{{display:flex;flex-wrap:wrap;gap:4px 16px;align-items:baseline}} .cart-total strong{{font-size:24px}}
.cart-shop{{border:1px solid var(--line);border-radius:8px;padding:8px 12px;margin-top:8px;overflow-x:auto}}
.cart-shop h4{{margin:0 0 4px;display:flex;justify-content:space-between;gap:12px}}
.sr{{position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0 0 0 0)}}
</style></head><body>
<h1>Biotabs Preise</h1>
<p class=muted>Letzter Lauf: {esc(local_time(last_run))} · {len(offers)} Angebote aus {len({o['shop'] for o in offers})} Shops
{f" · <b>{warnings} Shop(s) mit Warnung</b>" if warnings else ""} · Preise inkl. MwSt.</p>

<div class=chips><a href='/' class='{'' if produkt else 'on'}'>Alle</a>{''.join(
    f"<a href='{esc(link(produkt=g))}' class='{'on' if g == produkt else ''}'>{esc(g)}</a>" for g in GROUP_NAMES)}</div>

<h2>Günstigste Angebote{' – ' + esc(produkt) if produkt else ''}</h2>
<div class=wrap><table><tr><th>Produkt</th><th>Größe</th><th>Günstigster Shop</th><th>Preis</th><th>einzeln inkl. Versand</th><th>Grundpreis</th><th>Ersparnis</th><th>verfügbar</th></tr>
{render_best(best_offers(offers), produkt, promos) or '<tr><td colspan=8>Noch keine Daten.</td></tr>'}</table></div>

<h2 id=warenkorb>Warenkorb-Rechner</h2>
<p class=muted>Produkte und Mengen wählen: Der Rechner sucht die insgesamt günstigste Aufteilung auf einen oder mehrere Shops,
inklusive Versandkosten, versandkostenfrei-Grenzen und Gutscheinen, die für das ganze Sortiment gelten. Versandgewichte sind geschätzt.</p>
<div class=cart>
<div id=cart-items></div>
<div class=cart-row><button type=button id=cart-add>Produkt hinzufügen</button>
<label><input type=checkbox id=cart-coupons checked> Gutscheine einrechnen</label></div>
<div id=cart-result aria-live=polite><noscript>Der Warenkorb-Rechner braucht JavaScript.</noscript></div>
</div>

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

<h2>Shops: Versand und Aktionen</h2>
<p class=muted>Versand innerhalb Deutschlands, Standardpaket. Aktionen werden bei jedem Lauf von der Startseite gelesen;
Bedingungen (z. B. ausgenommene Marken) stehen im Shop.</p>
<div class=wrap><table><tr><th>Shop</th><th>Versand</th><th>frei ab</th><th>Aktionen</th></tr>
{render_shops(promos)}</table></div>

<details{' open' if warnings else ''}><summary>Zustand letzter Lauf ({len(runs)} Shops{f', {warnings} Warnung(en)' if warnings else ', alle ok'})</summary>
<div class=wrap><table><tr><th>Shop</th><th>Geprüft</th><th>Seiten</th><th>Preise</th><th>Fehler</th><th>Status</th></tr>
{render_runs(runs) or '<tr><td colspan=6>Noch kein Lauf.</td></tr>'}</table></div></details>
<script>const DATA = {cart_data(offers, promos)};</script>
<script>{WARENKORB_JS.read_text(encoding="utf-8")}</script>
</body></html>"""
