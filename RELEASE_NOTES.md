# Farley File 1.0.0

**9 november 2026 — eerste stabiele release**

Farley File is een persoonlijk, zelfgehost netwerkgeheugen: personen staan centraal, niet hun sociale platforms. Deze release brengt de bestaande archieven, koppelingen en profielen samen in één overzichtelijke interface.

## Nieuw in 1.0

- **Eén interface.** Een herkenbare Farley File-header, logo, paginatitels en een volledig, consistent navigatiemenu op de homepage en onderliggende schermen, inclusief het Twitter-archief.
- **Netwerkactiviteit als werklijst.** Contacten om opnieuw te bekijken kunnen worden afgevinkt, teruggezet en als afgehandeld teruggevonden. Als meerdere sociale accounts aan één persoon zijn gekoppeld, wordt die persoon één keer getoond.
- **Eén plek voor mogelijke koppelingen.** Verklaarbare voorstellen over LinkedIn, Facebook, Instagram, Twitter en handmatige persoonsprofielen, met expliciete bevestiging. Farley File voegt nooit autonoom personen samen.
- **De nieuwe profielpagina.** De afgesproken volgorde is **Persoonlijk → Obsidian → Werkhistorie → Sociale accounts → Tijdlijn**.
- **Sociale accounts beheren.** Bekijk ook historische Twitter-identiteiten tussen de overige accounts, zoek geïmporteerde accounts van alle ondersteunde platforms en koppel ze bewust. Elk platform heeft een subtiele ontkoppelactie.
- **Gecombineerde persoonstijdlijn.** Een chronologische geschiedenis met platformfilters, paginering, LinkedIn-berichten, Facebook-gesprekken, tweets en Twitter-DM-gesprekken. Vanuit de tijdlijn kun je volledige beschikbare berichten en gesprekken openen.
- **Testen.** Automatische Python-syntaxcontrole en unit tests via GitHub Actions, plus handmatige acceptatietests op de homelab-installatie.

## Belangrijk om te weten

- Alle gegevens blijven in je eigen SQLite-database. Maak vóór upgraden een back-up.
- Een account ontkoppelen verwijdert **geen** geïmporteerde berichten, maar maakt nog **niet** een eerdere persoonsamenvoeging ongedaan.
- Instagram-inboxberichten verschijnen pas in de persoonstijdlijn zodra de afzender betrouwbaar aan een geïmporteerd account kan worden gekoppeld.
- Het Twitter-archief bevat geen gesprekken die niet in de oorspronkelijke export aanwezig waren.
- De tijdlijn toont geregistreerde gegevens, niet noodzakelijk het volledige historische contact.
- WhatsApp-import valt buiten versie 1.0.

**Met dank aan de eerste praktijktests:** de homepage, netwerkactiviteit inclusief terugzetten, Twitter-archief, mogelijke koppelingen, netwerktags, profielvolgorde, tijdlijn en het koppelen van accounts zijn doorlopen op de echte installatie.
