# Network Search

Een lichte, zelfgehoste zoekmachine voor je LinkedIn-netwerk. Zoek op naam, functie, werkgever en de inhoud van LinkedIn-gesprekken. Gebouwd met **FastAPI**, **SQLite FTS5** en Docker.

> **Huidige versie: v0.5.0** — trefwoordzoeken met Nederlandstalige en Engelstalige synoniemen. Nog geen AI/semantische zoekmachine.

## Mogelijkheden

- **Instagram ZIP-import:** officiële JSON-export in één keer uploaden. Alleen volgers, gevolgde accounts en normale inbox-tekstberichten. Geen message requests, broadcasts, gesynchroniseerde telefooncontacten of media.
- **Instagram doorzoeken:** accounts en inbox-tekstberichten verschijnen afzonderlijk bij zoekresultaten. Instagram-accounts worden niet automatisch aan LinkedIn-personen gekoppeld.


- **LinkedIn-connecties importeren** uit `Connections.csv` (naam, functie, werkgever, profiel-URL).
- **Berichten importeren** uit `messages.csv`, inclusief doorzoekbare inhoud.
- **Werkhistorie bijhouden:** bij een volgende LinkedIn-import worden wijzigingen in werkgever en/of functie opgeslagen, zonder de eerdere vermelding te wissen. De datum is de eerste waarneming in een export, **niet** de echte startdatum van een baan. Ontbrekende velden worden niet als wijziging geteld.
- **Tijdlijn per contact:** het aantal geïmporteerde LinkedIn-berichten per jaar, plus waargenomen functiewijzigingen. Datums van vacatures/werkgevers zijn de eerste waarneming in een export.
- **Netwerkactiviteit:** een overzicht van LinkedIn-berichten per jaar en een lijst van contacten met minstens drie gekoppelde berichten, zonder herkend LinkedIn-contact in de laatste twee kalenderjaren. Dit is geen objectieve maat voor de sterkte van een relatie.
- **Contactgeschiedenis bekijken:** klik op *Gesprekken bekijken (6)* om gekoppelde berichten te openen.
- **Slimmer zoeken:** bekende termen worden uitgebreid met synoniemen in het Nederlands en Engels. Bijvoorbeeld `IT manager overheid` zoekt ook naar verwante functietitels en overheidsorganisaties. De zoekopdracht combineert begrippen met AND; synoniemen binnen een begrip met OR.
- **Gerangschikte resultaten** op basis van full-text-relevantie.
- **CSV-import onderaan de pagina** in een inklapbaar blok.
- **Versienummer in de footer** en link naar GitHub.
- Herhaald importeren is mogelijk; berichten worden op inhoudelijke rij-hash gededupliceerd.

De regels voor zoektermuitbreiding staan in [app/search.py](app/search.py). Ze zijn bewust beperkt om misleidende matches te beperken: een functietitel bewijst niet dat iemand een specifieke vaardigheid beheerst.

## Installeren

```sh
git clone https://github.com/MartinZwolle/network-search.git
cd network-search
docker compose up -d --build
```

Open `http://<server-ip>:8098` vanaf je eigen netwerk. Wanneer de host via Tailscale/MagicDNS bereikbaar is, kan bijvoorbeeld `http://homelab:8098` werken.

**Let op:** de standaard Compose-poort is momenteel `8098:8080` en luistert daardoor op alle hostinterfaces. Als je alleen toegang via een SSH-tunnel wilt, wijzig dan de poort in `compose.yaml` naar `127.0.0.1:8098:8080`.

### Bijwerken vanuit Git / Komodo

Omdat de Python-code tijdens het bouwen in de Docker-image wordt gekopieerd, is alleen een Git Pull en Deploy niet voldoende voor codewijzigingen. Gebruik **Pull → Rebuild → Deploy** (of het equivalent in je Komodo-versie). De lokale database blijft bewaard in de volume-mount `./data:/data`, zolang dezelfde persistente map gebruikt wordt.

### Importeren

Open de app en klap onder de zoekresultaten **CSV importeren** uit. Upload de bestanden *apart*:

1. `Connections.csv`
2. `messages.csv`

Voor Instagram kun je de oorspronkelijke Meta ZIP (JSON-formaat) in hetzelfde importblok uploaden (max. 80 MB). Een nieuwe Instagram-import dedupliceert berichten en werkt volgstatussen bij. Alleen tekstberichten worden opgenomen. De ZIP wordt niet als bestand opgeslagen; de inhoud wordt verwerkt in SQLite. De import negeert bewust berichtverzoeken en gesynchroniseerde contacten.

De importer ondersteunt gebruikelijke LinkedIn-CSV-encodings; bestanden mogen maximaal **25 MB per upload** zijn. De ruwe uploadbestanden worden niet als losse bestanden opgeslagen. Geïmporteerde persoonsgegevens en berichtinhoud staan in `data/network.db` op de Docker-host.

Bij een upgrade vanaf v0.3.1 naar v0.3.2 worden reeds geïmporteerde werkgevers en functies als eerste bekende observatie geregistreerd. Maak vóór een update of nieuwe import een back-up van `data/network.db`. Opnieuw uploaden van dezelfde export maakt geen extra werkhistorie-items aan.

Contacten zonder profiel-URL worden op dit moment niet geïmporteerd; koppeling tussen contacten en gesprekken gebeurt op basis van LinkedIn-profiel-URL. Groepsgesprekken kunnen meerdere contacten bevatten.

## Privacy en beveiliging

**Deze versie heeft geen login, autorisatie of bescherming tegen ongewenste uploads. Stel de app niet rechtstreeks aan het publieke internet bloot.** De standaardpoort is toegankelijk voor apparaten die de Docker-host op dat adres kunnen bereiken. Gebruik firewallregels, een vertrouwd thuisnetwerk, een Tailscale-only binding of een authenticerende reverse proxy.

`data/`, `*.csv`, `*.db` en `.env` staan in `.gitignore`. **Commit nooit exports, de SQLite-database, persoonlijke gesprekken of wachtwoorden naar GitHub.** Zorg voor passende back-ups en toegangsrechten op de datamap.

## Roadmap

- [x] LinkedIn-contacten en berichten doorzoeken
- [x] Contacten koppelen aan LinkedIn-berichten
- [x] Berichtenaantal per contact en contactgeschiedenis
- [x] NL/EN-synoniemen en relevantere sortering
- [x] Werkgever- en functiehistorie vastleggen bij nieuwe LinkedIn-exports
- [x] Basis-relatieanalyse: frequentie per jaar en laatste herkende LinkedIn-bericht
- [ ] Uitgebreide relatieanalyse: wederkerigheid, filters en selectie voor Monica
- [x] Instagram: volgers, gevolgde accounts en inbox-tekst importeren
- [ ] Facebook-export ondersteunen
- [ ] Accounts van dezelfde persoon veilig koppelen (met handmatige bevestiging)
- [ ] Monica-integratie voor notities, contactmomenten en herinneringen
- [ ] Verdere zoekverbeteringen, eventueel optionele lokale semantische zoekfunctie

## Techniek

- Python / FastAPI
- SQLite + FTS5
- HTML/CSS
- Docker Compose

Bijdragen en verbeteringen zijn welkom.
