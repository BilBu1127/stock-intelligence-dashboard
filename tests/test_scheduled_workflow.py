import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]
SCHEDULED_PATH = ROOT / ".github" / "workflows" / "scheduled-portfolio-update.yml"
MANUAL_PATH = ROOT / ".github" / "workflows" / "manual-production-update.yml"


class ScheduledWorkflowPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.scheduled_text = SCHEDULED_PATH.read_text(encoding="utf-8")
        cls.manual_text = MANUAL_PATH.read_text(encoding="utf-8")
        cls.workflow = yaml.load(cls.scheduled_text, Loader=yaml.BaseLoader)

    def test_schedule_uses_seoul_0815_and_2015(self):
        triggers = self.workflow["on"]
        self.assertIn("workflow_dispatch", triggers)
        self.assertEqual(triggers["schedule"], [{"cron": "15 8,20 * * *", "timezone": "Asia/Seoul"}])
        self.assertNotIn("push", triggers)
        self.assertNotIn("pull_request", triggers)

    def test_permissions_are_contents_write_only(self):
        self.assertEqual(self.workflow["permissions"], {"contents": "write"})

    def test_scheduled_update_is_main_only(self):
        self.assertIn("if: github.ref == 'refs/heads/main'", self.scheduled_text)
        self.assertIn("ref: main", self.scheduled_text)
        self.assertIn('test "$(git branch --show-current)" = "main"', self.scheduled_text)
        self.assertIn("--target-branch main", self.scheduled_text)
        self.assertIn("--scheduled-production", self.scheduled_text)
        self.assertIn("git push origin HEAD:main", self.scheduled_text)

    def test_manual_staging_workflow_still_blocks_main(self):
        self.assertIn('test "$TARGET_REF" != "main"', self.manual_text)
        self.assertIn('test "$TARGET_REF" = "automation-staging"', self.manual_text)

    def test_fail_fast_validation_precedes_external_collection(self):
        tests = self.scheduled_text.index("- name: Run Python tests")
        javascript = self.scheduled_text.index("- name: Check JavaScript syntax")
        existing_data = self.scheduled_text.index("- name: Validate existing public data")
        external = self.scheduled_text.index("- name: Generate and apply validated incremental update")
        self.assertLess(tests, javascript)
        self.assertLess(javascript, existing_data)
        self.assertLess(existing_data, external)

    def test_allowlist_and_empty_commit_guards_exist(self):
        self.assertIn("data/news/by-company/*.json", self.scheduled_text)
        self.assertIn("data/earnings/by-company/*.json", self.scheduled_text)
        self.assertIn("data/disclosures/by-company/*.json", self.scheduled_text)
        self.assertIn("data/state/*.json", self.scheduled_text)
        self.assertIn("Disallowed repository change", self.scheduled_text)
        self.assertIn("No data changes; no commit created", self.scheduled_text)
        self.assertIn('test "${#staged[@]}" -gt 0', self.scheduled_text)

    def test_integrity_failure_blocks_commit(self):
        self.assertIn("--data-only", self.scheduled_text)
        self.assertIn('report.get("commit_eligible")', self.scheduled_text)
        self.assertIn("Validate generated public data", self.scheduled_text)

    def test_concurrency_matches_manual_update(self):
        scheduled = self.workflow["concurrency"]
        manual = yaml.load(self.manual_text, Loader=yaml.BaseLoader)["concurrency"]
        self.assertEqual(scheduled["group"], "portfolio-production-update")
        self.assertEqual(scheduled, manual)
        self.assertEqual(self.workflow["jobs"]["update"]["timeout-minutes"], "75")

    def test_force_push_is_absent(self):
        lowered = self.scheduled_text.casefold()
        self.assertNotIn("git push --force", lowered)
        self.assertNotIn("git push -f", lowered)


if __name__ == "__main__":
    unittest.main()
