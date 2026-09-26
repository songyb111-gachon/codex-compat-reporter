"""What the reporter must never do, held to tests.

It is one file that reads somebody's machine and writes a document they are asked to send to
strangers. What it promises, and where each promise is held:

- the file says only what the machine's own records say (ReportTests, AttributionTests,
  LocalChecksTests, CapabilityTests, DeliveredTests),
- nothing in it can be free text, an identifier or a path (NothingButCountsTests),
- it reads the machine and never writes to it (StateDatabaseTests, ReadOnlyTests),
- what is sent is exactly the file the person read, and only after they said yes (SubmitTests),
- a file the project would refuse is refused here first (ValidateTests),
- nothing it starts puts a console window on the screen (NoConsoleWindowTests),
- the command line says what happened, in words and in its exit code (CliTests).

Everything runs on synthetic installations in temporary folders; nothing here reads this
machine's own homes, and no test starts a real gh.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import ast
import base64
import contextlib
import hashlib
import importlib.util
import io
import json
import os
import pathlib
import re
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

# Before the module is imported, point its homes at a folder that does not exist, so that even a
# test that forgot to patch them could never read this machine's own installation.
_SANDBOX = pathlib.Path(tempfile.gettempdir()) / "codex-compat-reporter-tests-nowhere"
os.environ["CODEX_AUTO_RESUME_HOME"] = str(_SANDBOX / "product")
os.environ["CODEX_HOME"] = str(_SANDBOX / "codex")

import codex_compat_report as reporter  # noqa: E402

# The product's own checkout, when this one sits beside it (the maintainer's machine, or CAR_CHECKOUT).
# The tests that read it are skipped elsewhere, the public CI included.
PRODUCT = pathlib.Path(os.environ.get("CAR_CHECKOUT") or HERE.parent.parent / "codex-auto-resume")
PRODUCT_APP = PRODUCT / "src" / "codex_auto_resume" / "runtime" / "app.py"
# The receiving side's one reader of a report, which judges a pull request and files what passes.
PRODUCT_READER = PRODUCT / "build" / "community_report.py"

NOW = float(int(time.time()) - 10 * 86400)
VERSION = "codex-cli 0.155.0-alpha.9.2"
THREAD = "0a1b2c3d-0001-7000-8000-000000000001"
TURN = "0a1b2c3d-0002-7000-8000-000000000002"
LOGIN = "someone"
SHA = "0123456789abcdef0123456789abcdef01234567"

COLUMNS = ("interruption_id", "thread_id", "turn_id", "category", "state", "last_error",
           "detected_at", "resumed_at", "outcome_at", "submitted_at", "recovery_turn_id",
           "recovery_turn_status", "gate_eval", "reset_at", "limit_type", "history_hidden_at")
GATES = json.dumps({"engine_compatible": ["PASS", "ok"], "identity": ["PASS", "ok"],
                    "thread_available": ["PASS", "ok"], "usage": ["PASS", "ok"]})
# The sixteen capabilities the product's watcher judges (compat/model.py CAPABILITIES).
SIXTEEN = ("engine_present", "exact_thread_recovery", "usage_limit_detection", "usage_reset_hint",
           "usage_probe", "thread_eligibility", "loaded_state_detection", "recovery_turn_tracking",
           "queue_withdraw", "outcome_observation", "transient_classification", "projection_freshness",
           "empty_response_recovery", "not_loaded_recovery", "goal_continuation", "subagent_recovery")


def stamp(when) -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(when))


def engine_line(when, version, words) -> str:
    """A log line exactly as the product's runtime/app.py writes it."""
    return ("[%s] engine %s %s. Delivery is still proven per interruption before anything is marked "
            "resumed." % (stamp(when), version, words))


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

    def __init__(self, rows=(), *, log_lines=None, logs=None, engine=VERSION, capabilities=None,
                 compat=None, user_version=3, columns=COLUMNS, under="", state=True, history=True):
        self.temporary = tempfile.TemporaryDirectory()
        self.root = pathlib.Path(self.temporary.name)
        self.home = self.root / under / "product" if under else self.root / "product"
        (self.home / "config").mkdir(parents=True)
        (self.home / "logs").mkdir()
        (self.home / "app" / ".codex-plugin").mkdir(parents=True)
        (self.home / "app" / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "codex-auto-resume", "version": "0.6.9"}), encoding="utf-8")
        watcher = compat if compat is not None else {"engine": {"version": engine},
                                                     "capabilities": capabilities or {}}
        (self.home / "config" / "compatibility.json").write_text(json.dumps(watcher), encoding="utf-8")
        if logs is None:
            logs = {"auto-resume.log": log_lines if log_lines is not None else [
                engine_line(NOW - 7200, engine, reporter.ENGINE_LOG_WORDS["structurally_compatible"])]}
        for name, lines in logs.items():
            (self.home / "logs" / name).write_text("\n".join(lines) + "\n", encoding="utf-8")

        self.codex = self.home.parent / "codex-home"
        self.codex.mkdir()
        if history:
            database = sqlite3.connect(self.codex / "thread_history_10.sqlite")
            database.execute("CREATE TABLE thread_items (thread_id, turn_id, item_type, text)")
            database.executemany("INSERT INTO thread_items VALUES (?, ?, ?, ?)",
                                 [(THREAD, TURN, "agentMessage", "a private sentence")] * 2
                                 + [(THREAD, TURN, "fileChange", "C:/Users/someone/secret.txt")])
            database.commit()
            database.close()
        if state:
            database = sqlite3.connect(self.home / "config" / "state.sqlite")
            if columns:
                database.execute("CREATE TABLE interruptions (%s)" % ", ".join(columns))
                database.executemany("INSERT INTO interruptions VALUES (%s)" % ", ".join("?" * len(columns)),
                                     [[row.get(name) for name in columns] for row in rows])
            database.execute("PRAGMA user_version = %d" % user_version)
            database.commit()
            database.close()

    def __enter__(self):
        self.patches = [mock.patch.object(reporter, "PRODUCT", self.home),
                        mock.patch.object(reporter, "CODEX", self.codex),
                        mock.patch.object(reporter, "HOME", self.root)]
        for patch in self.patches:
            patch.start()
        return self

    def __exit__(self, *exc):
        for patch in self.patches:
            patch.stop()
        self.temporary.cleanup()
        return False

    def snapshot(self):
        """Every file under the installation and the Codex home, with its bytes and its mtime."""
        return {str(path): (hashlib.sha256(path.read_bytes()).hexdigest(), path.stat().st_mtime_ns)
                for path in sorted(self.root.rglob("*")) if path.is_file()
                and not path.is_relative_to(self.root / "work")}


def run_main(*argv):
    """(exit code, stdout, stderr) of the command line, as a person would see it."""
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        try:
            code = reporter.main(list(argv))
        except SystemExit as exit_:
            code = exit_.code
    return code, out.getvalue(), err.getvalue()


def load_product_reader():
    spec = importlib.util.spec_from_file_location("community_report_for_tests", PRODUCT_READER)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class ReportTests(unittest.TestCase):
    def test_a_machine_with_records_reports_them(self):
        with Installation([record()]):
            report = reporter.build(LOGIN)
        self.assertEqual(report["format"], reporter.FORMAT)
        self.assertEqual(report["codex_version"], VERSION)
        self.assertEqual(len(report["records"]), 1)
        self.assertEqual(report["records"][0]["state"], "recovered")
        self.assertEqual(report["records"][0]["progress_items"],
                         {"agentMessage": 2, "commandExecution": 0, "fileChange": 1, "mcpToolCall": 0})
        self.assertEqual(report["reporter"]["github_login"], LOGIN)

    def test_a_machine_with_nothing_installed_is_refused(self):
        with tempfile.TemporaryDirectory() as empty:
            with mock.patch.object(reporter, "PRODUCT", pathlib.Path(empty)):
                with self.assertRaises(reporter.Refused):
                    reporter.build(LOGIN)

    def test_a_login_that_is_not_one_is_refused(self):
        for bad in ("", "not a login", "-leading", "trailing-", "a" * 40, "sla/sh"):
            with self.subTest(bad):
                with self.assertRaises(reporter.Refused):
                    reporter.check_login(bad)
        for good in ("a", "songyb111-gachon", "A-1", "com10", "nul0"):
            self.assertEqual(reporter.check_login(good), good)

    def test_a_login_windows_keeps_for_a_device_is_refused_before_anything_is_written(self):
        """The project could not hold its folder: git for Windows refuses docs/evidence/community/nul/."""
        for reserved in ("nul", "NUL", "Con", "aux", "prn", "com1", "LPT9"):
            with self.subTest(reserved):
                with self.assertRaises(reporter.Refused) as refused:
                    reporter.check_login(reserved)
                self.assertIn("Windows keeps that name for a device", str(refused.exception))

    def test_records_hidden_with_clear_history_are_left_out(self):
        hidden = record(detected_at=NOW - 3000, resumed_at=NOW - 2900, outcome_at=NOW - 2800,
                        history_hidden_at=NOW - 100)
        notes = {}
        with Installation([record(), hidden]):
            report = reporter.build(LOGIN, notes=notes)
        self.assertEqual(len(report["records"]), 1)
        self.assertEqual(notes["hidden"], 1)

    def test_a_version_that_is_not_one_is_refused(self):
        with Installation([record()]):
            for bad in ("0.155.0 C:/Users/me", "latest", "1..2", "0.155.0.lock", "0.155.0."):
                with self.subTest(bad):
                    with self.assertRaises(reporter.Refused):
                        reporter.build("a", bad)
        self.assertEqual(reporter.canonical_version("0.155.0"), "codex-cli 0.155.0")
        self.assertEqual(reporter.canonical_version("codex-cli 0.155.0"), "codex-cli 0.155.0")

    def test_a_version_has_the_one_spelling_the_product_writes(self):
        for spelling, written in (("00.155.0", "0.155.0"), ("0.0155.0", "0.155.0"),
                                  ("0.155.0-alpha.09.2", "0.155.0-alpha.9.2"), ("0.155.0-alpha.9.0", "0.155.0-alpha.9")):
            with self.subTest(spelling):
                with self.assertRaises(reporter.Refused) as refused:
                    reporter.canonical_version(spelling)
                self.assertIn("give it as %s." % written, str(refused.exception))
        for outside in ("0.155.0-beta.1", "0.155", "1.2.3.4"):
            with self.subTest(outside), self.assertRaises(reporter.Refused):
                reporter.canonical_version(outside)
        self.assertEqual(reporter.canonical_version("0.155.0-alpha.0"), "codex-cli 0.155.0-alpha.0")

    def test_more_records_than_a_report_may_hold_are_refused_before_anything_is_written(self):
        rows = [record(detected_at=NOW - 5000 + n, resumed_at=NOW - 4000 + n, outcome_at=NOW - 3000 + n)
                for n in range(reporter.MAX_RECORDS + 1)]
        with Installation(rows, log_lines=[engine_line(NOW - 7200, VERSION, reporter.ENGINE_LOG_CHECKS_ONLY)]):
            with self.assertRaisesRegex(reporter.Refused, "at most 500"):
                reporter.build(LOGIN)
            with tempfile.TemporaryDirectory() as work, contextlib.chdir(work):
                code, _out, err = run_main("report", "--login", LOGIN)
                self.assertEqual((code, list(pathlib.Path(work).iterdir())), (2, []))
                self.assertIn("at most 500", err)


class NothingButCountsTests(unittest.TestCase):
    """The promise that decides whether this tool may exist at all."""

    def test_a_word_the_product_does_not_publish_never_travels(self):
        secret = "C:/Users/someone/plans/quarterly.txt"
        with Installation([record(state=secret, last_error=secret, category=secret,
                                  recovery_turn_status=secret)]):
            report = reporter.build(LOGIN)
        written = json.dumps(report)
        self.assertNotIn("quarterly", written)
        self.assertNotIn("Users", written)
        kept = report["records"][0]
        self.assertEqual([kept["state"], kept["reason"], kept["category"], kept["turn_status"]],
                         ["other"] * 4)

    def test_no_identifier_or_path_reaches_the_file(self):
        with Installation([record()]) as installation:
            report = reporter.build(LOGIN)
            written = reporter.encode(report).decode("ascii")
            homes = (installation.root, installation.home, installation.codex)
        # json.dumps writes a Windows path with doubled backslashes, so the forbidden forms are the
        # JSON-escaped ones as well as the plain ones.
        forbidden = [THREAD, TURN, "a" * 64, "a private sentence", "secret.txt"]
        for home in homes:
            forbidden += [str(home), json.dumps(str(home))[1:-1], home.as_posix()]
        for value in forbidden:
            with self.subTest(value[:24]):
                self.assertNotIn(value, written)
        self.assertNotIn("\\\\", written, "a Windows path would show its separators")

    def assert_known_few(self, report):
        """Read the whole document and refuse anything that is not a word, a time or a count."""
        words = (reporter.CATEGORIES | reporter.STATES | reporter.REASONS | reporter.TURN_STATUSES
                 | set(reporter.PROGRESS) | set(reporter.EXERCISED)
                 | {"VERIFIED", "CHECKED", "PASS", "NONE", "other", VERSION, reporter.FORMAT,
                    "codex-compat-reporter"})
        sentences = {report["note"], report["recorded_by"], report["attribution"]["rule"]}
        times = re.compile(r"\A\d{4}-\d\d-\d\dT\d\d:\d\d:\d\dZ\Z")
        # A plain word - a version or a login - is allowed only where a version or a login goes.
        plain = re.compile(r"\A[0-9A-Za-z_.\-]{1,40}\Z")
        plain_at = {"report.reporter.github_login", "report.reporter.tool_version",
                    "report.reporter.product_version", "report.reporter.windows"}
        uuid = re.compile(r"[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")
        hex64 = re.compile(r"[0-9a-fA-F]{64}")

        def walk(value, where):
            if isinstance(value, dict):
                for key, item in value.items():
                    self.assertRegex(key, r"\A[a-z_A-Z]+\Z", "a key of " + where)
                    walk(item, where + "." + key)
            elif isinstance(value, list):
                for index, item in enumerate(value):
                    walk(item, "%s[%d]" % (where, index))
            elif isinstance(value, str):
                self.assertIsNone(uuid.search(value), "%s holds an id: %r" % (where, value))
                self.assertIsNone(hex64.search(value), "%s holds a hash: %r" % (where, value))
                if value in sentences:
                    return
                self.assertTrue(value in words or times.match(value)
                                or (where in plain_at and plain.match(value)),
                                "%s is free text: %r" % (where, value))

        walk(report, "report")

    def test_every_string_in_the_file_is_one_of_a_known_few(self):
        with Installation([record()]):
            self.assert_known_few(reporter.build("songyb111-gachon"))

    def test_the_walk_catches_an_id_or_a_hash_even_where_a_plain_word_may_go(self):
        with Installation([record()]):
            report = reporter.build("songyb111-gachon")
        for leak in (THREAD, "a" * 64):
            with self.subTest(leak[:12]):
                leaked = json.loads(json.dumps(report))
                leaked["reporter"]["product_version"] = leak
                with self.assertRaises(AssertionError):
                    self.assert_known_few(leaked)
        leaked = json.loads(json.dumps(report))
        leaked["records"][0]["state"] = "songyb111-gachon"
        with self.assertRaises(AssertionError, msg="a plain word where a state goes is free text"):
            self.assert_known_few(leaked)


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

    def test_a_record_during_which_another_version_ran_counts_for_neither(self):
        timeline = [(100, "codex-cli 1"), (150, "codex-cli 2"), (300, "codex-cli 1")]
        self.assertIsNone(reporter.version_at(timeline, 120, 200, "codex-cli 1"))
        self.assertEqual(reporter.placement(timeline, 120, 200, "codex-cli 1")[1],
                         "the engine changed while it ran")

    def test_a_record_the_next_line_disowns_says_so_rather_than_that_it_changed_while_it_ran(self):
        timeline = [(100, "codex-cli 1"), (300, "codex-cli 2")]
        self.assertEqual(reporter.placement(timeline, 120, 200, "codex-cli 2"),
                         (None, "the next engine line after it names another version"))
        self.assertEqual(reporter.placement(timeline, 120, 200, "codex-cli 1"),
                         (None, "the next engine line after it names another version"))
        self.assertEqual(reporter.placement([(100, "codex-cli 1")], 120, 200, "codex-cli 2"),
                         (None, "the engine changed after it"))

    def test_only_this_versions_records_are_reported(self):
        words = reporter.ENGINE_LOG_WORDS["structurally_compatible"]
        lines = [engine_line(NOW - 9000, "codex-cli 0.150.0", words), engine_line(NOW - 5000, VERSION, words)]
        old = record(detected_at=NOW - 8000, resumed_at=NOW - 7900, outcome_at=NOW - 7800)
        with Installation([old, record()], log_lines=lines):
            report = reporter.build(LOGIN)
        self.assertEqual(len(report["records"]), 1, "the older engine's record is not this one's")

    def test_an_engine_line_in_a_rotated_log_is_read(self):
        """The product keeps five rotated copies; the engine line can be in any of them."""
        line = engine_line(NOW - 7200, VERSION, reporter.ENGINE_LOG_WORDS["verified"])
        with Installation([record()], logs={"auto-resume.log.3": [line],
                                            "auto-resume.log": ["[%s] nothing about the engine" % stamp(NOW)]}):
            report = reporter.build(LOGIN)
        self.assertEqual(len(report["records"]), 1)
        self.assertEqual(report["local_checks"]["reports"], 1)

    def test_the_rotated_logs_are_read_oldest_first(self):
        words = reporter.ENGINE_LOG_WORDS["verified"]
        logs = {"auto-resume.log.5": [engine_line(NOW - 9000, "codex-cli 0.150.0", words)],
                "auto-resume.log.1": [engine_line(NOW - 7200, VERSION, words)],
                "auto-resume.log": []}
        with Installation([record()], logs=logs):
            lines = reporter.log_lines()
            self.assertEqual([reporter.engine_version_of(text) for _when, text in lines],
                             ["codex-cli 0.150.0", VERSION])

    def test_status_says_how_many_records_could_not_be_placed_and_why(self):
        early = record(detected_at=NOW - 90000, resumed_at=NOW - 89000, outcome_at=NOW - 88000)
        with Installation([record(), early]):
            code, out, _err = run_main("status")
        self.assertEqual(code, 0)
        self.assertIn("2 in all: 1 on this engine version, 0 on other versions, 1 (1: no engine line "
                      "before it in the logs kept) not placed", out)


class LocalChecksTests(unittest.TestCase):
    """The product's own checks passing, read from its log in the words it writes."""

    def local_checks(self, words, version=VERSION, report_on=None):
        with Installation([], log_lines=[engine_line(NOW - 7200, version, words)], engine=version,
                          capabilities={}):
            return reporter.build(LOGIN, report_on)["local_checks"]

    def test_every_pass_wording_the_product_writes_is_counted(self):
        for word in ("verified", "structurally_compatible", "checked"):
            with self.subTest(word):
                checks = self.local_checks(reporter.ENGINE_LOG_WORDS[word])
                self.assertEqual((checks["reports"], checks["covers"]), (1, list(reporter.GATE)))
        for words in (reporter.ENGINE_LOG_CHECKS_ONLY,
                      "is not a version this tool was verified against; accepted because `codex queue` "
                      "still offers --thread/--message"):
            with self.subTest(words[:30]):
                self.assertEqual(self.local_checks(words)["reports"], 1)

    def test_the_incompatible_line_is_not_a_pass(self):
        """It says the checks pass, but the product sends nothing on that build."""
        checks = self.local_checks(reporter.ENGINE_LOG_WORDS["incompatible"])
        self.assertEqual((checks["reports"], checks["covers"]), (0, []))

    def test_an_alphas_lines_do_not_count_for_its_final_build(self):
        words = reporter.ENGINE_LOG_WORDS["verified"]
        lines = [engine_line(NOW - 7200 + n, VERSION, words) for n in range(3)]
        with Installation([], log_lines=lines, engine="codex-cli 0.155.0"):
            report = reporter.build(LOGIN, "0.155.0")
        self.assertEqual(report["local_checks"]["reports"], 0)
        self.assertEqual(report["verdict"], "NONE")

    def test_status_reads_the_same_words(self):
        with Installation([record()], log_lines=[engine_line(NOW - 7200, VERSION,
                                                             reporter.ENGINE_LOG_WORDS["checked"])]):
            _code, out, _err = run_main("status")
        self.assertIn("passed on this version (1 log line)", out)

    @unittest.skipUnless(PRODUCT_APP.is_file(), "the product checkout is not beside this one")
    def test_the_wordings_are_the_products_own(self):
        tree = ast.parse(PRODUCT_APP.read_text(encoding="utf-8"))
        found = {}
        for node in tree.body:
            if isinstance(node, ast.Assign) and isinstance(node.targets[0], ast.Name):
                if node.targets[0].id in ("ENGINE_LOG_WORDS", "ENGINE_LOG_CHECKS_ONLY"):
                    found[node.targets[0].id] = ast.literal_eval(node.value)
        self.assertEqual(found["ENGINE_LOG_WORDS"], reporter.ENGINE_LOG_WORDS)
        self.assertEqual(found["ENGINE_LOG_CHECKS_ONLY"], reporter.ENGINE_LOG_CHECKS_ONLY)


class CapabilityTests(unittest.TestCase):
    def test_the_watchers_sixteen_capabilities_become_at_most_the_ten_a_report_may_name(self):
        every = {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"} for name in SIXTEEN}
        with Installation([record()], capabilities=every):
            report = reporter.build(LOGIN)
        self.assertLessEqual(set(report["capabilities"]), set(reporter.EXERCISED))
        self.assertLessEqual(set(report["local_checks"]["covers"]), set(reporter.EXERCISED))
        self.assertNotIn("queue_withdraw", report["local_checks"]["covers"])
        self.assertEqual(reporter.validate(reporter.encode(report))[1], [])

    @unittest.skipUnless(PRODUCT_READER.is_file(), "the product's checkout is not beside this one")
    def test_the_receiving_side_accepts_what_the_sixteen_become(self):
        every = {name: {"state": "COMPATIBLE", "reason": "local_checks_passed"} for name in SIXTEEN}
        with Installation([record()], capabilities=every):
            raw = reporter.encode(reporter.build(LOGIN))
        _report, problems, _recomputed = load_product_reader().inspect(raw, author=LOGIN, releases=None)
        self.assertEqual(problems, [])

    def test_a_registry_backed_pass_is_a_local_pass_too(self):
        watcher = {"engine_present": {"reason": "registry_verified"},
                   "usage_probe": {"reason": "registry_checked"},
                   "thread_eligibility": {"reason": "local_check_failed"}}
        with Installation([], capabilities=watcher, log_lines=[]):
            covers = reporter.build(LOGIN)["local_checks"]["covers"]
        self.assertEqual(covers, ["engine_present", "usage_probe"])

    def test_a_watcher_report_of_the_wrong_shape_is_read_as_saying_nothing(self):
        for compat in ([1, 2], {"engine": "codex-cli 1", "capabilities": {"engine_present": "PASS"}},
                       {"engine": {"version": VERSION}, "capabilities": ["engine_present"]}):
            with self.subTest(compat):
                with Installation([record()], compat=compat):
                    report = reporter.build(LOGIN)
                self.assertEqual(report["codex_version"], VERSION)


class DeliveredTests(unittest.TestCase):
    def test_a_backfilled_turn_id_without_resumed_at_is_not_a_delivery(self):
        backfilled = record(state="outcome_unverified", resumed_at=None, outcome_at=None,
                            recovery_turn_status=None)
        with Installation([backfilled]):
            report = reporter.build(LOGIN)
        self.assertIsNone(report["records"][0]["delivered_at"])
        self.assertEqual(report["capabilities"]["exact_thread_recovery"]["confirmed"], 0)
        self.assertEqual(report["capabilities"]["outcome_observation"]["missed"], 0)
        self.assertNotEqual(report["verdict"], "PASS")

    def test_a_delivered_recovery_that_held_is_verified(self):
        with Installation([record()]):
            report = reporter.build(LOGIN)
        self.assertEqual(report["capabilities"]["exact_thread_recovery"]["level"], "VERIFIED")
        self.assertEqual(report["verdict"], "PASS")

    def test_a_recovery_that_never_reached_codex_verifies_nothing(self):
        with Installation([record(state="waiting_for_usage", resumed_at=None, outcome_at=None,
                                  submitted_at=None, recovery_turn_id=None,
                                  recovery_turn_status=None, last_error="usage_unavailable")]):
            report = reporter.build(LOGIN)
        levels = {name: entry["level"] for name, entry in report["capabilities"].items()}
        self.assertNotIn("VERIFIED", levels.values())
        self.assertIn(report["verdict"], ("CHECKED", "NONE"))

    def test_the_newest_history_generation_is_the_one_read(self):
        with Installation([record()]) as installation:
            for number in (2, 9, 11):
                (installation.codex / ("thread_history_%d.sqlite" % number)).write_bytes(b"")
            self.assertEqual(reporter.newest_history().name, "thread_history_11.sqlite")


class StateDatabaseTests(unittest.TestCase):
    """What the state database may be, and what the reporter says when it is something else."""

    def test_a_newer_schema_is_refused_rather_than_read_as_todays(self):
        with Installation([record()], user_version=4):
            with self.assertRaisesRegex(reporter.Refused, "newer Codex Auto Resume.*Update"):
                reporter.build(LOGIN)

    def test_an_older_or_unknown_schema_is_refused_with_the_version_it_needs(self):
        for version in (0, 2):
            with self.subTest(version):
                with Installation([record()], user_version=version):
                    with self.assertRaisesRegex(reporter.Refused, "v0.6.0 or newer"):
                        reporter.build(LOGIN)

    def test_a_missing_column_or_table_is_refused(self):
        without = tuple(name for name in COLUMNS if name != "outcome_at")
        for columns in (without, ()):
            with self.subTest(len(columns)):
                with Installation([record()], columns=columns):
                    with self.assertRaisesRegex(reporter.Refused, "missing: "):
                        reporter.build(LOGIN)

    def test_a_corrupt_database_is_refused_not_a_traceback(self):
        with Installation([record()]) as installation:
            (installation.home / "config" / "state.sqlite").write_bytes(b"this is not a database" * 100)
            with self.assertRaisesRegex(reporter.Refused, "could not be read"):
                reporter.build(LOGIN)
            code, _out, err = run_main("report", "--login", LOGIN, "--out",
                                       str(installation.root / "r.json"))
            self.assertEqual(code, 2)
            self.assertIn("could not be read", err)

    def test_a_gate_evaluation_of_the_wrong_shape_counts_no_gates(self):
        for gates in ("{not json", "[1, 2]", json.dumps({"usage": {"PASS": 1}})):
            with self.subTest(gates):
                with Installation([record(gate_eval=gates)]):
                    report = reporter.build(LOGIN)
                self.assertEqual(report["records"][0]["gates_passed"], 0)

    def test_a_home_whose_folder_names_hold_hash_and_percent_is_read_and_not_written(self):
        with Installation([record()], under="a#b%41") as installation:
            before = installation.snapshot()
            report = reporter.build(LOGIN)
            self.assertEqual(len(report["records"]), 1)
            self.assertIsNotNone(report["records"][0]["progress_items"], "the history was read too")
            self.assertEqual(installation.snapshot(), before, "no file appeared or changed")

    def test_status_on_a_fresh_install_says_what_it_can(self):
        with Installation(state=False):
            code, out, _err = run_main("status")
        self.assertEqual(code, 0)
        self.assertIn("none yet (no state database", out)
        self.assertIn("engine version : %s" % VERSION, out)

    def test_status_on_a_database_it_cannot_read_says_why_and_goes_on(self):
        with Installation([record()], user_version=9):
            code, out, _err = run_main("status")
        self.assertEqual(code, 0)
        self.assertIn("cannot be read", out)
        self.assertIn("local checks", out)


class ValidateTests(unittest.TestCase):
    """The project's own rules, applied before anything is written or sent."""

    def good(self):
        with Installation([record()]):
            return json.loads(reporter.encode(reporter.build(LOGIN)))

    MUTATIONS = {
        "a version that is not one": lambda r: r.update(codex_version="codex-cli latest"),
        "a capability outside the ten": lambda r: r["capabilities"].update(
            queue_withdraw={"confirmed": 0, "missed": 0, "last_confirmed": None, "level": "CHECKED"}),
        "a covered name outside the ten": lambda r: r["local_checks"]["covers"].append("queue_withdraw"),
        "an unexpected key": lambda r: r.update(extra="hello"),
        "a word the product does not write": lambda r: r["records"][0].update(state="my own words"),
        "a time that is not one": lambda r: r["records"][0].update(detected_at="yesterday"),
        "an outcome before its detection": lambda r: r["records"][0].update(outcome_at="2000-01-01T00:00:00Z"),
        "a login that is not one": lambda r: r["reporter"].update(github_login="not a login"),
        "a login Windows keeps for a device": lambda r: r["reporter"].update(github_login="nul"),
        "a version in another spelling": lambda r: r.update(codex_version="codex-cli 0.155.0-alpha.09.2"),
        "a free-text product version": lambda r: r["reporter"].update(product_version="0.6.9 on my laptop"),
        "a window set by hand": lambda r: r["attribution"].update(window=["a", "b"]),
        "more records than there are": lambda r: r["capabilities"]["engine_present"].update(confirmed=5),
    }

    def test_a_report_this_tool_writes_passes(self):
        self.assertEqual(reporter.validate(reporter.encode(self.good()))[1], [])

    def test_every_rule_refuses_what_it_should(self):
        for name, mutate in self.MUTATIONS.items():
            with self.subTest(name):
                report = self.good()
                mutate(report)
                self.assertNotEqual(reporter.validate(reporter.encode(report))[1], [])

    def test_the_size_and_record_limits(self):
        report = self.good()
        report["records"] = report["records"] * (reporter.MAX_RECORDS + 1)
        self.assertIn("records is not a list of at most 500", reporter.validate(reporter.encode(report))[1])
        self.assertEqual(reporter.validate(b" " * (reporter.MAX_BYTES + 1))[1], ["the file is larger than 1 MB"])
        self.assertEqual(reporter.validate(json.dumps({"edited": True}).encode())[1][0][:5], "keys:")

    @unittest.skipUnless(PRODUCT_READER.is_file(), "the product's checkout is not beside this one")
    def test_the_receiving_side_agrees_rule_for_rule(self):
        """The project's own reader, which judges the pull request and files what passes (before
        v1.2.0 this compared with the maintainer's tool, whose copy of it is gone)."""
        reader = load_product_reader()
        if not hasattr(reader, "canonical_version"):
            self.skipTest("the product checkout beside this one predates the rule on a version's spelling")
        for name, mutate in [("unchanged", lambda r: None)] + list(self.MUTATIONS.items()):
            with self.subTest(name):
                report = self.good()
                mutate(report)
                raw = reporter.encode(report)
                self.assertEqual(bool(reporter.validate(raw)[1]), bool(reader.inspect(raw, releases=None)[1]))


# ------------------------------------------------------------------------------------ submit
REPO = reporter.REPO
FORK = "%s/%s" % (LOGIN, REPO.split("/")[1])


class FakeGh:
    """gh, recorded: every call's arguments and environment, and the body of every upload.

    It answers as GitHub would for the state it is given, and fails the test on any call it
    does not know - so a new call to GitHub cannot slip in without a test saying so.
    """

    def __init__(self, exe, *, signed_in=True, login=LOGIN, door=True, filed=False, open_prs=(),
                 fork=False, branch=False, copying=0, answers=None):
        self.exe, self.signed_in, self.login = exe, signed_in, login
        self.door, self.filed, self.fork, self.branch = door, filed, fork, branch
        self.fork_name = "%s/%s" % (login, REPO.split("/")[1])     # the fork GitHub would make for that login
        # (url, head branch) for each open pull request of this login; a bare url is a report's.
        self.open_prs = [(pr, "compat-report/codex-cli-0.155.0") if isinstance(pr, str) else tuple(pr)
                         for pr in open_prs]
        self.copying = copying          # how many looks at a new fork's main find it not yet copied
        self.answers = dict(answers or {})
        self.calls, self.environments, self.uploads = [], [], []

    NOT_FOUND = (1, '{"message":"Not Found","status":"404"}', "gh: Not Found (HTTP 404)")
    EMPTY = (1, '{"message":"Git Repository is empty.","status":"409"}', "gh: Git Repository is empty. (HTTP 409)")

    @staticmethod
    def key(arguments):
        if arguments[:2] == ["auth", "status"]:
            return ("auth status",)
        if arguments[:2] in (["pr", "list"], ["pr", "create"]):
            return ("pr " + arguments[1],)
        assert arguments[0] == "api", arguments
        assert arguments[1:4] == ["--hostname", "github.com", "-X"], "every api call pins the host"
        return (arguments[4], arguments[5])

    def __call__(self, argv, **kwargs):
        argv = list(argv)
        self.calls.append(argv)
        self.environments.append(kwargs.get("env") or {})
        assert argv[0] == self.exe, "gh is started by its resolved path: %r" % argv[0]
        key = self.key(argv[1:])
        if key in self.answers:
            answer = self.answers[key]
            if isinstance(answer, BaseException):
                raise answer
            return subprocess.CompletedProcess(argv, *answer)
        return subprocess.CompletedProcess(argv, *self.answer(key, argv[1:]))

    def answer(self, key, arguments):
        path, branch = reporter.destination(VERSION, self.login)
        FORK = self.fork_name  # noqa: N806 - the routes read as GitHub's, for whichever login is signed in
        routes = {
            ("auth status",): (0, "", "") if self.signed_in else (1, "", "You are not logged into any GitHub hosts."),
            ("GET", "user"): (0, self.login, ""),
            ("GET", "repos/%s/contents/%s" % (REPO, reporter.COMMUNITY)): (0, "[]", "") if self.door else self.NOT_FOUND,
            ("GET", "repos/%s/contents/%s" % (REPO, path)): (0, "{}", "") if self.filed else self.NOT_FOUND,
            ("pr list",): (0, json.dumps([{"url": url, "headRefName": head} for url, head in self.open_prs]), ""),
            ("GET", "repos/" + FORK): (0, json.dumps({"full_name": FORK, "fork": True,
                                                      "parent": {"full_name": REPO}}), "") if self.fork else self.NOT_FOUND,
            ("GET", "repos/%s/git/ref/heads/%s" % (FORK, branch)): (0, "{}", "") if self.branch else self.NOT_FOUND,
            ("GET", "repos/%s/git/ref/heads/main" % REPO): (0, SHA, ""),
            ("GET", "repos/%s/git/ref/heads/main" % FORK): (self.EMPTY if self.copying > 0 else (0, SHA, ""))
                                                           if self.fork else self.NOT_FOUND,
            ("POST", "repos/%s/forks" % REPO): (0, FORK, ""),
            ("POST", "repos/%s/git/refs" % FORK): (0, "{}", ""),
            ("PATCH", "repos/%s/git/refs/heads/%s" % (FORK, branch)): (0, "{}", ""),
            ("PUT", "repos/%s/contents/%s" % (FORK, path)): (0, "{}", ""),
            ("pr create",): (0, "https://github.com/%s/pull/7" % REPO, ""),
        }
        if key not in routes:
            raise AssertionError("an unexpected call to GitHub: %r" % (arguments,))
        if key == ("POST", "repos/%s/forks" % REPO):
            self.fork = True
        if key == ("GET", "repos/%s/git/ref/heads/main" % FORK) and self.fork:
            self.copying -= 1
        if key[0] == "PUT":
            with open(arguments[arguments.index("--input") + 1], encoding="ascii") as handle:
                self.uploads.append(json.load(handle))
        return routes[key]

    def verbs(self):
        return [self.key(call[1:]) for call in self.calls]

    def writes(self):
        return [key for key in self.verbs() if key[0] in ("POST", "PUT", "PATCH", "DELETE", "pr create")]


class SubmitTests(unittest.TestCase):
    """What leaves the machine, and when."""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.installation = self.stack.enter_context(Installation([record()]))
        self.work = self.installation.root / "work"
        self.work.mkdir()
        self.bin = self.installation.root / "bin"
        self.bin.mkdir()
        self.exe = str(self.bin / "gh.exe")
        pathlib.Path(self.exe).write_bytes(b"not a real gh")
        self.stack.enter_context(contextlib.chdir(self.work))
        self.stack.enter_context(mock.patch.dict(os.environ, {"PATH": ".;;relative\\bin;" + str(self.bin),
                                                              "GH_HOST": "ghe.example.com"}))
        self.sleep = self.stack.enter_context(mock.patch.object(reporter.time, "sleep"))
        code, out, err = run_main("report", "--login", LOGIN)
        self.assertEqual(code, 0, err)
        self.file = self.work / "codex-cli-0.155.0-alpha.9.2.json"
        self.reviewed = self.file.read_bytes()

    def tearDown(self):
        self.stack.close()

    def submit(self, *argv, **fake):
        gh = FakeGh(self.exe, **fake)
        with mock.patch.object(reporter.subprocess, "run", gh):
            code, out, err = run_main("submit", *argv)
        return gh, code, out, err

    def uploaded(self, gh):
        self.assertEqual(len(gh.uploads), 1)
        return base64.b64decode(gh.uploads[0]["content"])

    def test_the_exact_calls_of_a_first_report_and_the_bytes_they_carry(self):
        gh, code, out, err = self.submit(str(self.file), "--yes")
        self.assertEqual(code, 0, err)
        path, branch = "docs/evidence/community/someone/codex-cli-0.155.0-alpha.9.2.json", \
            "compat-report/codex-cli-0.155.0-alpha.9.2"
        self.assertEqual(gh.verbs(), [
            ("auth status",),
            ("GET", "user"),
            ("GET", "repos/%s/contents/docs/evidence/community" % REPO),
            ("GET", "repos/%s/contents/%s" % (REPO, path)),
            ("pr list",),
            ("GET", "repos/" + FORK),
            ("GET", "repos/%s/git/ref/heads/main" % REPO),
            ("POST", "repos/%s/forks" % REPO),
            ("GET", "repos/%s/git/ref/heads/main" % FORK),
            ("POST", "repos/%s/git/refs" % FORK),
            ("PUT", "repos/%s/contents/%s" % (FORK, path)),
            ("pr create",),
        ])
        self.assertEqual(self.uploaded(gh), self.reviewed, "the bytes sent are the bytes read")
        self.assertEqual(self.file.read_bytes(), self.reviewed, "the file is not rewritten")
        self.assertEqual(gh.uploads[0]["branch"], branch)
        auth = gh.calls[0]
        self.assertEqual(auth[1:], ["auth", "status", "--hostname", "github.com"])
        refs = gh.calls[9]
        self.assertIn("ref=refs/heads/" + branch, refs)
        self.assertIn("sha=" + SHA, refs)
        listing = gh.calls[4]
        self.assertEqual(listing[listing.index("--repo") + 1], "github.com/" + REPO)
        self.assertNotIn("--head", listing, "any open report of this login counts, not only this one")
        self.assertEqual(listing[listing.index("--json") + 1], "url,headRefName")
        self.assertEqual(listing[listing.index("--author") + 1], LOGIN)
        opened = gh.calls[-1]
        self.assertEqual(opened[opened.index("--repo") + 1], "github.com/" + REPO)
        self.assertEqual(opened[opened.index("--base") + 1], "main")
        self.assertEqual(opened[opened.index("--head") + 1], "%s:%s" % (LOGIN, branch))
        self.assertIn("opened: https://github.com/%s/pull/7" % REPO, out)
        self.assertEqual(out.rstrip().splitlines()[-1], reporter.AFTER_SUBMIT)
        for environment in gh.environments:
            self.assertEqual(environment.get("NoDefaultCurrentDirectoryInExePath"), "1")
            self.assertNotIn("GH_HOST", environment)
        self.assertFalse(any(call[0] == "gh" for call in gh.calls))
        self.assertNotIn("sync", [word for call in gh.calls for word in call])

    def test_an_edited_file_that_still_passes_is_sent_as_edited(self):
        edited = json.loads(self.reviewed)
        edited["records"][0]["progress_items"] = None
        self.file.write_bytes(json.dumps(edited).encode("ascii"))
        reviewed = self.file.read_bytes()
        gh, code, _out, err = self.submit(str(self.file), "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.uploaded(gh), reviewed)
        self.assertEqual(self.file.read_bytes(), reviewed)

    def test_a_file_the_project_would_refuse_is_refused_before_any_call(self):
        self.file.write_bytes(b'{"edited": true}')
        gh, code, _out, err = self.submit(str(self.file), "--yes")
        self.assertEqual((code, gh.calls), (2, []))
        self.assertIn("nothing was sent", err)

    def test_nothing_is_written_without_yes(self):
        for argv, expected in (((str(self.file),), 2), ((str(self.file), "--dry-run"), 0)):
            with self.subTest(argv):
                gh, code, out, err = self.submit(*argv)
                self.assertEqual(code, expected, err)
                self.assertEqual(gh.writes(), [])
                self.assertIn("With --yes this writes to GitHub", out)
                self.assertIn("a fork of %s under your account" % REPO, out)
        self.assertEqual(self.file.read_bytes(), self.reviewed)

    def test_a_closed_door_sends_nothing_and_says_so_in_its_exit_code(self):
        gh, code, out, _err = self.submit(str(self.file), "--yes", door=False)
        self.assertEqual(code, reporter.EXIT_NOT_OPEN)
        self.assertEqual(gh.writes(), [])
        self.assertEqual(gh.verbs()[-1], ("GET", "repos/%s/contents/docs/evidence/community" % REPO))
        self.assertIn("not taking reports yet", out)

    def test_a_failure_is_not_mistaken_for_a_closed_door(self):
        key = ("GET", "repos/%s/contents/docs/evidence/community" % REPO)
        gh, code, _out, err = self.submit(str(self.file), "--yes",
                                          answers={key: (1, "", "gh: Server Error (HTTP 502)")})
        self.assertEqual(code, 2)
        self.assertIn("HTTP 502", err)
        self.assertEqual(gh.writes(), [])

    def test_a_wrong_login_is_refused_before_any_fork(self):
        gh, code, _out, err = self.submit(str(self.file), "--yes", login="somebody-else")
        self.assertEqual(code, 2)
        self.assertIn("signed in as somebody-else", err)
        self.assertEqual(gh.writes(), [])
        gh, code, _out, err = self.submit(str(self.file), "--yes", "--login", "other")
        self.assertEqual((code, gh.calls), (2, []))

    def test_a_file_filed_under_the_login_in_another_letter_case_says_how_github_spells_it(self):
        """Not "signed in as someone, so ... Someone cannot be sent": it is the same account, and the
        project takes the report only under someone (community_check.py compares the folder exactly)."""
        other = self.work / "typed-in-another-case.json"
        code, _out, err = run_main("report", "--login", "Someone", "--out", str(other))
        self.assertEqual(code, 0, err)
        gh, code, _out, err = self.submit(str(other), "--yes")
        self.assertEqual((code, gh.writes()), (2, []))
        self.assertIn("filed under Someone, but GitHub spells that login someone", err)
        self.assertIn("report --login someone --force", err)
        self.assertNotIn("cannot be sent from here", err)

    def test_gh_not_signed_in_is_a_clear_refusal(self):
        gh, code, _out, err = self.submit(str(self.file), "--yes", signed_in=False)
        self.assertEqual((code, len(gh.calls)), (2, 1))
        self.assertIn("gh auth login", err)

    def test_the_path_and_branch_are_canonical_whatever_the_file_is_called(self):
        other = self.work / "my report.json"
        other.write_bytes(self.reviewed)
        gh, code, out, err = self.submit(str(other), "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertIn("adding docs/evidence/community/someone/codex-cli-0.155.0-alpha.9.2.json", out)
        self.assertIn("someone:compat-report/codex-cli-0.155.0-alpha.9.2", out)
        gh, code, _out, err = self.submit(str(other), "--yes")
        self.assertEqual(code, 0, err)
        put = [call for call in gh.calls if call[5:6] == ["PUT"]][0]
        self.assertEqual(put[6], "repos/%s/contents/docs/evidence/community/someone/"
                                 "codex-cli-0.155.0-alpha.9.2.json" % FORK)
        self.assertEqual(self.uploaded(gh), self.reviewed)

    def test_a_report_already_filed_or_open_is_refused_before_any_write(self):
        for fake, said in (({"filed": True}, "already filed"),
                           ({"open_prs": ["https://github.com/%s/pull/3" % REPO]}, "already open")):
            with self.subTest(said):
                gh, code, _out, err = self.submit(str(self.file), "--yes", **fake)
                self.assertEqual(code, 2)
                self.assertIn(said, err)
                self.assertEqual(gh.writes(), [])

    def test_one_report_at_a_time_whatever_its_version_and_other_pull_requests_do_not_count(self):
        """The project files one open report per account; a second is closed there, so it is not sent."""
        other = ("https://github.com/%s/pull/4" % REPO, "compat-report/codex-cli-0.153.4")
        gh, code, _out, err = self.submit(str(self.file), "--yes", open_prs=[other])
        self.assertEqual(code, 2)
        self.assertIn("one report per account at a time", err)
        self.assertEqual(gh.writes(), [])
        code_change = ("https://github.com/%s/pull/5" % REPO, "fix-a-typo")
        gh, code, _out, err = self.submit(str(self.file), "--yes", open_prs=[code_change])
        self.assertEqual(code, 0, err)

    def test_this_reports_own_open_pull_request_is_closed_first_and_the_refusal_says_so(self):
        """The project's comment on a refused report says to close it, then submit again; submit says
        the same, and writes nothing while it is open."""
        own = ("https://github.com/%s/pull/7" % REPO, "compat-report/codex-cli-0.155.0-alpha.9.2")
        gh, code, _out, err = self.submit(str(self.file), "--yes", fork=True, branch=True, open_prs=[own])
        self.assertEqual(code, 2)
        self.assertIn("Your pull request for this report is still open: %s. Close it on GitHub first" % own[0], err)
        self.assertEqual(gh.writes(), [])

    def test_a_left_over_branch_is_reset_to_main_rather_than_reused(self):
        gh, code, out, err = self.submit(str(self.file), "--yes", fork=True, branch=True)
        self.assertEqual(code, 0, err)
        branch = "compat-report/codex-cli-0.155.0-alpha.9.2"
        self.assertEqual(gh.writes(), [("PATCH", "repos/%s/git/refs/heads/%s" % (FORK, branch)),
                                       ("PUT", "repos/%s/contents/docs/evidence/community/someone/"
                                               "codex-cli-0.155.0-alpha.9.2.json" % FORK),
                                       ("pr create",)])
        patch = [call for call in gh.calls if "PATCH" in call][0]
        self.assertIn("force=true", patch)
        self.assertEqual(self.uploaded(gh), self.reviewed)

    def test_a_failed_branch_stops_before_the_upload(self):
        key = ("POST", "repos/%s/git/refs" % FORK)
        gh, code, _out, err = self.submit(str(self.file), "--yes",
                                          answers={key: (1, "", "gh: Reference update failed (HTTP 422)")})
        self.assertEqual(code, 2)
        self.assertIn("HTTP 422", err)
        self.assertNotIn("PUT", [key[0] for key in gh.verbs()])
        self.assertIn("Already written to GitHub by this run: the fork %s." % FORK, err)
        self.assertIn("Running submit again is safe", err)

    def test_a_new_fork_is_given_time_to_be_copied_before_its_branch_is_made(self):
        gh, code, _out, err = self.submit(str(self.file), "--yes", copying=3)
        self.assertEqual(code, 0, err)
        looks = [n for n, key in enumerate(gh.verbs()) if key == ("GET", "repos/%s/git/ref/heads/main" % FORK)]
        self.assertEqual(len(looks), 4)
        self.assertEqual(gh.verbs()[looks[-1] + 1], ("POST", "repos/%s/git/refs" % FORK))
        self.assertEqual(self.sleep.call_count, 3)

    def test_a_new_fork_never_copied_is_refused_saying_what_was_written(self):
        gh, code, _out, err = self.submit(str(self.file), "--yes", copying=10 ** 6)
        self.assertEqual(code, 2)
        self.assertEqual(self.sleep.call_count, reporter.FORK_WAITS)
        self.assertEqual(gh.writes(), [("POST", "repos/%s/forks" % REPO)])
        self.assertIn("has not finished copying", err)
        self.assertIn("Already written to GitHub by this run: the fork %s." % FORK, err)

    def test_a_failed_pull_request_lists_what_was_written_and_a_second_run_finishes_it(self):
        gh, code, _out, err = self.submit(str(self.file), "--yes",
                                          answers={("pr create",): (1, "", "gh: Validation Failed (HTTP 422)")})
        self.assertEqual(code, 2)
        path, branch = reporter.destination(VERSION, LOGIN)
        self.assertIn("HTTP 422", err)
        self.assertIn("Already written to GitHub by this run: the fork %s; the branch %s; the file %s on "
                      "that branch." % (FORK, branch, path), err)
        gh, code, out, err = self.submit(str(self.file), "--yes", fork=True, branch=True)
        self.assertEqual(code, 0, err)
        self.assertEqual([key[0] for key in gh.writes()], ["PATCH", "PUT", "pr create"])
        self.assertEqual(self.uploaded(gh), self.reviewed)

    def test_a_refusal_before_any_write_does_not_speak_of_writes(self):
        for fake in ({"filed": True}, {"login": "somebody-else"}, {}):
            with self.subTest(fake):
                _gh, code, _out, err = self.submit(str(self.file), *(("--yes",) if fake else ()), **fake)
                self.assertEqual(code, 2)
                self.assertNotIn("Already written", err)

    def test_gh_that_cannot_be_started_is_a_refusal(self):
        gh, code, _out, err = self.submit(str(self.file), "--yes",
                                          answers={("auth status",): OSError(206, "The filename or extension is too long")})
        self.assertEqual(code, 2)
        self.assertIn("could not be started", err)

    def test_no_gh_on_path_is_a_clear_refusal_and_nothing_starts(self):
        with mock.patch.dict(os.environ, {"PATH": ".;relative"}):
            gh, code, _out, err = self.submit(str(self.file), "--yes")
        self.assertEqual((code, gh.calls), (2, []))
        self.assertIn("https://cli.github.com/", err)

    def test_a_planted_gh_in_the_current_folder_is_never_started(self):
        (self.work / "gh.exe").write_bytes(b"planted")
        self.assertEqual(reporter.find_gh(".;;relative\\bin;" + str(self.bin)), self.exe)
        self.assertIsNone(reporter.find_gh(".;" + str(self.work.relative_to(self.installation.root))))
        # The current folder named absolutely, or spelled another way, is still the current folder.
        with contextlib.chdir(self.work):
            for spelling in (str(self.work), str(self.work / "."), str(self.work / ".." / self.work.name)):
                with self.subTest(spelling=spelling):
                    self.assertIsNone(reporter.find_gh(spelling))
                    self.assertEqual(reporter.find_gh(spelling + ";" + str(self.bin)), self.exe)
        gh, code, _out, err = self.submit(str(self.file), "--dry-run")
        self.assertEqual(code, 0, err)
        self.assertEqual({call[0] for call in gh.calls}, {self.exe})

    def test_every_argument_stays_short_with_the_largest_report_allowed(self):
        rows = [record(detected_at=NOW - 7000 + n, resumed_at=NOW - 6900 + n,
                       outcome_at=NOW - 6800 + n) for n in range(reporter.MAX_RECORDS)]
        with Installation(rows) as installation, contextlib.chdir(installation.root):
            code, _out, err = run_main("report", "--login", LOGIN)
            self.assertEqual(code, 0, err)
            big = installation.root / "codex-cli-0.155.0-alpha.9.2.json"
            reviewed = big.read_bytes()
            self.assertEqual(len(json.loads(reviewed)["records"]), reporter.MAX_RECORDS)
            gh, code, _out, err = self.submit(str(big), "--yes")
        self.assertEqual(code, 0, err)
        self.assertEqual(self.uploaded(gh), reviewed)
        longest = max(len(subprocess.list2cmdline(call)) for call in gh.calls)
        self.assertLess(longest, 32_000)

    def test_the_file_named_by_its_sha256_or_found_alone(self):
        digest = hashlib.sha256(self.reviewed).hexdigest()
        gh, code, _out, err = self.submit("--dry-run", "--sha256", digest)
        self.assertEqual(code, 0, err)
        gh, code, _out, err = self.submit("--dry-run", "--sha256", "0" * 64)
        self.assertEqual((code, gh.calls), (2, []))
        self.assertIn("has changed", err)
        (self.work / "codex-cli-0.1.0.json").write_bytes(self.reviewed)
        gh, code, _out, err = self.submit("--dry-run")
        self.assertEqual((code, gh.calls), (2, []))
        self.assertIn("This folder has 2", err)

    def test_the_summary_says_what_is_sent_before_anything_is(self):
        gh, code, out, _err = self.submit(str(self.file), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn("bytes       : %d, SHA-256 %s" % (len(self.reviewed), hashlib.sha256(self.reviewed).hexdigest()),
                      out)
        self.assertIn("gh          : %s, host github.com, signed in as someone" % self.exe, out)
        self.assertIn("1 records (", out)
        self.assertIn("when each capability was last confirmed", out)

    def test_the_summary_lists_the_times_the_readme_says_are_published_word_for_word(self):
        _gh, code, out, _err = self.submit(str(self.file), "--dry-run")
        self.assertEqual(code, 0)
        self.assertIn(reporter.PUBLISHED_TIMES, out)
        readme = " ".join((HERE.parent / "README.md").read_text(encoding="utf-8").split())
        self.assertIn("exactly as recorded: " + reporter.PUBLISHED_TIMES + ".", readme)


def scripted(answers, asked):
    """input(), answered from a list: a string is typed, a callable is run (to change something while
    the person reads) and its answer typed, and the end of the list is the end of the input."""
    answers = list(answers)

    def answer(prompt):
        asked.append(prompt)
        if not answers:
            raise EOFError
        given = answers.pop(0)
        return given() if callable(given) else given
    return answer


# The guide's questions in order, on a machine where gh is signed in as the login.
LOGIN_Q, OPEN_Q, READ_Q, SEND_Q = "GitHub login", "Open it in Notepad?", "Press Enter", "Type send"


class GuideTests(unittest.TestCase):
    """The guide sends nothing unless `send` is typed, and then exactly the file the person was shown."""

    def setUp(self):
        self.stack = contextlib.ExitStack()
        self.installation = self.stack.enter_context(Installation([record()]))
        root = self.installation.root
        self.work, self.bin, self.nowhere = root / "work", root / "bin", root / "no-gh"
        for folder in (self.work, self.bin, self.nowhere):
            folder.mkdir()
        self.exe = str(self.bin / "gh.exe")
        pathlib.Path(self.exe).write_bytes(b"not a real gh")
        self.stack.enter_context(contextlib.chdir(self.work))
        self.stack.enter_context(mock.patch.object(reporter.time, "sleep"))
        self.file = pathlib.Path.cwd() / "codex-cli-0.155.0-alpha.9.2.json"

    def tearDown(self):
        self.stack.close()

    def guide(self, *answers, gh=True, **fake):
        """(exit code, what was printed, the fake gh, the questions asked, the windows opened)."""
        asked, shown = [], []
        fake_gh = self.gh = FakeGh(self.exe, **fake)      # an answer may change what GitHub will say
        with mock.patch.object(reporter, "input", scripted(answers, asked), create=True), \
                mock.patch.object(reporter.subprocess, "run", fake_gh), \
                mock.patch.object(reporter, "show", lambda program, argument: shown.append((program, argument)) or True), \
                mock.patch.dict(os.environ, {"PATH": str(self.bin if gh else self.nowhere)}):
            code, out, err = run_main("guide")
        return code, out + err, fake_gh, asked, shown

    def questions(self, asked):
        return [next((word for word in (LOGIN_Q, OPEN_Q, READ_Q, SEND_Q, "Write a new one", "browser")
                      if word in prompt), prompt) for prompt in asked]

    def test_send_sends_the_bytes_the_person_was_shown_and_nothing_else_sends(self):
        code, said, gh, asked, shown = self.guide("", "", "", "send")
        self.assertEqual(code, 0, said)
        self.assertEqual(self.questions(asked), [LOGIN_Q, OPEN_Q, READ_Q, SEND_Q])
        self.assertEqual(shown, [(reporter.NOTEPAD, str(self.file))])
        self.assertEqual(len(gh.uploads), 1)
        self.assertEqual(base64.b64decode(gh.uploads[0]["content"]), self.file.read_bytes())
        self.assertEqual([key[0] for key in gh.writes()], ["POST", "POST", "PUT", "pr create"])
        self.assertIn("opened: https://github.com/%s/pull/7" % REPO, said)
        self.assertIn(str(self.file), said)
        self.assertIn("Sending writes to GitHub, as someone:", said)

    def test_anything_but_send_sends_nothing(self):
        for answer in ("", "yes", "y", "send it", "sned", "--yes", None):
            with self.subTest(answer):
                self.file.unlink(missing_ok=True)
                answers = ("", "", "") + (() if answer is None else (answer,))
                code, said, gh, asked, _shown = self.guide(*answers)
                self.assertEqual(code, 0, said)
                self.assertEqual(self.questions(asked)[-1], SEND_Q)
                self.assertEqual(gh.writes(), [])
                self.assertIn("Nothing was sent. The report stays here", said)
                self.assertTrue(self.file.is_file())
        self.file.unlink()
        code, said, gh, _asked, _shown = self.guide("", "", "", " SEND ")
        self.assertEqual((code, len(gh.uploads)), (0, 1), "the word, in any case and with spaces around it")

    def test_every_question_has_a_default_that_sends_nothing(self):
        """Stopped after any number of empty answers - the end of the input, and Enter at every question -
        nothing reaches GitHub, with gh and without it."""
        for gh in (True, False):
            for given in range(6):
                with self.subTest(gh=gh, answers=given):
                    self.file.unlink(missing_ok=True)
                    code, said, fake, asked, shown = self.guide(*[""] * given, gh=gh)
                    self.assertEqual(code, 0, said)
                    self.assertEqual(fake.writes(), [])
                    self.assertNotIn(reporter.BROWSER, [program for program, _argument in shown])
                    self.assertIn("Nothing was", said)

    def test_a_file_edited_while_it_is_read_is_what_is_sent(self):
        def edit():
            edited = json.loads(self.file.read_bytes())
            edited["records"][0]["progress_items"] = None
            self.file.write_bytes(reporter.encode(edited))
            return ""
        code, said, gh, _asked, _shown = self.guide("", "", edit, "send")
        self.assertEqual(code, 0, said)
        self.assertIn("The file has changed since it was written", said)
        self.assertEqual(base64.b64decode(gh.uploads[0]["content"]), self.file.read_bytes())
        self.assertIsNone(json.loads(base64.b64decode(gh.uploads[0]["content"]))["records"][0]["progress_items"])

    def test_a_file_changed_after_the_question_is_refused_not_sent(self):
        def change_then_send():
            self.file.write_bytes(self.file.read_bytes().replace(b'"verdict": "PASS"', b'"verdict": "NONE"'))
            return "send"
        code, said, gh, _asked, _shown = self.guide("", "", "", change_then_send)
        self.assertEqual(code, 2)
        self.assertIn("has changed: its SHA-256 is", said)
        self.assertEqual(gh.writes(), [])
        self.assertIn("Nothing was sent", said)

    def test_a_file_the_project_would_refuse_is_never_offered_to_send(self):
        def spoil():
            self.file.write_bytes(b'{"edited": true}')
            return ""
        code, said, gh, asked, _shown = self.guide("", "", spoil)
        self.assertEqual(code, 2)
        self.assertNotIn(SEND_Q, self.questions(asked))
        self.assertEqual(gh.calls[2:], [], "after the login, not one more call")

    def test_without_gh_the_file_is_written_and_the_web_way_is_said_and_nothing_sent(self):
        code, said, gh, asked, shown = self.guide("someone", "n", gh=False)
        self.assertEqual(code, 0, said)
        self.assertEqual(gh.calls, [])
        self.assertEqual(self.questions(asked), [LOGIN_Q, OPEN_Q, "browser"])
        self.assertEqual(shown, [], "the browser is opened only on a yes")
        self.assertTrue(self.file.is_file())
        path, branch = reporter.destination(VERSION, "someone")
        for step in ("1. Open https://github.com/%s and choose Fork\n" % REPO, "\n         %s\n" % branch,
                     "\n         %s\n" % path, "Contribute > Open pull request",
                     "One report pull request of yours may be open at a time"):
            self.assertIn(step, said)
        self.assertIn("is not installed here", said)
        self.file.unlink()
        code, said, gh, asked, shown = self.guide("someone", "n", "y", gh=False)
        self.assertEqual(shown, [(reporter.BROWSER, "https://github.com/" + REPO)])

    def test_gh_not_signed_in_or_signed_in_as_another_goes_the_web_way(self):
        code, said, gh, asked, _shown = self.guide("someone", "n", signed_in=False)
        self.assertEqual((code, gh.writes()), (0, []))
        self.assertEqual(asked[0], "  GitHub login: ", "no login is offered when gh has none")
        self.assertIn("not signed in to github.com here", said)
        self.assertIn("gh auth login --hostname github.com", said)
        self.file.unlink()
        code, said, gh, asked, _shown = self.guide("someone", "n", login="somebody-else")
        self.assertEqual((code, gh.writes()), (0, []))
        self.assertEqual(asked[0], "  GitHub login [somebody-else]: ")
        self.assertIn("signed in here as somebody-else, not someone", said)

    def test_a_login_typed_in_another_letter_case_is_filed_as_github_spells_it(self):
        """GitHub takes Someone for someone, but the project files a report only under the pull request's
        author as GitHub spells it: the guide takes gh's spelling, and sends from here."""
        code, said, gh, asked, _shown = self.guide("Someone", "", "", "send")
        self.assertEqual(code, 0, said)
        self.assertIn("GitHub spells that login someone", said)
        self.assertEqual(json.loads(self.file.read_bytes())["reporter"]["github_login"], "someone")
        self.assertEqual(self.questions(asked), [LOGIN_Q, OPEN_Q, READ_Q, SEND_Q])
        self.assertEqual(base64.b64decode(gh.uploads[0]["content"]), self.file.read_bytes())
        self.assertNotIn("Sign it in as", said)

    def test_gh_signed_in_after_the_login_as_the_same_account_is_not_sent_the_web_way(self):
        """The web steps would name a folder the project refuses, and "sign it in" would change nothing."""
        def sign_in():
            self.gh.signed_in = True
            return "n"
        code, said, gh, _asked, _shown = self.guide("Someone", sign_in, signed_in=False)
        self.assertEqual((code, gh.writes()), (2, []))
        self.assertIn("filed under Someone, but GitHub spells that login someone", said)
        self.assertNotIn("To send it on the web", said)
        self.assertIn("Nothing was sent. The report stays here", said)

    def test_the_login_is_held_to_the_same_rules_and_asked_again(self):
        code, said, _gh, asked, _shown = self.guide("not a login", "nul", gh=False)
        self.assertEqual(code, 0)
        self.assertIn("That is not a GitHub login", said)
        self.assertIn("Windows keeps that name for a device", said)
        self.assertEqual(len(asked), 3)
        self.assertIn("Nothing was written, and nothing was sent.", said)
        self.assertFalse(self.file.exists())
        code, said, _gh, asked, _shown = self.guide("a b", "c d", "e f", gh=False)
        self.assertEqual(code, 2)
        self.assertFalse(self.file.exists())

    def test_a_byte_order_mark_is_never_part_of_an_answer(self):
        """Windows PowerShell puts one before the text it pipes into a program (Report.cmd, 2026-09-27)."""
        code, said, _gh, _asked, _shown = self.guide("\ufeffsomeone", "\ufeffn", gh=False)
        self.assertEqual(code, 0, said)
        self.assertEqual(json.loads(self.file.read_bytes())["reporter"]["github_login"], "someone")

    def test_a_file_already_there_is_kept_unless_the_person_says_to_write_over_it(self):
        report, raw, _notes = reporter.make_report(LOGIN)
        kept = json.loads(raw)
        kept["records"][0]["progress_items"] = None
        self.file.write_bytes(reporter.encode(kept))
        before = self.file.read_bytes()
        code, said, gh, asked, _shown = self.guide("", "", "n", "send")
        self.assertEqual(code, 0, said)
        self.assertEqual(self.questions(asked), [LOGIN_Q, "Write a new one", OPEN_Q, SEND_Q])
        self.assertEqual(self.file.read_bytes(), before)
        self.assertEqual(base64.b64decode(gh.uploads[0]["content"]), before, "the kept file is what is sent")
        code, said, gh, asked, _shown = self.guide("", "y", "n", "")
        self.assertNotEqual(self.file.read_bytes(), before)
        self.assertEqual(gh.writes(), [])

    def test_a_file_there_filed_under_another_login_is_not_taken_for_this_one(self):
        other = json.loads(reporter.make_report("somebody-else")[1])
        self.file.write_bytes(reporter.encode(other))
        code, said, gh, _asked, _shown = self.guide("", "", "n")
        self.assertEqual(code, 2)
        self.assertIn("is filed under somebody-else, not someone", said)
        self.assertEqual(gh.writes(), [])

    def test_a_machine_with_nothing_to_report_stops_before_asking_anything(self):
        for installation in (Installation(state=False), Installation([], compat={}, log_lines=[])):
            with self.subTest(installation), installation:
                code, said, gh, asked, _shown = self.guide("", "", "", "send")
                self.assertEqual((code, asked, gh.calls), (2, [], []))
                self.assertIn("Nothing was written, and nothing was sent.", said)

    def test_a_closed_door_or_a_refusal_sends_nothing_and_keeps_the_file(self):
        code, said, gh, asked, _shown = self.guide("", "", "", "send", door=False)
        self.assertEqual((code, gh.writes()), (reporter.EXIT_NOT_OPEN, []))
        self.assertNotIn(SEND_Q, self.questions(asked))
        self.assertIn("not taking reports yet", said)
        self.file.unlink()
        code, said, gh, asked, _shown = self.guide("", "", "", "send", filed=True)
        self.assertEqual((code, gh.writes()), (2, []))
        self.assertIn("already filed", said)
        self.assertIn("Nothing was sent. The report stays here", said)

    def test_the_readmes_say_that_a_refused_guide_keeps_what_it_wrote(self):
        """Exit code 2 from the guide can come after it wrote the report, and after its own send wrote to
        GitHub: neither README may say that a refusal wrote nothing, outside submit --yes."""
        code, _said, _gh, _asked, _shown = self.guide("", "", "", "send", filed=True)
        self.assertEqual(code, 2)
        self.assertTrue(self.file.is_file())
        for name in ("README.md", "README.ko.md"):
            with self.subTest(name):
                rows = [line for line in (HERE.parent / name).read_text(encoding="utf-8").splitlines()
                        if line.startswith("| 2 |")]
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0].count("`guide`"), 2, "the file it keeps, and its send after `send`")
                self.assertNotIn("Nothing was written or sent - except under `submit --yes`", rows[0])

    def test_a_refusal_after_writes_does_not_say_nothing_was_sent(self):
        code, said, gh, _asked, _shown = self.guide("", "", "", "send",
                                                    answers={("pr create",): (1, "", "gh: Validation Failed (HTTP 422)")})
        self.assertEqual(code, 2)
        self.assertIn("Already written to GitHub by this run", said)
        self.assertNotIn("Nothing was sent", said)

    def test_what_sending_writes_is_what_was_listed_when_the_person_was_asked(self):
        """A fork that appears between the question and the send changes what is written: ask again."""
        def fork_appears():
            self.gh.fork = True
            return "send"
        code, said, gh, _asked, _shown = self.guide("", "", "", fork_appears)
        self.assertEqual(code, 2)
        self.assertIn("changed while you were asked", said)
        self.assertEqual(gh.writes(), [])

    @unittest.skipUnless(PRODUCT_READER.is_file(), "the product's checkout is not beside this one")
    def test_the_web_steps_name_the_path_and_branch_the_project_takes(self):
        spec = importlib.util.spec_from_file_location("community_check_for_tests",
                                                      PRODUCT / "build" / "community_check.py")
        check = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(check)
        _code, said, _gh, _asked, _shown = self.guide("someone", "n", gh=False)
        path, branch = reporter.destination(VERSION, "someone")
        self.assertIn("\n         %s\n" % path, said)
        self.assertEqual(check.REPORT_PATH.fullmatch(path).group(1), "someone")
        self.assertTrue(branch.startswith(check.BRANCH_PREFIX))


class ReadOnlyTests(unittest.TestCase):
    def test_status_report_and_a_dry_run_change_nothing_they_read(self):
        with Installation([record()]) as installation:
            (installation.home / "logs" / "auto-resume.log.2").write_text(
                engine_line(NOW - 9000, VERSION, reporter.ENGINE_LOG_WORDS["verified"]) + "\n", encoding="utf-8")
            work = installation.root / "work"
            work.mkdir()
            bin_ = installation.root / "bin"
            bin_.mkdir()
            exe = bin_ / "gh.exe"
            exe.write_bytes(b"not a real gh")
            before = installation.snapshot()
            with contextlib.chdir(work), mock.patch.dict(os.environ, {"PATH": str(bin_)}):
                self.assertEqual(run_main("status")[0], 0)
                self.assertEqual(run_main("report", "--login", LOGIN)[0], 0)
                with mock.patch.object(reporter.subprocess, "run", FakeGh(str(exe))):
                    self.assertEqual(run_main("submit", "--dry-run")[0], 0)
            self.assertEqual(installation.snapshot(), before)


class NoConsoleWindowTests(unittest.TestCase):
    """Nothing the reporter starts may put a console window on the screen - from a terminal, or from a
    program with no console of its own (pythonw, or a window that runs this code), where a console
    program started plainly opens a window of its own and hands it to everything it starts.

    Held here by reading the source, since no test here starts a real process (setUpModule). The
    mechanism itself - a console program given CREATE_NO_WINDOW under pythonw, and git started by it,
    show nothing - was measured on Windows 11 on 2026-09-26, and is held by codex-compat-admin's
    NoConsoleWindowTests, which runs the real chain."""

    def calls(self):
        tree = ast.parse(pathlib.Path(reporter.__file__).read_text(encoding="utf-8"))
        return [node for node in ast.walk(tree) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and node.func.attr in ("run", "Popen", "call",
                                                                                  "check_call", "check_output")
                and getattr(node.func.value, "id", None) == "subprocess"]

    def tree(self):
        return ast.parse(pathlib.Path(reporter.__file__).read_text(encoding="utf-8"))

    def shown(self):
        """The starts inside show(), the one function that opens a window the person asked for."""
        function = [node for node in ast.walk(self.tree()) if isinstance(node, ast.FunctionDef) and node.name == "show"]
        self.assertEqual(len(function), 1)
        return [node for node in ast.walk(function[0]) if isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute) and getattr(node.func.value, "id", None) == "subprocess"]

    def test_every_process_it_starts_is_given_a_hidden_console(self):
        calls = self.calls()
        self.assertTrue(calls)
        windows = [ast.unparse(call) for call in self.shown()]
        for call in calls:
            if ast.unparse(call) in windows:
                continue
            flags = [keyword.value for keyword in call.keywords if keyword.arg == "creationflags"]
            self.assertEqual(len(flags), 1, ast.unparse(call))
            self.assertIn("CREATE_NO_WINDOW", ast.unparse(flags[0]))

    def test_the_one_start_without_it_is_a_gui_program_the_person_asked_for_by_its_full_path(self):
        """Notepad on the report, and File Explorer handed the project's address, which opens the default
        browser: GUI programs, for which Windows makes no console, named by their path in the Windows folder."""
        (start,) = self.shown()
        self.assertEqual(ast.unparse(start.func), "subprocess.Popen")
        self.assertEqual(ast.unparse(start.args[0]), "[str(program), argument]")
        self.assertNotIn("shell", [keyword.arg for keyword in start.keywords])
        callers = [node for node in ast.walk(self.tree()) if isinstance(node, ast.Call)
                   and isinstance(node.func, ast.Name) and node.func.id == "show"]
        self.assertEqual(sorted({ast.unparse(call.args[0]) for call in callers}), ["BROWSER", "NOTEPAD"])
        windows = reporter._windows_folder()
        self.assertEqual((reporter.NOTEPAD, reporter.BROWSER),
                         (windows / "System32" / "notepad.exe", windows / "explorer.exe"))
        self.assertTrue(reporter.NOTEPAD.is_absolute() and reporter.BROWSER.is_absolute())

    def test_the_windows_folder_is_a_full_path_whatever_systemroot_says(self):
        for value, expected in (("D:\\Windows", "D:\\Windows"), ("", "C:\\Windows"), ("Windows", "C:\\Windows"),
                                ("\\Windows", "C:\\Windows")):
            with self.subTest(value), mock.patch.dict(os.environ, {"SystemRoot": value}):
                self.assertEqual(str(reporter._windows_folder()), expected)

    def test_it_starts_no_python_child(self):
        """A Python child would be started with sys.executable, and under pythonw that has no console to
        hand down to what it starts in turn."""
        self.assertEqual([ast.unparse(call) for call in self.calls() if "executable" in ast.unparse(call)], [])


class CliTests(unittest.TestCase):
    def test_version_and_help(self):
        self.assertEqual(run_main("--version")[0], 0)
        code, out, _err = run_main("--help")
        self.assertEqual(code, 0)
        self.assertIn("Exit codes", out)

    def test_a_refusal_is_exit_code_2_with_the_reason_on_stderr(self):
        with tempfile.TemporaryDirectory() as empty:
            with mock.patch.object(reporter, "PRODUCT", pathlib.Path(empty)):
                code, out, err = run_main("status")
        self.assertEqual((code, out), (2, ""))
        self.assertIn("does not look installed", err)

    def test_a_version_argument_that_is_not_one_is_a_usage_error(self):
        with Installation([record()]) as installation, contextlib.chdir(installation.root):
            code, _out, err = run_main("report", "--login", LOGIN, "--codex-version", "latest")
            self.assertEqual(code, 2)
            self.assertIn("is not a Codex version", err)
            self.assertFalse(list(installation.root.glob("*.json")))

    def test_report_prints_what_it_wrote_and_what_it_left_out(self):
        with Installation([record(), record(history_hidden_at=NOW)]) as installation, \
                contextlib.chdir(installation.root):
            code, out, _err = run_main("report", "--login", LOGIN, "--version", "0.155.0-alpha.9.2")
            self.assertEqual(code, 0)
            written = (installation.root / "codex-cli-0.155.0-alpha.9.2.json").read_bytes()
        self.assertIn("records    : 1,", out)
        self.assertIn("left out   : 1 hidden with Clear history", out)
        self.assertIn("SHA-256    : %s" % hashlib.sha256(written).hexdigest(), out)

    def test_report_never_writes_over_a_file_without_force(self):
        with Installation([record()]) as installation, contextlib.chdir(installation.root):
            target = installation.root / "codex-cli-0.155.0-alpha.9.2.json"
            target.write_bytes(b"the file I read")
            code, _out, err = run_main("report", "--login", LOGIN)
            self.assertEqual(code, 2)
            self.assertIn("--force", err)
            self.assertEqual(target.read_bytes(), b"the file I read")
            self.assertEqual(run_main("report", "--login", LOGIN, "--force")[0], 0)
            self.assertNotEqual(target.read_bytes(), b"the file I read")

    def test_report_into_a_folder_that_does_not_exist_is_refused(self):
        with Installation([record()]) as installation:
            code, _out, err = run_main("report", "--login", LOGIN, "--out",
                                       str(installation.root / "nope" / "r.json"))
        self.assertEqual(code, 2)
        self.assertIn("does not exist", err)


def setUpModule():
    # No test may start a real process: a test that needs gh installs FakeGh over this.
    # platform.version() may start `ver` once on some Pythons; it is asked first, and cached.
    global _no_processes
    import platform
    platform.version()
    _no_processes = [mock.patch.object(subprocess, name, side_effect=AssertionError("a real process"))
                     for name in ("run", "Popen")]
    for patch in _no_processes:
        patch.start()


def tearDownModule():
    for patch in _no_processes:
        patch.stop()


if __name__ == "__main__":
    unittest.main()
