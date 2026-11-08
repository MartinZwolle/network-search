"""Read-only browser for all archived Twitter DM conversations.

Includes conversations with accounts that have no remaining username.
Never infer a new identity from a missing handle.
"""
from html import escape
from urllib.parse import urlencode

from app.person_ids import account_person
from app.twitter_view import _label

PAGE_SIZE = 30
MESSAGE_PAGE_SIZE = 80


def _link(path, **params):
    return path + "?" + urlencode(params)


def _shell(title):
    return ('<!doctype html><html lang="nl"><meta charset="utf-8">'
            '<meta name="viewport" content="width=device-width, initial-scale=1">'
            f'<title>{escape(title)} · Farley File</title>'
            '<style>body{font:16px/1.65 system-ui,sans-serif;max-width:1000px;'
            'margin:0 auto;padding:32px 22px;background:#f5f7f6;color:#252b30}'
            'a{color:#087f80}section{background:white;border:1px solid #dde6e5;'
            'padding:24px;margin:20px 0}article{border-top:1px solid #dde6e5;'
            'padding:14px 0}small,.muted{color:#647078}'
            'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}'
            'nav{display:flex;gap:16px;flex-wrap:wrap}</style>'
            '<nav><a href="/twitter">← Twitter-archief</a>'
            '<a href="/twitter/explore">Twitter ontdekken</a></nav>')


def _participants(db, conversation_id, me):
    """Use participant IDs from actual messages, not the conversation ID string."""
    rows = db.execute("""
        SELECT DISTINCT user_id FROM (
            SELECT sender_id AS user_id FROM twitter_dms WHERE conversation_id=?
            UNION SELECT recipient_id AS user_id FROM twitter_dms WHERE conversation_id=?
        ) WHERE user_id <> '' ORDER BY user_id
    """, (conversation_id, conversation_id)).fetchall()
    others = [row["user_id"] for row in rows if row["user_id"] not in me]
    if others:
        return others
    return [row["user_id"] for row in rows]


def _person_links(db, user_ids):
    rendered = []
    for uid in user_ids:
        label = escape(_label(db, uid))
        pid = account_person(db, "twitter", uid)
        if pid is None:
            rendered.append(f'{label} <small>(ID {escape(uid)})</small>')
        else:
            rendered.append(f'<a href="/person/{pid}">{label}</a> '
                            f'<small>(ID {escape(uid)})</small>')
    return ", ".join(rendered)


def conversations(db, page_number=1):
    page_number = max(1, min(int(page_number), 100000))
    count = db.execute(
        "SELECT COUNT(DISTINCT conversation_id) FROM twitter_dms"
    ).fetchone()[0]
    pages = max(1, (count + PAGE_SIZE - 1) // PAGE_SIZE)
    page_number = min(page_number, pages)
    rows = db.execute("""
        SELECT conversation_id, COUNT(*) AS message_count,
               MIN(created_at) AS first_at, MAX(created_at) AS last_at
        FROM twitter_dms
        GROUP BY conversation_id
        ORDER BY last_at DESC, conversation_id
        LIMIT ? OFFSET ?
    """, (PAGE_SIZE, (page_number - 1) * PAGE_SIZE)).fetchall()
    own = {row["user_id"] for row in db.execute(
        "SELECT user_id FROM twitter_accounts WHERE is_self=1"
    )}
    html = _shell("Twitter-DM-gesprekken")
    html += ('<h1>Twitter-DM-gesprekken</h1>'
             '<p class="muted">Alle gesprekken uit je eigen export, ook als '
             'de andere accountnaam niet meer bekend is. Dan tonen we het '
             'historische account-ID. Dit betekent niet dat een account '
             'vandaag nog bestaat.</p>'
             f'<section><h2>{count} gesprekken in het archief</h2>'
             f'<p>Pagina {page_number} van {pages} · nieuwste gesprekken eerst.</p>')
    for row in rows:
        cid = row["conversation_id"]
        participants = _participants(db, cid, own)
        names = _person_links(db, participants) or "Onbekende gesprekspartner"
        href = escape(_link("/twitter/dms/thread", conversation_id=cid), quote=True)
        html += (f'<article><a href="{href}"><strong>Gesprek openen →</strong></a><br>'
                 f'{names}<br><small>{row["message_count"]} berichten · '
                 f'{escape((row["first_at"] or "")[:10])} t/m '
                 f'{escape((row["last_at"] or "")[:10])}</small></article>')
    if not rows:
        html += "<p>Er zijn nog geen Twitter-DM-gesprekken geïmporteerd.</p>"
    html += '</section><nav>'
    if page_number > 1:
        html += f'<a href="{escape(_link("/twitter/dms", page_number=page_number-1), quote=True)}">← Vorige</a>'
    if page_number < pages:
        html += f'<a href="{escape(_link("/twitter/dms", page_number=page_number+1), quote=True)}">Volgende →</a>'
    return html + '</nav></html>'


def thread(db, conversation_id, page_number=1):
    """Render messages chronologically, paginated from the first message."""
    count = db.execute(
        "SELECT COUNT(*) FROM twitter_dms WHERE conversation_id=?", (conversation_id,)
    ).fetchone()[0]
    if not count:
        return None
    pages = max(1, (count + MESSAGE_PAGE_SIZE - 1) // MESSAGE_PAGE_SIZE)
    page_number = min(max(1, int(page_number)), pages)
    rows = db.execute("""
        SELECT dm_id, sender_id, recipient_id, created_at, content
        FROM twitter_dms WHERE conversation_id=?
        ORDER BY created_at ASC, dm_id ASC LIMIT ? OFFSET ?
    """, (conversation_id, MESSAGE_PAGE_SIZE,
          (page_number - 1) * MESSAGE_PAGE_SIZE)).fetchall()
    own = {row["user_id"] for row in db.execute(
        "SELECT user_id FROM twitter_accounts WHERE is_self=1"
    )}
    participants = _participants(db, conversation_id, own)
    html = _shell("Twitter-DM-gesprek")
    html += ('<p><a href="/twitter/dms">← Alle DM-gesprekken</a></p>'
             '<h1>Twitter-DM-gesprek</h1>'
             f'<p>{_person_links(db, participants)}</p>'
             f'<p class="muted">{count} berichten · pagina {page_number} van {pages}. '
             'Dit gesprek komt uit je persoonlijke archief; berichten '
             'van verwijderde accounts zijn alleen zichtbaar voor zover '
             'ze daadwerkelijk in de export aanwezig zijn.</p><section>')
    for row in rows:
        sender = escape(_label(db, row["sender_id"]))
        direction = "Jij" if row["sender_id"] in own else sender
        html += (f'<article><strong>{direction}</strong> '
                 f'<small>{escape(row["created_at"][:16])}</small>'
                 f'<pre>{escape(row["content"])}</pre></article>')
    html += '</section><nav>'
    if page_number > 1:
        prev = _link("/twitter/dms/thread",
                     conversation_id=conversation_id, page_number=page_number-1)
        html += f'<a href="{escape(prev, quote=True)}">← Vorige berichten</a>'
    if page_number < pages:
        nxt = _link("/twitter/dms/thread",
                    conversation_id=conversation_id, page_number=page_number+1)
        html += f'<a href="{escape(nxt, quote=True)}">Volgende berichten →</a>'
    return html + '</nav></html>'
