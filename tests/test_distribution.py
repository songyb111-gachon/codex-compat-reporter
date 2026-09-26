"""What the reporter ships, held to tests.

- Report.cmd starts the guide beside it with a Python found by full path only - never through the
  current folder - in UTF-8, and always waits before its window closes (ReportCmdTests).

No test here starts a process (setUpModule).

    python -m unittest discover -s tests
"""
from __future__ import annotations

import pathlib
import re
import subprocess
import sys
import unittest
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
for _path in (str(ROOT), str(HERE)):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_report as fixture  # noqa: E402 - sandboxes the homes before the reporter is imported
import codex_compat_report as reporter  # noqa: E402

CMD = ROOT / "Report.cmd"


# ---------------------------------------------------------------------------------- Report.cmd
# What cmd.exe does itself and never looks for as a file, so a planted echo.bat or goto.cmd in the
# current folder is never run by these names. A line starting with ':' is a label and runs nothing.
BUILTINS = {"@echo", "setlocal", "set", "title", "if", "goto", "call", "for", "echo", "echo.", "pause", "exit", "rem"}
CONDITION = re.compile(r'if\s+(/i\s+)?(not\s+)?(defined\s+\S+|exist\s+"[^"]*"|"[^"]*"=="[^"]*")\s+', re.I)
LOOP = re.compile(r"for\s+%%\w\s+in\s+\(.*?\)\s+do\s+", re.I)
# Where Report.cmd may find Python, in the order it looks - and the empty value it starts from.
PYTHONS = ["", r"%USERPROFILE%\.codex-auto-resume\runtime\python.exe", r"%SystemRoot%\py.exe",
           r"%LOCALAPPDATA%\Programs\Python\Launcher\py.exe", r"%ENTRY%\python.exe"]


def cmd_lines():
    return CMD.read_bytes().decode("ascii").split("\r\n")


def command_of(line: str) -> str:
    """What a line runs, with its `if` conditions and its `for ... do` taken off."""
    rest = line.strip()
    while True:
        peeled = CONDITION.match(rest) or LOOP.match(rest)
        if not peeled:
            return rest
        rest = rest[peeled.end():]


def block(label: str) -> list:
    """The lines of one labelled block, up to the next label."""
    lines = cmd_lines()
    start = lines.index(":" + label)
    rest = lines[start + 1:]
    end = next((n for n, line in enumerate(rest) if line.startswith(":")), len(rest))
    return rest[:end]


class ReportCmdTests(unittest.TestCase):
    def test_it_is_plain_ascii_with_crlf_line_endings(self):
        """cmd.exe misreads labels in a batch file with bare LF endings; .gitattributes keeps CRLF."""
        raw = CMD.read_bytes()
        raw.decode("ascii")
        self.assertTrue(raw.endswith(b"\r\n"))
        self.assertNotIn(b"\n", raw.replace(b"\r\n", b""))
        self.assertNotIn(b"\r", raw.replace(b"\r\n", b""))
        self.assertIsNone(re.search(rb"[\x00-\x08\x0b\x0c\x0e-\x1f]", raw.replace(b"\r\n", b"")))

    def test_no_command_is_resolved_through_the_current_folder(self):
        lines = cmd_lines()
        first_program = next(n for n, line in enumerate(lines) if line.startswith('"'))
        self.assertLess(lines.index('set "NoDefaultCurrentDirectoryInExePath=1"'), first_program)
        for number, line in enumerate(lines, 1):
            if not line.strip() or line.startswith(":"):
                continue
            command = command_of(line)
            first = command.split()[0].lower()
            with self.subTest("Report.cmd:%d" % number):
                if first.startswith('"%systemroot%\\') or first == '"%python%"':
                    continue
                self.assertIn(first, BUILTINS, "run by bare name: %r" % line)
                if first == "call":
                    self.assertTrue(command.split()[1].startswith(":"), "a call to anything but a label: %r" % line)

    def test_system_programs_are_named_by_their_full_path(self):
        self.assertIn('"%SystemRoot%\\System32\\chcp.com" 65001 >nul', cmd_lines())
        # `start` would open a second console, and `where` would look a program up by its name.
        for line in cmd_lines():
            if line.strip() and not line.startswith(":"):
                self.assertNotIn(command_of(line).split()[0].lower(), ("start", "where", "cmd", "cmd.exe"))

    def test_python_is_looked_for_in_four_places_in_order_and_never_taken_from_outside(self):
        lines = cmd_lines()
        values = [found.group(1) for line in lines for found in [re.search(r'set "PYTHON=([^"]*)"', line)] if found]
        self.assertEqual(values, PYTHONS)
        self.assertLess(lines.index('set "PYTHON="'), lines.index(next(l for l in lines if "set \"PYTHON=%" in l)))
        for line in lines:
            found = re.search(r'set "PYTHON=([^"]+)"', line)
            if found:
                with self.subTest(found.group(1)):
                    self.assertIn('if exist "%s"' % found.group(1), line, "set only when that very file is there")
        self.assertIn('if defined PYTHON set "PYTHON_FLAGS=-3"', lines, "the launcher is asked for Python 3")

    def test_a_path_entry_counts_only_as_a_full_path_that_is_neither_folder(self):
        look = block("look")
        for line in ('if not "%ENTRY:~1,2%"==":\\" if not "%ENTRY:~0,2%"=="\\\\" exit /b 0',
                     'if /i "%ENTRY%"=="%CURRENT%" exit /b 0', 'if /i "%ENTRY%"=="%HERE%" exit /b 0'):
            self.assertIn(line, look)
        lines = cmd_lines()
        self.assertIn('set "CURRENT=%CD%"', lines)
        self.assertIn('set "HERE=%~dp0"', lines)
        self.assertIn('if defined PATH for %%D in ("%PATH:;=" "%") do if not defined PYTHON call :look "%%~D"', lines)

    def test_it_runs_the_guide_beside_it_in_utf8_and_always_waits_before_closing(self):
        lines = cmd_lines()
        self.assertIn('set "SCRIPT=%~dp0codex_compat_report.py"', lines)
        self.assertIn('"%PYTHON%" %PYTHON_FLAGS% -X utf8 "%SCRIPT%" guide', lines)
        self.assertEqual([line for line in lines if line.strip()][-3:], ["echo.", "pause", "exit /b %EXIT_CODE%"])
        self.assertEqual(sum(1 for line in lines if line.strip().lower() == "pause"), 1)
        # Every way out goes through :finished: the only other exits return from :look.
        exits = [n for n, line in enumerate(lines) if command_of(line).lower().startswith("exit")]
        look = lines.index(":look")
        inside = range(look, look + 1 + len(block("look")))
        self.assertEqual([n for n in exits if n not in inside], [max(exits)])
        for line in block("look"):
            if command_of(line).lower().startswith("exit"):
                self.assertEqual(command_of(line), "exit /b 0")
        targets = {found.group(1) for line in lines for found in [re.search(r"goto\s+(\w+)", line)] if found}
        self.assertLessEqual(targets, {line[1:] for line in lines if line.startswith(":")})

    def test_what_it_says_when_there_is_nothing_to_run(self):
        missing = "\n".join(block("missing"))
        self.assertIn("No Python was found", missing)
        self.assertIn("%%USERPROFILE%%", missing, "the variable's name, never a user folder that could hold & or )")
        self.assertIn("Extract All", "\n".join(block("unzip")))
        self.assertIn('if "%EXIT_CODE%"=="9009" goto missing', cmd_lines(), "Windows' Store stand-in for python.exe")

    def test_the_command_it_runs_exists(self):
        code, out, _err = fixture.run_main("guide", "--help")
        self.assertEqual(code, 0)
        self.assertIn("usage: codex_compat_report guide", out)


def setUpModule():
    # No test may start a real process; platform.version() may start `ver` once, so it is asked first.
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
