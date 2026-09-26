// How the window hears the reporter: codex_compat_report.py beside Report.exe, run with the Python
// Report.cmd would run it with, isolated and in UTF-8, with no console and nothing to read from, off the
// window's thread. Every decision and every byte of a report is the script's; the window shows what the
// script answers, as the one JSON object its --json interface prints (codex_compat_report.py `answer`).
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
        // Whether there is a script and a Python to run it; when not, Missing says what Report.cmd says.
        bool Found { get; }
        string Missing { get; }
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
        // What Report.cmd says (:missing and :unzip), for Report.exe.
        internal const string NoPython =
            "No Python was found to run the reporter. It looks, in this order, for:\n" +
            "  - the Python Codex Auto Resume installs, %USERPROFILE%\\.codex-auto-resume\\runtime\\python.exe\n" +
            "  - the Python launcher, py.exe, which the python.org installer puts in Windows\n" +
            "  - python.exe in a folder on PATH\n" +
            "A report is about Codex Auto Resume: install it first, then double-click Report.exe again.";
        internal const string NoScript =
            "codex_compat_report.py is not beside this file. Unzip the whole ZIP first - right-click it and\n" +
            "choose Extract All - and then double-click Report.exe in the folder that makes.";
        // Windows' own stand-in for python.exe, which only offers the Microsoft Store, exits with this.
        const int StoreStandIn = 9009;

        readonly string folder;         // where the report is written: the current folder, as for Report.cmd
        readonly string here;           // this program's own folder, where the script must be
        readonly string script;
        string python;
        string flags;
        string missing;

        public LiveCore()
        {
            folder = Environment.CurrentDirectory;
            // The file's own path, as Windows loaded it. (WinForms' ExecutablePath is read back from a URI
            // that decodes %XX, so in a folder called reporter%41x it names reporterAx, a folder beside it.)
            here = Path.GetDirectoryName(typeof(LiveCore).Assembly.Location);
            script = Path.Combine(here, Script);
            if (!File.Exists(script))
            {
                missing = NoScript;
            }
            else if (!FindPython(here, folder, out python, out flags))
            {
                missing = NoPython;
            }
        }

        public bool Found
        {
            get { return missing == null; }
        }

        public string Missing
        {
            get { return missing; }
        }

        // For Report.exe --where: what this machine would give the window, found as above; nothing started.
        internal Ordered Where()
        {
            return new Ordered()
                .Add("here", here)
                .Add("script", script)
                .Add("python", python)
                .Add("flags", flags)
                .Add("missing", missing);
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
            string program = python;
            string where = folder;
            Thread worker = new Thread(delegate()
            {
                Answer answer = RunPython(program, commandLine, where);
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

        // The one place Python is started: no console, no shell, nothing to read from, both streams read
        // as UTF-8, and the exit code kept.
        static Answer RunPython(string program, string commandLine, string where)
        {
            ProcessStartInfo start = new ProcessStartInfo(program, commandLine);
            start.UseShellExecute = false;
            start.CreateNoWindow = true;
            start.WindowStyle = ProcessWindowStyle.Hidden;
            start.RedirectStandardInput = true;
            start.RedirectStandardOutput = true;
            start.RedirectStandardError = true;
            start.StandardOutputEncoding = new UTF8Encoding(false);
            start.StandardErrorEncoding = new UTF8Encoding(false);
            start.WorkingDirectory = where;
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
                        Answer none = Answer.Refusal(NoPython);
                        none.NoPython = true;
                        return none;
                    }
                    return Answer.Read(output, errors, process.ExitCode);
                }
            }
            catch (Win32Exception error)
            {
                return Answer.Refusal(program + " could not be started: " + error.Message);
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

    // The answers of a fixture file, for --describe and --render: {"python": true or false, "survey",
    // "login", "report", "exists", "file", "web", "plan", "sent"}, each answer as the script's --json
    // gives it (tests/test_window.py makes them by running the script's own functions).
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
            get { return !fixture.Has("python") || fixture.Bool("python"); }
        }

        public string Missing
        {
            get { return Found ? null : LiveCore.NoPython; }
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
