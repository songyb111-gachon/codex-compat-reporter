// Report.exe: double-click it, and the reporter's guide opens as a window.
//
// Two test hooks, used by tests/test_window.py and by the pictures, with no Python and nothing of this
// machine read - the reporter's answers come from a fixture file:
//
//   Report.exe --fixture <json> --describe <1-5 | confirm> [--scale 1.25|1.5|2] [--size min] [--have-read]
//       prints, as JSON, every control the page shows: its name, text, bounds, preferred size, whether its
//       text fits, tab order, accessible name, access key and whether it is enabled - and each run of the
//       reporter the window asked for on the way, its arguments as given. No window is shown. Given lists -
//       --describe 1,2,3 --scale 1,1.5 --size default,min - it prints a JSON array, one object for each.
//   Report.exe --fixture <json> --render <1-5 | confirm> --out <png> [--scale ...] [--size min] [--have-read]
//       draws that page off-screen into a PNG, with the scroll bar of each box that scrolls, and its access
//       keys and focus hidden, as in a window opened with the mouse.
//
// Two more, for the README's pictures (tools/make_window_pictures.py): --font <family> draws in that
// family, at the system font's size, as a Windows whose message font it is would - Segoe UI, Windows'
// own, where this machine's is another; --end shows the page scrolled to its end, as after reading down it.
//
// Four conditions of other machines, which the tests bring about here (tests/test_window.py), read from
// the environment with --describe and --render only - never by the window, nor by --where:
//   CODEX_COMPAT_REPORTER_TEST_AREA=<width>x<height>   a working area of that size, at the corner of this
//       screen's, in its place: a small screen's, such as the 1024 x 720 of GitHub's runners;
//   CODEX_COMPAT_REPORTER_TEST_STYLES=none   no visual styles, as in a session Windows draws none in, a
//       service's such as a runner's: the controls are classic, and so is each scroll bar --render draws;
//   CODEX_COMPAT_REPORTER_TEST_FRAME=<a FormBorderStyle>   another frame and caption around the window,
//       FixedSingle's or none at all, as a Windows of other metrics draws them: the inside is what it keeps;
//   CODEX_COMPAT_REPORTER_TEST_CUES=shown   the access keys and the focus shown when the window is made, as
//       Windows makes a window after a key was the last input: a page is drawn as opened with the mouse.
// Any other value is refused, and so is an area larger than this screen's working area, which WinForms
// would fit the window to instead: a condition asked for is brought about, or nothing is drawn.
//
// And one that reads this machine, to say where the window would take the reporter from, and starts
// nothing: Report.exe --where prints, as JSON, the folder it counts as its own, the script it would run,
// the Python it would run it with, and what it would say is missing.
//
// C# 5 only: this is compiled by the in-box csc (tools/make_exe.py).
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Drawing.Imaging;
using System.Globalization;
using System.IO;
using System.Reflection;
using System.Text;
using System.Windows.Forms;
using System.Windows.Forms.VisualStyles;

namespace CodexCompatReporter
{
    internal static class Program
    {
        [STAThread]
        static int Main(string[] arguments)
        {
            Application.EnableVisualStyles();
            Application.SetCompatibleTextRenderingDefault(false);
            if (arguments.Length == 0)
            {
                Application.Run(new ReportForm(Ui.ForScreen(), new LiveCore(), false, Application.ProductVersion,
                                               Screen.PrimaryScreen.WorkingArea));
                return 0;
            }
            try
            {
                return Hooks.Run(arguments);
            }
            catch (Exception error)
            {
                Hooks.Error(error.GetType().Name + ": " + error.Message);
                return 1;
            }
        }
    }

    // Where the window is after it was driven: the page it is at, in which of that page's states, and
    // what it asked the reporter on the way, each run's arguments as the window gave them; and whether
    // Windows made it with its access keys shown.
    internal sealed class Where
    {
        public readonly string State;
        public readonly int At;
        public readonly List<string[]> Asked;
        public bool CuesWhenMade;

        public Where(string state, int at, List<string[]> asked)
        {
            State = state;
            At = at;
            Asked = asked;
        }
    }

    internal static class Hooks
    {
        const string Usage = "usage: Report.exe --fixture <json> (--describe <1-5|confirm> | --render <1-5|confirm> " +
                             "--out <png>) [--scale 1|1.25|1.5|2] [--size default|min] [--have-read] [--font <family>] " +
                             "[--end]\n" +
                             "--describe takes lists too - 1,2,3 and --scale 1,2 and --size default,min - and then " +
                             "prints a JSON array, one object for each page at each scale and size.\n" +
                             "Report.exe --where: where it would take the reporter and Python from, as JSON.\n" +
                             "Without arguments it opens the window.";

        public static void Error(string text)
        {
            Write(Console.OpenStandardError(), text + "\n");
        }

        static void Write(Stream stream, string text)
        {
            byte[] bytes = new UTF8Encoding(false).GetBytes(text);
            stream.Write(bytes, 0, bytes.Length);
            stream.Flush();
        }

        static bool IsPage(string what)
        {
            return what == "confirm" || what == "1" || what == "2" || what == "3" || what == "4" || what == "5";
        }

        const string AreaVariable = "CODEX_COMPAT_REPORTER_TEST_AREA";
        const string StylesVariable = "CODEX_COMPAT_REPORTER_TEST_STYLES";
        const string FrameVariable = "CODEX_COMPAT_REPORTER_TEST_FRAME";
        const string CuesVariable = "CODEX_COMPAT_REPORTER_TEST_CUES";
        const int WM_UPDATEUISTATE = 0x0128;
        const int WM_QUERYUISTATE = 0x0129;
        const int UIS_SET = 1;
        const int UIS_CLEAR = 2;
        const int UISF_HIDEFOCUS = 0x1;
        const int UISF_HIDEACCEL = 0x2;

        // The working area the window is fitted to: this screen's, or the smaller one the tests ask for.
        static bool Area(out Rectangle area)
        {
            area = Screen.PrimaryScreen.WorkingArea;
            string asked = Environment.GetEnvironmentVariable(AreaVariable);
            if (asked == null)
            {
                return true;
            }
            string[] sides = asked.Split('x');
            int width;
            int height;
            if (sides.Length != 2 ||
                !int.TryParse(sides[0], NumberStyles.None, CultureInfo.InvariantCulture, out width) ||
                !int.TryParse(sides[1], NumberStyles.None, CultureInfo.InvariantCulture, out height) ||
                width < 1 || height < 1 || width > area.Width || height > area.Height)
            {
                Error(AreaVariable + " is <width>x<height>, no larger than this screen's working area, " + area.Width +
                      "x" + area.Height + ": " + asked);
                return false;
            }
            area = new Rectangle(area.Location, new Size(width, height));
            return true;
        }

        public static int Run(string[] arguments)
        {
            if (arguments.Length == 1 && arguments[0] == "--where")
            {
                Write(Console.OpenStandardOutput(), Json.Write(new LiveCore().Where()) + "\n");
                return 0;
            }
            string fixturePath = null;
            string describe = null;
            string render = null;
            string output = null;
            string scaleList = "1";
            string sizeList = "default";
            bool haveRead = false;
            string family = null;
            bool end = false;
            for (int i = 0; i < arguments.Length; i++)
            {
                string argument = arguments[i];
                bool more = i + 1 < arguments.Length;
                if (argument == "--fixture" && more)
                {
                    fixturePath = arguments[++i];
                }
                else if (argument == "--describe" && more)
                {
                    describe = arguments[++i];
                }
                else if (argument == "--render" && more)
                {
                    render = arguments[++i];
                }
                else if (argument == "--out" && more)
                {
                    output = arguments[++i];
                }
                else if (argument == "--scale" && more)
                {
                    scaleList = arguments[++i];
                }
                else if (argument == "--size" && more)
                {
                    sizeList = arguments[++i];
                }
                else if (argument == "--have-read")
                {
                    haveRead = true;
                }
                else if (argument == "--font" && more)
                {
                    family = arguments[++i];
                }
                else if (argument == "--end")
                {
                    end = true;
                }
                else
                {
                    Error(Usage);
                    return 2;
                }
            }
            string[] pages = (describe ?? render ?? "").Split(',');
            string[] sizes = sizeList.Split(',');
            List<float> scales = new List<float>();
            foreach (string text in scaleList.Split(','))
            {
                float scale;
                if (!float.TryParse(text, NumberStyles.Float, CultureInfo.InvariantCulture, out scale) || scale < 1f || scale > 3f)
                {
                    Error(Usage);
                    return 2;
                }
                scales.Add(scale);
            }
            bool well = fixturePath != null && (describe == null) != (render == null) && (render == null || output != null);
            foreach (string page in pages)
            {
                well = well && IsPage(page);
            }
            foreach (string size in sizes)
            {
                well = well && (size == "default" || size == "min");
            }
            if (!well || (render != null && pages.Length * scales.Count * sizes.Length != 1))
            {
                Error(Usage);
                return 2;
            }
            Rectangle area;
            if (!Area(out area))
            {
                return 2;
            }
            string styles = Environment.GetEnvironmentVariable(StylesVariable);
            string frame = Environment.GetEnvironmentVariable(FrameVariable);
            string cues = Environment.GetEnvironmentVariable(CuesVariable);
            if ((styles != null && styles != "none") || (cues != null && cues != "shown") ||
                (frame != null && (frame.Trim() != frame || !Enum.IsDefined(typeof(FormBorderStyle), frame))))
            {
                Error(StylesVariable + " is none and " + CuesVariable + " shown when they are set, and " +
                      FrameVariable + " one of " + string.Join(", ", Enum.GetNames(typeof(FormBorderStyle))));
                return 2;
            }
            if (styles != null)
            {
                Application.VisualStyleState = VisualStyleState.NoneEnabled;
            }
            JsonObject fixture = JsonObject.From(Json.Parse(File.ReadAllText(fixturePath, new UTF8Encoding(false))));
            if (fixture == null)
            {
                Error("the fixture is not one JSON object");
                return 2;
            }
            List<object> described = new List<object>();
            foreach (string page in pages)
            {
                foreach (float scale in scales)
                {
                    foreach (string size in sizes)
                    {
                        Form form = Made(fixture, page, scale, size == "min", haveRead, family, end, area,
                                         frame == null ? (FormBorderStyle?)null
                                                       : (FormBorderStyle)Enum.Parse(typeof(FormBorderStyle), frame),
                                         cues != null);
                        if (form == null)
                        {
                            Error("the fixture does not reach the question asked before sending");
                            return 2;
                        }
                        using (form)
                        {
                            if (render != null)
                            {
                                Render(form, output);
                            }
                            else
                            {
                                described.Add(Describe(form, page, scale, size, area));
                            }
                        }
                    }
                }
            }
            if (describe != null)
            {
                Write(Console.OpenStandardOutput(), Json.Write(described.Count == 1 ? described[0] : described) + "\n");
            }
            return 0;
        }

        // The window at a page, as the person would find it there with the fixture's answers: made, laid
        // out and drawn off-screen, never shown. For "confirm", the question asked before sending. With
        // `end`, the page scrolled to its end; with a `frame`, in that frame, and fitted again; with `cues`,
        // made as after a key.
        static Form Made(JsonObject fixture, string page, float scale, bool smallest, bool haveRead, string family,
                         bool end, Rectangle area, FormBorderStyle? frame, bool cues)
        {
            Ui ui = Ui.ForScale(scale, family);
            FixtureCore core = new FixtureCore(fixture);
            ReportForm wizard = new ReportForm(ui, core, true, Application.ProductVersion, area);
            if (frame != null)
            {
                wizard.FormBorderStyle = frame.Value;
                wizard.Fit(area);
            }
            if (smallest)
            {
                wizard.Size = wizard.MinimumSize;
            }
            Form form = wizard;
            if (page == "confirm")
            {
                wizard.Drive(5, true, false);
                JsonObject plan = wizard.Plan;
                string sha256 = wizard.ShownSha;
                wizard.Dispose();
                if (plan == null)
                {
                    return null;
                }
                form = new ConfirmForm(ui, plan.Str("repository"), plan.Str("login"), sha256);
                form.Tag = new Where("confirm", 5, core.Asked);
            }
            else
            {
                wizard.Drive(int.Parse(page, CultureInfo.InvariantCulture), haveRead, fixture.Has("sent"));
                form.Tag = new Where(wizard.State(), wizard.Page, core.Asked);
            }
            Prepare(form, cues);
            if (end)
            {
                foreach (Control found in form.Controls.Find("page", false))
                {
                    // The row lowest on the page, brought into view: the rows move with it. (AutoScrollPosition
                    // is not set on a control never shown, which is never Created, and a layout of a window
                    // never shown scrolls it back to the top, so none follows.)
                    Control last = null;
                    foreach (Control row in found.Controls)
                    {
                        if (last == null || row.Bottom > last.Bottom)
                        {
                            last = row;
                        }
                    }
                    ScrollableControl scrolled = found as ScrollableControl;
                    if (scrolled != null && last != null)
                    {
                        scrolled.ScrollControlIntoView(last);
                    }
                }
            }
            return form;
        }

        // Every window handle made, and every layout done, as they would be on the screen - with the access
        // keys and the focus hidden, as in a window opened with the mouse, the way Report.exe is opened.
        // Windows makes a window with them shown when a key was the last input on the machine, so a page
        // drawn without this would show them or not by what was last done here, a click or a key.
        static void Prepare(Form form, bool cues)
        {
            Handles(form);
            if (cues)
            {
                Cues(form, UIS_CLEAR);
            }
            ((Where)form.Tag).CuesWhenMade = CuesShown(form);
            Cues(form, UIS_SET);
            for (int pass = 0; pass < 2; pass++)
            {
                Layouts(form);
                ConfirmForm confirm = form as ConfirmForm;
                if (confirm != null)
                {
                    confirm.Arrange();
                }
            }
        }

        // Sets (UIS_SET) or clears (UIS_CLEAR) the window's hiding of its access keys and focus, and so
        // its controls': Windows passes the message on to each of them.
        static void Cues(Form form, int action)
        {
            int hidden = UISF_HIDEFOCUS | UISF_HIDEACCEL;
            Native.SendMessage(form.Handle, WM_UPDATEUISTATE, new IntPtr(action | hidden << 16), IntPtr.Zero);
        }

        // Whether the window shows its access keys, as Windows keeps it.
        static bool CuesShown(Form form)
        {
            return (Native.SendMessage(form.Handle, WM_QUERYUISTATE, IntPtr.Zero, IntPtr.Zero).ToInt32() &
                    UISF_HIDEACCEL) == 0;
        }

        static void Handles(Control control)
        {
            IntPtr made = control.Handle;
            foreach (Control child in control.Controls)
            {
                Handles(child);
            }
        }

        static void Layouts(Control control)
        {
            control.PerformLayout();
            foreach (Control child in control.Controls)
            {
                Layouts(child);
            }
        }

        // A control's own Visible, whatever its window's: the window is never shown here.
        static readonly MethodInfo GetState = typeof(Control).GetMethod("GetState", BindingFlags.Instance | BindingFlags.NonPublic,
                                                                        null, new Type[] { typeof(int) }, null);

        static bool Shown(Control control)
        {
            return GetState == null ? control.Visible : (bool)GetState.Invoke(control, new object[] { 2 });
        }

        static List<object> Box(Rectangle box)
        {
            List<object> found = new List<object>();
            found.Add(box.X);
            found.Add(box.Y);
            found.Add(box.Width);
            found.Add(box.Height);
            return found;
        }

        // What the page shows, and where: the window's inside ("client"), the least it can be made
        // ("minimum", an inside too), the frame and caption Windows draws around it, the working area it
        // was fitted to, whether Windows draws it in visual styles, and whether it shows its access keys, and
        // showed them when it was made.
        static Ordered Describe(Form form, string what, float scale, string size, Rectangle area)
        {
            Size frame = form.Size - form.ClientSize;
            List<object> around = new List<object>();
            around.Add(frame.Width);
            around.Add(frame.Height);
            List<object> controls = new List<object>();
            Walk(form, form, new List<int>(), new Rectangle(Point.Empty, form.ClientSize), controls);
            Control focused = form.ActiveControl;
            List<object> asked = new List<object>();
            foreach (string[] run in ((Where)form.Tag).Asked)
            {
                asked.Add(new List<object>(run));
            }
            return new Ordered()
                .Add("page", what)
                .Add("state", ((Where)form.Tag).State)
                .Add("at", ((Where)form.Tag).At)
                .Add("scale", (double)scale)
                .Add("size", size)
                .Add("title", form.Text)
                .Add("client", Box(new Rectangle(Point.Empty, form.ClientSize)))
                .Add("minimum", form.MinimumSize.IsEmpty ? null
                                                         : Box(new Rectangle(Point.Empty, form.MinimumSize - frame)))
                .Add("frame", around)
                .Add("area", Box(area))
                .Add("visual_styles", Application.RenderWithVisualStyles)
                .Add("keyboard_cues", CuesShown(form))
                .Add("keyboard_cues_when_made", ((Where)form.Tag).CuesWhenMade)
                .Add("accept", form.AcceptButton is Control ? ((Control)form.AcceptButton).Name : null)
                .Add("cancel", form.CancelButton is Control ? ((Control)form.CancelButton).Name : null)
                .Add("focus", focused == null ? null : focused.Name)
                .Add("asked", asked)
                .Add("controls", controls);
        }

        static void Walk(Control parent, Form form, List<int> path, Rectangle clip, List<object> into)
        {
            List<Control> children = new List<Control>();
            foreach (Control child in parent.Controls)
            {
                children.Add(child);
            }
            children.Sort(delegate(Control a, Control b) { return a.TabIndex.CompareTo(b.TabIndex); });
            foreach (Control child in children)
            {
                if (!Shown(child))
                {
                    continue;
                }
                Point origin = form.PointToClient(parent.PointToScreen(child.Location));
                Rectangle bounds = new Rectangle(origin, child.Size);
                Rectangle seen = Rectangle.Intersect(bounds, clip);
                List<int> tab = new List<int>(path);
                tab.Add(child.TabIndex);
                Size preferred;
                bool fits = Fits(child, out preferred);
                List<object> tabs = new List<object>();
                foreach (int index in tab)
                {
                    tabs.Add(index);
                }
                into.Add(new Ordered()
                    .Add("name", child.Name)
                    .Add("type", child.GetType().Name)
                    .Add("text", child.Text)
                    .Add("bounds", Box(bounds))
                    .Add("visible", seen.Width > 0 && seen.Height > 0 ? Box(seen) : null)
                    .Add("preferred", Box(new Rectangle(Point.Empty, preferred)))
                    .Add("fits", fits)
                    .Add("container", child.Controls.Count > 0)
                    .Add("tab", tabs)
                    .Add("tab_stop", child.TabStop)
                    .Add("checked", child is CheckBox ? (object)((CheckBox)child).Checked
                                    : child is RadioButton ? (object)((RadioButton)child).Checked : null)
                    .Add("accessible_name", child.AccessibleName)
                    .Add("mnemonic", Mnemonic(child))
                    .Add("enabled", child.Enabled));
                if (child.Controls.Count > 0)
                {
                    Point inside = form.PointToClient(child.PointToScreen(Point.Empty));
                    Rectangle client = Rectangle.Intersect(clip, new Rectangle(inside, child.ClientSize));
                    Walk(child, form, tab, client, into);
                }
            }
        }

        // The access key a control answers to, upper-cased: the character after a lone & in its text, where
        // the control reads & so; null when it has none.
        static string Mnemonic(Control control)
        {
            ButtonBase button = control as ButtonBase;
            Label label = control as Label;
            if (!(button != null ? button.UseMnemonic : label != null && label.UseMnemonic))
            {
                return null;
            }
            string text = control.Text ?? "";
            for (int i = 0; i + 1 < text.Length; i++)
            {
                if (text[i] != '&')
                {
                    continue;
                }
                if (text[i + 1] == '&')
                {
                    i++;
                    continue;
                }
                return text.Substring(i + 1, 1).ToUpperInvariant();
            }
            return null;
        }

        // Whether a control's text is all inside it: for a label its wrapped size at its width, for a
        // button or a box to tick its one line, for an edit control every line of it or, where it
        // scrolls, at least one - and for a one-line edit control, its whole width too.
        static bool Fits(Control control, out Size preferred)
        {
            TextArea area = control as TextArea;
            if (area != null)
            {
                preferred = new Size(control.Width, area.Grows ? area.LineCount() * area.LineHeight() + control.Height -
                                                                 control.ClientSize.Height : control.Height);
                return area.Fits();
            }
            TextBox box = control as TextBox;
            if (box != null)
            {
                preferred = new Size(control.Width, box.PreferredHeight);
                return control.Height >= box.PreferredHeight && Native.WholeOnOneLine(box);
            }
            if (control is ButtonBase)
            {
                preferred = control.GetPreferredSize(Size.Empty);
                return preferred.Width <= control.Width && preferred.Height <= control.Height;
            }
            if (control is Label)
            {
                preferred = control.GetPreferredSize(new Size(control.Width, 0));
                return preferred.Width <= control.Width && preferred.Height <= control.Height;
            }
            preferred = control.Size;
            return true;
        }

        // The page as it would be on the screen, drawn off-screen: the window's inside, without its frame.
        static void Render(Form form, string output)
        {
            using (Bitmap whole = new Bitmap(form.Width, form.Height))
            {
                form.DrawToBitmap(whole, new Rectangle(Point.Empty, form.Size));
                int border = (form.Width - form.ClientSize.Width) / 2;
                Rectangle client = new Rectangle(border, form.Height - form.ClientSize.Height - border,
                                                 form.ClientSize.Width, form.ClientSize.Height);
                using (Bitmap page = whole.Clone(client, PixelFormat.Format24bppRgb))
                {
                    using (Graphics graphics = Graphics.FromImage(page))
                    {
                        ScrollBars(form, form, graphics, new Rectangle(Point.Empty, form.ClientSize));
                    }
                    page.Save(output, ImageFormat.Png);
                }
            }
        }

        // An edit control draws its scroll bar on the screen only, never into a bitmap, which keeps a blank
        // strip in its place: each box that scrolls has it drawn here, where the screen has it, in the
        // system's style and at the line its text is scrolled to, so a picture shows the box holds more.
        static void ScrollBars(Control parent, Form form, Graphics graphics, Rectangle clip)
        {
            foreach (Control child in parent.Controls)
            {
                if (!Shown(child))
                {
                    continue;
                }
                Point origin = form.PointToClient(parent.PointToScreen(child.Location));
                Point inside = form.PointToClient(child.PointToScreen(Point.Empty));
                TextArea area = child as TextArea;
                if (area != null && !area.Grows)
                {
                    int border = inside.X - origin.X;
                    int left = inside.X + child.ClientSize.Width;
                    Rectangle bar = new Rectangle(left, inside.Y, origin.X + child.Width - border - left,
                                                  child.ClientSize.Height);
                    int shown = Math.Max(1, child.ClientSize.Height / area.LineHeight());
                    graphics.SetClip(clip);
                    ScrollBar(graphics, bar, area.LineCount(), shown, area.FirstLine());
                    graphics.ResetClip();
                }
                if (child.Controls.Count > 0)
                {
                    ScrollBars(child, form, graphics, Rectangle.Intersect(clip, new Rectangle(inside, child.ClientSize)));
                }
            }
        }

        static void ScrollBar(Graphics graphics, Rectangle bar, int lines, int shown, int first)
        {
            if (bar.Width <= 0 || bar.Height <= 0)
            {
                return;
            }
            bool scrolls = lines > shown;
            int arrow = Math.Min(SystemInformation.VerticalScrollBarArrowHeight, bar.Height / 2);
            Rectangle up = new Rectangle(bar.X, bar.Y, bar.Width, arrow);
            Rectangle down = new Rectangle(bar.X, bar.Bottom - arrow, bar.Width, arrow);
            Rectangle track = new Rectangle(bar.X, up.Bottom, bar.Width, Math.Max(0, down.Top - up.Bottom));
            Rectangle thumb = Rectangle.Empty;
            if (scrolls && track.Height > 0)
            {
                int tall = Math.Min(track.Height, Math.Max(SystemInformation.VerticalScrollBarThumbHeight,
                                                           track.Height * shown / lines));
                int top = track.Y + (track.Height - tall) * Math.Min(first, lines - shown) / (lines - shown);
                thumb = new Rectangle(bar.X, top, bar.Width, tall);
            }
            if (ScrollBarRenderer.IsSupported)
            {
                ScrollBarRenderer.DrawUpperVerticalTrack(graphics, track, scrolls ? ScrollBarState.Normal
                                                                                  : ScrollBarState.Disabled);
                ScrollBarRenderer.DrawArrowButton(graphics, up, scrolls ? ScrollBarArrowButtonState.UpNormal
                                                                        : ScrollBarArrowButtonState.UpDisabled);
                ScrollBarRenderer.DrawArrowButton(graphics, down, scrolls ? ScrollBarArrowButtonState.DownNormal
                                                                          : ScrollBarArrowButtonState.DownDisabled);
                if (!thumb.IsEmpty)
                {
                    ScrollBarRenderer.DrawVerticalThumb(graphics, thumb, ScrollBarState.Normal);
                    ScrollBarRenderer.DrawVerticalThumbGrip(graphics, thumb, ScrollBarState.Normal);
                }
            }
            else
            {
                using (Brush brush = new SolidBrush(SystemColors.ScrollBar))
                {
                    graphics.FillRectangle(brush, track);
                }
                ButtonState state = scrolls ? ButtonState.Normal : ButtonState.Inactive;
                ControlPaint.DrawScrollButton(graphics, up, ScrollButton.Up, state);
                ControlPaint.DrawScrollButton(graphics, down, ScrollButton.Down, state);
                if (!thumb.IsEmpty)
                {
                    ControlPaint.DrawButton(graphics, thumb, ButtonState.Normal);
                }
            }
        }
    }
}
