"""Basic security regression checks for the Hermes integration."""
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from app.hermes_api import authorize


class HermesAuthTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.key_path = Path(self.temp.name) / "api-key"
        self.key = "a" * 64
        self.key_path.write_text(self.key, encoding="utf-8")
        self.env = patch.dict(os.environ, {"FARLEY_API_KEY_FILE": str(self.key_path)})
        self.env.start()

    def tearDown(self):
        self.env.stop()
        self.temp.cleanup()

    def test_bearer_works(self):
        self.assertIsNone(authorize("Bearer " + self.key, None))

    def test_x_api_key_works(self):
        self.assertIsNone(authorize(None, self.key))

    def test_missing_and_invalid_are_rejected(self):
        for authorization, x_api_key in ((None, None), ("Bearer wrong", None),
                                          (None, "wrong"), ("Basic abc", None),
                                          ("Bearer " + self.key, self.key)):
            with self.subTest(authorization=bool(authorization), x=bool(x_api_key)):
                with self.assertRaises(HTTPException) as caught:
                    authorize(authorization, x_api_key)
                self.assertEqual(caught.exception.status_code, 401)

    def test_missing_key_file_fails_closed(self):
        self.key_path.unlink()
        with self.assertRaises(HTTPException) as caught:
            authorize("Bearer " + self.key, None)
        self.assertEqual(caught.exception.status_code, 503)

    def test_short_key_file_fails_closed(self):
        self.key_path.write_text("short", encoding="utf-8")
        with self.assertRaises(HTTPException) as caught:
            authorize("Bearer short", None)
        self.assertEqual(caught.exception.status_code, 503)


if __name__ == "__main__":
    unittest.main()
