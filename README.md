# Network Search

Zelfgehoste LinkedIn-netwerkzoekmachine met FastAPI en SQLite FTS5.

## Installatie

```sh
git clone https://github.com/MartinZwolle/network-search.git
cd network-search
docker compose up -d --build
```

De applicatie luistert standaard op **127.0.0.1:8098** van de Docker-host. Maak vanaf je desktop bijvoorbeeld een SSH-tunnel:

```sh
ssh -L 8098:127.0.0.1:8098 gebruiker@homelab
```

Open vervolgens http://localhost:8098. Importeer de LinkedIn-bestanden `Connections.csv` en `messages.csv` afzonderlijk via de webinterface.

## Veiligheid

**Deze MVP heeft geen authenticatie. Publiceer de poort niet rechtstreeks op het internet.** Gebruik een SSH-tunnel of beschermde reverse proxy. CSV's en SQLite-data horen uitsluitend lokaal in `./data/` en worden met `.gitignore` uitgesloten. Zet nooit LinkedIn-exports, berichtinhoud of credentials in Git.

## Functies

- Contacten zoeken op naam, functie, werkgever
- Volledige tekst van berichten doorzoeken
- CSV-upload en herimport met deduplicatie

Monica-koppeling, geavanceerde relatieanalyse en semantisch zoeken zijn nog niet beschikbaar.
