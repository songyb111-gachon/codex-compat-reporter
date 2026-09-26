// What the window reads and writes as JSON: the one object the reporter answers with (codex_compat_report.py
// --json) and what --describe prints. A small reader of its own, so the window needs nothing beyond the
// three assemblies every .NET Framework 4.8 has.
//
// C# 5 only: this is compiled by the in-box csc (tools/make_exe.py).
using System;
using System.Collections.Generic;
using System.Globalization;
using System.Text;

namespace CodexCompatReporter
{
    internal static class Json
    {
        // One JSON value, and nothing after it but white space. Objects are Dictionary<string, object>,
        // arrays List<object>, numbers double, true and false bool, null null.
        public static object Parse(string text)
        {
            int at = 0;
            object value = Value(text, ref at);
            Space(text, ref at);
            if (at != text.Length)
            {
                throw new FormatException("something follows the JSON value at " + at);
            }
            return value;
        }

        static void Space(string text, ref int at)
        {
            while (at < text.Length && (text[at] == ' ' || text[at] == '\t' || text[at] == '\r' || text[at] == '\n'))
            {
                at++;
            }
        }

        static object Value(string text, ref int at)
        {
            Space(text, ref at);
            if (at >= text.Length)
            {
                throw new FormatException("the JSON ends early");
            }
            char c = text[at];
            if (c == '{')
            {
                return Object(text, ref at);
            }
            if (c == '[')
            {
                return Array(text, ref at);
            }
            if (c == '"')
            {
                return String(text, ref at);
            }
            if (Word(text, ref at, "true"))
            {
                return true;
            }
            if (Word(text, ref at, "false"))
            {
                return false;
            }
            if (Word(text, ref at, "null"))
            {
                return null;
            }
            return Number(text, ref at);
        }

        static bool Word(string text, ref int at, string word)
        {
            if (string.CompareOrdinal(text, at, word, 0, word.Length) == 0)
            {
                at += word.Length;
                return true;
            }
            return false;
        }

        static Dictionary<string, object> Object(string text, ref int at)
        {
            Dictionary<string, object> found = new Dictionary<string, object>(StringComparer.Ordinal);
            at++;
            Space(text, ref at);
            if (at < text.Length && text[at] == '}')
            {
                at++;
                return found;
            }
            while (true)
            {
                Space(text, ref at);
                if (at >= text.Length || text[at] != '"')
                {
                    throw new FormatException("a JSON object's key is not a string at " + at);
                }
                string key = String(text, ref at);
                Space(text, ref at);
                if (at >= text.Length || text[at] != ':')
                {
                    throw new FormatException("no ':' after a key at " + at);
                }
                at++;
                found[key] = Value(text, ref at);
                Space(text, ref at);
                if (at < text.Length && text[at] == ',')
                {
                    at++;
                    continue;
                }
                if (at < text.Length && text[at] == '}')
                {
                    at++;
                    return found;
                }
                throw new FormatException("a JSON object does not end at " + at);
            }
        }

        static List<object> Array(string text, ref int at)
        {
            List<object> found = new List<object>();
            at++;
            Space(text, ref at);
            if (at < text.Length && text[at] == ']')
            {
                at++;
                return found;
            }
            while (true)
            {
                found.Add(Value(text, ref at));
                Space(text, ref at);
                if (at < text.Length && text[at] == ',')
                {
                    at++;
                    continue;
                }
                if (at < text.Length && text[at] == ']')
                {
                    at++;
                    return found;
                }
                throw new FormatException("a JSON array does not end at " + at);
            }
        }

        static string String(string text, ref int at)
        {
            StringBuilder found = new StringBuilder();
            at++;
            while (at < text.Length)
            {
                char c = text[at++];
                if (c == '"')
                {
                    return found.ToString();
                }
                if (c != '\\')
                {
                    if (c < ' ')
                    {
                        throw new FormatException("a control character inside a JSON string");
                    }
                    found.Append(c);
                    continue;
                }
                if (at >= text.Length)
                {
                    break;
                }
                char escaped = text[at++];
                if (escaped == '"' || escaped == '\\' || escaped == '/')
                {
                    found.Append(escaped);
                }
                else if (escaped == 'b')
                {
                    found.Append('\b');
                }
                else if (escaped == 'f')
                {
                    found.Append('\f');
                }
                else if (escaped == 'n')
                {
                    found.Append('\n');
                }
                else if (escaped == 'r')
                {
                    found.Append('\r');
                }
                else if (escaped == 't')
                {
                    found.Append('\t');
                }
                else if (escaped == 'u' && at + 4 <= text.Length)
                {
                    // Python's json.dumps(ensure_ascii=True) writes every other character this way, a
                    // character outside the Basic Multilingual Plane as two of them; UTF-16 keeps both.
                    found.Append((char)int.Parse(text.Substring(at, 4), NumberStyles.AllowHexSpecifier,
                                                 CultureInfo.InvariantCulture));
                    at += 4;
                }
                else
                {
                    throw new FormatException("an unknown escape in a JSON string");
                }
            }
            throw new FormatException("a JSON string does not end");
        }

        static double Number(string text, ref int at)
        {
            int start = at;
            while (at < text.Length && "+-0123456789.eE".IndexOf(text[at]) >= 0)
            {
                at++;
            }
            if (at == start)
            {
                throw new FormatException("not a JSON value at " + start);
            }
            return double.Parse(text.Substring(start, at - start), NumberStyles.Float, CultureInfo.InvariantCulture);
        }

        // --------------------------------------------------------------------------- writing
        // What --describe prints: Ordered objects keep their keys in the order they were added.
        public static string Write(object value)
        {
            StringBuilder written = new StringBuilder();
            Write(written, value);
            return written.ToString();
        }

        static void Write(StringBuilder written, object value)
        {
            Ordered ordered = value as Ordered;
            System.Collections.IList list = value as System.Collections.IList;
            if (value == null)
            {
                written.Append("null");
            }
            else if (value is bool)
            {
                written.Append((bool)value ? "true" : "false");
            }
            else if (value is int || value is long)
            {
                written.Append(Convert.ToInt64(value, CultureInfo.InvariantCulture).ToString(CultureInfo.InvariantCulture));
            }
            else if (value is float || value is double)
            {
                written.Append(Convert.ToDouble(value, CultureInfo.InvariantCulture).ToString("R", CultureInfo.InvariantCulture));
            }
            else if (value is string)
            {
                Quote(written, (string)value);
            }
            else if (ordered != null)
            {
                written.Append('{');
                for (int i = 0; i < ordered.Count; i++)
                {
                    if (i > 0)
                    {
                        written.Append(", ");
                    }
                    Quote(written, ordered.Key(i));
                    written.Append(": ");
                    Write(written, ordered.Value(i));
                }
                written.Append('}');
            }
            else if (list != null)
            {
                written.Append('[');
                for (int i = 0; i < list.Count; i++)
                {
                    if (i > 0)
                    {
                        written.Append(", ");
                    }
                    Write(written, list[i]);
                }
                written.Append(']');
            }
            else
            {
                Quote(written, value.ToString());
            }
        }

        static void Quote(StringBuilder written, string text)
        {
            written.Append('"');
            foreach (char c in text)
            {
                if (c == '"' || c == '\\')
                {
                    written.Append('\\').Append(c);
                }
                else if (c < ' ' || c > '~')
                {
                    written.Append("\\u").Append(((int)c).ToString("x4", CultureInfo.InvariantCulture));
                }
                else
                {
                    written.Append(c);
                }
            }
            written.Append('"');
        }
    }

    // A JSON object to write, its keys in the order they were added.
    internal sealed class Ordered
    {
        readonly List<string> keys = new List<string>();
        readonly List<object> values = new List<object>();

        public Ordered Add(string key, object value)
        {
            keys.Add(key);
            values.Add(value);
            return this;
        }

        public int Count
        {
            get { return keys.Count; }
        }

        public string Key(int index)
        {
            return keys[index];
        }

        public object Value(int index)
        {
            return values[index];
        }
    }

    // A JSON object the reporter wrote, read field by field: a field that is missing, or not of the kind
    // asked for, reads as nothing (null, false, an empty list), never as an exception.
    internal sealed class JsonObject
    {
        readonly Dictionary<string, object> fields;

        JsonObject(Dictionary<string, object> fields)
        {
            this.fields = fields;
        }

        public static JsonObject From(object value)
        {
            Dictionary<string, object> fields = value as Dictionary<string, object>;
            return fields == null ? null : new JsonObject(fields);
        }

        public bool Has(string key)
        {
            return fields.ContainsKey(key) && fields[key] != null;
        }

        public string Str(string key)
        {
            object value;
            return fields.TryGetValue(key, out value) ? value as string : null;
        }

        public bool Bool(string key)
        {
            object value;
            return fields.TryGetValue(key, out value) && value is bool && (bool)value;
        }

        public int Int(string key, int otherwise)
        {
            object value;
            if (fields.TryGetValue(key, out value) && value is double)
            {
                double number = (double)value;
                if (number >= int.MinValue && number <= int.MaxValue && Math.Floor(number) == number)
                {
                    return (int)number;
                }
            }
            return otherwise;
        }

        public JsonObject Obj(string key)
        {
            object value;
            return fields.TryGetValue(key, out value) ? From(value) : null;
        }

        public List<string> Strings(string key)
        {
            List<string> found = new List<string>();
            object value;
            List<object> list = fields.TryGetValue(key, out value) ? value as List<object> : null;
            if (list != null)
            {
                foreach (object item in list)
                {
                    string text = item as string;
                    if (text != null)
                    {
                        found.Add(text);
                    }
                }
            }
            return found;
        }

        public List<JsonObject> Objects(string key)
        {
            List<JsonObject> found = new List<JsonObject>();
            object value;
            List<object> list = fields.TryGetValue(key, out value) ? value as List<object> : null;
            if (list != null)
            {
                foreach (object item in list)
                {
                    JsonObject entry = From(item);
                    if (entry != null)
                    {
                        found.Add(entry);
                    }
                }
            }
            return found;
        }
    }
}
