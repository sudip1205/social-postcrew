"""Word timings of a recording with faster-whisper (run as a separate process with the Python that has it installed).

    python3 whisper_words.py <audio.wav> [language]   ->   JSON list of {"w", "s", "e", "p"} on stdout
    python3 whisper_words.py --many a.wav b.wav ...   ->   {"a.wav": [...], ...}

VERBATIM (owner, 2026-11-17: "it is not removing duplicate recordings, fumbles"): Whisper normally tidies speech up, dropping repeated
words, false starts and "um"s, so the cleaner could not see them. Here it is asked to write every word as said:
- the large-v3 model on the GPU (small on the CPU when there is no GPU, or WHISPER_MODEL to choose);
- no voice-activity filter (it cut short fumbles), and each segment is not conditioned on the previous text (that smooths repeats away);
- a prompt written in disfluent style, which makes Whisper keep fillers and repetitions.
"p" is Whisper's confidence in the word (0-1): a low value often means a mumbled or mispronounced word.
"""
import json
import os
import sys

DISFLUENT = ("Umm, so, so the the node, uh, holds a- holds a value. Hmm, let me say that again. Like, the, the list, um, it points, "
             "it points to the next one.")


def model():
    from faster_whisper import WhisperModel
    name = os.environ.get("WHISPER_MODEL")
    try:
        import ctranslate2
        gpu = ctranslate2.get_cuda_device_count() > 0
    except Exception:
        gpu = False
    if gpu:
        try:
            return WhisperModel(name or "large-v3", device="cuda", compute_type="float16")
        except Exception:
            pass
    return WhisperModel(name or "small", device="cpu", compute_type="int8")


def words_of(m, path, lang="en"):
    segments, _ = m.transcribe(path, language=lang, word_timestamps=True, vad_filter=False, condition_on_previous_text=False,
                               initial_prompt=DISFLUENT, beam_size=5, temperature=0.0)
    return [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3), "p": round(float(w.probability), 3)}
            for seg in segments for w in (seg.words or []) if w.word.strip()]


def main():
    """One file -> its words; --many f1 f2 ... -> {file: words} (one model load for all)."""
    m = model()
    if sys.argv[1] == "--many":
        json.dump({f: words_of(m, f) for f in sys.argv[2:]}, sys.stdout)
        return
    json.dump(words_of(m, sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "en"), sys.stdout)


if __name__ == "__main__":
    main()
