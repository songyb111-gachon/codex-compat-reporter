// The window: the guide's five steps as the five pages of a plain Windows wizard, in the guide's words.
// What each page shows is what codex_compat_report.py answered; nothing here decides what a report holds,
// whether a login or a file will do, or what is sent. The window adds two things of its own, both to hold
// the person to what they were shown: the SHA-256 of the bytes it shows and the writes it lists, which
// pin the send (`submit --sha256 ... --write ...`: the script sends exactly those, or nothing), and a
// question asked once more, whose default answer is no, before anything is written to GitHub.
//
// C# 5 only: this is compiled by the in-box csc (tools/make_exe.py).
using System;
using System.Collections.Generic;
using System.ComponentModel;
using System.Diagnostics;
using System.Drawing;
using System.Globalization;
using System.IO;
using System.Security.Cryptography;
using System.Text;
using System.Text.RegularExpressions;
using System.Windows.Forms;

namespace CodexCompatReporter
{
    internal sealed class ReportForm : Form
    {
        // The guide's steps (codex_compat_report.py, Guide.steps), and the sentences it prints that the
        // window shows as they are: tests/test_window.py holds each to the script's own words.
        internal static readonly string[] Titles =
        {
            "What this machine can show", "Your GitHub login", "Write the report", "Read it", "Send it, or not",
        };
        internal const string Purpose = ": how Codex Auto Resume behaved on this machine, as a file.";
        internal const string Public = "The report is filed under it, and it is public once sent.";
        internal const string Short = "It is short, and reading it is the only way to be sure of what would be sent:";
        internal const string Changed = "The file has changed since it was written. What would be sent is what it holds now.";
        internal const string Unsent = "Nothing was sent. The report stays here, yours to send or delete:";
        internal const string Stays = "The report stays here:";
        internal const string NoNotepad = "Notepad could not be started: open the file above yourself.";
        // What the window says in words of its own, where the guide asks at the console.
        internal const string Nothing = "Nothing leaves this machine unless you choose Send at the end.";
        internal const string Offered = "gh, the GitHub CLI, is signed in here as {0}: it is filled in below.";
        internal const string Mismatch = "The file changed after it was shown here, so nothing more is done with what " +
                                         "was shown. It is shown again below as it is now: read it again, then choose Next.";
        internal const string Opened = "The pull request is open:";
        internal const string IfClosed = "Close, and nothing is sent: the report stays here, yours to send or delete:";
        internal const string Again = "Back, then Next, reads the file again and asks GitHub once more what sending " +
                                      "would write.";
        // The only addresses the window opens: the project's page, and a pull request on it.
        internal const string ProjectPage = "https://github.com/songyb111-gachon/codex-auto-resume-windows";
        internal const string PullRequest = @"^https://github\.com/songyb111-gachon/codex-auto-resume-windows/pull/[0-9]+$";

        readonly Ui ui;
        readonly ICore core;
        readonly bool unattended;       // --describe and --render: nothing is opened, and no question is asked
        readonly string version;
        readonly Label title;
        readonly Stack stack;
        readonly Label status;
        readonly Button back;
        readonly Button next;
        readonly Button send;
        readonly Button close;
        Control focusOn;

        int page = 1;
        bool busy;
        bool sending;
        bool noPython;
        JsonObject survey;
        string surveyRefused;
        string typed;
        string login;
        List<string> loginSaid = new List<string>();
        string loginRefused;
        bool asking;
        bool writeOver;
        JsonObject report;
        string reportRefused;
        byte[] shown;
        string shownSha;
        string shownText;
        string readRefused;
        string mismatch;
        string stepRefused;
        JsonObject web;
        JsonObject plan;
        JsonObject sent;
        string sendRefused;
        bool sendKept;
        bool haveRead;

        public ReportForm(Ui ui, ICore core, bool unattended, string version)
        {
            this.ui = ui;
            this.core = core;
            this.unattended = unattended;
            this.version = version;
            SuspendLayout();
            AutoScaleMode = AutoScaleMode.None;
            Font = ui.Font;
            Name = "window";
            Text = "codex-compat-reporter";
            AccessibleName = "codex-compat-reporter";
            StartPosition = FormStartPosition.CenterScreen;
            MinimumSize = new Size(ui.Px(520), ui.Px(400));
            Size = new Size(ui.Px(640), ui.Px(520));
            if (!unattended)
            {
                Rectangle area = Screen.PrimaryScreen.WorkingArea;
                MinimumSize = new Size(Math.Min(MinimumSize.Width, area.Width), Math.Min(MinimumSize.Height, area.Height));
                Size = new Size(Math.Min(Width, area.Width), Math.Min(Height, area.Height));
            }

            title = new Label();
            title.Name = "title";
            title.Font = ui.Heading;
            title.AutoSize = false;
            title.UseMnemonic = false;
            title.TabIndex = 0;
            stack = new Stack(ui);
            stack.Name = "page";
            stack.AccessibleName = "Page";
            stack.TabIndex = 1;
            status = new Label();
            status.Name = "status";
            status.AutoSize = false;
            status.UseMnemonic = false;
            status.AccessibleName = "What is happening";
            status.TabIndex = 2;
            back = Push("back", "< &Back", "Back", 3);
            next = Push("next", "&Next >", "Next", 4);
            // No access key: while a button has the focus, WinForms clicks the button whose access key is
            // typed even without Alt, and one stray S must not start a send.
            send = Push("send", "Send...", "Send", 5);
            close = Push("close", "&Close", "Close", 6);
            Controls.Add(title);
            Controls.Add(stack);
            Controls.Add(status);
            Controls.Add(back);
            Controls.Add(next);
            Controls.Add(send);
            Controls.Add(close);
            back.Click += delegate { GoBack(); };
            next.Click += delegate { GoOn(); };
            send.Click += delegate { SendIt(); };
            close.Click += delegate { Close(); };
            CancelButton = close;
            AcceptButton = next;
            UpdateButtons();
            ResumeLayout(false);
        }

        Button Push(string name, string text, string accessible, int tab)
        {
            Button button = new Button();
            button.Name = name;
            button.Text = text;
            button.AccessibleName = accessible;
            button.UseVisualStyleBackColor = true;
            button.AutoSizeMode = AutoSizeMode.GrowAndShrink;     // its preferred size is its text's alone
            button.TabIndex = tab;
            return button;
        }

        public int Page
        {
            get { return page; }
        }

        // ------------------------------------------------------------------------------- layout
        bool Shows(Button button)
        {
            if (button == next)
            {
                return page < 5;
            }
            if (button == send)
            {
                return page == 5 && plan != null && sent == null;
            }
            return true;
        }

        protected override void OnLayout(LayoutEventArgs e)
        {
            base.OnLayout(e);
            if (close == null)
            {
                return;                 // still being made
            }
            int margin = ui.Px(12);
            int gap = ui.Px(8);
            int width = Math.Max(1, ClientSize.Width - 2 * margin);
            title.SetBounds(margin, margin, width, title.GetPreferredSize(new Size(width, 0)).Height);
            int buttonHeight = 0;
            foreach (Button button in new Button[] { back, next, send, close })
            {
                if (Shows(button))
                {
                    buttonHeight = Math.Max(buttonHeight, ui.ButtonSize(button).Height);
                }
            }
            int x = ClientSize.Width - margin;
            int y = ClientSize.Height - margin - buttonHeight;
            foreach (Button button in new Button[] { close, send, next, back })
            {
                if (!Shows(button))
                {
                    continue;
                }
                int buttonWidth = ui.ButtonSize(button).Width;
                x -= buttonWidth;
                button.SetBounds(x, y, buttonWidth, buttonHeight);
                x -= ui.Px(6);
            }
            int line = TextRenderer.MeasureText("Ag", status.Font).Height;
            int statusHeight = Math.Max(line, status.Text.Length == 0 ? 0 : status.GetPreferredSize(new Size(width, 0)).Height);
            int statusTop = y - gap - statusHeight;
            status.SetBounds(margin, statusTop, width, statusHeight);
            int top = title.Bottom + gap;
            stack.SetBounds(margin, top, Math.Max(1, ClientSize.Width - margin - ui.Px(4)), Math.Max(1, statusTop - gap - top));
        }

        void UpdateButtons()
        {
            title.Text = "Step " + page + " of 5: " + Titles[page - 1];
            title.AccessibleName = title.Text;
            next.Visible = Shows(next);
            send.Visible = Shows(send);
            back.Enabled = !busy && page > 1 && sent == null;
            next.Enabled = !busy && CanGoOn();
            send.Enabled = !busy && haveRead;
            close.Enabled = !busy;
            AcceptButton = page < 5 ? next : (Shows(send) ? send : close);
            PerformLayout();
        }

        bool CanGoOn()
        {
            if (page == 1)
            {
                return survey != null && survey.Str("blocked") == null && !noPython && core.Found;
            }
            if (page == 2)
            {
                return true;
            }
            if (page == 3)
            {
                return asking || report != null;
            }
            if (page == 4)
            {
                return report != null;
            }
            return false;
        }

        // ----------------------------------------------------------------- running the reporter
        void Busy(string doing)
        {
            busy = true;
            status.Text = doing;
            UseWaitCursor = true;
            UpdateButtons();
        }

        void Idle()
        {
            busy = false;
            sending = false;
            status.Text = "";
            UseWaitCursor = false;
            UpdateButtons();
        }

        void Ask(string doing, string[] arguments, Action<Answer> then)
        {
            Busy(doing);
            core.Run(this, arguments, delegate(Answer answer)
            {
                Idle();
                if (answer.NoPython)
                {
                    noPython = true;
                    page = 1;
                    Build();
                    return;
                }
                then(answer);
            });
        }

        protected override void OnShown(EventArgs e)
        {
            base.OnShown(e);
            Start();
        }

        protected override void OnFormClosing(FormClosingEventArgs e)
        {
            // Stopped half-way, a send leaves on GitHub what it had written: it is let finish.
            if (busy && sending && e.CloseReason == CloseReason.UserClosing)
            {
                e.Cancel = true;
                status.Text = "Sending is under way: this window can be closed when it is done.";
                return;
            }
            base.OnFormClosing(e);
        }

        public void Start()
        {
            page = 1;
            Build();
            if (core.Found)
            {
                Ask("Looking at what this machine can show...", new string[] { "survey" }, delegate(Answer answer)
                {
                    if (answer.Ok)
                    {
                        survey = answer.Fields;
                        typed = survey.Str("default_login");
                    }
                    else
                    {
                        surveyRefused = answer.Refused;
                    }
                    Build();
                });
            }
        }

        public void GoOn()
        {
            if (busy || !CanGoOn())
            {
                return;
            }
            if (page == 1)
            {
                page = 2;
                loginRefused = null;
                Build();
            }
            else if (page == 2)
            {
                CheckLogin();
            }
            else if (page == 3)
            {
                if (asking)
                {
                    WriteReport(!writeOver);
                }
                else
                {
                    ToRead();
                }
            }
            else if (page == 4)
            {
                CheckShown();
            }
        }

        void GoBack()
        {
            if (busy || sent != null || page == 1)
            {
                return;
            }
            if (page == 5)
            {
                ToRead();
                return;
            }
            page -= 1;
            loginRefused = null;
            Build();
        }

        void CheckLogin()
        {
            Ask("Checking the login, and asking gh which login it is signed in as...",
                new string[] { "login", "--", typed ?? "" }, delegate(Answer answer)
            {
                if (answer.Ok)
                {
                    login = answer.Fields.Str("login");
                    loginSaid = answer.Fields.Strings("said");
                    loginRefused = null;
                    typed = login;
                    ToWrite();
                }
                else
                {
                    loginRefused = answer.Refused;
                    Build();
                }
            });
        }

        string ReportFileHere()
        {
            JsonObject file = survey == null ? null : survey.Obj("report_file");
            string path = file == null ? null : file.Str("path");
            return path != null && core.Exists(path) ? path : null;
        }

        void ToWrite()
        {
            page = 3;
            report = null;
            reportRefused = null;
            writeOver = false;
            asking = ReportFileHere() != null;
            Build();
            if (!asking)
            {
                WriteReport(true);
            }
        }

        // --keep unless the person chose to write a new one over the file there: a file is never written
        // over without that choice, and one kept is held to the project's rules and to the login first.
        void WriteReport(bool keep)
        {
            Ask(keep && asking ? "Reading the report that is already there..." : "Writing the report...",
                new string[] { "report", "--login", login, keep ? "--keep" : "--force", "--json" }, delegate(Answer answer)
            {
                if (answer.Ok)
                {
                    report = answer.Fields;
                    asking = false;
                }
                else
                {
                    reportRefused = answer.Refused;
                    asking = ReportFileHere() != null;
                }
                Build();
            });
        }

        void ToRead()
        {
            page = 4;
            stepRefused = null;
            mismatch = null;
            ReadShown();
            Build();
        }

        // The file's bytes, read once for the page: what it shows, and the SHA-256 that pins what is sent.
        void ReadShown()
        {
            shown = null;
            shownText = null;
            shownSha = null;
            readRefused = null;
            string path = report.Str("path");
            try
            {
                shown = core.Read(path);
                shownSha = Sha256(shown);
                shownText = Showable(shown);
            }
            catch (IOException error)
            {
                readRefused = path + " could not be read: " + error.Message;
            }
            catch (UnauthorizedAccessException error)
            {
                readRefused = path + " could not be read: " + error.Message;
            }
        }

        internal static string Sha256(byte[] bytes)
        {
            using (SHA256CryptoServiceProvider sha = new SHA256CryptoServiceProvider())
            {
                StringBuilder hex = new StringBuilder();
                foreach (byte b in sha.ComputeHash(bytes))
                {
                    hex.Append(b.ToString("x2", CultureInfo.InvariantCulture));
                }
                return hex.ToString();
            }
        }

        // The whole file as text, every character of it to be seen. The reporter writes a report in printable
        // ASCII alone (JSON with ensure_ascii), so any other character is an edit, and an edit control would
        // hide it, stop at it or draw it as nothing: a control character, a zero-width space or joiner, a
        // byte order mark, a mark that turns the text's direction. Each is shown instead: a control
        // character as its Unicode picture - CR too, so a line that ends in CR LF is told from one that ends
        // in LF - DEL as its own, and every other character outside printable ASCII as U+XXXX in
        // guillemets, which the reporter never writes either. Tab and LF are shown as they are.
        internal static string Showable(byte[] bytes)
        {
            string text = new UTF8Encoding(false, false).GetString(bytes);
            StringBuilder shown = new StringBuilder(text.Length);
            for (int i = 0; i < text.Length; i++)
            {
                char c = text[i];
                if (c == '\t' || c == '\n' || (c >= ' ' && c < '\u007f'))
                {
                    shown.Append(c);
                }
                else if (c < ' ')
                {
                    shown.Append((char)(0x2400 + c));
                }
                else if (c == '\u007f')
                {
                    shown.Append('\u2421');
                }
                else
                {
                    int point = c;
                    if (char.IsHighSurrogate(c) && i + 1 < text.Length && char.IsLowSurrogate(text[i + 1]))
                    {
                        point = char.ConvertToUtf32(c, text[i + 1]);
                        i++;
                    }
                    shown.Append('\u00ab').Append("U+").Append(point.ToString("X4", CultureInfo.InvariantCulture))
                         .Append('\u00bb');
                }
            }
            return shown.ToString();
        }

        // Next on the fourth page: the script reads the file again, as it would send it, and holds it to the
        // project's rules; what it read must be what was shown, byte for byte, or nothing goes on.
        void CheckShown()
        {
            if (shown == null)
            {
                ToRead();
                return;
            }
            Ask("Reading the file again, as it would be sent...",
                new string[] { "web-steps", report.Str("path"), "--login", login, "--json" }, delegate(Answer answer)
            {
                if (!answer.Ok)
                {
                    stepRefused = answer.Refused;
                    mismatch = null;
                    Build();
                }
                else if (answer.Fields.Str("sha256") != shownSha)
                {
                    ReadShown();
                    stepRefused = null;
                    mismatch = Mismatch;
                    Build();
                }
                else
                {
                    web = answer.Fields;
                    ToSend();
                }
            });
        }

        void ToSend()
        {
            page = 5;
            plan = null;
            sent = null;
            sendRefused = null;
            sendKept = false;
            haveRead = false;
            Build();
            if (web.Strings("why").Count > 0)
            {
                return;                 // gh cannot send it from here: the page says how to send it on the web
            }
            Ask("Asking GitHub what sending would write; nothing is written...",
                new string[] { "submit", report.Str("path"), "--login", login, "--sha256", shownSha, "--dry-run", "--json" },
                delegate(Answer answer)
            {
                if (answer.Ok && answer.Fields.Str("sha256") == shownSha)
                {
                    plan = answer.Fields;
                }
                else
                {
                    Refuse(answer.Ok ? Mismatch : answer.Refused, answer);
                }
                Build();
            });
        }

        void Refuse(string sentence, Answer answer)
        {
            sendRefused = sentence;
            // As the guide says it: after writes, or when the project is not taking reports yet, the report
            // stays here; after any other refusal, nothing was sent.
            sendKept = answer.Written.Count > 0 || answer.Exit == 3;
        }

        void SendIt()
        {
            if (busy || plan == null || !haveRead)
            {
                return;
            }
            if (!unattended)
            {
                using (ConfirmForm confirm = new ConfirmForm(ui, plan.Str("repository"), plan.Str("login"), shownSha))
                {
                    if (confirm.ShowDialog(this) != DialogResult.OK)
                    {
                        return;
                    }
                }
            }
            sending = true;
            List<string> arguments = new List<string>(new string[] { "submit", report.Str("path"), "--login", login,
                                                                     "--sha256", shownSha });
            // The writes this page listed, given back: the script writes exactly these, or nothing.
            foreach (string write in plan.Strings("writes"))
            {
                arguments.Add("--write=" + write);
            }
            arguments.Add("--yes");
            arguments.Add("--json");
            Ask("Sending the report to GitHub...", arguments.ToArray(), delegate(Answer answer)
            {
                haveRead = false;
                if (answer.Ok)
                {
                    sent = answer.Fields;
                }
                else
                {
                    // What was listed is no longer what sending would write - after a send refused half-way
                    // least of all - so Send goes with it: the list is asked for again, and read again.
                    plan = null;
                    Refuse(answer.Refused, answer);
                }
                Build();
            });
        }

        // ----------------------------------------------------------------------------- the pages
        void Build()
        {
            stack.Clear();
            focusOn = null;
            stack.SuspendLayout();
            if (page == 1)
            {
                BuildMachine();
            }
            else if (page == 2)
            {
                BuildLogin();
            }
            else if (page == 3)
            {
                BuildWrite();
            }
            else if (page == 4)
            {
                BuildRead();
            }
            else
            {
                BuildSend();
            }
            stack.ResumeLayout(false);
            UpdateButtons();
            stack.PerformLayout();
            Control first = focusOn ?? (AcceptButton as Control);
            if (first != null && first.CanFocus)
            {
                first.Focus();
            }
            else
            {
                ActiveControl = first;
            }
        }

        Label Words(string name, string text)
        {
            Label label = new Label();
            label.Name = name;
            label.AutoSize = false;
            label.UseMnemonic = false;
            label.Text = text;
            label.AccessibleName = text;
            return stack.Add(label);
        }

        TextArea Said(string name, string text, string accessible)
        {
            TextArea area = new TextArea(name, text, false, true);
            area.AccessibleName = accessible;
            area.AccessibleDescription = text;
            return stack.Add(area);
        }

        TextArea Listing(string name, string text, string accessible)
        {
            TextArea area = new TextArea(name, text, true, true);
            area.Font = ui.Mono;
            area.AccessibleName = accessible;
            return stack.Add(area);
        }

        // A path, whole: it breaks where the line ends, however long it is.
        TextArea PathBox(string name, string path, string accessible)
        {
            TextArea box = new TextArea(name, path ?? "", true, true);
            box.AccessibleName = accessible;
            return stack.Add(box);
        }

        Button Action(string name, string text, string accessible, EventHandler click)
        {
            Button button = Push(name, text, accessible, 0);
            button.Click += click;
            return stack.Add(button, true);
        }

        LinkLabel Link(string name, string text, string address)
        {
            LinkLabel link = new LinkLabel();
            link.Name = name;
            link.AutoSize = false;
            link.UseMnemonic = false;
            link.Text = text;
            link.AccessibleName = text;
            link.LinkClicked += delegate { OpenAddress(address); };
            return stack.Add(link, true);
        }

        static string Joined(List<string> lines)
        {
            return string.Join("\n", lines.ToArray());
        }

        void BuildMachine()
        {
            string shownVersion = survey != null && survey.Str("tool_version") != null ? survey.Str("tool_version") : version;
            Words("purpose", "codex-compat-reporter " + shownVersion + Purpose);
            Words("nothing", Nothing);
            if (!core.Found || noPython)
            {
                Said("missing", noPython ? LiveCore.NoPython : core.Missing, "Why the reporter cannot run");
            }
            else if (surveyRefused != null)
            {
                Said("refused", surveyRefused, "Why nothing can be shown");
            }
            else if (survey != null)
            {
                Listing("machine", Joined(survey.Strings("lines")), "What this machine can show");
                if (survey.Str("blocked") != null)
                {
                    Said("blocked", survey.Str("blocked"), "Why no report can be written here yet");
                }
            }
        }

        void BuildLogin()
        {
            Words("public", Public);
            string offered = survey == null ? null : survey.Str("default_login");
            if (offered != null)
            {
                Words("offered", string.Format(CultureInfo.InvariantCulture, Offered, offered));
            }
            Label label = Words("login_label", "&GitHub login:");
            label.UseMnemonic = true;
            label.AccessibleName = "GitHub login";
            TextBox box = new TextBox();
            box.Name = "login";
            box.MaxLength = 100;
            box.Text = typed ?? "";
            box.AccessibleName = "GitHub login";
            box.TextChanged += delegate { typed = box.Text; };
            stack.Add(box);
            focusOn = box;
            if (loginRefused != null)
            {
                Said("refused", loginRefused, "Why this login cannot be taken");
            }
        }

        void BuildWrite()
        {
            if (loginSaid.Count > 0)
            {
                Said("login_said", Joined(loginSaid), "About the login");
            }
            if (asking)
            {
                Said("already", survey.Obj("report_file").Str("already"), "A report is already here");
                RadioButton keep = Choice("keep", "&Keep it as it is", !writeOver);
                RadioButton over = Choice("over", "&Write a new one over it", writeOver);
                over.CheckedChanged += delegate { writeOver = over.Checked; };
                focusOn = writeOver ? over : keep;
            }
            if (report != null)
            {
                Words("said", report.Str("said") ?? "");
                Listing("facts", Joined(report.Strings("lines")), "What the report holds");
            }
            if (reportRefused != null)
            {
                Said("refused", reportRefused, "Why there is no report to read");
            }
        }

        RadioButton Choice(string name, string text, bool chosen)
        {
            RadioButton choice = new RadioButton();
            choice.Name = name;
            choice.Text = text;
            choice.AccessibleName = text.Replace("&", "");
            choice.Checked = chosen;
            choice.UseVisualStyleBackColor = true;
            return stack.Add(choice, true);
        }

        void BuildRead()
        {
            string path = report.Str("path");
            // Why the page is still here, first, where it is seen and read out: the page opens at its top.
            if (mismatch != null)
            {
                focusOn = Said("mismatch", mismatch, "The file changed after it was shown");
            }
            if (stepRefused != null)
            {
                focusOn = Said("refused", stepRefused, "Why it cannot be sent");
            }
            Words("short", Short);
            PathBox("path", path, "The report file");
            Action("notepad", "&Open in Notepad", "Open the report in Notepad", delegate { OpenInNotepad(path); });
            if (readRefused != null)
            {
                Said("unreadable", readRefused, "Why the report cannot be shown");
            }
            else
            {
                TextArea file = new TextArea("file", shownText, true, false);
                file.Font = ui.Mono;
                file.AccessibleName = "The whole report, as it would be sent";
                stack.Fill(file, ui.Px(120));
                TextArea digest = Said("sha256", "SHA-256 of what is shown: " + shownSha, "SHA-256 of what is shown");
                digest.Font = ui.Mono;
                if (shownSha != report.Str("sha256"))
                {
                    Said("changed", Changed, "The file has changed since it was written");
                }
            }
        }

        void BuildSend()
        {
            if (sent != null)
            {
                string address = sent.Str("url") ?? "";
                Words("opened", Opened);
                if (IsPullRequest(address))
                {
                    Link("pull_request", address, address);
                }
                else
                {
                    Said("pull_request", address, "The pull request's address");
                }
                Said("after", sent.Str("after") ?? "", "What happens next");
                return;
            }
            if (web == null)
            {
                return;
            }
            if (web.Strings("why").Count > 0)
            {
                BuildWeb();
                return;
            }
            if (sendRefused != null)
            {
                // Why nothing was sent, or what was, first, where it is seen and read out.
                focusOn = Said("refused", sendRefused, "Why it was not sent");
                Words("stays", sendKept ? Stays : Unsent);
                PathBox("path", report.Str("path"), "The report file");
                Words("again", Again);
            }
            else if (plan != null)
            {
                focusOn = Listing("checked", Joined(plan.Strings("checked")), "What was checked, and where it would go");
                Said("sending", plan.Str("sending") ?? "", "What sending writes to GitHub");
                List<string> writes = new List<string>();
                foreach (string write in plan.Strings("writes"))
                {
                    writes.Add("- " + write);
                }
                Said("writes", Joined(writes), "What sending writes to GitHub");
                CheckBox read = new CheckBox();
                read.Name = "have_read";
                read.Text = "I &have read it";
                read.AccessibleName = "I have read it";
                read.Checked = haveRead;
                read.UseVisualStyleBackColor = true;
                read.CheckedChanged += delegate
                {
                    haveRead = read.Checked;
                    UpdateButtons();
                };
                stack.Add(read, true);
                Words("if_closed", IfClosed);
                PathBox("path", report.Str("path"), "The report file");
            }
        }

        void BuildWeb()
        {
            int number = 0;
            foreach (string why in web.Strings("why"))
            {
                Said("why" + (++number), why, "Why this cannot send it");
            }
            Said("stays_here", web.Str("stays") ?? "", "Where the report is");
            string path = web.Str("file");
            PathBox("path", path, "The report file");
            Action("notepad", "&Open in Notepad", "Open the report in Notepad", delegate { OpenInNotepad(path); });
            Said("intro", web.Str("intro") ?? "", "How to send it on the web");
            number = 0;
            foreach (JsonObject step in web.Objects("steps"))
            {
                number++;
                Said("step" + number, number + ". " + (step.Str("text") ?? ""), "Step " + number);
                string copy = step.Str("copy");
                if (!string.IsNullOrEmpty(copy))
                {
                    stack.Indent(stack.Add(new CopyRow(ui, "copy" + number, copy, "What to type in step " + number)), ui.Px(20));
                }
                int note = 0;
                foreach (string said in step.Strings("notes"))
                {
                    stack.Indent(Said("note" + number + "_" + (++note), said, "About step " + number), ui.Px(20));
                }
            }
            Said("then", web.Str("then") ?? "", "What happens next");
            if (web.Str("project_page") == ProjectPage)
            {
                Link("project_page", "Open the project's page on GitHub", ProjectPage);
            }
        }

        // ------------------------------------------------------------------- what it opens
        internal static bool IsPullRequest(string address)
        {
            if (address == null)
            {
                return false;
            }
            // $ also matches before a last line break: the match must be the whole address.
            Match found = Regex.Match(address, PullRequest, RegexOptions.CultureInvariant);
            return found.Success && found.Value == address;
        }

        // A validated https address, opened by the shell in the default browser; nothing else is opened so.
        void OpenAddress(string address)
        {
            if (unattended || !(IsPullRequest(address) || address == ProjectPage))
            {
                return;
            }
            try
            {
                ProcessStartInfo browser = new ProcessStartInfo(address);
                browser.UseShellExecute = true;
                Process.Start(browser);
            }
            catch (Win32Exception)
            {
                status.Text = "The browser could not be started: open " + address + " yourself.";
            }
        }

        // Notepad, by its full path in the Windows folder: a GUI program, so no console.
        void OpenInNotepad(string path)
        {
            if (unattended || string.IsNullOrEmpty(path))
            {
                return;
            }
            string windows = Environment.GetFolderPath(Environment.SpecialFolder.Windows);
            if (string.IsNullOrEmpty(windows))
            {
                windows = @"C:\Windows";
            }
            try
            {
                ProcessStartInfo notepad = new ProcessStartInfo(Path.Combine(windows, "System32", "notepad.exe"),
                                                                LiveCore.Quote(path));
                notepad.UseShellExecute = false;
                Process.Start(notepad);
            }
            catch (Win32Exception)
            {
                status.Text = NoNotepad;
            }
        }

        // ------------------------------------------------------------------ for the test hooks
        // Where the window would be after the person went on to `target`, the reporter answering from a
        // fixture: ticked "I have read it" when told to, and sent when the fixture holds what sending said.
        internal void Drive(int target, bool read, bool sendIt)
        {
            Start();
            for (int guard = 0; guard < 8 && page < target; guard++)
            {
                int before = page;
                bool wasAsking = asking;
                GoOn();
                if (page == before && !(page == 3 && wasAsking))
                {
                    break;
                }
            }
            if (page == 5 && plan != null && (read || sendIt))
            {
                haveRead = true;
                Build();
            }
            if (page == 5 && sendIt)
            {
                SendIt();
            }
        }

        internal string State()
        {
            if (page != 5)
            {
                return page == 3 && asking ? "asking" : "page";
            }
            if (sent != null)
            {
                return "sent";
            }
            if (web != null && web.Strings("why").Count > 0)
            {
                return "web";
            }
            return plan != null && sendRefused == null ? "plan" : "refused";
        }

        internal JsonObject Plan
        {
            get { return plan; }
        }

        internal string ShownSha
        {
            get { return shownSha; }
        }
    }
}
