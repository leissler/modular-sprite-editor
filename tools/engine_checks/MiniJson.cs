using System.Collections.Generic;
using System.Globalization;
using System.Text;

// A small JSON reader for the check: objects -> Dictionary<string, object>, arrays -> List<object>, numbers -> double.
public static class MiniJson
{
    public static object Parse(string text) { int i = 0; return Value(text, ref i); }

    static void Skip(string s, ref int i) { while (i < s.Length && char.IsWhiteSpace(s[i])) i++; }

    static object Value(string s, ref int i)
    {
        Skip(s, ref i);
        char c = s[i];
        if (c == '{')
        {
            var d = new Dictionary<string, object>(); i++; Skip(s, ref i);
            if (s[i] == '}') { i++; return d; }
            while (true)
            {
                Skip(s, ref i); var key = (string)Value(s, ref i); Skip(s, ref i); i++; // ':'
                d[key] = Value(s, ref i); Skip(s, ref i);
                if (s[i++] == '}') return d;
            }
        }
        if (c == '[')
        {
            var l = new List<object>(); i++; Skip(s, ref i);
            if (s[i] == ']') { i++; return l; }
            while (true) { l.Add(Value(s, ref i)); Skip(s, ref i); if (s[i++] == ']') return l; }
        }
        if (c == '"')
        {
            var b = new StringBuilder(); i++;
            while (s[i] != '"')
            {
                if (s[i] == '\\')
                {
                    i++;
                    char e = s[i];
                    if (e == 'u') { b.Append((char)int.Parse(s.Substring(i + 1, 4), NumberStyles.HexNumber)); i += 4; }
                    else b.Append(e == 'n' ? '\n' : e == 't' ? '\t' : e);
                }
                else b.Append(s[i]);
                i++;
            }
            i++;
            return b.ToString();
        }
        if (s.Substring(i).StartsWith("true")) { i += 4; return true; }
        if (s.Substring(i).StartsWith("false")) { i += 5; return false; }
        if (s.Substring(i).StartsWith("null")) { i += 4; return null; }
        int start = i;
        while (i < s.Length && "+-0123456789.eE".IndexOf(s[i]) >= 0) i++;
        return double.Parse(s.Substring(start, i - start), CultureInfo.InvariantCulture);
    }
}
