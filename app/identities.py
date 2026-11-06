"""Explicit, user-confirmed links between LinkedIn and Instagram profiles.

Never infer a shared person solely from similar names. Normalization only
provides suggestions, and only the user can confirm a link.
"""
import re
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
            if linked is None:
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
        "INSERT OR IGNORE INTO profile_links VALUES (?, ?, ?)",
        (linkedin_url, instagram_username, datetime.now(timezone.utc).isoformat()),
    )


def unlink(db, linkedin_url, instagram_username):
    db.execute(
        "DELETE FROM profile_links WHERE linkedin_url=? AND instagram_username=?",
        (linkedin_url, instagram_username),
    )
