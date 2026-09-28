// How the window hears the reporter: the codex_compat_report.py this program carries inside it, written
// out to a folder of the user's own and checked again before every start, run with the Python Report.cmd
// would run it with, isolated and in UTF-8, in this program's own folder, with no console and nothing to
// read from, off the window's thread. Every decision and every byte of a report is the script's; the
// window shows what the script answers, as the one JSON object its --json interface prints
// (codex_compat_report.py `answer`).
//
// --fixture puts a file of those answers in the script's place, for tests and pictures: then no Python
// is looked for or started, and nothing of this machine is read.
//
// C# 5 only: this is compiled by the in-box csc (tools/make_exe.py).
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Globalization;
using System.IO;
using System.Text;
using System.Threading;
using System.Windows.Forms;

namespace CodexCompatReporter
{
    // What one run of the script answered: its JSON object when it gave one, or the sentence it refused
    // with - its own, or, when it said nothing a window can read, what the window can say about that.
    internal sealed class Answer
    {
        public JsonObject Fields;
        public string Refused;
        public int Exit;
        public bool NoPython;
        // What a send that was refused half-way had written to GitHub, as the script lists it.
        public List<string> Written = new List<string>();

        public bool Ok
        {
            get { return Fields != null && Refused == null; }
        }

        public static Answer Read(string output, string errors, int exit)
        {
            JsonObject found = null;
            try
            {
                found = JsonObject.From(Json.Parse(output.Trim()));
            }
            catch (FormatException)
            {
                found = null;
            }
            if (found == null)
            {
                Answer none = Refusal("codex_compat_report.py did not answer this window (exit code " + exit + ")." +
                                      Tail(errors));
                none.Exit = exit;
                return none;
            }
            return Of(found, exit);
        }

        // The object the script printed: what it found, or the sentence it refused with.
        public static Answer Of(JsonObject found, int exit)
        {
            Answer answer = new Answer();
            answer.Exit = exit;
            if (!found.Bool("ok"))
            {
                answer.Refused = found.Str("refused") ?? "codex_compat_report.py refused, and did not say why.";
                answer.Written = found.Strings("written");
            }
            else
            {
                answer.Fields = found;
            }
            return answer;
        }

        static string Tail(string errors)
        {
            string[] lines = (errors ?? "").Replace("\r\n", "\n").Trim().Split('\n');
            if (lines.Length == 0 || lines[0].Length == 0)
            {
                return "";
            }
            int from = Math.Max(0, lines.Length - 6);
            return "\n" + string.Join("\n", lines, from, lines.Length - from);
        }

        public static Answer Refusal(string sentence)
        {
            Answer answer = new Answer();
            answer.Refused = sentence;
            answer.Exit = 2;
            return answer;
        }
    }

    // The reporter, as the window reaches it: live, or the answers of a fixture.
    internal interface ICore
    {
        // Whether there is a script and a Python to run it; when not, Missing says why - for no Python,
        // what Report.cmd says - and WithoutPython is that sentence, for a Python that turns out not to run.
        bool Found { get; }
        string Missing { get; }
        string WithoutPython { get; }
        // The script run with these arguments; `done` is called on the window's thread with its answer.
        void Run(Control window, string[] arguments, Action<Answer> done);
        // Whether a file is there, and its bytes: the report, which the window shows as it is.
        bool Exists(string path);
        byte[] Read(string path);
    }

    internal sealed class LiveCore : ICore
    {
        // Where Report.cmd looks for Python, in its order, and the flags it gives each: `set "PYTHON=..."`
        // there, one pair a line here, so that tests/test_window.py reads both lists and holds them equal.
        internal static readonly string[] Places =
        {
            @"%USERPROFILE%\.codex-auto-resume\runtime\python.exe", "",
            @"%SystemRoot%\py.exe", "-3",
            @"%LOCALAPPDATA%\Programs\Python\Launcher\py.exe", "-3",
            @"%ENTRY%\python.exe", "",
        };
        // Report.cmd's `"%PYTHON%" %PYTHON_FLAGS% -I -X utf8 "%SCRIPT%"`: isolated, so no module is taken
        // from the script's folder or the current one, and in UTF-8 whatever the code page.
        internal static readonly string[] Isolated = { "-I", "-X", "utf8" };
        internal const string Script = "codex_compat_report.py";
        // Where this program keeps the reporter it carries: %LOCALAPPDATA%\codex-compat-reporter\, in a
        // folder named by the first 16 hex digits of the script's SHA-256 - one folder for each script.
        internal const string Keeper = "codex-compat-reporter";
        internal const int Named = 16;
        // What Report.cmd says (:missing), with this program's own name for Report.cmd's, {0}: the name it
        // was saved under - Report.exe in the ZIP, the release's own for the file on its own.
        internal const string NoPython =
            "No Python was found to run the reporter. It looks, in this order, for:\n" +
            "  - the Python Codex Auto Resume installs, %USERPROFILE%\\.codex-auto-resume\\runtime\\python.exe\n" +
            "  - the Python launcher, py.exe, which the python.org installer puts in Windows\n" +
            "  - python.exe in a folder on PATH\n" +
            "A report is about Codex Auto Resume: install it first, then double-click {0} again.";
        // When its copy cannot be put where it keeps it: that folder ({0}), why ({1}), and its name ({2}).
        internal const string NotWritten =
            "This program carries the reporter, codex_compat_report.py, and runs it from a folder of yours,\n" +
            "{0}\n" +
            "but it could not be written there: {1}\n" +
            "Nothing was run. Make sure that folder can be written to, then double-click {2} again.";
        internal const string NoLocalAppData = "LOCALAPPDATA does not name a folder by its full path.";
        internal const string NotTheSame = "what is there now is not what it wrote.";
        // When the copy is no longer the one it carries, as it is about to run it: its path ({0}), its name ({1}).
        internal const string CopyChanged =
            "The reporter was not run: its copy,\n{0}\nis no longer the one this program wrote there. " +
            "Close this window and double-click {1} again, and it writes its own copy there again.";
        // When what it carries is not what it was built with.
        internal const string Damaged =
            "The reporter this program carries is not the one it was built with, so nothing was run: the file " +
            "is damaged. Download it again.";
        // Windows' own stand-in for python.exe, which only offers the Microsoft Store, exits with this.
        const int StoreStandIn = 9009;

        readonly string current;        // the current folder, whose python.exe is never taken from PATH
        readonly string here;           // this program's own folder: Python runs in it, so the report is written there
        readonly string name;           // this program's file name, as it was saved
        readonly string folder;         // where its copy of the script is kept, or null when LOCALAPPDATA names none
        readonly string script;         // that copy
        string python;
        string flags;
        string missing;

        public LiveCore()
        {
            current = Environment.CurrentDirectory;
            // The file's own path, as Windows loaded it. (WinForms' ExecutablePath is read back from a URI
            // that decodes %XX, so in a folder called reporter%41x it names reporterAx, a folder beside it.)
            string self = typeof(LiveCore).Assembly.Location;
            here = Path.GetDirectoryName(self);
            name = Path.GetFileName(self);
            folder = KeptIn();
            script = folder == null ? null : Path.Combine(folder, Script);
            string unkept = Keep();
            bool found = FindPython(here, current, out python, out flags);
            missing = unkept ?? (found ? null : WithoutPython);
        }

        public bool Found
        {
            get { return missing == null; }
        }

        public string Missing
        {
            get { return missing; }
        }

        public string WithoutPython
        {
            get { return string.Format(CultureInfo.InvariantCulture, NoPython, name); }
        }

        // For Report.exe --where: what this machine would give the window, found and kept as above - the
        // script it carries, by its SHA-256, and the copy it runs, in which folder; nothing started.
        internal Ordered Where()
        {
            return new Ordered()
                .Add("here", here)
                .Add("name", name)
                .Add("sha256", Embedded.Sha256)
                .Add("script", script)
                .Add("working_directory", here)
                .Add("python", python)
                .Add("flags", flags)
                .Add("missing", missing);
        }

        // %LOCALAPPDATA%\codex-compat-reporter\<the first 16 hex digits of the SHA-256>: LOCALAPPDATA as the
        // environment gives it, as Report.cmd reads it, and only when it is a full path (C:\... or
        // \\server\...); null otherwise, and then nothing is written anywhere.
        static string KeptIn()
        {
            string local = Environment.GetEnvironmentVariable("LOCALAPPDATA");
            if (string.IsNullOrEmpty(local) || local.IndexOfAny(Path.GetInvalidPathChars()) >= 0 ||
                !((local.Length >= 3 && local.Substring(1, 2) == ":\\") || local.StartsWith("\\\\", StringComparison.Ordinal)))
            {
                return null;
            }
            return Path.Combine(local, Keeper, Embedded.Sha256.Substring(0, Named));
        }

        // The script as this program carries it, compiled in by tools/make_exe.py; null when it is not there.
        static byte[] Carried()
        {
            using (Stream stream = typeof(LiveCore).Assembly.GetManifestResourceStream(Embedded.Resource))
            {
                if (stream == null)
                {
                    return null;
                }
                using (MemoryStream bytes = new MemoryStream())
                {
                    stream.CopyTo(bytes);
                    return bytes.ToArray();
                }
            }
        }

        // Whether a file is there and holds exactly the bytes this program carries.
        static bool Intact(string path)
        {
            try
            {
                return path != null && File.Exists(path) && ReportForm.Sha256(File.ReadAllBytes(path)) == Embedded.Sha256;
            }
            catch (IOException)
            {
                return false;
            }
            catch (UnauthorizedAccessException)
            {
                return false;
            }
        }

        // Puts the script this program carries in its folder, unless the file there already holds those
        // bytes: written to a new name beside it first, then moved into place, so the file is never
        // half-written, and whatever else was there - a changed copy, a read-only one - is replaced whole.
        // Null when the copy is in place; otherwise the sentence the window shows instead of its pages.
        string Keep()
        {
            byte[] carried = Carried();
            if (carried == null || ReportForm.Sha256(carried) != Embedded.Sha256)
            {
                return Damaged;
            }
            if (folder == null)
            {
                return string.Format(CultureInfo.InvariantCulture, NotWritten,
                                     "%LOCALAPPDATA%\\" + Keeper + "\\" + Embedded.Sha256.Substring(0, Named),
                                     NoLocalAppData, name);
            }
            if (Intact(script))
            {
                return null;
            }
            // A name no longer than the script's, so a folder that can hold the one can hold the other.
            string temporary = Path.Combine(folder, "~" + Guid.NewGuid().ToString("N").Substring(0, 12) + ".tmp");
            string why = null;
            try
            {
                Directory.CreateDirectory(folder);
                using (FileStream file = new FileStream(temporary, FileMode.CreateNew, FileAccess.Write, FileShare.None))
                {
                    file.Write(carried, 0, carried.Length);
                }
                if (File.Exists(script))
                {
                    File.SetAttributes(script, FileAttributes.Normal);
                    File.Replace(temporary, script, null, true);
                }
                else
                {
                    File.Move(temporary, script);
                }
            }
            catch (IOException error)
            {
                why = error.Message;
            }
            catch (UnauthorizedAccessException error)
            {
                why = error.Message;
            }
            catch (NotSupportedException error)
            {
                why = error.Message;
            }
            catch (ArgumentException error)
            {
                why = error.Message;
            }
            finally
            {
                Discard(temporary);
            }
            // Another start of this program may have put the same bytes there first: then all is well.
            return Intact(script) ? null : string.Format(CultureInfo.InvariantCulture, NotWritten, folder,
                                                         why ?? NotTheSame, name);
        }

        static void Discard(string temporary)
        {
            try
            {
                if (File.Exists(temporary))
                {
                    File.Delete(temporary);
                }
            }
            catch (IOException)
            {
            }
            catch (UnauthorizedAccessException)
            {
            }
        }

        static string Expand(string place, string entry)
        {
            int end = place.IndexOf('%', 1);
            string name = place.Substring(1, end - 1);
            string value = name == "ENTRY" ? entry : Environment.GetEnvironmentVariable(name);
            // cmd's `if defined`: a variable that is not set is never read as an empty folder.
            return string.IsNullOrEmpty(value) ? null : value + place.Substring(end + 1);
        }

        // cmd's `%%~zF %%~tF`: a file's size and the minute it was written, the same for every name the
        // file has; null when there is no file.
        static string Signature(string file)
        {
            if (file == null || !File.Exists(file))
            {
                return null;
            }
            FileInfo info = new FileInfo(file);
            return info.Length.ToString(CultureInfo.InvariantCulture) + " " +
                   info.LastWriteTime.ToString("yyyy-MM-dd HH:mm", CultureInfo.InvariantCulture);
        }

        // Report.cmd's search, step for step: the first place that holds the file wins; a PATH entry counts
        // only as a full path (C:\... or \\server\...), and never when its python.exe is the one in the
        // current folder or beside this program, however PATH spells that folder.
        internal static bool FindPython(string here, string current, out string python, out string flags)
        {
            for (int i = 0; i + 1 < Places.Length; i += 2)
            {
                if (Places[i].StartsWith("%ENTRY%", StringComparison.Ordinal))
                {
                    continue;
                }
                string candidate = Expand(Places[i], null);
                if (candidate != null && File.Exists(candidate))
                {
                    python = candidate;
                    flags = Places[i + 1];
                    return true;
                }
            }
            string walk = Places[Places.Length - 2];
            string currentPython = Signature(Path.Combine(current.TrimEnd('\\'), "python.exe"));
            string herePython = Signature(Path.Combine(here, "python.exe"));
            string path = Environment.GetEnvironmentVariable("PATH") ?? "";
            foreach (string listed in path.Replace("\"", "").Split(';'))
            {
                string entry = listed;
                if (entry.Length == 0)
                {
                    continue;
                }
                bool full = (entry.Length >= 3 && entry.Substring(1, 2) == ":\\") || entry.StartsWith("\\\\", StringComparison.Ordinal);
                if (!full)
                {
                    continue;
                }
                if (entry.EndsWith("\\", StringComparison.Ordinal))
                {
                    entry = entry.Substring(0, entry.Length - 1);
                }
                string candidate = Expand(walk, entry);
                string seen = Signature(candidate);
                if (seen == null || seen == currentPython || seen == herePython)
                {
                    continue;
                }
                python = candidate;
                flags = Places[Places.Length - 1];
                return true;
            }
            python = null;
            flags = null;
            return false;
        }

        // One argument as the C runtime reads a command line back into arguments.
        internal static string Quote(string argument)
        {
            if (argument.Length > 0 && argument.IndexOfAny(" \t\n\v\"".ToCharArray()) < 0)
            {
                return argument;
            }
            StringBuilder quoted = new StringBuilder("\"");
            int slashes = 0;
            foreach (char c in argument)
            {
                if (c == '\\')
                {
                    slashes++;
                    continue;
                }
                if (c == '"')
                {
                    quoted.Append('\\', slashes * 2 + 1).Append('"');
                }
                else
                {
                    quoted.Append('\\', slashes).Append(c);
                }
                slashes = 0;
            }
            return quoted.Append('\\', slashes * 2).Append('"').ToString();
        }

        public void Run(Control window, string[] arguments, Action<Answer> done)
        {
            List<string> all = new List<string>();
            if (flags.Length > 0)
            {
                all.Add(flags);
            }
            all.AddRange(Isolated);
            all.Add(script);
            all.AddRange(arguments);
            List<string> quoted = new List<string>();
            foreach (string argument in all)
            {
                quoted.Add(Quote(argument));
            }
            string commandLine = string.Join(" ", quoted);
            Thread worker = new Thread(delegate()
            {
                Answer answer = RunPython(commandLine);
                try
                {
                    window.BeginInvoke(done, answer);
                }
                catch (InvalidOperationException)
                {
                    // The window was closed while the script ran.
                }
            });
            worker.IsBackground = true;
            worker.Start();
        }

        // The one place Python is started. First its copy of the script is opened so that nothing can change
        // or replace it until Python is done with it, and read: Python is started only when those are the
        // bytes this program carries. Then with no console, no shell and nothing to read from, in this
        // program's own folder, both streams read as UTF-8, and the exit code kept.
        Answer RunPython(string commandLine)
        {
            string changed = string.Format(CultureInfo.InvariantCulture, CopyChanged, script, name);
            FileStream held;
            try
            {
                held = new FileStream(script, FileMode.Open, FileAccess.Read, FileShare.Read);
            }
            catch (IOException)
            {
                return Answer.Refusal(changed);
            }
            catch (UnauthorizedAccessException)
            {
                return Answer.Refusal(changed);
            }
            using (held)
            {
                byte[] bytes;
                using (MemoryStream read = new MemoryStream())
                {
                    held.CopyTo(read);
                    bytes = read.ToArray();
                }
                if (ReportForm.Sha256(bytes) != Embedded.Sha256)
                {
                    return Answer.Refusal(changed);
                }
                ProcessStartInfo start = new ProcessStartInfo(python, commandLine);
                start.UseShellExecute = false;
                start.CreateNoWindow = true;
                start.WindowStyle = ProcessWindowStyle.Hidden;
                start.RedirectStandardInput = true;
                start.RedirectStandardOutput = true;
                start.RedirectStandardError = true;
                start.StandardOutputEncoding = new UTF8Encoding(false);
                start.StandardErrorEncoding = new UTF8Encoding(false);
                // Its own folder, never the current one: the report is written beside this program, and the
                // reporter takes gh from neither the current folder nor its own, so never from this one.
                start.WorkingDirectory = here;
                start.EnvironmentVariables["NoDefaultCurrentDirectoryInExePath"] = "1";
                try
                {
                    using (Process process = Process.Start(start))
                    {
                        process.StandardInput.Close();
                        string errors = "";
                        Thread reader = new Thread(delegate() { errors = process.StandardError.ReadToEnd(); });
                        reader.IsBackground = true;
                        reader.Start();
                        string output = process.StandardOutput.ReadToEnd();
                        reader.Join();
                        process.WaitForExit();
                        if (process.ExitCode == StoreStandIn)
                        {
                            Answer none = Answer.Refusal(WithoutPython);
                            none.NoPython = true;
                            return none;
                        }
                        return Answer.Read(output, errors, process.ExitCode);
                    }
                }
                catch (Win32Exception error)
                {
                    return Answer.Refusal(python + " could not be started: " + error.Message);
                }
            }
        }

        public bool Exists(string path)
        {
            return File.Exists(path);
        }

        public byte[] Read(string path)
        {
            return File.ReadAllBytes(path);
        }
    }

    // The answers of a fixture file, for --describe and --render: {"python": true or false, "missing",
    // "survey", "login", "report", "exists", "file", "web", "plan", "sent"}, each answer as the script's
    // --json gives it (tests/test_window.py makes them by running the script's own functions), and
    // "missing" a sentence LiveCore says when it cannot run the reporter, as Report.exe --where gives it.
    internal sealed class FixtureCore : ICore
    {
        readonly JsonObject fixture;
        // Each run asked of it, its arguments as the window gave them, for --describe.
        public readonly List<string[]> Asked = new List<string[]>();

        public FixtureCore(JsonObject fixture)
        {
            this.fixture = fixture;
        }

        public bool Found
        {
            get { return !fixture.Has("missing") && (!fixture.Has("python") || fixture.Bool("python")); }
        }

        public string Missing
        {
            get { return fixture.Str("missing") ?? (Found ? null : WithoutPython); }
        }

        public string WithoutPython
        {
            get { return string.Format(CultureInfo.InvariantCulture, LiveCore.NoPython, "Report.exe"); }
        }

        public void Run(Control window, string[] arguments, Action<Answer> done)
        {
            Asked.Add((string[])arguments.Clone());
            string key = arguments[0];
            if (key == "web-steps")
            {
                key = "web";
            }
            else if (key == "submit")
            {
                key = Array.IndexOf(arguments, "--yes") >= 0 ? "sent" : "plan";
            }
            JsonObject answer = fixture.Obj(key);
            if (answer == null)
            {
                done(Answer.Refusal("The fixture has no answer for " + key + "."));
                return;
            }
            done(Answer.Of(answer, answer.Bool("ok") ? 0 : answer.Int("exit", 2)));
        }

        public bool Exists(string path)
        {
            return fixture.Bool("exists");
        }

        public byte[] Read(string path)
        {
            string text = fixture.Str("file");
            if (text == null)
            {
                throw new IOException(path + " could not be read: the fixture holds no file.");
            }
            return new UTF8Encoding(false).GetBytes(text);
        }
    }
}
