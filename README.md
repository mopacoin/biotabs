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
- **Tiefstpreis bisher** je Produkt und Größe über alle Shops und alle Läufe, gezählt werden nur lieferbare
  Angebote. Ist das aktuelle Bestangebot so günstig wie der Tiefstpreis, steht dort *Tiefstpreis*.
- **Tiefstpreis-Alarm** oben auf der Seite: Wurde der bisherige Tiefstpreis in den letzten 7 Tagen
  (`ALARM_DAYS` in `app.py`) unterboten und ist das aktuelle Bestangebot noch so günstig, erscheint es dort.
  Die erste Beobachtung eines Produkts löst keinen Alarm aus.
- **Preisverlauf**: Der Button *Verlauf* neben jedem Preis zeigt den Preis dieses Angebots über alle Läufe,
  mit Tiefst-/Höchstpreis, ausverkauften Läufen und den Preisänderungen als Tabelle.
- **Zustand der Läufe** eingeklappt am Seitenende, bei Warnungen automatisch offen.

- **Einzeln inkl. Versand**: was ein Artikel kostet, wenn man nur ihn bestellt.
- **Warenkorb-Rechner** (`/#warenkorb`): Produkte, Größen und Mengen wählen; gesucht wird die insgesamt
  günstigste Aufteilung auf einen oder mehrere Shops. Berücksichtigt werden Versandkosten nach Gewicht und
  Warenwert, versandkostenfrei-Grenzen, Mindestbestellwerte und Gutscheine, die für das ganze Sortiment gelten.
  Die Suche ist exakt (geprüft gegen eine vollständige Suche über alle Zuordnungen); je Produkt werden die
  10 günstigsten Shops betrachtet. Der Warenkorb bleibt im Browser gespeichert.
- **Shops: Versand und Aktionen**: Versandkosten mit Quelle und die bei jedem Lauf erkannten Aktionen.

JSON-Schnittstelle: `/api/angebote?produkt=Bio%20PK%205-8&groesse=1%20l`, `/api/bestpreise`,
`/api/versand`, `/api/aktionen`, `/api/tiefstpreise` und `/api/verlauf?shop=…&product=…&variant=…`.

## Versandkosten und Aktionen

- **Versandkosten** stehen in `shops.py` (`SHIPPING`), von Hand aus den Versandseiten der Shops übernommen
  (Stand 19.10.2026). Sie ändern sich selten, sollten aber gelegentlich geprüft werden. Bei hobbygrow,
  grungarten und chiligrow nennt der Shop keine Beträge; dort wird pauschal mit 8 € gerechnet
  (`DEFAULT_SHIPPING`), auf der Seite als geschätzt markiert. Das gilt auch für neue Shops ohne Eintrag.
- **Versandgewicht** wird aus der Packungsgröße geschätzt (Tablette ca. 21 g, Flüssigkeit ca. 1,1 kg/l).
  Das betrifft nur Shops mit Gewichtsstaffeln.
- **Aktionen** liest der Scraper bei jedem Lauf von der Startseite (Banner-Texte mit Code oder Prozent-Rabatt).
  In den Warenkorb-Rechner fließen nur Codes ein, die laut Text "auf alles" gelten. Bedingungen wie
  ausgenommene Marken oder Mindestwerte kann die Erkennung nicht prüfen.

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
