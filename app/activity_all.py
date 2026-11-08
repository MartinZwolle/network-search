"""Cross-platform recorded network activity, not a measure of real friendships.

Only imported messages are counted. A person's last *recorded* message is not
necessarily their last actual contact. Group messages are labelled separately.
"""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape

from app.activity import parse_date, _bars
from app.person_ids import account_person
from app.manual import display_name


def _timestamp(ms):
    if not ms:
        return None
    try:
        return datetime.fromtimestamp(int(ms) / 1000, timezone.utc).replace(tzinfo=None)
    except (ValueError, OverflowError, OSError, TypeError):
        return None


def _mark(entries, pid, source, when, message_id, group=False):
    if pid is None or when is None:
        return
    entry = entries[pid]
    unique = (source,message_id)
    if unique in entry["seen"]:
        return
    entry["seen"].add(unique)
    entry["messages"] += 1
    entry["by_platform"][source] += 1
    if group:
        entry["group"] += 1
    if entry["last"] is None or when > entry["last"]:
        entry["last"] = when


def gather(db):
    """Return annual counts and person-level recorded activity without reading message bodies."""
    annual = defaultdict(Counter)
    entries = defaultdict(lambda: {
        "messages":0,"by_platform":Counter(),"group":0,"last":None,"seen":set()
    })
    unknown=Counter()

    # One count per imported LinkedIn message, even if associated to
    # multiple people through sender / recipients.
    for row in db.execute("SELECT message_key,date FROM messages"):
        date=parse_date(row["date"])
        if date:
            annual[date.year]["LinkedIn"] += 1
        else:
            unknown["LinkedIn"] += 1

    for row in db.execute("""SELECT cm.contact_url,cm.message_key,m.date
                              FROM contact_messages cm
                              JOIN messages m ON m.message_key=cm.message_key"""):
        pid=account_person(db,"linkedin",row["contact_url"])
        _mark(entries,pid,"LinkedIn",parse_date(row["date"]),row["message_key"])

    # Instagram messages contain a sender display string, not a verified
    # external account ID. Count all by year; associate to a profile only
    # if that string *exactly* matches an imported Instagram username.
    ig_names={r["username"] for r in db.execute("SELECT username FROM instagram_accounts")}
    for row in db.execute("SELECT message_key,sender,date FROM instagram_messages"):
        date=parse_date(row["date"])
        if date:
            annual[date.year]["Instagram"] += 1
        else:
            unknown["Instagram"] += 1
        handle=(row["sender"] or "").strip().lstrip("@").casefold()
        if handle in ig_names:
            _mark(entries,account_person(db,"instagram",handle),
                  "Instagram",date,row["message_key"])

    # Facebook sender name-keys are historically ambiguous. We can show
    # recorded sender activity but do not infer personal interactions
    # from the sender's participation in a group chat.
    for row in db.execute("""SELECT m.message_key,m.sender_key,m.timestamp_ms,
                                     t.is_group
                              FROM facebook_messages m
                              JOIN facebook_threads t ON t.id=m.thread_id"""):
        date=_timestamp(row["timestamp_ms"])
        if date:
            annual[date.year]["Facebook"] += 1
        else:
            unknown["Facebook"] += 1
        if row["sender_key"]:
            pid=account_person(db,"facebook",row["sender_key"])
            _mark(entries,pid,"Facebook",date,row["message_key"],
                  bool(row["is_group"]))

    own={r["user_id"] for r in db.execute("SELECT user_id FROM twitter_accounts WHERE is_self=1")}
    for row in db.execute("SELECT created_at FROM twitter_tweets"):
        date=parse_date(row["created_at"])
        if date:
            annual[date.year]["Twitter tweets"]+=1
        else:
            unknown["Twitter tweets"]+=1
    for row in db.execute("SELECT dm_id,sender_id,recipient_id,created_at FROM twitter_dms"):
        date=parse_date(row["created_at"])
        if date:
            annual[date.year]["Twitter DM"]+=1
        else:
            unknown["Twitter DM"]+=1
        other=(row["recipient_id"] if row["sender_id"] in own
               else row["sender_id"] if row["recipient_id"] in own else "")
        if other:
            _mark(entries,account_person(db,"twitter",other),"Twitter DM",date,row["dm_id"])
    return annual,entries,unknown


def render(db, source="all"):
    choices=("all","linkedin","instagram","facebook","twitter")
    if source not in choices:
        source="all"
    annual,entries,unknown=gather(db)
    keys={"linkedin":"LinkedIn","instagram":"Instagram","facebook":"Facebook","twitter":"Twitter tweets"}
    active_sources=(["Twitter tweets","Twitter DM"] if source=="twitter" else [keys[source]] if source!="all" else ["LinkedIn","Instagram","Facebook","Twitter tweets","Twitter DM"])
    years=sorted(annual)
    yearly=[(str(year),sum(annual[year][p] for p in active_sources))
            for year in years if sum(annual[year][p] for p in active_sources)]
    totals={p:sum(annual[y][p] for y in years)+unknown[p] for p in ["LinkedIn","Instagram","Facebook","Twitter tweets","Twitter DM"]}
    all_total=sum(totals.values())
    unrecognized=sum(unknown[p] for p in active_sources)
    title="Alle platforms" if source=="all" else ("Twitter" if source=="twitter" else keys[source])

    html=('<section><h2>Netwerkactiviteit over alle platforms</h2>'
          '<p class="muted">Berichten uit je geïmporteerde archieven, geen live '
          'activiteit en geen volledig beeld van je persoonlijke contact. '
          'Een groepsbericht telt één keer per platform, niet voor elke deelnemer.</p>'
          '<nav style="display:flex;gap:16px;flex-wrap:wrap">')
    for key,label in (("all","Alles"),("linkedin","LinkedIn"),
                      ("instagram","Instagram"),("facebook","Facebook"),("twitter","Twitter")):
        selected=' aria-current="page" style="font-weight:800"' if source==key else ""
        html+=f'<a href="/activity?source={key}"{selected}>{label}</a>'
    html+='</nav>'
    html+='<div style="display:flex;gap:12px;flex-wrap:wrap;margin-top:20px">'
    for p in ["LinkedIn","Instagram","Facebook","Twitter tweets","Twitter DM"]:
        html+=(f'<div style="background:#eef5f4;border-radius:5px;padding:14px;min-width:170px">'
               f'<small>{p}</small><br><strong style="font-size:1.65rem">'
               f'{totals[p]:,}</strong><br><small>geïmporteerde tekstberichten</small></div>')
    html+='</div></section>'
    html+=(f'<section><h2>Berichten per jaar · {escape(title)}</h2>'
           '<p class="muted">Alleen berichten met een herkenbare datum; jaren '
           'zonder berichten worden niet getoond.</p>')
    html+=_bars(yearly)
    if unrecognized:
        html+=f'<p class="muted">{unrecognized} berichten zonder herkende datum.</p>'
    if source=="all" and years:
        html+='<details><summary style="cursor:pointer;color:#087f80">Jaren per platform vergelijken</summary>'
        html+='<div style="overflow-x:auto"><table style="width:100%;border-collapse:collapse">'
        html+='<tr><th style="text-align:left">Jaar</th><th>LinkedIn</th><th>Instagram</th><th>Facebook</th><th>Twitter tweets</th><th>Twitter DM</th><th>Totaal</th></tr>'
        for year in reversed(years):
            vals=[annual[year][p] for p in ["LinkedIn","Instagram","Facebook","Twitter tweets","Twitter DM"]]
            html+=(f'<tr><td>{year}</td>'
                   +''.join(f'<td style="text-align:center">{v}</td>' for v in vals)
                   +f'<td style="text-align:center"><strong>{sum(vals)}</strong></td></tr>')
        html+='</table></div></details>'
    html+='</section>'

    # Do not interpret the absence of matching metadata as proof of inactivity.
    # A source selector filters both counts and the observed last-message date.
    cutoff=datetime.now(timezone.utc).year-2
    dormant=[]
    for pid,entry in entries.items():
        selected_count=sum(entry["by_platform"][p] for p in active_sources)
        if selected_count<3:
            continue
        # Source-specific last contact is computed in gather's per-source
        # activity only from known dated records: the combined last could
        # otherwise obscure earlier events. In this first version only
        # show dormant candidates in the All-platform view.
        if source!="all":
            continue
        last=entry["last"]
        if last is not None and last.year<=cutoff:
            dormant.append((pid,entry))
    dormant.sort(key=lambda item:(-item[1]["messages"],display_name(db,item[0]).casefold()))
    html+='<section><h2>Contacten om opnieuw te bekijken</h2>'
    html+=('<p class="muted">Ten minste drie herleidbare berichten en geen '
           'herleidbaar bericht in de afgelopen twee kalenderjaren. '
           'Dit betekent <strong>niet</strong> dat je deze persoon sindsdien '
           'niet gesproken hebt. Voor Facebook tellen hier alleen berichten '
           'die de persoon zelf heeft verzonden; bij groepsgesprekken is dat '
           'geen één-op-één-contact.</p>')
    if source!="all":
        html+='<p>Schakel naar <a href="/activity">Alle platforms</a> voor dit overzicht.</p>'
    elif not dormant:
        html+='<p>Geen contacten gevonden met deze selectie.</p>'
    for pid,entry in dormant[:40] if source=="all" else []:
        counts=' · '.join(f'{p}: {entry["by_platform"][p]}'
                          for p in active_sources if entry["by_platform"][p])
        html+=(f'<article><a href="/person/{pid}"><strong>'
               f'{escape(display_name(db,pid))}</strong></a><br>'
               f'<small>{entry["messages"]} berichten · {escape(counts)}'
               f' · laatste geregistreerde bericht: {entry["last"].date().isoformat()}'
               f'{" · inclusief groepsberichten" if entry["group"] else ""}</small></article>')
    return html+'</section>'
