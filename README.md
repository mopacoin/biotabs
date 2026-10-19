# Biotabs Preis-Tracker

Ruft zweimal täglich die Preise aller BioTabs-Produkte (Düngetabletten, Bio PK 5-8, Silicium Flash,
Bactrex, Orgatrex, Startrex, Mycotrex) in jeder Größe bei deutschen Shops ab und zeigt sie auf
einer lokalen Webseite.

## Funktionsweise

- **Produktsuche** über die Sitemaps der Shops, höchstens einmal pro Woche (`--discover` erzwingt sie).
- **Preise je Größe** über Adapter, die das Shopsystem automatisch erkennen:
  - *JTL-Shop*: jede Größe ist ein Kind-Artikel (`data-ref`), dessen Seite über `?a=<id>` abgerufen wird.
  - *Shoptet*: ein `offers`-Element je Größe, der Größenname steht in den eingebetteten Tracking-Daten.
  - *Shopify*: `<produkt-url>.js` liefert alle Varianten als JSON.
  - *WooCommerce*: alle Varianten stehen als JSON im Attribut `data-product_variations`.
  - Sonst: JSON-LD (auch `ProductGroup` mit `hasVariant`) bzw. Microdata. Eine reine Preisspanne
    ("ab 9,90 €") wird als Fehler gemeldet, nicht gespeichert.
- **Produktfilter** auf Namensebene: nur Düngetabletten, Bio PK 5-8, Silicium Flash, Bactrex,
  Orgatrex, Startrex, Mycotrex. Sets, Guerilla Tabs, Boom Boom Spray, PK Booster usw. fallen raus.
- **Grundpreis** in €/Stück, €/kg oder €/l, damit Größen und Shops vergleichbar sind.
- **Shops parallel**, je Shop eine Anfrage alle 5 Sekunden, `robots.txt` wird beachtet.
- **Zustandsprüfung**: Liefert ein Shop keine Preise oder weniger als die Hälfte des letzten Laufs,
  steht das als Warnung im Log und oben auf der Webseite.

Neuer Shop: Eintrag in `shops.py` ergänzen. Dort stehen auch die entfernten Shops mit Grund.

## Webseite

- **Günstigste Angebote**: je Produkt und Größe der billigste verfügbare Shop, mit Grundpreis und
  Abstand zum Zweitbilligsten.
- **Filter** über Produkt-Chips und Formular. Jede Ansicht ist eine eigene URL und lässt sich als
  Lesezeichen speichern, z. B.
  - `/?produkt=Bio+PK+5-8` – alle Bio-PK-Angebote, günstigste zuerst
  - `/?produkt=Bio+PK+5-8&groesse=1+l&verfuegbar=true` – nur lieferbare 1-Liter-Flaschen
  - `/?produkt=Düngetabletten&sortierung=grundpreis` – Tabletten nach Preis pro Stück, alle Packungsgrößen
- **Preisänderungen** gegenüber dem vorigen Lauf als ▲/▼ neben dem Preis.
- **Zustand der Läufe** eingeklappt am Seitenende, bei Warnungen automatisch offen.

JSON-Schnittstelle mit denselben Filtern: `/api/angebote?produkt=Bio%20PK%205-8&groesse=1%20l`
und `/api/bestpreise`.

## Installation auf dem Raspberry Pi

```bash
cd ~
# Projektordner auf den Pi kopieren, z. B. per scp, nach ~/biotabs-tracker
cd ~/biotabs-tracker
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```

In `scraper.py` bei `USER_AGENT` eine Kontaktadresse eintragen.

Ersten Lauf starten und prüfen:

```bash
.venv/bin/python scraper.py --discover
```

Die Dateien in `deploy/` gehen von Benutzer `pi` und `/home/pi/biotabs-tracker` aus. Bei anderem
Benutzer die Pfade anpassen, dann:

```bash
sudo cp deploy/*.service deploy/*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now biotabs-scrape.timer biotabs-web.service
```

Die Webseite läuft dann unter `http://127.0.0.1:8000` auf dem Pi. Für Zugriff aus dem Heimnetz in
`deploy/biotabs-web.service` `--host 127.0.0.1` durch `--host 0.0.0.0` ersetzen. Nicht ins Internet
freigeben: Die Seite hat keinen Login.

Logs: `journalctl -u biotabs-scrape.service`
