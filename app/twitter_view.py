"""Minimal archived Twitter browser, using stable IDs instead of mutable handles."""
from html import escape
from urllib.parse import quote
from app.person_ids import account_person

def _label(db,uid):
    row=db.execute("""SELECT handle FROM twitter_handles WHERE user_id=?
        ORDER BY CASE source WHEN 'archive_account' THEN 0 WHEN 'reply' THEN 1 ELSE 2 END,
        last_seen DESC LIMIT 1""",(uid,)).fetchone()
    return ("@"+row["handle"]) if row else ("Twitter-ID "+uid)

def page(db,q="",kind="all",person_id=None):
    kind=kind if kind in ("all","tweets","dms","people") else "all"
    q=(q or "").strip()[:150]
    html=('<!doctype html><html lang="nl"><meta charset="utf-8"><meta name="viewport" '
          'content="width=device-width,initial-scale=1">'
          '<title>Twitter-archief · Farley File</title><style>'
          'body{font:16px/1.65 system-ui,sans-serif;max-width:1000px;'
          'margin:0 auto;padding:35px 22px;background:#f5f7f6;color:#252b30}'
          'a{color:#087f80}section{background:white;padding:22px;margin:20px 0;'
          'border:1px solid #dde6e5}article{border-top:1px solid #dde6e5;padding:14px 0}'
          'input{padding:10px;max-width:85%;width:450px}button{padding:10px;background:#087f80;'
          'color:white;border:0;cursor:pointer}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}'
          'small{color:#647078}</style><p><a href="/">← Farley File</a> · '
          '<a href="/activity">Netwerkactiviteit</a></p><h1>Twitter-archief</h1>'
          '<p>Historische gebruikersnamen zijn aanwijzingen; accounts kunnen later '
          'zijn hernoemd of verwijderd. Geen live Twitter-gegevens.</p>')
    if person_id is None:
        html+=('<section><form method="get" action="/twitter">'
               f'<input type="search" name="q" value="{escape(q,quote=True)}" '
               'placeholder="Zoek gebruikersnaam of tekst">'
               '<button>Zoek</button></form></section>')
    if not q and person_id is None:
        stats=db.execute("""SELECT (SELECT count(*) FROM twitter_accounts) a,
          (SELECT count(*) FROM twitter_tweets) t,
          (SELECT count(*) FROM twitter_dms) d""").fetchone()
        return (html+f'<section><h2>{stats["a"]} account-ID’s · '
                f'{stats["t"]} tweets · {stats["d"]} privéberichten</h2>'
                '<p>Zoek naar een persoon, gebruikersnaam of onderwerp.</p></section></html>')
    ids=[]
    if person_id is not None:
        ids=[r["account_key"] for r in db.execute(
            "SELECT account_key FROM farley_accounts WHERE person_id=? AND platform='twitter'",
            (person_id,))]
    elif q:
        term="%"+q.casefold().replace("\\","\\\\").replace("%","\\%").replace("_","\\_")+"%"
        ids=[r["user_id"] for r in db.execute(
            "SELECT DISTINCT user_id FROM twitter_handles WHERE handle LIKE ? ESCAPE '\\' LIMIT 30",
            (term,))]
        if q.isdigit():
            ids.append(q)
        ids=list(dict.fromkeys(ids))
    if ids and kind in ("all","people"):
        html+='<section><h2>Historische accounts</h2>'
        for uid in ids[:30]:
            pid=account_person(db,"twitter",uid)
            if pid is None:
                continue
            handles=[r["handle"] for r in db.execute(
                "SELECT DISTINCT handle FROM twitter_handles WHERE user_id=? ORDER BY handle LIMIT 12",
                (uid,))]
            html+=(f'<article><a href="/person/{pid}"><strong>{escape(_label(db,uid))}</strong></a> '
                   f'<small>ID: {escape(uid)}</small><br>'
                   f'<small>Historische namen: {escape(", ".join("@"+h for h in handles) or "onbekend")}</small>'
                   f' · <a href="/twitter?person_id={pid}">Twitter-activiteit bekijken</a></article>')
        html+='</section>'
    if kind in ("all","tweets"):
        if person_id is not None and not ids:
            tweets=[]
        elif ids:
            placeholders=",".join("?" for _ in ids)
            tweets=db.execute(f"""SELECT DISTINCT t.* FROM twitter_tweets t
                LEFT JOIN twitter_mentions m ON m.tweet_id=t.tweet_id
                WHERE t.reply_to_user_id IN ({placeholders})
                   OR m.user_id IN ({placeholders})
                ORDER BY t.created_at DESC LIMIT 100""",(*ids,*ids)).fetchall()
        elif q:
            from app.search import query_expression
            expression=query_expression(q)
            tweets=db.execute("""SELECT t.* FROM twitter_tweets_fts f
               JOIN twitter_tweets t ON t.tweet_id=f.tweet_id
               WHERE twitter_tweets_fts MATCH ? ORDER BY t.created_at DESC LIMIT 100""",
               (expression,)).fetchall() if expression else []
        else:
            tweets=[]
        html+=f'<section><h2>Tweets en vermeldingen ({len(tweets)} getoond)</h2>'
        for t in tweets:
            html+=(f'<article><small>{escape(t["created_at"][:16])} · '
                   f'<a href="https://twitter.com/i/web/status/{quote(t["tweet_id"])}" '
                   'target="_blank" rel="noopener noreferrer">Originele tweet ↗</a></small>'
                   f'<pre>{escape(t["content"])}</pre></article>')
        html+='</section>'
    if kind in ("all","dms"):
        if ids:
            placeholders=",".join("?" for _ in ids)
            rows=db.execute(f"""SELECT * FROM twitter_dms
                WHERE sender_id IN ({placeholders}) OR recipient_id IN ({placeholders})
                ORDER BY created_at DESC LIMIT 100""",(*ids,*ids)).fetchall()
        elif q:
            from app.search import query_expression
            expression=query_expression(q)
            rows=db.execute("""SELECT d.* FROM twitter_dms_fts f
              JOIN twitter_dms d ON d.dm_id=f.dm_id
              WHERE twitter_dms_fts MATCH ? ORDER BY d.created_at DESC LIMIT 100""",
              (expression,)).fetchall() if expression else []
        else:
            rows=[]
        html+=f'<section><h2>Privéberichten ({len(rows)} getoond)</h2>'
        html+='<p><small>Dit zijn privéberichten uit je eigen archief. Niet openbaar delen.</small></p>'
        for d in rows:
            html+=(f'<article><small>{escape(d["created_at"][:16])} · '
                   f'{escape(_label(db,d["sender_id"]))} → '
                   f'{escape(_label(db,d["recipient_id"]))}</small>'
                   f'<pre>{escape(d["content"])}</pre></article>')
        html+='</section>'
    return html+'</html>'
