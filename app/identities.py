"""Explicit, user-confirmed links between LinkedIn and Instagram profiles.

Never infer a shared person solely from similar names. Normalization only
provides suggestions, and only the user can confirm a link.
"""
import re
from app.person_ids import merge as merge_person_ids, detach_instagram
from datetime import datetime, timezone


def compact(value):
    return re.sub(r"[^a-z0-9]", "", (value or "").casefold())


def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS profile_links (
      linkedin_url TEXT NOT NULL,
      instagram_username TEXT NOT NULL UNIQUE,
      confirmed_at TEXT NOT NULL,
      PRIMARY KEY(linkedin_url, instagram_username)
    );
    CREATE INDEX IF NOT EXISTS idx_profile_links_linkedin
      ON profile_links(linkedin_url);
    CREATE TABLE IF NOT EXISTS profile_rejections (
      linkedin_url TEXT NOT NULL,
      instagram_username TEXT NOT NULL,
      rejected_at TEXT NOT NULL,
      PRIMARY KEY(linkedin_url, instagram_username)
    );
    """)


def candidates(db, linkedin_rows, instagram_rows):
    """Find exact compact name/username overlaps among supplied search results."""
    result = []
    seen = set()
    for contact in linkedin_rows:
        key = compact((contact["first_name"] or "") + (contact["last_name"] or ""))
        if not key:
            continue
        for account in instagram_rows:
            handle = account["username"]
            if key != compact(handle) or (contact["url"], handle) in seen:
                continue
            seen.add((contact["url"], handle))
            linked = db.execute(
                "SELECT linkedin_url FROM profile_links WHERE instagram_username=?", (handle,)
            ).fetchone()
            rejected = db.execute(
                "SELECT 1 FROM profile_rejections WHERE linkedin_url=? AND instagram_username=?",
                (contact["url"], handle),
            ).fetchone()
            if linked is None and rejected is None:
                result.append((contact, account))
    return result[:15]


def link(db, linkedin_url, instagram_username):
    exists = db.execute("SELECT 1 FROM contacts WHERE url=?", (linkedin_url,)).fetchone()
    account = db.execute(
        "SELECT 1 FROM instagram_accounts WHERE username=?", (instagram_username,)
    ).fetchone()
    if not exists or not account:
        raise ValueError("LinkedIn-contact of Instagram-account niet gevonden")
    prior = db.execute(
        "SELECT linkedin_url FROM profile_links WHERE instagram_username=?",
        (instagram_username,),
    ).fetchone()
    if prior and prior["linkedin_url"] != linkedin_url:
        raise ValueError("Dit Instagram-account is al gekoppeld aan een ander contact")
    db.execute(
        "DELETE FROM profile_rejections WHERE linkedin_url=? AND instagram_username=?",
        (linkedin_url, instagram_username),
    )
    db.execute(
        "INSERT OR IGNORE INTO profile_links VALUES (?, ?, ?)",
        (linkedin_url, instagram_username, datetime.now(timezone.utc).isoformat()),
    )
    merge_person_ids(db, linkedin_url, instagram_username)


def unlink(db, linkedin_url, instagram_username):
    existing = db.execute(
        "SELECT 1 FROM profile_links WHERE linkedin_url=? AND instagram_username=?",
        (linkedin_url, instagram_username),
    ).fetchone()
    db.execute(
        "DELETE FROM profile_links WHERE linkedin_url=? AND instagram_username=?",
        (linkedin_url, instagram_username),
    )
    if existing:
        detach_instagram(db, instagram_username)


def all_candidates(db):
    """Suggest unlinked exact compact-name matches across the entire database.

    This does not infer identities, and intentionally excludes loose/fuzzy matches.
    Return deterministic sorted suggestions without loading message content.
    """
    accounts = {}
    for row in db.execute("""SELECT username FROM instagram_accounts
                              WHERE follows=1 OR follower=1 ORDER BY username"""):
        key = compact(row["username"])
        if key:
            accounts.setdefault(key, []).append(row["username"])
    rejected = {(r["linkedin_url"], r["instagram_username"]) for r in db.execute(
        "SELECT linkedin_url, instagram_username FROM profile_rejections"
    )}
    linked = {row["instagram_username"] for row in db.execute(
        "SELECT instagram_username FROM profile_links"
    )}
    suggestions = []
    for contact in db.execute(
        """SELECT url, first_name, last_name, company, position
           FROM contacts ORDER BY last_name, first_name"""
    ):
        first = (contact["first_name"] or "").strip()
        last = (contact["last_name"] or "").strip()
        if not first or not last:
            continue
        key = compact(first + last)
        if len(key) < 6:
            continue
        for handle in accounts.get(key, []):
            if handle not in linked and (contact["url"], handle) not in rejected:
                suggestions.append((contact, handle))
    return suggestions


def reject(db, linkedin_url, instagram_username):
    """Permanently hide this exact suggestion, unless user reverses it."""
    if not db.execute("SELECT 1 FROM contacts WHERE url=?", (linkedin_url,)).fetchone():
        raise ValueError("LinkedIn-contact niet gevonden")
    if not db.execute("SELECT 1 FROM instagram_accounts WHERE username=?", (instagram_username,)).fetchone():
        raise ValueError("Instagram-account niet gevonden")
    db.execute(
        "INSERT OR IGNORE INTO profile_rejections VALUES (?, ?, ?)",
        (linkedin_url, instagram_username, datetime.now(timezone.utc).isoformat()),
    )


def restore(db, linkedin_url, instagram_username):
    db.execute(
        "DELETE FROM profile_rejections WHERE linkedin_url=? AND instagram_username=?",
        (linkedin_url, instagram_username),
    )


def resolve_contact(db, value):
    """Find a unique LinkedIn URL from a pasted URL or an exact full name."""
    value = (value or "").strip()
    if not value:
        raise ValueError("Vul een LinkedIn-naam of profiel-URL in")
    direct = db.execute("SELECT url FROM contacts WHERE url=?", (value,)).fetchone()
    if direct:
        return direct["url"]
    matches = [
        row["url"]
        for row in db.execute("SELECT url, first_name, last_name FROM contacts")
        if " ".join(filter(None, [row["first_name"], row["last_name"]])).casefold() == value.casefold()
    ]
    if len(matches) == 1:
        return matches[0]
    if not matches:
        raise ValueError("Geen LinkedIn-contact met deze exacte naam gevonden")
    raise ValueError("Er zijn meerdere contacten met deze naam; gebruik de LinkedIn-profiel-URL")
