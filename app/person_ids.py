"""Persistent person identifiers and optional Obsidian note links.

External account names are mutable; /person/<id> stays valid when social
accounts change. Old IDs redirect after two people are explicitly merged.
"""
from urllib.parse import urlsplit


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS farley_people (
        id INTEGER PRIMARY KEY AUTOINCREMENT
    );
    CREATE TABLE IF NOT EXISTS farley_accounts (
        platform TEXT NOT NULL,
        account_key TEXT NOT NULL,
        person_id INTEGER NOT NULL REFERENCES farley_people(id),
        PRIMARY KEY(platform, account_key)
    );
    CREATE INDEX IF NOT EXISTS idx_farley_accounts_person ON farley_accounts(person_id);
    CREATE TABLE IF NOT EXISTS farley_aliases (
        old_id INTEGER PRIMARY KEY,
        current_id INTEGER NOT NULL
    );
    CREATE TABLE IF NOT EXISTS farley_notes (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        person_id INTEGER NOT NULL REFERENCES farley_people(id),
        title TEXT NOT NULL,
        target TEXT NOT NULL
    );
    """)


def resolve(db, person_id):
    """Follow old ID aliases; guard against loops."""
    pid = int(person_id)
    seen = set()
    while True:
        if pid in seen:
            raise ValueError("Ongeldige persoonskoppeling")
        seen.add(pid)
        row = db.execute("SELECT current_id FROM farley_aliases WHERE old_id=?", (pid,)).fetchone()
        if row is None:
            return pid
        pid = row["current_id"]


def account_person(db, platform, key):
    row = db.execute(
        "SELECT person_id FROM farley_accounts WHERE platform=? AND account_key=?",
        (platform, key),
    ).fetchone()
    return resolve(db, row["person_id"]) if row else None


def ensure_account(db, platform, key):
    pid = account_person(db, platform, key)
    if pid is not None:
        return pid
    cursor = db.execute("INSERT INTO farley_people DEFAULT VALUES")
    pid = cursor.lastrowid
    db.execute(
        "INSERT INTO farley_accounts(platform,account_key,person_id) VALUES (?,?,?)",
        (platform, key, pid),
    )
    return pid


def merge(db, linkedin_url, instagram_username):
    """Keep the LinkedIn person's stable ID, retain old Instagram ID as alias."""
    dest = ensure_account(db, "linkedin", linkedin_url)
    source = ensure_account(db, "instagram", instagram_username)
    if source == dest:
        return dest
    db.execute("UPDATE farley_accounts SET person_id=? WHERE person_id=?", (dest, source))
    db.execute("UPDATE farley_notes SET person_id=? WHERE person_id=?", (dest, source))
    db.execute("UPDATE farley_aliases SET current_id=? WHERE current_id=?", (dest, source))
    db.execute("INSERT OR REPLACE INTO farley_aliases VALUES (?,?)", (source, dest))
    return dest


def detach_instagram(db, instagram_username):
    """Separating a profile does not renumber the remaining person's ID."""
    row = db.execute(
        "SELECT person_id FROM farley_accounts WHERE platform='instagram' AND account_key=?",
        (instagram_username,),
    ).fetchone()
    if row is None:
        return
    new_id = db.execute("INSERT INTO farley_people DEFAULT VALUES").lastrowid
    db.execute(
        "UPDATE farley_accounts SET person_id=? WHERE platform='instagram' AND account_key=?",
        (new_id, instagram_username),
    )


def sync(db):
    """Idempotent bootstrap and population after imports."""
    for row in db.execute("SELECT url FROM contacts"):
        ensure_account(db, "linkedin", row["url"])
    for row in db.execute("SELECT username FROM instagram_accounts"):
        ensure_account(db, "instagram", row["username"])
    for row in db.execute("SELECT linkedin_url,instagram_username FROM profile_links"):
        merge(db, row["linkedin_url"], row["instagram_username"])


def details(db, person_id):
    pid = resolve(db, person_id)
    if not db.execute("SELECT 1 FROM farley_people WHERE id=?", (pid,)).fetchone():
        return None
    return pid, db.execute(
        "SELECT platform,account_key FROM farley_accounts WHERE person_id=? ORDER BY platform,account_key",
        (pid,),
    ).fetchall()


def add_note(db, person_id, title, target):
    title = (title or "").strip()
    target = (target or "").strip()
    if not (0 < len(title) <= 160):
        raise ValueError("Geef een notitietitel op (maximaal 160 tekens)")
    if len(target) > 2048 or not target.lower().startswith("obsidian://"):
        raise ValueError("Gebruik een obsidian://-link naar een notitie")
    parsed = urlsplit(target)
    if parsed.scheme.lower() != "obsidian" or parsed.netloc.lower() not in {"open", "new", "advanced-uri"}:
        raise ValueError("Geen ondersteunde Obsidian-link")
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    db.execute("INSERT INTO farley_notes(person_id,title,target) VALUES (?,?,?)", (info[0],title,target))


def remove_note(db, person_id, note_id):
    info = details(db, person_id)
    if info is None:
        raise ValueError("Persoon niet gevonden")
    db.execute("DELETE FROM farley_notes WHERE id=? AND person_id=?", (note_id,info[0]))
