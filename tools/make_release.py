"""The release: the ZIP of the seven files a reporter needs, packed the same way every time, and
Report.exe on its own.

    python tools/make_exe.py                                    # Report.exe, beside codex_compat_report.py
    python tools/make_release.py --version 1.4.1 --out dist

It writes codex-compat-reporter-<version>.zip, holding FILES under one folder of that name and
nothing else, and CodexCompatReporter-<version>.exe, the very bytes of the Report.exe in that ZIP,
under a name of its own: Report.exe carries the reporter inside it (tools/make_exe.py), so it runs
downloaded on its own as well as unzipped. Beside each is <its name>.sha256 in sha256sum's format.
.github/workflows/release.yml runs both tools on the tagged tree and publishes the four files.

Report.exe is the one file the tree does not hold: tools/make_exe.py compiles it from gui/, and this
refuses to pack one that is missing or says it is another version than codex_compat_report.py's.

The same tree gives the same bytes, so anyone can rebuild a tag and compare: the entries in one fixed
order, stored rather than compressed (the zlib builds in different Pythons need not agree), each with
one time - SOURCE_DATE_EPOCH, which the workflow sets to the tagged commit's - and the same attributes
whichever system builds it. The files go in as the checkout wrote them, and .gitattributes makes every
checkout write them alike; Report.exe is the same bytes from the same sources and the same compiler
(tools/make_exe.py).
"""
from __future__ import annotations

import argparse
import hashlib
import os
import pathlib
import re
import sys
import time
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
# What a reporter needs: the tool, the two ways to start it - its window and its console guide - what
# explains it, and the licence. Nothing that only builds or tests it - gui/, tools/, tests/ and the
# pictures stay in the repository.
FILES = ("codex_compat_report.py", "Report.exe", "Report.cmd", "README.md", "README.ko.md", "LICENSE",
         "docs/REPORT_FORMAT.md")
EXE = "Report.exe"                      # a build output of tools/make_exe.py, never in the repository
STANDALONE = "CodexCompatReporter-%s.exe"   # the same bytes, published beside the ZIP
VERSION = re.compile(r"\A\d+\.\d+\.\d+\Z")
EARLIEST = 315532800            # 1980-01-01T00:00:00Z: a ZIP cannot hold an earlier time


def declared(root: pathlib.Path = ROOT) -> str:
    """__version__ as codex_compat_report.py declares it, read without running it."""
    found = re.search(r'(?m)^__version__ = "([^"]+)"\s*$', (root / "codex_compat_report.py").read_text(encoding="utf-8"))
    if not found:
        raise SystemExit("codex_compat_report.py declares no __version__")
    return found.group(1)


def name_of(version: str) -> str:
    return "codex-compat-reporter-%s" % version


def standalone_of(version: str) -> str:
    return STANDALONE % version


def assets(version: str) -> tuple:
    """What a release publishes, in the order it is published: the ZIP, the program on its own, and
    the checksum beside each."""
    zip_name, exe_name = name_of(version) + ".zip", standalone_of(version)
    return zip_name, zip_name + ".sha256", exe_name, exe_name + ".sha256"


def checksum(path: pathlib.Path) -> None:
    """<path>.sha256 beside it, in sha256sum's format."""
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    (path.parent / (path.name + ".sha256")).write_bytes(("%s  %s\n" % (digest, path.name)).encode("ascii"))


def product_version(raw: bytes) -> str | None:
    """The product version a Windows program says it is - what Explorer's Properties shows, and what
    tools/make_exe.py writes from __version__ - read from its version resource; None when it says none.
    The String there is its key, "ProductVersion", then its value, both UTF-16 and ending in a NUL, the
    value set on the next four-byte boundary of the String, which starts six bytes before its key."""
    key = "ProductVersion\0".encode("utf-16-le")
    at = raw.find(key) if raw[:2] == b"MZ" else -1
    if at < 6:
        return None
    start = at + len(key) + (-(6 + len(key)) % 4)
    end = start
    while end + 1 < len(raw) and raw[end:end + 2] != b"\0\0":
        end += 2
    try:
        return raw[start:end].decode("utf-16-le") if end + 1 < len(raw) else None
    except UnicodeDecodeError:
        return None


def build(version: str, out: pathlib.Path, epoch: int | None = None, root: pathlib.Path = ROOT) -> pathlib.Path:
    """Write the ZIP, the program on its own and a .sha256 beside each into `out`; the ZIP's path."""
    if not VERSION.match(version):
        raise SystemExit("%r is not MAJOR.MINOR.PATCH" % version)
    if version != declared(root):
        raise SystemExit("the version asked for, %s, is not the tool's own, %s" % (version, declared(root)))
    missing = [name for name in FILES if not (root / name).is_file()]
    if missing:
        raise SystemExit("missing: %s%s" % (", ".join(missing), " (python tools/make_exe.py makes Report.exe)"
                                                                  if EXE in missing else ""))
    program = (root / EXE).read_bytes()          # read once: the ZIP's Report.exe and the one on its own
    said = product_version(program)
    if said != version:
        raise SystemExit("Report.exe says it is %s, not %s: make it again from this tree with python "
                         "tools/make_exe.py" % (said or "no version", version))
    # Even seconds, since a ZIP keeps no odd ones, and in UTC wherever it is built.
    stamp = time.gmtime(max(EARLIEST, int(epoch if epoch is not None else EARLIEST)) // 2 * 2)[:6]
    folder = name_of(version)
    out.mkdir(parents=True, exist_ok=True)
    target = out / (folder + ".zip")
    with zipfile.ZipFile(target, "w", zipfile.ZIP_STORED) as archive:
        for name in FILES:
            entry = zipfile.ZipInfo("%s/%s" % (folder, name), date_time=stamp)
            entry.compress_type = zipfile.ZIP_STORED
            entry.create_system = 3                     # the same on every system that builds it
            entry.external_attr = 0o100644 << 16        # a plain file, readable by everyone
            archive.writestr(entry, program if name == EXE else (root / name).read_bytes())
    checksum(target)
    alone = out / standalone_of(version)
    alone.write_bytes(program)
    checksum(alone)
    return target


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--version", default=None, help="the version to build (default: the tool's own)")
    parser.add_argument("--out", default="dist", help="the folder to write into (default: dist)")
    arguments = parser.parse_args(argv)
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch is not None and not epoch.isdigit():
        raise SystemExit("SOURCE_DATE_EPOCH is not a number of seconds: %r" % epoch)
    version = arguments.version or declared()
    target = build(version, pathlib.Path(arguments.out), int(epoch) if epoch else None)
    for made in (target, target.parent / standalone_of(version)):
        print("%s  %s" % (hashlib.sha256(made.read_bytes()).hexdigest(), made))
    return 0


if __name__ == "__main__":
    sys.exit(main())
