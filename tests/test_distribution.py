"""What the reporter ships, and the pictures that show it, held to tests.

- Report.cmd starts the guide beside it with a Python found by full path only - never through the
  current folder - in UTF-8, and always waits before its window closes (ReportCmdTests);
- the release ZIP holds the six files a reporter needs and nothing else, the same bytes from the same
  tree (ReleaseZipTests); the workflow that publishes it builds from the tag alone, keeps write access
  where none of the repository's code runs, leaves no token on disk, and attests what it publishes
  (ReleaseWorkflowTests);
- every picture the READMEs show is there, carries the text it shows and nothing else, and that text
  is exactly what the guide prints today against the tests' fixture: its values, and no one else's
  (PictureTests).

YAML is read as text, as the product's tests/test_workflow_privilege.py reads it: no YAML library is
needed, and what is held is the text GitHub runs. No test here starts a process (setUpModule).

    python -m unittest discover -s tests
"""
from __future__ import annotations

import hashlib
import pathlib
import re
import subprocess
import sys
import tempfile
import time
import unittest
import zipfile
from unittest import mock

HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parent
for _path in (str(ROOT), str(HERE), str(ROOT / "tools")):
    if _path not in sys.path:
        sys.path.insert(0, _path)

import test_report as fixture  # noqa: E402 - sandboxes the homes before the reporter is imported
import codex_compat_report as reporter  # noqa: E402
import make_pictures  # noqa: E402
import make_release  # noqa: E402

CMD = ROOT / "Report.cmd"
WORKFLOW = ROOT / ".github" / "workflows" / "release.yml"
READMES = (ROOT / "README.md", ROOT / "README.ko.md")
# The product's checkout, when it sits beside this one (the maintainer's machine, or CAR_CHECKOUT).
PRODUCT = fixture.PRODUCT


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


# ----------------------------------------------------------------------------------- the ZIP
EPOCH = 1790000001


class ReleaseZipTests(unittest.TestCase):
    def build(self, folder, **keywords):
        return make_release.build(reporter.__version__, pathlib.Path(folder), keywords.pop("epoch", EPOCH), **keywords)

    def test_the_same_tree_gives_the_same_bytes(self):
        with tempfile.TemporaryDirectory() as one, tempfile.TemporaryDirectory() as two:
            first, second = self.build(one), self.build(two)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            digest = hashlib.sha256(first.read_bytes()).hexdigest()
            self.assertEqual((pathlib.Path(one) / (first.name + ".sha256")).read_bytes(),
                             ("%s  %s\n" % (digest, first.name)).encode("ascii"))
            self.assertEqual(sorted(path.name for path in pathlib.Path(one).iterdir()),
                             [first.name, first.name + ".sha256"])

    def test_it_holds_the_six_files_as_they_are_and_nothing_else(self):
        folder = "codex-compat-reporter-%s" % reporter.__version__
        self.assertEqual(make_release.FILES, ("codex_compat_report.py", "Report.cmd", "README.md", "README.ko.md",
                                              "LICENSE", "docs/REPORT_FORMAT.md"))
        with tempfile.TemporaryDirectory() as out:
            target = self.build(out)
            self.assertEqual(target.name, folder + ".zip")
            with zipfile.ZipFile(target) as archive:
                self.assertEqual(archive.namelist(), ["%s/%s" % (folder, name) for name in make_release.FILES])
                for entry, name in zip(archive.infolist(), make_release.FILES):
                    with self.subTest(name):
                        self.assertEqual(archive.read(entry), (ROOT / name).read_bytes())
                        self.assertEqual(entry.compress_type, zipfile.ZIP_STORED)
                        self.assertEqual(entry.date_time, time.gmtime(EPOCH - 1)[:6])
                        self.assertEqual((entry.create_system, entry.external_attr), (3, 0o100644 << 16))
                self.assertEqual(archive.comment, b"")

    def test_it_refuses_a_version_that_is_not_the_tools(self):
        with tempfile.TemporaryDirectory() as out:
            for version in ("9.9.9", "v%s" % reporter.__version__, reporter.__version__ + "-beta"):
                with self.subTest(version), self.assertRaises(SystemExit):
                    make_release.build(version, pathlib.Path(out), EPOCH)
            self.assertEqual(list(pathlib.Path(out).iterdir()), [])
        self.assertEqual(make_release.declared(), reporter.__version__)

    def test_a_time_before_1980_or_none_is_the_zip_formats_first(self):
        with tempfile.TemporaryDirectory() as out:
            for epoch in (None, 0):
                with self.subTest(epoch), zipfile.ZipFile(self.build(out, epoch=epoch)) as archive:
                    self.assertEqual(archive.infolist()[0].date_time, (1980, 1, 1, 0, 0, 0))


# ------------------------------------------------------------------------------ the workflow
def workflow() -> str:
    return WORKFLOW.read_text(encoding="utf-8")


def job(name: str) -> str:
    """The text of one job, from its key to the next job's key or the end."""
    source = workflow()
    start = re.search(r"(?m)^  %s:\s*$" % re.escape(name), source)
    if not start:
        raise AssertionError("job %s not found" % name)
    rest = source[start.end():]
    end = re.search(r"(?m)^  [A-Za-z0-9_-]+:\s*$", rest)
    return rest[:end.start()] if end else rest


def step(text: str, name: str) -> str:
    start = text.index("- name: %s\n" % name)
    end = text.find("\n      - ", start + 1)
    return text[start:] if end < 0 else text[start:end]


def granted(text: str) -> dict:
    """{scope: access} of the first `permissions:` block in the text."""
    found = re.search(r"(?m)^( +)permissions:\s*\n((?:\1  .*\n)+)", text)
    if not found:
        return {}
    return dict(re.findall(r"(?m)^ +([a-z-]+): (read|write)\s*$", found.group(2)))


def run_scripts(text: str) -> list:
    """(line number, script line) for every line of every `run:` script."""
    lines, found, indent, inside = text.splitlines(), [], 0, False
    for number, line in enumerate(lines, 1):
        stripped = line.lstrip()
        current = len(line) - len(stripped)
        if inside and stripped and current <= indent:
            inside = False
        if re.match(r"(- )?run: ?\|?", stripped):
            inside, indent = True, current
            found.append((number, stripped.split("run:", 1)[1]))
            continue
        if inside:
            found.append((number, line))
    return found


# The actions a workflow here may use: first-party, pinned by full commit SHA, the pins the product's
# own workflows use (codex-auto-resume .github/workflows, 2026-09).
PINS = {
    "actions/checkout": "3d3c42e5aac5ba805825da76410c181273ba90b1",
    "actions/setup-python": "5fda3b95a4ea91299a34e894583c3862153e4b97",
    "actions/upload-artifact": "043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    "actions/download-artifact": "3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c",
    "actions/attest-build-provenance": "4d101475d8b20a2381f78447822ac1eab6504dd8",
}


class ReleaseWorkflowTests(unittest.TestCase):
    def test_only_a_version_tag_starts_it(self):
        trigger = re.search(r"(?ms)^on:\n(.*?)^\S", workflow()).group(1)
        self.assertEqual(trigger.split(), ["push:", "tags:", '["v*"]'])

    def test_nothing_is_granted_at_the_top_and_each_job_asks_for_what_it_uses(self):
        self.assertRegex(workflow(), r"(?m)^permissions: \{\}\s*$")
        self.assertEqual(granted(job("build")), {"contents": "read"})
        self.assertEqual(granted(job("publish")), {"contents": "write", "id-token": "write", "attestations": "write"})
        self.assertEqual(re.findall(r"(?m)^  ([a-z-]+):\s*$", workflow().split("\njobs:\n", 1)[1]), ["build", "publish"])

    def test_every_action_is_first_party_and_pinned_by_its_full_sha(self):
        uses = re.findall(r"uses: ([^@\s]+)@(\S+)", workflow())
        self.assertTrue(uses)
        for action, pin in uses:
            with self.subTest(action):
                self.assertEqual(PINS.get(action), pin)

    @unittest.skipUnless((PRODUCT / ".github" / "workflows").is_dir(), "the product's checkout is not beside this one")
    def test_the_pins_are_the_products_own(self):
        theirs = set()
        for path in (PRODUCT / ".github" / "workflows").glob("*.yml"):
            theirs |= set(re.findall(r"uses: ([^@\s]+)@([0-9a-f]{40})", path.read_text(encoding="utf-8")))
        self.assertLessEqual(set(re.findall(r"uses: ([^@\s]+)@(\S+)", workflow())), theirs)

    def test_no_token_is_left_on_disk_or_seen_by_the_repositorys_code(self):
        source = workflow()
        self.assertEqual(source.count("persist-credentials: false"), source.count("uses: actions/checkout@"))
        self.assertNotIn("persist-credentials: true", source)
        self.assertNotIn("secrets.", job("build"))
        self.assertEqual(source.count("secrets.GITHUB_TOKEN"), 1)
        self.assertIn("GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}", step(job("publish"), "Publish the release"))
        scripts = "\n".join(line for _number, line in run_scripts(source))
        for word in ("extraheader", "credential", "git config", "GITHUB_TOKEN", "GH_TOKEN", "set-output"):
            self.assertNotIn(word, scripts, "no script writes or reads a token itself")

    def test_the_job_that_can_write_runs_none_of_the_repositorys_code(self):
        publish = job("publish")
        self.assertNotIn("actions/checkout", publish)
        scripts = "\n".join(line for _number, line in run_scripts(publish))
        for code in ("python", "tools/", "unittest", "pwsh", "powershell", "./"):
            self.assertNotIn(code, scripts)
        # No script of the repository's run through a shell, at the start of a command or after ; | && (.
        self.assertIsNone(re.search(r"(?m)(^\s*|[;|&(]\s*)(bash|sh|source|\.)\s", scripts))
        self.assertNotIn("shell: pwsh", publish)

    def test_nothing_from_outside_the_tags_tree_runs(self):
        scripts = "\n".join(line for _number, line in run_scripts(workflow()))
        for fetcher in ("curl", "wget", "Invoke-WebRequest", "iwr ", "pip ", "pip3", "npm", "npx", "choco",
                        "winget", "iex", "Invoke-Expression", "bash <", "| sh", "| bash"):
            self.assertNotIn(fetcher, scripts)
        # The only fetch is the tag itself, for its message, from this repository.
        fetches = re.findall(r"git fetch .*", scripts)
        self.assertEqual(fetches, ['git fetch --no-tags --depth=1 origin "+refs/tags/$TAG:refs/tags/$TAG"'])
        # The repository's own code that runs, all of it in the build job: its tests and the ZIP builder.
        self.assertEqual(re.findall(r"python [^\n]*", scripts),
                         ["python -m unittest discover -s tests", 'python tools/make_release.py --version "$VERSION" --out dist'])

    def test_no_expression_is_spliced_into_a_run_script(self):
        """`${{ }}` inside `run:` is text substituted into a shell script; values go through `env:`."""
        for number, line in run_scripts(workflow()):
            with self.subTest("release.yml:%d" % number):
                self.assertNotIn("${{", line)

    def test_one_step_attests_the_zip_after_it_is_checked_and_before_it_is_published(self):
        source, publish = workflow(), job("publish")
        self.assertEqual(source.count("uses: actions/attest-build-provenance@"), 1)
        self.assertIn("subject-path: ${{ env.ZIP }}", step(publish, "Attest the ZIP"))
        self.assertIn("      ZIP: dist/codex-compat-reporter-${{ needs.build.outputs.version }}.zip\n", publish)
        order = [publish.index("- name: %s\n" % name) for name in
                 ("Take what the build job made", "Check it again, here", "Attest the ZIP", "Publish the release")]
        self.assertEqual(order, sorted(order))

    def test_one_release_carries_the_zip_and_its_checksum_with_the_tags_message(self):
        source = workflow()
        self.assertEqual(source.count("gh release create"), 1)
        command = step(job("publish"), "Publish the release")
        create = command[command.index("gh release create"):]
        self.assertEqual(re.findall(r'"(\$[A-Z]+(?:\.sha256)?)"', create.split("--")[0]), ["$ZIP", "$ZIP.sha256"])
        self.assertIn("--notes-file dist/release-notes.md", create)
        self.assertIn("--verify-tag", create)
        notes = step(job("build"), "Take the release notes from the tag's message")
        self.assertIn("%(contents:subject)%0a%0a%(contents:body)", notes)
        self.assertIn('== "tag" ]]', notes, "an annotated tag, whose message is the notes")
        self.assertIn('== "$GITHUB_SHA" ]]', notes)

    def test_the_zip_is_checked_again_for_exactly_what_make_release_packs(self):
        check = step(job("publish"), "Check it again, here")
        listed = re.search(r'printf "\$folder/%s\\n" ([^)]*)\)', check).group(1).split()
        self.assertEqual(tuple(listed), make_release.FILES)
        self.assertIn('sha256sum "$ZIP"', check)
        self.assertIn('"$GITHUB_REF" == "refs/tags/v$VERSION"', check)

    def test_the_build_job_tests_the_tag_and_stamps_the_zip_with_its_commits_time(self):
        build = job("build")
        self.assertLess(build.index("python -m unittest discover -s tests"), build.index("python tools/make_release.py"))
        self.assertIn('export SOURCE_DATE_EPOCH="$(git log -1 --format=%ct)"', build)
        self.assertIn(r'[[ "$TAG" =~ ^v([0-9]+\.[0-9]+\.[0-9]+)$ ]]', build)


# ------------------------------------------------------------------------------ the pictures
IMAGE = re.compile(r"!\[([^\]]*)\]\(([^)\s]+)\)")


class PictureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.frames = make_pictures.frames()          # the guide, run now against the fixture

    def linked(self, readme):
        return IMAGE.findall(readme.read_text(encoding="utf-8"))

    def test_every_picture_the_readmes_show_is_there_and_both_show_the_same_ones(self):
        expected = ["docs/images/" + name for name, _gh, _question in make_pictures.PICTURES]
        for readme in READMES:
            with self.subTest(readme.name):
                links = self.linked(readme)
                self.assertEqual([path for _alt, path in links], expected)
                for alt, path in links:
                    self.assertTrue(alt.strip(), "every picture says what it shows")
                    self.assertTrue((ROOT / path).is_file(), path)
        self.assertEqual(sorted(path.name for path in (ROOT / "docs" / "images").iterdir()),
                         sorted(name for name, _gh, _question in make_pictures.PICTURES))

    def test_each_picture_holds_its_image_and_its_text_and_nothing_else(self):
        for name in self.frames:
            with self.subTest(name):
                chunks = make_pictures.chunks((ROOT / "docs" / "images" / name).read_bytes())
                self.assertEqual(chunks[0][0], "IHDR")
                self.assertEqual(chunks[-1][0], "IEND")
                self.assertLessEqual({kind for kind, _body in chunks}, {"IHDR", "PLTE", "IDAT", "iTXt", "IEND"})
                self.assertEqual([kind for kind, _body in chunks].count("iTXt"), 1)
                width, height = [int.from_bytes(chunks[0][1][at:at + 4], "big") for at in (0, 4)]
                self.assertEqual((width, height), (make_pictures.WIDTH * make_pictures.SCALE,
                                                   make_pictures.HEIGHT * make_pictures.SCALE))

    def test_each_picture_shows_what_the_guide_prints_today(self):
        """Change a word the guide prints, and this fails until the pictures are made again."""
        for name, rows in self.frames.items():
            with self.subTest(name):
                shown = make_pictures.carried((ROOT / "docs" / "images" / name).read_bytes())
                self.assertEqual(shown, make_pictures.shown_text(rows),
                                 "run: python tools/make_pictures.py (from PowerShell or cmd)")

    def test_nothing_in_a_picture_is_anyone_elses(self):
        for name in self.frames:
            shown = make_pictures.unwrapped(make_pictures.carried((ROOT / "docs" / "images" / name).read_bytes()))
            with self.subTest(name):
                make_pictures.refuse_elsewhere(shown, (tempfile.gettempdir(),))
                self.assertIn(make_pictures.LOGIN, shown)
                self.assertEqual(set(re.findall(r"C:\\Users\\([^\\\s]+)", shown)), {make_pictures.LOGIN})
                self.assertNotIn("@", shown)

    def test_the_check_refuses_what_is_not_the_fixtures(self):
        for text in ("installation : C:\\Users\\someone\\.codex-auto-resume", "signed in as someone",
                     "mail me at someone@example.com", "D:\\work\\report.json",
                     "GitHub login [someone]: ", tempfile.gettempdir()):
            with self.subTest(text), self.assertRaises(SystemExit):
                make_pictures.refuse_elsewhere(text, (tempfile.gettempdir(),))
        # A login the window cuts in two is read whole: the fixture's passes, and anyone else's does not.
        width = make_pictures.COLUMNS
        make_pictures.refuse_elsewhere(make_pictures.unwrapped("signed in as ExampleUs".rjust(width) + "\ner, host"))
        with self.assertRaises(SystemExit):
            make_pictures.refuse_elsewhere(make_pictures.unwrapped("signed in as ExampleUs".rjust(width) + "\nerX, host"))


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
