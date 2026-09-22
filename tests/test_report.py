"""What the reporter must never do, held to tests.

It is one file that reads somebody's machine and writes a document they are asked to send to
strangers. Two promises carry all of it: the file says only what the machine's own records say,
and nothing in it can be free text. Everything here checks one of those two.

    py tests/test_report.py            (or: py -m unittest discover -s tests)
"""
from __future__ import annotations

import json
import pathlib
import re
import sqlite3
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

import codex_compat_report as reporter  # noqa: E402

NOW = 1_800_000_000.0
VERSION = "codex-cli 0.155.0-alpha.9.2"
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"

COLUMNS = ("interruption_id", "thread_id", "turn_id", "category", "state", "last_error",
           "detected_at", "resumed_at", "outcome_at", "submitted_at", "recovery_turn_id",
           "recovery_turn_status", "gate_eval", "reset_at", "limit_type")
GATES = json.dumps({"engine_compatible": ["PASS", "ok"], "identity": ["PASS", "ok"],
                    "thread_available": ["PASS", "ok"], "usage": ["PASS", "ok"]})


def record(**fields) -> dict:
    row = {name: None for name in COLUMNS}
    row.update({"interruption_id": "a" * 64, "thread_id": THREAD, "turn_id": TURN,
                "category": "usage_limit", "state": "recovered", "last_error": "progress_observed",
                "detected_at": NOW - 3600, "resumed_at": NOW - 1800, "outcome_at": NOW - 900,
                "submitted_at": NOW - 1800, "recovery_turn_id": TURN,
                "recovery_turn_status": "completed", "gate_eval": GATES,
                "reset_at": NOW - 1200, "limit_type": "codex:primary"})
    row.update(fields)
    return row


class Installation:
    """A product installation on disk, with only what the reporter reads."""

    def __init__(self, rows=(), *, log_lines=None, engine=VERSION):
        self.temporary = tempfile.TemporaryDirectory()
        self.home = pathlib.Path(self.temporary.name)
        (self.home / "config").mkdir(parents=True)
        (self.home / "logs").mkdir()
        (self.home / "app" / ".codex-plugin").mkdir(parents=True)
        (self.home / "app" / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "codex-auto-resume", "version": "0.6.9"}), encoding="utf-8")
        (self.home / "config" / "compatibility.json").write_text(json.dumps(
            {"engine": {"version": engine}, "capabilities": {}}), encoding="utf-8")
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - 7200))
        lines = log_lines if log_lines is not None else [
            "[%s] engine %s; is compatible: its local checks pass" % (when, engine)]
        (self.home / "logs" / "auto-resume.log").write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.codex = self.home / "codex-home"
        self.codex.mkdir()
        database = sqlite3.connect(self.home / "config" / "state.sqlite")
        database.execute("CREATE TABLE interruptions (%s)" % ", ".join(COLUMNS))
        for row in rows:
            database.execute("INSERT INTO interruptions VALUES (%s)" % ", ".join("?" * len(COLUMNS)),
                             [row[name] for name in COLUMNS])
        database.commit()
        database.close()

    def __enter__(self):
        self.patches = [mock.patch.object(reporter, "PRODUCT", self.home),
                        mock.patch.object(reporter, "CODEX", self.codex)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self.patches:
            patch.stop()
        self.temporary.cleanup()
        return False


class ReportTests(unittest.TestCase):
    def test_a_machine_with_records_reports_them(self):
        with Installation([record()]):
            report = reporter.build("someone")
        self.assertEqual(report["format"], reporter.FORMAT)
        self.assertEqual(report["codex_version"], VERSION)
        self.assertEqual(len(report["records"]), 1)
        self.assertEqual(report["records"][0]["state"], "recovered")
        self.assertEqual(report["reporter"]["github_login"], "someone")

    def test_a_machine_with_nothing_installed_is_refused(self):
        with tempfile.TemporaryDirectory() as empty:
            with mock.patch.object(reporter, "PRODUCT", pathlib.Path(empty)):
                with self.assertRaises(reporter.Refused):
                    reporter.build("someone")

    def test_a_login_that_is_not_one_is_refused(self):
        for bad in ("", "not a login", "-leading", "trailing-", "a" * 40, "sla/sh"):
            with self.subTest(bad):
                with self.assertRaises(reporter.Refused):
                    reporter.check_login(bad)
        for good in ("a", "songyb111-gachon", "A-1"):
            self.assertEqual(reporter.check_login(good), good)


class NothingButCountsTests(unittest.TestCase):
    """The promise that decides whether this tool may exist at all."""

    def test_a_word_the_product_does_not_publish_never_travels(self):
        secret = "C:/Users/someone/plans/quarterly.txt"
        with Installation([record(state=secret, last_error=secret, category=secret,
                                  recovery_turn_status=secret)]):
            report = reporter.build("someone")
        written = json.dumps(report)
        self.assertNotIn("quarterly", written)
        self.assertNotIn("Users", written)
        kept = report["records"][0]
        self.assertEqual([kept["state"], kept["reason"], kept["category"], kept["turn_status"]],
                         ["other"] * 4)

    def test_no_identifier_or_path_reaches_the_file(self):
        with Installation([record()]):
            report = reporter.build("someone")
        written = json.dumps(report)
        for forbidden in (THREAD, TURN, "a" * 64, str(reporter.HOME)):
            with self.subTest(forbidden[:24]):
                self.assertNotIn(forbidden, written)
        self.assertNotIn("\\\\", written, "a Windows path would show its separators")

    def test_every_string_in_the_file_is_one_of_a_known_few(self):
        """Read the whole document and refuse anything that is not a word, a time or a count."""
        with Installation([record()]):
            report = reporter.build("songyb111-gachon")
        allowed = (reporter.CATEGORIES | reporter.STATES | reporter.REASONS | reporter.TURN_STATUSES
                   | set(reporter.PROGRESS) | set(reporter.EXERCISED)
                   | {"VERIFIED", "CHECKED", "PASS", "NONE", VERSION, reporter.FORMAT,
                      "codex-compat-reporter", "songyb111-gachon"})
        sentences = {report["note"], report["recorded_by"], report["attribution"]["rule"]}
        times = re.compile(r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
        # One word, ASCII, no separator and no space: a version or a login, never a sentence,
        # a path or anything somebody typed.
        plain = re.compile(r"\A[0-9A-Za-z_.\-]{1,40}\Z")

        def walk(value, where):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertRegex(key, r"\A[a-z_A-Z]+\Z", "a key of " + where)
                    walk(item, where + "." + key)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, "%s[%d]" % (where, index))
            elif isinstance(value, str) and value not in sentences:
                self.assertTrue(value in allowed or times.match(value) or plain.match(value),
                                "%s is free text: %r" % (where, value))

        walk(report, "report")


class AttributionTests(unittest.TestCase):
    """A record counts for a version only when the log puts that version on both sides of it."""

    def timeline(self):
        return [(NOW - 10000, "codex-cli 0.150.0"), (NOW - 5000, VERSION)]

    def test_a_record_between_two_reports_of_one_version_counts(self):
        self.assertEqual(reporter.version_at(self.timeline(), NOW - 4000, NOW - 3000, VERSION),
                         VERSION)

    def test_a_record_that_straddles_an_upgrade_counts_for_neither(self):
        self.assertIsNone(reporter.version_at(self.timeline(), NOW - 6000, NOW - 4000, VERSION))

    def test_a_record_before_any_report_counts_for_nothing(self):
        self.assertIsNone(reporter.version_at(self.timeline(), NOW - 20000, NOW - 19000, VERSION))

    def test_a_record_after_the_last_report_counts_for_what_is_installed_now(self):
        self.assertEqual(reporter.version_at(self.timeline(), NOW - 100, NOW, VERSION), VERSION)
        self.assertIsNone(reporter.version_at(self.timeline(), NOW - 100, NOW, "codex-cli 0.156.0"))

    def test_only_this_versions_records_are_reported(self):
        when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - 9000))
        lines = ["[%s] engine codex-cli 0.150.0; is compatible: its local checks pass" % when,
                 "[%s] engine %s; is compatible: its local checks pass"
                 % (time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(NOW - 5000)), VERSION)]
        old = record(detected_at=NOW - 8000, resumed_at=NOW - 7900, outcome_at=NOW - 7800)
        with Installation([old, record()], log_lines=lines):
            report = reporter.build("someone")
        self.assertEqual(len(report["records"]), 1, "the older engine's record is not this one's")


class GradeTests(unittest.TestCase):
    """What the report says it earns, which the project recomputes anyway."""

    def test_a_delivered_recovery_that_held_is_verified(self):
        with Installation([record()]):
            report = reporter.build("someone")
        self.assertEqual(report["capabilities"]["exact_thread_recovery"]["level"], "VERIFIED")
        self.assertEqual(report["verdict"], "PASS")

    def test_a_recovery_that_never_reached_codex_verifies_nothing(self):
        with Installation([record(state="waiting_for_usage", resumed_at=None, outcome_at=None,
                                  submitted_at=None, recovery_turn_id=None,
                                  recovery_turn_status=None, last_error="usage_unavailable")]):
            report = reporter.build("someone")
        levels = {name: entry["level"] for name, entry in report["capabilities"].items()}
        self.assertNotIn("VERIFIED", levels.values())
        self.assertIn(report["verdict"], ("CHECKED", "NONE"))

    def test_the_newest_history_generation_is_the_one_read(self):
        with Installation([record()]) as installation:
            for number in (2, 9, 10):
                (installation.codex / ("thread_history_%d.sqlite" % number)).write_bytes(b"")
            self.assertEqual(reporter.newest_history().name, "thread_history_10.sqlite")


if __name__ == "__main__":
    unittest.main()
