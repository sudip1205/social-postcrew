"""What the voice is given to read: every symbol, number, abbreviation and acronym spelled out as words.

ElevenLabs' own guidance says its models "struggle" with numbers, currency, dates, times, URLs, unit abbreviations, shortcuts and
symbols, and the way to deal with that is to write them out as the words to be spoken before the text is sent. When the model cannot
read something it makes a noise instead ("ooo"), so nothing is left for it to guess:

  speakable(text)   the narration as it must be sent to the voice ("O(n^2)" -> "O of n squared", "9 - 7 = 2" -> "nine minus seven
                    equals two", "API" -> "A P I", "kubectl" -> "cube control", "$4.50" -> "four dollars and fifty cents").
  problems(text)    what cannot be made speakable and the writer must rewrite: code, identifiers, addresses, emoji, odd symbols, lone
                    letters, words with no vowels, tokens the voice would have to guess.
  report(text)      the spoken form of every respelled token, for the reviewers.

The script keeps its written text (captions, on-screen words and timing use that); only what is sent to the voice is respelled.
"""
import re

ONES = ("zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen "
        "nineteen").split()
TENS = "zero ten twenty thirty forty fifty sixty seventy eighty ninety".split()
SCALES = ((10 ** 12, "trillion"), (10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand"))
ORDINALS = {"one": "first", "two": "second", "three": "third", "five": "fifth", "eight": "eighth", "nine": "ninth", "twelve": "twelfth"}


def cardinal(n):
    """12045 -> 'twelve thousand forty five'."""
    if n < 0:
        return "minus " + cardinal(-n)
    if n < 20:
        return ONES[n]
    if n < 100:
        return TENS[n // 10] + (" " + ONES[n % 10] if n % 10 else "")
    if n < 1000:
        return ONES[n // 100] + " hundred" + (" " + cardinal(n % 100) if n % 100 else "")
    for size, name in SCALES:
        if n >= size:
            return cardinal(n // size) + " " + name + (" " + cardinal(n % size) if n % size else "")
    return str(n)


def ordinal(n):
    words = cardinal(n).split()
    last = words[-1]
    if last in ORDINALS:
        words[-1] = ORDINALS[last]
    elif last.endswith("y"):
        words[-1] = last[:-1] + "ieth"
    else:
        words[-1] = last + "th"
    return " ".join(words)


def digits(s):
    return " ".join(ONES[int(c)] for c in s if c.isdigit())


def number(s, year=False):
    """'1,000' -> 'one thousand'; '3.14' -> 'three point one four'; '007' -> 'zero zero seven'; years as 'twenty twenty six'."""
    s = s.replace(",", "")
    if "." in s:
        whole, frac = s.split(".", 1)
        return (number(whole) if whole else "zero") + " point " + digits(frac)
    if len(s) > 12 or (len(s) > 1 and s.startswith("0")):
        return digits(s)
    n = int(s)
    if year and 1100 <= n <= 2099 and n % 100:
        return cardinal(n // 100) + " " + (("oh " + cardinal(n % 100)) if n % 100 < 10 else cardinal(n % 100))
    return cardinal(n)


# how a technical term is SAID (the written form stays in the captions). Case-insensitive unless noted.
SAID = {
    "kubectl": "cube control", "nginx": "engine X", "sudo": "sue doo", "chmod": "change mod", "regex": "reg ex", "sqlite": "sequel light",
    "postgresql": "post gres sequel", "postgres": "post gres", "mysql": "my sequel", "nosql": "no sequel", "sql": "sequel",
    "json": "jason", "yaml": "yammel", "oauth2": "oh auth two", "oauth": "oh auth", "oidc": "O I D C", "grpc": "g R P C",
    "apigee": "ap ih gee", "resilience4j": "resilience four J", "uuid": "U U I D", "ascii": "ask ee", "gui": "gooey", "saas": "sass",
    "lifo": "life oh", "fifo": "fife oh", "cors": "cores", "ipv4": "I P version four", "ipv6": "I P version six", "http/2": "H T T P two",
    "http/3": "H T T P three", "tcp/ip": "T C P I P", "ci/cd": "C I C D", "i/o": "I O", "s3": "S three", "ec2": "E C two",
    "wsl": "W S L", "iam": "I A M", "ldap": "L dap", "kms": "K M S", "hmac": "H mac", "sha256": "S H A two fifty six",
    "sha-256": "S H A two fifty six", "aes": "A E S", "rsa": "R S A", "jwt": "J W T", "tls": "T L S", "ssl": "S S L", "ssh": "S S H",
    "cdn": "C D N", "dns": "D N S", "api": "A P I", "apis": "A P Is", "url": "U R L", "urls": "U R Ls", "http": "H T T P",
    "https": "H T T P S", "tcp": "T C P", "udp": "U D P", "cpu": "C P U", "gpu": "G P U", "ram": "ram", "aws": "A W S", "gcp": "G C P",
    "ui": "U I", "ux": "U X", "id": "I D", "ids": "I Ds", "cli": "C L I", "lru": "L R U", "ttl": "T T L", "qps": "Q P S", "ip": "I P",
    "rest": "rest", "html": "H T M L", "css": "C S S", "xml": "X M L", "csv": "C S V", "pdf": "P D F", "sdk": "S D K", "vpn": "V P N",
    "vpc": "V P C", "mfa": "M F A", "otp": "O T P", "sso": "S S O", "rbac": "R back", "acid": "acid", "cap": "cap", "db": "D B",
    "ai": "A I", "ml": "M L", "llm": "L L M", "rag": "rag", "mcp": "M C P", "os": "O S", "io": "I O", "ide": "I D E", "jvm": "J V M",
    "jdk": "J D K", "orm": "O R M", "crud": "crud", "dto": "D T O", "sla": "S L A", "slo": "S L O", "sli": "S L I", "waf": "waf",
    "csrf": "C S R F", "xss": "X S S", "ddos": "D dos", "dos": "dos", "ssr": "S S R", "spa": "S P A", "pwa": "P W A", "iot": "I O T",
    "sqs": "S Q S", "sns": "S N S", "ecs": "E C S", "eks": "E K S", "etl": "E T L", "oltp": "O L T P", "olap": "O L A P", "bfs": "B F S",
    "dfs": "D F S", "dp": "D P", "nat": "nat", "lan": "lan", "wan": "wan", "ftp": "F T P", "smtp": "S M T P", "imap": "I M A P",
    "jwe": "J W E", "jws": "J W S", "ecc": "E C C", "md5": "M D five", "gif": "jif", "png": "P N G", "utf": "U T F", "dom": "dom",
    "ssd": "S S D", "hdd": "H D D", "tpu": "T P U", "pr": "P R", "qa": "Q A", "mttr": "M T T R", "dao": "D A O", "rps": "R P S",
}
# a word that is not an acronym when it is written in capitals ("UP", "NOT", "LOAD"): said as a plain word
PLAIN = frozenset("UP IN ON OR IF IS IT NO SO DO GO OK AS AT BE BY HE ME MY OF TO US WE AN AM ALL AND ANY ARE BUT CAN DID FOR GET HAS "
                  "HER HIM HIS HOW ITS LET MAY NEW NOT NOW OFF OLD ONE OUR OUT SEE THE TWO USE WAS WAY WHO WHY YES YET YOU RUN SET "
                  "MAP KEY PUT TOP END MIN MAX SUM AVG".split())
UNITS = {"ms": "milliseconds", "ns": "nanoseconds", "us": "microseconds", "s": "seconds", "sec": "seconds", "min": "minutes",
         "hr": "hours", "h": "hours", "kb": "kilobytes", "mb": "megabytes", "gb": "gigabytes", "tb": "terabytes", "pb": "petabytes",
         "kbps": "kilobits per second", "mbps": "megabits per second", "gbps": "gigabits per second", "px": "pixels",
         "ghz": "gigahertz", "mhz": "megahertz", "hz": "hertz", "kib": "kibibytes", "mib": "mebibytes", "gib": "gibibytes",
         "rps": "requests per second", "qps": "queries per second", "x": "times", "k": "thousand", "m": "million", "b": "billion",
         "%": "percent"}
SYMBOLS = [   # applied in this order
    (r"&&", " and "), (r"\|\|", " or "), (r"!==?", " is not equal to "), (r"===?", " equals "), (r">=", " is at least "),
    (r"<=", " is at most "), (r"\+\+", " plus plus "), (r"--(?=\s|$)", " minus minus "), (r"\+=", " plus equals "),
    (r"->|=>|→|⇒", " to "), (r"←|<-", " from "), (r"≤", " is at most "), (r"≥", " is at least "),
    (r"≠", " is not equal to "), (r"≈", " is about "), (r"×", " times "), (r"÷", " divided by "),
    (r"°C", " degrees Celsius"), (r"°F", " degrees Fahrenheit"), (r"°", " degrees"), (r"∞", " infinity "),
    (r"…", "..."), (r"[—–]", ", "), (r"[“”]", '"'), (r"[‘’]", "'"), (r"²", " squared"),
    (r"³", " cubed"),
]


def _unit(num_spoken, u):
    word = UNITS.get(u.lower())
    return f"{num_spoken} {word}" if word else None


def _money(m):
    sym = {"$": ("dollar", "cent"), "€": ("euro", "cent"), "£": ("pound", "pence")}[m.group(1)]
    whole = int(m.group(2).replace(",", ""))
    out = cardinal(whole) + " " + sym[0] + ("" if whole == 1 else "s")
    if m.group(3):
        cents = int((m.group(3)[1:] + "0")[:2])
        if cents:
            out += " and " + cardinal(cents) + " " + (sym[1] if cents == 1 or sym[1] == "pence" else sym[1] + "s")
    suffix = {"k": " thousand", "m": " million", "b": " billion"}.get((m.group(4) or "").lower(), "")
    return out + suffix if suffix else out


def _acronym(w):
    low = w.lower()
    if low in SAID:
        return SAID[low]
    if w in PLAIN:
        return w.lower()
    if len(w) <= 3 or not VOWELS.search(w):
        return " ".join(w)   # an unknown acronym is spelled letter by letter
    return w.lower()   # a longer word with vowels in capitals is a word shouted ("LOAD")


def speakable(text):
    s = " ".join(str(text or "").split())
    if not s:
        return ""
    s = re.sub(r"```.*?```|`", " ", s)
    s = re.sub(r"[*_]{1,2}(?=\S)([^*_]+?)(?<=\S)[*_]{1,2}", r"\1", s)   # markdown emphasis
    s = re.sub(r"https?://([^\s/]+)(/\S*)?", lambda m: _address(m.group(1) + (m.group(2) or "")), s)
    s = re.sub(r"\b([\w.+-]+)@([\w-]+(?:\.[\w-]+)+)\b", lambda m: f"{_words(m.group(1))} at {_address(m.group(2))}", s)
    # whole terms with punctuation inside them
    for term in sorted((t for t in SAID if re.search(r"[/\-]", t)), key=len, reverse=True):
        s = re.sub(rf"(?<![\w]){re.escape(term)}(?![\w])", " " + SAID[term] + " ", s, flags=re.I)
    s = re.sub(r"\b([AaPp])\.[Mm]\.", lambda m: m.group(1).upper() + " M", s)
    s = re.sub(r"\b(AM|PM)\b", lambda m: m.group(1)[0] + " M", s)
    s = re.sub(r"(?<=\d)\s?([ap])m\b", lambda m: " " + m.group(1).upper() + " M", s)
    s = re.sub(r"\bC\+\+", "C plus plus", s)
    s = re.sub(r"\bC#", "C sharp", s)
    s = re.sub(r"\bF#", "F sharp", s)
    s = re.sub(r"(?<!\w)\.NET\b", "dot net", s)
    s = re.sub(r"\bNode\.js\b", "node J S", s, flags=re.I)
    s = re.sub(r"\b([A-Za-z]+)\.js\b", lambda m: m.group(1) + " J S", s)
    # complexity: O(n^2) -> O of n squared
    s = re.sub(r"\b([OΘΩ])\(([^()]*)\)", lambda m: f"{m.group(1)} of {_inside(m.group(2))}", s)
    s = re.sub(r"\b([A-Za-z])\^2\b", r"\1 squared", s)
    s = re.sub(r"\b([A-Za-z])\^3\b", r"\1 cubed", s)
    s = re.sub(r"\b(\w+)\^(\w+)\b", r"\1 to the power of \2", s)
    for pat, rep in SYMBOLS:
        s = re.sub(pat, rep, s)
    s = re.sub(r"([$€£])\s?(\d[\d,]*)(\.\d+)?(?:\s?([kKmMbB])\b)?", _money, s)
    s = re.sub(r"(?<=\d):(?=\d{2}\b)", " ", s)   # 9:30 -> 9 30
    s = re.sub(r"\b(\d{1,2}) (\d{2})\b(?= ?(?:AM|PM|am|pm|a\.m\.|p\.m\.))", lambda m: number(m.group(1)) + " " + ("" if m.group(2) == "00" else ("oh " + number(m.group(2)) if m.group(2)[0] == "0" else number(m.group(2)))), s)
    s = re.sub(r"\b(\d+)(st|nd|rd|th)\b", lambda m: ordinal(int(m.group(1))), s)
    s = re.sub(r"(?<![\w.])v(\d+(?:\.\d+)*)\b", lambda m: "version " + number(m.group(1)), s)
    s = re.sub(r"\b(?:in|since|by|from|until|year|of)\s+(1[1-9]\d\d|20\d\d)\b", lambda m: m.group(0).rsplit(" ", 1)[0] + " " + number(m.group(1), year=True), s, flags=re.I)
    s = re.sub(r"(?<=\d)\s-\s(?=\d)", " minus ", s)   # 9 - 7: a minus
    s = re.sub(r"(?<=\d)-(?=\d)", " to ", s)           # 1-3: a range
    s = re.sub(r"(?<![\w])-(\d)", r"minus \1", s)
    s = re.sub(r"(?<=\s)-(?=\s)", " minus ", s)
    s = re.sub(r"(?<=\s)\+(?=\s)|(?<=\d)\+(?=\d)", " plus ", s)
    s = re.sub(r"(?<=\w)\+(?=\s|$|[.,])", " plus", s)
    s = re.sub(r"(?<=[\w)\]])\s?=\s?(?=[\w(\[-])", " equals ", s)
    s = re.sub(r"(?<=\s)=(?=\s)", " equals ", s)
    s = re.sub(r"(?<=\w)\s?<\s?(?=\w)", " is less than ", s)
    s = re.sub(r"(?<=\w)\s?>\s?(?=\w)", " is greater than ", s)
    s = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?%", lambda m: number(m.group(1)) + " percent", s)
    s = re.sub(r"(?<=\w)\s?%\s?(?=\w)", " modulo ", s)
    s = re.sub(r"(\d[\d,]*(?:\.\d+)?)\s?([A-Za-z]{1,4})\b", _numunit, s)
    s = re.sub(r"(?<=\d)\s?[*x×]\s?(?=\d)", " times ", s)
    s = re.sub(r"(?<=\d)\s?/\s?(?=\d)", " over ", s)
    s = re.sub(r"(?<=\w)\s?\*\s?(?=\w)", " times ", s)
    s = re.sub(r"#(\d+)", lambda m: "number " + number(m.group(1)), s)
    s = re.sub(r"(?<=\s)&(?=\s)|(?<=\w)&(?=\w)", " and ", s)
    s = re.sub(r"(?<=\w)@(?=\w)", " at ", s)
    s = re.sub(r"~(?=\d)", "about ", s)
    # code-ish words: nums[i] -> nums of i, two_sum -> two sum, twoSum -> two Sum, a.b -> a dot b, f() -> f
    s = re.sub(r"(\w)\[([^\]]*)\]", lambda m: f"{m.group(1)} of {m.group(2)}", s)
    s = re.sub(r"(\w)\(\)", r"\1", s)
    s = re.sub(r"(?<=[a-z0-9])_(?=[a-z0-9])", " ", s)
    s = re.sub(r"\b([a-z]+)((?:[A-Z][a-z0-9]+)+)\b", lambda m: _camel(m.group(0)), s)
    s = re.sub(r"(?<=[A-Za-z])\.(?=[A-Za-z]{2,}\b)", " dot ", s)
    s = re.sub(r"\s?[\[\]{}<>|\\^~]\s?", " ", s)
    s = re.sub(r"\s?\(\s?", ", ", s)
    s = re.sub(r"\s?\)\s?", ", ", s)
    s = re.sub(r"\b[A-Za-z][A-Za-z0-9]*\b", lambda m: _word(m.group(0)), s)
    s = re.sub(r"\b\d[\d,]*(?:\.\d+)?\b", lambda m: number(m.group(0)), s)
    s = re.sub(r"[^\w\s.,;:!?'\"\-]", " ", s)   # anything still left (emoji, stray symbols) is not read
    s = re.sub(r"\s+([.,;:!?])", r"\1", s)
    s = re.sub(r"([,;:])\s*([,;:])+", r"\1", s)
    s = re.sub(r",\s*([.!?])", r"\1", s)
    s = re.sub(r"\.{4,}", "...", s)
    return " ".join(s.split()).strip(" ,;")


def _numunit(m):
    u = m.group(2)
    if u.lower() in ("st", "nd", "rd", "th") or u.lower() not in UNITS:
        return m.group(0)
    return _unit(number(m.group(1)), u) or m.group(0)


def _camel(w):
    return re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", w)


def _word(w):
    if w in SAID or w.lower() in SAID and not w.islower() and not w.istitle():
        return SAID.get(w, SAID.get(w.lower(), w))
    if w.lower() in ("kubectl", "nginx", "sudo", "chmod", "regex", "sqlite", "postgres", "postgresql", "mysql", "nosql", "apigee",
                     "oauth", "oauth2", "resilience4j", "ascii", "uuid"):
        return SAID[w.lower()]
    if w.isupper() and len(w) >= 2:
        return _acronym(w)
    if w.lower() in SAID and w.lower() in ("json", "yaml", "sql", "saas", "gui", "cors", "lifo", "fifo") and (w.isupper() or w.istitle()):
        return SAID[w.lower()]
    return w


def _words(s):
    return re.sub(r"[._+-]+", " ", s)


def _address(a):
    a = a.rstrip("/")
    a = re.sub(r"^www\.", "w w w dot ", a)
    return re.sub(r"[/.]", lambda m: " dot " if m.group(0) == "." else " slash ", a).replace("-", " dash ")


def _inside(inner):
    """The inside of O(...): n, n^2, log n, n log n, 1, n * m."""
    t = inner.strip()
    t = re.sub(r"\b([A-Za-z])\^2\b|\b([A-Za-z])²", lambda m: (m.group(1) or m.group(2)) + " squared", t)
    t = re.sub(r"\b([A-Za-z])\^3\b|\b([A-Za-z])³", lambda m: (m.group(1) or m.group(2)) + " cubed", t)
    t = re.sub(r"\b([A-Za-z])\^(\w+)\b", r"\1 to the power of \2", t)
    t = re.sub(r"\s?\*\s?", " times ", t)
    t = re.sub(r"\s?\+\s?", " plus ", t)
    t = re.sub(r"\b\d+\b", lambda m: number(m.group(0)), t)
    return " ".join(t.split())


# ---------- what cannot be made speakable ----------
VOWELS = re.compile(r"[aeiouy]", re.I)


def problems(text):
    """What in this narration the voice would have to guess at, as messages for the writer. Empty when it can all be spoken."""
    t = " ".join(str(text or "").split())
    found = []

    def add(msg):
        if msg not in found:
            found.append(msg)

    if re.search(r"\w(?:\.\.\.|\u2026)\s*[a-z]", t) or re.search(r"(?:^|\W)(?:and|or|the|a|of|to|in|is|are|then)(?:\.\.\.|\u2026)", t, re.I):
        add("an ellipsis in the middle of a sentence: the voice stops there for a full second, in the wrong place. Use '...' only after a "
            "complete sentence, before the key point")
    if re.search(r"https?://|www\.|\b[\w-]+\.(?:com|org|io|dev|net|ai|app)\b|\S+@\S+\.\w+", t):
        add("a web address or email: say it in words or leave it for the description")
    for m in re.finditer(r"\b\w+_\w+\b", t):
        add(f"'{m.group(0)}' is a code name (underscore): say it in words ({_words(m.group(0))!r}) and show the name on screen")
    for m in re.finditer(r"\b[a-z]+(?:[A-Z][a-z0-9]+)+\b", t):
        if m.group(0).lower() not in SAID:
            add(f"'{m.group(0)}' is a code name (camelCase): say it in words ({_camel(m.group(0)).lower()!r}) and show the name on screen")
    if re.search(r"[`{}\\|]|::|\w\(\)|\w\[[^\]]*\]|==|!=|<=|>=|->|=>|&&|\|\|", t):
        add("code in the narration (brackets, braces, operators, backticks): describe it in words and show the code on screen")
    if re.search(r"(?:^|\s)/[\w.-]+(?:/[\w.-]+)+|\b[\w.-]+/[\w.-]+\.\w{1,4}\b|~/|\b[A-Za-z]:\\", t):
        add("a file path: say where it is in words")
    if re.search(r"\b[0-9a-f]{8,}\b|\b[0-9a-f]{8}-[0-9a-f]{4}-", t, re.I):
        add("a hash or id: say what it is, not its characters")
    if re.search(r"[^\x00-\x7f‘’“”—–…→²³×÷≤≥≠≈°€£ΩΘ]", t):
        add("a symbol or emoji the voice cannot read: use words")
    if re.search(r"(?<![\w'])[a-z]\s*,\s*[a-z](?![\w'])|(?<=[.!?]\s)[a-z]\s*[.,]|\b(?:old|new|letter|character|char)\s+[a-z]\b(?!\w)", t):
        add("lone lowercase letters (like 'a, b, c' or 'the old a'): the voice makes a stray sound on them; write letters as capitals "
            "(A, B, C)")
    for m in re.finditer(r"\b[A-Za-z]{4,}\b", t):
        w = m.group(0)
        if w.lower() in SAID or w.isupper() or w.lower() in {x.lower() for x in PLAIN}:
            continue
        if not VOWELS.search(w):
            add(f"'{w}' has no vowels: the voice cannot say it. Spell it out or use another word")
        elif re.search(r"[^aeiouy\W\d_]{6,}", w, re.I):
            add(f"'{w}' is a run of consonants the voice cannot say: use another word or say how it sounds")
    for m in re.finditer(r"\b(?=[A-Za-z]*\d)(?=\d*[A-Za-z])[A-Za-z0-9]{2,}\b", t):
        w = m.group(0)
        if w.lower() in SAID or re.fullmatch(r"\d+(?:st|nd|rd|th|k|m|b|x|ms|s|kb|mb|gb|tb|px|hz)", w, re.I) or re.fullmatch(r"v\d+", w, re.I):
            continue
        add(f"'{w}' mixes letters and digits: say it in words ('{_digit_split(w)}') or use another name")
    for m in re.finditer(r"\b[A-Z]{2,}\b", t):
        w = m.group(0)
        if w.lower() not in SAID and w not in PLAIN and len(w) > 5:
            add(f"'{w}' is an acronym the voice may not know: write what it stands for")
    return found


def _digit_split(w):
    return re.sub(r"(?<=\d)(?=[A-Za-z])|(?<=[A-Za-z])(?=\d)", " ", w).lower()


def report(text):
    """[(written, spoken)] for every word or symbol that was respelled, for the reviewers (what the voice will actually say)."""
    raw, said = str(text or "").split(), speakable(text)
    if " ".join(raw).lower().replace("...", "") == said.lower().replace("...", ""):
        return []
    return [(" ".join(raw), said)]
