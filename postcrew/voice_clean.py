"""Cleaning the owner's recording of a script (Factory > Plans > Voice). Owner, 2026-11-17: "when voice is processing it is not removing
duplicate recordings, fumbles ... it is also catching all mispronounced words. fix that".

Input: the words of the recording as they were SAID (whisper_words.py, verbatim: repeats, restarts and fillers are written down too) and
the script's lines. Output, per sentence of the script: which recorded words to keep.

1. Every place a sentence was (re)started is a candidate take. Each candidate is aligned word by word with the script sentence; similar
   words count ("singly"/"singli", "prev"/"previous", "3rd"/"third"), and a word that differs (said "lived" for "link") is a
   MISPRONOUNCED word.
2. One take is chosen per sentence, in order, over the whole recording (dynamic programming): the cleanest takes win, a take with a
   mispronounced word loses to a clean retake, and between equally good takes the LAST one wins (a retake is said because the first
   one was wrong).
3. Inside the chosen take, words that are not in the script are cut: stutters ("from from"), fillers ("um"), restarts inside the
   sentence ("four pointer change. Next previous. Insert after B four pointer change" keeps only the last).
4. A sentence whose best take still has a mispronounced word is marked: it is read by the AI voice instead, and the report names it so
   it can be recorded again.
"""
import re
from difflib import SequenceMatcher

_ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
_TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()
_ORD = {"1st": "first", "2nd": "second", "3rd": "third", "4th": "fourth", "5th": "fifth", "6th": "sixth", "7th": "seventh",
        "8th": "eighth", "9th": "ninth", "10th": "tenth"}
SMALL = {"a", "an", "the", "is", "are", "was", "and", "or", "of", "to", "in", "on", "it", "its", "it's", "this", "that", "so", "s", "be",
         "will", "would", "can", "could", "for", "at", "by", "with", "you", "we", "then", "now", "just"}
FILLERS = {"um", "umm", "uh", "uhh", "uhm", "er", "erm", "ah", "hmm", "mm", "mhm"}
OK_SIM = 0.6        # two words this similar are the same word said or spelled a little differently
BAD_PROB = 0.12     # Whisper this unsure of a word that matches: still fine (a mumble is rarely this low and right)


def sentences(text):
    """A line's sentences ("use?Doubly" splits too)."""
    return [s.strip() for s in re.split(r"(?<=[.!?])\s*(?=[A-Z0-9\"'])|(?<=[.!?])\s+", str(text).strip()) if s and s.strip()]


def _num(n):
    if n < 20:
        return [_ONES[n]]
    if n < 100:
        return [_TENS[n // 10]] + ([_ONES[n % 10]] if n % 10 else [])
    for size, word in ((10**9, "billion"), (10**6, "million"), (1000, "thousand"), (100, "hundred")):
        if n >= size:
            return _num(n // size) + [word] + (_num(n % size) if n % size else [])
    return []


def _tok(w):
    return re.sub(r"[^a-z0-9']", "", w.lower()).strip("'")


def word_tokens(word):
    """One written word -> the tokens it is said as ("45" -> forty five, "3rd" -> third, "B's" -> bs)."""
    w = str(word).strip()
    raw = w.replace(",", "") if re.fullmatch(r"\W*\d{1,3}(,\d{3})+\W*", w) else w
    m = re.fullmatch(r"\W*(\d+)(?:\.(\d+))?(%|x|k)?\W*", raw, re.I)
    if m and len(m.group(1)) <= 12:
        out = _num(int(m.group(1)))
        if m.group(2):
            out += ["point"] + [_ONES[int(c)] for c in m.group(2)]
        return out + {"%": ["percent"], "x": ["x"], "k": ["thousand"]}.get((m.group(3) or "").lower(), [])
    t = _tok(w)
    t = _ORD.get(t, t)
    return [t] if t else []


def raw_words(text):
    return [x for x in re.split(r"[\s\-–—/]+|(?<=[.!?:;,])(?=[A-Za-z])", str(text)) if x]


def tokens(text):
    """[(token, index of the written word it came from)] for a text; words split on spaces, hyphens, slashes and glued punctuation."""
    out = []
    for k, w in enumerate(raw_words(text)):
        out += [(t, k) for t in word_tokens(w)]
    return out


def spoken(script_sentence, toks, ops, words, heard):
    """What dip_puck reads for you (the American version): the script's sentence, with YOUR reading of its abbreviations ("prev" said
    as "previous"). Everything else stays the script's words: a slip of the tongue is not copied."""
    raw = raw_words(script_sentence)
    for o in ops:
        if o[0] != "m":
            continue
        t, k = toks[o[1]]
        w = raw[k]
        core = re.sub(r"[^A-Za-z]", "", w)
        said = re.sub(r"[^A-Za-z']", "", words[heard[o[2]][1]]["w"])
        if core and (core.isupper() or len(core) <= 4) and said.lower().startswith(core.lower()) and len(said) >= len(core) + 2:
            raw[k] = w.replace(core, said.lower() if not core.isupper() else said)
    return " ".join(raw)


def sim(a, b):
    if a == b:
        return 1.0
    if a in SMALL and b in SMALL:   # "a" for "the", "is" for "'s": the owner's own wording, not a mistake
        return OK_SIM
    if not a or not b:
        return 0.0
    if a.startswith(b) or b.startswith(a):   # prev / previous, doubly / double-ly
        return max(0.7, SequenceMatcher(None, a, b).ratio())
    return SequenceMatcher(None, a, b).ratio()


def heard_tokens(words):
    """The recording's tokens, each with the index of its word."""
    out = []
    for k, w in enumerate(words):
        out += [(t, k) for t in word_tokens(w["w"])]
    return out


# ---------- one take: the script sentence aligned to the recording from a start ----------
MATCH, SUB, MISS, EXTRA = 2.0, -1.6, -1.4, -0.45   # a wrong word costs less than a missing word + an extra one: it is a mispronunciation


def align_from(script_toks, heard, start, limit):
    """Global on the script sentence, free end on the recording: (score, end, ops). ops: ("m", si, hi) a match (hi = heard token index),
    ("x", si, hi) a mispronounced word, ("-", si, None) a word not said, ("+", None, hi) a word said that is not in the script."""
    n, m = len(script_toks), max(0, min(len(heard), limit) - start)
    if not n or not m:
        return (-1e9, start, [])
    neg = -1e9
    D = [[neg] * (m + 1) for _ in range(n + 1)]
    B = [[None] * (m + 1) for _ in range(n + 1)]
    D[0][0] = 0.0
    for b in range(1, m + 1):   # words said before the sentence starts are not free: a take starts at its first word
        D[0][b] = neg
    for a in range(1, n + 1):
        D[a][0] = D[a - 1][0] + MISS
        B[a][0] = "-"
    for a in range(1, n + 1):
        sa = script_toks[a - 1]
        for b in range(1, m + 1):
            h = heard[start + b - 1][0]
            s = sim(sa, h)
            best, how = (D[a - 1][b - 1] + (MATCH * s if s >= OK_SIM else SUB)), ("m" if s >= OK_SIM else "x")
            v = D[a - 1][b] + MISS
            if v > best:
                best, how = v, "-"
            v = D[a][b - 1] + (EXTRA * (0.4 if h in FILLERS else 1.0))
            if v > best:
                best, how = v, "+"
            D[a][b], B[a][b] = best, how
    end = max(range(1, m + 1), key=lambda b: (D[n][b], -b))
    ops, a, b = [], n, end
    while a > 0 or b > 0:
        how = B[a][b] if a > 0 else "+"
        if how in ("m", "x"):
            ops.append((how, a - 1, start + b - 1)); a -= 1; b -= 1
        elif how == "-":
            ops.append(("-", a - 1, None)); a -= 1
        else:
            ops.append(("+", None, start + b - 1)); b -= 1
    ops.reverse()
    while ops and ops[0][0] == "+":   # a take starts and ends on script words
        ops.pop(0)
    while ops and ops[-1][0] == "+":
        ops.pop()
    return D[n][end], end, ops


def candidates(script_toks, heard, lo=0, hi=None):
    """Every take of a sentence in heard[lo:hi]: starts where one of its first words was said."""
    hi = len(heard) if hi is None else hi
    n = len(script_toks)
    heads = script_toks[:3]
    out = []
    for i in range(lo, hi):
        if not any(sim(heads[k], heard[i][0]) >= 0.75 for k in range(len(heads))):
            continue
        score, end, ops = align_from(script_toks, heard, i, i + 2 * n + 12)
        if not ops:
            continue
        said = [o for o in ops if o[0] in ("m", "x")]
        good = sum(1 for o in ops if o[0] == "m")
        if good < max(1, 0.5 * n):
            continue
        hs = [o[2] for o in ops if o[2] is not None]
        out.append({"i": min(hs), "j": max(hs) + 1, "score": score / (MATCH * n), "ops": ops, "good": good, "said": len(said),
                    "bad": sum(1 for o in ops if o[0] == "x")})
    # one candidate per (start, end): keep the best
    best = {}
    for c in out:
        k = (c["i"], c["j"])
        if k not in best or c["score"] > best[k]["score"]:
            best[k] = c
    return list(best.values())


def choose(heard, sents):
    """One take per sentence, in order, over the whole recording. sents: [script tokens]. Returns [candidate or None]."""
    H = len(heard)
    cands = [sorted(candidates(st, heard), key=lambda c: c["i"]) for st in sents]
    # DP over sentences: state = (sentence k, chosen candidate) with the end position; a skipped sentence costs SKIP
    SKIP = -0.6
    LATE = 0.04   # tie-break: the later of two equally good takes (the retake)
    import math
    best = [{} for _ in sents]   # best[k][c_idx or -1-end] = (value, prev key)
    prev_states = {("start", 0): (0.0, None)}   # key -> (value, back)
    for k, cs in enumerate(cands):
        states = {}
        for key, (val, _) in prev_states.items():
            end = key[1]
            # skip this sentence
            sk = ("skip", end, k)
            v = val + SKIP
            if sk not in states or v > states[sk][0]:
                states[sk] = (v, key)
            for ci, c in enumerate(cs):
                if c["i"] < end:
                    continue
                v = val + c["score"] + LATE * (c["i"] / max(1, H))
                ck = ("c", c["j"], k, ci)
                if ck not in states or v > states[ck][0]:
                    states[ck] = (v, key)
        # keep the states small: the best value for each end position
        pruned = {}
        for key, (v, back) in states.items():
            e = key[1]
            if e not in pruned or v > pruned[e][1][0]:
                pruned[e] = (key, (v, back))
        prev_states = {key: vb for key, vb in pruned.values()}
        best[k] = dict(states)
    # trace back from the best final state
    key = max(prev_states, key=lambda kk: prev_states[kk][0])
    picks = [None] * len(sents)
    for k in range(len(sents) - 1, -1, -1):
        if key[0] == "c":
            picks[k] = cands[k][key[3]]
        key = best[k][key][1]
    return picks


def clean(words, texts):
    """The whole cleaning. Returns sentences: [{"line", "text", "keep": [word indices], "bad": [(said, script)], "missing": bool}] and
    the words cut (each cut stretch as text)."""
    heard = heard_tokens(words)
    flat = []
    for li, t in enumerate(texts):
        for s in sentences(t):
            st = tokens(s)
            if st:
                flat.append({"line": li, "text": s, "toks": st})
    picks = choose(heard, [[t for t, _ in f["toks"]] for f in flat])
    used, out = set(), []
    for f, c in zip(flat, picks):
        if not c:
            out.append({"line": f["line"], "text": f["text"], "keep": [], "bad": [], "missing": True})
            continue
        keep = sorted({heard[o[2]][1] for o in c["ops"] if o[0] in ("m", "x")} | _extras_to_keep(words, heard, c["ops"]))
        # a word said twice in a row inside the take (a stutter): keep the second
        keep = _drop_stutters(words, keep)
        bad = [(words[heard[o[2]][1]]["w"], f["toks"][o[1]][0]) for o in c["ops"]
               if o[0] == "x" and not (f["toks"][o[1]][0] in SMALL or _tok(words[heard[o[2]][1]]["w"]) in SMALL)]
        lead = 0
        while lead < len(c["ops"]) and c["ops"][lead][0] == "-":
            lead += 1
        first = heard[c["ops"][lead][2]][1] if lead < len(c["ops"]) and c["ops"][lead][2] is not None else None
        if 0 < lead <= 2 and first and first - 1 >= 0 and first - 1 not in used and words[first]["s"] - words[first - 1]["e"] < 0.5 \
                and _tok(words[first - 1]["w"]) not in FILLERS:
            keep = [first - 1] + keep   # the first word, heard as another word ("Here" for "Your"): it was said, keep it
        # words of the script the take does not have (said "double latest" for "doubly linked list"): the sentence is not complete
        bad += [("", f["toks"][o[1]][0]) for k, o in enumerate(c["ops"]) if o[0] == "-" and k >= lead and f["toks"][o[1]][0] not in SMALL]
        bad = [b for b in bad if b[0] or b[1] not in [x[1] for x in bad if x[0]]]
        used.update(range(keep[0], keep[-1] + 1) if keep else [])
        said = " ".join(words[k]["w"] for k in keep)
        out.append({"line": f["line"], "text": f["text"], "keep": keep, "bad": bad, "missing": False, "score": round(c["score"], 2),
                    "said": said, "spoken": spoken(f["text"], f["toks"], c["ops"], words, heard)})
    kept = {k for s in out for k in s["keep"]}
    removed, run = [], []
    for k, w in enumerate(words):
        if k in kept:
            if run:
                removed.append(" ".join(run)); run = []
        else:
            run.append(w["w"])
    if run:
        removed.append(" ".join(run))
    return out, removed


def _extras_to_keep(words, heard, ops):
    """Words said inside the take that are not in the script. Cut: fillers, a restart (3+ words, or words that repeat what comes next).
    Kept: one or two words of the owner's own wording ("is a big win", "you would use"); cutting them would break the sentence."""
    keep, run = set(), []

    def done(nxt):
        ks = sorted({heard[h][1] for h in run})
        if not ks:
            return
        said = [_tok(words[k]["w"]) for k in ks]
        if len(ks) <= 2 and not all(x in FILLERS for x in said):
            ahead = [_tok(words[k]["w"]) for k in range(ks[-1] + 1, min(len(words), ks[-1] + 1 + len(ks)))]
            if said != ahead:   # not a repeat of the next words
                keep.update(k for k, x in zip(ks, said) if x not in FILLERS)

    for o in ops:
        if o[0] == "+":
            run.append(o[2])
        else:
            if run:
                done(o)
            run = []
    return keep


def _drop_stutters(words, keep):
    out = []
    for k in keep:
        if out and _tok(words[out[-1]]["w"]) == _tok(words[k]["w"]) and words[k]["s"] - words[out[-1]]["e"] < 1.0:
            out[-1] = k   # "from from": the second one
            continue
        out.append(k)
    return out

