import io
import json
import sqlite3
import unittest
import zipfile

from app.person_ids import migrate as migrate_people,account_person
from app.twitter import migrate,import_archive


def archive():
    data={
        "account.js":[{"account":{"accountId":"7514442","username":"elegantchaos"}}],
        "follower.js":[{"follower":{"accountId":"12345"}}],
        "following.js":[{"following":{"accountId":"12345"}}],
        "tweets.js":[{"tweet":{
            "id_str":"99999","created_at":"Wed Jan 01 12:00:00 +0000 2014",
            "full_text":"Hoi @oudeNaam",
            "in_reply_to_user_id_str":"12345","in_reply_to_screen_name":"oudeNaam",
            "entities":{"user_mentions":[{"id_str":"12345","screen_name":"oudeNaam"}]}
        }}],
        "direct-messages.js":[{"dmConversation":{"conversationId":"7514442-12345",
            "messages":[{"messageCreate":{"id":"88888","senderId":"12345",
                "recipientId":"7514442","createdAt":"2014-01-02T12:00:00.000Z",
                "text":"Persoonlijk bericht"}}]}}],
    }
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,"w") as z:
        for name,payload in data.items():
            z.writestr("data/"+name,"window.YTD."+name[:-3]+".part0 = "+
                       json.dumps(payload))
    return stream.getvalue()


class TwitterImportTests(unittest.TestCase):
    def setUp(self):
        self.db=sqlite3.connect(":memory:")
        self.db.row_factory=sqlite3.Row
        migrate_people(self.db)
        migrate(self.db)

    def test_historical_id_and_handle_retained(self):
        counts=import_archive(self.db,archive())
        self.assertEqual(counts["tweets"],1)
        self.assertEqual(counts["dms"],1)
        self.assertEqual(counts["followers"],1)
        pid=account_person(self.db,"twitter","12345")
        self.assertIsNotNone(pid)
        self.assertNotEqual(pid,account_person(self.db,"twitter","7514442"))
        self.assertEqual(self.db.execute(
            "SELECT handle FROM twitter_handles WHERE user_id='12345'"
        ).fetchone()["handle"],"oudenaam")
        self.assertEqual(self.db.execute(
            "SELECT content FROM twitter_dms WHERE dm_id='88888'"
        ).fetchone()["content"],"Persoonlijk bericht")

    def test_repeated_import_does_not_duplicate(self):
        import_archive(self.db,archive())
        import_archive(self.db,archive())
        for table in ("twitter_tweets","twitter_dms","twitter_tweets_fts","twitter_dms_fts"):
            self.assertEqual(self.db.execute(
                "SELECT count(*) FROM "+table).fetchone()[0],1)

    def test_invalid_archive_rejected(self):
        with self.assertRaises(ValueError):
            import_archive(self.db,b"not a zip")

if __name__=="__main__":
    unittest.main()
