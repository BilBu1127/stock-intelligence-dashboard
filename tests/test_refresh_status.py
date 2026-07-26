import json
import tempfile
import unittest
from pathlib import Path

from scripts.refresh_status import update_refresh_status


class RefreshStatusTests(unittest.TestCase):
    def make_data_root(self, directory):
        root = Path(directory) / "data"
        for group, payload in (
            ("earnings", {"generatedAt": "2026-07-26T07:00:00Z"}),
            ("disclosures", {"generatedAt": "2026-07-26T08:00:00Z"}),
            ("news", {"generated_at": "2026-07-26T09:00:00Z"}),
        ):
            (root / group).mkdir(parents=True, exist_ok=True)
            (root / group / "index.json").write_text(json.dumps(payload), encoding="utf-8")
        return root

    def test_successful_refresh_updates_even_without_content_changes(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_data_root(directory)
            status = update_refresh_status(root, "2026-07-26T10:00:00Z", content_changed=False)
            self.assertEqual(status["lastSuccessfulRefreshAt"], "2026-07-26T10:00:00Z")
            self.assertEqual(status["lastContentChangedAt"], "2026-07-26T09:00:00Z")

    def test_content_timestamp_changes_only_when_content_changed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = self.make_data_root(directory)
            update_refresh_status(root, "2026-07-26T10:00:00Z", content_changed=False)
            status = update_refresh_status(root, "2026-07-26T11:00:00Z", content_changed=True)
            self.assertEqual(status["lastSuccessfulRefreshAt"], "2026-07-26T11:00:00Z")
            self.assertEqual(status["lastContentChangedAt"], "2026-07-26T11:00:00Z")
