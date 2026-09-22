# codex-compat-reporter

[한국어](README.ko.md)

A small Windows tool that turns your own [Codex Auto Resume](https://github.com/songyb111-gachon/codex-auto-resume-windows)
installation's records into one JSON file you can send to the project: how the product behaved on
your machine, with your Codex version. Counts, states and times. Nothing you said to Codex.

The product's compatibility data says which Codex versions have been seen to work. Today only the
maintainer's own machine feeds it, which is one machine and one way of working. This is how yours
can say something too.

## What it does

```
py codex_compat_report.py status                          # what this machine can show
py codex_compat_report.py report --login <your login>     # write the report, and read it
py codex_compat_report.py submit --login <your login>     # open a pull request with it
```

`status` prints the installed product version, the Codex version it sees, how many recovery records
exist here and whether the product's own checks passed on this version. `report` writes
`codex-cli-<version>.json` in the current folder. Read that file - it is a plain, short document,
and reading it is the only way to be sure of what you are sending. `submit` opens a public pull
request adding it to the project, and refuses until you pass `--yes`.

Needs Windows, Python 3.11 or newer, Codex Auto Resume installed, and - for `submit` - a signed-in
[`gh`](https://cli.github.com/). No packages to install; it is one file of standard library.

## What it reads, and what it never reads

It opens everything read-only and changes no setting, on your machine or anywhere else.

| It reads | For |
| --- | --- |
| `~/.codex-auto-resume/config/state.sqlite` | when a recovery was detected, delivered, and how it ended |
| `~/.codex-auto-resume/logs/auto-resume.log` | which Codex version was installed around each record, and whether the product's local checks passed |
| `~/.codex-auto-resume/config/compatibility.json` | what the watcher itself concluded about this Codex |
| `~/.codex/thread_history_*.sqlite` | how many items the recovered turn produced, by kind |

It never reads, and the report never carries: message text, turn or thread identifiers, file paths,
folder names, your Windows user name, your Codex account, or anything you typed. The only free text
in the file is the GitHub login you pass yourself. See [the format](docs/REPORT_FORMAT.md) for every
field, and the report itself for the rest - it is yours to read before it is anyone's to receive.

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
`submit` says so and stops, and `report` still works: keep the file and send it when the door opens.

MIT licensed. Issues and pull requests are welcome, in English or Korean.
