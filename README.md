# Farley File

![Farley File-logo](app/static/farley-logo.svg)

Een lichte, zelfgehoste zoekmachine voor je persoonlijke netwerk over meerdere sociale platforms. Zoek op naam, functie, werkgever en de inhoud van LinkedIn-gesprekken. Gebouwd met **FastAPI**, **SQLite FTS5** en Docker.

> **Huidige versie: v0.12.0** — trefwoordzoeken met Nederlandstalige en Engelstalige synoniemen. Nog geen AI/semantische zoekmachine.

## Historische Twitter-import (v0.12.0)

Farley File accepteert de **originele Twitter ZIP-export** van maximaal 100 MB. De importer leest uitsluitend `account.js`, `tweets.js`, `following.js`, `follower.js` en `direct-messages.js` uit de `data/` map. Media, advertenties, telefooncontacten en overige exportbestanden worden genegeerd.

- Numerieke Twitter-account-ID's blijven leidend; gebruikersnamen worden als **historisch waargenomen aliassen** bewaard, ook als een account inmiddels verdwenen of hernoemd is.
- Tweets, replies, vermeldingen en privéberichten worden met originele tijdstippen opgeslagen en kunnen worden doorzocht via **Twitter-archief**.
- De activiteitspagina toont Twitter-tweets en Twitter-DM's afzonderlijk per jaar.
- Nieuwe Twitter-identiteiten worden **niet automatisch aan LinkedIn, Instagram of Facebook gekoppeld**. Via het persoonsdossier kan de gebruiker zelf op account-ID koppelen.
- Import is bedoeld om herhaalbaar te zijn: vaste tweet- en DM-ID's voorkomen duplicaten.
- Verwijderde Twitter-accounts blijven als historische account-ID bewaard, ook zonder bekende gebruikersnaam.
- Bij tweets bevat de export vooral **je eigen kant van het publieke gesprek**; suggereer geen volledige gesprekken met anderen. Bij DM's bevat de export wel beide kanten voor zover aanwezig.
- **Privacy:** houd de originele ZIP en de SQLite-database lokaal en beveiligd. De applicatie biedt nog geen aparte toegangsrechten per bericht.
- De implementatie bevat unit tests in `tests/test_twitter.py`. **Nog niet op de homelab-installatie uitgevoerd.**

## Netwerkactiviteit over alle platforms (v0.11.1)

De pagina **Netwerkactiviteit** combineert nu historische LinkedIn-, Instagram- en Facebook-tekstberichten. Filter per platform, bekijk berichten per jaar en open de tabel met jaartotalen per bron. De lijst *Contacten om opnieuw te bekijken* combineert gekoppelde profielen op basis van herleidbare berichtrecords. Afzenders zonder betrouwbare Instagram-identiteit worden wel meegeteld in de algemene statistiek, maar niet aan een persoonsprofiel gekoppeld. Facebook-groepsberichten worden als groepsactiviteit gemarkeerd.

**Let op:** laatste *geregistreerde* bericht is niet hetzelfde als het laatste echte contact, en de importhistorie van de platformen heeft verschillende dekkingen. Twitter kan later worden toegevoegd zonder de LinkedIn-geschiedenis te vervangen.

## Slimmere koppelvoorstellen (v0.11.0)

Op **Mogelijke koppelingen** worden naast de bestaande LinkedIn/Instagram-voorstellen ook voorstellen tussen Facebook, Instagram, LinkedIn en handmatig aangemaakte personen getoond. De aanwijzingen zijn transparant: exact gelijke namen (ongevoelig voor accenttekens), gebruikersnaam die overeenkomt met de naam, of sterk gelijkende namen mét dezelfde werkgever; gedeelde netwerktags geven extra context maar zijn nooit op zichzelf voldoende bewijs.

- Elk voorstel bevat de **reden** en links naar beide profielen.
- Samenvoegen gebeurt **uitsluitend na expliciete bevestiging**. Afwijzingen worden opgeslagen en blijven na herimport bestaan.
- Reeds gekoppelde accounts worden niet opnieuw voorgesteld; twee verschillende LinkedIn-profielen of Facebook-identiteiten worden niet als veilige automatische samenvoeging aangeboden.
- Namen alleen bewijzen niets; ga bij twijfel niet samenvoegen. Een samenvoeging is nog niet met één klik omkeerbaar.
- De vergelijking gebruikt alleen namen, gebruikersnamen, werkgever en netwerktags; geen privéberichtinhoud. Handmatige opmerkingen/tags/werkhistorie blijven bij samenvoegen behouden.
- Regressietests in `tests/test_smart_matches.py`; **nog op de homelab-installatie te valideren**.

## Facebook-import (v0.10.0, nog te testen op homeserver)

- **Import vanuit JSON-ZIP:** de Facebook-export wordt lokaal verwerkt. De importer kijkt alleen naar `friends/your_friends.json` en `inbox/<thread>/message_*.json`, waarbij een extra bovenliggende map geen probleem is.
- **Vrienden en gesprekken:** de vriendenlijst en de namen van gespreksdeelnemers worden als afzonderlijke Facebook-identiteiten opgeslagen; alle beschikbare tekstberichten zijn doorzoekbaar. Foto's, video's en andere media worden niet geïmporteerd. Bijlagen worden niet opgeslagen.
- **Gesprekken per profiel:** Facebook-personen tonen betrokken gesprekken en groepsgesprekken. Vanuit zoekresultaten kun je ook direct een gesprek openen.
- **Accountkoppeling:** Facebook-profielen worden **nooit automatisch** samengevoegd met bestaande LinkedIn-/Instagram-profielen op basis van een naam. Op de persoonspagina kan een geïmporteerde Facebook-identiteit handmatig aan een andere persoon worden gekoppeld.
- **Herhaalbaar:** herhaalde imports slaan identieke tekstberichten niet opnieuw op en raken handmatig toegevoegde gegevens niet.
- **Beperkingen:** Facebook geeft vaak geen betrouwbare unieke profiel-ID in de export. Personen met exact dezelfde naam kunnen daarom één Facebook-naamidentiteit delen; controleer samenvoegingen altijd zelf. Sommige berichten kunnen enkel uit media of verwijderde inhoud bestaan en worden dan overgeslagen. Deze versie is nog niet op de echte homeserver getest.
- **Omvang:** maximaal 128 MB ZIP; als het oorspronkelijke archief groter is, maak dan een kleinere ZIP of verwijder uitsluitend de mediabestanden uit een kopie. De originele export hoeft niet in de repository of database.

## Berichten: doorklikken naar personen (v0.9.x)

- In de LinkedIn-zoekresultaten is de afzender aanklikbaar **als de profiel-URL van de afzender betrouwbaar overeenkomt met een geïmporteerd contact**. De link opent de permanente `/person/<id>`-pagina.
- Afzenders zonder herkenbare LinkedIn-profiel-URL blijven gewone tekst; op naam alleen wordt nooit een koppeling gegokt. Instagram-inboxberichten worden pas gekoppeld als de export daarvoor voldoende betrouwbare accountgegevens bevat.

## Dubbele personen voorkomen en beheren (v0.9.x)

- Bij handmatig toevoegen controleren we eerst of er al een persoon met **dezelfde volledige naam** bestaat. Je krijgt bestaande profielen te zien en kunt teruggaan, een bestaand profiel openen of bewust toch een nieuw profiel maken. Dit is alleen een suggestie: personen met dezelfde naam zijn niet automatisch dezelfde persoon.
- Op een **los, handmatig aangemaakt profiel** verschijnen bestaande personen met exact dezelfde naam als voorstel voor **Samenvoegen**. Samenvoegen vraagt bevestiging, bewaart handmatige context, tags, functies en Obsidian-notities, en houdt een oude profiel-URL als redirect bruikbaar.
- Je kunt ook een **handmatig profiel verwijderen**, inclusief de daarbij ingevulde gegevens, na expliciete bevestiging. Geïmporteerde of gekoppelde sociale profielen zijn niet via deze actie te verwijderen. Maak vóór wijzigingen in profielen altijd een databaseback-up.
- De dubbele-namencontrole is voorlopig beperkt tot gelijke namen, afgezien van hoofdletters en spaties. Andere spellingen, naamswijzigingen en afkortingen kunnen nog als twee afzonderlijke personen voorkomen.

## Handmatige personen en werkhistorie (v0.9.0)

- **Personen zonder socials:** maak op de startpagina een nieuw profiel met alleen een naam. Het krijgt meteen een permanent `/person/<id>`-adres. Het profiel is op naam te vinden; later kun je via de profielpagina een bestaand, al geïmporteerd LinkedIn- of Instagram-account expliciet aan dezelfde persoon koppelen.
- **Weergavenaam:** pas de naam van een persoon onafhankelijk van de LinkedIn- of Instagram-export aan; ook deze handmatig ingevoerde naam blijft behouden.
- **Functies en banen:** voeg zelfstandig banen toe (uit het verleden of de toekomst), met functietitel, werkgever en optionele echte begin- en einddatum. Je kunt zelf toegevoegde banen ook wijzigen of verwijderen.
- **Geïmporteerde LinkedIn-functies corrigeren:** bewerken schrijft een afzonderlijke correctie in `farley_job_overrides`. De oorspronkelijke waarneming in `employment_history` blijft onaangetast. Een latere export kan nieuwe waarnemingen toevoegen, maar wist of overschrijft jouw correcties niet. Een eerste waarnemingsdatum is geen bekende startdatum.
- **Strikte scheiding bronnen:** persoonlijke notities, netwerktags, Obsidian-links, handmatig aangemaakte personen, eigen functieregels en geïmporteerde-correcties staan in aparte tabellen en worden niet door LinkedIn/Instagram-imports geüpdatet. Bij expliciete samenvoegingen worden bestaande handmatige velden meegenomen.
- **Voor upgrade:** maak een consistente SQLite-back-up van `data/network.db`. Alle nieuwe tabellen worden toegevoegd bij het starten; de app is nog in de 0.x-fase en nieuwe workflows moeten eerst met een testprofiel worden nagelopen.

## Logo

Het Farley File-logo staat als schaalbare SVG in `app/static/farley-logo.svg` en verschijnt naast de titel op de startpagina, op persoonspagina’s en als browsericoon. Het bestand is onderdeel van de Docker-image; opnieuw bouwen is dus nodig bij een update.

## Persoonlijk dossier en netwerktags (v0.8.0)

- **Bewerkbare persoonsinformatie:** vier optionele velden op iedere profielpagina: *Hoe ken ik deze persoon?*, *Achtergrond*, *Interesses* (komma-gescheiden) en *Wat wil ik onthouden?*. Alles blijft opgeslagen bij volgende imports.
- **Overlappende netwerken:** voeg meerdere `#tags` toe aan een persoon, bijvoorbeeld `#wehkamp, #bierproefclub`. Interesses en netwerktags zijn gescheiden: interesses beschrijven onderwerpen; netwerktags groeperen mensen.
- **Nieuw tabblad Netwerktags:** toont alle groepen met aantallen; klik op een tag voor de unieke personen in die groep. Een persoon kan in veel groepen zitten, zonder duplicatie.
- **Accounts samenvoegen:** reeds handmatig ingevulde context en tags van beide profielen blijven bewaard wanneer je accounts koppelt. Gespreksverslagen blijven in Obsidian; geen dubbele opslag.
- **Privacy:** tags en notities zijn privé, net als de rest van Farley File; zet de app niet zonder authenticatie open naar internet.

## Farley File & Obsidian (v0.7.0)

- **Nieuwe naam:** de webapp heet **Farley File**. De bestaande GitHub-repository, Compose-stack, poort 8098 en database blijven voor compatibiliteit `network-search` heten.
- **Permanente persoons-ID's:** iedere geïmporteerde persoon heeft een vaste URL `/person/<id>`. Accounts houden hun eigen oorspronkelijke sleutels. Bestaande bevestigde koppelingen blijven bewaard.
- **Veilige koppelingen:** bij samenvoegen blijft de ID van het LinkedIn-profiel bestaan en leidt de oude Instagram-ID door. Bij ontkoppelen krijgt het afgesplitste Instagram-account een nieuw profiel; de oorspronkelijke persoon-URL blijft behouden.
- **Obsidian:** op iedere profielpagina staat een knop om een Markdown-link `[👤 Naam](http://homelab:8098/person/<id>)` te kopiëren. Bij browsers die klembordtoegang op HTTP blokkeren verschijnt een kopieervak.
- **Gespreksverslagen blijven in Obsidian:** optioneel kun je één of meer `obsidian://open?... `-links met titel aan een persoon toevoegen, bekijken of verwijderen. Farley File slaat uitsluitend verwijzingen op, niet de inhoud van je notities. Obsidian is nodig op het apparaat dat de link opent.
- **Privacy:** beide applicaties blijven privé. Farley File biedt nog geen ingebouwde authenticatie, dus uitsluitend bereikbaar maken via vertrouwd LAN of Tailscale (niet publiek).

## Personen en sociale accounts (v0.6.0)

- **Eén profielpagina per persoon:** zowel een LinkedIn-zoekresultaat als een Instagram-zoekresultaat opent `/person`. Ook een Instagram-account zonder LinkedIn-contact heeft een eigen profiel.
- **Koppelen vanaf de profielpagina:** zoek vanuit een LinkedIn-profiel naar Instagram-gebruikersnamen, of andersom vanuit een Instagram-profiel naar een LinkedIn-contact. Bekijk het externe profiel en bevestig de link. Je kunt de accounts vanaf dezelfde pagina weer ontkoppelen.
- **Geen dubbele personen in zoekresultaten:** wanneer LinkedIn en Instagram gekoppeld zijn verschijnt één resultaat, inclusief de gekoppelde accounts. Ook zoeken op de Instagram-gebruikersnaam toont de gezamenlijke profielpagina.
- **Bestaande koppelingen behouden:** v0.6.0 gebruikt de bestaande `profile_links`-tabel, zonder destructieve migratie. De vroegere `/contact?url=`-links verwijzen door naar de nieuwe persoonspagina.
- **Nog beperkt:** LinkedIn-berichten en werkhistorie staan op de profielpagina. Instagram-inboxberichten blijven doorzoekbaar, maar zijn nog niet betrouwbaar op gebruikersnaam aan een persoon gekoppeld. Facebook is nog niet geïmporteerd. Het model is voorbereid op een volgende bron, maar Facebook-koppelingen werken nog niet.

## Mogelijkheden

- **Instagram ZIP-import:** officiële JSON-export in één keer uploaden. Alleen volgers, gevolgde accounts en normale inbox-tekstberichten. Geen message requests, broadcasts, gesynchroniseerde telefooncontacten of media.
- **Handmatig koppelen en afwijzen:** op het tabblad Mogelijke koppelingen kun je een LinkedIn-contact op exacte volledige naam (of profiel-URL) koppelen aan een Instagram-gebruikersnaam. Met **Geen koppeling** wijs je een specifiek voorstel blijvend af; via Afgewezen voorstellen is dit te herstellen. Afwijzingen gelden per profielpaar en blijven na herstart bewaard.
- **Mogelijke koppelingen:** een apart tabblad naast Netwerkactiviteit doorzoekt alle LinkedIn- en Instagram-accounts op exacte naam/gebruikersnaam-overeenkomsten. Bekijk beide profielen, bevestig een koppeling en de bevestigde combinatie verdwijnt uit de suggesties. Geen automatische samenvoeging; lijst is gepagineerd.
- **Profielen handmatig koppelen:** een zoekopdracht zoals `Ilse Wintermans` kan ook `@ilsewintermans` vinden. Bij exacte overeenkomst van naam en gebruikersnaam verschijnt een voorstel *Mogelijk dezelfde persoon*. Koppelen vereist een expliciete bevestiging en kan vanaf de contactpagina worden teruggedraaid. Geen automatische samenvoeging van personen.
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
- [x] Facebook-export JSON: vrienden, inboxtekst en per-persoon-gesprekken (nog lokaal testen)
- [x] Eén persoonspagina voor LinkedIn en Instagram, handmatig koppelen vanuit beide richtingen en zoekresultaten ontdubbelen
- [x] Eerste handmatige koppeling LinkedIn ↔ Instagram, met suggesties en ontkoppelen
- [ ] Uitbreiding naar een universeel personenmodel (ook voor Facebook)
- [x] Farley File-naam, permanente personenlinks en Obsidian-notitiekoppeling
- [x] Handmatig personen toevoegen (zonder sociaal account)
- [x] Werkhistorie handmatig aanvullen, corrigeren en dateren zonder exports te overschrijven
- [x] Bewerkbaar persoonsdossier: hoe ken ik iemand, achtergrond, interesses en geheugensteuntjes
- [x] Overlappende netwerktags met overzichtspagina's
- [ ] Eventueel een Monica-integratie als daar later behoefte aan is
- [ ] Verdere zoekverbeteringen, eventueel optionele lokale semantische zoekfunctie

## Techniek

- Python / FastAPI
- SQLite + FTS5
- HTML/CSS
- Docker Compose

Bijdragen en verbeteringen zijn welkom.
