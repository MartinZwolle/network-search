"""Historical Twitter archive import. Preserve immutable numeric IDs and observed handles.

A handle is only an observation at export time; it is never treated as
proof of identity or automatically merged with a person on another network.
"""
import io
import json
import re
import zipfile
from datetime import datetime, timezone
from app.person_ids import ensure_account

MAX_ZIP=100*1024*1024
MAX_JSON=55*1024*1024
MAX_TOTAL=95*1024*1024
FILES={"account.js","tweets.js","following.js","follower.js",
       "direct-messages.js"}

def migrate(db):
    db.executescript("""
    CREATE TABLE IF NOT EXISTS twitter_accounts (
      user_id TEXT PRIMARY KEY, following INTEGER NOT NULL DEFAULT 0,
      follower INTEGER NOT NULL DEFAULT 0, is_self INTEGER NOT NULL DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS twitter_handles (
      user_id TEXT NOT NULL, handle TEXT NOT NULL, source TEXT NOT NULL,
      first_seen TEXT NOT NULL DEFAULT '', last_seen TEXT NOT NULL DEFAULT '',
      PRIMARY KEY(user_id,handle,source)
    );
    CREATE INDEX IF NOT EXISTS idx_twitter_handles_name
      ON twitter_handles(handle);
    CREATE TABLE IF NOT EXISTS twitter_tweets (
      tweet_id TEXT PRIMARY KEY, author_id TEXT NOT NULL,
      created_at TEXT NOT NULL, content TEXT NOT NULL,
      reply_to_user_id TEXT NOT NULL DEFAULT '',
      reply_to_tweet_id TEXT NOT NULL DEFAULT '',
      is_retweet INTEGER NOT NULL DEFAULT 0
    );
    CREATE INDEX IF NOT EXISTS idx_twitter_tweets_date ON twitter_tweets(created_at);
    CREATE TABLE IF NOT EXISTS twitter_mentions (
      tweet_id TEXT NOT NULL, user_id TEXT NOT NULL,
      handle TEXT NOT NULL DEFAULT '', PRIMARY KEY(tweet_id,user_id)
    );
    CREATE INDEX IF NOT EXISTS idx_twitter_mentions_user
      ON twitter_mentions(user_id);
    CREATE TABLE IF NOT EXISTS twitter_dms (
      dm_id TEXT PRIMARY KEY, conversation_id TEXT NOT NULL,
      sender_id TEXT NOT NULL, recipient_id TEXT NOT NULL,
      created_at TEXT NOT NULL, content TEXT NOT NULL
    );
    CREATE INDEX IF NOT EXISTS idx_twitter_dms_date ON twitter_dms(created_at);
    CREATE INDEX IF NOT EXISTS idx_twitter_dms_sender ON twitter_dms(sender_id);
    CREATE INDEX IF NOT EXISTS idx_twitter_dms_recipient ON twitter_dms(recipient_id);
    CREATE VIRTUAL TABLE IF NOT EXISTS twitter_tweets_fts
      USING fts5(tweet_id UNINDEXED,content);
    CREATE VIRTUAL TABLE IF NOT EXISTS twitter_dms_fts
      USING fts5(dm_id UNINDEXED,content);
    """)

def _id(value):
    value=str(value or "").strip()
    return value if re.fullmatch(r"[0-9]{1,25}",value) else ""

def _handle(value):
    value=str(value or "").strip().lstrip("@").casefold()
    return value if re.fullmatch(r"[a-z0-9_]{1,15}",value) else ""

def _stamp(value):
    value=str(value or "").strip()
    if not value:
        return ""
    try:
        d=datetime.fromisoformat(value.replace("Z","+00:00"))
    except ValueError:
        try:
            d=datetime.strptime(value,"%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            return ""
    return d.astimezone(timezone.utc).isoformat() if d.tzinfo else d.replace(tzinfo=timezone.utc).isoformat()

def _read(archive, member):
    info=archive.getinfo(member)
    if info.file_size>MAX_JSON:
        raise ValueError("Twitter JSON-bestand te groot")
    raw=archive.read(member)
    text=raw.decode("utf-8-sig")
    marker=text.find("=")
    if marker<0:
        raise ValueError("Twitter JSON-formaat niet herkend")
    result=json.loads(text[marker+1:].strip().rstrip(";"))
    if not isinstance(result,list):
        raise ValueError("Verwacht een Twitter-array")
    return result

def _account(db,user_id):
    uid=_id(user_id)
    if not uid:
        return ""
    db.execute("INSERT OR IGNORE INTO twitter_accounts(user_id) VALUES(?)",(uid,))
    ensure_account(db,"twitter",uid)
    return uid

def _observe(db,user_id,handle,source,stamp=""):
    uid=_account(db,user_id)
    name=_handle(handle)
    if uid and name:
        db.execute("""INSERT INTO twitter_handles
          (user_id,handle,source,first_seen,last_seen) VALUES(?,?,?,?,?)
          ON CONFLICT(user_id,handle,source) DO UPDATE SET
            first_seen=CASE WHEN excluded.first_seen<>'' AND
              (twitter_handles.first_seen='' OR excluded.first_seen<twitter_handles.first_seen)
              THEN excluded.first_seen ELSE twitter_handles.first_seen END,
            last_seen=CASE WHEN excluded.last_seen>twitter_handles.last_seen
              THEN excluded.last_seen ELSE twitter_handles.last_seen END""",
          (uid,name,source,stamp,stamp))
    return uid

def import_archive(db,content):
    if len(content)>MAX_ZIP:
        raise ValueError("Twitter ZIP is te groot (maximaal 100 MB)")
    try:
        archive=zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile as exc:
        raise ValueError("Geen geldig Twitter ZIP-archief") from exc
    with archive:
        members={f"data/{name}" for name in FILES}
        present=members.intersection(set(archive.namelist()))
        if "data/account.js" not in present or "data/tweets.js" not in present:
            raise ValueError("Twitter-archief mist data/account.js of data/tweets.js")
        if sum(archive.getinfo(name).file_size for name in present)>MAX_TOTAL:
            raise ValueError("Twitter JSON-bestanden samen te groot")
        data={name[5:]:_read(archive,name) for name in sorted(present)}
    profile=data["account"][0].get("account",{}) if data["account"] else {}
    self_id=_id(profile.get("accountId"))
    if not self_id:
        raise ValueError("Twitter-account-ID ontbreekt")
    self_handle=_handle(profile.get("username"))
    _observe(db,self_id,self_handle,"archive_account")
    db.execute("UPDATE twitter_accounts SET is_self=1 WHERE user_id=?",(self_id,))
    counts={"tweets":0,"mentions":0,"dms":0,"following":0,"followers":0,
            "identities":0,"self_id":self_id}
    for section,flag in (("follower.js","follower"),("following.js","following")):
        if section not in data:
            continue
        # New snapshots represent present following/follower status; old
        # tweet identities and observed handles are never removed.
        db.execute(f"UPDATE twitter_accounts SET {flag}=0")
        for item in data[section]:
            uid=_account(item.get(section[:-3],{}).get("accountId"))
            if uid:
                db.execute(f"UPDATE twitter_accounts SET {flag}=1 WHERE user_id=?",(uid,))
                counts[section[:-3]+"s" if section=="follower.js" else "following"]+=1
    for record in data["tweets.js"]:
        item=record.get("tweet",{})
        tid=_id(item.get("id_str") or item.get("id"))
        date=_stamp(item.get("created_at"))
        if not tid or not date:
            continue
        body=item.get("full_text")
        if not isinstance(body,str):
            continue
        reply=_id(item.get("in_reply_to_user_id_str") or item.get("in_reply_to_user_id"))
        reply_tweet=_id(item.get("in_reply_to_status_id_str") or item.get("in_reply_to_status_id"))
        db.execute("""INSERT OR IGNORE INTO twitter_tweets
            (tweet_id,author_id,created_at,content,reply_to_user_id,reply_to_tweet_id,is_retweet)
            VALUES(?,?,?,?,?,?,?)""",
            (tid,self_id,date,body,reply,reply_tweet,
             int(bool(item.get("retweeted")) or body.startswith("RT @"))))
        db.execute("INSERT OR IGNORE INTO twitter_tweets_fts(tweet_id,content) VALUES(?,?)",
                   (tid,body)) if db.execute(
                   "SELECT changes()").fetchone()[0] else None
        counts["tweets"]+=1
        if reply:
            _observe(db,reply,item.get("in_reply_to_screen_name"),"reply",date)
        mentions=item.get("entities",{}).get("user_mentions",[])
        for m in mentions if isinstance(mentions,list) else []:
            uid=_observe(db,m.get("id_str") or m.get("id"),m.get("screen_name"),"mention",date)
            if not uid:
                continue
            db.execute("INSERT OR IGNORE INTO twitter_mentions VALUES(?,?,?)",
                       (tid,uid,_handle(m.get("screen_name"))))
            counts["mentions"]+=1
    for conv in data.get("direct-messages.js",[]):
        thread=conv.get("dmConversation",{})
        conversation_id=str(thread.get("conversationId") or "")
        for wrapped in thread.get("messages",[]):
            msg=wrapped.get("messageCreate",{})
            mid=_id(msg.get("id"))
            sender=_account(db,msg.get("senderId"))
            recipient=_account(db,msg.get("recipientId"))
            date=_stamp(msg.get("createdAt"))
            body=msg.get("text")
            if not(mid and sender and recipient and date and isinstance(body,str)):
                continue
            db.execute("""INSERT OR IGNORE INTO twitter_dms
              (dm_id,conversation_id,sender_id,recipient_id,created_at,content)
              VALUES(?,?,?,?,?,?)""",
              (mid,conversation_id,sender,recipient,date,body))
            if db.execute("SELECT changes()").fetchone()[0]:
                db.execute("INSERT INTO twitter_dms_fts(dm_id,content) VALUES(?,?)",(mid,body))
            counts["dms"]+=1
    counts["identities"]=db.execute("SELECT COUNT(*) FROM twitter_accounts").fetchone()[0]
    return counts
