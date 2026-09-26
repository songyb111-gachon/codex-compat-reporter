// Report.exe: double-click it, and the reporter's guide opens as a window.
//
// Two test hooks, used by tests/test_window.py and by the pictures, with no Python and nothing of this
// machine read - the reporter's answers come from a fixture file:
//
//   Report.exe --fixture <json> --describe <1-5 | confirm> [--scale 1.25|1.5|2] [--size min] [--have-read]
//       prints, as JSON, every control the page shows: its name, text, bounds, preferred size, whether its
//       text fits, tab order, accessible name and whether it is enabled. No window is shown. Given lists -
//       --describe 1,2,3 --scale 1,1.5 --size default,min - it prints a JSON array, one object for each.
//   Report.exe --fixture <json> --render <1-5 | confirm> --out <png> [--scale ...] [--size min] [--have-read]
//       draws that page off-screen into a PNG.
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
                Application.Run(new ReportForm(Ui.ForScreen(), new LiveCore(), false, Application.ProductVersion));
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

    // Where the window is after it was driven: the page it is at, and in which of that page's states.
    internal sealed class Where
    {
        public readonly string State;
        public readonly int At;

        public Where(string state, int at)
        {
            State = state;
            At = at;
        }
    }

    internal static class Hooks
    {
        const string Usage = "usage: Report.exe --fixture <json> (--describe <1-5|confirm> | --render <1-5|confirm> " +
                             "--out <png>) [--scale 1|1.25|1.5|2] [--size default|min] [--have-read]\n" +
                             "--describe takes lists too - 1,2,3 and --scale 1,2 and --size default,min - and then " +
                             "prints a JSON array, one object for each page at each scale and size.\n" +
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

        public static int Run(string[] arguments)
        {
            string fixturePath = null;
            string describe = null;
            string render = null;
            string output = null;
            string scaleList = "1";
            string sizeList = "default";
            bool haveRead = false;
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
                        Form form = Made(fixture, page, scale, size == "min", haveRead);
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
                                described.Add(Describe(form, page, scale, size));
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
        // out and drawn off-screen, never shown. For "confirm", the question asked before sending.
        static Form Made(JsonObject fixture, string page, float scale, bool smallest, bool haveRead)
        {
            Ui ui = Ui.ForScale(scale);
            ReportForm wizard = new ReportForm(ui, new FixtureCore(fixture), true, Application.ProductVersion);
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
                form.Tag = new Where("confirm", 5);
            }
            else
            {
                wizard.Drive(int.Parse(page, CultureInfo.InvariantCulture), haveRead, fixture.Has("sent"));
                form.Tag = new Where(wizard.State(), wizard.Page);
            }
            Prepare(form);
            return form;
        }

        // Every window handle made, and every layout done, as they would be on the screen.
        static void Prepare(Form form)
        {
            Handles(form);
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

        static Ordered Describe(Form form, string what, float scale, string size)
        {
            List<object> controls = new List<object>();
            Walk(form, form, new List<int>(), new Rectangle(Point.Empty, form.ClientSize), controls);
            Control focused = form.ActiveControl;
            return new Ordered()
                .Add("page", what)
                .Add("state", ((Where)form.Tag).State)
                .Add("at", ((Where)form.Tag).At)
                .Add("scale", (double)scale)
                .Add("size", size)
                .Add("title", form.Text)
                .Add("client", Box(new Rectangle(Point.Empty, form.ClientSize)))
                .Add("minimum", Box(new Rectangle(Point.Empty, form.MinimumSize)))
                .Add("accept", form.AcceptButton is Control ? ((Control)form.AcceptButton).Name : null)
                .Add("cancel", form.CancelButton is Control ? ((Control)form.CancelButton).Name : null)
                .Add("focus", focused == null ? null : focused.Name)
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
                    .Add("enabled", child.Enabled));
                if (child.Controls.Count > 0)
                {
                    Point inside = form.PointToClient(child.PointToScreen(Point.Empty));
                    Rectangle client = Rectangle.Intersect(clip, new Rectangle(inside, child.ClientSize));
                    Walk(child, form, tab, client, into);
                }
            }
        }

        // Whether a control's text is all inside it: for a label its wrapped size at its width, for a
        // button or a box to tick its one line, for an edit control every line of it or, where it
        // scrolls, at least one.
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
                return control.Height >= box.PreferredHeight;
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
                    page.Save(output, ImageFormat.Png);
                }
            }
        }
    }
}
