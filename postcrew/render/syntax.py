"""Tiny syntax highlighter for code shown in posters and animations."""
import re

from .theme import CORAL, CREAM, GOLD, MUTED, TEAL

KEYWORDS = {
    "java": "static void int long double boolean char if else for while return new continue break class "
            "public private final import null true false this throws try catch default switch case do var",
    "python": "def class if elif else for while return import from as with try except finally raise "
              "None True False and or not in is lambda yield pass break continue async await",
    "javascript": "const let var function return if else for while new class import from export async await "
                  "null true false this try catch throw",
    "bash": "if then else fi for do done while case esac function export echo cd",
    "sql": "select from where group by order having join left right inner on as and or not in insert "
           "into values update set delete create table limit",
    "yaml": "true false null",
    "json": "true false null",
}
COMMENT = {"java": "//", "javascript": "//", "python": "#", "bash": "#", "yaml": "#", "sql": "--", "json": None}
STRING_COLOR = "#9bd67a"

_TOKEN = re.compile(r"""
    (?P<string>"(?:\\.|[^"\\])*"|'(?:\\.|[^'\\])*')
  | (?P<number>\b\d+(?:\.\d+)?\b)
  | (?P<ident>[A-Za-z_][A-Za-z0-9_]*)
  | (?P<other>.)
""", re.X | re.S)


def tokenize(line, lang="java"):
    """Return [(text, color)] for one line of code."""
    lang = lang if lang in KEYWORDS else "java"
    kw = set(KEYWORDS[lang].split())
    marker = COMMENT.get(lang)
    code, comment = line, ""
    if marker:
        # find a comment marker that is not inside a string
        in_str, quote = False, ""
        for i, ch in enumerate(line):
            if in_str:
                if ch == quote and line[i - 1] != "\\":
                    in_str = False
            elif ch in "\"'":
                in_str, quote = True, ch
            elif line.startswith(marker, i):
                code, comment = line[:i], line[i:]
                break
    out = []
    for m in _TOKEN.finditer(code):
        kind, txt = m.lastgroup, m.group()
        if kind == "string":
            out.append((txt, STRING_COLOR))
        elif kind == "number":
            out.append((txt, CORAL))
        elif kind == "ident":
            ci = txt.lower() if lang == "sql" else txt
            if ci in kw:
                out.append((txt, GOLD))
            elif txt[0].isupper() and lang in ("java", "javascript", "python"):
                out.append((txt, TEAL))
            else:
                out.append((txt, CREAM))
        else:
            out.append((txt, CREAM))
    if comment:
        out.append((comment, MUTED))
    return out
