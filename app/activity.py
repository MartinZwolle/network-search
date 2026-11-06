"""LinkedIn message activity views. No inferred relationship strength or private AI profiling."""
from collections import Counter, defaultdict
from datetime import datetime, timezone
from html import escape
from urllib.parse import quote

DATE_FORMATS = (
    "%Y-%m-%d %H:%M:%S %Z", "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S",
    "%Y-%m-%d", "%b %d, %Y", "%B %d, %Y",
    "%m/%d/%Y", "%d/%m/%Y",
)


def parse_date(value):
    """Best-effort LinkedIn date parser; unknown dates remain unclassified."""
    text = (value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        pass
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    return None


def year_counts(history):
    counts = Counter()
    unknown = 0
    for item in history:
        d = parse_date(item["date"])
        if d:
            counts[d.year] += 1
        else:
            unknown += 1
    return sorted(counts.items(), reverse=True), unknown


def _bars(items, max_width=100):
    if not items:
        return "<p class='muted'>Nog geen berichten met een herkenbare datum.</p>"
    maximum = max(value for _, value in items) or 1
    result = '<div class="activity-bars">'
    for label, value in items:
        pct = max(2, round(value / maximum * max_width))
        result += (
            '<div style="display:grid;grid-template-columns:70px minmax(0,1fr) 55px;'
            'gap:12px;align-items:center;margin:9px 0">'
            f'<span>{escape(str(label))}</span>'
            f'<div style="height:14px;background:#e5eeed;border-radius:3px">'
            f'<div style="height:14px;width:{pct}%;background:#087f80;'
            f'border-radius:3px"></div></div><strong>{value}</strong></div>')
    return result + "</div>"


def contact_timeline(history, employment):
    """Compact overview of when recorded LinkedIn messages and work changes occurred."""
    by_year, undated = year_counts(history)
    html = '<section><h2>Tijdlijn</h2><p class="muted">LinkedIn-berichten per jaar; '
    html += 'dit is niet hetzelfde als alle persoonlijke contactmomenten.</p>'
    html += _bars(sorted(by_year))
    if undated:
        html += f'<p class="muted">{undated} berichten zonder herkende datum.</p>'
    if employment:
        html += '<h3>Waargenomen loopbaanwijzigingen</h3>'
        html += '<p class="muted">De datum is wanneer een export de wijziging liet zien, niet de echte overstapdatum.</p>'
        for job in employment:
            html += (f"<article><small>{escape(job['first_seen_at'][:10])}</small> · "
                     f"{escape(job['company'] or 'Onbekende werkgever')} — "
                     f"{escape(job['position'] or 'Onbekende functie')}</article>")
    return html + '</section>'


def network_activity(db):
    """Aggregated per-year messages and per-contact last activity, without scoring people."""
    rows = db.execute("""
        SELECT m.date, m.sender_url, cm.contact_url, c.first_name, c.last_name
        FROM messages m
        LEFT JOIN contact_messages cm ON cm.message_key = m.message_key
        LEFT JOIN contacts c ON c.url = cm.contact_url
    """).fetchall()
    # Group by unique message records: a group message may link several contacts.
    date_rows = db.execute("SELECT date FROM messages").fetchall()
    annual, undated = year_counts(date_rows)
    contacts = defaultdict(lambda: {"messages": 0, "last": None, "name": ""})
    for row in rows:
        url = row["contact_url"]
        if not url:
            continue
        c = contacts[url]
        c["messages"] += 1
        c["name"] = " ".join(filter(None, (row["first_name"], row["last_name"])))
        d = parse_date(row["date"])
        if d and (c["last"] is None or d > c["last"]):
            c["last"] = d
    # Only a descriptive list, not a claim that a relationship is important/close.
    cutoff = datetime.now(timezone.utc).year - 2
    dormant = sorted(
        ((url, c) for url, c in contacts.items()
         if c["messages"] >= 3 and c["last"] and c["last"].year <= cutoff),
        key=lambda pair: (-pair[1]["messages"], pair[1]["name"].casefold()),
    )[:40]
    html = ('<section><h2>Berichten per jaar</h2>'
            '<p class="muted">Op basis van de geïmporteerde LinkedIn-berichten. '
            'Groepsberichten tellen hier één keer mee.</p>')
    html += _bars(sorted(annual))
    if undated:
        html += f'<p class="muted">{undated} berichten hebben geen herkende datum.</p>'
    html += '</section><section><h2>Contacten om opnieuw te bekijken</h2>'
    html += ('<p class="muted">Minstens drie gekoppelde LinkedIn-berichten en geen '
             'herkend LinkedIn-bericht in de afgelopen twee kalenderjaren. '
             'Dit zegt niets over gesprekken buiten LinkedIn.</p>')
    if not dormant:
        html += '<p>Geen contacten gevonden met deze selectie.</p>'
    for url, c in dormant:
        name = escape(c["name"] or url)
        link = quote(url, safe="")
        date = c["last"].strftime("%Y-%m-%d")
        html += (f'<article><a href="/contact?url={link}"><strong>{name}</strong></a><br>'
                 f'<small>{c["messages"]} berichten · laatste LinkedIn-bericht: {date}</small></article>')
    html += '</section>'
    return html
