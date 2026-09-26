// The question asked once more before anything is written to GitHub: where it goes, as whom, and the
// SHA-256 of exactly what goes. Its default button is Cancel, so Enter, Esc and closing it all send nothing.
//
// C# 5 only: this is compiled by the in-box csc (tools/make_exe.py).
using System;
using System.Drawing;
using System.Windows.Forms;

namespace CodexCompatReporter
{
    internal sealed class ConfirmForm : Form
    {
        internal const string Question = "Send this report to GitHub now? It opens a public pull request, and a pull " +
                                         "request cannot be unpublished.";
        readonly Ui ui;
        readonly Label question;
        readonly TextArea details;
        public readonly Button Send;
        public readonly Button Cancel;

        public ConfirmForm(Ui ui, string repository, string login, string sha256)
        {
            this.ui = ui;
            SuspendLayout();
            AutoScaleMode = AutoScaleMode.None;
            Font = ui.Font;
            Name = "confirm";
            Text = "Send the report?";
            AccessibleName = Text;
            FormBorderStyle = FormBorderStyle.FixedDialog;
            MaximizeBox = false;
            MinimizeBox = false;
            ShowIcon = false;
            ShowInTaskbar = false;
            StartPosition = FormStartPosition.CenterParent;

            question = new Label();
            question.Name = "question";
            question.AutoSize = false;
            question.UseMnemonic = false;
            question.Text = Question;
            question.AccessibleName = Question;
            question.TabIndex = 0;
            details = new TextArea("details", "Repository: " + repository + "\nLogin: " + login +
                                              "\nSHA-256 of what is sent:\n" + sha256, true, true);
            details.Font = ui.Mono;
            details.AccessibleName = "Where it goes, as whom, and the SHA-256 of what goes";
            details.TabIndex = 1;
            Send = new Button();
            Send.Name = "send";
            Send.Text = "&Send";
            Send.AccessibleName = "Send";
            Send.UseVisualStyleBackColor = true;
            Send.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Send.DialogResult = DialogResult.OK;
            Send.TabIndex = 2;
            Cancel = new Button();
            Cancel.Name = "cancel";
            Cancel.Text = "Cancel";
            Cancel.AccessibleName = "Cancel";
            Cancel.UseVisualStyleBackColor = true;
            Cancel.AutoSizeMode = AutoSizeMode.GrowAndShrink;
            Cancel.DialogResult = DialogResult.Cancel;
            Cancel.TabIndex = 3;
            Controls.Add(question);
            Controls.Add(details);
            Controls.Add(Send);
            Controls.Add(Cancel);
            // Cancel is the default: Enter does what Esc does, and that sends nothing.
            AcceptButton = Cancel;
            CancelButton = Cancel;
            ActiveControl = Cancel;
            ClientSize = new Size(ui.Px(520), ui.Px(200));
            ResumeLayout(false);
            Arrange();
        }

        protected override void OnHandleCreated(EventArgs e)
        {
            base.OnHandleCreated(e);
            BeginInvoke(new MethodInvoker(Arrange));
        }

        // As tall as what it says, at its one width.
        public void Arrange()
        {
            int margin = ui.Px(12);
            int gap = ui.Px(10);
            int width = ClientSize.Width - 2 * margin;
            int y = margin;
            int tall = question.GetPreferredSize(new Size(width, 0)).Height;
            question.SetBounds(margin, y, width, tall);
            y += tall + gap;
            tall = details.HeightAt(width);
            details.SetBounds(margin, y, width, tall);
            y += tall + gap + ui.Px(4);
            Size send = ui.ButtonSize(Send);
            Size cancel = ui.ButtonSize(Cancel);
            int height = Math.Max(send.Height, cancel.Height);
            int x = ClientSize.Width - margin - cancel.Width;
            Cancel.SetBounds(x, y, cancel.Width, height);
            x -= ui.Px(6) + send.Width;
            Send.SetBounds(x, y, send.Width, height);
            ClientSize = new Size(ClientSize.Width, y + height + margin);
        }
    }
}
