"""The README's pictures of the guide: its real run, on a machine that does not exist.

    python tools/make_pictures.py            # docs/images/guide-*.png, photographed by headless Edge
    python tools/make_pictures.py --text     # print what each picture shows, and make nothing

Every line in them is printed by the guide itself, run in this process with scripted answers against
the tests' Installation fixture - a made-up installation in a temporary folder - with the login
ExampleUser, a pinned clock and a pinned Windows build. gh is played by the tests' FakeGh, and the
two windows the guide can open are not opened, so nothing is started, nothing of this machine is read
and nothing is sent. One thing is changed on the way to the picture: where things are. The temporary
folders are shown where they would be on ExampleUser's machine, and a frame that still names any other
place is refused before it is drawn.

A frame is the console as it stands at one question: the lines above it, as many as the window holds,
drawn as HTML and photographed by headless Microsoft Edge. Edge draws nothing when it is started from
Git Bash, so it is started through Windows PowerShell - and run this script from PowerShell or cmd too.
Each PNG keeps the text it shows in an iTXt chunk and no other metadata; tests/test_distribution.py
reads that text to hold every picture to the fixture's values and to what the guide prints today.

This file is not shipped: the release ZIP holds only what a reporter needs (tools/make_release.py).
"""
from __future__ import annotations

import argparse
import calendar
import contextlib
import html
import io
import os
import pathlib
import re
import struct
import subprocess
import sys
import tempfile
import zlib
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
for _path in (str(ROOT), str(ROOT / "tests")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_report as fixture  # noqa: E402 - sandboxes the homes before it imports the reporter
import codex_compat_report as reporter  # noqa: E402

LOGIN = "ExampleUser"
CLOCK = float(calendar.timegm((2026, 9, 20, 9, 0, 0)))          # 2026-09-20T09:00:00Z
WINDOWS_BUILD = "10.0.26100"
# Where the fixture's folders are shown: where they would be on ExampleUser's machine.
SHOWN_HOME = "C:\\Users\\%s" % LOGIN
SHOWN_PRODUCT = SHOWN_HOME + "\\.codex-auto-resume"
SHOWN_FOLDER = SHOWN_HOME + "\\Downloads\\codex-compat-reporter-%s" % reporter.__version__
SHOWN_GH = "C:\\Program Files\\GitHub CLI\\gh.exe"
# Every place a frame may name, and the one login.
PLACES = (SHOWN_PRODUCT, SHOWN_FOLDER, SHOWN_GH)
TITLE = "codex-compat-reporter"          # what Report.cmd's `title` puts on the window
COLUMNS, ROWS = 100, 30
KEYWORD = "codex-compat-reporter frame"  # the iTXt chunk that carries a picture's text


def records():
    """Three recoveries on this engine version, and one hidden with Clear history."""
    day = 86400
    return [fixture.record(detected_at=CLOCK - 2 * day - 3600, submitted_at=CLOCK - 2 * day - 1800,
                           resumed_at=CLOCK - 2 * day - 1800, outcome_at=CLOCK - 2 * day - 900,
                           reset_at=CLOCK - 2 * day - 1900),
            fixture.record(detected_at=CLOCK - day - 7200, submitted_at=CLOCK - day - 5400,
                           resumed_at=CLOCK - day - 5400, outcome_at=CLOCK - day - 4800,
                           reset_at=CLOCK - day - 5500),
            fixture.record(category="stream_interrupted", last_error="progress_observed",
                           detected_at=CLOCK - 5400, submitted_at=CLOCK - 5300, resumed_at=CLOCK - 5300,
                           outcome_at=CLOCK - 4700, reset_at=None, limit_type=None),
            fixture.record(detected_at=CLOCK - day, submitted_at=CLOCK - day + 60, resumed_at=CLOCK - day + 60,
                           outcome_at=CLOCK - day + 600, history_hidden_at=CLOCK - 3600)]


STOP = "\0"                              # where a question and its answer end; nothing prints it


class Console:
    """What the console shows: everything printed, and the prompts and what is typed at them, with a
    STOP after each answer so a frame can end there."""

    def __init__(self, answers):
        self.text = io.StringIO()
        self.answers = list(answers)

    def write(self, text):
        return self.text.write(text)

    def flush(self):
        pass

    def input(self, prompt):
        answer = self.answers.pop(0) if self.answers else ""
        self.text.write(prompt + answer + STOP + "\n")
        return answer


def run(answers, *, gh: bool):
    """(what the console shows, the temporary places no frame may name) for one run of the guide."""
    console = Console(answers)
    installation = fixture.Installation(records(), log_lines=[fixture.engine_line(
        CLOCK - 3 * 86400, fixture.VERSION, reporter.ENGINE_LOG_WORDS["verified"])])
    fake = fixture.FakeGh(SHOWN_GH, login=LOGIN)
    with installation, contextlib.ExitStack() as stack:
        work = installation.root / "work"
        work.mkdir()
        stack.enter_context(contextlib.chdir(work))
        for patch in (mock.patch.object(reporter.time, "time", return_value=CLOCK),
                      mock.patch.object(reporter.time, "sleep"),
                      mock.patch.object(reporter.platform, "version", return_value=WINDOWS_BUILD),
                      mock.patch.object(reporter, "find_gh", return_value=SHOWN_GH if gh else None),
                      mock.patch.object(reporter.subprocess, "run", fake),
                      mock.patch.object(reporter.subprocess, "Popen", side_effect=AssertionError("a real process")),
                      mock.patch.object(reporter, "show", return_value=True),
                      mock.patch.object(reporter, "input", console.input, create=True),
                      contextlib.redirect_stdout(console), contextlib.redirect_stderr(console)):
            stack.enter_context(patch)
        reporter.main(["guide"])
        cwd = pathlib.Path.cwd()
        places = {str(installation.home): SHOWN_PRODUCT, str(cwd): SHOWN_FOLDER, str(work): SHOWN_FOLDER}
        temporary = {str(installation.root), os.path.realpath(installation.root), tempfile.gettempdir()}
    text = console.text.getvalue()
    for place in sorted(places, key=len, reverse=True):
        text = text.replace(place, places[place])
    return text, temporary


# The four pictures: which run, and the question each one stops at.
#   1 - what this machine shows, and the login gh is signed in as, offered
#   2 - the report written, its summary and full path, and Notepad open on it
#   3 - what sending writes to GitHub, and `send` typed
#   4 - without gh: the web way, step by step, and the browser offered
PICTURES = (("guide-1-start.png", True, 0), ("guide-2-read.png", True, 2), ("guide-3-send.png", True, 3),
            ("guide-4-web.png", False, 2))
ANSWERS = {True: ["", "", "", "send"], False: [LOGIN, "n", ""]}


def frames() -> dict:
    """{file name: the rows it shows}, each row at most COLUMNS wide, as the console wraps them."""
    made, runs = {}, {}
    for gh in (True, False):
        text, temporary = run(ANSWERS[gh], gh=gh)
        refuse_elsewhere(text.replace(STOP, ""), temporary)
        runs[gh] = text.split(STOP)
    for name, gh, question in PICTURES:
        rows = []
        for line in "".join(runs[gh][:question + 1]).split("\n"):
            rows += [line[start:start + COLUMNS] for start in range(0, max(len(line), 1), COLUMNS)]
        made[name] = rows[-ROWS:]
    return made


def refuse_elsewhere(text: str, temporary=()):
    """Raise unless every place the text names is one of PLACES, and every login in it is LOGIN."""
    problems = []
    for place in temporary:
        if place and place in text:
            problems.append("a temporary folder: %s" % place)
    # The project's own address is the one other name a frame holds: it is where a report goes.
    rest = text.replace(reporter.REPO, "")
    for place in PLACES:
        rest = rest.replace(place, "")
    for found in re.finditer(r"[A-Za-z]:\\\S*|\\\\\S+", rest):
        problems.append("a place outside the fixture: %s" % found.group())
    for found in re.finditer(r"[\w.+-]+@[\w-]+\.[\w.]+", rest):
        problems.append("an e-mail address: %s" % found.group())
    for word in ("signed in here as ", "signed in as ", "GitHub login [", "request from ",
                 "community/", "GitHub, as ", "GitHub as "):
        for found in re.finditer(re.escape(word) + r"([A-Za-z0-9-]+)", rest):
            if found.group(1) != LOGIN:
                problems.append("a login other than %s: %s" % (LOGIN, found.group()))
    for name in ("USERNAME", "USERPROFILE"):
        value = os.environ.get(name) or ""
        if len(value) >= 3 and value.casefold() != LOGIN.casefold() \
                and re.search(r"(?i)(?<![\w-])%s(?![\w-])" % re.escape(value), rest):
            problems.append("this machine's %s" % name)
    if problems:
        raise SystemExit("refused: a frame names what is not the fixture's:\n  " + "\n  ".join(problems))


# ------------------------------------------------------------------------------------ drawing
PAGE = """<!doctype html>
<html><head><meta charset="utf-8"><style>
html, body {{ margin: 0; padding: 0; background: #0c0c0c; }}
.window {{ width: {width}px; height: {height}px; overflow: hidden; background: #0c0c0c;
          font-family: "Segoe UI", sans-serif; }}
.bar {{ height: 36px; background: #202020; display: flex; align-items: flex-end; }}
.tab {{ margin-left: 8px; height: 30px; padding: 0 14px 0 12px; background: #0c0c0c; color: #ffffff;
        border-radius: 6px 6px 0 0; display: flex; align-items: center; gap: 9px; font-size: 12px; }}
.icon {{ width: 16px; height: 12px; border: 1px solid #9a9a9a; border-radius: 2px; font: bold 8px Consolas, monospace;
         color: #d0d0d0; display: flex; align-items: center; padding-left: 2px; box-sizing: border-box; }}
.controls {{ margin-left: auto; align-self: stretch; display: flex; }}
.controls span {{ width: 46px; display: flex; align-items: center; justify-content: center; color: #ffffff;
                  font-size: 11px; }}
pre {{ margin: 0; padding: 6px 10px; font: 14px/18px "Cascadia Mono", Consolas, monospace; color: #cccccc;
       white-space: pre; }}
.cursor {{ display: inline-block; width: 1px; height: 16px; background: #cccccc; vertical-align: -3px; }}
</style></head><body><div class="window">
<div class="bar"><div class="tab"><span class="icon">&gt;_</span>{title}</div>
<div class="controls"><span>&#x2014;</span><span>&#x2610;</span><span>&#x2715;</span></div></div>
<pre>{rows}<span class="cursor"></span></pre>
</div></body></html>
"""
WIDTH, HEIGHT, SCALE = 844, 36 + 12 + 18 * ROWS, 2


def page(rows) -> str:
    return PAGE.format(width=WIDTH, height=HEIGHT, title=html.escape(TITLE),
                       rows=html.escape("\n".join(rows)))


def shown_text(rows) -> str:
    """The text a picture carries: its title, then its rows as they are drawn."""
    return "\n".join([TITLE] + list(rows))


def unwrapped(shown: str) -> str:
    """A picture's text with the console's wrapping undone: a row as wide as the window went on in the
    next one, so a login or a path cut in two is read whole."""
    lines = []
    for row in shown.split("\n"):
        if lines and len(lines[-1][-1]) == COLUMNS:
            lines[-1].append(row)
        else:
            lines.append([row])
    return "\n".join("".join(parts) for parts in lines)


def chunks(data: bytes):
    """[(type, body)] of a PNG, each chunk's CRC checked."""
    if data[:8] != b"\x89PNG\r\n\x1a\n":
        raise ValueError("not a PNG")
    found, at = [], 8
    while at < len(data):
        length, kind = struct.unpack(">I4s", data[at:at + 8])
        body = data[at + 8:at + 8 + length]
        (crc,) = struct.unpack(">I", data[at + 8 + length:at + 12 + length])
        if zlib.crc32(kind + body) != crc:
            raise ValueError("a %s chunk fails its CRC" % kind.decode("latin-1"))
        found.append((kind.decode("latin-1"), body))
        at += 12 + length
    return found


def chunk(kind: str, body: bytes) -> bytes:
    kind = kind.encode("latin-1")
    return struct.pack(">I4s", len(body), kind) + body + struct.pack(">I", zlib.crc32(kind + body))


def carrying(png: bytes, text: str) -> bytes:
    """The picture with its image chunks only, and the text it shows in one iTXt chunk."""
    kept = [(kind, body) for kind, body in chunks(png) if kind in ("IHDR", "PLTE", "IDAT")]
    words = KEYWORD.encode("latin-1") + b"\0\0\0" + b"\0" + b"\0" + text.encode("utf-8")
    return b"\x89PNG\r\n\x1a\n" + b"".join(chunk(kind, body) for kind, body in kept) \
        + chunk("iTXt", words) + chunk("IEND", b"")


def carried(png: bytes) -> str | None:
    """The text a picture carries, or None."""
    for kind, body in chunks(png):
        if kind == "iTXt" and body.startswith(KEYWORD.encode("latin-1") + b"\0"):
            rest = body[len(KEYWORD) + 1:]
            if rest[:2] != b"\0\0":
                raise ValueError("the text is compressed")
            _language, _translated, text = rest[2:].split(b"\0", 2)
            return text.decode("utf-8")
    return None


# Edge, started through Windows PowerShell and waited for; the paths travel as environment variables.
CAPTURE = r"""
$ErrorActionPreference = 'Stop'
$arguments = @('--headless=new', '--disable-gpu', '--hide-scrollbars', '--no-first-run',
  '--no-default-browser-check', '--disable-extensions', ('"--user-data-dir=' + $env:PICTURE_PROFILE + '"'),
  ('--force-device-scale-factor=' + $env:PICTURE_SCALE), ('--window-size=' + $env:PICTURE_SIZE),
  ('"--screenshot=' + $env:PICTURE_PNG + '"'), ('"' + $env:PICTURE_URL + '"'))
$edge = Start-Process -FilePath $env:PICTURE_EDGE -ArgumentList $arguments -PassThru -WindowStyle Hidden
$edge.WaitForExit()
"""


def find_edge() -> pathlib.Path:
    for folder in (os.environ.get("ProgramFiles(x86)"), os.environ.get("ProgramFiles")):
        if folder:
            candidate = pathlib.Path(folder) / "Microsoft" / "Edge" / "Application" / "msedge.exe"
            if candidate.is_file():
                return candidate
    raise SystemExit("Microsoft Edge was not found under Program Files.")


def photograph(edge: pathlib.Path, source: pathlib.Path, target: pathlib.Path, profile: pathlib.Path):
    windows = reporter._windows_folder()
    powershell = windows / "System32" / "WindowsPowerShell" / "v1.0" / "powershell.exe"
    environment = dict(os.environ, PICTURE_EDGE=str(edge), PICTURE_PROFILE=str(profile), PICTURE_PNG=str(target),
                       PICTURE_URL=source.as_uri(), PICTURE_SIZE="%d,%d" % (WIDTH, HEIGHT), PICTURE_SCALE=str(SCALE))
    subprocess.run([str(powershell), "-NoLogo", "-NoProfile", "-NonInteractive", "-ExecutionPolicy", "Bypass",
                    "-Command", CAPTURE], env=environment, check=True, stdin=subprocess.DEVNULL,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0), timeout=120)
    if not target.is_file():
        raise SystemExit("Edge wrote no picture for %s" % source.name)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--text", action="store_true", help="print what each picture shows, and make nothing")
    arguments = parser.parse_args(argv)
    made = frames()
    if arguments.text:
        for name, rows in made.items():
            print("=" * COLUMNS)
            print(name)
            print(shown_text(rows))
        return 0
    edge = find_edge()
    IMAGES.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="codex-compat-pictures-") as scratch:
        scratch = pathlib.Path(scratch)
        for name, rows in made.items():
            source = scratch / (name[:-len(".png")] + ".html")
            source.write_text(page(rows), encoding="utf-8")
            shot = scratch / name
            photograph(edge, source, shot, scratch / "profile")
            png = shot.read_bytes()
            width, height = struct.unpack(">II", chunks(png)[0][1][:8])
            if (width, height) != (WIDTH * SCALE, HEIGHT * SCALE):
                raise SystemExit("%s came out %dx%d, not %dx%d" % (name, width, height, WIDTH * SCALE, HEIGHT * SCALE))
            (IMAGES / name).write_bytes(carrying(png, shown_text(rows)))
            print("made %s" % (IMAGES / name).relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
