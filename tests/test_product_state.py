"""The state database as Codex Auto Resume's own code writes it, read by the reporter.

The other tests build the product's state by hand, in the columns the reporter reads. These have the
product make it, from its own tags: schema 3 by v0.6.10's store, schema 4 by v0.6.11's - fresh, and
migrated from v0.6.10's - and schema 5, with the advanced edition's file of version 4, by v0.6.15-beta's (its
branch until that tag is made) and, with the file of version 5, by v0.6.16-beta.3's, and with the file of version 7
(6 is its step on the way), by v0.6.16-beta.4's - each fresh, and the older file brought to the newer version by the
product's own opening of it - with every record registered and claimed by that store and then carried to
where it ends in the store's own columns, as the engine's watch would carry it; and, at v0.6.11, the
advanced edition's own claim ledger paying for the sends its goal continuation carries, and pruning
those units 90 days on, as its watcher would. The reporter
then reads each of them as it reads an installation, and what it counts is what the product's own
receiving side counts (build/community_report.py).

Skipped where the product's repository, with its tags, is not beside this checkout - the public CI
among them. `git archive` takes each tag's src/codex_auto_resume (and advanced/src) into a temporary
folder, and a child `python -I` runs it from there under homes of its own, with no window. Nothing
here reads this machine's homes, writes anywhere but temporary folders, or reaches a network.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
import json
import os
import pathlib
import shutil
import sqlite3
import subprocess
import sys
import tarfile
import tempfile
import time
import unittest
import uuid
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
if str(HERE.parent) not in sys.path:
    sys.path.insert(0, str(HERE.parent))

_SANDBOX = pathlib.Path(tempfile.gettempdir()) / "codex-compat-reporter-tests-nowhere"
os.environ.setdefault("CODEX_AUTO_RESUME_HOME", str(_SANDBOX / "product"))
os.environ.setdefault("CODEX_HOME", str(_SANDBOX / "codex"))

import codex_compat_report as reporter  # noqa: E402

# The product's repository, when this checkout sits beside it (the maintainer's machine, or CAR_CHECKOUT).
PRODUCT = pathlib.Path(os.environ.get("CAR_CHECKOUT") or HERE.parent.parent / "codex-auto-resume")
GIT = shutil.which("git")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
SCHEMA_3, SCHEMA_4 = "v0.6.10", "v0.6.11"        # the last release of each schema's first line
# Schema 5's first release, or, until its tag is made, the branch it is built on.
SCHEMA_5_REFS = ("v0.6.15-beta", "v0614-beta2")
# The advanced file of version 5 (the usage meter's table), v0.6.16-beta.3's. A later ledger version is added the
# same way: its first release here, a tree of it in setUpClass, and a twin test beside the ones for version 5.
LEDGER_5_REFS = ("v0.6.16-beta.3",)
# The advanced file of version 7 (version 6, the wrap-up's wordings, is the step on the way to it; no release
# writes 6 and stops there): v0.6.16-beta.4's. Its table of wordings, headless_runs and chat_messages are the new ones.
LEDGER_7_REFS = ("v0.6.16-beta.4",)
VERSION = "codex-cli 0.158.0"
LOGIN = "someone"

# What the child runs, with the product's tree first on its path: <tree> <home> <base time> <mode>. In mode
# "prune", base is the time the product's own pruning pass runs at, on the ledger already in <home>.
CHILD = r'''
import hashlib, json, pathlib, sqlite3, sys

tree, home, base, mode = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), float(sys.argv[3]), sys.argv[4]
sys.path[:0] = [str(tree / "src")] + ([str(tree / "advanced" / "src")] if (tree / "advanced" / "src").is_dir() else [])

from codex_auto_resume import config, machine
from codex_auto_resume.store import SCHEMA_VERSION, Store

paths = config.Paths(home)
paths.ensure()
if mode == "migrate":
    with Store(paths.state_dir, migrate=True) as store:
        print(json.dumps({"schema": store.schema_version(), "count": len(store.all_records())}))
    raise SystemExit(0)


def extras(advanced, base):
    """What v0.6.16-beta.4 adds that the reporter does not read, as its own methods write it: a person's own wrap-up
    wording (version 6), a turn run here and a Dashboard chat message (version 7)."""
    with advanced._transaction() as connection:
        generation = connection.execute("SELECT generation FROM meta").fetchone()[0]
    advanced.set_wording("usage_wrap_up", "wrap_custom_five_hour", "Please wrap up, the budget is low.",
                         generation=generation, actor="dashboard", at=base)
    thread = "0a1b2c3d-%04x-7000-8000-%012x" % (9, 9)
    advanced.run_started(hashlib.sha256(b"a run").hexdigest(), "headless_run", thread,
                         started_at=base, ends_by=base + 600)
    advanced.add_chat(thread, "Is the build green?", hashlib.sha256(b"a chat").hexdigest(), at=base)


if mode in ("upgrade", "upgrade 7"):
    # A file of an older version opened by a build that writes a newer one: the product's own migration (state/schema.py
    # UPGRADE_FROM_4, then FROM_5 and the stage-4 step where the build has them), after which the meter has a reading
    # in it as the usage meter would have saved one, and, with "upgrade 7", the new tables a row each.
    from codex_auto_resume_advanced.state import AdvancedState

    advanced = AdvancedState(paths)
    advanced.save_meter([{"bucket": "codex", "window_minutes": 300, "used_percent": 91.5, "reset_at": int(base) + 3600}],
                        at=base)
    if mode == "upgrade 7":
        extras(advanced, base)
    advanced.close()
    ledger = sqlite3.connect(advanced.path)
    print(json.dumps({"ledger_schema": ledger.execute("PRAGMA user_version").fetchone()[0],
                      "spend": [list(row) for row in ledger.execute(
                          "SELECT interruption_id, at FROM spend ORDER BY spend_id")],
                      "meter": ledger.execute("SELECT count(*) FROM meter").fetchone()[0],
                      "tables": sorted(row[0] for row in ledger.execute(
                          "SELECT name FROM sqlite_master WHERE type='table'"))}))
    raise SystemExit(0)
if mode == "prune":
    from codex_auto_resume_advanced.state import AdvancedState
    from codex_auto_resume_advanced.state.journal import JournalMixin

    advanced = AdvancedState(paths)
    path = advanced.path
    advanced.close()
    ledger = sqlite3.connect(path)
    JournalMixin._prune_spend(ledger, "main", base)        # the pass its journal and every 256th unit run
    ledger.commit()
    print(json.dumps({"units": ledger.execute("SELECT count(*) FROM spend").fetchone()[0],
                      "given": ledger.execute("SELECT seq FROM sqlite_sequence WHERE name='spend'").fetchone()[0]}))
    ledger.close()
    raise SystemExit(0)


def key(name):
    return hashlib.sha256(name.encode("ascii")).hexdigest()


def uuid_of(number, kind):
    return "0a1b2c3d-%04x-7000-8000-%012x" % (kind, number)


def gates(**words):
    vector = {name: machine.gate(machine.PASS) for name in machine.GATES}
    vector.update(words)
    return machine.encode_gates(vector)


store = Store(paths.state_dir)
store.set_enabled(True, base)
written = {}


def make(name, number, *, state, reason, delivered=True, ledger=None, carried=(), client=None, gate_eval=None,
         hidden=False, turn_status="completed", claims=1, home=""):
    """One record, registered and claimed by the store, then carried to where it ends in its own columns - of
    the default Codex home, or (schema 5) of the home whose key `home` is, with the id that home's engine gives."""
    interruption = key(name)
    at = base + number * 3600
    record = {"thread_id": uuid_of(number, 1), "turn_id": uuid_of(number, 2), "completed_at": at - 60,
              "started_at": at - 600, "ordinal": 3, "interruption_id": interruption, "reset_at": at - 30,
              "limit_type": "codex:primary", "uncertain": False, "category": "usage_limit"}
    if home:
        from codex_auto_resume.domain import ids
        interruption = ids.interruption_id(record["thread_id"], record["turn_id"], record["completed_at"],
                                           record["ordinal"], home_key=home)
        record["interruption_id"] = interruption
    assert store.register(record, at, state="waiting_poll", next_retry_at=at, **({"home_key": home} if home else {}))
    claimed_at = None
    for claim in range(claims):
        claimed_at = at + 60.5 + claim * 900
        options = {"ledger": ledger, "carried": frozenset(carried)} if ledger is not None and claim == 0 else {}
        claimed, gate, why = store.reserve_detailed(interruption, claimed_at, **options)
        assert claimed, (name, gate, why)
        if claim + 1 < claims:              # a route that left it waiting: its claim given back, its time kept
            assert store.release_claim(interruption, "waiting_retry", "released_before_send", claimed_at + 1,
                                       next_retry_at=claimed_at + 2)
    changes = {"state": state, "last_error": reason, "gate_eval": gate_eval or gates(), "recovery_client_id": client}
    if delivered:
        changes.update(queue_id=uuid_of(number, 3), first_queued_at=claimed_at + 5, resumed_at=claimed_at + 30,
                       turn_started_at=claimed_at + 30, recovery_turn_id=uuid_of(number, 4),
                       recovery_turn_status=turn_status, outcome_at=claimed_at + 600)
    if hidden:
        changes["history_hidden_at"] = claimed_at + 700
    with store._transaction() as connection:
        connection.execute("UPDATE interruptions SET %s WHERE interruption_id=?"
                           % ", ".join("%s=?" % column for column in changes), (*changes.values(), interruption))
    written[name] = {"interruption_id": interruption, "last_claim_at": claimed_at, "client_id": client}


make("worked", 1, state="recovered", reason="progress_observed")
make("failed", 2, state="recovery_turn_failed", reason="turn_failed", turn_status="failed")
make("hidden", 3, state="recovered", reason="progress_observed", hidden=True)
if mode in ("v4", "v5", "v5 homes", "v5 meter", "v7"):
    assert SCHEMA_VERSION == (4 if mode == "v4" else 5)
    from codex_auto_resume.domain import ids
    from codex_auto_resume.domain.plug import Plug, Point
    from codex_auto_resume_advanced.ledger import ClaimLedger
    from codex_auto_resume_advanced.state import AdvancedState

    advanced = AdvancedState(paths)
    with advanced._transaction() as connection:        # the file made by its own schema; armed by hand
        connection.execute("INSERT INTO arming (capability, state, since, actor, reason, statement_revision, "
                           "engine_version, warnings) VALUES (?,?,?,?,?,?,?,?)",
                           ("goal_continuation", "armed", base, "dashboard", None, 1, None, None))

    class Paying(Plug):
        """The edition's claim ledger as core asks it (P11), told that the goal continuation's answer is
        carried - what the edition's runtime tells it when that feature named the channel or the route."""
        __slots__ = ("ledger",)

        def __init__(self, ledger):
            self.ledger = ledger

        def claim_ledger(self, connection, record, now, carried):
            return self.ledger.claim(connection, record, now, {"goal_continuation"} if carried else set())

    paying = Paying(ClaimLedger(advanced))
    make("marker free", 4, state="recovered", reason="progress_observed",
         client=ids.continuation_client_id(key("marker free")))
    make("goal route", 5, state="submission_unknown", reason="queue_result_unknown_do_not_resend", delivered=False,
         gate_eval=gates(thread_available=machine.gate(machine.PASS, machine.PLUGGED)))
    make("goal held", 6, state="superseded", reason="later_turn_exists", delivered=False,
         gate_eval=gates(thread_available=machine.gate(machine.WAIT, machine.HELD)))
    make("goal channel", 7, state="recovered", reason="progress_observed", ledger=paying, carried={Point.SENDER})
    make("paid then standard", 8, state="recovered", reason="progress_observed", ledger=paying,
         carried={Point.UNLOADED}, claims=2)
    if mode in ("v5 meter", "v7"):
        advanced.save_meter([{"bucket": "codex", "window_minutes": 300, "used_percent": 91.5,
                              "reset_at": int(base) + 3600}], at=base)
    if mode == "v7":
        extras(advanced, base)
    advanced.close()
    ledger = sqlite3.connect(advanced.path)
    written["meter"] = ledger.execute("SELECT count(*) FROM meter").fetchone()[0] if mode in ("v5 meter", "v7") else None
    written["extras"] = [ledger.execute("SELECT count(*) FROM " + name).fetchone()[0]
                         for name in ("wordings", "headless_runs", "chat_messages")] if mode == "v7" else None
    written["spend"] = [list(row) for row in ledger.execute("SELECT interruption_id, at FROM spend ORDER BY spend_id")]
    written["ledger_schema"] = ledger.execute("PRAGMA user_version").fetchone()[0]
    ledger.close()
if mode == "v5 homes":
    # A record of a further Codex home, as its engine registers it: the key the home is known by, from its path.
    from codex_auto_resume import homes
    other = homes.key(home / "second-codex-home")
    make("other home", 9, state="recovered", reason="progress_observed", home=other)
    written["home_key"] = other
store.close()
with Store(paths.state_dir, check=True) as checked:     # every row is one the product's own validator takes
    written["schema"] = checked.schema_version()
    written["count"] = len(checked.all_records())
    written["home_keys"] = sorted({row.get("home_key", "") for row in checked.all_records()})
print(json.dumps(written))
'''


def run(argv, **options):
    return subprocess.run(argv, capture_output=True, stdin=subprocess.DEVNULL, timeout=300,
                          creationflags=NO_WINDOW, **options)


def tagged() -> bool:
    if GIT is None or not (PRODUCT / ".git").exists():
        return False
    try:
        return all(run([GIT, "-C", str(PRODUCT), "rev-parse", "--verify", "-q", "refs/tags/%s^{commit}" % tag])
                   .returncode == 0 for tag in (SCHEMA_3, SCHEMA_4))
    except (OSError, subprocess.SubprocessError):
        return False


def schema_5_ref():
    """The first of SCHEMA_5_REFS the product's repository has, as a tag or a branch; None when it has neither."""
    if not tagged():
        return None
    for ref in SCHEMA_5_REFS:
        for full in ("refs/tags/%s" % ref, "refs/heads/%s" % ref):
            try:
                if run([GIT, "-C", str(PRODUCT), "rev-parse", "--verify", "-q", full + "^{commit}"]).returncode == 0:
                    return full
            except (OSError, subprocess.SubprocessError):
                return None
    return None


SCHEMA_5 = schema_5_ref()


def ledger_5_ref():
    """The first of LEDGER_5_REFS the product's repository has as a tag; None when it has none."""
    if not tagged():
        return None
    for ref in LEDGER_5_REFS:
        try:
            if run([GIT, "-C", str(PRODUCT), "rev-parse", "--verify", "-q", "refs/tags/%s^{commit}" % ref]).returncode == 0:
                return "refs/tags/" + ref
        except (OSError, subprocess.SubprocessError):
            return None
    return None


LEDGER_5 = ledger_5_ref()


def ledger_7_ref():
    """The first of LEDGER_7_REFS the product's repository has as a tag; None when it has none."""
    if not tagged():
        return None
    for ref in LEDGER_7_REFS:
        try:
            if run([GIT, "-C", str(PRODUCT), "rev-parse", "--verify", "-q", "refs/tags/%s^{commit}" % ref]).returncode == 0:
                return "refs/tags/" + ref
        except (OSError, subprocess.SubprocessError):
            return None
    return None


LEDGER_7 = ledger_7_ref()


def extract(tag, paths, into: pathlib.Path) -> pathlib.Path:
    """The tag's own files under `paths`, as `git archive` gives them, in a folder of their own."""
    done = run([GIT, "-C", str(PRODUCT), "archive", "--format=tar", tag, *paths])
    if done.returncode:
        raise AssertionError("git archive %s: %s" % (tag, done.stderr.decode("utf-8", "replace")))
    into.mkdir(parents=True)
    with tarfile.open(fileobj=io.BytesIO(done.stdout)) as archive:
        archive.extractall(into, **({"filter": "data"} if hasattr(tarfile, "data_filter") else {}))
    return into


def load_product_reader():
    spec = importlib.util.spec_from_file_location("community_report_for_product_state",
                                                  PRODUCT / "build" / "community_report.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@unittest.skipUnless(tagged(), "the product's repository, with its tags, is not beside this checkout")
class ProductStateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        root = pathlib.Path(cls.temporary.name)
        cls.root = root
        cls.base = time.time() - 3 * 86400 + 0.25
        trees = {SCHEMA_3: extract(SCHEMA_3, ["src/codex_auto_resume"], root / "v3-tree"),
                 SCHEMA_4: extract(SCHEMA_4, ["src/codex_auto_resume", "advanced/src"], root / "v4-tree")}
        cls.made = {}
        for name, tag, mode in (("v4", SCHEMA_4, "v4"), ("v3", SCHEMA_3, "v3")):
            cls.made[name] = cls.child(trees[tag], root / name, mode)
        shutil.copytree(root / "v3", root / "migrated")
        cls.made["migrated"] = cls.child(trees[SCHEMA_4], root / "migrated", "migrate")
        # The v0.6.11 state as its watcher leaves it 92 days on, when its ledger has pruned every unit.
        cls.pruned_at = cls.base + 92 * 86400
        shutil.copytree(root / "v4", root / "pruned")
        cls.made["pruned"] = cls.child(trees[SCHEMA_4], root / "pruned", "prune", base=cls.pruned_at)
        if SCHEMA_5:
            tree = extract(SCHEMA_5, ["src/codex_auto_resume", "advanced/src"], root / "v5-tree")
            for name in ("v5", "v5 homes"):
                cls.made[name] = cls.child(tree, root / name, name)
        if LEDGER_5 and SCHEMA_5:
            tree = extract(LEDGER_5, ["src/codex_auto_resume", "advanced/src"], root / "v5b-tree")
            cls.made["v5 meter"] = cls.child(tree, root / "v5 meter", "v5 meter")
            # The version-4 file v0.6.15-beta made, opened by v0.6.16-beta.3: brought to version 5 in place.
            shutil.copytree(root / "v5", root / "v5 upgraded")
            cls.made["v5 upgraded"] = cls.child(tree, root / "v5 upgraded", "upgrade")
            # v0.6.16-beta.3's own pruning, 92 days on, of the ledger it made.
            shutil.copytree(root / "v5 meter", root / "v5 pruned")
            cls.made["v5 pruned"] = cls.child(tree, root / "v5 pruned", "prune", base=cls.pruned_at)
        if LEDGER_7 and LEDGER_5 and SCHEMA_5:
            tree = extract(LEDGER_7, ["src/codex_auto_resume", "advanced/src"], root / "v7-tree")
            cls.made["v7"] = cls.child(tree, root / "v7", "v7")
            # The version-5 file v0.6.16-beta.3 made, opened by v0.6.16-beta.4: brought to version 7 in place
            # (UPGRADE_FROM_5, then the stage-4 step); and the version-4 file of v0.6.15-beta, through all three.
            shutil.copytree(root / "v5 meter", root / "v7 upgraded")
            cls.made["v7 upgraded"] = cls.child(tree, root / "v7 upgraded", "upgrade 7")
            shutil.copytree(root / "v5", root / "v7 from 4")
            cls.made["v7 from 4"] = cls.child(tree, root / "v7 from 4", "upgrade")
            # v0.6.16-beta.4's own pruning, 92 days on, of the ledger it made.
            shutil.copytree(root / "v7", root / "v7 pruned")
            cls.made["v7 pruned"] = cls.child(tree, root / "v7 pruned", "prune", base=cls.pruned_at)

    @classmethod
    def child(cls, tree, home, mode, base=None):
        """What the product's own code made in `home`, as the child said it."""
        home.mkdir(parents=True, exist_ok=True)
        script = cls.root / "child.py"
        script.write_text(CHILD, encoding="utf-8")
        scratch = {"CODEX_AUTO_RESUME_HOME": str(home), "CODEX_HOME": str(home / "codex-home"),
                   "LOCALAPPDATA": str(home / "local"), "APPDATA": str(home / "roaming")}
        done = run([sys.executable, "-I", str(script), str(tree), str(home), repr(cls.base if base is None else base),
                    mode],
                   cwd=str(cls.root), env=dict(os.environ, **scratch))
        if done.returncode:
            raise AssertionError("the product's own code failed (%s):\n%s"
                                 % (mode, done.stderr.decode("utf-8", "replace")[-3000:]))
        return json.loads(done.stdout.decode("utf-8"))

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def installation(self, made, *, user_version=None, ledger_version=None):
        """An installation holding what the product made in `made`, with only what the reporter reads."""
        home = self.root / "installation"
        if home.exists():
            shutil.rmtree(home)
        (home / "app" / ".codex-plugin").mkdir(parents=True)
        (home / "app" / ".codex-plugin" / "plugin.json").write_text(
            json.dumps({"name": "codex-auto-resume", "version": "0.6.11"}), encoding="utf-8")
        (home / "logs").mkdir()
        stamp = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(self.base - 3600))
        (home / "logs" / "auto-resume.log").write_text(
            "[%s] engine %s %s. Delivery is still proven per interruption before anything is marked resumed.\n"
            % (stamp, VERSION, reporter.ENGINE_LOG_WORDS["verified"]), encoding="utf-8")
        shutil.copytree(self.root / made / "config", home / "config",
                        ignore=shutil.ignore_patterns("*backup*", "*-journal", "*-wal", "*-shm"))
        (home / "config" / "compatibility.json").write_text(json.dumps({"engine": {"version": VERSION}}),
                                                            encoding="utf-8")
        for name, version in (("state.sqlite", user_version), ("advanced/advanced.sqlite", ledger_version)):
            if version is not None:
                database = sqlite3.connect(home / "config" / name)
                database.execute("PRAGMA user_version = %d" % version)
                database.commit()
                database.close()
        (home / "codex").mkdir()
        return mock.patch.multiple(reporter, PRODUCT=home, CODEX=home / "codex", HOME=self.root)

    def report(self, made, at=None, **options):
        """What the reporter makes of it, run now or, given `at`, with this machine's clock at that time."""
        notes = {}
        clock = contextlib.nullcontext() if at is None else mock.patch.object(reporter.time, "time", return_value=at)
        with self.installation(made, **options), clock:
            report = reporter.build(LOGIN, notes=notes)
            status = reporter.machine()
        return report, notes, status

    def test_the_product_made_each_state_with_its_own_store(self):
        self.assertEqual((self.made["v3"]["schema"], self.made["v3"]["count"]), (3, 3))
        self.assertEqual((self.made["v4"]["schema"], self.made["v4"]["count"]), (4, 8))
        self.assertEqual(self.made["migrated"], {"schema": 4, "count": 3})

    def test_schema_4_is_read_with_the_counts_the_receiving_side_makes_of_it(self):
        report, notes, status = self.report("v4")
        self.assertEqual([entry["state"] for entry in report["records"]],
                         ["recovered", "recovery_turn_failed", "recovered"])
        self.assertEqual([bool(entry["delivered_at"]) for entry in report["records"]], [True] * 3)
        self.assertEqual((notes["hidden"], notes["routed"], notes["elsewhere"], notes["unplaced"], notes["route_unknown"]),
                         (1, 4, 0, {}, 0))
        exact = report["capabilities"]["exact_thread_recovery"]
        self.assertEqual((exact["confirmed"], exact["missed"], exact["level"]), (3, 0, "VERIFIED"))
        self.assertEqual(report["reporter"]["product_version"], "0.6.11")
        self.assertEqual((status["records"]["total"], status["records"]["other_route"], status["hidden"]), (3, 4, 1))
        self.assertIn("other route    : 4 sent by an advanced feature's own route, which a report leaves out",
                      status["lines"])
        raw = reporter.encode(report)
        self.assertEqual(reporter.validate(raw)[1], [])
        reader = load_product_reader()
        parsed, problems, _recomputed = reader.inspect(raw, author=LOGIN, releases=None)
        self.assertEqual(problems, [])
        self.assertEqual(reader.graded(parsed), {"worked": True, "failed": True, "neither": False, "both": True})

    def test_the_marks_it_reads_are_the_ones_the_product_wrote(self):
        marker_free = self.made["v4"]["marker free"]
        namespace = uuid.uuid5(uuid.NAMESPACE_URL, "urn:codex-auto-resume:continuation-client-id")
        self.assertEqual(marker_free["client_id"], str(uuid.uuid5(namespace, marker_free["interruption_id"])))
        self.assertEqual(reporter.CONTINUATION_NAMESPACE, namespace)
        # The ledger paid each claim that carried the feature's answer at that claim's own time: the one the
        # goal continuation's channel was sent from is its record's last claim, and the route that left a
        # record waiting is not the claim the standard route later sent it from.
        spent = {key: at for key, at in self.made["v4"]["spend"]}
        channel, then = self.made["v4"]["goal channel"], self.made["v4"]["paid then standard"]
        self.assertEqual(spent[channel["interruption_id"]], channel["last_claim_at"])
        self.assertLess(spent[then["interruption_id"]], then["last_claim_at"])
        self.assertEqual(len(spent), 2)

    def test_a_record_claimed_before_the_products_own_pruning_reaches_is_left_out(self):
        """92 days on, v0.6.11's own pruning has taken both units (LEDGER REACH): the goal continuation's
        channel, now marked by nothing, and every other record claimed then are left out, not counted as the
        standard route's. The same ledger before the pruning, read at the same time, lost nothing and tells
        every claim, as it did."""
        self.assertEqual(self.made["pruned"], {"units": 0, "given": 2})
        report, notes, status = self.report("pruned", at=self.pruned_at)
        self.assertEqual((len(report["records"]), notes["hidden"], notes["routed"], notes["route_unknown"]),
                         (0, 1, 3, 4))
        self.assertEqual((status["records"]["total"], status["records"]["other_route"],
                          status["records"]["route_unknown"]), (0, 3, 4))
        self.assertIn("route unknown  : 4 claimed before the advanced edition's spend ledger reaches back, which "
                      "a report leaves out", status["lines"])
        self.assertEqual(report["capabilities"]["exact_thread_recovery"]["confirmed"], 0)
        report, notes, _status = self.report("v4", at=self.pruned_at)
        self.assertEqual((len(report["records"]), notes["routed"], notes["route_unknown"]), (3, 4, 0))

    def test_schema_3_reads_as_it_did_and_as_v0_6_11_migrates_it(self):
        reports = {}
        for made in ("v3", "migrated"):
            with self.subTest(made):
                report, notes, _status = self.report(made)
                self.assertEqual([entry["state"] for entry in report["records"]], ["recovered", "recovery_turn_failed"])
                self.assertEqual((notes["hidden"], notes["routed"], notes["route_unknown"]), (1, 0, 0))
                reports[made] = dict(report, recorded_at=None)
        self.assertEqual(reports["v3"], reports["migrated"])

    @unittest.skipUnless(SCHEMA_5, "schema 5's release, or its branch, is not in the product's repository")
    def test_schema_5_and_ledger_4_read_as_their_v0_6_11_twins(self):
        """v0.6.15-beta's store and edition make the same records as v0.6.11's, every one the default home's
        (home_key ''), and the spend ledger of version 4: the report is v0.6.11's, of schema 4 and ledger 2."""
        self.assertEqual((self.made["v5"]["schema"], self.made["v5"]["count"], self.made["v5"]["ledger_schema"]),
                         (5, 8, 4))
        self.assertEqual(self.made["v5"]["home_keys"], [""])
        self.assertEqual(self.made["v4"]["spend"], self.made["v5"]["spend"])
        reports = {}
        for made in ("v4", "v5"):
            with self.subTest(made):
                report, notes, status = self.report(made)
                self.assertEqual((notes["hidden"], notes["routed"], notes["route_unknown"]), (1, 4, 0))
                reports[made] = (dict(report, recorded_at=None), notes, status["records"], status["lines"])
        self.assertEqual(reports["v4"], reports["v5"])

    @unittest.skipUnless(SCHEMA_5, "schema 5's release, or its branch, is not in the product's repository")
    def test_a_record_of_another_codex_home_counts_and_its_home_is_never_said(self):
        """The record v0.6.15-beta's store keeps for a further Codex home is counted as the default home's are
        (HOMES), and the receiving side counts it so; nothing the reporter writes or says carries its key."""
        made = self.made["v5 homes"]
        self.assertEqual((made["schema"], made["count"], made["home_keys"]), (5, 9, sorted(["", made["home_key"]])))
        report, notes, status = self.report("v5 homes")
        self.assertEqual([entry["state"] for entry in report["records"]],
                         ["recovered", "recovery_turn_failed", "recovered", "recovered"])
        self.assertIsNone(report["records"][-1]["progress_items"])
        self.assertEqual((notes["hidden"], notes["routed"], notes["route_unknown"]), (1, 4, 0))
        exact = report["capabilities"]["exact_thread_recovery"]
        self.assertEqual((exact["confirmed"], exact["missed"], exact["level"]), (4, 0, "VERIFIED"))
        self.assertEqual(status["records"]["total"], 4)
        raw = reporter.encode(report)
        reader = load_product_reader()
        _parsed, problems, _recomputed = reader.inspect(raw, author=LOGIN, releases=None)
        self.assertEqual(problems, [])
        for text in (raw.decode("ascii"), json.dumps(status), json.dumps(notes)):
            self.assertNotIn(made["home_key"], text)
            self.assertNotIn("home_key", text)
            self.assertNotIn("second-codex-home", text)

    @unittest.skipUnless(LEDGER_5 and SCHEMA_5, "ledger 5's release is not in the product's repository")
    def test_ledger_5_with_a_meter_reads_as_ledger_4_did(self):
        """v0.6.16-beta.3 makes the advanced file of version 5 - the usage meter's table, and `options` and
        `continuations` made again with wider lists - and the core state of schema 5 as before. The spend table
        is the same, so the report is the version-4 file's, and says nothing of the meter."""
        made = self.made["v5 meter"]
        self.assertEqual((made["schema"], made["count"], made["ledger_schema"], made["meter"]), (5, 8, 5, 1))
        self.assertEqual(made["home_keys"], [""])
        self.assertEqual(self.made["v5"]["spend"], made["spend"])
        reports = {}
        for name in ("v5", "v5 meter"):
            with self.subTest(name):
                report, notes, status = self.report(name)
                self.assertEqual((notes["hidden"], notes["routed"], notes["route_unknown"]), (1, 4, 0))
                reports[name] = (dict(report, recorded_at=None), notes, status["records"], status["lines"])
        self.assertEqual(reports["v5"], reports["v5 meter"])
        report, _notes, status = self.report("v5 meter")
        raw = reporter.encode(report)
        self.assertEqual(reporter.validate(raw)[1], [])
        _parsed, problems, _recomputed = load_product_reader().inspect(raw, author=LOGIN, releases=None)
        self.assertEqual(problems, [])
        shown = raw.decode("ascii") + json.dumps(status)
        for word in ("meter", "used_percent", "91.5", "wrap_up"):
            self.assertNotIn(word, shown)

    @unittest.skipUnless(LEDGER_5 and SCHEMA_5, "ledger 5's release is not in the product's repository")
    def test_a_version_4_file_opened_by_v0_6_16_beta_3_keeps_every_unit_and_reads_the_same(self):
        """The product's own migration (UPGRADE_FROM_4) remakes two tables and adds the meter's, and keeps the
        spend ledger's rows and ids as they were: the report is the one the version-4 file gave."""
        upgraded = self.made["v5 upgraded"]
        self.assertEqual((upgraded["ledger_schema"], upgraded["meter"]), (5, 1))
        self.assertIn("meter", upgraded["tables"])
        self.assertEqual(upgraded["spend"], self.made["v5"]["spend"])
        before, after = self.report("v5")[:2], self.report("v5 upgraded")[:2]
        self.assertEqual((dict(before[0], recorded_at=None), before[1]), (dict(after[0], recorded_at=None), after[1]))
        self.assertEqual(after[1]["routed"], 4)

    @unittest.skipUnless(LEDGER_5 and SCHEMA_5, "ledger 5's release is not in the product's repository")
    def test_v0_6_16_beta_3s_own_pruning_leaves_the_same_reach(self):
        """Its pruning pass, 92 days on, takes both units as v0.6.11's did (LEDGER REACH), and the records
        claimed then are left out as route unknown."""
        self.assertEqual(self.made["v5 pruned"], {"units": 0, "given": 2})
        report, notes, _status = self.report("v5 pruned", at=self.pruned_at)
        self.assertEqual((len(report["records"]), notes["hidden"], notes["routed"], notes["route_unknown"]),
                         (0, 1, 3, 4))

    @unittest.skipUnless(LEDGER_7 and LEDGER_5 and SCHEMA_5, "ledger 7's release is not in the product's repository")
    def test_ledger_7_with_wordings_runs_and_chat_reads_as_ledger_4_did(self):
        """v0.6.16-beta.4 makes the advanced file of version 7: version 6 widens `options` and `continuations` again
        and adds the wordings' table, version 7 adds headless_runs and chat_messages, and the spend table is the
        same. The report is the version-4 file's, and says nothing of any of them."""
        made = self.made["v7"]
        self.assertEqual((made["schema"], made["count"], made["ledger_schema"], made["meter"]), (5, 8, 7, 1))
        self.assertEqual(made["extras"], [1, 1, 1])
        self.assertEqual(made["home_keys"], [""])
        self.assertEqual(self.made["v5"]["spend"], made["spend"])
        reports = {}
        for name in ("v5", "v7"):
            with self.subTest(name):
                report, notes, status = self.report(name)
                self.assertEqual((notes["hidden"], notes["routed"], notes["route_unknown"]), (1, 4, 0))
                reports[name] = (dict(report, recorded_at=None), notes, status["records"], status["lines"])
        self.assertEqual(reports["v5"], reports["v7"])
        report, _notes, status = self.report("v7")
        raw = reporter.encode(report)
        self.assertEqual(reporter.validate(raw)[1], [])
        _parsed, problems, _recomputed = load_product_reader().inspect(raw, author=LOGIN, releases=None)
        self.assertEqual(problems, [])
        shown = raw.decode("ascii") + json.dumps(status)
        for word in ("meter", "used_percent", "91.5", "wrap_up", "budget is low", "Is the build green", "headless",
                     "chat", "wording"):
            self.assertNotIn(word, shown)

    @unittest.skipUnless(LEDGER_7 and LEDGER_5 and SCHEMA_5, "ledger 7's release is not in the product's repository")
    def test_files_of_version_5_and_4_opened_by_v0_6_16_beta_4_keep_every_unit_and_read_the_same(self):
        """The product's own migration (UPGRADE_FROM_5 and the stage-4 step; from 4, UPGRADE_FROM_4 first) remakes
        two tables, adds three, and keeps the spend ledger's rows and ids as they were."""
        upgraded = self.made["v7 upgraded"]
        self.assertEqual((upgraded["ledger_schema"], upgraded["meter"]), (7, 1))
        for table in ("meter", "wordings", "headless_runs", "chat_messages"):
            self.assertIn(table, upgraded["tables"])
        self.assertEqual(self.made["v7 from 4"]["ledger_schema"], 7)
        for name in ("v7 upgraded", "v7 from 4"):
            with self.subTest(name):
                self.assertEqual(self.made[name]["spend"], self.made["v5"]["spend"])
                before, after = self.report("v5")[:2], self.report(name)[:2]
                self.assertEqual((dict(before[0], recorded_at=None), before[1]),
                                 (dict(after[0], recorded_at=None), after[1]))
                self.assertEqual(after[1]["routed"], 4)

    @unittest.skipUnless(LEDGER_7 and LEDGER_5 and SCHEMA_5, "ledger 7's release is not in the product's repository")
    def test_v0_6_16_beta_4s_own_pruning_leaves_the_same_reach(self):
        """Its pruning pass, 92 days on, takes both units as v0.6.11's did (LEDGER REACH), the rows of its new tables
        stay where they are, and the records claimed then are left out as route unknown."""
        self.assertEqual(self.made["v7 pruned"], {"units": 0, "given": 2})
        report, notes, _status = self.report("v7 pruned", at=self.pruned_at)
        self.assertEqual((len(report["records"]), notes["hidden"], notes["routed"], notes["route_unknown"]),
                         (0, 1, 3, 4))

    def test_a_schema_it_does_not_know_is_refused_on_the_products_own_file(self):
        for version, said in ((6, r"newer Codex Auto Resume than this reporter knows \(schema 6\)\. "
                                  r"Update codex-compat-reporter\."),
                              (2, r"has schema 2; this reporter needs Codex Auto Resume v0\.6\.0 or newer")):
            with self.subTest(version):
                with self.installation("v4", user_version=version):
                    with self.assertRaisesRegex(reporter.Refused, said):
                        reporter.build(LOGIN)

    def test_a_ledger_schema_it_does_not_know_is_refused_on_the_products_own_ledger(self):
        with reporter.readonly(self.root / "v4" / "config" / "advanced" / "advanced.sqlite") as ledger:
            self.assertIn(ledger.execute("PRAGMA user_version").fetchone()[0], reporter.LEDGER_SCHEMAS)
        for version, said in ((8, r"newer Codex Auto Resume than this reporter knows \(ledger schema 8\)\. "
                                  r"Update codex-compat-reporter\."),
                              (0, r"has ledger schema 0, which no Codex Auto Resume this reporter knows writes")):
            with self.subTest(version):
                with self.installation("v4", ledger_version=version):
                    with self.assertRaisesRegex(reporter.Refused, said):
                        reporter.build(LOGIN)
                    status = reporter.machine()
                self.assertEqual(status["records"]["found"], "unreadable")


if __name__ == "__main__":
    unittest.main()
