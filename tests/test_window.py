"""Report.exe, the reporter's window, held to tests.

It is a front end and nothing more: every word it shows of a report, a login or a send is what
codex_compat_report.py answered through its --json interface. What it promises, and where each is held:

- it is C# 5, compiled by the compiler every Windows has, and the same sources give the same bytes
  (BuildTests);
- it finds Python where Report.cmd finds it, in Report.cmd's order and with its flags, from the folder it
  is in whatever that folder is called, and starts it with no console, no shell and nothing to read
  from, isolated and in UTF-8 (PythonTests);
- it reaches no network of its own, and opens only the project's page and a pull request on it
  (OpeningTests);
- sending takes the "I have read it" box and one more question, whose default answer is Cancel, and
  pins the SHA-256 of the bytes the window showed and the writes it listed; every character of the
  file is shown, and a refusal is at the top of its page, in view (SendTests);
- every page, at 100%, 125%, 150% and 200% and at its smallest size, shows every text whole, no control
  on another and every control named for a screen reader, in a tab order, with Back, Next and Close at
  the bottom right, Enter on the default button and Esc on Close, and no access key twice or on Send
  (PageTests);
- the pages are the guide's five steps in the guide's words, and what they show of the machine, the
  report and a send is what the script answered (WordsTests);
- the README's pictures of it show what it describes today, from the made-up machine's answers, with
  the scroll bar of a box that scrolls, and what the ZIP packs is a Report.exe of the tool's version
  (PictureTests).

Report.exe is only ever run here with --fixture: its answers are made in this process by the reporter's
own functions against the tests' made-up installation, with gh played by FakeGh, so Report.exe starts no
Python and reads nothing of this machine. A missing C# compiler skips the tests that need Report.exe on
a machine of one's own, and fails them where the CI variable is set: GitHub's Windows runners have it.

    python -m unittest discover -s tests
"""
from __future__ import annotations

import contextlib
import hashlib
import json
import os
import pathlib
import platform
import re
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
import zlib
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
for _path in (str(ROOT), str(HERE), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_report as fixture  # noqa: E402 - sandboxes the homes before the reporter is imported
import test_distribution as distribution  # noqa: E402
import codex_compat_report as reporter  # noqa: E402
import make_exe  # noqa: E402
import make_pictures  # noqa: E402
import make_release  # noqa: E402
import make_window_pictures  # noqa: E402

GUI = ROOT / "gui"
SCALES = ("1", "1.25", "1.5", "2")
SIZES = ("default", "min")
PAGES = ("1", "2", "3", "4", "5")
LONG_LOGIN = "a" + "-b" * 19                        # 39 characters, the longest login GitHub allows
PULL_REQUEST = r"^https://github\.com/songyb111-gachon/codex-auto-resume-windows/pull/[0-9]+$"


def csharp() -> str:
    return "\n".join((ROOT / source).read_text(encoding="ascii") for source in make_exe.SOURCES)


# ------------------------------------------------------------------------ reading the C#
LITERAL = re.compile(r'@"((?:[^"]|"")*)"|"((?:[^"\\]|\\.)*)"')
ESCAPES = {"n": "\n", "r": "\r", "t": "\t", "\\": "\\", '"': '"', "0": "\0"}


def literals(text: str) -> list:
    """The C# string literals in `text`, in order, as the strings they are."""
    found = []
    for match in LITERAL.finditer(text):
        verbatim, regular = match.groups()
        found.append(verbatim.replace('""', '"') if verbatim is not None
                     else re.sub(r"\\(.)", lambda escape: ESCAPES[escape.group(1)], regular))
    return found


def declared(name: str):
    """A C# constant's value: a string built of literals, or the list of an array's."""
    match = re.search(r"(const string|static readonly string\[\]) %s =\s*(.*?);" % name, csharp(), re.S)
    if not match:
        raise AssertionError("no constant %s in the C#" % name)
    return "".join(literals(match.group(2))) if match.group(1) == "const string" else literals(match.group(2))


def method(name: str, taking: str = "") -> str:
    """The body of the one C# method called `name` (whose parameters hold `taking`), braces and all."""
    source = csharp()
    heads = [match for match in re.finditer(r"\n\s+(?:[\w<>\[\]]+\s+)+%s\(([^;{]*)\)\s*\{" % name, source)
             if taking in match.group(1)]
    if len(heads) != 1:
        raise AssertionError("%d methods called %s" % (len(heads), name))
    start = depth = heads[0].end() - 1
    for at in range(start, len(source)):
        depth += {"{": 1, "}": -1}.get(source[at], 0)
        if depth == start:
            return source[heads[0].start():at + 1]
    raise AssertionError("%s never ends" % name)


# ---------------------------------------------------------------------- the fixtures
def sending(path, login, digest, writes) -> list:
    """The arguments the window sends with (Wizard.cs, SendIt): the bytes it showed and the writes it listed."""
    return (["submit", str(path), "--login", login, "--sha256", digest] + ["--write=" + write for write in writes]
            + ["--yes", "--json"])


def answers(*, gh=True, exists=False, send=True, login=fixture.LOGIN, installation=None, fake=None,
            typed=None, between=None) -> dict:
    """What the reporter answers at each step the window takes, as the window's fixture: made by its own
    --json interface, run in this process against the tests' made-up installation, gh played by FakeGh.
    `between` is called with FakeGh after the writes are listed and before they are sent."""
    made = installation or fixture.Installation([fixture.record(), fixture.record(history_hidden_at=fixture.NOW)])
    found = {}
    with made, contextlib.ExitStack() as stack:
        root = made.root
        work, folder, nowhere = root / "work", root / "bin", root / "no-gh"
        for place in (work, folder, nowhere):
            place.mkdir()
        exe = folder / "gh.exe"
        exe.write_bytes(b"not a real gh")
        stack.enter_context(contextlib.chdir(work))
        github = fixture.FakeGh(str(exe), login=login, **(fake or {}))
        stack.enter_context(mock.patch.object(reporter.subprocess, "run", github))
        stack.enter_context(mock.patch.object(reporter.time, "sleep"))
        stack.enter_context(mock.patch.dict(os.environ, {"PATH": str(folder if gh else nowhere)}))

        def ask(*argv):
            return fixture.run_json(*argv)[1]
        found["survey"] = ask("survey")
        if not found["survey"]["ok"] or found["survey"]["blocked"]:
            return found
        found["login"] = ask("login", "--", typed or login)
        if not found["login"]["ok"]:
            return found
        target = pathlib.Path(found["survey"]["report_file"]["path"])
        if exists:
            target.write_bytes(reporter.make_report(login)[1])
        found["exists"] = exists
        found["report"] = ask("report", "--login", login, "--keep", "--json")
        raw = target.read_bytes()
        found["file"] = raw.decode("utf-8")
        found["web"] = ask("web-steps", str(target), "--login", login, "--json")
        digest = hashlib.sha256(raw).hexdigest()
        if gh and found["web"]["ok"] and not found["web"]["why"]:
            found["plan"] = ask("submit", str(target), "--login", login, "--sha256", digest, "--dry-run", "--json")
            if send and found["plan"]["ok"]:
                if between:
                    between(github)
                found["sent"] = ask(*sending(target, login, digest, found["plan"]["writes"]))
    return found


FIXTURES = {}
WORK = None


def setUpModule():
    global WORK
    platform.version()                     # asked once, before gh is played by FakeGh
    WORK = tempfile.TemporaryDirectory(prefix="report-window-tests-")
    FIXTURES.update({
        "plan": answers(send=False),
        "sent": answers(),
        "web": answers(gh=False),
        "exists": answers(exists=True, send=False),
        "long": answers(login=LONG_LOGIN),
        "blocked": answers(installation=fixture.Installation(state=False)),
        "closed": answers(fake={"door": False}),
        "half": answers(fake={"answers": {("pr create",): (1, "", "gh: Validation Failed (HTTP 422)")}}),
        "typo": answers(typed="-someone"),
        "no-python": {"python": False},
        "weblong": answers(gh=False, login=LONG_LOGIN),
        # The fork appears after the writes were listed: what sending would write is not what was listed.
        "moved": answers(between=lambda github: setattr(github, "fork", True)),
    })
    changed = json.loads(json.dumps(FIXTURES["plan"]))
    changed["file"] = changed["file"].replace('"PASS"', '"NONE"')
    FIXTURES["changed"] = changed
    refused = json.loads(json.dumps(FIXTURES["plan"]))
    refused["web"] = {"ok": False, "refused": "A refusal of web-steps, as the script words one.", "exit": 2}
    FIXTURES["steprefused"] = refused
    for name, found in FIXTURES.items():
        path(name).write_text(json.dumps(found), encoding="utf-8")


def tearDownModule():
    WORK.cleanup()


def path(name: str) -> pathlib.Path:
    return pathlib.Path(WORK.name) / ("%s.json" % name)


_BUILT = {}


def report_exe() -> pathlib.Path:
    """Report.exe, built once for these tests by tools/make_exe.py."""
    if "exe" not in _BUILT:
        if make_exe.compiler() is None:
            if os.environ.get("CI"):
                raise AssertionError("the C# compiler of .NET Framework 4.8 is not on this runner")
            raise unittest.SkipTest("the C# compiler of .NET Framework 4.8 is not on this machine")
        _BUILT["exe"] = make_exe.build(pathlib.Path(WORK.name) / "build")
    return _BUILT["exe"]


def run_exe(*argv) -> subprocess.CompletedProcess:
    """Report.exe with a fixture, and with every home it could read pointed at a folder that is not there."""
    nowhere = str(pathlib.Path(WORK.name) / "nowhere")
    environment = dict(os.environ, USERPROFILE=nowhere, LOCALAPPDATA=nowhere, CODEX_AUTO_RESUME_HOME=nowhere,
                       CODEX_HOME=nowhere, GH_CONFIG_DIR=nowhere)
    return subprocess.run([str(report_exe()), *argv], capture_output=True, stdin=subprocess.DEVNULL, timeout=300,
                          env=environment, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))


_DESCRIBED = {}


def describe(name, pages=("1",), scales=("1",), sizes=("default",), *more, fixture_path=None) -> list:
    """What Report.exe --describe prints for the fixture: one description a page, scale and size. A fixture
    of this module's is described once for each question; one written by a test, every time."""
    argv = ("--fixture", str(fixture_path or path(name)), "--describe", ",".join(pages), "--scale", ",".join(scales),
            "--size", ",".join(sizes), *more)
    if fixture_path is not None or argv not in _DESCRIBED:
        done = run_exe(*argv)
        if done.returncode:
            raise AssertionError("Report.exe --describe failed (%d): %s"
                                 % (done.returncode, done.stderr.decode("utf-8", "replace")))
        _DESCRIBED[argv] = done.stdout.decode("utf-8")
    found = json.loads(_DESCRIBED[argv])
    return found if isinstance(found, list) else [found]


def control(description: dict, name: str) -> dict:
    found = [entry for entry in description["controls"] if entry["name"] == name]
    if len(found) != 1:
        raise AssertionError("%d controls called %s on page %s (%s)" % (len(found), name, description["page"],
                                                                          [entry["name"] for entry in description["controls"]]))
    return found[0]


def names(description: dict) -> list:
    return [entry["name"] for entry in description["controls"]]


def shown(text: str) -> str:
    """A text as an edit control holds it: its line breaks as CR LF."""
    return text.replace("\r\n", "\n").replace("\n", "\r\n")


def pixels(png: bytes):
    """(width, height, rows of (r, g, b)) of a PNG of 8-bit RGB, as Report.exe --render saves one."""
    found = make_pictures.chunks(png)
    width, height, depth, kind = struct.unpack(">IIBB", found[0][1][:10])
    if (depth, kind) != (8, 2):
        raise AssertionError("not 8-bit RGB: depth %d, colour type %d" % (depth, kind))
    data = zlib.decompress(b"".join(body for name, body in found if name == "IDAT"))
    stride, rows, previous, at = width * 3, [], bytearray(width * 3), 0
    for _row in range(height):
        kind, line = data[at], bytearray(data[at + 1:at + 1 + stride])
        at += 1 + stride
        for i in range(stride):
            left = line[i - 3] if i >= 3 else 0
            up, corner = previous[i], (previous[i - 3] if i >= 3 else 0)
            if kind == 1:
                line[i] = (line[i] + left) & 255
            elif kind == 2:
                line[i] = (line[i] + up) & 255
            elif kind == 3:
                line[i] = (line[i] + (left + up) // 2) & 255
            elif kind == 4:
                guess = left + up - corner
                near = min((abs(guess - left), 0, left), (abs(guess - up), 1, up), (abs(guess - corner), 2, corner))
                line[i] = (line[i] + near[2]) & 255
        rows.append([tuple(line[i:i + 3]) for i in range(0, stride, 3)])
        previous = line
    return width, height, rows


# --------------------------------------------------------------------------- the build
class BuildTests(unittest.TestCase):
    def test_it_is_c_sharp_5_compiled_by_the_compiler_every_windows_has(self):
        exe = report_exe()
        self.assertEqual(exe.read_bytes()[:2], b"MZ")
        csc = make_exe.compiler()
        self.assertEqual(csc.parts[-2:], ("v4.0.30319", "csc.exe"))
        self.assertIn(csc.parts[-3], ("Framework64", "Framework"))
        # That compiler knows no C# 6: a string interpolation is refused, so every source it took is C# 5.
        with tempfile.TemporaryDirectory() as folder:
            newer = pathlib.Path(folder) / "Newer.cs"
            newer.write_text('class Newer { static void Main() { int one = 1; System.Console.Write($"{one}"); } }',
                             encoding="ascii")
            done = subprocess.run([str(csc), "/nologo", "/out:" + str(pathlib.Path(folder) / "Newer.exe"), str(newer)],
                                  capture_output=True, stdin=subprocess.DEVNULL,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertNotEqual(done.returncode, 0)

    def test_the_same_sources_give_the_same_bytes(self):
        first = report_exe().read_bytes()
        with tempfile.TemporaryDirectory() as folder:
            again = make_exe.build(pathlib.Path(folder)).read_bytes()
        self.assertEqual(hashlib.sha256(again).hexdigest(), hashlib.sha256(first).hexdigest())

    def test_every_source_is_compiled_in_one_order_and_is_plain_ascii(self):
        self.assertEqual(sorted(make_exe.SOURCES), sorted("gui/" + source.name for source in GUI.glob("*.cs")))
        self.assertEqual(len(set(make_exe.SOURCES)), len(make_exe.SOURCES))
        for source in make_exe.SOURCES:
            with self.subTest(source):
                raw = (ROOT / source).read_bytes()
                raw.decode("ascii")
                self.assertIn(b"C# 5 only", raw, "each source says which C# it is")
        self.assertEqual(make_exe.REFERENCES, ("System.dll", "System.Core.dll", "System.Drawing.dll",
                                               "System.Windows.Forms.dll"))

    def test_report_exe_is_a_build_output_and_never_in_the_repository(self):
        self.assertIn("Report.exe", (ROOT / ".gitignore").read_text(encoding="utf-8").split())
        self.assertEqual(make_exe.NAME, "Report.exe")

    def test_the_manifest_asks_for_the_systems_own_controls_system_dpi_and_no_elevation(self):
        manifest = (GUI / "Report.manifest").read_text(encoding="utf-8")
        self.assertIn('name="Microsoft.Windows.Common-Controls" version="6.0.0.0"', manifest)
        self.assertIn('<dpiAware xmlns="http://schemas.microsoft.com/SMI/2005/WindowsSettings">true</dpiAware>',
                      manifest)
        self.assertIn('<requestedExecutionLevel level="asInvoker" uiAccess="false" />', manifest)
        self.assertIn("/win32manifest:", " ".join(re.findall(r'"(/[^"]+)', (ROOT / "tools" / "make_exe.py")
                                                             .read_text(encoding="utf-8"))))

    def test_it_targets_net_framework_4_8_so_winforms_is_not_run_as_4_0(self):
        """Without TargetFramework .NET runs a program as one for .NET 4.0, and WinForms turns off what it
        fixed since for High Contrast and screen readers (AccessibilityImprovements) and Ctrl+A in a box of
        several lines. The in-box compiler adds no TargetFramework of its own."""
        self.assertIn('[assembly: TargetFramework(".NETFramework,Version=v4.8", FrameworkDisplayName = '
                      '".NET Framework 4.8")]', make_exe.version_source())
        self.assertIn(b"\x1a.NETFramework,Version=v4.8", report_exe().read_bytes(), "the attribute, compiled in")

    def test_the_manifests_line_endings_do_not_change_the_bytes(self):
        """csc embeds the manifest byte for byte: a checkout with LF must build what one with CRLF builds."""
        built = []
        with tempfile.TemporaryDirectory() as folder:
            for ending in (b"\n", b"\r\n"):
                root = pathlib.Path(folder) / ("lf" if ending == b"\n" else "crlf")
                for name in ("gui", "tools"):
                    shutil.copytree(ROOT / name, root / name, ignore=shutil.ignore_patterns("__pycache__"))
                for name in ("LICENSE", "codex_compat_report.py"):
                    shutil.copy2(ROOT / name, root / name)
                manifest = root / make_exe.MANIFEST
                manifest.write_bytes(manifest.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", ending))
                built.append(hashlib.sha256(make_exe.build(root / "out", root).read_bytes()).hexdigest())
        self.assertEqual(built[0], built[1])
        self.assertEqual(make_exe.manifest_bytes().count(b"\n"), make_exe.manifest_bytes().count(b"\r\n"))

    def test_without_the_compiler_it_says_where_it_looked(self):
        with mock.patch.object(make_exe, "compiler", return_value=None):
            with self.assertRaises(SystemExit) as stopped:
                make_exe.build(pathlib.Path(WORK.name) / "never")
        self.assertIn("(%WINDIR%\\Microsoft.NET\\Framework64\\v4.0.30319\\csc.exe)", str(stopped.exception))
        self.assertNotIn("%%", str(stopped.exception))
        self.assertFalse((pathlib.Path(WORK.name) / "never").exists())

    def test_its_version_is_the_scripts(self):
        self.assertIn('[assembly: AssemblyInformationalVersion("%s")]' % reporter.__version__, make_exe.version_source())
        # What Explorer's Properties shows, and what the release ZIP checks before it packs Report.exe.
        self.assertEqual(make_release.product_version(report_exe().read_bytes()), reporter.__version__)
        (page,) = describe("no-python")
        self.assertEqual(control(page, "purpose")["text"],
                         "codex-compat-reporter %s: how Codex Auto Resume behaved on this machine, as a file."
                         % reporter.__version__)

    def test_normalize_pe_is_the_products_own(self):
        """Copied from Codex Auto Resume, where it builds the product's window: the same but for the
        paragraph that says so."""
        ours = (ROOT / "tools" / "normalize_pe.py").read_text(encoding="utf-8")
        self.assertIn("Copied unchanged but for this paragraph from Codex Auto Resume's build/normalize_pe.py", ours)
        theirs = fixture.PRODUCT / "build" / "normalize_pe.py"
        if theirs.is_file():
            paragraph = re.search(r"\n\nCopied unchanged.*?\n(?=\"\"\")", ours, re.S).group(0)
            self.assertEqual(ours.replace(paragraph, "\n"), theirs.read_text(encoding="utf-8"))


# ------------------------------------------------------------------------------ Python
class PythonTests(unittest.TestCase):
    def test_it_looks_where_report_cmd_looks_in_its_order_with_its_flags(self):
        places = declared("Places")
        pairs = list(zip(places[::2], places[1::2]))
        # Report.cmd: `set "PYTHON=..."` in order after the empty start, and -3 for the Python launcher.
        expected = [(place, "-3" if place.endswith("\\py.exe") else "") for place in distribution.PYTHONS[1:]]
        self.assertEqual(pairs, expected)
        self.assertEqual(distribution.PYTHONS[1:], [found.group(1) for line in distribution.cmd_lines()
                                                    for found in [re.search(r'set "PYTHON=([^"]+)"', line)] if found])
        search = method("FindPython")
        self.assertIn('Places[i].StartsWith("%ENTRY%"', search, "the PATH walk comes last, as in Report.cmd")
        self.assertIn('path.Replace("\\"", "").Split(\';\')', search, "PATH read without its quotes, as Report.cmd reads it")
        self.assertIn('entry.Substring(1, 2) == ":\\\\"', search, "a full path only: C:\\...")
        self.assertIn('entry.StartsWith("\\\\\\\\"', search, "or \\\\server\\...")
        for folder in ("currentPython", "herePython"):
            self.assertIn("seen == %s" % folder, search, "never the python.exe of the current folder or of this one")
        self.assertIn('"yyyy-MM-dd HH:mm"', method("Signature"), "the file's size and minute, as %%~zF %%~tF")

    def test_it_runs_the_script_beside_it_isolated_and_in_utf8_as_report_cmd_does(self):
        run = [line for line in distribution.cmd_lines() if line.startswith('"%PYTHON%"')]
        self.assertEqual(run, ['"%PYTHON%" %PYTHON_FLAGS% -I -X utf8 "%SCRIPT%" guide'])
        self.assertEqual(declared("Isolated"), run[0].split("%PYTHON_FLAGS% ")[1].split(' "%SCRIPT%"')[0].split())
        self.assertEqual(declared("Script"), "codex_compat_report.py")
        self.assertIn('set "SCRIPT=%~dp0codex_compat_report.py"', distribution.cmd_lines())
        self.assertIn("script = Path.Combine(here, Script);", csharp())
        self.assertIn("here = Path.GetDirectoryName(typeof(LiveCore).Assembly.Location);", csharp())
        self.assertNotIn("Application.ExecutablePath", csharp(), "a path read back from a URI, which decodes %XX")
        live = csharp().split("internal sealed class LiveCore")[1].split("internal sealed class FixtureCore")[0]
        running = live.split("public void Run(Control window")[1].split("static Answer RunPython")[0]
        self.assertLess(running.index("all.AddRange(Isolated);"), running.index("all.Add(script);"))
        self.assertLess(running.index("all.Add(script);"), running.index("all.AddRange(arguments);"))

    def test_its_own_folder_is_the_one_it_is_in_whatever_that_folder_is_called(self):
        """Report.cmd's %~dp0. In a folder called reporter%41x, Report.exe is there - not in reporterAx
        beside it, which is what a path read back from a URI would say - so it runs the script beside it,
        never one beside that other folder, and never takes the python.exe beside it from PATH."""
        base = pathlib.Path(WORK.name) / "percent"
        here, other, elsewhere, bin_ = (base / "reporter%41x", base / "reporterAx", base / "elsewhere", base / "bin")
        for folder in (here, other, elsewhere, bin_):
            folder.mkdir(parents=True)
        shutil.copy2(report_exe(), here / "Report.exe")
        (other / "codex_compat_report.py").write_text("# the wrong script\n", encoding="utf-8")
        nowhere = str(pathlib.Path(WORK.name) / "nowhere")

        def where(path, current):
            environment = dict(os.environ, USERPROFILE=nowhere, LOCALAPPDATA=nowhere, SYSTEMROOT=nowhere,
                               CODEX_AUTO_RESUME_HOME=nowhere, CODEX_HOME=nowhere, GH_CONFIG_DIR=nowhere, PATH=path)
            done = subprocess.run([str(here / "Report.exe"), "--where"], capture_output=True, cwd=str(current),
                                  stdin=subprocess.DEVNULL, timeout=120, env=environment,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.assertEqual(done.returncode, 0, done.stderr.decode("utf-8", "replace"))
            return json.loads(done.stdout.decode("utf-8"))

        found = where("", here)
        self.assertEqual((found["here"], found["script"]), (str(here), str(here / "codex_compat_report.py")))
        self.assertEqual(found["missing"], declared("NoScript"), "no script beside it, whatever is beside reporterAx")
        (here / "codex_compat_report.py").write_text("# the script\n", encoding="utf-8")
        (here / "python.exe").write_bytes(b"p" * 123)                # planted beside Report.exe
        (bin_ / "python.exe").write_bytes(b"p" * 77)                 # a Python on PATH, in a folder of its own
        found = where(str(here), elsewhere)
        self.assertEqual((found["python"], found["missing"]), (None, declared("NoPython")))
        found = where("%s;%s" % (here, bin_), elsewhere)
        self.assertEqual((found["python"], found["flags"], found["missing"]), (str(bin_ / "python.exe"), "", None))

    def test_every_start_of_python_has_no_console_no_shell_and_nothing_to_read(self):
        source = csharp()
        starts = [match.start() for match in re.finditer(r"Process\.Start\(", source)]
        self.assertEqual(len(starts), 3)
        self.assertEqual(len(re.findall(r"new ProcessStartInfo\(", source)), 3)
        python = method("RunPython")
        for setting in ("start.UseShellExecute = false;", "start.CreateNoWindow = true;",
                        "start.RedirectStandardInput = true;", "process.StandardInput.Close();",
                        "start.StandardOutputEncoding = new UTF8Encoding(false);",
                        "start.StandardErrorEncoding = new UTF8Encoding(false);", "Process.Start(start)"):
            self.assertIn(setting, python)
        self.assertNotIn("UseShellExecute = true", python)
        # The other two open what the person asked for: Notepad by its full path, and a checked address.
        notepad = method("OpenInNotepad")
        self.assertIn('Path.Combine(windows, "System32", "notepad.exe")', notepad)
        self.assertIn("Environment.GetFolderPath(Environment.SpecialFolder.Windows)", notepad)
        self.assertIn("notepad.UseShellExecute = false;", notepad)
        browser = method("OpenAddress")
        self.assertIn("if (unattended || !(IsPullRequest(address) || address == ProjectPage))", browser)
        self.assertLess(browser.index("IsPullRequest(address)"), browser.index("Process.Start"))
        self.assertEqual(sum(part.count("Process.Start(") for part in (python, notepad, browser)), 3)

    def test_the_command_line_is_quoted_as_the_c_runtime_reads_it(self):
        quoting = method("Quote", "string argument")
        self.assertIn("quoted.Append('\\\\', slashes * 2 + 1).Append('\"');", quoting)
        self.assertIn("return quoted.Append('\\\\', slashes * 2).Append('\"').ToString();", quoting)
        self.assertIn('"login", "--", typed ?? ""', csharp(), "a login typed with a leading - is not an option")

    def test_without_python_it_says_what_report_cmd_says(self):
        def said(label):
            return [line[len("echo "):].replace("%%", "%").replace("Report.cmd", "Report.exe")
                    for line in distribution.block(label) if line.startswith("echo ")]
        self.assertEqual(declared("NoPython").split("\n"), said("missing"))
        self.assertEqual(declared("NoScript").split("\n"), said("unzip"))
        self.assertIn("9009", method("RunPython") + csharp().split("StoreStandIn = ")[1][:8])
        (page,) = describe("no-python")
        self.assertEqual(control(page, "missing")["text"], shown(declared("NoPython")))
        self.assertFalse(control(page, "next")["enabled"])


# --------------------------------------------------------------------- what it opens
class OpeningTests(unittest.TestCase):
    def test_it_reaches_no_network_of_its_own(self):
        source = csharp()
        for word in ("System.Net", "WebClient", "HttpClient", "WebRequest", "Socket", "TcpClient", "Dns.",
                     "WebBrowser", "DllImport(\"ws2_32", "wininet", "winhttp"):
            self.assertNotIn(word, source)
        self.assertEqual(re.findall(r'DllImport\("([^"]+)"\)', source), ["user32.dll"], "one: SendMessage")

    def test_it_opens_only_the_projects_page_and_a_pull_request_on_it(self):
        self.assertEqual(declared("PullRequest"), PULL_REQUEST)
        self.assertEqual(declared("ProjectPage"), reporter.PROJECT_PAGE)
        self.assertIn("github.com/%s/pull/" % reporter.REPO, declared("PullRequest").replace("\\.", "."))
        self.assertIn("return found.Success && found.Value == address;", method("IsPullRequest"))

    def test_only_an_address_of_a_pull_request_on_the_project_is_a_link(self):
        good = FIXTURES["sent"]["sent"]["url"]
        self.assertRegex(good, PULL_REQUEST)
        for address, link in ((good, True), (good + "\n", False), (good + "/files", False), (good + "#x", False),
                              (good.replace("songyb111-gachon/", "someone/"), False),
                              (good.replace("https:", "http:"), False),
                              (good.replace("github.com", "github.com.example.net"), False),
                              (good[:-1] + "\u0667", False), ("javascript:alert(1)", False)):
            with self.subTest(address):
                changed = json.loads(json.dumps(FIXTURES["sent"]))
                changed["sent"]["url"] = address
                where = pathlib.Path(WORK.name) / "address.json"
                where.write_text(json.dumps(changed), encoding="utf-8")
                (page,) = describe(None, ("5",), fixture_path=where)
                self.assertEqual(page["state"], "sent")
                self.assertEqual(control(page, "pull_request")["type"], "LinkLabel" if link else "TextArea")

    def test_the_web_page_links_the_projects_page_only(self):
        (page,) = describe("web", ("5",))
        self.assertEqual(page["state"], "web")
        self.assertEqual(control(page, "project_page")["type"], "LinkLabel")
        changed = json.loads(json.dumps(FIXTURES["web"]))
        changed["web"]["project_page"] = "https://example.net/"
        where = pathlib.Path(WORK.name) / "elsewhere.json"
        where.write_text(json.dumps(changed), encoding="utf-8")
        (page,) = describe(None, ("5",), fixture_path=where)
        self.assertNotIn("project_page", names(page))


# ------------------------------------------------------------------------------ sending
class SendTests(unittest.TestCase):
    def test_send_waits_for_i_have_read_it(self):
        (page,) = describe("plan", ("5",))
        self.assertEqual((page["at"], page["state"]), (5, "plan"))
        self.assertEqual((control(page, "have_read")["checked"], control(page, "send")["enabled"]), (False, False))
        self.assertEqual(page["accept"], "send")
        (page,) = describe("plan", ("5",), ("1",), ("default",), "--have-read")
        self.assertEqual((control(page, "have_read")["checked"], control(page, "send")["enabled"]), (True, True))
        self.assertIn("if (busy || plan == null || !haveRead)", method("SendIt"))

    def test_one_more_question_names_where_as_whom_and_what_and_its_default_is_cancel(self):
        (page,) = describe("plan", ("confirm",))
        self.assertEqual((page["accept"], page["cancel"], page["focus"]), ("cancel", "cancel", "cancel"))
        digest = hashlib.sha256(FIXTURES["plan"]["file"].encode("utf-8")).hexdigest()
        self.assertEqual(control(page, "details")["text"],
                         shown("Repository: %s\nLogin: %s\nSHA-256 of what is sent:\n%s" % (reporter.REPO, fixture.LOGIN,
                                                                                            digest)))
        self.assertLess(control(page, "send")["bounds"][0], control(page, "cancel")["bounds"][0])
        confirm = method("ConfirmForm")
        for line in ("AcceptButton = Cancel;", "CancelButton = Cancel;", "ActiveControl = Cancel;",
                     "Send.DialogResult = DialogResult.OK;", "Cancel.DialogResult = DialogResult.Cancel;"):
            self.assertIn(line, confirm)
        sending = method("SendIt")
        self.assertLess(sending.index("confirm.ShowDialog(this) != DialogResult.OK"), sending.index('"--yes"'))

    def test_what_is_sent_is_pinned_to_the_sha256_of_what_was_shown_and_the_writes_listed(self):
        self.assertEqual((GUI / "Wizard.cs").read_text(encoding="ascii").count('"--yes"'), 1)
        self.assertIn('"submit", report.Str("path"), "--login", login, "--sha256", shownSha, "--dry-run", "--json"',
                      method("ToSend"))
        sent = FIXTURES["sent"]
        (page,) = describe("sent", ("5",))
        digest = hashlib.sha256(sent["file"].encode("utf-8")).hexdigest()
        path = sent["report"]["path"]
        self.assertEqual(page["asked"][-2:], [
            ["submit", path, "--login", fixture.LOGIN, "--sha256", digest, "--dry-run", "--json"],
            sending(path, fixture.LOGIN, digest, sent["plan"]["writes"])])
        self.assertEqual(len(sent["plan"]["writes"]), 4)
        self.assertIn('else if (answer.Fields.Str("sha256") != shownSha)', method("CheckShown"))
        self.assertIn("shownSha = Sha256(shown);", method("ReadShown"))
        (page,) = describe("plan", ("4",))
        digest = hashlib.sha256(FIXTURES["plan"]["file"].encode("utf-8")).hexdigest()
        self.assertEqual(control(page, "sha256")["text"], "SHA-256 of what is shown: " + digest)
        self.assertEqual(control(page, "file")["text"], shown(FIXTURES["plan"]["file"]), "the whole file")
        self.assertNotIn("changed", names(page))

    def test_what_page_5_listed_is_what_send_writes_or_nothing(self):
        """The fork appeared after page 5 listed the writes: the script refuses, as the guide does, and the
        window drops the list - Send goes with it - so what it sends next is listed and read again."""
        moved = FIXTURES["moved"]
        self.assertEqual((moved["plan"]["fork_exists"], moved["sent"]),
                         (False, {"ok": False, "refused": reporter.CHANGED, "exit": 2}))
        for page in describe("moved", ("5",), SCALES, SIZES):
            with self.subTest(scale=page["scale"], size=page["size"]):
                self.assertEqual((page["at"], page["state"]), (5, "refused"))
                self.assertEqual(control(page, "refused")["text"], reporter.CHANGED)
                self.assertEqual(control(page, "stays")["text"], declared("Unsent"))
                self.assertEqual(control(page, "again")["text"], declared("Again"))
                for gone in ("checked", "writes", "have_read", "send"):
                    self.assertNotIn(gone, names(page))
                self.assertTrue(control(page, "back")["enabled"])

    def test_a_refusal_is_at_the_top_of_its_page_in_view_with_the_focus(self):
        for name, number, why in (("half", "5", "refused"), ("closed", "5", "refused"), ("moved", "5", "refused"),
                                  ("changed", "5", "mismatch"), ("steprefused", "5", "refused")):
            for page in describe(name, (number,), SCALES, SIZES):
                with self.subTest(name, scale=page["scale"], size=page["size"]):
                    self.assertEqual(page["focus"], why)
                    self.assertEqual(names(page)[:3], ["title", "page", why], "the page's first row")
                    self.assertIsNotNone(control(page, why)["visible"])
                    if page["at"] == 5:
                        for row in ("stays", "path"):
                            self.assertIsNotNone(control(page, row)["visible"], row)
        (page,) = describe("half", ("5",))
        self.assertNotIn("have_read", names(page), "a send refused half-way leaves no Send to press again")

    def test_a_file_changed_after_it_was_written_is_said_so(self):
        (page,) = describe("changed", ("4",))
        self.assertEqual(control(page, "changed")["text"], declared("Changed"))
        (page,) = describe("changed", ("5",))
        self.assertEqual((page["at"], control(page, "mismatch")["text"]), (4, shown(declared("Mismatch"))),
                         "the script read other bytes than the window showed: nothing goes on")
        self.assertIn("It is shown again below", declared("Mismatch"), "and it is above the file")

    def test_every_character_the_reporter_does_not_write_is_shown(self):
        """The report is printable ASCII: anything else in the file is an edit, and an edit control draws
        some of it as nothing - a zero-width space, a byte order mark, a turn of the text's direction.
        Each is shown as a Unicode picture or as U+XXXX in guillemets, never as itself."""
        hidden = ("\u0085", "\u200b", "\u200c", "\u200d", "\ufeff", "\u202a", "\u202e", "\u2060", "\u00ad",
                  "\u2066", "\u180e", "\U000e0041", "\u00e9", "\u00ab", "\u2400", "\x00", "\x1b", "\x7f", "\r")
        pictured = {"\x00": "\u2400", "\x1b": "\u241b", "\x7f": "\u2421", "\r": "\u240d"}
        edited = json.loads(json.dumps(FIXTURES["plan"]))
        edited["file"] = edited["file"].replace('"PASS"', '"PA%sSS"' % "".join(hidden), 1)
        where = pathlib.Path(WORK.name) / "hidden.json"
        where.write_text(json.dumps(edited), encoding="utf-8")
        (page,) = describe(None, ("4",), fixture_path=where)
        expected = '"PA%sSS"' % "".join(pictured.get(c, "\u00abU+%04X\u00bb" % ord(c)) for c in hidden)
        self.assertEqual(control(page, "file")["text"], shown(FIXTURES["plan"]["file"].replace('"PASS"', expected, 1)))
        self.assertEqual(control(page, "sha256")["text"], "SHA-256 of what is shown: "
                         + hashlib.sha256(edited["file"].encode("utf-8")).hexdigest())

    def test_the_ready_page_says_that_closing_sends_nothing_and_where_the_file_stays(self):
        (page,) = describe("plan", ("5",))
        rows = names(page)
        self.assertEqual(rows[rows.index("have_read"):rows.index("have_read") + 3], ["have_read", "if_closed", "path"])
        self.assertEqual(control(page, "if_closed")["text"], declared("IfClosed"))
        self.assertIn("yours to send or delete", declared("IfClosed"), "the guide's words when nothing is sent")
        self.assertEqual(control(page, "path")["text"], FIXTURES["plan"]["report"]["path"])

    def test_the_pull_request_and_what_happens_next(self):
        (page,) = describe("sent", ("5",))
        self.assertEqual(page["state"], "sent")
        self.assertEqual(control(page, "pull_request")["text"], FIXTURES["sent"]["sent"]["url"])
        self.assertEqual(control(page, "after")["text"], reporter.AFTER_SUBMIT)
        self.assertEqual((control(page, "back")["enabled"], page["accept"]), (False, "close"))
        self.assertNotIn("send", [entry["name"] for entry in page["controls"] if entry["enabled"]])

    def test_a_refusal_is_the_scripts_sentence_on_the_page(self):
        (page,) = describe("closed", ("5",))
        self.assertEqual(control(page, "refused")["text"], shown("\n".join(reporter.NOT_OPEN)))
        self.assertEqual(control(page, "stays")["text"], declared("Stays"))
        (page,) = describe("half", ("5",))
        self.assertEqual(control(page, "refused")["text"], shown(FIXTURES["half"]["sent"]["refused"]))
        self.assertIn("Already written to GitHub by this run", control(page, "refused")["text"])
        self.assertEqual(control(page, "stays")["text"], declared("Stays"))
        (page,) = describe("typo", ("3",))
        self.assertEqual((page["at"], control(page, "refused")["text"]), (2, FIXTURES["typo"]["login"]["refused"]))
        self.assertEqual(control(page, "login")["text"], FIXTURES["plan"]["login"]["login"],
                         "the box holds what gh is signed in as until something else is typed")
        (page,) = describe("blocked", ("2",))
        self.assertEqual((page["at"], control(page, "blocked")["text"]), (1, FIXTURES["blocked"]["survey"]["blocked"]))
        self.assertFalse(control(page, "next")["enabled"])

    def test_the_web_steps_are_the_scripts_with_each_value_to_copy(self):
        (page,) = describe("web", ("5",))
        web = FIXTURES["web"]["web"]
        self.assertEqual(control(page, "why1")["text"], web["why"][0])
        self.assertEqual((control(page, "stays_here")["text"], control(page, "intro")["text"], control(page, "then")["text"]),
                         (web["stays"], web["intro"], web["then"]))
        self.assertEqual(control(page, "path")["text"], web["file"])
        for number, step in enumerate(web["steps"], 1):
            self.assertEqual(control(page, "step%d" % number)["text"], "%d. %s" % (number, step["text"]))
            if step["copy"]:
                self.assertEqual(control(page, "copy%d_value" % number)["text"], step["copy"])
                self.assertEqual(control(page, "copy%d_copy" % number)["text"], "Copy")
            else:
                self.assertNotIn("copy%d" % number, names(page))
        self.assertNotIn("send", [entry["name"] for entry in page["controls"]])


# -------------------------------------------------------------------------------- pages
def overlapping(description: dict) -> list:
    leaves = [entry for entry in description["controls"] if not entry["container"] and entry["visible"]]
    found = []
    for number, one in enumerate(leaves):
        for other in leaves[number + 1:]:
            x1, y1, w1, h1 = one["visible"]
            x2, y2, w2, h2 = other["visible"]
            if x1 < x2 + w2 and x2 < x1 + w1 and y1 < y2 + h2 and y2 < y1 + h1:
                found.append((one["name"], other["name"]))
    return found


# Each fixture, and the pages where it shows something the others do not.
SHOWN = {"plan": PAGES, "long": PAGES, "sent": ("5",), "web": ("5",), "exists": ("3", "4"), "closed": ("5",),
         "half": ("5",), "blocked": ("1",), "typo": ("2",), "no-python": ("1",), "weblong": ("5",), "moved": ("5",),
         "changed": ("5",), "steprefused": ("5",)}


class PageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.described = {name: describe(name, pages, SCALES, SIZES) for name, pages in SHOWN.items()}
        cls.described["confirm"] = describe("plan", ("confirm",), SCALES, SIZES)

    def every(self):
        for name, descriptions in self.described.items():
            for description in descriptions:
                yield "%s page %s (%s) at %s, %s size" % (name, description["page"], description["state"],
                                                          description["scale"], description["size"]), description

    def test_it_reaches_every_page_and_state(self):
        reached = {(name, entry["at"], entry["state"]) for name, entries in self.described.items() for entry in entries}
        for expected in (("plan", 1, "page"), ("plan", 2, "page"), ("plan", 3, "page"), ("plan", 4, "page"),
                         ("plan", 5, "plan"), ("sent", 5, "sent"), ("web", 5, "web"), ("exists", 3, "asking"),
                         ("closed", 5, "refused"), ("half", 5, "refused"), ("long", 5, "sent"), ("confirm", 5, "confirm")):
            self.assertIn(expected, reached)

    def test_every_text_is_whole_at_every_scale_and_size(self):
        for where, description in self.every():
            for entry in description["controls"]:
                with self.subTest(where, control=entry["name"]):
                    self.assertTrue(entry["fits"], "%s: %s in %s" % (entry["text"][:60], entry["preferred"], entry["bounds"]))

    def test_a_path_and_a_value_to_type_are_shown_whole_however_long(self):
        """One line of an edit control runs off its side: a path (at the smallest size, or a long one) and
        the file name to type on GitHub (with a 39-character login) break where the line ends instead."""
        for name, page, rows in (("plan", "4", ("path",)), ("plan", "5", ("path",)),
                                 ("weblong", "5", ("path", "copy2_value", "copy3_value"))):
            for description in self.described[name]:
                if description["page"] != page:
                    continue
                for row in rows:
                    with self.subTest(name, page=page, row=row, scale=description["scale"], size=description["size"]):
                        entry = control(description, row)
                        self.assertEqual((entry["type"], entry["fits"]), ("TextArea", True))
        (page,) = describe("weblong", ("5",), ("1",), ("default",))
        self.assertIn("/%s/" % LONG_LOGIN, control(page, "copy3_value")["text"])
        self.assertGreater(control(page, "copy3_value")["bounds"][3], control(page, "copy2_value")["bounds"][3],
                           "two lines")

    def test_no_control_lies_on_another(self):
        for where, description in self.every():
            with self.subTest(where):
                self.assertEqual(overlapping(description), [])

    def test_nothing_runs_off_the_side_or_below_the_buttons(self):
        for where, description in self.every():
            width, height = description["client"][2:]
            for entry in description["controls"]:
                x, y, w, h = entry["bounds"]
                with self.subTest(where, control=entry["name"]):
                    self.assertGreaterEqual(x, 0)
                    self.assertLessEqual(x + w, width, "no page is wider than the window: it never scrolls sideways")
                    if entry["visible"] is not None:
                        vx, vy, vw, vh = entry["visible"]
                        self.assertLessEqual(vy + vh, height)

    def test_no_access_key_twice_on_a_page_and_none_on_send(self):
        """While a button or a box to tick has the focus, WinForms takes an access key typed without Alt:
        two controls with one key would take it to the wrong one, and one on Send would send on a bare S."""
        for where, description in self.every():
            with self.subTest(where):
                keys = [entry["mnemonic"] for entry in description["controls"] if entry["mnemonic"]]
                self.assertEqual(len(keys), len(set(keys)), keys)
                for entry in description["controls"]:
                    if entry["name"] == "send":
                        self.assertIsNone(entry["mnemonic"])
        (page,) = describe("plan", ("4",))
        self.assertEqual({entry["name"]: entry["mnemonic"] for entry in page["controls"] if entry["mnemonic"]},
                         {"notepad": "O", "back": "B", "next": "N", "close": "C"})

    def test_every_control_is_named_for_a_screen_reader_and_has_its_place_in_the_tab_order(self):
        for where, description in self.every():
            with self.subTest(where):
                for entry in description["controls"]:
                    self.assertTrue((entry["accessible_name"] or "").strip(), entry["name"])
                    self.assertTrue(entry["name"])
                tabs = [tuple(entry["tab"]) for entry in description["controls"]]
                self.assertEqual(len(tabs), len(set(tabs)), "no two controls share a place in the tab order")
                self.assertEqual(len(names(description)), len(set(names(description))))

    def test_back_next_and_close_sit_at_the_bottom_right_with_enter_and_esc_on_them(self):
        for where, description in self.every():
            if description["page"] == "confirm":
                continue
            with self.subTest(where):
                width, height = description["client"][2:]
                # Send is there wherever what sending writes is listed, beside "I have read it".
                sends = "have_read" in names(description)
                expected = (["back", "next", "close"] if description["at"] < 5 else
                            ["back", "send", "close"] if sends else ["back", "close"])
                self.assertEqual([name for name in ("back", "next", "send", "close") if name in names(description)],
                                 expected)
                buttons = [control(description, name) for name in expected]
                xs = [entry["bounds"][0] for entry in buttons]
                self.assertEqual(xs, sorted(xs))
                close = control(description, "close")
                self.assertAlmostEqual(close["bounds"][0] + close["bounds"][2], width - round(12 * description["scale"]),
                                       delta=1)
                self.assertEqual(len({entry["bounds"][1] for entry in buttons}), 1)
                self.assertGreater(close["bounds"][1], height * 0.6)
                self.assertEqual(description["cancel"], "close")
                self.assertEqual(description["accept"], "next" if description["at"] < 5 else ("send" if sends else "close"))

    def test_the_window_scales_and_has_a_sensible_smallest_size(self):
        for where, description in self.every():
            if description["page"] == "confirm":
                continue
            with self.subTest(where):
                scale = description["scale"]
                minimum = description["minimum"][2:]
                self.assertEqual(minimum, [round(520 * scale), round(400 * scale)])
                client = description["client"][2:]
                if description["size"] == "min":
                    self.assertTrue(client[0] < minimum[0] and client[1] < minimum[1], "the frame is outside the minimum")
                else:
                    self.assertEqual(client, [description["client"][2], description["client"][3]])
                    self.assertGreater(client[0], minimum[0] - 40 * scale, "it opens larger than its smallest size")


# -------------------------------------------------------------------------------- words
def guide_steps() -> list:
    """The guide's step titles, as its source prints them: self.step(1, "what this machine can show")."""
    source = pathlib.Path(reporter.__file__).read_text(encoding="utf-8")
    return [title for _number, title in sorted(re.findall(r'self\.step\((\d), "([^"]+)"\)', source))]


class WordsTests(unittest.TestCase):
    def test_the_pages_are_the_guides_five_steps(self):
        titles = declared("Titles")
        self.assertEqual(len(guide_steps()), reporter.STEPS)
        self.assertEqual([title[0].lower() + title[1:] for title in titles], guide_steps())
        for number, page in enumerate(describe("plan", PAGES), 1):
            self.assertEqual(control(page, "title")["text"], "Step %d of 5: %s" % (number, titles[number - 1]))

    def test_what_it_shares_with_the_guide_is_the_guides_own_words(self):
        source = pathlib.Path(reporter.__file__).read_text(encoding="utf-8")
        for name in ("Purpose", "Public", "Short", "Changed", "Unsent", "Stays", "NoNotepad"):
            with self.subTest(name):
                self.assertIn(declared(name), source)

    def test_what_it_shows_of_the_machine_the_report_and_a_send_is_the_scripts(self):
        plan = FIXTURES["plan"]
        first, second, third, fourth, fifth = describe("plan", PAGES)
        self.assertEqual(control(first, "machine")["text"], shown("\n".join(plan["survey"]["lines"])))
        self.assertEqual(control(second, "login")["text"], plan["survey"]["default_login"])
        self.assertEqual(control(second, "offered")["text"],
                         declared("Offered").replace("{0}", plan["survey"]["default_login"]))
        self.assertEqual(control(third, "said")["text"], plan["report"]["said"])
        self.assertEqual(control(third, "facts")["text"], shown("\n".join(plan["report"]["lines"])))
        self.assertEqual(control(fourth, "path")["text"], plan["report"]["path"])
        self.assertEqual(control(fifth, "checked")["text"], shown("\n".join(plan["plan"]["checked"])))
        self.assertEqual(control(fifth, "sending")["text"], plan["plan"]["sending"])
        self.assertEqual(control(fifth, "writes")["text"], shown("\n".join("- " + write for write in plan["plan"]["writes"])))
        (asking,) = describe("exists", ("3",))
        self.assertEqual(control(asking, "already")["text"], FIXTURES["exists"]["survey"]["report_file"]["already"])
        self.assertEqual([(control(asking, name)["text"], control(asking, name)["checked"]) for name in ("keep", "over")],
                         [("&Keep it as it is", True), ("&Write a new one over it", False)],
                         "the guide's answer when nothing is typed: keep the file")
        (kept,) = describe("exists", ("4",))
        self.assertEqual((kept["at"], FIXTURES["exists"]["report"]["said"]), (4, reporter.KEPT))


# ------------------------------------------------------------------------------ pictures
class PictureTests(unittest.TestCase):
    """docs/images/window-*.png, made by tools/make_window_pictures.py: Report.exe's own drawing of each
    page from the made-up machine's answers. What each carries is held to what Report.exe describes of
    that page now, from those answers made again here - change a word the window shows, and this fails
    until the pictures are made again."""

    @classmethod
    def setUpClass(cls):
        cls.answered = pathlib.Path(WORK.name) / "pictures.json"
        cls.answered.write_text(json.dumps(make_window_pictures.answers()), encoding="utf-8")
        cls.described = make_window_pictures.describe(report_exe(), cls.answered)

    def test_each_picture_shows_what_report_exe_describes_today(self):
        for name, page in make_window_pictures.PICTURES:
            description = self.described[name]
            png = (ROOT / "docs" / "images" / name).read_bytes()
            with self.subTest(name):
                self.assertEqual((description["page"], description["at"]), (page, int(page)))
                self.assertEqual(make_window_pictures.carried(png), make_window_pictures.shown_text(description),
                                 "run: python tools/make_window_pictures.py")
                width, height = [int.from_bytes(make_pictures.chunks(png)[0][1][at:at + 4], "big") for at in (0, 4)]
                self.assertEqual([width, height], description["client"][2:], "the window's inside, at scale 1")

    def test_a_box_that_scrolls_has_its_scroll_bar_in_the_picture(self):
        """An edit control paints its scroll bar on the screen only: Report.exe --render draws it, so the
        picture of the fourth page says the report goes on below what the box shows."""
        description = self.described["window-4.png"]
        x, y, w, h = control(description, "file")["visible"]
        _width, _height, rows = pixels((ROOT / "docs" / "images" / "window-4.png").read_bytes())
        strip = {rows[row][column] for row in range(y + 4, y + h - 4) for column in range(x + w - 18, x + w - 4)}
        self.assertGreater(len(strip), 4, "one colour: the strip is blank")

    def test_they_show_the_five_steps_and_the_fifth_ready_to_send(self):
        self.assertEqual([page for _name, page in make_window_pictures.PICTURES], list(PAGES))
        fifth = self.described["window-5.png"]
        self.assertEqual(fifth["state"], "plan")
        self.assertEqual((control(fifth, "have_read")["checked"], control(fifth, "send")["enabled"]), (True, True))
        self.assertIsNotNone(control(fifth, "have_read")["visible"], "scrolled to its end: the box is in the picture")
        self.assertIsNotNone(control(fifth, "writes")["visible"])
        for description in self.described.values():
            self.assertEqual((description["scale"], description["size"]), (1, "default"))

    def test_the_font_and_the_end_change_where_things_are_never_what_they_say(self):
        """--font and --end are for the pictures only: the same controls, the same words and the same
        states as the page the tests above hold, in another family or scrolled."""
        plain = describe(None, PAGES, ("1",), ("default",), "--have-read", fixture_path=self.answered)
        for before, after in zip(plain, (self.described[name] for name, _page in make_window_pictures.PICTURES)):
            with self.subTest(before["page"]):
                self.assertEqual([(entry["name"], entry["text"], entry["checked"], entry["enabled"])
                                  for entry in before["controls"]],
                                 [(entry["name"], entry["text"], entry["checked"], entry["enabled"])
                                  for entry in after["controls"]])
                self.assertEqual(make_window_pictures.shown_text(before), make_window_pictures.shown_text(after))
        self.assertIsNone(control(plain[4], "have_read")["visible"], "without --end the fifth page opens at its top")
        done = run_exe("--fixture", str(self.answered), "--describe", "1", "--font", "No Such Family Anywhere")
        self.assertNotEqual(done.returncode, 0, "a family that is not installed is refused, not drawn in another")


if __name__ == "__main__":
    unittest.main()
