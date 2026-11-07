"""Resolve message authors only when a reliable LinkedIn account match exists.

Never infer identity from a displayed name: names can collide.
"""
from app.person_ids import account_person


def sender_person_id(db, message):
    """Use the importer's LinkedIn URL key, falling back to an unambiguous
    contact_message relation for exports where the sender URL was missing.
    """
    from app.main import profile_key  # Local import; used only after app starts.
    sender_key = profile_key(message["sender_url"] or "")
    if sender_key:
        urls = db.execute("SELECT url FROM contacts").fetchall()
        for row in urls:
            if profile_key(row["url"]) == sender_key:
                return account_person(db, "linkedin", row["url"])
        return None
    # An absent URL does not prove the sender is the contact in a conversation.
    return None
