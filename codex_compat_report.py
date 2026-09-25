"""codex-compat-reporter - tell the Codex Auto Resume project how it behaved on your machine.

    python codex_compat_report.py status
    python codex_compat_report.py report --login <your GitHub login> [--codex-version V] [--out FILE] [--force]
    python codex_compat_report.py submit [FILE] [--login L] [--sha256 HEX] [--dry-run | --yes]

(`py` works in place of `python` where the Python launcher is installed.)

What it reads, on this machine only and read-only: the product's own installation - its plugin
manifest, its log and the five rotated copies of it, its state database and the compatibility
report its watcher writes - and, for progress counts alone, Codex's own history database. Thread
and turn ids, and the paths of those files, are read to find and join the records; they are used
here and never written into the report. Records hidden with Clear history are left out.

What it writes: one JSON file of counts, states, times and version strings, which `report` writes
and never writes over unless told to. `submit` sends exactly the bytes of that file, after you have
read it: it never rebuilds it, and it checks it with the project's own rules before anything
leaves the machine.

What it cannot do: make a Codex version "verified" for anybody else. A report has a grade of its
own, Reported: it stands beside the ladder of four words - verified, checked, compatible, failed
here - and never on it, and never raises a version's tier. It is shown beside the version with the
number of machines that said the same thing, and a version whose own evidence says nothing stays
compatible however many reports arrive. The tool measures; the project recomputes every derived
field from the measurements when the report arrives, so a hand-edited conclusion does not survive.
Nothing here proves a file was not made up on the machine that sent it, and the project says so out
loud rather than pretending otherwise.

Exit codes: 0 done; 1 an unexpected error (a bug - please report it); 2 refused (the message says
why and what to do), or a usage error; 3 `submit` found the project not taking reports yet, and sent
nothing.
"""
from __future__ import annotations

import argparse
import base64
import collections
import contextlib
import datetime as dt
import hashlib
import json
import math
import os
import pathlib
import platform
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

__version__ = "1.1.0"

REPO = "songyb111-gachon/codex-auto-resume-windows"
HOST = "github.com"                             # every GitHub call names it; GH_HOST never redirects one
COMMUNITY = "docs/evidence/community"          # where a report goes on the product repository
FORMAT = "codex-auto-resume-compat-evidence/1"  # the maintainer's own evidence format, unchanged
HOME = pathlib.Path(os.environ.get("USERPROFILE") or pathlib.Path.home())
PRODUCT = pathlib.Path(os.environ.get("CODEX_AUTO_RESUME_HOME") or (HOME / ".codex-auto-resume"))
CODEX = pathlib.Path(os.environ.get("CODEX_HOME") or (HOME / ".codex"))

EXIT_OK, EXIT_REFUSED, EXIT_NOT_OPEN = 0, 2, 3
SCHEMA = 3                   # the state database's user_version; Codex Auto Resume v0.6.0 and later
MINIMUM_PRODUCT = "v0.6.0"
MAX_BYTES, MAX_RECORDS = 1_000_000, 500       # the receiving side's limits, compat_admin.py

GATE = ("engine_present", "exact_thread_recovery")
PROGRESS = ("agentMessage", "commandExecution", "fileChange", "mcpToolCall")
OUTCOMES = {"recovered", "completed_no_progress", "recovery_turn_failed", "stopped_by_user", "handed_over"}
LOG_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")
ENGINE = re.compile(r"engine (codex-cli \d[0-9A-Za-z.\-]*?)[\s;,)]")
# The product keeps its log and five rotated copies (logbook.py, BACKUP_COUNT = 5), read oldest first.
LOG_NAMES = tuple("auto-resume.log.%d" % number for number in range(5, 0, -1)) + ("auto-resume.log",)

# What the product's log says about the engine it accepted - copied verbatim from its
# runtime/app.py (v0.6.5 and later; "checked" since v0.6.7). Every one of them but "incompatible"
# says the local checks passed and the product went on to use the engine. The "incompatible" line
# also says the checks pass, but the product sends nothing on that build, so it is not counted.
ENGINE_LOG_WORDS = {
    "verified": "is verified: its local checks pass, and the registry data in force verifies "
                "this build",
    "structurally_compatible": "is compatible: its local checks pass (`codex queue` still "
                               "offers --thread/--message), and the registry data in force "
                               "does not verify this build",
    "incompatible": "passes its local checks, but the registry data in force marks it "
                    "incompatible; nothing is sent while that data is in force",
    "checked": "is checked: its local checks pass, and the registry data in force records the "
               "maintainer's checks passing on this build; no real recovery has verified it yet",
}
ENGINE_LOG_CHECKS_ONLY = "passes its local checks (`codex queue` still offers --thread/--message)"
ENGINE_LOG_BEFORE_0_6_5 = "accepted because `codex queue` still offers"   # v0.6.0 - v0.6.4
PASSES = (ENGINE_LOG_WORDS["verified"], ENGINE_LOG_WORDS["structurally_compatible"],
          ENGINE_LOG_WORDS["checked"], ENGINE_LOG_CHECKS_ONLY, ENGINE_LOG_BEFORE_0_6_5)
# The reasons the watcher's own compatibility report gives when a capability's local checks
# passed (compat/standing.py resolve: a registry_* reason is given only on a local PASS).
LOCAL_PASS_REASONS = frozenset({"local_checks_passed", "registry_verified", "registry_checked"})

LOGIN = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z")
VERSION = re.compile(r"\Acodex-cli \d[0-9A-Za-z.\-]{0,39}\Z")
WORD = re.compile(r"\A[A-Za-z0-9_.\-]{1,40}\Z")
TIME = "%Y-%m-%dT%H:%M:%SZ"

# Every word a record can contribute to the report, copied from the product's own public
# vocabulary. A value outside these sets becomes "other" rather than travelling: the product may
# one day write a word this tool has not seen, and an unknown word is the one place free text could
# get in. Nothing here can hold a path, a message or a name.
CATEGORIES = frozenset({
    "auth_service_transient", "network_transient", "rate_limit_transient", "server_5xx",
    "stream_interrupted", "terminal_auth", "terminal_failure", "terminal_invalid",
    "terminal_permission", "terminal_policy", "terminal_user", "timeout", "unknown", "usage_limit"})
STATES = frozenset({
    "cancelled", "completed_no_progress", "failed", "handed_over", "no_progress_exhausted",
    "outcome_unverified", "queued", "recovered", "recovery_turn_failed", "resumed",
    "retry_budget_exhausted", "stopped_by_user", "submission_unknown", "submitting", "superseded",
    "superseded_by_user", "terminal_failure", "turn_completed", "turn_started", "waiting_backoff",
    "waiting_for_app", "waiting_for_loaded_thread", "waiting_for_usage", "waiting_poll",
    "waiting_reset", "waiting_retry", "withdrawn_unconfirmed"})
TURN_STATUSES = frozenset({"completed", "failed", "inProgress", "interrupted", "other"})
REASONS = frozenset({
    "ambiguous_receipt", "awaiting_delivery_receipt", "budget_restored", "cancel",
    "category_disabled", "chain_cap", "correlation_conflict", "daily_submission_cap",
    "desktop_app_unavailable", "duplicate_marker", "duplicate_owner", "expired",
    "later_turn_exists", "latest_turn_changed", "loaded_recheck_failed", "loaded_state_unknown",
    "marker_not_turn_initiator", "multiple_matching_queue_items", "no_progress_budget",
    "no_progress_observed", "no_receipt_do_not_resend", "notLoaded", "not_loaded",
    "other_recovery_in_flight", "outcome_deadline", "owned_queue_removed", "parent_cancelled",
    "parent_handed_over", "paused", "paused_unknown", "post_send_bookkeeping_failed",
    "progress_observed", "progress_then_turn_failed", "projection_stale",
    "queue_cleanup_unconfirmed", "queue_launch_retry_limit", "queue_process_not_started",
    "queue_result_unknown_do_not_resend", "queued_item_edited", "recovery_budget",
    "released_after_withdrawal", "released_before_send", "retry_now", "stale_turn_row",
    "superseded", "superseded_by_user", "thread_disabled", "thread_submission_cooldown",
    "turn_failed", "turn_interrupted", "turn_without_user_item", "unknown_turn_status",
    "usage_never_available", "usage_not_restored_after_reset", "usage_recheck_failed",
    "usage_unavailable", "usage_unknown", "user_cancelled", "user_input_queued", "user_joined",
    "user_queued_input", "waiting_reset", "withdraw_unconfirmed"})

# The columns read from the state database, and nothing else. thread_id and recovery_turn_id
# only key the progress count below; history_hidden_at only leaves hidden records out.
COLUMNS = ("thread_id", "category", "state", "last_error", "detected_at", "resumed_at", "outcome_at",
           "submitted_at", "recovery_turn_id", "recovery_turn_status", "gate_eval", "reset_at",
           "limit_type", "history_hidden_at")


def known(value, vocabulary):
    """The word itself when the report is allowed to carry it, "other" when it is not."""
    if value is None:
        return None
    return value if isinstance(value, str) and value in vocabulary else "other"


class Refused(Exception):
    """Something this tool will not guess at. The message says what to do."""
    exit_code = EXIT_REFUSED


# --------------------------------------------------------------------- what one recovery shows
def _gates(row) -> dict:
    """The record's gate evaluation, or {} when it is missing or not what the product writes."""
    try:
        gates = json.loads(row["gate_eval"] or "{}")
    except (ValueError, TypeError):
        return {}
    return gates if isinstance(gates, dict) else {}


def _gate(row, name):
    """True or False for one gate, as the maintainer's tool reads it; None when the evaluation
    is not the JSON object the product writes."""
    try:
        gates = json.loads(row["gate_eval"] or "{}")
    except (ValueError, TypeError):
        return None
    if not isinstance(gates, dict):
        return None
    gate = gates.get(name)
    return isinstance(gate, list) and bool(gate) and gate[0] == "PASS"


def _delivered(row):
    """Delivered means the product proved its message arrived: resumed_at is set. A backfilled
    recovery_turn_id without it proves nothing (store/records.py), and the file's delivered_at
    is read from the same column, so the two can never disagree."""
    return bool(row["resumed_at"])


EXERCISED = {
    "usage_limit_detection": lambda r: True if r["category"] == "usage_limit" else None,
    "usage_reset_hint": lambda r: (bool(r["reset_at"]) and str(r["limit_type"] or "").startswith("codex:"))
                                  if r["category"] == "usage_limit" else None,
    "engine_present": lambda r: _gate(r, "engine_compatible") if r["gate_eval"] else None,
    "projection_freshness": lambda r: _gate(r, "identity") if r["gate_eval"] else None,
    "loaded_state_detection": lambda r: _gate(r, "thread_available") if r["gate_eval"] else None,
    "usage_probe": lambda r: _gate(r, "usage") if r["gate_eval"] else None,
    "thread_eligibility": lambda r: True if r["submitted_at"] else None,
    "exact_thread_recovery": lambda r: True if _delivered(r) else (False if r["submitted_at"] and r["state"]
                                                                   in ("submission_unknown", "failed") else None),
    "recovery_turn_tracking": lambda r: (r["state"] in OUTCOMES) if _delivered(r) and r["state"] != "turn_started" else None,
    "outcome_observation": lambda r: (r["state"] in OUTCOMES) if _delivered(r) and r["state"] != "turn_started" else None,
}


# ------------------------------------------------------------------------------ small helpers
def iso(when) -> str:
    return dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime(TIME)


def _moment(value):
    """A stored time as a number, or None when it is not one."""
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value <= 0:
        return None
    return float(value)


def _dict(value) -> dict:
    return value if isinstance(value, dict) else {}


def full(version: str) -> str:
    version = version.strip()
    return version if version.startswith("codex-cli ") else "codex-cli " + version


def canonical_version(value: str) -> str:
    """`codex-cli <version>` as the project accepts it, and safe as a file and branch name."""
    version = full(str(value))
    if (not VERSION.match(version) or ".." in version or version.endswith(".")
            or version.endswith(".lock")):
        raise Refused("%r is not a Codex version: give it as 0.155.0 or codex-cli 0.155.0." % value)
    return version


def file_name(version: str) -> str:
    """codex-cli-<version>.json: the name a report has, wherever it is kept."""
    return "codex-cli-%s.json" % canonical_version(version)[len("codex-cli "):]


def destination(version: str, login: str):
    """The one path and branch a report for this version from this login can have."""
    name = file_name(version)
    return "%s/%s/%s" % (COMMUNITY, login, name), "compat-report/" + name[:-len(".json")]


def default_path(version: str) -> pathlib.Path:
    return pathlib.Path.cwd() / file_name(version)


@contextlib.contextmanager
def readonly(path: pathlib.Path):
    """A SQLite file opened so that nothing can be written to it, as the product opens Codex's.

    The URI comes from Path.as_uri(), which escapes '#', '%' and '?' in a folder name; a
    hand-built one lets a '#' cut off `?mode=ro`, and SQLite then creates a file there.
    """
    connection = sqlite3.connect(pathlib.Path(path).resolve().as_uri() + "?mode=ro", uri=True, timeout=3)
    try:
        connection.execute("PRAGMA query_only = ON")
        connection.execute("PRAGMA trusted_schema = OFF")
        yield connection
    finally:
        connection.close()


# ------------------------------------------------------------------------------ this machine
def installed_product() -> str:
    manifest = PRODUCT / "app" / ".codex-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8-sig"))["version"])
    except (OSError, ValueError, KeyError, TypeError):
        raise Refused("Codex Auto Resume does not look installed at %s.\n"
                      "Install it first, or set CODEX_AUTO_RESUME_HOME to where it is." % PRODUCT)


def watcher_report() -> dict:
    """The compatibility report the watcher writes for itself - the product's own answer."""
    try:
        return _dict(json.loads((PRODUCT / "config" / "compatibility.json").read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return {}


def engine_version_of(text: str):
    found = ENGINE.search(text + " ")
    return found.group(1) if found else None


def installed_codex(lines=None) -> str:
    """The engine version the product last reported, which is the version a report is about."""
    version = _dict(watcher_report().get("engine")).get("version")
    if isinstance(version, str) and version.strip() and VERSION.match(full(version)):
        return full(version)
    for _when, text in reversed(log_lines() if lines is None else lines):
        found = engine_version_of(text)
        if found and VERSION.match(found):
            return found
    raise Refused("This machine has no engine version to report yet: start Codex, let the watcher "
                  "run once, and try again.")


def log_lines() -> list:
    """(time, text) for every line of the product's log and its rotated copies, oldest first."""
    lines = []
    for name in LOG_NAMES:
        try:
            text = (PRODUCT / "logs" / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            found = LOG_LINE.match(line)
            if not found:
                continue
            try:
                when = time.mktime(time.strptime(found.group(1), "%Y-%m-%d %H:%M:%S"))
            except (ValueError, OverflowError):
                continue
            lines.append((when, found.group(2)))
    lines.sort(key=lambda line: line[0])
    return lines


def engine_timeline(lines) -> list:
    return [(when, version) for when, text in lines for version in [engine_version_of(text)] if version]


def passes_checks(text: str, version: str) -> bool:
    """A log line saying the product's local checks passed on exactly this engine version."""
    return engine_version_of(text) == version and any(words in text for words in PASSES)


def placement(timeline, start, end, current):
    """(version, None) for the engine version a record belongs to, or (None, why) when the
    product's own reports cannot say: the last report before must name it, no report between may
    name another, and the first report after must name it too - or there is none yet and it is
    the version installed now."""
    before = [version for when, version in timeline if when <= start]
    if not before:
        return None, "no engine line before it in the logs kept"
    version = before[-1]
    if {other for when, other in timeline if start < when < end} - {version}:
        return None, "the engine changed while it ran"
    after = [other for when, other in timeline if when >= end]
    if after:
        return (version, None) if after[0] == version else (None, "the engine changed while it ran")
    return (version, None) if version == current else (None, "the engine changed after it")


def version_at(timeline, start, end, current):
    return placement(timeline, start, end, current)[0]


def span(row):
    start = _moment(row["resumed_at"]) or _moment(row["detected_at"])
    return start, _moment(row["outcome_at"]) or start


def state_rows():
    """(rows, hidden) from the product's state database, or None when there is none yet.

    Only the named columns, only records not hidden with Clear history, and only from the
    schema this reporter knows: a newer or unknown one is refused rather than read as today's.
    """
    path = PRODUCT / "config" / "state.sqlite"
    if not path.is_file():
        return None
    try:
        with readonly(path) as db:
            found = db.execute("PRAGMA user_version").fetchone()[0]
            if found > SCHEMA:
                raise Refused("%s was written by a newer Codex Auto Resume than this reporter knows "
                              "(schema %d). Update codex-compat-reporter." % (path, found))
            if found != SCHEMA:
                raise Refused("%s has schema %d; this reporter needs Codex Auto Resume %s or newer "
                              "(schema %d)." % (path, found, MINIMUM_PRODUCT, SCHEMA))
            present = {row[1] for row in db.execute("PRAGMA table_info(interruptions)")}
            missing = [name for name in COLUMNS if name not in present]
            if missing:
                raise Refused("%s does not hold the records this reporter reads (missing: %s). It "
                              "needs Codex Auto Resume %s or newer." % (path, ", ".join(missing), MINIMUM_PRODUCT))
            db.row_factory = sqlite3.Row
            rows = [dict(row) for row in db.execute(
                "SELECT %s FROM interruptions WHERE history_hidden_at IS NULL" % ", ".join(COLUMNS))]
            hidden = db.execute("SELECT count(*) FROM interruptions "
                                "WHERE history_hidden_at IS NOT NULL").fetchone()[0]
    except sqlite3.Error as error:
        raise Refused("%s could not be read: %s" % (path, error))
    return [row for row in rows if _moment(row["detected_at"])], hidden


def newest_history():
    """Codex names its history database with a schema generation - thread_history_9, _10.

    The product reads the newest generation and never falls back to an older one, whose
    contents can be stale; the number is compared as a number, so _10 beats _9.
    """
    found = [(int(match.group(1)), path) for path in CODEX.glob("thread_history_*.sqlite")
             for match in [re.fullmatch(r"thread_history_(\d+)\.sqlite", path.name)] if match]
    return max(found)[1] if found else None


def progress_items(thread_id, turn_id):
    """How many items of each kind the recovered turn produced: counts only, never their text.

    This is the one query that passes over the conversation: SQLite reads that turn's rows to
    count them, and only the counts come back.
    """
    history = newest_history()
    if not history or not turn_id:
        return None
    try:
        with readonly(history) as db:
            counts = dict(db.execute("SELECT item_type, count(*) FROM thread_items "
                                     "WHERE thread_id=? AND turn_id=? GROUP BY item_type",
                                     (thread_id, turn_id)).fetchall())
    except sqlite3.Error:
        return None
    return {kind: counts.get(kind, 0) for kind in PROGRESS}


# ------------------------------------------------------------------------------- the report
def build(login: str, version: str | None = None, notes: dict | None = None) -> dict:
    """What this machine can show for one engine version, as counts, states and times.

    `notes`, when given, is filled with what the report leaves out and why, for the person to read.
    """
    login = check_login(login)
    product = installed_product()
    lines = log_lines()
    current = installed_codex(lines)
    version = canonical_version(version) if version else current
    found = state_rows()
    if found is None:
        raise Refused("This machine has no recovery state yet (%s): let the watcher run first."
                      % (PRODUCT / "config" / "state.sqlite"))
    every, hidden = found
    timeline = engine_timeline(lines)

    rows, elsewhere, unplaced = [], 0, collections.Counter()
    for row in every:
        placed, why = placement(timeline, *span(row), current)
        if placed == version:
            rows.append(row)
        elif placed:
            elsewhere += 1
        else:
            unplaced[why] += 1
    rows.sort(key=lambda row: _moment(row["detected_at"]))
    if notes is not None:
        notes.update(hidden=hidden, elsewhere=elsewhere, unplaced=dict(unplaced))
    if len(rows) > MAX_RECORDS:
        raise Refused("This machine has %d records on %s, and a report holds at most %d. Nothing was "
                      "written." % (len(rows), version, MAX_RECORDS))

    reports = [(when, text) for when, text in lines if passes_checks(text, version)]
    checked = set(GATE) if reports else set()
    watcher = watcher_report()
    engine = _dict(watcher.get("engine"))
    if version == current and engine.get("version", version) in (version, version[len("codex-cli "):]):
        # Only the ten capabilities a report may name: the watcher judges sixteen, and a name
        # outside these would get the whole report refused on arrival.
        checked |= {name for name, capability in _dict(watcher.get("capabilities")).items()
                    if name in EXERCISED and isinstance(capability, dict)
                    and capability.get("reason") in LOCAL_PASS_REASONS}

    capabilities = {}
    for name, judge in EXERCISED.items():
        verdicts = [judge(row) for row in rows]
        last = max((_moment(row["outcome_at"]) or _moment(row["detected_at"])
                    for row, verdict in zip(rows, verdicts) if verdict), default=None)
        capabilities[name] = {"confirmed": verdicts.count(True), "missed": verdicts.count(False),
                              "last_confirmed": iso(last) if last else None}
    delivered = any(_delivered(row) and row["state"] in OUTCOMES for row in rows)
    for name in sorted(capabilities):
        entry = capabilities[name]
        if delivered and entry["confirmed"] and not entry["missed"]:
            entry["level"] = "VERIFIED"
        elif name in checked:
            entry["level"] = "CHECKED"
        else:
            entry["level"] = None
    # A recovery that did not clear the gate verifies nothing, exactly as the maintainer's tool has it.
    if delivered and not all(capabilities[name]["level"] == "VERIFIED" for name in GATE):
        for name, entry in capabilities.items():
            if entry["level"] == "VERIFIED":
                entry["level"] = "CHECKED" if name in checked else None
    levels = [entry["level"] for entry in capabilities.values() if entry["level"]]

    return {
        "format": FORMAT,
        "codex_version": version,
        "verdict": "PASS" if "VERIFIED" in levels else ("CHECKED" if levels else "NONE"),
        "recorded_at": iso(time.time()),
        "recorded_by": "codex-compat-reporter %s, on a contributor's Windows machine" % __version__,
        "reporter": {"github_login": login, "tool": "codex-compat-reporter", "tool_version": __version__,
                     "product_version": product, "windows": platform.version()},
        "attribution": {
            "rule": ("a record counts for this version only when the product's engine reports before and after "
                     "it - or the version installed now - name this version and no other"),
            "window": None,
            "basis": None,
        },
        "local_checks": {"reports": len(reports),
                         "first": iso(reports[0][0]) if reports else None,
                         "last": iso(reports[-1][0]) if reports else None,
                         "covers": sorted(checked)},
        "records": [{
            "detected_at": iso(_moment(row["detected_at"])),
            "delivered_at": iso(_moment(row["resumed_at"])) if _moment(row["resumed_at"]) else None,
            "outcome_at": iso(_moment(row["outcome_at"])) if _moment(row["outcome_at"]) else None,
            "category": known(row["category"], CATEGORIES), "state": known(row["state"], STATES),
            "reason": known(row["last_error"], REASONS),
            "turn_status": known(row["recovery_turn_status"], TURN_STATUSES),
            "gates_passed": sum(1 for gate in _gates(row).values()
                                if isinstance(gate, list) and gate and gate[0] == "PASS"),
            "progress_items": progress_items(row["thread_id"], row["recovery_turn_id"]),
        } for row in rows],
        "capabilities": {name: capabilities[name] for name in sorted(capabilities)},
        "note": "Content-free: counts, states and times from this machine's own records, with no conversation "
                "text, identifiers or paths, counted only towards the Reported grade beside the version and "
                "never towards a version's tier.",
    }


def encode(report: dict) -> bytes:
    return (json.dumps(report, indent=2, ensure_ascii=True) + "\n").encode("ascii")


# ---------------------------------------------------------------- the receiving side's rules
# The whole of what a report may contain, as codex-compat-admin checks it on arrival (its
# inspect()). A report this tool writes or sends is held to the same rules first, so a refusal
# happens here, on the sender's machine, before anything is public.
TOP_KEYS = {"format", "codex_version", "verdict", "recorded_at", "recorded_by", "reporter",
            "attribution", "local_checks", "records", "capabilities", "note"}
REPORTER_KEYS = {"github_login", "tool", "tool_version", "product_version", "windows"}
RECORD_KEYS = {"detected_at", "delivered_at", "outcome_at", "category", "state", "reason",
               "turn_status", "gates_passed", "progress_items"}
CAPABILITY_KEYS = {"confirmed", "missed", "last_confirmed", "level"}


def _when(value, field, problems, allow_none=True):
    if value is None:
        if not allow_none:
            problems.append("%s is missing" % field)
        return None
    try:
        return dt.datetime.strptime(value, TIME).replace(tzinfo=dt.timezone.utc).timestamp()
    except (TypeError, ValueError):
        problems.append("%s is not a UTC time like 2026-09-22T17:27:30Z" % field)
        return None


def _count(value, field, problems, limit=10 ** 6):
    if not isinstance(value, int) or isinstance(value, bool) or not 0 <= value <= limit:
        problems.append("%s is not a count" % field)
        return 0
    return value


def validate(raw: bytes):
    """(report, problems): the file read as the untrusted document the project will read it as."""
    problems = []
    if len(raw) > MAX_BYTES:
        return None, ["the file is larger than 1 MB"]
    try:
        report = json.loads(raw.decode("utf-8"))
    except (ValueError, UnicodeDecodeError) as error:
        return None, ["not readable as UTF-8 JSON: %s" % error]
    if not isinstance(report, dict):
        return None, ["the file is not one JSON object"]
    missing, extra = TOP_KEYS - set(report), set(report) - TOP_KEYS
    if missing or extra:
        return report, ["keys: " + "; ".join(said for said in (
            "missing " + ", ".join(sorted(missing)) if missing else "",
            "unexpected " + ", ".join(sorted(extra)) if extra else "") if said)]
    if report["format"] != FORMAT:
        problems.append("format is not %s" % FORMAT)
    if not isinstance(report["codex_version"], str) or not VERSION.match(report["codex_version"]):
        problems.append("codex_version is not `codex-cli <version>`")
    else:
        try:
            canonical_version(report["codex_version"])
        except Refused:
            problems.append("codex_version cannot name a file and a branch")
    if not isinstance(report["verdict"], str) or report["verdict"] not in ("PASS", "CHECKED", "NONE"):
        problems.append("verdict is not PASS, CHECKED or NONE")
    written = _when(report["recorded_at"], "recorded_at", problems, allow_none=False)
    if written and written > time.time() + 86400:
        problems.append("recorded_at is in the future")

    sender = report["reporter"]
    if not isinstance(sender, dict) or set(sender) != REPORTER_KEYS:
        problems.append("reporter: its keys are not %s" % ", ".join(sorted(REPORTER_KEYS)))
        sender = {}
    login = sender.get("github_login")
    if not isinstance(login, str) or not LOGIN.match(login):
        problems.append("reporter.github_login is not a GitHub login")
    if sender.get("tool") != "codex-compat-reporter":
        problems.append("reporter.tool is not codex-compat-reporter")
    for field in ("tool_version", "product_version", "windows"):
        if not isinstance(sender.get(field), str) or not WORD.match(sender.get(field) or ""):
            problems.append("reporter.%s is not a plain version" % field)

    attribution = report["attribution"]
    if not isinstance(attribution, dict) or set(attribution) != {"rule", "window", "basis"}:
        problems.append("attribution: its keys are not rule, window, basis")
    elif attribution["basis"] is not None or attribution["window"] is not None:
        problems.append("attribution.window and .basis are for a window set by hand; a report sets neither")

    checks = report["local_checks"]
    if not isinstance(checks, dict) or set(checks) != {"reports", "first", "last", "covers"}:
        problems.append("local_checks: its keys are not reports, first, last, covers")
        checks = {"reports": 0, "first": None, "last": None, "covers": []}
    _count(checks["reports"], "local_checks.reports", problems)
    _when(checks["first"], "local_checks.first", problems)
    _when(checks["last"], "local_checks.last", problems)
    covers = checks["covers"] if isinstance(checks["covers"], list) else []
    if not isinstance(checks["covers"], list) or not all(isinstance(name, str) for name in covers) \
            or not set(covers) <= set(EXERCISED):
        problems.append("local_checks.covers names something that is not a capability")

    records = report["records"]
    if not isinstance(records, list) or len(records) > MAX_RECORDS:
        problems.append("records is not a list of at most %d" % MAX_RECORDS)
        records = []
    for number, record in enumerate(records, 1):
        where = "records[%d]" % number
        if not isinstance(record, dict) or set(record) != RECORD_KEYS:
            problems.append("%s: its keys are not %s" % (where, ", ".join(sorted(RECORD_KEYS))))
            continue
        found = _when(record["detected_at"], where + ".detected_at", problems, allow_none=False)
        delivered = _when(record["delivered_at"], where + ".delivered_at", problems)
        ended = _when(record["outcome_at"], where + ".outcome_at", problems)
        for earlier, later, names in ((found, delivered, "detected_at, delivered_at"),
                                      (found, ended, "detected_at, outcome_at")):
            if earlier and later and later < earlier:
                problems.append("%s: %s are out of order" % (where, names))
        if ended and ended > time.time() + 86400:
            problems.append("%s.outcome_at is in the future" % where)
        for field, vocabulary in (("category", CATEGORIES), ("state", STATES),
                                  ("reason", REASONS), ("turn_status", TURN_STATUSES)):
            value = record[field]
            if value is not None and (not isinstance(value, str) or value not in vocabulary | {"other"}):
                problems.append("%s.%s is not one of the product's own words" % (where, field))
        _count(record["gates_passed"], where + ".gates_passed", problems, limit=64)
        items = record["progress_items"]
        if items is not None:
            if not isinstance(items, dict) or set(items) - set(PROGRESS):
                problems.append("%s.progress_items names something the product does not count" % where)
            else:
                for kind, many in items.items():
                    _count(many, "%s.progress_items.%s" % (where, kind), problems)

    capabilities = report["capabilities"]
    if not isinstance(capabilities, dict) or not set(capabilities) <= set(EXERCISED):
        problems.append("capabilities names something that is not a capability")
        capabilities = {}
    for name, entry in sorted(capabilities.items()):
        if not isinstance(entry, dict) or set(entry) != CAPABILITY_KEYS:
            problems.append("capabilities.%s: its keys are not %s" % (name, ", ".join(sorted(CAPABILITY_KEYS))))
            continue
        confirmed = _count(entry["confirmed"], "capabilities.%s.confirmed" % name, problems, MAX_RECORDS)
        missed = _count(entry["missed"], "capabilities.%s.missed" % name, problems, MAX_RECORDS)
        _when(entry["last_confirmed"], "capabilities.%s.last_confirmed" % name, problems)
        if entry["level"] not in (None, "VERIFIED", "CHECKED"):
            problems.append("capabilities.%s.level is not VERIFIED, CHECKED or null" % name)
        if confirmed + missed > len(records):
            problems.append("capabilities.%s counts %d judgements from %d records"
                            % (name, confirmed + missed, len(records)))
    return report, problems


def time_span(report: dict) -> str:
    times = [record.get(field) for record in report["records"]
             for field in ("detected_at", "delivered_at", "outcome_at") if record.get(field)]
    return "%s to %s" % (min(times), max(times)) if times else "no records"


# ------------------------------------------------------------------------------- the commands
def check_login(login: str) -> str:
    if not login or not LOGIN.match(login):
        raise Refused("Give the GitHub login the report will be filed under: --login <your login>.")
    return login


def _unplaced_text(notes: dict) -> str:
    unplaced = notes.get("unplaced") or {}
    if not unplaced:
        return "0"
    return "%d (%s)" % (sum(unplaced.values()),
                        ", ".join("%d: %s" % (many, why) for why, many in sorted(unplaced.items())))


def cmd_status(_arguments) -> int:
    product = installed_product()
    lines = log_lines()
    engine = _dict(watcher_report().get("engine")).get("version")
    try:
        current = installed_codex(lines)
    except Refused:
        current = None
    print("installation   : %s" % PRODUCT)
    print("product version: %s" % product)
    print("engine version : %s" % (current or "not reported yet")
          + ("" if current is None or engine else " (from the log; the watcher has not written its report)"))
    try:
        found = state_rows()
    except Refused as refused:
        found = None
        print("records here   : cannot be read - %s" % refused)
    else:
        if found is None:
            print("records here   : none yet (no state database at %s)" % (PRODUCT / "config" / "state.sqlite"))
    if found is not None:
        rows, hidden = found
        timeline = engine_timeline(lines)
        on, elsewhere, unplaced = 0, 0, collections.Counter()
        for row in rows:
            placed, why = placement(timeline, *span(row), current)
            if placed and placed == current:
                on += 1
            elif placed:
                elsewhere += 1
            else:
                unplaced[why] += 1
        print("records here   : %d in all: %d on this engine version, %d on other versions, %s not placed"
              % (len(rows), on, elsewhere, _unplaced_text({"unplaced": unplaced})))
        print("hidden         : %d hidden with Clear history, which a report leaves out" % hidden)
    seen = sum(1 for _when, text in lines if current and passes_checks(text, current))
    print("local checks   : %s" % ("passed on this version (%d log lines)" % seen if seen
                                   else "not seen in the logs kept"))
    print()
    print("Write the report with:  python codex_compat_report.py report --login <your GitHub login>")
    return EXIT_OK


def write_new(target: pathlib.Path, raw: bytes, force: bool) -> None:
    """Write the report without ever replacing a file somebody may have read, unless told to."""
    if not target.parent.is_dir():
        raise Refused("The folder %s does not exist." % target.parent)
    try:
        with open(target, "wb" if force else "xb") as handle:
            handle.write(raw)
    except FileExistsError:
        raise Refused("%s already exists - it may be the file you read. Keep it and send it with "
                      "`submit`, or pass --force to write a new one over it." % target)
    except OSError as error:
        raise Refused("%s could not be written: %s" % (target, error))


def cmd_report(arguments) -> int:
    notes = {}
    report = build(arguments.login, arguments.version, notes)
    raw = encode(report)
    _parsed, problems = validate(raw)
    if problems:
        raise Refused("The report this machine would write breaks the project's rules, so it was not "
                      "written:\n  - " + "\n  - ".join(problems))
    target = pathlib.Path(arguments.out) if arguments.out else default_path(report["codex_version"])
    write_new(target, raw, arguments.force)
    print("wrote %s" % target)
    print("  version    : %s" % report["codex_version"])
    print("  verdict    : %s" % report["verdict"])
    print("  records    : %d, %s" % (len(report["records"]), time_span(report)))
    print("  left out   : %d hidden with Clear history; %d on other engine versions; %s not placed"
          % (notes["hidden"], notes["elsewhere"], _unplaced_text(notes)))
    print("  SHA-256    : %s" % hashlib.sha256(raw).hexdigest())
    print()
    print("Read it - it is yours to send or not. Then:  python codex_compat_report.py submit \"%s\"" % target)
    return EXIT_OK


# ----------------------------------------------------------------------------------- GitHub
def find_gh(path: str | None = None):
    """gh.exe from an absolute PATH entry, or None. Never the current folder: Windows would
    otherwise start a gh.exe that sits beside a downloaded script before the real one."""
    for entry in (os.environ.get("PATH", "") if path is None else path).split(os.pathsep):
        entry = entry.strip().strip('"')
        if not entry or entry == "." or not pathlib.Path(entry).is_absolute():
            continue
        candidate = pathlib.Path(entry) / "gh.exe"
        if candidate.is_file():
            return str(candidate)
    return None


def _not_found(result) -> bool:
    code, out, err = result
    return code != 0 and ("(HTTP 404)" in err or '"status":"404"' in out.replace(" ", ""))


class GitHub:
    """The GitHub CLI, started by its absolute path, pinned to github.com, never prompting."""

    def __init__(self, exe: str):
        self.exe = exe

    @classmethod
    def find(cls):
        exe = find_gh()
        if not exe:
            raise Refused("submit needs the GitHub CLI: install it from https://cli.github.com/, then run "
                          "`gh auth login --hostname github.com`, and try again. (Only gh.exe in a folder "
                          "on PATH is used, never one in the current folder.)")
        return cls(exe)

    def run(self, *arguments):
        environment = dict(os.environ, NoDefaultCurrentDirectoryInExePath="1", GH_PROMPT_DISABLED="1",
                           GH_NO_UPDATE_NOTIFIER="1")
        environment.pop("GH_HOST", None)
        environment.pop("GH_REPO", None)
        try:
            done = subprocess.run([self.exe, *arguments], capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", stdin=subprocess.DEVNULL, env=environment,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        except OSError as error:
            raise Refused("gh could not be started (%s): %s" % (self.exe, error))
        return done.returncode, (done.stdout or "").strip(), (done.stderr or "").strip()

    def api(self, method: str, endpoint: str, *more):
        return self.run("api", "--hostname", HOST, "-X", method, endpoint, *more)

    @staticmethod
    def must(result, doing: str) -> str:
        code, out, err = result
        if code:
            raise Refused("GitHub refused %s: %s" % (doing, (err or out or "gh exited %d" % code)[:800]))
        return out


def pick_file(given):
    if given:
        return pathlib.Path(given)
    found = sorted(pathlib.Path.cwd().glob("codex-cli-*.json"))
    if len(found) == 1:
        return found[0]
    raise Refused("Name the report to send: submit <FILE>. %s" % (
        "There is none in this folder; write one with `report` first." if not found else
        "This folder has %d: %s." % (len(found), ", ".join(path.name for path in found))))


def cmd_submit(arguments) -> int:
    path = pick_file(arguments.file)
    try:
        with open(path, "rb") as handle:
            raw = handle.read(MAX_BYTES + 1)          # read once; these bytes are what is sent
    except OSError as error:
        raise Refused("%s could not be read: %s. Write the report with `report` first." % (path, error))
    report, problems = validate(raw)
    if problems:
        raise Refused("%s is not a report the project would accept, so nothing was sent:\n  - %s"
                      % (path, "\n  - ".join(problems)))
    login = report["reporter"]["github_login"]
    if arguments.login and arguments.login != login:
        raise Refused("The file is filed under %s, not %s." % (login, arguments.login))
    digest = hashlib.sha256(raw).hexdigest()
    if arguments.sha256 and arguments.sha256.strip().lower() != digest:
        raise Refused("%s has changed: its SHA-256 is %s, not %s." % (path, digest, arguments.sha256))
    target, branch = destination(report["codex_version"], login)
    fork = "%s/%s" % (login, REPO.split("/")[1])

    print("file        : %s" % path)
    print("bytes       : %d, SHA-256 %s" % (len(raw), digest))
    print("report      : %s, %d records (%s), verdict %s"
          % (report["codex_version"], len(report["records"]), time_span(report), report["verdict"]))
    print("times       : published as written, UTC to the second - when the file was written, when each "
          "record was detected, delivered and ended, and the first and last local-check pass")
    print("left out    : records hidden with Clear history, when the file was written")
    print("destination : %s, pull request from %s:%s" % (REPO, login, branch))
    print("              adding %s" % target)

    github = GitHub.find()
    if github.run("auth", "status", "--hostname", HOST)[0]:
        raise Refused("gh is not signed in to github.com. Run `gh auth login --hostname github.com` "
                      "and try again.")
    who = github.must(github.api("GET", "user", "--jq", ".login"), "the question of who is signed in")
    print("gh          : %s, host %s, signed in as %s" % (github.exe, HOST, who))
    if who != login:
        raise Refused("gh is signed in as %s, so a report filed under %s cannot be sent from here."
                      % (who, login))

    door = github.api("GET", "repos/%s/contents/%s" % (REPO, COMMUNITY))
    if _not_found(door):
        print()
        print("The project is not taking reports yet: %s does not exist on %s's main." % (COMMUNITY, REPO))
        print("Nothing was sent. Keep the file, and run submit again when that folder appears.")
        return EXIT_NOT_OPEN
    github.must(door, "a look at %s" % COMMUNITY)
    filed = github.api("GET", "repos/%s/contents/%s" % (REPO, target))
    if filed[0] == 0:
        raise Refused("%s is already filed on %s. Reports are add-only: one per GitHub login per "
                      "Codex version." % (target, REPO))
    if not _not_found(filed):
        github.must(filed, "a look for an earlier report")
    listed = github.must(github.run("pr", "list", "--repo", "%s/%s" % (HOST, REPO), "--state", "open",
                                    "--head", branch, "--author", login, "--json", "url"),
                         "the list of open pull requests")
    try:
        open_ones = [entry.get("url") for entry in json.loads(listed or "[]") if isinstance(entry, dict)]
    except ValueError:
        raise Refused("gh answered the list of open pull requests with something that is not JSON.")
    if open_ones:
        raise Refused("A pull request for this report is already open: %s. One report per GitHub login "
                      "per Codex version." % ", ".join(open_ones))

    looked = github.api("GET", "repos/" + fork)
    has_fork = not _not_found(looked)
    if has_fork:
        try:
            info = _dict(json.loads(github.must(looked, "a look for your fork") or "{}"))
        except ValueError:
            info = {}
        if not info.get("fork") or _dict(info.get("parent")).get("full_name") != REPO:
            raise Refused("You have a repository named %s that is not a fork of %s, so GitHub would fork "
                          "it under another name. Rename that repository, then try again." % (fork, REPO))
    has_branch = False
    if has_fork:
        found = github.api("GET", "repos/%s/git/ref/heads/%s" % (fork, branch))
        has_branch = found[0] == 0
        if not has_branch and not _not_found(found):
            github.must(found, "a look for the branch %s" % branch)
    base = github.must(github.api("GET", "repos/%s/git/ref/heads/main" % REPO, "--jq", ".object.sha"),
                       "a look at the project's main")
    if not re.fullmatch(r"[0-9a-f]{40}", base):
        raise Refused("GitHub did not give the project's main as a commit: %r" % base[:80])

    print()
    print("With --yes this writes to GitHub, as %s:" % login)
    print("  - %s" % ("the fork %s, which exists already and is not changed otherwise" % fork if has_fork else
                      "a fork of %s under your account, %s: public, and kept until you delete it" % (REPO, fork)))
    print("  - the branch %s on it, %s the project's main" % (branch, "reset to" if has_branch else "made at"))
    print("  - one commit on that branch adding exactly the bytes above, as %s" % target)
    print("  - one public pull request on %s - a pull request cannot be unpublished" % REPO)
    if arguments.dry_run:
        print()
        print("--dry-run: nothing was written. The calls above only read from GitHub.")
        return EXIT_OK
    if not arguments.yes:
        raise Refused("Nothing was sent. Add --yes when you have read the file and want it public.")

    if not has_fork:
        made = github.must(github.api("POST", "repos/%s/forks" % REPO, "--jq", ".full_name"), "the fork")
        if made != fork:
            raise Refused("GitHub answered with the fork %s, not %s - an older fork under another name? "
                          "Nothing more was written. Rename it to %s, or delete it, and run submit again."
                          % (made, fork, fork))
        for _attempt in range(10):                      # a brand new fork takes a moment to exist
            if github.api("GET", "repos/" + fork, "--jq", ".full_name")[0] == 0:
                break
            time.sleep(3)
        else:
            raise Refused("GitHub has not finished making %s. Run submit again in a minute." % fork)
    if has_branch:
        github.must(github.api("PATCH", "repos/%s/git/refs/heads/%s" % (fork, branch),
                               "-f", "sha=" + base, "-F", "force=true"), "the branch reset")
    else:
        github.must(github.api("POST", "repos/%s/git/refs" % fork,
                               "-f", "ref=refs/heads/" + branch, "-f", "sha=" + base), "the branch")
    folder = tempfile.mkdtemp(prefix="codex-compat-report-")
    try:
        upload = os.path.join(folder, "upload.json")
        with open(upload, "w", encoding="ascii") as handle:
            json.dump({"message": "Compatibility report for %s from %s" % (report["codex_version"], login),
                       "branch": branch, "content": base64.b64encode(raw).decode("ascii")}, handle)
        github.must(github.api("PUT", "repos/%s/contents/%s" % (fork, target), "--input", upload),
                    "the file")
    finally:
        shutil.rmtree(folder, ignore_errors=True)
    url = github.must(github.run(
        "pr", "create", "--repo", "%s/%s" % (HOST, REPO), "--base", "main", "--head", "%s:%s" % (login, branch),
        "--title", "Compatibility report: %s (%s)" % (report["codex_version"], login),
        "--body", "Written by codex-compat-reporter %s from my own machine's records. Counts, states and "
                  "times only. I understand that it counts towards the Reported grade beside the version "
                  "and nothing else: it raises no version's tier and changes nothing the product allows "
                  "itself to do." % report["reporter"]["tool_version"]), "the pull request")
    print("opened:", url)
    return EXIT_OK


def _version_argument(value):
    try:
        return canonical_version(value)
    except Refused as refused:
        raise argparse.ArgumentTypeError(str(refused))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(
        prog="codex_compat_report", description="Report how Codex Auto Resume behaved on your machine.",
        epilog="Exit codes: 0 done; 1 an unexpected error; 2 refused, or a usage error; 3 the project "
               "is not taking reports yet (submit sent nothing).")
    parser.add_argument("--version", action="version", version="codex-compat-reporter " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="what this machine can show")
    status.set_defaults(run=cmd_status)
    report = commands.add_parser("report", help="write the report, for you to read")
    report.add_argument("--login", required=True, help="your GitHub login, which the report is filed under")
    report.add_argument("--codex-version", "--version", dest="version", default=None, type=_version_argument,
                        metavar="VERSION", help="the Codex version to report on (default: the one installed)")
    report.add_argument("--out", default=None, metavar="FILE",
                        help="where to write it (default: codex-cli-<version>.json in the current folder)")
    report.add_argument("--force", action="store_true", help="write over a file that is already there")
    report.set_defaults(run=cmd_report)
    submit = commands.add_parser("submit", help="send a report you have read, exactly as it is")
    submit.add_argument("file", nargs="?", default=None, metavar="FILE",
                        help="the report to send (default: the one codex-cli-*.json in the current folder)")
    submit.add_argument("--login", default=None, help="refuse unless the file is filed under this login")
    submit.add_argument("--sha256", default=None, metavar="HEX",
                        help="refuse unless the file's SHA-256 is this one, as `report` printed it")
    either = submit.add_mutually_exclusive_group()
    either.add_argument("--dry-run", action="store_true", help="check everything, say what it would write, and stop")
    either.add_argument("--yes", action="store_true", help="yes, open the public pull request")
    submit.set_defaults(run=cmd_submit)
    arguments = parser.parse_args(argv)
    try:
        if os.name != "nt":
            raise Refused("Codex Auto Resume is a Windows product, and so is this.")
        return arguments.run(arguments)
    except Refused as refused:
        print(refused, file=sys.stderr)
        return refused.exit_code


if __name__ == "__main__":
    sys.exit(main())
