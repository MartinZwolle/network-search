import csv
import json
import zipfile
from datetime import datetime, timezone
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
from fastapi.staticfiles import StaticFiles
from app.search import query_expression, expanded_query
from app.message_people import contact_lookup, author_profile
from app.activity import contact_timeline
from app.activity_all import render as render_network_activity
from app.instagram import migrate as migrate_instagram, import_archive
from app.facebook import migrate as migrate_facebook, import_archive as import_facebook, find_messages as find_facebook_messages
from app.twitter import migrate as migrate_twitter, import_archive as import_twitter
from app.people import profile as render_profile, profile_url, merged_contacts
from app.person_ids import migrate as migrate_person_ids, sync as sync_person_ids, account_person, details as person_details, add_note, remove_note
from app.context import migrate as migrate_context, save as save_context
from app.manual import migrate as migrate_manual, create_person, rename_person, search_manual, display_name as farley_display_name, save_job, delete_manual_job, possible_duplicates, delete_person
from app.person_ids import merge_people
from app.identities import migrate as migrate_identities, candidates as identity_candidates, compact, link as link_profiles, unlink as unlink_profiles, all_candidates, reject as reject_match, restore as restore_match, resolve_contact, migrate_facebook_matches, facebook_candidates, reject_facebook_match
from app.employment import migrate as migrate_employment, observe as observe_employment, now_utc
from app.smart_matches import migrate as migrate_smart_matches, candidates as smart_candidates, reject as reject_smart_match

DATA = Path(os.getenv("DATA_DIR", "/data"))
DATA.mkdir(parents=True, exist_ok=True)
DB = DATA / "network.db"
app = FastAPI(title="Farley File")
app.mount("/static", StaticFiles(directory=Path(__file__).parent / "static"), name="static")
APP_VERSION = "0.12.0"


def footer():
    return (f'<footer style="margin-top:36px;padding:18px 0;border-top:1px solid #dde6e5;'
            f'color:#647078;font-size:.85rem;text-align:center">'
            f'Farley File · v{APP_VERSION} · '
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
    migrate_person_ids(_db)
    migrate_context(_db)
    migrate_manual(_db)
    migrate_facebook(_db)
    migrate_twitter(_db)
    migrate_facebook_matches(_db)
    migrate_smart_matches(_db)
    sync_person_ids(_db)


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
        sync_person_ids(db)
    return RedirectResponse("/?imported=" + str(count), status_code=303)


@app.post("/upload-instagram")
async def upload_instagram(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Selecteer de officiële Instagram ZIP-export")
    content = await file.read(80 * 1024 * 1024 + 1)
    try:
        with connect() as db:
            counts = import_archive(db, content)
            sync_person_ids(db)
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
    person_id = None
    if source == "person":
        with connect() as db:
            person_id = account_person(db, "linkedin", linkedin_url)
    destination = ("/matches" if source == "matches" else
                   "/person/" + str(person_id) if person_id is not None else
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


@app.post("/upload-facebook")
async def upload_facebook(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400, "Selecteer een Facebook ZIP-export")
    content = await file.read(128 * 1024 * 1024 + 1)
    try:
        with connect() as db:
            counts = import_facebook(db, content)
    except (ValueError, UnicodeDecodeError, OSError, zipfile.BadZipFile,
            json.JSONDecodeError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return RedirectResponse(
        "/?fb_imported=" + str(counts["messages"]), status_code=303)


@app.post("/upload-twitter")
async def upload_twitter(file: UploadFile = File(...)):
    if not file.filename or not file.filename.lower().endswith(".zip"):
        raise HTTPException(400,"Selecteer een officiële Twitter ZIP-export")
    content=await file.read(100*1024*1024+1)
    try:
        with connect() as db:
            counts=import_twitter(db,content)
    except (ValueError,UnicodeDecodeError,OSError,json.JSONDecodeError,zipfile.BadZipFile) as exc:
        raise HTTPException(400,str(exc)) from exc
    return RedirectResponse("/?twitter_imported="+str(counts["tweets"]),status_code=303)


@app.get("/facebook/thread/{thread_id}", response_class=HTMLResponse)
def facebook_thread(thread_id: str):
    with connect() as db:
        thread = db.execute("SELECT * FROM facebook_threads WHERE id=?", (thread_id,)).fetchone()
        if thread is None:
            raise HTTPException(404, "Facebook-gesprek niet gevonden")
        rows = db.execute(
            """SELECT * FROM facebook_messages WHERE thread_id=?
               ORDER BY timestamp_ms, message_key LIMIT 5000""", (thread_id,)
        ).fetchall()
        page = (f'<!doctype html><html lang="nl"><meta charset="utf-8">'
                f'<meta name="viewport" content="width=device-width, initial-scale=1">'
                f'<title>Facebook-gesprek · Farley File</title>'
                f'<style>body{{font:16px/1.7 system-ui,sans-serif;max-width:930px;'
                f'margin:0 auto;padding:32px 20px;background:#f5f7f6;color:#252b30}}'
                f'a{{color:#087f80}}article{{background:white;padding:18px;'
                f'border:1px solid #dde6e5;margin:12px 0}}'
                f'pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}</style>'
                f'<p><a href="/">← Farley File</a></p>'
                f'<h1>{escape(thread["title"])}</h1>'
                f'<p>Facebook · {"Groepsgesprek" if thread["is_group"] else "Gesprek"}'
                f' · {len(rows)} berichten getoond</p>')
        for row in rows:
            pid = account_person(db, "facebook", row["sender_key"]) if row["sender_key"] else None
            author = escape(row["sender_name"])
            if pid is not None:
                author = f'<a href="/person/{pid}">{author}</a>'
            when = (datetime.fromtimestamp(row["timestamp_ms"]/1000,timezone.utc)
                    .strftime("%Y-%m-%d %H:%M")) if row["timestamp_ms"] else ""
            page += (f'<article><strong>{author}</strong> <small>{when}</small>'
                     f'<pre>{escape(row["content"])}</pre></article>')
        return page + footer() + "</html>"


@app.post("/person/new")
def new_person(name: str = Form(...), confirmed: str = Form("")):
    name = " ".join(name.split())
    if not 2 <= len(name) <= 160:
        raise HTTPException(400, "Naam moet tussen 2 en 160 tekens lang zijn")
    with connect() as db:
        matches = possible_duplicates(db, name)
        if matches and confirmed != "yes":
            html = ('<!doctype html><html lang="nl"><meta charset="utf-8">'
                    '<meta name="viewport" content="width=device-width, initial-scale=1">'
                    '<title>Bestaat deze persoon al? · Farley File</title>'
                    '<style>body{font:16px/1.6 system-ui,sans-serif;max-width:780px;'
                    'margin:40px auto;padding:20px;background:#f5f7f6;color:#252b30}'
                    'section{background:#fff;padding:26px;border:1px solid #dde6e5}'
                    'a{color:#087f80}button{background:#087f80;color:#fff;'
                    'border:0;padding:12px 16px;cursor:pointer;font:inherit}'
                    'article{padding:12px 0;border-bottom:1px solid #dde6e5}'
                    '</style><section><h1>Deze persoon ken je misschien al</h1>'
                    f'<p>Je wilt <strong>{escape(name)}</strong> toevoegen, maar '
                    'er bestaat al een profiel met dezelfde naam.</p>')
            for match in matches:
                html += (f'<article><a href="/person/{match["id"]}">'
                         f'{escape(match["name"])}</a>'
                         f' · {escape(match["platforms"] or "handmatig profiel")}</article>')
            html += (f'<p><a href="/">← Annuleren</a></p>'
                     '<p>Toch een afzonderlijke persoon met deze naam?</p>'
                     '<form method="post" action="/person/new">'
                     f'<input type="hidden" name="name" value="{escape(name,quote=True)}">'
                     '<input type="hidden" name="confirmed" value="yes">'
                     '<button type="submit">Toch nieuw profiel aanmaken</button>'
                     '</form></section></html>')
            return HTMLResponse(html)
        try:
            pid = create_person(db, name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(pid), status_code=303)


@app.post("/person/{person_id}/merge")
def merge_duplicate_person(person_id: int, target_id: int = Form(...),
                           confirmed: str = Form("")):
    if confirmed != "yes":
        raise HTTPException(400, "Bevestiging vereist")
    with connect() as db:
        source = person_details(db, person_id)
        target = person_details(db, target_id)
        if source is None or target is None or source[0] == target[0]:
            raise HTTPException(400, "Selecteer twee verschillende bestaande profielen")
        # A manual profile may be merged into an imported profile, not vice versa.
        manually_added = db.execute(
            "SELECT created_manually FROM farley_person_names WHERE person_id=?",
            (source[0],)
        ).fetchone()
        if not manually_added or not manually_added["created_manually"] or source[1]:
            raise HTTPException(400, "Alleen losse, handmatig aangemaakte personen samenvoegen")
        try:
            merge_people(db, target[0], source[0])
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(target_id), status_code=303)


@app.post("/person/{person_id}/delete")
def remove_manual_person(person_id: int, confirmed: str = Form("")):
    if confirmed != "delete":
        raise HTTPException(400, "Bevestiging vereist")
    with connect() as db:
        try:
            delete_person(db, person_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/", status_code=303)


@app.post("/person/{person_id}/name")
def update_person_name(person_id: int, name: str = Form(...)):
    with connect() as db:
        try:
            rename_person(db, person_id, name)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(person_id), status_code=303)


@app.post("/person/{person_id}/job")
def update_person_job(person_id: int, kind: str = Form("new"),
                      job_id: int = Form(0), company: str = Form(""),
                      title: str = Form(""), started: str = Form(""),
                      ended: str = Form(""), note: str = Form("")):
    with connect() as db:
        try:
            if kind not in ("new", "manual", "import"):
                raise ValueError("Onbekend functietype")
            save_job(db, person_id, company, title, started, ended, note,
                     job_id=job_id if kind == "manual" else None,
                     history_id=job_id if kind == "import" else None)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(person_id), status_code=303)


@app.post("/person/{person_id}/job/delete")
def remove_person_job(person_id: int, job_id: int = Form(...)):
    with connect() as db:
        try:
            delete_manual_job(db, person_id, job_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(person_id), status_code=303)


@app.post("/person/{person_id}/attach")
def attach_existing_social(person_id: int, platform: str = Form(...),
                           account: str = Form(...)):
    key = account.strip()
    if platform not in ("linkedin", "instagram", "facebook"):
        raise HTTPException(400, "Onbekend sociaal platform")
    if platform == "instagram":
        key = key.lstrip("@").casefold()
    if platform == "facebook":
        key = "name:" + " ".join(key.casefold().split()).removeprefix("name:")
    with connect() as db:
        destination = person_details(db, person_id)
        if destination is None:
            raise HTTPException(404, "Persoon niet gevonden")
        source_id = account_person(db, platform, key)
        if source_id is None:
            raise HTTPException(400, "Account nog niet geïmporteerd. Gebruik de exacte profiel-URL, gebruikersnaam of Facebook-naam.")
        try:
            merge_people(db, destination[0], source_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(person_id), status_code=303)


@app.get("/", response_class=HTMLResponse)
def index(q: str = "", imported: int = 0, ig_imported: int = -1, fb_imported: int = -1, twitter_imported: int = -1):
    with connect() as db:
        total_contacts = db.execute("SELECT count(*) FROM contacts").fetchone()[0]
        total_messages = db.execute("SELECT count(*) FROM messages").fetchone()[0]
        ig_accounts = db.execute("SELECT count(*) FROM instagram_accounts WHERE follows=1 OR follower=1").fetchone()[0]
        ig_messages_total = db.execute("SELECT count(*) FROM instagram_messages").fetchone()[0]
        ig_results = []
        ig_message_results = []
        fb_results = []
        fb_message_results = []
        fb_people_total = db.execute("SELECT count(*) FROM facebook_people").fetchone()[0]
        fb_message_total = db.execute("SELECT count(*) FROM facebook_messages").fetchone()[0]
        twitter_accounts = db.execute("SELECT COUNT(*) FROM twitter_accounts").fetchone()[0]
        twitter_tweets = db.execute("SELECT COUNT(*) FROM twitter_tweets").fetchone()[0]
        twitter_dms = db.execute("SELECT COUNT(*) FROM twitter_dms").fetchone()[0]
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
        if q.strip():
            fb_results = db.execute(
                "SELECT fb_key,display_name FROM facebook_people WHERE display_name LIKE ? ESCAPE '\\' LIMIT 50",
                (like,),
            ).fetchall()
            fb_message_results = find_facebook_messages(db, q)
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
        if q.strip():
            fb_seen = {account_person(db,"linkedin",row["url"]) if source=="linkedin"
                       else account_person(db,"instagram",row["username"])
                       for source,row in people_results}
            for fb in fb_results:
                pid = account_person(db,"facebook",fb["fb_key"])
                if pid is not None and pid not in fb_seen:
                    people_results.append(("facebook",fb))
                    fb_seen.add(pid)
        if q.strip():
            present_ids = {
                account_person(db, "linkedin", row["url"]) if source == "linkedin"
                else account_person(db, "instagram", row["username"]) if source == "instagram"
                else account_person(db, "facebook", row["fb_key"]) if source == "facebook"
                else row["person_id"]
                for source, row in people_results
            }
            for row in search_manual(db, q):
                pid = row["person_id"]
                if pid not in present_ids:
                    people_results.append(("manual", row))
                    present_ids.add(pid)
    page = f"""<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Farley File</title><link rel="icon" type="image/svg+xml" href="/static/farley-logo.svg"><style>
:root{{--ink:#252b30;--muted:#647078;--accent:#087f80;--edge:#dde6e5;--paper:#fff;--bg:#f5f7f6}}
*{{box-sizing:border-box}}body{{font:16px/1.65 system-ui,-apple-system,Segoe UI,sans-serif;max-width:1050px;margin:0 auto;padding:38px 24px 90px;background:var(--bg);color:var(--ink)}}
h1,h2,h3{{line-height:1.25;letter-spacing:-.035em}}h1{{font-size:clamp(2.3rem,5vw,4rem);margin:.35em 0 .15em}}h2{{font-size:1.45rem}}
a{{color:var(--accent);text-decoration-thickness:1px;text-underline-offset:3px}}
header{{border-bottom:4px solid var(--accent);padding-bottom:23px;margin-bottom:30px}}\n.app-heading{{display:flex;align-items:center;gap:18px;margin-top:8px}}.app-heading h1{{margin:0}}.app-logo{{width:clamp(64px,10vw,88px);height:auto;border-radius:15px;flex-shrink:0}}
.brand{{font-size:.83rem;text-transform:uppercase;letter-spacing:.17em;font-weight:800;color:var(--accent)}}
section{{background:var(--paper);padding:clamp(20px,4vw,32px);margin:22px 0;border:1px solid var(--edge);border-radius:5px;box-shadow:0 8px 28px #192f2d08}}
input[type=text]{{padding:13px 15px;width:min(78%,650px);border:1px solid #bdcbcb;border-radius:4px;font:inherit}}
button{{background:var(--accent);color:white;border:0;padding:14px 20px;border-radius:4px;font:inherit;font-weight:700;cursor:pointer}}
button:hover{{filter:brightness(.9)}}.add-person{{margin:16px 0 22px;background:#fff;padding:13px 20px;border:1px solid var(--edge);border-radius:5px}}.add-person summary{{cursor:pointer;color:var(--accent);font-weight:700;list-style:none}}.add-person summary::-webkit-details-marker{{display:none}}.plus-icon{{display:inline-flex;align-items:center;justify-content:center;width:28px;height:28px;border-radius:50%;background:#e4f3f0;font-size:1.35rem;margin-right:7px}}.add-person[open] .plus-icon{{transform:rotate(45deg)}}article{{padding:16px 0;border-top:1px solid var(--edge)}}
article strong{{font-size:1.08rem}}small,.muted{{color:var(--muted)}}
pre{{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}}
.badge{{display:inline-block;padding:3px 10px;background:#e4f3f0;color:#075f5c;border-radius:3px;font-size:.85rem;font-weight:700}}
@media(max-width:550px){{input[type=text]{{width:100%;margin-bottom:10px}}button{{width:100%}}}}
</style><header><span class="brand">Elegant Chaos / Labs</span><div class="app-heading"><img class="app-logo" src="/static/farley-logo.svg" alt="" width="82" height="82"><h1>Farley File</h1></div><span class="muted">Je netwerk, opnieuw ontdekt.</span><nav style="margin-top:16px"><a href="/" aria-label="Naar de startpagina">⌂ Home</a> · <a href="/activity">Netwerkactiviteit</a> · <a href="/matches">Mogelijke koppelingen</a> · <a href="/tags">Netwerktags</a></nav></header>
    <p>LinkedIn: {total_contacts} contacten · {total_messages} berichten<br>Instagram: {ig_accounts} accounts · {ig_messages_total} inbox-berichten<br>Facebook: {fb_people_total} personen · {fb_message_total} berichten<br>Twitter: {twitter_accounts} historische accounts · {twitter_tweets} tweets · {twitter_dms} DM’s</p>
    {("<p>Geïmporteerde rijen: " + str(imported) + "</p>") if imported else ""}
    {("<p>Instagram: " + str(ig_imported) + " inbox-berichten verwerkt.</p>") if ig_imported >= 0 else ""}
    {("<p>Facebook: " + str(fb_imported) + " nieuwe berichten verwerkt.</p>") if fb_imported >= 0 else ""}
    {("<p>Twitter: " + str(twitter_imported) + " tweets uit archief verwerkt.</p>") if twitter_imported >= 0 else ""}
    <details class="add-person"><summary><span class="plus-icon" aria-hidden="true">+</span> Persoon toevoegen</summary>
    <p class="muted">Ook zonder LinkedIn, Instagram of Facebook. Later kun je accounts toevoegen.</p>
    <form method="post" action="/person/new">
    <input type="text" name="name" required maxlength="160" placeholder="Voor- en achternaam">
    <button type="submit">Toevoegen</button></form></details>
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
        page += '<section><h2>Mogelijk dezelfde persoon</h2><p class="muted">Controleer de profielen voordat je koppelt.</p>'
        for contact, account in suggestions:
            name = escape((contact["first_name"] or "") + " " + (contact["last_name"] or ""))
            handle = escape(account["username"])
            page += (f'<article><strong>{name}</strong> (LinkedIn) ↔ '
                     f'<a href="https://www.instagram.com/{quote(account["username"], safe="")}/" '
                     f'target="_blank" rel="noopener noreferrer">@{handle}</a>'
                     f'<form method="post" action="/profile-link">'
                     f'<input type="hidden" name="linkedin_url" value="{escape(contact["url"], quote=True)}">'
                     f'<input type="hidden" name="instagram_username" value="{escape(account["username"], quote=True)}">'
                     f'<button type="submit">Zelfde persoon — koppelen</button></form>'
                     f'<form method="post" action="/profile-link">'
                     f'<input type="hidden" name="linkedin_url" value="{escape(contact["url"], quote=True)}">'
                     f'<input type="hidden" name="instagram_username" value="{escape(account["username"], quote=True)}">'
                     f'<input type="hidden" name="action" value="reject">'
                     f'<button type="submit" style="background:#69767a">Geen koppeling</button>'
                     f'</form></article>')
        page += '</section>'
    if q.strip():
        page += f'<section><h2>Personen ({len(people_results)} getoond)</h2>'
        for source, person in people_results:
            if source == "facebook":
                person_link = "/person/" + str(account_person(db, "facebook", person["fb_key"]))
                display_name = person["display_name"]
                social_labels = "Facebook"
                note = "Facebook-contact"
                count = ""
            elif source == "manual":
                display_name = person["display_name"]
                person_link = "/person/" + str(person["person_id"])
                social_labels = "Persoonlijk toegevoegd"
                note = "Persoonlijk dossier"
                count = ""
            elif source == "linkedin":
                display_name = farley_display_name(db, account_person(db, "linkedin", person["url"]))
                person_link = "/person/" + str(account_person(db, "linkedin", person["url"]))
                with connect() as links_db:
                    linked_handles = [r["instagram_username"] for r in links_db.execute(
                        "SELECT instagram_username FROM profile_links WHERE linkedin_url=? ORDER BY instagram_username",
                        (person["url"],)
                    )]
                social_labels = "LinkedIn" + (" · Instagram " + ", ".join("@" + h for h in linked_handles) if linked_handles else "")
                note = f'{person["position"] or ""} · {person["company"] or ""}'
                count = f'{person["message_count"]} LinkedIn-berichten'
            else:
                display_name = farley_display_name(db, account_person(db, "instagram", person["username"]))
                person_link = "/person/" + str(account_person(db, "instagram", person["username"]))
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
        sender_lookup = contact_lookup(db) if messages else {}
        for message in messages:
            sender_name = escape(message["sender"] or "Onbekende afzender")
            sender_id = author_profile(message, sender_lookup)
            sender_html = (f'<a href="/person/{sender_id}">{sender_name}</a>'
                           if sender_id is not None else sender_name)
            page += (f'<article><strong>{escape(message["subject"] or "(geen onderwerp)")}'
                     f'</strong><br><small>{escape(message["date"] or "")} · '
                     f'{sender_html}</small>'
                     f'<pre>{escape((message["content"] or "")[:700])}</pre></article>')
        page += "</section>"
        page += f'<section><h2>Instagram-berichten ({len(ig_message_results)} getoond)</h2>'
        for msg in ig_message_results:
            page += (f'<article><strong>{escape(msg["sender"])}</strong> '
                     f'<small>{escape(msg["date"][:10])}</small>'
                     f'<pre>{escape(msg["content"][:700])}</pre></article>')
        page += "</section>"
        page += f'<section><h2>Facebook-berichten ({len(fb_message_results)} getoond)</h2>'
        for fb_msg in fb_message_results:
            pid = account_person(db, "facebook", fb_msg["sender_key"]) if fb_msg["sender_key"] else None
            sender = escape(fb_msg["sender_name"])
            if pid is not None:
                sender = f'<a href="/person/{pid}">{sender}</a>'
            page += (f'<article><strong>{sender}</strong> <small>· Facebook</small><br>'
                     f'<a href="/facebook/thread/{fb_msg["thread_id"]}">Volledig gesprek bekijken</a>'
                     f'<pre>{escape(fb_msg["content"][:700])}</pre></article>')
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
        <button>Importeer Instagram</button></form>
        <hr style="border:0;border-top:1px solid #dde6e5;margin:24px 0">
        <p><strong>Facebook-export (ZIP, maximaal 128 MB)</strong></p>
        <p>Alleen contacten en tekstberichten. Media worden overgeslagen.
        Facebook-personen worden niet automatisch gekoppeld op basis van naam.</p>
        <form action="/upload-facebook" method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".zip" required>
        <button>Importeer Facebook</button></form>
        <hr style="border:0;border-top:1px solid #dde6e5;margin:24px 0">
        <p><strong>Twitter-archief (ZIP, maximaal 100 MB)</strong></p>
        <p>Importeert tweets, replies, vermeldingen, DM’s en historische account-ID’s. 
        Bewaart oude gebruikersnamen als waarnemingen; koppelt nooit vanzelf aan een ander platform.
        Bevat privéberichten: bewaar de ZIP veilig.</p>
        <form action="/upload-twitter" method="post" enctype="multipart/form-data">
        <input type="file" name="file" accept=".zip" required>
        <button>Importeer Twitter</button></form></details>"""
    return page + footer() + "</html>"


@app.get("/contact")
def contact_detail(url: str):
    """Redirect older saved contact links to the stable person ID."""
    with connect() as db:
        pid = account_person(db, "linkedin", url)
    if pid is None:
        raise HTTPException(404, "Contact niet gevonden")
    return RedirectResponse("/person/" + str(pid), status_code=303)


@app.get("/person", response_class=HTMLResponse)
def person_detail(linkedin_url: str = "", instagram_username: str = "", find: str = ""):
    """Redirect historical profile URLs; keep Obsidian links permanent."""
    with connect() as db:
        pid = (account_person(db, "linkedin", linkedin_url) if linkedin_url else
               account_person(db, "instagram", instagram_username))
    if pid is None:
        raise HTTPException(404, "Persoon niet gevonden")
    destination = "/person/" + str(pid)
    if find:
        destination += "?find=" + quote(find, safe="")
    return RedirectResponse(destination, status_code=303)


@app.get("/person/{person_id}", response_class=HTMLResponse)
def person_by_id(person_id: int, find: str = ""):
    with connect() as db:
        info = person_details(db, person_id)
        if info is None:
            raise HTTPException(404, "Persoon niet gevonden")
        current_id = info[0]
        if current_id != person_id:
            destination = "/person/" + str(current_id)
            if find:
                destination += "?find=" + quote(find, safe="")
            return RedirectResponse(destination, status_code=303)
        return render_profile(db, person_id=current_id,
                              find=find, footer=footer,
                              contact_timeline=contact_timeline,
                              profile_key=profile_key)


@app.post("/person/{person_id}/context")
def update_person_context(person_id: int, how_known: str = Form(""),
                          background: str = Form(""), interests: str = Form(""),
                          remember: str = Form(""), network_tags: str = Form("")):
    with connect() as db:
        try:
            save_context(db, person_id, how_known=how_known,
                         background=background, interests=interests,
                         remember=remember, network_tags=network_tags)
            current_id = person_details(db, person_id)[0]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(current_id), status_code=303)


@app.get("/tags", response_class=HTMLResponse)
def tag_overview():
    with connect() as db:
        rows = db.execute(
            "SELECT tag,COUNT(*) AS total FROM farley_tags GROUP BY tag ORDER BY total DESC,tag"
        ).fetchall()
    html = """<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Netwerktags · Farley File</title>
    <style>
    body{font:16px/1.65 system-ui,sans-serif;max-width:1000px;margin:0 auto;
      padding:38px 24px;background:#f5f7f6;color:#252b30}
    a{color:#087f80}section{background:white;border:1px solid #dde6e5;
      padding:22px;margin:20px 0;border-radius:5px}
    .tag{display:inline-block;margin:6px;padding:8px 12px;background:#e4f3f0;border-radius:4px}
    </style><header><h1>Netwerktags</h1><nav><a href="/">⌂ Home</a> ·
    <a href="/activity">Netwerkactiviteit</a> · <a href="/matches">Mogelijke koppelingen</a> ·
    <a href="/tags">Netwerktags</a></nav></header><section>
    <p>Een persoon kan meerdere tags hebben. Groepen mogen elkaar overlappen.</p>"""
    if not rows:
        html += '<p>Nog geen tags. Voeg er een toe op een persoonspagina.</p>'
    for row in rows:
        html += (f'<a class="tag" href="/tags/{quote(row["tag"],safe="")}">'
                 f'#{escape(row["tag"])} ({row["total"]})</a>')
    return html + "</section>" + footer() + "</html>"


@app.get("/tags/{tag}", response_class=HTMLResponse)
def tag_members(tag: str):
    with connect() as db:
        members = db.execute(
            """SELECT DISTINCT t.person_id FROM farley_tags t
               WHERE t.tag=? COLLATE NOCASE ORDER BY t.person_id""", (tag,)
        ).fetchall()
        items = []
        for member in members:
            info = person_details(db, member["person_id"])
            if not info:
                continue
            pid, accounts = info
            linked = next((a["account_key"] for a in accounts if a["platform"]=="linkedin"), "")
            insta = next((a["account_key"] for a in accounts if a["platform"]=="instagram"), "")
            name = ""
            if linked:
                row = db.execute("SELECT first_name,last_name FROM contacts WHERE url=?", (linked,)).fetchone()
                if row:
                    name = " ".join(filter(None, (row["first_name"], row["last_name"])))
            items.append((pid, name or "@" + insta))
    html = ("""<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Netwerktag · Farley File</title>
    <style>body{font:16px/1.65 system-ui,sans-serif;max-width:1000px;margin:0 auto;
    padding:38px 24px;background:#f5f7f6;color:#252b30}a{color:#087f80}
    section{background:white;border:1px solid #dde6e5;padding:22px;margin:20px 0}
    article{padding:12px 0;border-top:1px solid #dde6e5}</style>"""
    + f'<p><a href="/tags">← Alle netwerktags</a></p><h1>#{escape(tag)}</h1>'
    + f'<section><p>{len(items)} personen</p>')
    for pid, name in sorted(set(items), key=lambda x:x[1].casefold()):
        html += f'<article><a href="/person/{pid}">{escape(name)}</a></article>'
    return html + "</section>" + footer() + "</html>"


@app.post("/obsidian-note/add")
def obsidian_note_add(person_id: int = Form(...), title: str = Form(...),
                      target: str = Form(...)):
    with connect() as db:
        try:
            add_note(db, person_id, title, target)
            current_id = person_details(db, person_id)[0]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(current_id), status_code=303)


@app.post("/obsidian-note/delete")
def obsidian_note_delete(person_id: int = Form(...), note_id: int = Form(...)):
    with connect() as db:
        try:
            remove_note(db, person_id, note_id)
            current_id = person_details(db, person_id)[0]
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/person/" + str(current_id), status_code=303)


@app.get("/activity", response_class=HTMLResponse)
def activity_page(source: str = "all"):
    with connect() as db:
        overview = render_network_activity(db, source)
    page = """<!doctype html><html lang="nl"><meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Netwerkactiviteit · Farley File</title>
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


@app.post("/facebook-match")
def facebook_match(facebook_key: str = Form(...), target_person_id: int = Form(...),
                   action: str = Form(...), confirmed: str = Form("")):
    if action not in ("link", "reject"):
        raise HTTPException(400, "Onbekende actie")
    with connect() as db:
        source_id = account_person(db, "facebook", facebook_key)
        target = person_details(db, target_person_id)
        if source_id is None or target is None:
            raise HTTPException(404, "Profiel niet gevonden")
        if action == "reject":
            reject_facebook_match(db, facebook_key, target[0])
        else:
            if confirmed != "yes":
                raise HTTPException(400, "Bevestiging vereist")
            if source_id == target[0]:
                raise HTTPException(400, "Deze profielen zijn al gekoppeld")
            # Facebook exports can identify people by name alone. Never merge
            # without an explicit target and a user confirmation.
            try:
                merge_people(db, target[0], source_id)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/matches?linked=1", status_code=303)


@app.post("/smart-match")
def smart_match(person_a: int = Form(...), person_b: int = Form(...),
                action: str = Form(...), confirmed: str = Form("")):
    if action not in ("link", "reject"):
        raise HTTPException(400, "Ongeldige actie")
    with connect() as db:
        first = person_details(db, person_a)
        second = person_details(db, person_b)
        if first is None or second is None or first[0] == second[0]:
            raise HTTPException(400, "Selecteer twee verschillende bestaande personen")
        if action == "reject":
            reject_smart_match(db, first[0], second[0])
        else:
            if confirmed != "yes":
                raise HTTPException(400, "Bevestig eerst de samenvoeging")
            # Validate that the proposal is still current (also excludes
            # conflicting LinkedIn and Facebook accounts).
            valid = any({c["source_id"],c["target_id"]} == {first[0],second[0]}
                        for c in smart_candidates(db))
            if not valid:
                raise HTTPException(400, "Deze koppeling is niet meer voorgesteld; vernieuw de pagina")
            try:
                merge_people(db, person_b, person_a)
            except ValueError as exc:
                raise HTTPException(400, str(exc)) from exc
    return RedirectResponse("/matches?linked=1#smart",status_code=303)


@app.get("/matches", response_class=HTMLResponse)
def possible_matches(page: int = 1, smart_page: int = 1, linked: int = 0):
    with connect() as db:
        suggestions = all_candidates(db)
        smart_suggestions = smart_candidates(db)
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
    <title>Mogelijke koppelingen · Farley File</title>
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
    smart_total = len(smart_suggestions)
    smart_size = 30
    smart_pages = max(1, (smart_total + smart_size - 1) // smart_size)
    smart_page = min(max(1, smart_page), smart_pages)
    smart_visible = smart_suggestions[(smart_page-1)*smart_size:smart_page*smart_size]
    html += (f'<section id="smart"><h2>Slimme koppelvoorstellen ({smart_total})</h2>'
             '<p class="muted">LinkedIn, Facebook, Instagram en handmatige profielen. '
             'Je ziet waarom twee personen mogelijk dezelfde zijn. '
             '<strong>Dit zijn aanwijzingen, geen identiteitsbewijs.</strong> '
             'Er wordt nooit automatisch samengevoegd. '
             'De gegevens van beide profielen blijven bij een bevestigde koppeling behouden.</p>')
    if not smart_visible:
        html += '<p>Geen nieuwe voorstellen op deze pagina.</p>'
    for item in smart_visible:
        source_id, target_id = item["source_id"], item["target_id"]
        evidence = "; ".join(item["reasons"])
        html += (f'<article><strong>{escape(item["source_name"])}</strong> '
                 f'({escape(item["source_platforms"])}) ↔ '
                 f'<strong>{escape(item["target_name"])}</strong> '
                 f'({escape(item["target_platforms"])})<br>'
                 f'<small>Waarom: {escape(evidence)}</small><br>'
                 f'<a href="/person/{source_id}">Profiel 1 bekijken</a> · '
                 f'<a href="/person/{target_id}">Profiel 2 bekijken</a>'
                 f'<form method="post" action="/smart-match" '
                 'onsubmit="return confirm(\'Weet je zeker dat dit dezelfde persoon is? '
                 'Samenvoegen kan niet automatisch ongedaan worden gemaakt.\')">'
                 f'<input type="hidden" name="person_a" value="{source_id}">'
                 f'<input type="hidden" name="person_b" value="{target_id}">'
                 '<input type="hidden" name="action" value="link">'
                 '<input type="hidden" name="confirmed" value="yes">'
                 '<button type="submit">Zelfde persoon — samenvoegen</button></form>'
                 '<form method="post" action="/smart-match">'
                 f'<input type="hidden" name="person_a" value="{source_id}">'
                 f'<input type="hidden" name="person_b" value="{target_id}">'
                 '<input type="hidden" name="action" value="reject">'
                 '<button type="submit" style="background:#69767a">Niet dezelfde persoon</button>'
                 '</form></article>')
    html += f'<p>Voorstellen: pagina {smart_page} van {smart_pages}. '
    if smart_page > 1:
        html += f'<a href="/matches?page={page}&smart_page={smart_page-1}#smart">← Vorige</a> · '
    if smart_page < smart_pages:
        html += f'<a href="/matches?page={page}&smart_page={smart_page+1}#smart">Volgende →</a>'
    html += '</p></section>'
    return html + footer() + '</html>'
