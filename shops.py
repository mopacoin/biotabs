"""Shops, die abgefragt werden. Neuer Shop: Zeile ergänzen, Plattform wird automatisch erkannt."""

SHOPS = {
    # JTL-Shop
    "grow-shop24": "https://www.grow-shop24.de/",
    "hobbygrow": "https://hobbygrow.de/",
    "bloomtech": "https://bloomtech.de/",
    "greenlight-shop": "https://www.greenlight-shop.de/",
    "puraplants": "https://www.puraplants.de/",
    "growmart": "https://www.growmart.de/",
    "plantyme": "https://plantyme.de/",
    "world-of-grow": "https://world-of-grow.de/",
    "plantplanet": "https://www.plantplanet.de/",
    # Shoptet
    "higarden": "https://www.higarden.de/",
    "grungarten": "https://www.grungarten.de/",
    # Shopify
    "gogrow": "https://gogrow.de/",
    "grow-factory": "https://grow-factory.de/",
    "grow-max": "https://www.grow-max.de/",
    # WooCommerce
    "pflanzburg": "https://pflanzburg.de/",
    "gruenefreude": "https://gruenefreude.com/",
    "chiligrow": "https://chiligrow.de/",
    # Sonstige (JSON-LD/Microdata)
    "growandstyle": "https://www.growandstyle.de/",
    "growversand": "https://growversand.de/",
    "growshop.de": "https://www.growshop.de/",
    "stargrow": "https://stargrow.de/",
    "head-nature": "https://www.head-nature.com/",  # englischsprachig, Plamundo GmbH
}

# Entfernt, weil sie automatische Abrufe blocken oder sich nicht sauber auslesen lassen:
# eden-grow.de (401), growland.net (403), schiller-germany.de (kein Preis im HTML),
# greentradingxxl.com (403, robots.txt verbietet alles), growxpert.de (nicht erreichbar),
# growberg.de (Sitemap liefert nur die Startseite), grow-guru.com (leere Sitemap),
# sepp-hanf.com (Sitemap enthält keine Produkte)
