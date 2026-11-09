"""Word timings of a recording with faster-whisper (run as a separate process with the Python that has it installed).

    python3 whisper_words.py <audio.wav> [language]   ->   JSON list of {"w", "s", "e"} on stdout
"""
import json
import sys


def main():
    from faster_whisper import WhisperModel
    model = WhisperModel("small", device="cpu", compute_type="int8")
    segments, _ = model.transcribe(sys.argv[1], language=(sys.argv[2] if len(sys.argv) > 2 else "en"), word_timestamps=True,
                                   vad_filter=True)
    words = [{"w": w.word.strip(), "s": round(w.start, 3), "e": round(w.end, 3)} for seg in segments for w in (seg.words or [])
             if w.word.strip()]
    json.dump(words, sys.stdout)


if __name__ == "__main__":
    main()
