"""Cross-platform person timeline with explicit data provenance.

Never infer Instagram inbox identities from display names or claim missing
Twitter replies are archived. Group Facebook threads are marked as groups.
"""
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote, urlencode

from app.activity import parse_date
from app.person_ids import details

PAGE_SIZE=30
PLATFORMS=("all","linkedin","facebook","instagram","twitter")


def _event(kind, stamp, title, summary="", link="", note=""):
    date=parse_date(stamp)
    if date is None:
        return None
    return (date,kind,title,summary,link,note)


def _all_events(db, person_id, platform):
    info=details(db,person_id)
    if info is None:
        return []
    account_map={}
    for row in info[1]:
        account_map.setdefault(row["platform"],[]).append(row["account_key"])
    events=[]
    if platform in ("all","linkedin"):
        for key in account_map.get("linkedin",[]):
            rows=db.execute("""SELECT m.date,m.sender,m.subject,m.content,m.message_key
                FROM contact_messages cm JOIN messages m ON m.message_key=cm.message_key
                WHERE cm.contact_url=? ORDER BY m.date DESC LIMIT 500""",(key,))
            for row in rows:
                summary=(row["content"] or "")[:380]
                item=_event("LinkedIn",row["date"],
                            row["subject"] or "LinkedIn-bericht",summary,
                            "", "Uit LinkedIn-export · " + (row["sender"] or "afzender onbekend"))
                if item: events.append(item)

    if platform in ("all","facebook"):
        fbkeys=account_map.get("facebook",[])
        if fbkeys:
            placeholders=",".join("?" for _ in fbkeys)
            rows=db.execute(f"""SELECT t.id,t.title,t.is_group,
                COUNT(DISTINCT m.message_key) cnt,MAX(m.timestamp_ms) latest
                FROM facebook_threads t
                JOIN facebook_thread_people tp ON tp.thread_id=t.id
                JOIN facebook_messages m ON m.thread_id=t.id
                WHERE tp.fb_key IN ({placeholders})
                GROUP BY t.id ORDER BY latest DESC LIMIT 300""",fbkeys)
            for row in rows:
                if not row["latest"]: continue
                when=datetime.fromtimestamp(int(row["latest"])/1000,timezone.utc)
                note="Groepsgesprek" if row["is_group"] else "Privégesprek"
                item=_event("Facebook",when.isoformat(),row["title"] or "Facebook-gesprek",
                            str(row["cnt"])+" geïmporteerde berichten",
                            "/facebook/thread/"+quote(str(row["id"]),safe=""),note)
                if item: events.append(item)

    if platform in ("all","twitter"):
        tids=account_map.get("twitter",[])
        if tids:
            placeholders=",".join("?" for _ in tids)
            rows=db.execute(f"""SELECT DISTINCT t.tweet_id,t.created_at,t.content,
                t.reply_to_user_id
                FROM twitter_tweets t LEFT JOIN twitter_mentions m ON m.tweet_id=t.tweet_id
                WHERE t.reply_to_user_id IN ({placeholders})
                   OR m.user_id IN ({placeholders})
                ORDER BY t.created_at DESC LIMIT 500""",[*tids,*tids])
            for row in rows:
                item=_event("Twitter",row["created_at"],
                            "Jouw antwoord of vermelding",row["content"],
                            "/twitter?person_id="+str(person_id),
                            "Alleen je eigen tweet; reacties van anderen ontbreken mogelijk")
                if item: events.append(item)
            rows=db.execute(f"""SELECT conversation_id,MAX(created_at) latest,COUNT(*) cnt
                FROM twitter_dms
                WHERE sender_id IN ({placeholders}) OR recipient_id IN ({placeholders})
                GROUP BY conversation_id ORDER BY latest DESC LIMIT 200""",[*tids,*tids])
            for row in rows:
                item=_event("Twitter",row["latest"],"Twitter-DM-gesprek",
                            str(row["cnt"])+" bewaarde privéberichten",
                            "/twitter/dms/thread?"+urlencode({"conversation_id":row["conversation_id"]}),
                            "Alleen berichten aanwezig in jouw export")
                if item: events.append(item)
    # Instagram inbox exports contain unverified sender display names.
    # They are intentionally excluded until exact identity mapping exists.
    return sorted(events,key=lambda e:e[0],reverse=True)


def render(db, person_id, platform="all", page=1):
    platform=platform if platform in PLATFORMS else "all"
    page=max(1,min(int(page),100000))
    events=_all_events(db,person_id,platform)
    total=len(events)
    max_page=max(1,(total+PAGE_SIZE-1)//PAGE_SIZE)
    page=min(page,max_page)
    shown=events[(page-1)*PAGE_SIZE:page*PAGE_SIZE]
    base="/person/"+str(person_id)
    html='<section id="tijdlijn"><h2>Tijdlijn</h2>'
    html+=('<p class="muted">De digitale geschiedenis van deze persoon, '
           'op basis van berichten in jouw archieven. Geen volledig overzicht '
           'van het echte contact. Facebook-gesprekken en Twitter-DM’s openen '
           'apart; eigen LinkedIn-berichten en tweets lees je hieronder.</p>')
    html+='<nav style="display:flex;gap:14px;flex-wrap:wrap">'
    for key,label in (("all","Alles"),("linkedin","LinkedIn"),("facebook","Facebook"),
                      ("instagram","Instagram"),("twitter","Twitter")):
        current=' aria-current="page" style="font-weight:800"' if platform==key else ""
        url=base+"?"+urlencode({"timeline_platform":key})+"#tijdlijn"
        html+=f'<a href="{escape(url,quote=True)}"{current}>{label}</a>'
    html+='</nav>'
    if platform in ("all","instagram"):
        html+=('<p class="muted" style="margin-top:14px">Instagram: de geïmporteerde '
               'inbox koppelt afzenders nog niet betrouwbaar aan account-ID’s. '
               'Deze berichten blijven daarom buiten de persoonstijdlijn.</p>')
    html+=f'<p class="muted">{total} herleidbare tijdlijnitems · pagina {page} van {max_page}</p>'
    if not shown:
        html+='<p>Geen herleidbare activiteiten voor deze selectie.</p>'
    prev_year=None
    for date,kind,title,summary,link,note in shown:
        if date.year!=prev_year:
            html+=f'<h3>{date.year}</h3>'
            prev_year=date.year
        html+=(f'<article><small>{escape(kind)} · {date:%d-%m-%Y %H:%M}</small>'
               f'<br><strong>{escape(title)}</strong>')
        if summary:
            html+=f'<pre>{escape(summary)}</pre>'
        if note:
            html+=f'<small>{escape(note)}</small><br>'
        if link:
            html+=f'<a href="{escape(link,quote=True)}">Gesprek / berichten bekijken →</a>'
        html+='</article>'
    html+='<nav style="display:flex;gap:18px;flex-wrap:wrap">'
    if page>1:
        url=base+"?"+urlencode({"timeline_platform":platform,"timeline_page":page-1})+"#tijdlijn"
        html+=f'<a href="{escape(url,quote=True)}">← Vorige</a>'
    if page<max_page:
        url=base+"?"+urlencode({"timeline_platform":platform,"timeline_page":page+1})+"#tijdlijn"
        html+=f'<a href="{escape(url,quote=True)}">Volgende →</a>'
    return html+'</nav></section>'
