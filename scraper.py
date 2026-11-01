"""Holt Biotabs-Preise je Größe von deutschen Shops und speichert sie in SQLite.

Aufruf:
    python scraper.py              # Preise abrufen (Produktsuche nur, wenn älter als 7 Tage)
    python scraper.py --discover   # Produktsuche über die Sitemaps erzwingen
    python scraper.py --shop NAME  # nur einen Shop abrufen (mehrfach möglich)
"""
import argparse
import gzip
import html
import json
import logging
import re
import sqlite3
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib import robotparser
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from shops import SHOPS

DB_PATH = Path(__file__).parent / "prices.db"
USER_AGENT = "BiotabsPreisTracker/0.2 (privat, Preisvergleich; kontakt: BITTE-EINTRAGEN)"
DELAY_SECONDS = 5  # Abstand zwischen zwei Anfragen an denselben Shop
DISCOVERY_MAX_AGE = timedelta(days=7)

PRODUCT_RE = re.compile(r"bio[-_ ]?tabs|bio[-_ ]?pk|sili[cz]ium[-_ ]?flash|bactrex|orgatrex|startrex|mycotrex", re.I)
# Gehört nicht zur Produktliste, obwohl der Name "biotabs" enthält
EXCLUDE_RE = re.compile(
    r"guerr?illa|boom[-_]?boom|juice|feeding|charts|nutrients/?$|marke|starter|perfect|(?<!pk-)(?<!pk_)booster|clipper|autopot|kit|box|guide"
    r"|/collections/|product-category|/kategorie/|/blogs?/",
    re.I,
)
# Filter auf Produktnamen: nur die gewünschten Produkte, keine Sets, Zubehör oder andere BioTabs-Artikel
TARGET_RE = re.compile(r"bio\s*pk|pk[-\s]*booster|\bpk\s*5-8|sili[cz]i?um|bactrex|orgatrex|startrex|mycotrex|tablett|\btabs\b|^bio\s*tabs\b.*\d\s*st", re.I)
NOT_TARGET_RE = re.compile(r"guerr?illa|boom|start(?:er)?pack|poster|l[üu]ftung|\bset\b|kit\b|box", re.I)
SIZE_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*(kg|gr|g|gramm|ml|l|liter|st[üu]ck|stk|st|tabs?|tabletten)(?![a-zäöü])", re.I)

log = logging.getLogger("scraper")


@dataclass
class Offer:
    product: str
    variant: str | None
    sku: str | None
    price: float
    available: bool
    url: str


class Shop:
    """Abruf eines Shops mit eigener Session, robots.txt-Prüfung und Wartezeit."""

    def __init__(self, name, home):
        self.name = name
        self.home = home
        self.session = requests.Session()
        self.session.headers["User-Agent"] = USER_AGENT
        self.robots = None
        self.last_request = 0.0

    def _wait(self):
        pause = DELAY_SECONDS - (time.monotonic() - self.last_request)
        if pause > 0:
            time.sleep(pause)
        self.last_request = time.monotonic()

    def robots_txt(self):
        if self.robots is None:
            self.robots = robotparser.RobotFileParser()
            try:
                self._wait()
                r = self.session.get(urljoin(self.home, "/robots.txt"), timeout=15)
                self.robots_text = r.text if r.status_code == 200 else ""
            except requests.RequestException:
                self.robots_text = "User-agent: *\nDisallow: /"  # bei Fehler lieber nicht abrufen
            self.robots.parse(self.robots_text.splitlines())
        return self.robots

    def get(self, url):
        if not self.robots_txt().can_fetch(USER_AGENT, url):
            raise PermissionError("durch robots.txt untersagt")
        self._wait()
        r = self.session.get(url, timeout=30)
        r.raise_for_status()
        return r

    def discover_product_urls(self):
        """Sucht in den Sitemaps nach URLs mit Produktbegriffen."""
        self.robots_txt()
        # Manche Shops tragen in der robots.txt Nicht-Sitemaps ein (plantplanet: llms.txt)
        todo = [u for u in re.findall(r"(?im)^sitemap:\s*(\S+)", self.robots_text) if re.search(r"\.xml(\.gz)?$", u)]
        fallbacks = [urljoin(self.home, p) for p in ("wp-sitemap.xml", "sitemap.xml", "sitemap_index.xml")]
        found, seen = {}, set()
        # Standardnamen nur, solange nichts gefunden wurde (growberg: sitemap.xml ist leer)
        while (todo or (not found and fallbacks)) and len(seen) < 60:
            sitemap = todo.pop() if todo else fallbacks.pop()
            if sitemap in seen:
                continue
            seen.add(sitemap)
            try:
                content = self.get(sitemap).content
            except Exception as e:
                log.warning("%s: Sitemap %s nicht lesbar: %s", self.name, sitemap, e)
                continue
            if sitemap.endswith(".gz"):
                content = gzip.decompress(content)
            xml = content.decode("utf-8", errors="replace")
            locs = re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", xml)
            if "<sitemapindex" in xml:
                todo.extend(locs)
                continue
            for url in locs:
                # growandstyle führt in der Sitemap auch eine Zweitdomain (simply-grow-systems.de)
                if urlparse(url).netloc.removeprefix("www.") != urlparse(self.home).netloc.removeprefix("www."):
                    continue
                path = urlparse(url).path
                # Shopware 6 hängt die Artikelnummer als eigenen Abschnitt an: /BioTabs-Bio-PK-5-8-1000ml/0634
                segments = [s for s in path.split("/") if s and not re.fullmatch(r"[\d.]+", s)]
                if segments and PRODUCT_RE.search(segments[-1]) and not EXCLUDE_RE.search(path):
                    found.setdefault(path, url)  # dieselbe Seite mit und ohne www. nur einmal
        return sorted(found.values())


# --- Auslesen der Produktseiten -------------------------------------------------


def json_ld_products(soup):
    for tag in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(tag.string or "")
        except json.JSONDecodeError:
            continue
        items = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("@type") == "Product":
                yield item
            elif item.get("@type") == "ProductGroup":  # Varianten als eigene Produkte (head-nature)
                yield from (v for v in item.get("hasVariant", []) if isinstance(v, dict))


def offers_of(item):
    offers = item.get("offers") or []
    return offers if isinstance(offers, list) else [offers]


def is_available(availability):
    return "InStock" in (availability or "") or "LimitedAvailability" in (availability or "")


def unescape(text):
    """Manche Shops kodieren doppelt ("St&amp;uuml;ck")."""
    while text and (decoded := html.unescape(text)) != text:
        text = decoded
    return text


def parse_generic(shop, url, soup):
    """JSON-LD, sonst Microdata, mit festem Preis je Angebot. Eine reine Preisspanne ist kein brauchbares Ergebnis."""
    offers = []
    for item in json_ld_products(soup):
        name = unescape(item.get("name") or "")
        for o in offers_of(item):
            if o.get("price") is not None:
                offers.append(Offer(name, None, item.get("sku"), float(o["price"]), is_available(o.get("availability")), url))
            elif o.get("@type") == "AggregateOffer":
                raise ValueError(f"nur Preisspanne {o.get('lowPrice')}–{o.get('highPrice')} €, keine Größen erkannt")
    if offers:
        return offers
    price = soup.find(attrs={"itemprop": "price"})
    if price and price.get("content"):
        h1 = soup.find("h1")
        sku = soup.find(attrs={"itemprop": "sku"})
        availability = soup.find(attrs={"itemprop": "availability"})
        offers.append(Offer(
            unescape(h1.get_text(" ", strip=True)) if h1 else None,
            None,
            (sku.get("content") or sku.get_text(strip=True)) if sku else None,
            float(price["content"]),
            is_available(availability.get("href") or availability.get("content")) if availability else True,
            url,
        ))
    return offers


def parse_jtl(shop, url, soup):
    """JTL-Shop: jede Größe hat einen Kind-Artikel (data-ref), der über ?a=<id> eine eigene Seite hat."""
    refs = {}
    for el in soup.select(".variation[data-ref]"):
        refs.setdefault(el["data-ref"], el.get("data-original") or el.get("data-title"))
    if not refs:
        return parse_generic(shop, url, soup)
    base = "{0.scheme}://{0.netloc}/".format(urlparse(url))
    offers = []
    for ref, label in refs.items():
        child = BeautifulSoup(shop.get(f"{base}?a={ref}").text, "lxml")
        for o in parse_generic(shop, url, child):
            o.variant = html.unescape(label) if label else None
            offers.append(o)
    return offers


def parse_shoptet(shop, url, soup):
    """Shoptet: ein Offer je Größe (SKU), die Größe steht in den eingebetteten Tracking-Daten."""
    text = str(soup)
    names = {}
    for m in re.finditer(r'"variant":"((?:[^"\\]|\\.)*)","manufacturer":"[^"]*","content_ids":\["((?:[^"\\]|\\.)*)"\]', text):
        variant, sku = (json.loads(f'"{g}"') for g in m.groups())
        names.setdefault(sku, variant)
    h1 = soup.find("h1")
    product = h1.get_text(" ", strip=True) if h1 else None
    offers = []
    for o in soup.find_all(attrs={"itemprop": "offers"}):
        prop = lambda p: (o.find(attrs={"itemprop": p}) or {}).get("content") or (o.find(attrs={"itemprop": p}) or {}).get("href")
        price, sku = prop("price"), prop("sku")
        if price is None:
            continue
        offers.append(Offer(product, names.get(sku), sku, float(price), is_available(prop("availability")), url))
    return offers


def parse_shopify(shop, url, soup):
    """Shopify: <produkt-url>.js liefert alle Varianten mit Titel, Preis in Cent und Verfügbarkeit."""
    data = shop.get(url.split("?")[0].rstrip("/") + ".js").json()
    offers = []
    for v in data.get("variants", []):
        variant = None if v.get("title") == "Default Title" else v.get("title")
        offers.append(Offer(data.get("title"), variant, v.get("sku") or None, v["price"] / 100, bool(v.get("available")), url))
    return offers


def parse_woocommerce(shop, url, soup):
    """WooCommerce: variable Produkte haben alle Varianten als JSON im Formular-Attribut."""
    form = soup.select_one("form.variations_form")
    if not form:
        return parse_generic(shop, url, soup)
    raw = form.get("data-product_variations")
    if not raw or raw == "false":
        raise ValueError("Varianten werden nachgeladen, nicht im HTML")
    # Anzeigetexte der Auswahlfelder, z. B. Wert "1-5-kg" -> "1,5 kg"
    labels = {
        (sel.get("name"), opt.get("value")): opt.get_text(strip=True)
        for sel in form.find_all("select")
        for opt in sel.find_all("option")
        if opt.get("value")
    }
    h1 = soup.select_one("h1.product_title") or soup.find("h1")
    product = unescape(h1.get_text(" ", strip=True)) if h1 else None
    offers = []
    for v in json.loads(raw):
        attrs = v.get("attributes") or {}
        variant = " / ".join(labels.get((k, val), val) for k, val in attrs.items() if val) or None
        offers.append(Offer(product, variant, v.get("sku") or None, float(v["display_price"]), bool(v.get("is_in_stock")), url))
    return offers


def detect_platform(page_html):
    if "shoptet" in page_html:
        return "shoptet"
    if "cdn.shopify.com" in page_html:
        return "shopify"
    if "woocommerce" in page_html:
        return "woocommerce"
    if "jtl" in page_html.lower():
        return "jtl"
    return "generic"


PARSERS = {
    "jtl": parse_jtl,
    "shoptet": parse_shoptet,
    "shopify": parse_shopify,
    "woocommerce": parse_woocommerce,
    "generic": parse_generic,
}


def is_target(product, variant=None):
    if not product or NOT_TARGET_RE.search(product):
        return False
    # Tabletten heißen teils nur "BioTabs" (gruenefreude, pflanzburg: "BIOtabs BioTabs"), Größe steht in der Variante
    if re.fullmatch(r"(?:bio\s*tabs\s*)+", product.strip(), re.I):
        return bool(variant and re.search(r"\d", variant))
    return bool(TARGET_RE.search(product))


def parse_size(variant, product):
    """Liefert (Menge, Einheit) mit Einheit Stück, kg oder l, sonst (None, None).

    Der Artikelname geht vor, weil Shops Variantenbezeichnungen falsch pflegen
    (grow-shop24: Artikel "Silicium Flash, 5000g", Variante "9L").
    """
    # hobbygrow nennt die Variante nur "10", die Einheit ergibt sich aus dem Produkt
    if variant and re.fullmatch(r"\d+", variant.strip()) and re.search(r"tab", product or "", re.I):
        return float(variant), "Stück"
    for name in (product, variant):
        if not name or re.search(r"\b\d{2,}\s*(?:,|oder)\s*\d{2,}", name):  # z. B. "10, 100 oder 400 Stück"
            continue
        matches = SIZE_RE.findall(name)
        if len(matches) != 1:
            continue
        amount, unit = matches[0]
        amount, unit = float(amount.replace(",", ".")), unit.lower()
        if unit.startswith(("st", "tab")):
            return amount, "Stück"
        if unit in ("g", "gr", "gramm"):
            return amount / 1000, "kg"
        if unit == "ml":
            return amount / 1000, "l"
        return amount, {"liter": "l"}.get(unit, unit)
    return None, None


# --- Aktionen und Gutscheine auf der Startseite ----------------------------------

PROMO_RE = re.compile(r"\b(?:code|gutschein|coupon|rabatt|sparen|spare)\b|\d\s*%", re.I)
PROMO_NOISE_RE = re.compile(r"cookie|codeabschnitt|scriptcode|tag manager|speicherdauer|datenschutz|newsletter|gespart|lieferzeit", re.I)
PERCENT_RE = re.compile(r"(?<![\d.,])(\d{1,2})\s*%")  # nicht "15.92%" als 92 % lesen
DISCOUNT_WORD_RE = re.compile(r"\brabatt|\bspar(?:en|e)\b|auf alles|gutschein", re.I)
CODE_RE = re.compile(r"(?i:\b(?:rabatt|gutschein)?code)\s*:?\s*[\"„'»]?([A-Z0-9][A-Z0-9-]{2,19})\b")
SITEWIDE_RE = re.compile(r"auf alles|gesamte[sn]? sortiment|alle artikel|auf den gesamten|sitewide", re.I)


def parse_promos(page_html):
    """Findet Aktionstexte (meist Banner oben) mit Code oder Prozentrabatt."""
    soup = BeautifulSoup(page_html, "lxml")
    for tag in soup(["script", "style", "noscript", "svg"]):
        tag.decompose()
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    segments = [s.strip() for s in re.split(r"[·•✔✓|]|(?<=[.!?])\s", text)]
    # "7% auf alles · Code PP7": Rabatt und Code stehen in zwei Abschnitten
    for i in range(len(segments) - 1):
        if PERCENT_RE.search(segments[i]) and not CODE_RE.search(segments[i]) and CODE_RE.match(segments[i + 1]):
            segments[i] = f"{segments[i]} · {CODE_RE.match(segments[i + 1]).group(0)}"
    promos = {}
    for segment in segments:
        if not (8 < len(segment) < 200) or not PROMO_RE.search(segment) or PROMO_NOISE_RE.search(segment):
            continue
        code = CODE_RE.search(segment)
        percent = PERCENT_RE.search(segment)
        if not code and not (percent and DISCOUNT_WORD_RE.search(segment)):
            continue
        # Auf den Bereich um Rabatt und Code kürzen, Cookie- und Menütexte davor/danach weglassen
        spans = [m.span() for m in (code, percent) if m]
        start, end = min(s for s, _ in spans), max(e for _, e in spans)
        start = segment.rfind(" ", 0, max(0, start - 30)) + 1 if start > 30 else 0
        end = segment.find(" ", end + 25) if segment.find(" ", end + 25) > 0 else len(segment)
        promo = {
            # Reste des Cookie-Banners davor abschneiden ("Dauerhaft zustimmen Jetzt sparen …")
            "text": re.sub(r"^.*\b(?:zustimmen|akzeptieren|ablehnen|konfigurieren)\s+", "", segment[start:end], flags=re.I).strip(" ›*!"),
            "code": code.group(1) if code else None,
            "percent": float(percent.group(1)) if percent else None,
            "sitewide": bool(SITEWIDE_RE.search(segment)),
        }
        key = promo["code"] or promo["text"]
        if key not in promos or (promo["percent"] and not promos[key]["percent"]):
            promos[key] = promo
    return sorted(promos.values(), key=lambda p: (p["code"] is None, not p["sitewide"]))[:5]


# --- Datenbank und Ablauf -------------------------------------------------------


def db_connect():
    con = sqlite3.connect(DB_PATH)
    con.executescript(
        """
        CREATE TABLE IF NOT EXISTS prices (
            id INTEGER PRIMARY KEY,
            checked_at TEXT NOT NULL,
            shop TEXT NOT NULL,
            url TEXT NOT NULL,
            product TEXT,
            variant TEXT,
            sku TEXT,
            price REAL,
            pack_size REAL,
            pack_unit TEXT,
            price_per_unit REAL,
            available INTEGER
        );
        CREATE INDEX IF NOT EXISTS prices_shop_checked ON prices (shop, checked_at);
        CREATE TABLE IF NOT EXISTS errors (
            checked_at TEXT NOT NULL,
            shop TEXT NOT NULL,
            url TEXT NOT NULL,
            error TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS product_urls (
            shop TEXT NOT NULL,
            url TEXT NOT NULL,
            discovered_at TEXT NOT NULL,
            PRIMARY KEY (shop, url)
        );
        CREATE TABLE IF NOT EXISTS promos (
            checked_at TEXT NOT NULL,
            shop TEXT NOT NULL,
            text TEXT NOT NULL,
            code TEXT,
            percent REAL,
            sitewide INTEGER
        );
        CREATE TABLE IF NOT EXISTS runs (
            checked_at TEXT NOT NULL,
            shop TEXT NOT NULL,
            pages INTEGER,
            offers INTEGER,
            errors INTEGER,
            warning TEXT
        );
        """
    )
    return con


def product_urls(con, shop, force):
    rows = con.execute("SELECT url, discovered_at FROM product_urls WHERE shop = ?", (shop.name,)).fetchall()
    fresh = rows and datetime.fromisoformat(min(r[1] for r in rows)) > datetime.now(timezone.utc) - DISCOVERY_MAX_AGE
    if fresh and not force:
        return [r[0] for r in rows]
    return None  # neue Suche nötig


def scrape_shop(shop, urls):
    """Läuft im eigenen Thread. Gibt (urls, offers, errors, promos) zurück, schreibt nichts in die DB."""
    try:
        promos = parse_promos(shop.get(shop.home).text)
    except Exception as e:
        log.warning("%s: Startseite für Aktionen nicht lesbar: %s", shop.name, e)
        promos = []
    if urls is None:
        urls = shop.discover_product_urls()
        log.info("%s: %d Produkt-URLs gefunden", shop.name, len(urls))
    offers, errors = [], []
    for i, url in enumerate(urls, 1):
        log.info("%s: Seite %d/%d %s", shop.name, i, len(urls), url)
        try:
            page = shop.get(url).text
            soup = BeautifulSoup(page, "lxml")
            found = PARSERS[detect_platform(page)](shop, url, soup)
            if not found:
                raise ValueError("kein Preis gefunden")
            offers.extend(found)
        except Exception as e:
            errors.append((url, str(e)))
    return urls, offers, errors, promos


def health_warning(con, shop, offers, errors, pages):
    if pages == 0:
        return "keine Produktseiten gefunden"
    if not offers:
        return "keine Preise gefunden – Parser defekt oder Shop blockiert"
    previous = con.execute(
        "SELECT offers FROM runs WHERE shop = ? AND offers > 0 ORDER BY checked_at DESC LIMIT 1", (shop,)
    ).fetchone()
    if previous and len(offers) < previous[0] * 0.5:
        return f"nur {len(offers)} statt bisher {previous[0]} Preise"
    if errors > pages / 2:
        return f"{errors} von {pages} Seiten fehlerhaft"
    return None


def run(shop_names=None, force_discovery=False):
    con = db_connect()
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    shops = [Shop(n, u) for n, u in SHOPS.items() if not shop_names or n in shop_names]
    jobs = {s.name: product_urls(con, s, force_discovery) for s in shops}

    with ThreadPoolExecutor(max_workers=len(shops) or 1) as pool:
        results = dict(zip([s.name for s in shops], pool.map(lambda s: scrape_shop(s, jobs[s.name]), shops)))

    for name, (urls, found, errors, promos) in results.items():
        con.executemany(
            "INSERT INTO promos VALUES (?,?,?,?,?,?)",
            [(now, name, p["text"], p["code"], p["percent"], p["sitewide"]) for p in promos],
        )
        for p in promos:
            log.info("%s: Aktion: %s", name, p["text"])
        if jobs[name] is None:
            con.execute("DELETE FROM product_urls WHERE shop = ?", (name,))
            con.executemany("INSERT INTO product_urls VALUES (?,?,?)", [(name, u, now) for u in urls])
        # Übersichtsseiten führen zu denselben Kind-Artikeln wie die Produktseite
        offers = list({(o.sku or o.product, o.variant): o for o in found if is_target(o.product, o.variant)}.values())
        skipped = sorted({o.product or "?" for o in found if not is_target(o.product, o.variant)})
        if skipped:
            log.info("%s: nicht auf der Produktliste: %s", name, "; ".join(skipped))
        for o in offers:
            amount, unit = parse_size(o.variant, o.product)
            con.execute(
                "INSERT INTO prices (checked_at, shop, url, product, variant, sku, price, pack_size, pack_unit, price_per_unit, available) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (now, name, o.url, o.product, o.variant, o.sku, o.price, amount, unit, round(o.price / amount, 4) if amount else None, o.available),
            )
        con.executemany("INSERT INTO errors VALUES (?,?,?,?)", [(now, name, u, e) for u, e in errors])
        warning = health_warning(con, name, offers, len(errors), len(urls))
        con.execute("INSERT INTO runs VALUES (?,?,?,?,?,?)", (now, name, len(urls), len(offers), len(errors), warning))
        level = logging.WARNING if warning else logging.INFO
        log.log(level, "%s: %d Seiten, %d Preise, %d Fehler%s", name, len(urls), len(offers), len(errors), f" – {warning}" if warning else "")
    con.commit()
    con.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--discover", action="store_true", help="Produktsuche über die Sitemaps erzwingen")
    parser.add_argument("--shop", action="append", help="nur diesen Shop abrufen")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    run(args.shop, args.discover)
