"""Link message authors to known contacts using verified LinkedIn profile URLs.

Never guess a person from display name alone.
"""
from urllib.parse import urlsplit
from app.person_ids import account_person


def linkedin_key(url):
    text = (url or "").strip()
    if not text:
        return ""
    path = urlsplit(text if "://" in text else "https://" + text).path
    path = path.rstrip("/").casefold()
    return path if path.startswith("/in/") else ""


def contact_lookup(db):
    """Build a single lookup for an entire search page."""
    lookup = {}
    for row in db.execute("SELECT url FROM contacts"):
        key = linkedin_key(row["url"])
        if key:
            pid = account_person(db, "linkedin", row["url"])
            if pid is not None:
                # Do not choose arbitrarily when imported URLs collide.
                lookup.setdefault(key, pid)
    return lookup


def author_profile(message, lookup):
    """Return a stable person ID only when sender_url identifies a known contact."""
    key = linkedin_key(message["sender_url"])
    return lookup.get(key) if key else None
