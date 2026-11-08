"""Explore a local Twitter archive without knowing a person's name.

Only locally imported archive data. Counters describe recorded activity, not
relationship strength. Handles are historical observations, not live identity.
"""
from html import escape
from urllib.parse import urlencode
from app.person_ids import account_person
from app.twitter_view import _label

PAGE_SIZE=40

def _url(**params):
    return "/twitter/explore?" + urlencode({k:v for k,v in params.items() if v is not None})

def _year_options(db):
    records=db.execute("""
        SELECT year, SUM(tweets) tweets, SUM(replies) replies, SUM(dms) dms
        FROM (
            SELECT substr(created_at,1,4) year, COUNT(*) tweets,
              SUM(CASE WHEN reply_to_user_id<>'' THEN 1 ELSE 0 END) replies,
              0 dms FROM twitter_tweets GROUP BY substr(created_at,1,4)
            UNION ALL
            SELECT substr(created_at,1,4) year,0,0,COUNT(*) dms
              FROM twitter_dms GROUP BY substr(created_at,1,4)
        )
        WHERE year GLOB '[12][0-9][0-9][0-9]'
        GROUP BY year ORDER BY year DESC
    """).fetchall()
    return records

def _people(db,year,limit=30):
    """Popular *recorded* reply/mention/DM counterparts, not inferred friends."""
    year_filter=" AND substr(t.created_at,1,4)=?" if year else ""
    dm_filter=" AND substr(d.created_at,1,4)=?" if year else ""
    values=(str(year),) if year else ()
    ids={}
    for row in db.execute(f"""
        SELECT user_id,SUM(n) n FROM (
            SELECT t.reply_to_user_id user_id,COUNT(*) n
              FROM twitter_tweets t
              WHERE t.reply_to_user_id<>'' {year_filter}
              GROUP BY t.reply_to_user_id
            UNION ALL
            SELECT m.user_id,COUNT(*) n
              FROM twitter_mentions m JOIN twitter_tweets t ON t.tweet_id=m.tweet_id
              WHERE m.user_id<>'' {year_filter}
              GROUP BY m.user_id
            UNION ALL
            SELECT CASE WHEN d.sender_id=me.user_id THEN d.recipient_id
                        ELSE d.sender_id END user_id,COUNT(*) n
              FROM twitter_dms d
              CROSS JOIN (SELECT user_id FROM twitter_accounts WHERE is_self=1 LIMIT 1) me
              WHERE (d.sender_id=me.user_id OR d.recipient_id=me.user_id) {dm_filter}
              GROUP BY user_id
        ) GROUP BY user_id ORDER BY n DESC LIMIT ?
    """, (*values,*values,*values,limit)):
        ids[row["user_id"]]=row["n"]
    return ids

def _entries(db,year,kind,offset):
    date_field="created_at"
    table="twitter_dms" if kind=="dms" else "twitter_tweets"
    where=["1=1"]
    args=[]
    if year:
        where.append("substr(created_at,1,4)=?")
        args.append(str(year))
    if kind=="replies":
        where.append("reply_to_user_id<>''")
    where_sql=" AND ".join(where)
    count=db.execute(f"SELECT COUNT(*) FROM {table} WHERE {where_sql}",args).fetchone()[0]
    rows=db.execute(f"""SELECT * FROM {table} WHERE {where_sql}
                          ORDER BY {date_field} DESC, rowid DESC LIMIT ? OFFSET ?""",
                    [*args,PAGE_SIZE,offset]).fetchall()
    return rows,count

def page(db,year=0,kind="tweets",page_number=1):
    years=_year_options(db)
    valid_years={int(r["year"]) for r in years}
    year=year if year in valid_years else 0
    kind=kind if kind in ("tweets","replies","dms") else "tweets"
    page_number=max(1,min(page_number,10000))
    offset=(page_number-1)*PAGE_SIZE
    rows,total=_entries(db,year,kind,offset)
    if offset>=total and total:
        page_number=max(1,(total-1)//PAGE_SIZE+1)
        offset=(page_number-1)*PAGE_SIZE
        rows,total=_entries(db,year,kind,offset)
    year_name=str(year) if year else "Alle jaren"
    html=('<!doctype html><html lang="nl"><meta charset="utf-8">'
          '<meta name="viewport" content="width=device-width,initial-scale=1">'
          '<title>Twitter ontdekken · Farley File</title><style>'
          'body{font:16px/1.65 system-ui,sans-serif;max-width:1050px;margin:0 auto;'
          'padding:32px 22px;background:#f5f7f6;color:#252b30}'
          'a{color:#087f80}section{background:#fff;border:1px solid #dde6e5;'
          'padding:24px;margin:20px 0}article{border-top:1px solid #dde6e5;padding:12px 0}'
          'pre{white-space:pre-wrap;overflow-wrap:anywhere;font:inherit}'
          'small,.muted{color:#647078}.years{display:flex;gap:8px;flex-wrap:wrap}'
          '.pill{display:inline-block;padding:6px 11px;background:#e4f3f0;'
          'border-radius:4px}.pill.active{background:#087f80;color:white}'
          'table{width:100%;border-collapse:collapse}td,th{padding:7px;text-align:left;'
          'border-bottom:1px solid #e8eeec}nav{display:flex;gap:12px;flex-wrap:wrap}'
          '</style><p><a href="/twitter">← Twitter-archief</a> · '
          '<a href="/activity">Netwerkactiviteit</a></p>'
          '<h1>Twitter ontdekken</h1>'
          '<p class="muted">Blader door je eigen Twitterarchief. De jaartallen tonen '
          'je geïmporteerde tweets en DM’s; antwoorden bevatten meestal alleen '
          'jouw kant van een gesprek. Historische gebruikersnamen kunnen verdwenen zijn.</p>')
    html+='<section><h2>Kies een jaar</h2><div class="years">'
    for yy,label in [(0,"Alle jaren")]+[(int(row["year"]),row["year"]) for row in years]:
        active=" active" if yy==year else ""
        html+=(f'<a class="pill{active}" href="{escape(_url(year=yy,kind=kind),quote=True)}">'
               f'{escape(label)}</a>')
    html+='</div><details style="margin-top:20px"><summary>Activiteit per jaar</summary>'
    html+='<table><tr><th>Jaar</th><th>Tweets</th><th>Replies</th><th>DM’s</th></tr>'
    for row in years:
        html+=(f'<tr><td>{escape(row["year"])}</td><td>{row["tweets"]}</td>'
               f'<td>{row["replies"]}</td><td>{row["dms"]}</td></tr>')
    html+='</table></details></section>'
    counterparts=_people(db,year)
    html+='<section><h2>Met wie had je contact?'+(f' · {year}' if year else '')+'</h2>'
    html+=('<p class="muted">Accounts die voorkomen in je replies, vermeldingen '
           'of DM’s. Het aantal is een optelsom van deze vermeldingen, '
           'geen aantal unieke gesprekken en geen ranglijst van vriendschappen.</p>')
    if not counterparts:
        html+='<p>Geen herleidbare account-ID’s in deze periode.</p>'
    for uid,count in counterparts.items():
        person=account_person(db,"twitter",uid)
        label=escape(_label(db,uid))
        link=(f'/person/{person}' if person is not None else
              '/twitter?q='+uid)
        html+=(f'<article><a href="{escape(link,quote=True)}"><strong>{label}</strong></a> '
               f'<small>· {count} geregistreerde verwijzingen</small> · '
               f'<a href="/twitter?q={escape(uid,quote=True)}">Berichten bekijken</a></article>')
    html+='</section>'
    labels={"tweets":"Alle tweets","replies":"Mijn replies","dms":"Privéberichten"}
    html+='<section><h2>Bladeren · '+escape(year_name)+'</h2><nav>'
    for k,label in labels.items():
        current=' class="pill active"' if k==kind else ' class="pill"'
        html+=(f'<a{current} href="{escape(_url(year=year,kind=k),quote=True)}">'
               f'{label}</a>')
    html+='</nav><p class="muted">'+str(total)+' berichten in deze selectie · pagina '+str(page_number)+'</p>'
    for row in rows:
        if kind=="dms":
            author=escape(_label(db,row["sender_id"]))
            recipient=escape(_label(db,row["recipient_id"]))
            heading=(f'<small>{escape(row["created_at"][:16])} · {author} → '
                     f'{recipient} · privé</small>')
        else:
            heading=f'<small>{escape(row["created_at"][:16])}'
            if row["reply_to_user_id"]:
                uid=row["reply_to_user_id"]
                heading+=(f' · antwoord aan <a href="/twitter?q={escape(uid,quote=True)}">'
                          f'{escape(_label(db,uid))}</a>')
            heading+='</small>'
        html+=f'<article>{heading}<pre>{escape(row["content"])}</pre></article>'
    if not rows:
        html+='<p>Geen berichten in deze selectie.</p>'
    html+='<nav>'
    if page_number>1:
        html+=(f'<a href="{escape(_url(year=year,kind=kind,page_number=page_number-1),quote=True)}">'
               '← Vorige</a>')
    if page_number*PAGE_SIZE<total:
        html+=(f'<a href="{escape(_url(year=year,kind=kind,page_number=page_number+1),quote=True)}">'
               'Volgende →</a>')
    return html+'</nav></section></html>'
