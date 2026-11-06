import csv
import hashlib
import io
import os
import re
import sqlite3
from html import escape
from pathlib import Path
from urllib.parse import urlsplit, quote
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
        CREATE TABLE IF NOT EXISTS contact_messages (
          contact_url TEXT NOT NULL, message_key TEXT NOT NULL,
          PRIMARY KEY(contact_url, message_key));
        CREATE INDEX IF NOT EXISTS idx_contact_messages_message
          ON contact_messages(message_key);
        """)


initialize()


def profile_key(url):
    """Use LinkedIn member paths as stable keys, ignoring host and query."""
    url = (url or "").strip()
    if not url:
        return ""
    path = urlsplit(url if "://" in url else "https://" + url).path
    path = path.rstrip("/").lower()
    return path if path.startswith("/in/") else ""


def rebuild_links(db):
    lookup = {}
    for row in db.execute("SELECT url FROM contacts"):
        key = profile_key(row["url"])
        if key:
            lookup.setdefault(key, row["url"])
    db.execute("DELETE FROM contact_messages")
    for row in db.execute("SELECT message_key, sender_url, recipient_urls FROM messages"):
        urls = [row["sender_url"]] + re.split(r"[,;\s]+", row["recipient_urls"] or "")
        keys = {profile_key(url) for url in urls}
        for key in keys:
            if key in lookup:
                db.execute("INSERT OR IGNORE INTO contact_messages VALUES (?, ?)",
                           (lookup[key], row["message_key"]))


with connect() as _db:
    rebuild_links(_db)


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
        rebuild_links(db)
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
:root{{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--paper:#fff;--bg:#f5f7f6}}
*{{box-sizing:border-box}}body{{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1050px;margin:0 auto;padding:38px 24px 90px;background:var(--bg);color:var(--ink)}}
h1,h2,h3{{line-height:1.25;letter-spacing:-.035em}}h1{{font-size:clamp(2.3rem,5vw,4rem);margin:.35em 0 .15em}}h2{{font-size:1.45rem}}
a{{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}}
header{{border-bottom:4px solid var(--accent);padding-bottom:23px;margin-bottom:30px}}
.brand{{font-size:.83rem;text-transform:uppercase;letter-spacing:.17em;font-weight:800;color:var(--accent)}}
section{{background:var(--paper);padding:clamp(20px,4vw,32px);margin:22px 0;border:1px solid var(--edge);border-radius:5px;box-shadow:0 8px 28px #192f2d08}}
input[type=text]{{padding:13px 15px;width:min(78%,650px);border:1px solid #bdcbcb;border-radius:4px;font:inherit}}
button{{background:var(--accent);color:white;border:0;padding:14px 20px;border-radius:4px;font:inherit;font-weight:700;cursor:pointer}}
button:hover{{filter:brightness(.9)}}article{{padding:16px 0;border-top:1px solid var(--edge)}}
article strong{{font-size:1.08rem}}small,.muted{{color:var(--muted)}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}
.badge{{display:inline-block;padding:3px 10px;background:#e4f3f0;color:#075f5c;border-radius:3px;font-size:.85rem;font-weight:700}}
@media(max-width:550px){{input[type=text]{{width:100%;margin-bottom:10px}}button{{width:100%}}}}
</style><header><span class="brand">Elegant Chaos / Labs</span><h1>Network Search</h1><span class="muted">Je netwerk, opnieuw ontdekt.</span></header>
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
                     f'<a href="/contact?url={quote(contact["url"], safe="")}">Gesprekken bekijken</a> · ' 
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


@app.get("/contact", response_class=HTMLResponse)
def contact_detail(url: str):
    with connect() as db:
        contact = db.execute("SELECT * FROM contacts WHERE url=?", (url,)).fetchone()
        if contact is None:
            raise HTTPException(404, "Contact niet gevonden")
        history = db.execute("""
            SELECT m.* FROM contact_messages cm
            JOIN messages m ON m.message_key=cm.message_key
            WHERE cm.contact_url=?
            ORDER BY m.date DESC
        """, (url,)).fetchall()
    name = " ".join(filter(None, (contact["first_name"], contact["last_name"])))
    received = sum(profile_key(m["sender_url"]) == profile_key(url) for m in history)
    sent = len(history) - received
    conversations = len({m["conversation_id"] for m in history if m["conversation_id"]})
    last = history[0]["date"] if history else "Geen berichten gevonden"
    page = """<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width,initial-scale=1">
    <title>Contact · Network Search</title>""" + "<style>\n:root{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--paper:#fff;--bg:#f5f7f6}\n*{box-sizing:border-box}body{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1050px;margin:0 auto;padding:38px 24px 90px;background:var(--bg);color:var(--ink)}\nh1,h2,h3{line-height:1.25;letter-spacing:-.035em}h1{font-size:clamp(2.3rem,5vw,4rem);margin:.35em 0 .15em}h2{font-size:1.45rem}\na{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}\nheader{border-bottom:4px solid var(--accent);padding-bottom:23px;margin-bottom:30px}\n.brand{font-size:.83rem;text-transform:uppercase;letter-spacing:.17em;font-weight:800;color:var(--accent)}\nsection{background:var(--paper);padding:clamp(20px,4vw,32px);margin:22px 0;border:1px solid var(--edge);border-radius:5px;box-shadow:0 8px 28px #192f2d08}\ninput[type=text]{padding:13px 15px;width:min(78%,650px);border:1px solid #bdcbcb;border-radius:4px;font:inherit}\nbutton{background:var(--accent);color:white;border:0;padding:14px 20px;border-radius:4px;font:inherit;font-weight:700;cursor:pointer}\nbutton:hover{filter:brightness(.9)}article{padding:16px 0;border-top:1px solid var(--edge)}\narticle strong{font-size:1.08rem}small,.muted{color:var(--muted)}\npre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}\n.badge{display:inline-block;padding:3px 10px;background:#e4f3f0;color:#075f5c;border-radius:3px;font-size:.85rem;font-weight:700}\n@media(max-width:550px){input[type=text]{width:100%;margin-bottom:10px}button{width:100%}}\n</style>" + f"""
    <p><a href="/">← Terug naar zoeken</a></p>
    <header><span class="brand">Elegant Chaos / Labs</span>
    <h1>{escape(name)}</h1><p>{escape(contact["position"] or "")} ·
    {escape(contact["company"] or "")}</p>
    <a href="{escape(url, quote=True)}" target="_blank" rel="noopener noreferrer">
    LinkedIn-profiel ↗</a></header>
    <section><h2>Contactgeschiedenis</h2>
    <p><span class="badge">{len(history)} berichten</span> ·
    {conversations} gesprekken · {received} ontvangen · {sent} overige</p>
    <p>Laatste LinkedIn-bericht: {escape(last)}</p></section>
    <section><h2>Berichten</h2>"""
    for msg in history:
        direction = "Ontvangen" if profile_key(msg["sender_url"]) == profile_key(url) else "Verzonden / groepsbericht"
        page += (f"<article><small>{escape(msg['date'] or '')} · {direction} · "
                 f"{escape(msg['sender'] or '')}</small>"
                 f"<h3>{escape(msg['subject'] or '(geen onderwerp)')}</h3>"
                 f"<pre>{escape(msg['content'] or '')}</pre></article>")
    return page + "</section></html>"
