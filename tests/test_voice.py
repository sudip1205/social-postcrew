"""ElevenLabs voice client against a fake HTTP opener. No network; ffmpeg tests skip when it is missing."""
import io
import json
import shutil
import subprocess
import tempfile
import unittest
import urllib.error
from pathlib import Path

from postcrew import voice
from postcrew.voice import VoiceError

FFMPEG = shutil.which("ffmpeg") and shutil.which("ffprobe")


class Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        self.close()


class FakeHTTP:
    """Answers in order (the last repeats): bytes/dict -> 200 body, int -> HTTP error, (int, body) -> error with body."""

    def __init__(self, *answers):
        self.answers, self.requests = list(answers), []

    def __call__(self, req, timeout=None):
        self.requests.append({"url": req.full_url, "method": req.get_method(), "headers": dict(req.header_items()),
                              "data": req.data})
        a = self.answers.pop(0) if len(self.answers) > 1 else self.answers[0]
        if isinstance(a, Exception):
            raise a
        if isinstance(a, int):
            a = (a, b"")
        if isinstance(a, tuple):
            raise urllib.error.HTTPError(req.full_url, a[0], "err", {}, io.BytesIO(
                a[1] if isinstance(a[1], bytes) else json.dumps(a[1]).encode()))
        return Resp(a if isinstance(a, bytes) else json.dumps(a).encode())


class VoiceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        old = voice.sleep
        voice.sleep = lambda s: None
        self.addCleanup(setattr, voice, "sleep", old)

    def test_synthesize_request_shape(self):
        http = FakeHTTP(b"ID3" + b"x" * 32000)
        r = voice.synthesize("Hello there.", "v1", "KEY", self.root / "a.mp3", "m1", 1.1, http)
        q = http.requests[0]
        self.assertEqual(q["url"], "https://api.elevenlabs.io/v1/text-to-speech/v1?output_format=mp3_44100_128")
        self.assertEqual(q["method"], "POST")
        h = {k.lower(): v for k, v in q["headers"].items()}
        self.assertEqual(h["xi-api-key"], "KEY")
        self.assertEqual(json.loads(q["data"]), {"text": "Hello there.", "model_id": "m1", "voice_settings": {
            "stability": 0.5, "similarity_boost": 0.8, "style": 0.0, "use_speaker_boost": True, "speed": 1.1}})
        self.assertTrue(Path(r["path"]).exists())
        self.assertEqual(r["characters"], 12)
        self.assertGreater(r["seconds"], 0)

    def test_list_voices_and_check_key(self):
        http = FakeHTTP({"voices": [{"voice_id": "a", "name": "Ann", "category": "premade", "preview_url": "u", "x": 1}]})
        self.assertEqual(voice.list_voices("K", http), [{"id": "a", "name": "Ann", "category": "premade", "preview_url": "u"}])
        self.assertTrue(http.requests[0]["url"].endswith("/v1/voices"))
        http = FakeHTTP({"character_count": 100, "character_limit": 10000})
        r = voice.check_key("K", http)
        self.assertTrue(r["ok"])
        self.assertEqual(r["characters_left"], 9900)
        self.assertTrue(http.requests[0]["url"].endswith("/v1/user/subscription"))
        r = voice.check_key("K", FakeHTTP(401))
        self.assertFalse(r["ok"])
        self.assertIn("rejected the API key", r["message"])

    def test_error_mapping(self):
        cases = [(401, "auth"), (403, "auth"), ((429, {"detail": {"status": "quota_exceeded", "message": "no"}}), "quota"),
                 ((400, {"detail": {"message": "bad voice"}}), "invalid"), ((422, {"detail": [{"msg": "too long"}]}), "invalid"),
                 ((200 + 300, b"oops"), "failed")]
        for answer, kind in cases:
            with self.assertRaises(VoiceError) as cm:
                voice.synthesize("hi", "v", "SECRET", self.root / "e.mp3", opener=FakeHTTP(answer))
            self.assertEqual(cm.exception.kind, kind, answer)
            self.assertNotIn("SECRET", str(cm.exception))
        with self.assertRaises(VoiceError) as cm:
            voice.synthesize("hi", "v", "K", self.root / "e.mp3", opener=FakeHTTP((400, {"detail": {"message": "bad voice"}})))
        self.assertIn("bad voice", str(cm.exception))
        with self.assertRaises(VoiceError) as cm:
            voice.synthesize("hi", "v", "K", self.root / "e.mp3", opener=FakeHTTP(urllib.error.URLError("down")))
        self.assertEqual(cm.exception.kind, "network")

    def test_retries_5xx_then_succeeds(self):
        http = FakeHTTP(503, 429, b"audio")
        voice.synthesize("hi", "v", "K", self.root / "r.mp3", opener=http)
        self.assertEqual(len(http.requests), 3)

    def test_cache_hit_makes_no_request(self):
        cfg = {"voice_id": "v", "model": "m", "speed": 1.0}
        http = FakeHTTP(b"x" * 16000)
        a = voice.cached_synthesize(self.root, "Some text.", cfg, "K", http)
        b = voice.cached_synthesize(self.root, "Some text.", cfg, "K", http)
        self.assertEqual(len(http.requests), 1)
        self.assertEqual(a["path"], b["path"])
        self.assertRegex(a["path"], r"cache/voice/[0-9a-f]{40}\.mp3$")
        voice.cached_synthesize(self.root, "Some text.", {**cfg, "speed": 1.2}, "K", http)
        voice.cached_synthesize(self.root, "Other text.", cfg, "K", http)
        self.assertEqual(len(http.requests), 3)

    def test_split_text_at_sentence_ends(self):
        text = " ".join(f"Sentence number {i} is here." for i in range(400))
        pieces = voice.split_text(text)
        self.assertGreater(len(pieces), 1)
        self.assertTrue(all(len(p) <= 4500 for p in pieces))
        self.assertTrue(all(p.endswith(".") for p in pieces))
        self.assertEqual(" ".join(pieces), text)
        self.assertEqual(voice.split_text("Short."), ["Short."])
        self.assertTrue(all(len(p) <= 100 for p in voice.split_text("x" * 250, 100)))

    def test_audio_seconds_fallback_without_ffprobe(self):
        p = self.root / "f.mp3"
        p.write_bytes(b"x" * 32000)
        orig = voice.shutil.which
        voice.shutil.which = lambda name: None
        try:
            self.assertEqual(voice.audio_seconds(p), 2.0)
        finally:
            voice.shutil.which = orig

    def test_pauses_are_added_for_the_voice_only(self):
        said = "A hash is a fingerprint. It never changes... Why does that matter? It lets you compare files."
        out = voice.prepare(said)
        self.assertEqual(out.count('<break time="0.2s" />'), 2)       # after a sentence that is followed by another
        self.assertEqual(out.count('<break time="0.7s" />'), 1)        # the deliberate beat
        self.assertEqual(voice.prepare(out), out)                       # never twice
        self.assertEqual(voice.prepare(said, "eleven_v3"), said)        # v3 has no break tags: it follows the punctuation
        self.assertNotIn("<break", said)

    @unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe not installed")
    def test_long_text_is_synthesized_in_parts_and_joined(self):
        tone = self.root / "tone.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=1",
                        "-b:a", "128k", str(tone)], check=True)
        http = FakeHTTP(tone.read_bytes())
        text = " ".join(f"Sentence number {i} is here." for i in range(400))
        n = len(voice.split_text(voice.prepare(text)))   # the pauses count towards ElevenLabs' size limit
        r = voice.cached_synthesize(self.root, text, {"voice_id": "v"}, "K", http)
        self.assertEqual(len(http.requests), n)
        for q in http.requests:
            self.assertLessEqual(len(json.loads(q["data"])["text"]), 4500)
        self.assertAlmostEqual(r["seconds"], float(n), delta=0.5 * n)
        self.assertEqual(r["characters"], len(voice.prepare(text)))
        self.assertEqual(list((self.root / "cache" / "voice").glob("*.part*")), [])
        voice.cached_synthesize(self.root, text, {"voice_id": "v"}, "K", http)
        self.assertEqual(len(http.requests), n)

    @unittest.skipUnless(FFMPEG, "ffmpeg/ffprobe not installed")
    def test_audio_seconds_uses_ffprobe(self):
        p = self.root / "t.mp3"
        subprocess.run(["ffmpeg", "-y", "-v", "error", "-f", "lavfi", "-i", "sine=duration=2", str(p)], check=True)
        self.assertAlmostEqual(voice.audio_seconds(p), 2.0, delta=0.2)


if __name__ == "__main__":
    unittest.main()


class HumanVoiceTests(unittest.TestCase):
    def test_nothing_is_left_for_the_voice_to_guess(self):
        out = voice.prepare("Move UP the list. The API is NOT slow, and TCP uses LOAD balancing.", pace="normal")
        self.assertIn("Move up the list", out)
        self.assertIn("The A P I is not slow", out)
        self.assertIn("T C P", out)
        self.assertIn("load balancing", out)

    def test_symbols_and_numbers_are_spelled_out(self):
        out = voice.prepare("At 9 - 7 = 2, O(n^2) is slow: 95% of $4.50 in 20ms.", model="eleven_v3")
        self.assertEqual(out, "At nine minus seven equals two, O of n squared is slow: ninety five percent of four dollars and fifty "
                              "cents in twenty milliseconds.")

    def test_break_tags_are_capped_because_too_many_cause_artifacts(self):
        out = voice.prepare("One here. Two here. Three here. Four here. Five here. Six here... Seven there.")
        self.assertLessEqual(out.count("<break"), voice.MAX_BREAKS)
        many = voice.prepare(" ".join("In Rome, we do this and that." for _ in range(40)))
        self.assertLessEqual(many.count("<break"), voice.MAX_BREAKS)
        self.assertIn('<break time="0.7s" />', out)   # the deliberate beat is kept first

    def test_a_clause_ending_comma_stops_the_voice_but_list_items_do_not(self):
        out = voice.prepare("In Python, a list works. Take curly, square, round, closing in reverse.")
        self.assertIn('In Python, <break time="0.1s" /> a list works.', out)
        self.assertIn("square, round, closing", out)   # list items keep the voice's own breath

    def test_the_voice_settings_stay_steady_so_it_does_not_invent_sounds(self):
        self.assertGreaterEqual(voice.HUMAN["stability"], 0.5)
        self.assertEqual(voice.HUMAN["style"], 0)
