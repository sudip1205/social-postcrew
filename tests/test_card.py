"""LinkedIn images in the Signal Board style (owner, 2026-11-24: "for linkedin post do not create movies. create images instead.
Refer this kind of images. and create a own attractive style.")."""
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from postcrew.render import card  # noqa: E402

SAMPLES = json.loads((Path(__file__).parent / "card_samples.json").read_text())


class CardSpecTests(unittest.TestCase):
    def test_every_layout_has_a_sample_and_the_samples_are_valid(self):
        self.assertEqual(set(SAMPLES), set(card.LAYOUTS))
        for name, spec in SAMPLES.items():
            self.assertEqual(card.validate_spec(spec), [], name)

    def test_what_a_layout_needs_is_said_before_drawing(self):
        self.assertIn("the compare layout needs 2 or 3 columns", card.validate_spec({"layout": "compare", "title": "x", "rows": [{}, {}]}))
        bad = dict(SAMPLES["compare"], rows=[{"label": "Time", "cells": ["1", "2"]}, {"label": "Cost", "cells": ["a", "b", "c"]}])
        self.assertIn("every compare row needs one cell per column", card.validate_spec(bad))
        self.assertTrue(card.validate_spec({"layout": "stats", "title": "x", "stats": [{"value": "1"}]}))

    def test_the_shown_text_has_every_word_and_number_without_the_accent_marks(self):
        t = card.shown_text(SAMPLES["stats"])
        for w in ("Six major banks went down.", "~8.5 hrs", "38%+", "Bank spokesperson", "resilience plan"):
            self.assertIn(w, t)
        self.assertNotIn("[[", t)
        self.assertIn("4,760", card.shown_text(SAMPLES["bars"]))

    def test_the_page_escapes_text_and_marks_the_accent_words(self):
        spec = dict(SAMPLES["points"], title="<b>Bad</b> and [[good]]")
        page = card.page(spec, "me", "Source: x")
        self.assertIn("&lt;b&gt;Bad&lt;/b&gt;", page)
        self.assertIn('<span class="acc">good</span>', page)
        self.assertNotIn("url(/static/fonts/", page)   # the fonts load from the Studio's own files, by full path
        self.assertIn(f"url(file://{card.STATIC}/fonts/", page)

    @unittest.skipUnless(card.chrome(), "Chrome is needed to draw the image")
    def test_a_sample_is_drawn_and_too_much_text_is_refused(self):
        with tempfile.TemporaryDirectory() as d:
            out = Path(d) / "c.png"
            card.render_card(SAMPLES["flow"], out, "example.com/me", "Source: example.com")
            from PIL import Image
            self.assertEqual(Image.open(out).size, (card.W, card.H))
            huge = dict(SAMPLES["points"], points=[{"head": "A long point " * 6, "body": "word " * 60}] * 5)
            with self.assertRaises(card.CardError):
                card.render_card(huge, Path(d) / "h.png")

    def test_cards_can_be_switched_off(self):
        with mock.patch.dict(os.environ, {"POSTCREW_CARDS": "off"}):
            self.assertFalse(card.available())


class VisualDesignerTests(unittest.TestCase):
    def test_linkedin_gets_a_still_image_even_for_a_video_category(self):
        from postcrew.agents.media import MediaAgent
        with tempfile.TemporaryDirectory() as d:
            ctx = mock.Mock()
            ctx.profile = {"handle": "example.com/me"}
            ctx.cat = {"media": "video", "label": "AI news"}
            ctx.outputs = {"writer": {"text": "One software bug. Six major banks went down for ~8.5 hrs.", "first_comment": ""},
                           "topic": {"topic": "Bank outage"}}
            ctx.previous = {}
            ctx.run.dir = Path(d)
            agent = MediaAgent()
            drawn = []
            with mock.patch.object(card, "available", return_value=True), \
                    mock.patch.object(card, "render_card", side_effect=lambda spec, path, *a: drawn.append(path) or {"scale": 1}), \
                    mock.patch.object(MediaAgent, "prompt", return_value="system"), \
                    mock.patch.object(MediaAgent, "ask", return_value=dict(SAMPLES["points"])):
                out = agent.run(ctx, None)
            self.assertEqual(out["kind"], "image")
            self.assertEqual(out["style"], "signal-board")
            self.assertTrue(out["path"].endswith("image.png"))
            self.assertEqual(len(drawn), 1)
            self.assertEqual(agent.summary(out), "image (points, Signal Board)")



class ThumbnailTests(unittest.TestCase):
    """Every Short gets a designed thumbnail when it is queued, and the upload sets it (owner, 2026-11-25)."""
    def test_a_designed_thumbnail_replaces_the_video_frame(self):
        from postcrew.agents import yt_publish
        from tests.helpers import TempWorkspace
        spec = {"tag": "Failover", "accent": "fire", "hook": "The server [[dies.]] Now what?",
                "graphic": {"type": "flow", "nodes": [{"icon": "dns", "label": "Active"}, {"icon": "dns", "label": "Passive"}], "bad": 0, "good": 1}}
        llm = mock.Mock(); llm.call.return_value = mock.Mock(data=spec)
        with TempWorkspace() as ws, mock.patch.dict(os.environ, {"POSTCREW_CARDS": "on"}), \
                mock.patch("postcrew.render.card.chrome", return_value="/bin/chrome"), \
                mock.patch("postcrew.render.thumb.render_thumb", side_effect=lambda s, path, h: __import__("PIL.Image").Image.new("RGB", (1080, 1920)).save(path)):
            out = yt_publish.designed_thumbnail(ws, ws.config(), {"title": "Active-Passive Failover", "narration": "a server dies"},
                                                ws.root / "media" / "p-thumb.jpg", llm=llm)
            self.assertTrue(out and out.exists())
            self.assertEqual(json.loads(out.with_suffix(".json").read_text())["hook"], spec["hook"])
            self.assertIsNone(yt_publish.designed_thumbnail(ws, ws.config(), {"title": "x", "long": True}, ws.root / "l.jpg", llm=llm))
            llm.call.side_effect = RuntimeError("offline")
            self.assertIsNone(yt_publish.designed_thumbnail(ws, ws.config(), {"title": "x"}, ws.root / "f.jpg", llm=llm))


if __name__ == "__main__":
    unittest.main()
