# codex-compat-reporter

[한국어](README.ko.md)

A small Windows tool that turns your own [Codex Auto Resume](https://github.com/songyb111-gachon/codex-auto-resume-windows)
installation's records into one JSON file you can send to the project: how the product behaved on
your machine, with your Codex version. Counts, states and times. Nothing you said to Codex.

The product's compatibility data says which Codex versions have been seen to work. Today only the
maintainer's own machine feeds it, which is one machine and one way of working. This is how yours
can say something too.

## Get it

It is one file of standard-library Python; there is nothing to install. Either clone the repository
and work in its folder:

```
git clone https://github.com/songyb111-gachon/codex-compat-reporter
cd codex-compat-reporter
```

or save [`codex_compat_report.py`](https://raw.githubusercontent.com/songyb111-gachon/codex-compat-reporter/main/codex_compat_report.py)
into a folder of its own and open a terminal there. The report is written into the folder you run
it from.

It needs:

- Windows, and Python 3.11 or newer. CI runs the tests on Python 3.11, 3.12, 3.13 and 3.14.
- Codex Auto Resume v0.6.0 or newer, installed, with its watcher having run at least once.
- For `submit` only: the [GitHub CLI](https://cli.github.com/), signed in with
  `gh auth login --hostname github.com`.

Every example below says `python`. Where the Python launcher is installed (the python.org
installer puts it there), `py` works the same; the Microsoft Store's Python has `python` but not
`py`.

## Use it

```
python codex_compat_report.py status                          # what this machine can show
python codex_compat_report.py report --login <your login>     # write the report
                                                              # ...now open the file and read it
python codex_compat_report.py submit <the file> --dry-run     # check everything, send nothing
python codex_compat_report.py submit <the file> --yes         # open the pull request
```

`report` writes `codex-cli-<version>.json`. Read that file - it is a plain, short document, and
reading it is the only way to be sure of what you are sending. `submit` sends exactly the bytes of
the file you name, as they are when you run it: it never rebuilds the report, and it never changes
the file. If you edit the file, what you saved is what is sent, provided it still follows
[the format](docs/REPORT_FORMAT.md); a file that does not is refused before anything leaves your
machine.

### Commands and options

| Command and option | What it does |
| --- | --- |
| `status` | Prints the installed product version, the Codex version it sees, how many records exist here (on this Codex version, on others, and not placed on any, with the reason), how many are hidden with Clear history, and whether the product's own checks passed on this version. Writes nothing. |
| `report --login LOGIN` | Writes the report for the Codex version installed now, filed under your GitHub login. Required. |
| `report --codex-version VERSION` | Reports on another Codex version this machine has records for, as `0.155.0` or `codex-cli 0.155.0`. `--version` is the same option. |
| `report --out FILE` | Writes the report to FILE instead of `codex-cli-<version>.json` in the current folder. The name you choose stays on your machine; see `submit`. |
| `report --force` | Writes over a file that is already there. Without it, `report` refuses, so a file you have read is never replaced behind your back. |
| `submit [FILE]` | Sends FILE. Without FILE it takes the one `codex-cli-*.json` in the current folder, and refuses if there is none or more than one. Without `--yes` or `--dry-run` it checks everything, says what it would do, sends nothing, and exits with 2. |
| `submit --dry-run` | Checks everything, says what it would write, and stops (exit 0). It still asks GitHub the read-only questions below. |
| `submit --yes` | Yes: writes to GitHub as listed below and opens the pull request. |
| `submit --login LOGIN` | Refuses unless the file is filed under LOGIN. |
| `submit --sha256 HEX` | Refuses unless the file's SHA-256 is HEX, as `report` printed it - a way to be sure the file is still the one you read. |
| `--version`, `--help` | The tool's own version, and help. They read nothing. |

### Exit codes

| Code | Meaning |
| --- | --- |
| 0 | Done: `status` printed, `report` wrote the file, `submit --dry-run` checked everything, or `submit --yes` opened the pull request. |
| 1 | An unexpected error - a bug. Please open an issue with what it printed. |
| 2 | Refused, with the reason and what to do on the error output; nothing was written or sent. Also a mistake in the command line. |
| 3 | `submit`: the project is not taking reports yet. Nothing was sent; keep the file. |

## What it reads

Everything is read on your machine and opened read-only. The installation is
`%USERPROFILE%\.codex-auto-resume` unless `CODEX_AUTO_RESUME_HOME` names another folder, and the
Codex home is `%USERPROFILE%\.codex` unless `CODEX_HOME` does.

| It reads | For |
| --- | --- |
| `.codex-auto-resume\app\.codex-plugin\plugin.json` | the installed product version |
| `.codex-auto-resume\config\state.sqlite` | the recovery records: when each was detected, delivered and how it ended, its category, state and reason, which gates it passed, and the thread and turn ids that key the count below. Records hidden with Clear history are left out. |
| `.codex-auto-resume\logs\auto-resume.log` and `auto-resume.log.1` to `.5` | which Codex version was running around each record, and whether the product's own checks passed on it |
| `.codex-auto-resume\config\compatibility.json` | what the watcher itself concluded about the Codex installed now |
| `.codex\thread_history_*.sqlite` (the newest) | how many items of each kind the recovered turn produced |

Thread and turn ids, and the paths of these files, are read and used on your machine only; they are
never written into the report and never sent. One query passes over your conversation itself: to
count what the recovered turn produced, SQLite reads that turn's items in Codex's history and hands
back only a number per kind - never their text. The product itself does the same, and its
[privacy notes](https://github.com/songyb111-gachon/codex-auto-resume-windows/blob/main/docs/PRIVACY.md)
say so.

It writes nothing on your machine but the report file, and - during `submit --yes` only - a
temporary copy of the upload in your temporary folder, deleted as soon as it is sent. Reading a
SQLite database that is in WAL mode lets SQLite update its shared-memory index (the `-shm` file),
as the product's own reads do; no data is written to the database itself.

## What the report carries, and what is published

The file is what is published, and nothing else is: a pull request makes it public, for good.
It carries:

- your GitHub login, the tool's version, the Codex Auto Resume version, and the Windows build
  number (like `10.0.26200`);
- the Codex version it is about;
- per record: its category, state, reason and turn status - each one of the product's own words,
  and `other` for any word the tool does not know - how many gates it passed, and how many items
  of each kind the recovered turn produced;
- per capability: how many records confirmed or missed it, and the level that shows;
- how many times the product's own checks passed here, and on what;
- times, all UTC to the second and exactly as recorded: when the file was written, when each
  record was detected, delivered and ended, when each capability was last confirmed, and the first
  and last time the product's checks passed. Together they show when the product was busy on your
  machine.

It never carries message text, thread or turn ids, file paths, folder names, your Windows user
name, your Codex account, or anything you typed. The only free text in it is the login you pass
yourself. [The format](docs/REPORT_FORMAT.md) lists every field.

## What `submit` does on GitHub

It uses the `gh.exe` found in a folder on your `PATH` - never one in the current folder - and
every call names `github.com`, so a `GH_HOST` set for another server is not used. It signs in as
whatever `gh` is signed in as; a token with the `public_repo` scope is enough.

It asks GitHub these read-only questions first - under `--dry-run`, and without `--yes`, too:
whether `gh` is signed in, and as whom (it must be the login in the file); whether the project
takes reports yet (the folder `docs/evidence/community/` on its main branch); whether your report
for this Codex version is already filed there or waiting in an open pull request of yours; whether
you have a fork of the project, and whether the branch below is on it; and which commit the
project's main is at.

Only with `--yes` does it write, as you:

1. a fork of `songyb111-gachon/codex-auto-resume-windows` under your account, when you have none -
   public, and kept until you delete it;
2. the branch `compat-report/codex-cli-<version>` on your fork, made at the project's main (or
   reset to it, when an earlier attempt left it behind);
3. one commit on that branch adding the exact bytes of your file as
   `docs/evidence/community/<your login>/codex-cli-<version>.json`;
4. one public pull request to the project. A pull request cannot be unpublished.

The name in the project is always `codex-cli-<version>.json` under your login, whatever you called
the file on your machine. There is one report per GitHub login per Codex version: `submit` refuses
when yours is already filed or its pull request is open.

## What a report can and cannot do

A report is a measurement, not a verdict. When one arrives, the project recomputes every derived
field from the records in it, so a conclusion edited by hand does not survive the trip.

Community reports have a grade of their own: **Reported**. What is known about a Codex version is
said with four words, and they are a ladder - *verified*, *checked*, *compatible* and *failed
here*. Reported is not one of them and never becomes one. It is shown beside the version, as its
own grade, with the number of machines that said the same thing: N reported it working, M reported
a failure, K reported nothing either way.

- A version whose own evidence says nothing stays **compatible** however many reports arrive.
- Reports **never raise a version's tier** to Verified or Checked, and never change what the
  product allows itself to do on anyone's machine. A version's tier still comes from evidence the
  maintainer recorded, and from your own installation's local checks.
- What they do is show that a version behaved - or did not - somewhere other than one machine. A
  version that fails for you is the most useful report there is.

Nothing here can prove a file was not written by hand on the machine that sent it. That is why
Reported stands beside the ladder and grants nothing, rather than being checked with ceremony and
then trusted. [The format](docs/REPORT_FORMAT.md) says exactly how a report is counted.

## Where it is going

The receiving side - the project showing these reports next to a version - is planned for the
product's v0.6.10. Until the folder `docs/evidence/community/` exists on the product's main branch,
`submit` says so, sends nothing and exits with 3, and `report` still works: keep the file and send
it when the door opens.

MIT licensed. Issues and pull requests are welcome, in English or Korean.
