import csv
import hashlib
import io
import os
import re
import sqlite3
from html import escape
from pathlib import Path
from urllib.parse import urlsplit, quote
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from app.search import query_expression, expanded_query
from app.activity import contact_timeline, network_activity
from app.instagram import migrate as migrate_instagram, import_archive
from app.people import profile as render_profile, profile_url, merged_contacts
from app.identities import migrate as migrate_identities, candidates as identity_candidates, compact, link as link_profiles, unlink as unlink_profiles, all_candidates, reject as reject_match, restore as restore_match, resolve_contact
from app.employment import migrate as migrate_employment, observe as observe_employment, now_utc

DATA = Path(os.getenv("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "network.db"
app = FastAPI(title="Network Search")
APP_VERSION = "0.6.0"


def footer():
    return (f'<footer style="margin-top:36px;padding:18px 0;border-top:1px solid #dde6e5;'
            f'color:#647078;font-size:.85rem;text-align:center">'
            f'Network Search · v{APP_VERSION} · '
            f'<a href="https://github.com/MartinZwolle/network-search" '
            f'target="_blank" rel="noopener noreferrer">GitHub</a></footer>')


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
with connect() as _db:
    migrate_employment(_db)
    migrate_instagram(_db)
    migrate_identities(_db)


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
    timestamp = now_utc()
    with connect() as db:
        for row in rows:
            if contacts:
                url = value(row, "URL")
                if not url:
                    continue
                observe_employment(db, url, value(row, "Company"),
                                   value(row, "Position"), timestamp)
                db.execute("""INSERT INTO contacts VALUES (?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                first_name=excluded.first_name, last_name=excluded.last_name,
                email=CASE WHEN excluded.email <> '' THEN excluded.email ELSE contacts.email END,
                company=CASE WHEN excluded.company <> '' THEN excluded.company ELSE contacts.company END,
                position=CASE WHEN excluded.position <> '' THEN excluded.position ELSE contacts.position END,
                connected_on=excluded.connected_on""",
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


@app.post("/upload-instagram")
async def upload_instagram(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Selecteer de officiële Instagram ZIP-export")
    content = await file.read(80 * 1024 * 1024 + 1)
    try:
        with connect() as db:
            counts = import_archive(db, content)
    except (ValueError, UnicodeDecodeError, OSError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        "/?ig_imported=" + str(counts["inbox_messages"]), status_code=303)


@app.post("/profile-link")
def profile_link(linkedin_url: str = Form(...), instagram_username: str = Form(...),
                 action: str = Form("link"), source: str = Form("contact")):
    with connect() as db:
        try:
            if action == "reject":
                reject_match(db, linkedin_url, instagram_username)
            elif action == "restore":
                restore_match(db, linkedin_url, instagram_username)
            elif action == "unlink":
                unlink_profiles(db, linkedin_url, instagram_username)
            elif action == "link":
                link_profiles(db, linkedin_url, instagram_username)
            else:
                raise HTTPException(400, "Onbekende actie")
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    destination = ("/matches" if source == "matches" else
                   profile_url(linkedin_url=linkedin_url) if source == "person" else
                   "/contact?url=" + quote(linkedin_url, safe=""))
    return RedirectResponse(destination, status_code=303)


@app.post("/manual-link")
def manual_link(linkedin_contact: str = Form(...), instagram_username: str = Form(...)):
    with connect() as db:
        try:
            url = resolve_contact(db, linkedin_contact)
            link_profiles(db, url, instagram_username.strip().lstrip("@").casefold())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/matches?linked=1", status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(q: str = "", imported: int = 0, ig_imported: int = -1):
    with connect() as db:
        total_contacts = db.execute("SELECT count(*) FROM contacts").fetchone()[0]
        total_messages = db.execute("SELECT count(*) FROM messages").fetchone()[0]
        ig_accounts = db.execute("SELECT count(*) FROM instagram_accounts WHERE follows=1 OR follower=1").fetchone()[0]
        ig_messages_total = db.execute("SELECT count(*) FROM instagram_messages").fetchone()[0]
        ig_results = []
        ig_message_results = []
        if q.strip():
            # Instagram usernames and message text are separate from LinkedIn identities.
            like = "%" + q.lower().replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
            ig_results = db.execute("SELECT * FROM instagram_accounts WHERE username LIKE ? ESCAPE '\\' LIMIT 50", (like,)).fetchall()
            # Also match "Ilse Wintermans" against @ilsewintermans.
            compact_query = compact(q)
            if compact_query:
                known = {r["username"] for r in ig_results}
                for row in db.execute("SELECT * FROM instagram_accounts"):
                    if row["username"] not in known and compact_query in compact(row["username"]):
                        ig_results.append(row)
                        known.add(row["username"])
                        if len(ig_results) >= 50:
                            break
            ig_message_results = db.execute("SELECT * FROM instagram_messages WHERE content LIKE ? ESCAPE '\\' LIMIT 30", (like,)).fetchall()
        contacts = []
        messages = []
        if query_expression(q):
            contacts = db.execute("""SELECT c.*, (SELECT COUNT(*) FROM contact_messages cm
                         WHERE cm.contact_url=c.url) AS message_count
                FROM contacts_fts f JOIN contacts c ON c.url=f.url
                WHERE contacts_fts MATCH ? ORDER BY bm25(contacts_fts, 0.0, 8.0, 3.0, 5.0) LIMIT 100""",
                (query_expression(q),)).fetchall()
            messages = db.execute("""SELECT m.* FROM messages_fts f
                JOIN messages m ON m.message_key=f.message_key
                WHERE messages_fts MATCH ? ORDER BY bm25(messages_fts, 0.0, 3.0, 1.0) LIMIT 50""",
                (query_expression(q),)).fetchall()
        # Allow a compact Instagram handle to also find a LinkedIn name.
        compact_query = compact(q)
        if compact_query and len(compact_query) >= 4:
            known_urls = {r["url"] for r in contacts}
            for row in db.execute("""SELECT c.*, (SELECT COUNT(*) FROM contact_messages cm
                        WHERE cm.contact_url=c.url) AS message_count FROM contacts c"""):
                full_name = (row["first_name"] or "") + (row["last_name"] or "")
                if row["url"] not in known_urls and compact_query in compact(full_name):
                    contacts.append(row)
                    known_urls.add(row["url"])
                    if len(contacts) >= 100:
                        break
        suggestions = identity_candidates(db, contacts, ig_results) if q.strip() else []
        people_results = merged_contacts(db, contacts, ig_results) if q.strip() else []
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
</style><header><span class="brand">Elegant Chaos / Labs</span><h1>Network Search</h1><span class="muted">Je netwerk, opnieuw ontdekt.</span><nav style="margin-top:16px"><a href="/" aria-label="Naar de startpagina">⌂ Home</a> · <a href="/activity">Netwerkactiviteit</a> · <a href="/matches">Mogelijke koppelingen</a></nav></header>
    <p>LinkedIn: {total_contacts} contacten · {total_messages} berichten<br>Instagram: {ig_accounts} accounts · {ig_messages_total} inbox-berichten</p>
    {("<p>Geïmporteerde rijen: " + str(imported) + "</p>") if imported else ""}
    {("<p>Instagram: " + str(ig_imported) + " inbox-berichten verwerkt.</p>") if ig_imported >= 0 else ""}
    <section><h2>Zoeken</h2><form method="get">
    <input name="q" type="text" value="{escape(q, quote=True)}"
           placeholder="Naam, werkgever, functie of gesprek">
    <button>Zoek</button></form>
    <p class="muted" style="font-size:.9rem">Zoek ook in het Nederlands of Engels:
    bijvoorbeeld <em>IT manager overheid</em>, <em>security</em> of <em>Kubernetes</em>.</p>
    </section>"""
    if q.strip() and expanded_query(q):
        page += '<p class="muted">Zoektermen uitgebreid met verwante functietitels en vaktermen (NL/EN). Dit is trefwoordzoeken, geen AI.</p>'
    if suggestions:
        page += '<section><h2>Mogelijk dezelfde persoon</h2><p class="muted">Alleen suggesties op basis van namen. Controleer de profielen vóór je bevestigt.</p>'
        for contact, account in suggestions:
            name = escape((contact["first_name"] or "") + " " + (contact["last_name"] or ""))
            handle = escape(account["username"])
            page += (f'<article><strong>{name}</strong> (LinkedIn) ↔ '
                     f'<a href="https://www.instagram.com/{quote(account["username"], safe="")}/" target="_blank" rel="noopener noreferrer">@{handle}</a>'
                     f'<form method="post" action="/profile-link">'
                     f'<input type="hidden" name="linkedin_url" value="{escape(contact["url"], quote=True)}">'
                     f'<input type="hidden" name="instagram_username" value="{escape(account["username"], quote=True)}">'
                     f'<button type="submit">Zelfde persoon — koppelen</button></form>'
                 f'<form action="/profile-link" method="post">'
                 f'<input type="hidden" name="linkedin_url" value="{escape(contact["url"], quote=True)}">'
                 f'<input type="hidden" name="instagram_username" value="{escape(username, quote=True)}">'
                 f'<input type="hidden" name="source" value="matches">'
                 f'<input type="hidden" name="action" value="reject">'
                 f'<button type="submit" style="background:#69767a">Geen koppeling</button>'
                 f'</form></article>')
        page += '</section>'
    if q.strip():
        page += f'<section><h2>Personen ({len(people_results)} getoond)</h2>'
        for source, person in people_results:
            if source == "linkedin":
                display_name = " ".join(filter(None, [person["first_name"], person["last_name"]]))
                person_link = profile_url(linkedin_url=person["url"])
                with connect() as links_db:
                    linked_handles = [r["instagram_username"] for r in links_db.execute(
                        "SELECT instagram_username FROM profile_links WHERE linkedin_url=? ORDER BY instagram_username",
                        (person["url"],)
                    )]
                social_labels = "LinkedIn" + (" · Instagram " + ", ".join("@" + h for h in linked_handles) if linked_handles else "")
                note = f'{person["position"] or ""} · {person["company"] or ""}'
                count = f'{person["message_count"]} LinkedIn-berichten'
            else:
                display_name = "@" + person["username"]
                person_link = profile_url(instagram_username=person["username"])
                social_labels = "Instagram"
                note = "Instagram-account"
                count = ""
            page += (f'<article><strong><a href="{escape(person_link, quote=True)}">{escape(display_name)}</a></strong><br>'
                     f'<small>{escape(social_labels)}</small><br>'
                     f'{escape(note)}<br>'
                     f'<a href="{escape(person_link, quote=True)}">Profiel bekijken</a>'
                     f'{" · " + escape(count) if count else ""}</article>')
        page += '</section>'
        page += f"<section><h2>Berichten ({len(messages)} getoond)</h2>"
        for message in messages:
            page += (f'<article><strong>{escape(message["subject"] or "(geen onderwerp)")}'
                     f'</strong><br><small>{escape(message["date"] or "")} · '
                     f'{escape(message["sender"] or "")}</small>'
                     f'<pre>{escape((message["content"] or "")[:700])}</pre></article>')
        page += "</section>"
        page += f'<section><h2>Instagram-berichten ({len(ig_message_results)} getoond)</h2>'
        for msg in ig_message_results:
            page += (f'<article><strong>{escape(msg["sender"])}</strong> '
                     f'<small>{escape(msg["date"][:10])}</small>'
                     f'<pre>{escape(msg["content"][:700])}</pre></article>')
        page += "</section>"
    page += """<details style="margin-top:32px;background:#fff;border:1px solid #dde6e5;
        padding:18px 24px;border-radius:5px">
        <summary style="cursor:pointer;color:#087f80;font-weight:700">CSV importeren</summary>
        <p>Upload Connections.csv en messages.csv afzonderlijk.
        Alle gegevens blijven op je eigen server.</p>
        <form action="/upload" method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".csv" required>
        <button>Importeer</button></form>
        <hr style="border:0;border-top:1px solid #dde6e5;margin:24px 0">
        <p><strong>Instagram-export (ZIP)</strong></p>
        <p>Alleen volgers, gevolgde accounts en gewone inbox-tekstberichten.
        Verzoeken, gesynchroniseerde telefooncontacten, broadcasts en media worden overgeslagen.</p>
        <form action="/upload-instagram" method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".zip" required>
        <button>Importeer Instagram</button></form></details>"""
    return page + footer() + "</html>"


@app.get("/contact")
def contact_detail(url: str):
    """Keep bookmarked historical contact URLs working."""
    return RedirectResponse(profile_url(linkedin_url=url), status_code=303)


@app.get("/person", response_class=HTMLResponse)
def person_detail(linkedin_url: str = "", instagram_username: str = "", find: str = ""):
    with connect() as db:
        return render_profile(db, linkedin_url=linkedin_url,
                              instagram_username=instagram_username,
                              find=find, footer=footer,
                              contact_timeline=contact_timeline,
                              profile_key=profile_key)


@app.get("/activity", response_class=HTMLResponse)
def activity_page():
    with connect() as db:
        overview = network_activity(db)
    page = """<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Netwerkactiviteit · Network Search</title>
    <style>
    :root{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--paper:#fff;--bg:#f5f7f6}
    *{box-sizing:border-box}
    body{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1050px;margin:0 auto;padding:38px 24px 90px;background:var(--bg);color:var(--ink)}
    h1,h2,h3{line-height:1.25;letter-spacing:-.035em}
    h1{font-size:clamp(2.3rem,5vw,4rem);margin:.35em 0 .15em}
    a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}
    header{border-bottom:4px solid var(--accent);padding-bottom:23px;margin-bottom:30px}
    .brand{font-size:.83rem;text-transform:uppercase;letter-spacing:.17em;font-weight:800;color:var(--accent)}
    section{background:var(--paper);padding:clamp(20px,4vw,32px);margin:22px 0;border:1px solid var(--edge);border-radius:5px;box-shadow:0 8px 28px #192f2d08}
    article{padding:14px 0;border-top:1px solid var(--edge)}
    .muted,small{color:var(--muted)}
    </style>
    <header><span class="brand">Elegant Chaos / Labs</span>
    <h1>Netwerkactiviteit</h1>
    <nav style="margin-top:16px"><a href="/">⌂ Home</a> ·
    <a href="/activity" aria-current="page">Netwerkactiviteit</a> · <a href="/matches">Mogelijke koppelingen</a></nav>
    </header>"""
    return page + overview + footer() + "</html>"


@app.get("/matches", response_class=HTMLResponse)
def possible_matches(page: int = 1, linked: int = 0):
    with connect() as db:
        suggestions = all_candidates(db)
        linked_count = db.execute("SELECT COUNT(*) FROM profile_links").fetchone()[0]
        rejected_rows = db.execute("""SELECT r.linkedin_url, r.instagram_username,
            c.first_name, c.last_name FROM profile_rejections r
            JOIN contacts c ON c.url=r.linkedin_url
            ORDER BY r.rejected_at DESC LIMIT 30""").fetchall()
        rejection_count = db.execute("SELECT COUNT(*) FROM profile_rejections").fetchone()[0]
    page_size = 30
    total = len(suggestions)
    max_page = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), max_page)
    visible = suggestions[(page - 1) * page_size:page * page_size]
    html = """<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Mogelijke koppelingen · Network Search</title>
    <style>
    :root{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--paper:#fff;--bg:#f5f7f6}
    *{box-sizing:border-box}body{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;
    max-width:1050px;margin:0 auto;padding:38px 24px 90px;background:var(--bg);color:var(--ink)}
    h1,h2{line-height:1.25;letter-spacing:-.035em}h1{font-size:clamp(2.3rem,5vw,4rem);margin:.35em 0 .15em}
    a{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}
    header{border-bottom:4px solid var(--accent);padding-bottom:23px;margin-bottom:30px}
    .brand{font-size:.83rem;text-transform:uppercase;letter-spacing:.17em;font-weight:800;color:var(--accent)}
    section{background:var(--paper);padding:clamp(20px,4vw,32px);margin:22px 0;
    border:1px solid var(--edge);border-radius:5px;box-shadow:0 8px 28px #192f2d08}
    article{padding:18px 0;border-top:1px solid var(--edge)}
    .muted,small{color:var(--muted)}
    button{background:var(--accent);color:white;border:0;padding:11px 16px;
    border-radius:4px;font:inherit;font-weight:700;cursor:pointer;margin-top:9px}
    </style>
    <header><span class="brand">Elegant Chaos / Labs</span>
    <h1>Mogelijke koppelingen</h1>
    <nav style="margin-top:16px"><a href="/">⌂ Home</a> ·
    <a href="/activity">Netwerkactiviteit</a> ·
    <a href="/matches" aria-current="page">Mogelijke koppelingen</a></nav>
    </header>"""
    html += """<section><h2>Handmatig koppelen</h2>
    <p class="muted">Ook voor accounts waarvan de namen niet overeenkomen.
    Vul de volledige LinkedIn-naam (of profiel-URL) en de exacte Instagram-gebruikersnaam in.
    Bij dubbele LinkedIn-namen gebruik je de profiel-URL.</p>
    <form action="/manual-link" method="post">
    <label for="linkedin_contact">LinkedIn-naam of profiel-URL</label><br>
    <input id="linkedin_contact" name="linkedin_contact" type="text"
           placeholder="Bijvoorbeeld Ilse Wintermans" required
           style="width:100%;max-width:540px;padding:10px;margin-bottom:10px"><br>
    <label for="instagram_username">Instagram-gebruikersnaam</label><br>
    <input id="instagram_username" name="instagram_username" type="text"
           placeholder="@gebruikersnaam" required
           style="width:100%;max-width:540px;padding:10px;margin-bottom:10px"><br>
    <button type="submit">Accounts koppelen</button></form></section>"""
    if linked:
        html += '<p style="color:#087f80"><strong>Accounts gekoppeld!</strong></p>'
    html += (f'<section><h2>{total} mogelijke koppelingen</h2>'
             f'<p>{linked_count} profielen al handmatig gekoppeld.</p>'
             '<p class="muted">Alleen exacte overeenkomsten tussen een volledige '
             'LinkedIn-naam zonder spaties en een Instagram-gebruikersnaam. '
             'Dit is een aanwijzing, geen bewijs dat het dezelfde persoon is. '
             'Controleer beide profielen voordat je koppelt.</p>')
    if not visible:
        html += '<p>Geen nieuwe suggesties gevonden.</p>'
    for contact, username in visible:
        name = escape(" ".join(filter(None, [contact["first_name"], contact["last_name"]])))
        ig_url = "https://www.instagram.com/" + quote(username, safe="") + "/"
        html += (f'<article><strong>{name}</strong><br>'
                 f'<small>{escape(contact["position"] or "")} · '
                 f'{escape(contact["company"] or "")}</small><br>'
                 f'<a href="{escape(contact["url"], quote=True)}" target="_blank" rel="noopener noreferrer">LinkedIn ↗</a>'
                 f' · <a href="{ig_url}" target="_blank" rel="noopener noreferrer">'
                 f'Instagram @{escape(username)} ↗</a>'
                 f'<form action="/profile-link" method="post">'
                 f'<input type="hidden" name="linkedin_url" value="{escape(contact["url"], quote=True)}">'
                 f'<input type="hidden" name="instagram_username" value="{escape(username, quote=True)}">'
                 f'<input type="hidden" name="source" value="matches">'
                 f'<button type="submit">Zelfde persoon — koppelen</button></form></article>')
    html += '</section><p>'
    if page > 1:
        html += f'<a href="/matches?page={page-1}">← Vorige</a> · '
    html += f'Pagina {page} van {max_page}'
    if page < max_page:
        html += f' · <a href="/matches?page={page+1}">Volgende →</a>'
    html += '</p>'
    html += (f'<details style="margin-top:24px"><summary style="cursor:pointer">'
             f'Afgewezen voorstellen ({rejection_count}) — herstellen</summary>'
             '<section><h2>Afgewezen voorstellen</h2>'
             '<p class="muted">De laatste 30 afwijzingen. Herstellen maakt de suggestie weer zichtbaar.</p>')
    for row in rejected_rows:
        display_name = escape(" ".join(filter(None, [row["first_name"], row["last_name"]])))
        html += (f'<article>{display_name} ↔ @{escape(row["instagram_username"])}'
                 f'<form method="post" action="/profile-link">'
                 f'<input type="hidden" name="linkedin_url" value="{escape(row["linkedin_url"], quote=True)}">'
                 f'<input type="hidden" name="instagram_username" value="{escape(row["instagram_username"], quote=True)}">'
                 f'<input type="hidden" name="action" value="restore">'
                 f'<input type="hidden" name="source" value="matches">'
                 f'<button type="submit">Afwijzing ongedaan maken</button></form></article>')
    html += '</section></details>'
    return html + footer() + '</html>'
