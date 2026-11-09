"""Verified, read-only LinkedIn message detail belonging to one Farley person."""
from html import escape
from urllib.parse import quote


def message(db,person_id,key):
    row=db.execute("""SELECT DISTINCT m.date,m.sender,m.subject,m.content,m.conversation_id
        FROM messages m JOIN contact_messages cm ON cm.message_key=m.message_key
        JOIN farley_accounts a ON a.platform='linkedin' AND a.account_key=cm.contact_url
        WHERE a.person_id=? AND m.message_key=? LIMIT 1""",(person_id,key)).fetchone()
    if row is None:
        return None
    html=('<!doctype html><html lang="nl"><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width,initial-scale=1">'
          '<title>LinkedIn-bericht · Farley File</title><style>'
          'body{font:16px/1.65 system-ui,sans-serif;max-width:1050px;margin:0 auto;'
          'padding:38px 24px;background:#f5f7f6;color:#252b30}'
          'a{color:#087f80}section{background:white;padding:24px;'
          'border:1px solid #dde6e5}pre{white-space:pre-wrap;overflow-wrap:anywhere;'
          'font:inherit}small{color:#647078}</style>'
          f'<p><a href="/person/{person_id}#tijdlijn">← Terug naar persoonstijdlijn</a></p>'
          '<h1>LinkedIn-bericht</h1>'
          '<section>'
          f'<h2>{escape(row["subject"] or "(geen onderwerp)")}</h2>'
          f'<small>{escape(row["date"] or "Datum onbekend")} · '
          f'{escape(row["sender"] or "Afzender onbekend")}</small>'
          f'<pre>{escape(row["content"] or "")}</pre></section>')
    return html+'</html>'
