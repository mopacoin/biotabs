"""Webseite: letzter Preisstand je Shop und Größe, plus Zustand des letzten Laufs."""
import html
import sqlite3

from fastapi import FastAPI
from fastapi.responses import HTMLResponse

from scraper import DB_PATH, db_connect

app = FastAPI()

LATEST_SQL = """
SELECT shop, url, product, variant, price, pack_size, pack_unit, price_per_unit, available, checked_at
FROM prices
WHERE checked_at = (SELECT MAX(checked_at) FROM prices p2 WHERE p2.shop = prices.shop)
ORDER BY product, pack_unit, pack_size, price_per_unit, price
"""

RUNS_SQL = """
SELECT shop, checked_at, pages, offers, errors, warning
FROM runs
WHERE checked_at = (SELECT MAX(checked_at) FROM runs r2 WHERE r2.shop = runs.shop)
ORDER BY warning IS NULL, shop
"""


def esc(value):
    return html.escape(str(value)) if value is not None else "–"


@app.get("/", response_class=HTMLResponse)
def index():
    db_connect().close()  # legt Tabellen an, falls noch kein Lauf stattfand
    con = sqlite3.connect(DB_PATH)
    prices = con.execute(LATEST_SQL).fetchall()
    runs = con.execute(RUNS_SQL).fetchall()
    con.close()

    price_rows = []
    for shop, url, product, variant, price, size, unit, per_unit, available, checked in prices:
        size_txt = f"{size:g} {unit}" if size and unit else "–"
        per_txt = f"{per_unit:.2f} €/{unit}" if per_unit is not None else "–"
        price_rows.append(
            f"<tr{'' if available else ' class=na'}><td>{esc(shop)}</td>"
            f"<td><a href='{esc(url)}'>{esc(product)}</a></td><td>{esc(variant)}</td>"
            f"<td class=num>{price:.2f} €</td><td>{size_txt}</td><td class=num>{per_txt}</td>"
            f"<td>{'ja' if available else 'nein'}</td></tr>"
        )
    run_rows = [
        f"<tr{' class=warn' if warning else ''}><td>{esc(shop)}</td><td>{esc(checked)}</td><td class=num>{pages}</td>"
        f"<td class=num>{offers}</td><td class=num>{errors}</td><td>{esc(warning) if warning else 'ok'}</td></tr>"
        for shop, checked, pages, offers, errors, warning in runs
    ]
    return f"""<!doctype html><html lang="de"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Biotabs Preise</title>
<style>
:root{{--bg:#fff;--fg:#111;--line:#ddd;--muted:#888;--warn:#fff3cd}}
@media (prefers-color-scheme: dark){{:root{{--bg:#111;--fg:#eee;--line:#333;--muted:#777;--warn:#4a3b00}}}}
body{{font-family:system-ui,sans-serif;margin:16px;background:var(--bg);color:var(--fg)}}
a{{color:inherit}} .wrap{{overflow-x:auto}}
table{{border-collapse:collapse;width:100%;margin-bottom:24px}}
td,th{{border-bottom:1px solid var(--line);padding:6px;text-align:left;font-size:14px;white-space:nowrap}}
.num{{text-align:right;font-variant-numeric:tabular-nums}} .na{{color:var(--muted)}} .warn{{background:var(--warn)}}
</style></head><body>
<h1>Biotabs Preise</h1>
<h2>Zustand letzter Lauf</h2>
<div class=wrap><table><tr><th>Shop</th><th>Geprüft (UTC)</th><th>Seiten</th><th>Preise</th><th>Fehler</th><th>Status</th></tr>
{''.join(run_rows) or '<tr><td colspan=6>Noch kein Lauf.</td></tr>'}</table></div>
<h2>Preise</h2>
<div class=wrap><table><tr><th>Shop</th><th>Produkt</th><th>Variante</th><th>Preis</th><th>Größe</th><th>Grundpreis</th><th>Verfügbar</th></tr>
{''.join(price_rows) or '<tr><td colspan=7>Noch keine Daten.</td></tr>'}</table></div>
</body></html>"""
