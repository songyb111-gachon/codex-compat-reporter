"""codex-compat-reporter - tell the Codex Auto Resume project how it behaved on your machine.

    py codex_compat_report.py status
    py codex_compat_report.py report --login <your GitHub login> [--out FILE]
    py codex_compat_report.py submit --login <your GitHub login> [--dry-run]

What it reads, on this machine only and read-only: the product's own installation - its log, its
state database and the compatibility report its watcher writes - and, for progress counts alone,
Codex's own history database. It opens nothing for writing and changes no setting.

What it writes: one JSON file of counts, states, times and a version string. No conversation text,
no titles, no identifiers, no paths, no user name. Read it before you send it; that is the point of
its being a file.

What it cannot do: make a Codex version "verified" for anybody else. A report has a grade of its
own, Reported: it stands beside the ladder of four words - verified, checked, compatible, failed
here - and never on it, and never raises a version's tier. It is shown beside the version with the
number of machines that said the same thing, and a version whose own evidence says nothing stays
compatible however many reports arrive. The tool measures; the project recomputes every derived
field from the measurements when the report arrives, so a hand-edited conclusion does not survive.
Nothing here proves a file was not made up on the machine that sent it, and the project says so out
loud rather than pretending otherwise.
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import json
import os
import pathlib
import platform
import re
import sqlite3
import subprocess
import sys
import time

__version__ = "1.0.0"

REPO = "songyb111-gachon/codex-auto-resume-windows"
COMMUNITY = "docs/evidence/community"          # where a report goes on the product repository
FORMAT = "codex-auto-resume-compat-evidence/1"  # the maintainer's own evidence format, unchanged
HOME = pathlib.Path(os.environ.get("USERPROFILE") or pathlib.Path.home())
PRODUCT = pathlib.Path(os.environ.get("CODEX_AUTO_RESUME_HOME") or (HOME / ".codex-auto-resume"))
CODEX = pathlib.Path(os.environ.get("CODEX_HOME") or (HOME / ".codex"))

GATE = ("engine_present", "exact_thread_recovery")
PROGRESS = ("agentMessage", "commandExecution", "fileChange", "mcpToolCall")
OUTCOMES = {"recovered", "completed_no_progress", "recovery_turn_failed", "stopped_by_user", "handed_over"}
LOG_LINE = re.compile(r"^\[(\d{4}-\d\d-\d\d \d\d:\d\d:\d\d)\] (.*)$")
ENGINE = re.compile(r"engine (codex-cli \d[0-9A-Za-z.\-]*?)[\s;,)]")
CHECKS = ("accepted because `codex queue` still offers", "is compatible: its local checks pass")
LOGIN = re.compile(r"\A[A-Za-z0-9](?:[A-Za-z0-9]|-(?=[A-Za-z0-9])){0,38}\Z")

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


def known(value, vocabulary):
    """The word itself when the report is allowed to carry it, "other" when it is not."""
    if value is None:
        return None
    return value if isinstance(value, str) and value in vocabulary else "other"


class Refused(SystemExit):
    """Something this tool will not guess at. The message says what to do."""


# --------------------------------------------------------------------- what one recovery shows
def _gate(row, name):
    try:
        return (json.loads(row["gate_eval"] or "{}").get(name) or [None])[0] == "PASS"
    except ValueError:
        return None


def _delivered(row):
    return bool(row["recovery_turn_id"])


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
    return dt.datetime.fromtimestamp(when, dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def full(version: str) -> str:
    version = version.strip()
    return version if version.startswith("codex-cli ") else "codex-cli " + version


@contextlib.contextmanager
def readonly(path: pathlib.Path):
    """A SQLite file opened so that nothing can be written to it, as the product opens Codex's."""
    connection = sqlite3.connect("file:%s?mode=ro" % path.as_posix().replace("?", "%3f"), uri=True)
    try:
        connection.execute("PRAGMA query_only = ON")
        yield connection
    finally:
        connection.close()


def installed_product() -> str:
    manifest = PRODUCT / "app" / ".codex-plugin" / "plugin.json"
    try:
        return str(json.loads(manifest.read_text(encoding="utf-8-sig"))["version"])
    except (OSError, ValueError, KeyError):
        raise Refused("Codex Auto Resume does not look installed at %s.\n"
                      "Install it first, or set CODEX_AUTO_RESUME_HOME to where it is." % PRODUCT)


def watcher_report() -> dict:
    """The compatibility report the watcher writes for itself - the product's own answer."""
    try:
        return json.loads((PRODUCT / "config" / "compatibility.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def installed_codex() -> str:
    """The engine version the product last reported, which is the version a report is about."""
    version = (watcher_report().get("engine") or {}).get("version")
    if version:
        return full(str(version))
    for _when, text in reversed(log_lines()):
        found = ENGINE.search(text)
        if found:
            return found.group(1)
    raise Refused("This machine has no engine version to report yet: start Codex, let the watcher "
                  "run once, and try again.")


def log_lines() -> list:
    lines = []
    for name in ("auto-resume.log.1", "auto-resume.log"):
        try:
            text = (PRODUCT / "logs" / name).read_text(encoding="utf-8", errors="replace")
        except OSError:
            continue
        for line in text.splitlines():
            found = LOG_LINE.match(line)
            if found:
                lines.append((time.mktime(time.strptime(found.group(1), "%Y-%m-%d %H:%M:%S")), found.group(2)))
    lines.sort()
    return lines


def engine_timeline(lines) -> list:
    return [(when, ENGINE.search(text).group(1)) for when, text in lines if ENGINE.search(text)]


def version_at(timeline, start, end, current) -> str | None:
    """The engine version a record belongs to: the one reported on both sides of it, and no other.

    A record that straddles an upgrade belongs to neither version, and one after the last report
    belongs to the version installed now.
    """
    before = [version for when, version in timeline if when <= start]
    after = [version for when, version in timeline if when >= end]
    if not before:
        return None
    if not after:
        return before[-1] if before[-1] == current else None
    return before[-1] if before[-1] == after[0] else None


def state_rows() -> list:
    path = PRODUCT / "config" / "state.sqlite"
    if not path.is_file():
        raise Refused("This machine has no recovery state yet (%s)." % path)
    with readonly(path) as db:
        db.row_factory = sqlite3.Row
        return [dict(row) for row in db.execute("SELECT * FROM interruptions")]


def newest_history():
    """Codex names its history database with a schema generation - thread_history_9, _10.

    The product reads the newest generation and never falls back to an older one, whose
    contents can be stale; the number is compared as a number, so _10 beats _9.
    """
    found = [(int(match.group(1)), path) for path in CODEX.glob("thread_history_*.sqlite")
             for match in [re.fullmatch(r"thread_history_(\d+)\.sqlite", path.name)] if match]
    return max(found)[1] if found else None


def progress_items(thread_id, turn_id):
    """How many items of each kind the recovered turn produced: counts only, never their text."""
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
def build(login: str, version: str | None = None) -> dict:
    """What this machine can show for one engine version, as counts, states and times."""
    product = installed_product()
    current = installed_codex()
    version = full(version) if version else current
    lines = log_lines()
    timeline = engine_timeline(lines)

    rows = [row for row in state_rows()
            if version_at(timeline, row["resumed_at"] or row["detected_at"],
                          row["outcome_at"] or row["resumed_at"] or row["detected_at"], current) == version]
    rows.sort(key=lambda row: row["detected_at"])

    reports = [(when, text) for when, text in lines if version in text and any(c in text for c in CHECKS)]
    checked = set(GATE) if reports else set()
    report = watcher_report()
    if version == current and (report.get("engine") or {}).get("version", version) in (version, version[len("codex-cli "):]):
        checked |= {name for name, capability in (report.get("capabilities") or {}).items()
                    if capability.get("reason") == "local_checks_passed"}

    capabilities = {}
    for name, judge in EXERCISED.items():
        verdicts = [judge(row) for row in rows]
        last = max((row["outcome_at"] or row["detected_at"] for row, verdict in zip(rows, verdicts) if verdict),
                   default=None)
        capabilities[name] = {"confirmed": verdicts.count(True), "missed": verdicts.count(False),
                              "last_confirmed": iso(last) if last else None}
    delivered = any(_delivered(row) and row["state"] in OUTCOMES for row in rows)
    for name in sorted(set(capabilities) | checked):
        entry = capabilities.setdefault(name, {"confirmed": 0, "missed": 0, "last_confirmed": None})
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
            "detected_at": iso(row["detected_at"]),
            "delivered_at": iso(row["resumed_at"]) if row["resumed_at"] else None,
            "outcome_at": iso(row["outcome_at"]) if row["outcome_at"] else None,
            "category": known(row["category"], CATEGORIES), "state": known(row["state"], STATES),
            "reason": known(row["last_error"], REASONS),
            "turn_status": known(row["recovery_turn_status"], TURN_STATUSES),
            "gates_passed": sum(1 for gate in json.loads(row["gate_eval"] or "{}").values()
                                if gate and gate[0] == "PASS"),
            "progress_items": progress_items(row["thread_id"], row["recovery_turn_id"]),
        } for row in rows],
        "capabilities": {name: capabilities[name] for name in sorted(capabilities)},
        "note": "Content-free: counts, states and times from this machine's own records, with no conversation "
                "text, identifiers or paths, counted only towards the Reported grade beside the version and "
                "never towards a version's tier.",
    }


def default_path(report: dict) -> pathlib.Path:
    version = report["codex_version"].replace("codex-cli ", "codex-cli-").replace(" ", "-")
    return pathlib.Path.cwd() / ("%s.json" % version)


# ------------------------------------------------------------------------------- the commands
def check_login(login: str) -> str:
    if not login or not LOGIN.match(login):
        raise Refused("Give the GitHub login the report will be filed under: --login <your login>.")
    return login


def cmd_status(_arguments) -> int:
    product = installed_product()
    report = watcher_report()
    engine = (report.get("engine") or {}).get("version") or "not reported yet"
    rows = state_rows()
    lines = log_lines()
    timeline = engine_timeline(lines)
    current = installed_codex()
    counted = [row for row in rows
               if version_at(timeline, row["resumed_at"] or row["detected_at"],
                             row["outcome_at"] or row["resumed_at"] or row["detected_at"], current) == current]
    print("installation   : %s" % PRODUCT)
    print("product version: %s" % product)
    print("engine version : %s" % engine)
    print("records here   : %d in all, %d of them on this engine version" % (len(rows), len(counted)))
    print("local checks   : %s" % ("passed on this version" if any(
        current in text and any(c in text for c in CHECKS) for _when, text in lines) else "not seen in the log yet"))
    print()
    print("Write the report with:  py codex_compat_report.py report --login <your GitHub login>")
    return 0


def cmd_report(arguments) -> int:
    report = build(check_login(arguments.login), arguments.version)
    target = pathlib.Path(arguments.out) if arguments.out else default_path(report)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %s" % target)
    print("  version   : %s" % report["codex_version"])
    print("  verdict   : %s" % report["verdict"])
    print("  records   : %d" % len(report["records"]))
    print()
    print("Read it - it is yours to send or not. Then: py codex_compat_report.py submit --login %s"
          % report["reporter"]["github_login"])
    return 0


def gh(*arguments, check=True):
    done = subprocess.run(["gh", *arguments], capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if check and done.returncode != 0:
        raise Refused((done.stderr or done.stdout or "gh failed").strip())
    return done.stdout.strip()


def accepting_reports() -> bool:
    """Whether the product repository takes reports yet: the folder they go in exists on main."""
    done = subprocess.run(["gh", "api", "repos/%s/contents/%s" % (REPO, COMMUNITY)],
                          capture_output=True, text=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return done.returncode == 0


def cmd_submit(arguments) -> int:
    login = check_login(arguments.login)
    report = build(login, arguments.version)
    target = pathlib.Path(arguments.out) if arguments.out else default_path(report)
    target.write_text(json.dumps(report, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print("wrote %s" % target)
    path = "%s/%s/%s" % (COMMUNITY, login, target.name)
    if not accepting_reports():
        print()
        print("The project is not taking reports yet: %s does not exist on %s's main." % (COMMUNITY, REPO))
        print("Keep the file. When that folder appears - planned for v0.6.10 - run submit again.")
        return 0
    print()
    print("This would open a public pull request on %s adding" % REPO)
    print("    %s" % path)
    print("with the contents of the file above - read it first; a pull request cannot be unpublished.")
    if arguments.dry_run:
        return 0
    if not arguments.yes:
        raise Refused("Add --yes when you have read the file and want it public.")

    who = gh("api", "user", "--jq", ".login")
    if who != login:
        raise Refused("gh is signed in as %s, so the report cannot be filed under %s." % (who, login))
    fork = gh("api", "-X", "POST", "repos/%s/forks" % REPO, "--jq", ".full_name")
    for _attempt in range(10):                      # a brand new fork takes a moment to exist
        if subprocess.run(["gh", "api", "repos/%s" % fork], capture_output=True,
                          creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).returncode == 0:
            break
        time.sleep(3)
    gh("repo", "sync", fork, "--source", REPO, check=False)
    head = gh("api", "repos/%s/git/ref/heads/main" % REPO, "--jq", ".object.sha")
    branch = "compat-report/%s" % target.stem
    gh("api", "-X", "POST", "repos/%s/git/refs" % fork,
       "-f", "ref=refs/heads/" + branch, "-f", "sha=" + head, check=False)
    import base64
    gh("api", "-X", "PUT", "repos/%s/contents/%s" % (fork, path),
       "-f", "message=Compatibility report for %s from %s" % (report["codex_version"], login),
       "-f", "branch=" + branch,
       "-f", "content=" + base64.b64encode(target.read_bytes()).decode("ascii"))
    url = gh("pr", "create", "--repo", REPO, "--base", "main", "--head", "%s:%s" % (login, branch),
             "--title", "Compatibility report: %s (%s)" % (report["codex_version"], login),
             "--body", "Written by codex-compat-reporter %s from my own machine's records. Counts, states and "
                       "times only. I understand that it counts towards the Reported grade beside the version "
                       "and nothing else: it raises no version's tier and changes nothing the product allows "
                       "itself to do." % __version__)
    print("opened:", url)
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="codex_compat_report",
                                     description="Report how Codex Auto Resume behaved on your machine.")
    parser.add_argument("--version", action="version", version="codex-compat-reporter " + __version__)
    commands = parser.add_subparsers(dest="command", required=True)
    status = commands.add_parser("status", help="what this machine can show")
    status.set_defaults(run=cmd_status)
    for name, run in (("report", cmd_report), ("submit", cmd_submit)):
        command = commands.add_parser(name, help="write the report" if name == "report" else "send the report")
        command.add_argument("--login", required=True, help="your GitHub login, which the report is filed under")
        command.add_argument("--version", dest="version", default=None,
                             help="the engine version to report on (default: the one installed)")
        command.add_argument("--out", default=None, help="where to write the report")
        if name == "submit":
            command.add_argument("--dry-run", action="store_true", help="say what it would open, and stop")
            command.add_argument("--yes", action="store_true", help="yes, open the pull request")
        command.set_defaults(run=run)
    arguments = parser.parse_args(argv)
    if os.name != "nt":
        raise Refused("Codex Auto Resume is a Windows product, and so is this.")
    return arguments.run(arguments)


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Refused as refused:
        print(refused, file=sys.stderr)
        sys.exit(2)
