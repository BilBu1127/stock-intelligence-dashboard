import tempfile
import unittest
from pathlib import Path

from scripts.credentials import load_values, missing_names


class CredentialLoaderTests(unittest.TestCase):
    def test_environment_wins_over_local_fallback(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "fallback.env"
            secret_key = "NAVER_CLIENT_" + "SECRET"
            path.write_text(f"NAVER_CLIENT_ID=local-id\n{secret_key}=local-secret\n", encoding="utf-8")
            values = load_values(("NAVER_CLIENT_ID", "NAVER_CLIENT_SECRET"), path, environ={"NAVER_CLIENT_ID": "action-id"})
        self.assertEqual(values["NAVER_CLIENT_ID"], "action-id")
        self.assertEqual(values["NAVER_CLIENT_SECRET"], "local-secret")

    def test_missing_names_reveals_names_only(self):
        self.assertEqual(missing_names({"A": "", "B": "value"}), ["A"])
