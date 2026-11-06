"""Import selected Instagram JSON data from official Meta ZIP exports.

Allowed paths: followers, following, and direct inbox messages.
Message requests, synced contacts, broadcast, and media are always excluded.
Instagram identities deliberately remain separate from LinkedIn contacts.
"""
import hashlib
import io
import json
import re
import sqlite3
import zipfile
from datetime import datetime, timezone


MAX_ARCHIVE = 80 * 1024 * 1024
MAX_TOTAL_JSON = 80 * 1024 * 1024
MAX_JSON_FILE = 20 * 1024 * 1024
MAX_MEMBERS = 6000


def normalize_name(value):
    return (value or "").strip().lstrip("@").casefold()


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS instagram_accounts (
        username TEXT PRIMARY KEY, follows INTEGER NOT NULL DEFAULT 0,
        follower INTEGER NOT NULL DEFAULT 0, updated_at TEXT NOT NULL);
    CREATE TABLE IF NOT EXISTS instagram_messages (
        message_key TEXT PRIMARY KEY, thread TEXT NOT NULL,
        sender TEXT NOT NULL, date TEXT NOT NULL, content TEXT NOT NULL);
    CREATE INDEX IF NOT EXISTS idx_instagram_sender
        ON instagram_messages(sender);
    """)


def entries(payload, following=False):
    if following:
        payload = payload.get("relationships_following", []) if isinstance(payload, dict) else []
    if not isinstance(payload, list):
        return set()
    result = set()
    for item in payload:
        if not isinstance(item, dict):
            continue
        strings = item.get("string_list_data", [])
        raw = (item.get("title") if following else "") or (
            strings[0].get("value", "") if strings and isinstance(strings[0], dict) else "")
        name = normalize_name(raw)
        if re.fullmatch(r"[a-z0-9_.]{1,30}", name):
            result.add(name)
    return result


def import_archive(db, content):
    if len(content) > MAX_ARCHIVE:
        raise ValueError("Instagram ZIP is te groot (maximaal 80 MB)")
    try:
        archive = zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as err:
        raise ValueError("Ongeldig ZIP-bestand") from err
    with archive:
        members = archive.infolist()
        if len(members) > MAX_MEMBERS:
            raise ValueError("Te veel bestanden in het ZIP-archief")
        selected = []
        for member in members:
            name = member.filename.replace("\\", "/").lower()
            path = "/" + name.lstrip("/")
            follow = (path.endswith("/connections/followers_and_following/following.json")
                      or re.search(r"/connections/followers_and_following/followers_\\d+\\.json$", path))
            inbox = ("/your_instagram_activity/messages/inbox/" in path
                     and re.search(r"/message_\\d+\\.json$", path))
            if member.is_dir() or not (follow or inbox):
                continue
            if member.file_size > MAX_JSON_FILE:
                raise ValueError("Een JSON-bestand is te groot")
            selected.append((member, follow, inbox))
        if sum(m.file_size for m, _, _ in selected) > MAX_TOTAL_JSON:
            raise ValueError("Te veel uitgepakte JSON-data")
        if not selected:
            raise ValueError("Geen ondersteunde Instagram-volgers of inbox-berichten gevonden")
        following, followers, messages = set(), set(), {}
        for member, follow, inbox in selected:
            with archive.open(member) as handle:
                data = json.load(io.TextIOWrapper(handle, encoding="utf-8-sig"))
            if follow:
                if member.filename.lower().endswith("/following.json"):
                    following |= entries(data, following=True)
                else:
                    followers |= entries(data)
            if inbox and isinstance(data, dict):
                thread = str(data.get("thread_path") or member.filename.rsplit("/", 1)[0])
                for msg in data.get("messages", []):
                    if not isinstance(msg, dict):
                        continue
                    sender = str(msg.get("sender_name") or "").strip()
                    timestamp = msg.get("timestamp_ms")
                    try:
                        date = datetime.fromtimestamp(int(timestamp)/1000, tz=timezone.utc).isoformat()
                    except (TypeError, ValueError, OverflowError, OSError):
                        continue
                    body = msg.get("content")
                    if not isinstance(body, str) or not body.strip():
                        continue
                    # Stable across repeated imports, including for identical text sent at other times.
                    key = hashlib.sha256(
                        json.dumps([thread, sender, timestamp, body], ensure_ascii=False).encode()
                    ).hexdigest()
                    messages[key] = (key, thread, sender, date, body)
        now = datetime.now(timezone.utc).isoformat()
        # New snapshots replace follow/follower flags, without altering history of messages.
        # Only update flags for categories actually present in the archive.
        has_following = any(m.filename.lower().endswith("/following.json") for m, a, _ in selected if a)
        has_followers = any(re.search(r"/followers_\\d+\\.json$", m.filename.lower()) for m, a, _ in selected if a)
        if has_following:
            db.execute("UPDATE instagram_accounts SET follows=0")
        if has_followers:
            db.execute("UPDATE instagram_accounts SET follower=0")
        for username in following | followers:
            db.execute("""INSERT INTO instagram_accounts(username,follows,follower,updated_at)
              VALUES (?,?,?,?) ON CONFLICT(username) DO UPDATE SET
              follows=CASE WHEN ? THEN excluded.follows ELSE instagram_accounts.follows END,
              follower=CASE WHEN ? THEN excluded.follower ELSE instagram_accounts.follower END,
              updated_at=excluded.updated_at""",
              (username, int(username in following), int(username in followers), now,
               int(has_following), int(has_followers)))
        db.executemany("""INSERT OR IGNORE INTO instagram_messages
            (message_key,thread,sender,date,content) VALUES (?,?,?,?,?)""", messages.values())
        return {"following": len(following), "followers": len(followers),
                "inbox_messages": len(messages)}
