// How the window is laid out: every size from the system font and one scale, text that wraps and scrolls
// and is never clipped, and no drawing of its own - only the system's colours, so High Contrast works.
//
// C# 5 only: this is compiled by the in-box csc (tools/make_exe.py).
using System;
using System.Collections.Generic;
using System.Drawing;
using System.Runtime.InteropServices;
using System.Windows.Forms;

namespace CodexCompatReporter
{
    // The fonts and the scale the window is drawn at. On the screen: the system's message font at the
    // system's DPI (the manifest declares the window system-DPI aware). For --describe and --render: the
    // same font drawn at a scale given, 1 to 2, in pixels, whatever the machine's DPI is - or, given a
    // family, that family at the system font's size, as a Windows whose message font it is would draw it.
    internal sealed class Ui
    {
        public readonly float Scale;
        public readonly Font Font;
        public readonly Font Heading;
        public readonly Font Mono;

        Ui(float scale, Font font, Font heading, Font mono)
        {
            Scale = scale;
            Font = font;
            Heading = heading;
            Mono = mono;
        }

        public static Ui ForScreen()
        {
            float dpi;
            using (Graphics screen = Graphics.FromHwnd(IntPtr.Zero))
            {
                dpi = screen.DpiX;
            }
            Font system = SystemFonts.MessageBoxFont;
            return new Ui(dpi / 96f, system,
                          new Font(system.FontFamily, system.SizeInPoints * 4f / 3f, FontStyle.Regular, GraphicsUnit.Point),
                          Monospaced(system.SizeInPoints * 10f / 9f, GraphicsUnit.Point));
        }

        public static Ui ForScale(float scale, string family)
        {
            Font system = SystemFonts.MessageBoxFont;
            // new FontFamily refuses a family that is not installed, rather than draw in another one.
            FontFamily drawn = family == null ? system.FontFamily : new FontFamily(family);
            float pixels = system.SizeInPoints * 96f / 72f * scale;
            return new Ui(scale, new Font(drawn, pixels, FontStyle.Regular, GraphicsUnit.Pixel),
                          new Font(drawn, pixels * 4f / 3f, FontStyle.Regular, GraphicsUnit.Pixel),
                          Monospaced(pixels * 10f / 9f, GraphicsUnit.Pixel));
        }

        static Font Monospaced(float size, GraphicsUnit unit)
        {
            Font font = new Font("Consolas", size, FontStyle.Regular, unit);
            if (font.Name != "Consolas")
            {
                font.Dispose();
                font = new Font(FontFamily.GenericMonospace, size, FontStyle.Regular, unit);
            }
            return font;
        }

        // A length given at 96 DPI, in this window's pixels.
        public int Px(int length)
        {
            return (int)Math.Round(length * Scale, MidpointRounding.AwayFromZero);
        }

        // A push button's size: its text's, and never smaller than Windows' own 75 x 23.
        public Size ButtonSize(ButtonBase button)
        {
            Size wanted = button.GetPreferredSize(Size.Empty);
            return new Size(Math.Max(wanted.Width + Px(8), Px(75)), Math.Max(wanted.Height, Px(23)));
        }
    }

    // A row whose height follows its content at the width it is given.
    internal interface IMeasured
    {
        int HeightAt(int width);
    }

    // Text the window shows but nobody edits: what the reporter said, a path, the report itself. An edit
    // control, read-only, so any of it can be selected and copied, and so a long path breaks where the
    // line ends instead of running off it. One that grows is as tall as its text at its width; one that
    // does not scrolls.
    internal sealed class TextArea : TextBox, IMeasured
    {
        const int EM_GETLINECOUNT = 0x00BA;
        const int EM_POSFROMCHAR = 0x00D6;
        readonly bool grows;

        [DllImport("user32.dll")]
        static extern IntPtr SendMessage(IntPtr window, int message, IntPtr wParam, IntPtr lParam);

        public TextArea(string name, string text, bool bordered, bool grows)
        {
            this.grows = grows;
            Name = name;
            Multiline = true;
            ReadOnly = true;
            WordWrap = true;
            MaxLength = 0;
            ScrollBars = grows ? ScrollBars.None : ScrollBars.Vertical;
            BorderStyle = bordered ? BorderStyle.Fixed3D : BorderStyle.None;
            BackColor = SystemColors.Control;
            ForeColor = SystemColors.ControlText;
            TabStop = bordered;
            Text = Tidy(text, grows);
            AccessibleName = name;
        }

        // Line breaks as an edit control shows them; for one that grows, no empty line after the last.
        public static string Tidy(string text, bool trim)
        {
            string lines = (text ?? "").Replace("\r\n", "\n").Replace("\r", "\n");
            return (trim ? lines.TrimEnd('\n') : lines).Replace("\n", "\r\n");
        }

        public bool Grows
        {
            get { return grows; }
        }

        int Chrome()
        {
            return IsHandleCreated ? Height - ClientSize.Height
                                   : (BorderStyle == BorderStyle.None ? 0 : SystemInformation.Border3DSize.Height * 2);
        }

        public int LineHeight()
        {
            return TextRenderer.MeasureText("Ag", Font, new Size(int.MaxValue, int.MaxValue),
                                            TextFormatFlags.NoPadding | TextFormatFlags.SingleLine).Height;
        }

        public int LineCount()
        {
            return Math.Max(1, SendMessage(Handle, EM_GETLINECOUNT, IntPtr.Zero, IntPtr.Zero).ToInt32());
        }

        public int HeightAt(int width)
        {
            int lines;
            if (IsHandleCreated)
            {
                // The edit control wraps the text itself, so it is asked: at this width, how many lines.
                if (Width != width)
                {
                    Width = width;
                }
                lines = LineCount();
            }
            else
            {
                int inner = Math.Max(1, width - Chrome() - 6);
                int tall = TextRenderer.MeasureText(Text.Length == 0 ? " " : Text, Font, new Size(inner, int.MaxValue),
                                                    TextFormatFlags.WordBreak | TextFormatFlags.TextBoxControl |
                                                    TextFormatFlags.NoPadding).Height;
                lines = Math.Max(1, (tall + LineHeight() - 1) / LineHeight());
            }
            return lines * LineHeight() + Chrome() + 2;
        }

        // For --describe: whether every line of the text is inside the box, or, for one that scrolls,
        // whether at least one line is.
        public bool Fits()
        {
            if (!IsHandleCreated)
            {
                return false;
            }
            if (!grows)
            {
                return ClientSize.Height >= LineHeight();
            }
            if (LineCount() * LineHeight() > ClientSize.Height)
            {
                return false;
            }
            if (TextLength == 0)
            {
                return true;
            }
            int where = SendMessage(Handle, EM_POSFROMCHAR, (IntPtr)(TextLength - 1), IntPtr.Zero).ToInt32();
            int top = (short)((where >> 16) & 0xFFFF);
            return top >= 0 && top + LineHeight() <= ClientSize.Height;
        }
    }

    // A value to type on GitHub, shown so it can be selected, with a button that copies it.
    internal sealed class CopyRow : Panel, IMeasured
    {
        readonly Ui ui;
        public readonly TextBox Value;
        public readonly Button Copy;

        public CopyRow(Ui ui, string name, string value, string accessibleName)
        {
            this.ui = ui;
            Name = name;
            AccessibleName = accessibleName;
            Value = new TextBox();
            Value.Name = name + "_value";
            Value.ReadOnly = true;
            Value.Text = value;
            Value.AccessibleName = accessibleName;
            Value.TabIndex = 0;
            Copy = new Button();
            Copy.Name = name + "_copy";
            Copy.Text = "Copy";
            Copy.AccessibleName = "Copy " + accessibleName;
            Copy.UseVisualStyleBackColor = true;
            Copy.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Copy.TabIndex = 1;
            Copy.Click += delegate
            {
                try
                {
                    Clipboard.SetText(Value.Text);
                }
                catch (System.Runtime.InteropServices.ExternalException)
                {
                    // Another program holds the clipboard: the value can still be selected and copied.
                }
            };
            Controls.Add(Value);
            Controls.Add(Copy);
        }

        public int HeightAt(int width)
        {
            return Math.Max(Value.PreferredHeight, ui.ButtonSize(Copy).Height);
        }

        protected override void OnLayout(LayoutEventArgs e)
        {
            Size button = ui.ButtonSize(Copy);
            int gap = ui.Px(6);
            Copy.SetBounds(Math.Max(0, ClientSize.Width - button.Width), 0, button.Width, button.Height);
            int boxWidth = Math.Max(1, ClientSize.Width - button.Width - gap);
            Value.SetBounds(0, Math.Max(0, (button.Height - Value.PreferredHeight) / 2), boxWidth, Value.PreferredHeight);
            base.OnLayout(e);
        }
    }

    // A page's content, top to bottom: each row as wide as the page, or as its content when it is a
    // button or a box to tick, and as tall as its content is at that width. One row may fill what height
    // is left. When the rows need more height than the page has, the page scrolls.
    internal sealed class Stack : Panel
    {
        readonly Ui ui;
        readonly List<Control> rows = new List<Control>();
        readonly HashSet<Control> narrow = new HashSet<Control>();
        readonly Dictionary<Control, int> indents = new Dictionary<Control, int>();
        Control filler;
        int fillerMinimum;

        public Stack(Ui ui)
        {
            this.ui = ui;
            AutoScroll = true;
            Padding = new Padding(0, 0, ui.Px(8), 0);
        }

        public T Add<T>(T row) where T : Control
        {
            return Add(row, false);
        }

        public T Add<T>(T row, bool asWideAsItNeeds) where T : Control
        {
            row.TabIndex = rows.Count;
            rows.Add(row);
            if (asWideAsItNeeds)
            {
                narrow.Add(row);
            }
            Controls.Add(row);
            return row;
        }

        // A row set in from the left, under the row it belongs to.
        public T Indent<T>(T row, int by) where T : Control
        {
            indents[row] = by;
            return row;
        }

        int IndentOf(Control row)
        {
            int by;
            return indents.TryGetValue(row, out by) ? by : 0;
        }

        public T Fill<T>(T row, int minimum) where T : Control
        {
            Add(row);
            filler = row;
            fillerMinimum = minimum;
            return row;
        }

        public void Clear()
        {
            SuspendLayout();
            foreach (Control row in rows)
            {
                Controls.Remove(row);
                row.Dispose();
            }
            rows.Clear();
            narrow.Clear();
            indents.Clear();
            filler = null;
            AutoScrollPosition = Point.Empty;
            ResumeLayout(false);
        }

        public int WidthOf(Control row, int width)
        {
            if (!narrow.Contains(row))
            {
                return width;
            }
            ButtonBase button = row as ButtonBase;
            Size wanted = button is Button ? ui.ButtonSize(button) : row.GetPreferredSize(Size.Empty);
            return Math.Min(width, wanted.Width);
        }

        public int HeightOf(Control row, int width)
        {
            IMeasured measured = row as IMeasured;
            if (measured != null)
            {
                return measured.HeightAt(width);
            }
            Button button = row as Button;
            if (button != null)
            {
                return ui.ButtonSize(button).Height;
            }
            TextBox box = row as TextBox;
            if (box != null && !box.Multiline)
            {
                return box.PreferredHeight;
            }
            return row.GetPreferredSize(new Size(width, 0)).Height;
        }

        protected override void OnLayout(LayoutEventArgs e)
        {
            // Twice at most: a scroll bar that comes or goes changes the width the rows wrap at.
            for (int pass = 0; pass < 3; pass++)
            {
                int before = ClientSize.Width;
                Arrange();
                base.OnLayout(e);
                if (ClientSize.Width == before)
                {
                    break;
                }
            }
        }

        void Arrange()
        {
            int width = Math.Max(1, ClientSize.Width - Padding.Horizontal);
            int gap = ui.Px(8);
            List<int> heights = new List<int>();
            int total = Padding.Vertical;
            foreach (Control row in rows)
            {
                int height = row == filler ? fillerMinimum : HeightOf(row, WidthOf(row, width - IndentOf(row)));
                heights.Add(height);
                total += height;
            }
            total += gap * Math.Max(0, rows.Count - 1);
            int left = ClientSize.Height - total - 1;
            int y = Padding.Top + AutoScrollPosition.Y;
            for (int i = 0; i < rows.Count; i++)
            {
                Control row = rows[i];
                int height = heights[i] + (row == filler && left > 0 ? left : 0);
                int indent = IndentOf(row);
                row.SetBounds(Padding.Left + indent + AutoScrollPosition.X, y, WidthOf(row, width - indent), height);
                y += height + gap;
            }
        }
    }
}
