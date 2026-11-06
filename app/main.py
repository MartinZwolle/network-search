import csv
import hashlib
import io
import os
import re
import sqlite3
from html import escape
from pathlib import Path
from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse

DATA = Path(os.getenv("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "network.db"
app = FastAPI(title="Network Search")


def connect():
    db = sqlite3.connect(DB)
    db.row_factory = sqlite3.Row
    return db


def initialize():
    with connect() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS contacts (
          url TEXT PRIMARY KEY, first_name TEXT, last_name TEXT,
          email TEXT, company TEXT, position TEXT, connected_on TEXT);
        CREATE TABLE IF NOT EXISTS messages (
          message_key TEXT PRIMARY KEY, conversation_id TEXT, sender TEXT,
          sender_url TEXT, recipients TEXT, recipient_urls TEXT,
          date TEXT, subject TEXT, content TEXT, folder TEXT);
        CREATE VIRTUAL TABLE IF NOT EXISTS contacts_fts USING
          fts5(url UNINDEXED, name, company, position);
        CREATE VIRTUAL TABLE IF NOT EXISTS messages_fts USING
          fts5(message_key UNINDEXED, subject, content);
        """)


initialize()


def value(row, *names):
    normalized = {re.sub(r"\s+", " ", k.strip()).upper(): (v or "").strip()
                  for k, v in row.items() if k}
    return next((normalized[name.upper()] for name in names
                 if name.upper() in normalized), "")


def parse_csv(raw):
    for encoding in ("utf-8-sig", "utf-16", "cp1252"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(400, "CSV-encoding niet ondersteund")
    lines = text.splitlines(keepends=True)
    header = next((i for i, line in enumerate(lines)
                   if ("First Name" in line and "Last Name" in line)
                   or "CONVERSATION ID" in line.upper()), None)
    if header is None:
        raise HTTPException(400, "LinkedIn CSV-kopregel niet gevonden")
    return list(csv.DictReader(io.StringIO("".join(lines[header:]))))


def query_expression(query):
    terms = re.findall(r"[\wÀ-ÿ]+", query)
    return " AND ".join('"' + term.replace('"', "") + '"*'
                        for term in terms[:12])


@app.post("/upload")
async def upload(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".csv"):
        raise HTTPException(400, "Selecteer een CSV-bestand")
    raw = await file.read(25 * 1024 * 1024 + 1)
    if len(raw) > 25 * 1024 * 1024:
        raise HTTPException(413, "CSV groter dan 25 MB")
    rows = parse_csv(raw)
    if not rows:
        raise HTTPException(400, "Lege CSV")
    contacts = any(k.strip().lower() == "first name" for k in rows[0])
    messages = any(k.strip().upper() == "CONVERSATION ID" for k in rows[0])
    if not (contacts or messages):
        raise HTTPException(400, "Geen Connections.csv of messages.csv")
    count = 0
    with connect() as db:
        for row in rows:
            if contacts:
                url = value(row, "URL")
                if not url:
                    continue
                db.execute("""INSERT INTO contacts VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                first_name=excluded.first_name, last_name=excluded.last_name,
                email=excluded.email, company=excluded.company,
                position=excluded.position, connected_on=excluded.connected_on""",
                (url, value(row, "First Name"), value(row, "Last Name"),
                 value(row, "Email Address"), value(row, "Company"),
                 value(row, "Position"), value(row, "Connected On")))
            else:
                key = hashlib.sha256(repr(sorted(row.items())).encode()).hexdigest()
                db.execute("INSERT OR IGNORE INTO messages VALUES (?,?,?,?,?,?,?,?,?,?)",
                (key, value(row, "CONVERSATION ID"), value(row, "FROM"),
                 value(row, "SENDER PROFILE URL"), value(row, "TO"),
                 value(row, "RECIPIENT PROFILE URLS"), value(row, "DATE"),
                 value(row, "SUBJECT"), value(row, "CONTENT"), value(row, "FOLDER")))
            count += 1
        if contacts:
            db.execute("DELETE FROM contacts_fts")
            db.execute("""INSERT INTO contacts_fts
                        SELECT url, first_name || ' ' || last_name,
                               company, position FROM contacts""")
        else:
            db.execute("DELETE FROM messages_fts")
            db.execute("""INSERT INTO messages_fts
                        SELECT message_key, subject, content FROM messages""")
    return RedirectResponse("/?imported=" + str(count), status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(q: str = "", imported: int = 0):
    with connect() as db:
        total_contacts = db.execute("SELECT count(*) FROM contacts").fetchone()[0]
        total_messages = db.execute("SELECT count(*) FROM messages").fetchone()[0]
        contacts = []
        messages = []
        if query_expression(q):
            contacts = db.execute("""SELECT c.* FROM contacts_fts f
                JOIN contacts c ON c.url=f.url
                WHERE contacts_fts MATCH ? LIMIT 100""",
                (query_expression(q),)).fetchall()
            messages = db.execute("""SELECT m.* FROM messages_fts f
                JOIN messages m ON m.message_key=f.message_key
                WHERE messages_fts MATCH ? LIMIT 50""",
                (query_expression(q),)).fetchall()
    page = f"""<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Network Search</title><style>
    body{{font:16px system-ui;max-width:960px;margin:40px auto;padding:0 20px;
         background:#f7f8fa;color:#20252b}}
    section{{background:white;padding:22px;margin:20px 0;border-radius:12px;
             box-shadow:0 2px 12px #0001}}
    input[type=text]{{padding:12px;width:75%;max-width:650px}}
    button{{padding:12px;cursor:pointer}}
    article{{padding:12px 0;border-top:1px solid #ddd}}
    small{{color:#555}}
    pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}
    </style><h1>Network Search</h1>
    <p>{total_contacts} contacten · {total_messages} berichten</p>
    {("<p>Geïmporteerde rijen: " + str(imported) + "</p>") if imported else ""}
    <section><h2>Zoeken</h2><form method="get">
    <input name="q" type="text" value="{escape(q, quote=True)}"
           placeholder="Naam, werkgever, functie of gesprek">
    <button>Zoek</button></form></section>
    <section><h2>CSV importeren</h2>
    <p>Upload Connections.csv en messages.csv afzonderlijk.
       Alle gegevens blijven op je eigen server.</p>
    <form action="/upload" method="post" enctype="multipart/form-data">
    <input type="file" name="file" accept=".csv" required>
    <button>Importeer</button></form></section>"""
    if q.strip():
        page += f"<section><h2>Contacten ({len(contacts)} getoond)</h2>"
        for contact in contacts:
            url = escape(contact["url"], quote=True)
            page += (f'<article><strong>{escape(contact["first_name"] or "")} '
                     f'{escape(contact["last_name"] or "")}</strong><br>'
                     f'{escape(contact["position"] or "")} · '
                     f'{escape(contact["company"] or "")}<br>'
                     f'<a href="{url}" target="_blank" rel="noopener noreferrer">'
                     'LinkedIn-profiel</a></article>')
        page += f"</section><section><h2>Berichten ({len(messages)} getoond)</h2>"
        for message in messages:
            page += (f'<article><strong>{escape(message["subject"] or "(geen onderwerp)")}'
                     f'</strong><br><small>{escape(message["date"] or "")} · '
                     f'{escape(message["sender"] or "")}</small>'
                     f'<pre>{escape((message["content"] or "")[:700])}</pre></article>')
        page += "</section>"
    return page + "</html>"
