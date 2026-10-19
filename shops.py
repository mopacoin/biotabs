"""Shops, die abgefragt werden, und ihre Versandkosten.

Neuer Shop: Zeile in SHOPS ergänzen (Plattform wird automatisch erkannt) und Versandkosten in SHIPPING eintragen.
"""

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

# Pauschale für Shops, die keine Versandkosten veröffentlichen, und für Shops ohne Eintrag in SHIPPING
DEFAULT_SHIPPING = 8.00

# Versandkosten innerhalb Deutschlands, Standardpaket, Stand 19.10.2026.
#   weight:     [(bis kg, Kosten), ...] – letzte Stufe gilt auch darüber
#   by_value:   [(ab Bestellwert, Kosten), ...] – überschreibt weight ab diesem Warenwert
#   free_from:  versandkostenfrei ab diesem Warenwert (None = nie)
#   min_order:  Mindestbestellwert
#   estimated:  True, wenn der Shop keine Beträge veröffentlicht (dann DEFAULT_SHIPPING)
SHIPPING = {
    "grow-shop24": {"weight": [(31.5, 5.90)], "free_from": 100, "source": "https://www.grow-shop24.de/versandinformationen"},
    "hobbygrow": {"weight": [(31.5, DEFAULT_SHIPPING)], "free_from": 149, "estimated": True,
                  "note": "Betrag nur im Warenkorb sichtbar", "source": "https://hobbygrow.de/Versandinformationen"},
    "bloomtech": {"weight": [(0.8, 3.90), (31.5, 7.90)], "free_from": 99, "source": "https://bloomtech.de/Versand-und-Zahlung_1"},
    "greenlight-shop": {"weight": [(1, 4.95), (29, 5.90), (59, 11.80)], "free_from": 150,
                        "source": "https://www.greenlight-shop.de/Versandinformationen"},
    "puraplants": {"weight": [(0.03, 3.95), (31.5, 5.95)], "free_from": 99, "source": "https://www.puraplants.de/Versandinformationen"},
    "growmart": {"weight": [(31.5, 6.90)], "free_from": 100, "source": "https://www.growmart.de/Versandkosten"},
    "plantyme": {"weight": [(5, 4.90), (20, 6.90), (31.5, 8.90)], "free_from": 59, "source": "https://plantyme.de/Versand-Lieferung"},
    "world-of-grow": {"weight": [(31.5, 6.90)], "free_from": 75, "source": "https://world-of-grow.de/Versandinformationen"},
    "plantplanet": {"weight": [(31.5, 6.90)], "free_from": 60, "source": "https://www.plantplanet.de/Versandinformation"},
    "higarden": {"weight": [(30, 7.95)], "by_value": [(100, 4.95)], "free_from": 200, "source": "https://www.higarden.de/delivery/"},
    "grungarten": {"weight": [(31.5, DEFAULT_SHIPPING)], "free_from": None, "estimated": True,
                   "note": "keine Versandseite gefunden, Versand aus Tschechien", "source": "https://www.grungarten.de/"},
    "gogrow": {"weight": [(31.5, 5.90)], "free_from": 300, "source": "https://gogrow.de/pages/zahlung-und-versand"},
    "grow-factory": {"weight": [(31.5, 5.90)], "free_from": 100, "source": "https://grow-factory.de/pages/versand"},
    "grow-max": {"weight": [(2, 4.90), (31.5, 5.90)], "free_from": 99,
                 "source": "https://www.grow-max.de/pages/versand-und-zahlungsinformationen"},
    "pflanzburg": {"weight": [(31.5, 7.90)], "free_from": 75, "source": "https://pflanzburg.de/versandarten/"},
    "gruenefreude": {"weight": [(20, 7.50), (40, 15.00)], "free_from": None, "source": "https://gruenefreude.com/versand/"},
    "chiligrow": {"weight": [(31.5, DEFAULT_SHIPPING)], "free_from": None, "estimated": True,
                  "note": "Versandseite ohne Beträge", "source": "https://chiligrow.de/versandarten/"},
    "growandstyle": {"weight": [(31, 5.50)], "free_from": 75,
                     "source": "https://www.growandstyle.de/allgemeine-informationen/versandkosten/"},
    "growversand": {"weight": [(31.5, 7.90)], "free_from": 99,
                    "note": "Betrag vom Schwester-Shop cludi.com", "source": "https://cludi.com/Informationen/Zahlung-und-Versand/"},
    "growshop.de": {"weight": [(31.5, 6.90)], "free_from": 100, "min_order": 25,
                    "source": "https://www.growshop.de/Zahlung-Versand:_:1.html"},
    "stargrow": {"weight": [(1, 4.90), (2, 5.50), (4, 5.90), (10, 9.90), (14, 14.90), (31, 17.90)], "free_from": None,
                 "source": "https://stargrow.de/Infos/Versand-Zahlung/"},
    "head-nature": {"weight": [(25, 4.99), (50, 9.98)], "free_from": 50, "source": "https://www.head-nature.com/Versandinformationen"},
}


def estimate_weight(amount, unit):
    """Grobes Versandgewicht in kg aus der Packungsgröße (Tablette ca. 21 g, Flüssigkeit ca. 1,1 kg/l)."""
    if amount is None:
        return 0.5
    if unit == "Stück":
        return amount * 0.022 + 0.05
    if unit == "l":
        return amount * 1.1 + 0.05
    return amount * 1.05 + 0.05  # kg


def shipping_cost(shop, subtotal, weight):
    """Versandkosten für einen Warenkorb bei diesem Shop; None, wenn der Mindestbestellwert fehlt."""
    rule = SHIPPING.get(shop, {"weight": [(31.5, DEFAULT_SHIPPING)], "free_from": None, "estimated": True})
    if subtotal < rule.get("min_order", 0):
        return None
    if rule.get("free_from") is not None and subtotal >= rule["free_from"]:
        return 0.0
    for from_value, cost in sorted(rule.get("by_value", []), reverse=True):
        if subtotal >= from_value:
            return cost
    for max_kg, cost in rule["weight"]:
        if weight <= max_kg:
            return cost
    return rule["weight"][-1][1]
