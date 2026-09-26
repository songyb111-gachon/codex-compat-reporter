"""The README's pictures of Report.exe: its five pages, on the made-up machine the guide's pictures show.

    python tools/make_window_pictures.py           # docs/images/window-1..5.png, drawn by Report.exe itself
    python tools/make_window_pictures.py --text    # print what each picture shows, and make nothing

What the window shows is what the reporter answers it, so the answers are made first, in this process:
the reporter's own --json interface, run against tools/make_pictures.py's made-up machine - its
installation, the login ExampleUser, its pinned clock and Windows build, and gh played by the tests'
FakeGh - with its temporary folders shown where they would be on ExampleUser's machine, and refused if
anything else is named. The two sets of pictures tell the same story, from the same values.

Report.exe, compiled from gui/ by tools/make_exe.py into a temporary folder, then draws each page off
the screen with --fixture and --render at scale 1. With --fixture it looks for no Python, starts
nothing and reads nothing of this machine: the answers above are all it knows.

Each PNG keeps the text it shows in an iTXt chunk and no other metadata: the window's title, then the
text of every control on the page in tab order, as Report.exe --describe gives them from the same
answers. tests/test_window.py describes each page again and holds the picture's text to it, and
tests/test_distribution.py holds that text to the fixture's values.

This file is not shipped: the release ZIP holds only what a reporter needs (tools/make_release.py).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import pathlib
import struct
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
IMAGES = ROOT / "docs" / "images"
for _path in (str(ROOT), str(ROOT / "tests"), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import make_pictures  # noqa: E402 - imports the tests' fixture, which sandboxes the homes first
import make_exe  # noqa: E402
import test_report as fixture  # noqa: E402

LOGIN = make_pictures.LOGIN
KEYWORD = "codex-compat-reporter window"     # the iTXt chunk that carries a picture's text
# The five pictures, a page each, at scale 1 and the size the window opens at. Each page is shown
# scrolled to its end, and "I have read it" is ticked on the fifth, so the writes listed and Send are
# there to see; the question asked before sending is not pictured, and nothing is sent. The font is
# Segoe UI, the message font of Windows as most people have it, whatever this machine's is: a Korean
# Windows' draws a backslash as a won sign.
PICTURES = (("window-1.png", "1"), ("window-2.png", "2"), ("window-3.png", "3"), ("window-4.png", "4"),
            ("window-5.png", "5"))
FLAGS = ("--scale", "1", "--size", "default", "--have-read", "--end", "--font", "Segoe UI")


def answers() -> dict:
    """What the reporter answers the window at each step, on the made-up machine, as Report.exe's
    --fixture reads it: gh signed in as ExampleUser, the report written, read and ready to send."""
    found = {}
    with make_pictures.made_up(gh=True) as (places, temporary):
        def ask(*argv):
            return fixture.run_json(*argv)[1]
        found["survey"] = ask("survey")
        found["login"] = ask("login", "--", LOGIN)
        found["exists"] = False
        found["report"] = ask("report", "--login", LOGIN, "--keep", "--json")
        target = pathlib.Path(found["report"]["path"])
        raw = target.read_bytes()
        found["file"] = raw.decode("utf-8")
        found["web"] = ask("web-steps", str(target), "--login", LOGIN, "--json")
        found["plan"] = ask("submit", str(target), "--login", LOGIN, "--sha256", hashlib.sha256(raw).hexdigest(),
                            "--dry-run", "--json")
    for name in ("survey", "login", "report", "web", "plan"):
        if not found[name].get("ok"):
            raise SystemExit("the made-up machine's %s was refused: %s" % (name, found[name].get("refused")))
    shown = placed(found, places)
    make_pictures.refuse_elsewhere("\n".join(strings(shown)), temporary)
    return shown


def placed(value, places: dict):
    """A fixture with every temporary place in its strings shown where it would be on ExampleUser's machine."""
    if isinstance(value, dict):
        return {key: placed(item, places) for key, item in value.items()}
    if isinstance(value, list):
        return [placed(item, places) for item in value]
    if isinstance(value, str):
        return make_pictures.shown_where(value, places)
    return value


def strings(value) -> list:
    """Every string in a fixture, its keys' included."""
    if isinstance(value, dict):
        return [text for key, item in value.items() for text in [key] + strings(item)]
    if isinstance(value, list):
        return [text for item in value for text in strings(item)]
    return [value] if isinstance(value, str) else []


def shown_text(description: dict) -> str:
    """The text a picture carries: the window's title, then each control's text in tab order, a box to
    tick or a choice marked [x] or [ ] as it stands, and its line breaks as LF."""
    lines = [description["title"]]
    for entry in description["controls"]:
        text = (entry["text"] or "").replace("\r\n", "\n")
        if not text:
            continue
        if entry["checked"] is not None:
            text = ("[x] " if entry["checked"] else "[ ] ") + text
        lines.append(text)
    return "\n".join(lines)


def carried(png: bytes) -> str | None:
    return make_pictures.carried(png, KEYWORD)


def unattended() -> dict:
    """Report.exe's environment: every home it could read pointed at a folder that is not there."""
    nowhere = str(pathlib.Path(tempfile.gettempdir()) / "codex-compat-window-pictures-nowhere")
    return dict(os.environ, USERPROFILE=nowhere, LOCALAPPDATA=nowhere, CODEX_AUTO_RESUME_HOME=nowhere,
                CODEX_HOME=nowhere, GH_CONFIG_DIR=nowhere)


def report_exe(exe: pathlib.Path, *argv) -> bytes:
    """What Report.exe printed, run with no console and nothing to read from; refused when it failed."""
    done = subprocess.run([str(exe), *argv], capture_output=True, stdin=subprocess.DEVNULL, timeout=300,
                          env=unattended(), creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode:
        raise SystemExit("Report.exe %s failed (%d): %s" % (" ".join(argv[2:4]), done.returncode,
                                                          done.stderr.decode("utf-8", "replace")))
    return done.stdout


def describe(exe: pathlib.Path, answered: pathlib.Path) -> dict:
    """{file name: what Report.exe --describe says of its page}, from the fixture file `answered`."""
    pages = ",".join(page for _name, page in PICTURES)
    found = json.loads(report_exe(exe, "--fixture", str(answered), "--describe", pages, *FLAGS).decode("utf-8"))
    return {name: description for (name, _page), description in zip(PICTURES, found)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--text", action="store_true", help="print what each picture shows, and make nothing")
    arguments = parser.parse_args(argv)
    made = answers()
    with tempfile.TemporaryDirectory(prefix="codex-compat-window-pictures-") as scratch:
        scratch = pathlib.Path(scratch)
        answered = scratch / "answers.json"
        answered.write_text(json.dumps(made), encoding="utf-8")
        exe = make_exe.build(scratch / "build")
        described = describe(exe, answered)
        if arguments.text:
            for name, description in described.items():
                print("=" * 100)
                print(name)
                print(shown_text(description))
            return 0
        IMAGES.mkdir(parents=True, exist_ok=True)
        for name, page in PICTURES:
            shot = scratch / name
            report_exe(exe, "--fixture", str(answered), "--render", page, "--out", str(shot), *FLAGS)
            png = shot.read_bytes()
            size = list(struct.unpack(">II", make_pictures.chunks(png)[0][1][:8]))
            if size != described[name]["client"][2:]:
                raise SystemExit("%s came out %dx%d, not the window's %dx%d" % (name, size[0], size[1],
                                                                              *described[name]["client"][2:]))
            text = shown_text(described[name])
            make_pictures.refuse_elsewhere(text, (str(scratch), tempfile.gettempdir()))
            (IMAGES / name).write_bytes(make_pictures.carrying(png, text, KEYWORD))
            print("made %s" % (IMAGES / name).relative_to(ROOT).as_posix())
    return 0


if __name__ == "__main__":
    sys.exit(main())
