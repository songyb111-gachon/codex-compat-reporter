"""Report.exe, the reporter's window, compiled from gui/ by the C# compiler every Windows already has.

    python tools/make_exe.py              # Report.exe beside codex_compat_report.py, where it looks for it
    python tools/make_exe.py --out DIR    # DIR/Report.exe

.NET Framework 4.8 is part of every supported Windows, and its compiler, csc.exe, sits beside it - C# 5,
and nothing to install, for whoever builds it or runs it. Codex Auto Resume builds its own window the
same way (its build/make_gui.ps1). The sources are compiled in the one order SOURCES gives, with a
version resource made from codex_compat_report.py's __version__ and LICENSE, and normalize_pe.py then
fixes the two fields the compiler stamps anew on every run, so the same sources give the same bytes and
anyone can rebuild Report.exe and compare.

Report.exe is a build output: .gitignore keeps it out of the repository.
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import subprocess
import sys
import tempfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT / "tools") not in sys.path:
    sys.path.insert(0, str(ROOT / "tools"))

import normalize_pe  # noqa: E402

# In the order csc takes them, which is part of what makes the bytes the same.
SOURCES = ("gui/Json.cs", "gui/Layout.cs", "gui/Core.cs", "gui/Confirm.cs", "gui/Wizard.cs", "gui/Program.cs")
MANIFEST = "gui/Report.manifest"
REFERENCES = ("System.dll", "System.Core.dll", "System.Drawing.dll", "System.Windows.Forms.dll")
NAME = "Report.exe"
VERSION = re.compile(r"\A(\d+)\.(\d+)\.(\d+)\Z")
HOLDER = re.compile(r"(?m)^Copyright \(c\) \d{4} ([A-Za-z][A-Za-z .'-]{0,80})\s*$")


def compiler():
    """csc.exe of .NET Framework 4.8, beside the framework in the Windows folder, or None."""
    windows = pathlib.Path(os.environ.get("WINDIR") or os.environ.get("SystemRoot") or "C:\\Windows")
    for framework in ("Framework64", "Framework"):
        csc = windows / "Microsoft.NET" / framework / "v4.0.30319" / "csc.exe"
        if csc.is_file():
            return csc
    return None


def declared(root: pathlib.Path = ROOT) -> str:
    """__version__ as codex_compat_report.py declares it, read without running it."""
    found = re.search(r'(?m)^__version__ = "([^"]+)"\s*$', (root / "codex_compat_report.py").read_text(encoding="utf-8"))
    if not found or not VERSION.match(found.group(1)):
        raise SystemExit("codex_compat_report.py declares no MAJOR.MINOR.PATCH __version__")
    return found.group(1)


def version_source(root: pathlib.Path = ROOT) -> str:
    """The version resource, as C#: what Explorer's Properties and a SmartScreen prompt show of the file."""
    version = declared(root)
    holder = HOLDER.search((root / "LICENSE").read_text(encoding="utf-8"))
    if not holder:
        raise SystemExit("LICENSE names no copyright holder")
    name = holder.group(1).strip()
    return "\r\n".join([
        "// Made by tools/make_exe.py from codex_compat_report.py and LICENSE. Do not edit.",
        "using System.Reflection;",
        '[assembly: AssemblyTitle("codex-compat-reporter")]',
        '[assembly: AssemblyDescription("codex-compat-reporter: a report of how Codex Auto Resume behaved on this machine")]',
        '[assembly: AssemblyProduct("codex-compat-reporter")]',
        '[assembly: AssemblyCompany("%s")]' % name,
        '[assembly: AssemblyCopyright("Copyright (c) %s. MIT License.")]' % name,
        '[assembly: AssemblyVersion("%s.0")]' % version,
        '[assembly: AssemblyFileVersion("%s.0")]' % version,
        '[assembly: AssemblyInformationalVersion("%s")]' % version,
        "",
    ])


def said(raw: bytes) -> str:
    """What csc printed: UTF-8 when /utf8output was heeded, the system's code page when it was not."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("mbcs" if os.name == "nt" else "latin-1", errors="replace")


def build(out: pathlib.Path, root: pathlib.Path = ROOT) -> pathlib.Path:
    """Compile Report.exe into `out` and make it reproducible; its path."""
    csc = compiler()
    if csc is None:
        raise SystemExit("The C# compiler of .NET Framework 4.8 was not found (%%WINDIR%%\\Microsoft.NET\\Framework64"
                         "\\v4.0.30319\\csc.exe).")
    out = pathlib.Path(out)
    out.mkdir(parents=True, exist_ok=True)
    exe = out / NAME
    with tempfile.TemporaryDirectory(prefix="report-exe-") as work:
        info = pathlib.Path(work) / "Report.VersionInfo.cs"
        info.write_bytes(version_source(root).encode("ascii"))
        arguments = [str(csc), "/nologo", "/utf8output", "/target:winexe", "/platform:anycpu", "/optimize+",
                     "/warn:4", "/warnaserror+", "/out:" + str(exe), "/win32manifest:" + str(root / MANIFEST)]
        arguments += ["/reference:" + reference for reference in REFERENCES]
        arguments += [str(root / source) for source in SOURCES] + [str(info)]
        done = subprocess.run(arguments, capture_output=True, stdin=subprocess.DEVNULL,
                              creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if done.returncode:
        raise SystemExit("Report.exe did not compile:\n%s%s" % (said(done.stdout), said(done.stderr)))
    # The in-box compiler has no /deterministic: every build stamps the second it ran into the PE header
    # and a fresh random GUID into the module's metadata, and nothing else varies.
    normalize_pe.normalise_file(exe)
    return exe


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--out", default=str(ROOT), help="the folder to write Report.exe into (default: beside "
                                                         "codex_compat_report.py)")
    arguments = parser.parse_args(argv)
    exe = build(pathlib.Path(arguments.out))
    print("%s  %s  (compiled by %s)" % (hashlib.sha256(exe.read_bytes()).hexdigest(), exe, compiler()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
