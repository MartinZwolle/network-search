"""Facebook JSON-export importer, retaining text only (never media assets).

Facebook exports typically have friend names without stable public profile URLs.
A facebook:name:<normalized-name> identity stays separate from LinkedIn/Instagram
until the user deliberately associates profiles. Same-name collisions within a
Facebook export cannot be resolved reliably; do not treat those IDs as verified.
"""
import hashlib
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from html import escape

from app.person_ids import ensure_account, account_person

MAX_ARCHIVE_SIZE = 128 * 1024 * 1024
MAX_JSON_UNCOMPRESSED = 12 * 1024 * 1024
MAX_TOTAL_JSON = 70 * 1024 * 1024
MAX_FILES = 12000


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS facebook_people (
        fb_key TEXT PRIMARY KEY,
        display_name TEXT NOT NULL,
        friend_since TEXT NOT NULL DEFAULT '',
        friend INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS facebook_threads (
        id TEXT PRIMARY KEY,
        title TEXT NOT NULL DEFAULT '',
        participant_names TEXT NOT NULL DEFAULT '',
        is_group INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS facebook_thread_people (
        thread_id TEXT NOT NULL REFERENCES facebook_threads(id),
        fb_key TEXT NOT NULL REFERENCES facebook_people(fb_key),
        PRIMARY KEY(thread_id, fb_key)
    );
    CREATE INDEX IF NOT EXISTS idx_fb_thread_people_key
      ON facebook_thread_people(fb_key);
    CREATE TABLE IF NOT EXISTS facebook_messages (
        message_key TEXT PRIMARY KEY,
        thread_id TEXT NOT NULL REFERENCES facebook_threads(id),
        sender_name TEXT NOT NULL DEFAULT '',
        sender_key TEXT NOT NULL DEFAULT '',
        timestamp_ms INTEGER NOT NULL DEFAULT 0,
        content TEXT NOT NULL DEFAULT ''
    );
    CREATE INDEX IF NOT EXISTS idx_fb_messages_thread
      ON facebook_messages(thread_id, timestamp_ms);
    CREATE VIRTUAL TABLE IF NOT EXISTS facebook_messages_fts
      USING fts5(message_key UNINDEXED, content, sender_name);
    """)


def _name(value):
    return " ".join((value or "").split()).strip()


def _key(name):
    text = _name(name).casefold()
    if not text or len(text) > 200:
        return ""
    return "name:" + text


def _timestamp(seconds):
    try:
        return datetime.fromtimestamp(int(seconds),timezone.utc).date().isoformat()
    except (ValueError, OverflowError, OSError, TypeError):
        return ""


def _person(db, name, friend=False, timestamp=""):
    name = _name(name)
    key = _key(name)
    if not key:
        return ""
    db.execute(
        """INSERT INTO facebook_people(fb_key,display_name,friend_since,friend)
           VALUES (?,?,?,?)
           ON CONFLICT(fb_key) DO UPDATE SET
             friend=MAX(facebook_people.friend, excluded.friend),
             friend_since=CASE WHEN excluded.friend_since <> ''
                 THEN excluded.friend_since ELSE facebook_people.friend_since END""",
        (key,name,timestamp,int(friend)),
    )
    ensure_account(db, "facebook", key)
    return key


def _safe_json(zipfile_obj, member, remaining):
    if member.file_size > MAX_JSON_UNCOMPRESSED or member.file_size > remaining:
        raise ValueError("Een JSON-bestand in de Facebook-export is te groot")
    with zipfile_obj.open(member) as stream:
        raw = stream.read(MAX_JSON_UNCOMPRESSED + 1)
    if len(raw) > MAX_JSON_UNCOMPRESSED:
        raise ValueError("Facebook JSON-bestand overschrijdt de veiligheidslimiet")
    return json.loads(raw.decode("utf-8-sig"))


def import_archive(db, content):
    if len(content) > MAX_ARCHIVE_SIZE:
        raise ValueError("Facebook-archief is te groot (maximaal 128 MB); filter mediabestanden")
    counts = {"friends":0,"threads":0,"messages":0,"people":0}
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except (zipfile.BadZipFile, OSError) as exc:
        raise ValueError("Geen geldig ZIP-bestand") from exc
    with archive as z:
        members = z.infolist()
        if len(members) > MAX_FILES:
            raise ValueError("Te veel bestanden in het Facebook-archief")
        total_json = 0
        friend_docs = []
        thread_docs = []
        for member in members:
            path = member.filename.replace("\\","/").casefold()
            if not path.endswith(".json") or member.is_dir():
                continue
            # Ignore photos, posts and all other unrelated export data.
            if path.endswith("/friends/your_friends.json"):
                friend_docs.append(member)
            elif re.search(r"/inbox/[^/]+/message_\d+\.json$",path):
                thread_docs.append(member)
        if not friend_docs and not thread_docs:
            raise ValueError("Geen Facebook-vriendenlijst of inboxberichten gevonden")
        for member in friend_docs + thread_docs:
            total_json += member.file_size
            if total_json > MAX_TOTAL_JSON:
                raise ValueError("Te veel JSON-tekst; splits de Facebook-export op")
            data = _safe_json(z, member, MAX_TOTAL_JSON)
            if member in friend_docs:
                if not isinstance(data,dict):
                    continue
                friends = data.get("friends_v2",[])
                if not isinstance(friends,list):
                    continue
                for friend in friends:
                    if not isinstance(friend,dict):
                        continue
                    if _person(db,friend.get("name"),True,_timestamp(friend.get("timestamp"))):
                        counts["friends"] += 1
                continue
            if not isinstance(data,dict):
                continue
            participants = data.get("participants") or []
            messages = data.get("messages") or []
            if not isinstance(participants,list) or not isinstance(messages,list):
                continue
            # Using the export's thread folder as identity avoids guessing from
            # title; preserve uniqueness even for repeated participant lists.
            path = member.filename.replace("\\","/")
            thread_folder = path.rsplit("/",1)[0].split("/")[-1]
            thread_id = hashlib.sha256(thread_folder.encode("utf-8")).hexdigest()[:28]
            names = [_name(p.get("name")) for p in participants if isinstance(p,dict)]
            names = list(dict.fromkeys(n for n in names if n))
            db.execute(
                """INSERT INTO facebook_threads(id,title,participant_names,is_group)
                   VALUES (?,?,?,?)
                   ON CONFLICT(id) DO UPDATE SET
                     title=excluded.title,participant_names=excluded.participant_names,
                     is_group=excluded.is_group""",
                (thread_id,_name(data.get("title")) or ", ".join(names),
                 json.dumps(names,ensure_ascii=False), int(len(names)>2)),
            )
            counts["threads"] += 1
            for name in names:
                key = _person(db,name)
                if key:
                    db.execute(
                        "INSERT OR IGNORE INTO facebook_thread_people(thread_id,fb_key) VALUES (?,?)",
                        (thread_id,key),
                    )
            for index, msg in enumerate(messages):
                if not isinstance(msg,dict):
                    continue
                sender_name = _name(msg.get("sender_name"))
                key = _person(db,sender_name)
                if key:
                    db.execute(
                        "INSERT OR IGNORE INTO facebook_thread_people(thread_id,fb_key) VALUES (?,?)",
                        (thread_id,key),
                    )
                body = msg.get("content")
                if not isinstance(body,str) or not body.strip():
                    continue  # no attachment payloads or media
                try:
                    stamp = int(msg.get("timestamp_ms",0))
                except (ValueError,TypeError):
                    stamp = 0
                # The repeated export preserves a stable message payload.
                message_id = hashlib.sha256(
                    (thread_id+"\0"+str(stamp)+"\0"+sender_name+"\0"+body).encode("utf-8")
                ).hexdigest()
                cur = db.execute(
                    """INSERT OR IGNORE INTO facebook_messages
                       (message_key,thread_id,sender_name,sender_key,timestamp_ms,content)
                       VALUES (?,?,?,?,?,?)""",
                    (message_id,thread_id,sender_name,key,stamp,body),
                )
                if cur.rowcount:
                    db.execute(
                        "INSERT INTO facebook_messages_fts VALUES (?,?,?)",
                        (message_id,body,sender_name),
                    )
                    counts["messages"] += 1
    counts["people"] = db.execute("SELECT count(*) FROM facebook_people").fetchone()[0]
    return counts


def find_messages(db, query, limit=30):
    """Use a safe quoted FTS phrase, or no results for malformed input."""
    words = [word for word in re.split(r"\s+",query.strip()) if word]
    if not words:
        return []
    phrase = " ".join(words).replace('"','""')
    try:
        return db.execute(
            """SELECT m.* FROM facebook_messages_fts f
               JOIN facebook_messages m ON m.message_key=f.message_key
               WHERE facebook_messages_fts MATCH ?
               ORDER BY bm25(facebook_messages_fts) LIMIT ?""",
            ('"'+phrase+'"',limit),
        ).fetchall()
    except Exception as exc:
        # Queries are user input; never silently return incorrect data on
        # schema errors. FTS errors from empty phrases give no matches.
        if "fts5" in str(exc).lower() or "syntax" in str(exc).lower():
            return []
        raise
