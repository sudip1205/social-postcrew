"""Your own plans (Manual run) reach every agent that shapes the video, and YouTube analytics read the connected channel."""
import unittest
from datetime import date
from types import SimpleNamespace

from postcrew import monthly, yt_analytics
from postcrew.agents.base import owner_plan_block
from postcrew.youtube import YouTubeError, _duration

from helpers import TempWorkspace

DAY = date(2026, 11, 4)


class OwnPlanTests(unittest.TestCase):
    def test_a_plan_you_write_waits_for_you_and_survives_generate_and_pruning(self):
        with TempWorkspace() as ws:
            i = monthly.add_manual(ws, "youtube", "Dijkstra on a city map", "Shortest path. Use 5 junctions.",
                                   "Animate each step, code beside it.", "long", references=["https://example.com/d"], today=DAY)
            self.assertTrue(i["manual"])
            self.assertEqual((i["angle"], i["format"]), ("Shortest path.", "long"))
            ids = [u["id"] for u in monthly.unassigned(ws, "youtube")]
            self.assertIn(i["id"], ids)
            monthly.clear_plans(ws, "youtube")                    # Generate plan starts clean, but not with your plans
            monthly.prune_stale_topics(ws, "youtube")             # "Your own plans" is not a Settings topic
            self.assertEqual(monthly.auto_assign(ws, "youtube", "2026-11", today=DAY)["assigned"], 0)   # never put on a day by itself
            self.assertIn(i["id"], [u["id"] for u in monthly.unassigned(ws, "youtube")])
            monthly.add_manual(ws, "youtube", "Dijkstra on a city map", "Shortest path.", "Slower, calmer.", "short", item_id=i["id"])
            self.assertEqual(next(u for u in monthly.unassigned(ws, "youtube") if u["id"] == i["id"])["how"], "Slower, calmer.")
            monthly.remove_manual(ws, "youtube", i["id"])
            self.assertNotIn(i["id"], [u["id"] for u in monthly.unassigned(ws, "youtube")])

    def test_bad_input_is_refused(self):
        with TempWorkspace() as ws:
            for args in (("ab",), ("Good topic", "x" * 3001), ("Good topic", "", "", "medium")):
                with self.assertRaises(ValueError):
                    monthly.add_manual(ws, "youtube", *args)
            with self.assertRaises(ValueError):
                monthly.add_manual(ws, "youtube", "Good topic", references=["not a link"])

    def test_running_it_carries_your_plan_to_the_agents_that_shape_the_video(self):
        with TempWorkspace() as ws:
            i = monthly.add_manual(ws, "youtube", "Dijkstra on a city map", "Use 5 junctions.", "Animate each step.", "short", today=DAY)
            info = monthly.run_plan(ws, "youtube", i["id"], "short", DAY)
            self.assertEqual(info["item"]["id"], i["id"])
            e = monthly._entry(dict(i, assigned={"date": DAY.isoformat()}), "assigned-short", "short", "youtube")
            self.assertEqual(e["owner_plan"]["how"], "Animate each step.")
            self.assertEqual(e["brief"]["context"], "Use 5 junctions.")
            ctx = SimpleNamespace(outputs={"topic": {"owner_plan": e["owner_plan"]}})
            for agent in ("writer", "direction", "graphics", "editor", "quality"):
                self.assertIn("Animate each step.", owner_plan_block(ctx, agent))
            self.assertEqual(owner_plan_block(ctx, "publisher"), "")
            self.assertEqual(owner_plan_block(SimpleNamespace(outputs={}), "writer"), "")


class FakeYT:
    deny = False

    def __init__(self, *a):
        pass

    def channel_stats(self):
        return {"id": "UC1", "title": "Dip-to-Dive", "subscribers": 120, "views": 5000, "videos": 2, "uploads": "UU1"}

    def uploads(self, playlist, limit=200):
        return ["v1", "v2"]

    def videos(self, ids):
        return [{"id": "v1", "title": "Climbing Stairs", "published_at": "2026-11-03T18:00:00Z", "seconds": 150, "views": 900, "likes": 40,
                 "comments": 5, "privacy": "public", "thumbnail": ""},
                {"id": "v2", "title": "My own upload", "published_at": "2026-10-01T18:00:00Z", "seconds": 900, "views": 100, "likes": 2,
                 "comments": 0, "privacy": "public", "thumbnail": ""},
                {"id": "v3", "title": "Draft", "published_at": "2026-10-02T18:00:00Z", "seconds": 60, "views": 1, "likes": 0,
                 "comments": 0, "privacy": "private", "thumbnail": ""},
                {"id": "v4", "title": "Shared link only", "published_at": "2026-10-03T18:00:00Z", "seconds": 60, "views": 3, "likes": 0,
                 "comments": 0, "privacy": "unlisted", "thumbnail": ""}]

    def report(self, start, end, metrics, dimensions="", sort="", filters="", limit=200):
        if FakeYT.deny:
            raise YouTubeError("YouTube refused access (Request had insufficient authentication scopes.): reconnect", "auth", 403)
        if dimensions == "video":
            return [{"video": "v1", "views": 900, "estimatedMinutesWatched": 1200, "averageViewDuration": 80, "averageViewPercentage": 53.3,
                     "likes": 40, "comments": 5, "shares": 3, "subscribersGained": 9}]
        return [{"day": "2026-11-03", "views": 700, "estimatedMinutesWatched": 900, "subscribersGained": 8, "subscribersLost": 1}]


class AnalyticsTests(unittest.TestCase):
    def connect(self, ws):
        ws.update_secrets(youtube_client_id="1-a.apps.googleusercontent.com", youtube_client_secret="s", youtube_refresh_token="r")
        ws.add_history({"id": "p1", "platform": "youtube", "topic": "Climbing Stairs", "run_id": "r1",
                        "youtube": {"video_id": "v1", "format": "short", "picture": {"score": 82}}})

    def test_every_video_with_the_crews_marked_and_their_watch_time(self):
        with TempWorkspace() as ws:
            self.connect(ws)
            FakeYT.deny = False
            d = yt_analytics.build(ws, FakeYT, today=date(2026, 11, 4))
            self.assertEqual(d["channel"]["title"], "Dip-to-Dive")
            v1, v2 = d["videos"]                                                  # private and unlisted left out
            self.assertEqual((v1["crew"]["post_id"], v1["format"], v1["analytics"]["averageViewPercentage"]), ("p1", "short", 53.3))
            self.assertIsNone(v2["crew"])
            self.assertEqual(v2["format"], "long")
            self.assertEqual((d["summary"]["crew_videos"], d["summary"]["crew_views"], d["summary"]["crew_minutes"]), (1, 900, 1200))
            self.assertEqual(d["analytics"]["daily"][0]["views"], 700)

    def test_an_older_connection_still_shows_the_counts_and_says_how_to_get_the_rest(self):
        with TempWorkspace() as ws:
            self.connect(ws)
            FakeYT.deny = True
            d = yt_analytics.overview(ws, FakeYT, refresh=True)
            self.assertFalse(d["analytics"]["ok"])
            self.assertIn("reconnect YouTube", d["analytics"]["message"])
            self.assertEqual(d["videos"][0]["views"], 900)
            FakeYT.deny = False
            self.assertTrue(yt_analytics.overview(ws, FakeYT)["cached"])          # fresh for 30 minutes

    def test_not_connected_and_durations(self):
        with TempWorkspace() as ws:
            self.assertFalse(yt_analytics.build(ws, FakeYT)["connected"])
        self.assertEqual((_duration("PT2M30S"), _duration("PT1H"), _duration("P0D"), _duration("bad")), (150, 3600, 0, None))



# ---------- PDFs and images attached to your own plan ----------
import io
import json

from postcrew import attachments
from postcrew.llm import LLMResult


class FakeRunner:
    def __init__(self):
        self.calls = []

    def __call__(self, cmd, **kw):
        self.calls.append(cmd)
        if cmd[0] == "pdftotext":
            return SimpleNamespace(stdout="Two Sum\nGiven nums and target, return indices.\nExample: nums = [2,7,11,15], target = 9 -> [0,1]",
                                   returncode=0)
        if cmd[0] == "pdfinfo":   # one tall page: a full-page screenshot of a web page
            return SimpleNamespace(stdout="Pages:          1\nPage    1 size: 612 x 1600 pts\n", returncode=0)
        from pathlib import Path
        Path(cmd[-1] + ".png").write_bytes(b"png")
        return SimpleNamespace(stdout="", returncode=0)


class ReaderLLM:
    def __init__(self):
        self.calls = []

    def call(self, agent_id, system, prompt, schema, **kw):
        self.calls.append((agent_id, prompt, kw.get("images")))
        return LLMResult(data={"title": "Two Sum", "statement": "Given nums and target, return indices.", "input_output": "list, int -> [i, j]",
                               "examples": [{"input": "nums = [2,7,11,15], target = 9", "output": "[0,1]", "explanation": "2+7"}],
                               "constraints": ["one answer"], "figures": ["an array of 4 boxes, 2 and 7 circled"], "solution_notes": "",
                               "unclear": []}, cost_usd=0, model="fake", turns=1)


class AttachmentTests(unittest.TestCase):
    def test_a_pdf_is_read_by_text_and_pages_and_the_problem_reaches_the_agents(self):
        with TempWorkspace() as ws:
            i = monthly.add_manual(ws, "youtube", "Two Sum explained", "", "Draw the array.", "short", today=DAY)
            pdf = b"%PDF-1.4 problem"
            attachments.save_upload(ws, "youtube", i["id"], "two-sum.pdf", io.BytesIO(pdf), len(pdf))
            png = b"\x89PNG figure"
            src = attachments.save_upload(ws, "youtube", i["id"], "figure.png", io.BytesIO(png), len(png))
            self.assertEqual(([f["kind"] for f in src["files"]], src["state"]), (["pdf", "image"], "new"))
            llm, runner = ReaderLLM(), FakeRunner()
            src = attachments.read(ws, "youtube", i["id"], llm=llm, runner=runner)
            self.assertEqual(src["state"], "done")
            agent, prompt, images = llm.calls[0]
            self.assertEqual(agent, "reader")
            self.assertIn("return indices", prompt)                          # the PDF's exact text
            self.assertEqual(len(images), 5)                     # the tall page in 4 overlapping sharp strips, and the image
            strips = [c for c in runner.calls if c[0] == "pdftoppm"]
            self.assertEqual([c[c.index("-y") + 1] for c in strips], ["0", "1380", "2760", "4140"])
            self.assertIn("220", strips[0])
            item = next(u for u in monthly.unassigned(ws, "youtube") if u["id"] == i["id"])
            e = monthly._entry(item, "assigned-short", "short", "youtube")
            ctx = SimpleNamespace(outputs={"topic": {"owner_plan": e["owner_plan"]}})
            block = owner_plan_block(ctx, "writer")
            for want in ("THE PROBLEM", "two-sum.pdf", "Example 1: input nums = [2,7,11,15], target = 9 -> output [0,1]",
                         "Figure 1 (redraw it faithfully): an array of 4 boxes"):
                self.assertIn(want, block)
            attachments.remove_file(ws, "youtube", i["id"], src["files"][0]["file"])
            monthly.remove_manual(ws, "youtube", i["id"])
            self.assertFalse((ws.root / "plans" / "youtube" / i["id"]).exists())

    def test_wrong_files_are_refused(self):
        with TempWorkspace() as ws:
            i = monthly.add_manual(ws, "youtube", "Two Sum explained", today=DAY)
            for name, data in (("notes.docx", b"x"), ("fake.pdf", b"not a pdf"), ("empty.png", b"")):
                with self.assertRaises(ValueError):
                    attachments.save_upload(ws, "youtube", i["id"], name, io.BytesIO(data), len(data))
            with self.assertRaises(ValueError):
                attachments.plan_dir(ws, "youtube", "../etc")

    def test_a_plan_with_unread_files_does_not_run(self):
        from postcrew.studio.server import Studio
        with TempWorkspace() as ws:
            i = monthly.add_manual(ws, "youtube", "Two Sum explained", today=DAY)
            attachments.save_upload(ws, "youtube", i["id"], "p.pdf", io.BytesIO(b"%PDF-1"), 6)
            with self.assertRaises(ValueError) as e:
                Studio(ws, 0).manual_run({"platform": "youtube", "id": i["id"], "format": "short"})
            self.assertIn("not read yet", str(e.exception))



# ---------- a real 2-D board ----------
from postcrew import gridviz
from postcrew import shapes

BOARD = ["BGBBGB", "GGGGGG", "BGBBGB", "GGGGGG", "BGBBGB", "BGBBGB"]   # HackerRank Two Pluses, sample 1


def board_scene(steps):
    return {"title": "Two pluses", "rows": BOARD, "legend": ["G = good", "B = bad"], "blocked": ["B"], "steps": steps}


def step(**kw):
    return {"say": "", "active": [], "found": [], "out": [], "marks": [], "pluses": [], "note": "", **kw}


class GridTests(unittest.TestCase):
    def test_a_plus_is_drawn_whole_and_a_wrong_one_is_refused(self):
        self.assertEqual(sorted(gridviz.plus_cells(1, 1, 1)), [(0, 1), (1, 0), (1, 1), (1, 2), (2, 1)])
        ok = board_scene([step(say="first plus", pluses=["1,1,1"], marks=["centre=1,1"], note="arm 1: area 5"),
                          step(say="second plus", pluses=["1,1,1", "3,4,1"], note="5 x 5 = 25")])
        self.assertEqual(gridviz.problems(ok, 3), [])
        bad = board_scene([step(pluses=["1,2,1"])])                       # its top cell (0,2) is B
        self.assertIn("covers cell 0,2, which is 'B'", gridviz.problems(bad, 3)[0])
        off = board_scene([step(pluses=["0,1,1"])])                       # its arm leaves the board
        self.assertIn("runs off the 6x6 board", gridviz.problems(off, 3)[0])
        ragged = dict(board_scene([step()]), rows=["GGG", "GG"])
        self.assertIn("same length", gridviz.problems(ragged, 3)[0])

    def test_the_board_is_timed_to_the_voice(self):
        words = {"first plus": 1.0, "second plus": 4.0}
        p = gridviz.props(board_scene([step(say="first plus", pluses=["1,1,1"]), step(say="second plus", pluses=["1,1,1", "3,4,1"])]),
                          lambda say, after: words.get(say, after))
        self.assertEqual([s["t"] for s in p["steps"]], [1.0, 4.0])
        self.assertEqual(p["steps"][1]["pluses"][1], {"label": "area 5", "cells": [[3, 4], [2, 4], [4, 4], [3, 3], [3, 5]]})
        self.assertEqual(p["blocked"], ["B"])

    def test_a_grid_problem_drawn_on_a_strip_is_sent_back(self):
        ctx = SimpleNamespace(outputs={"topic": {"topic": "Two Pluses", "angle": "",
                                                 "owner_plan": {"statement": "Given a grid of size n x m, each cell is good or bad."}}})
        strip = {"scenes": [{"layout": "trace", "cells": list("GGBGG")}] * 3}
        self.assertIn("a grid (rows and columns)", shapes.scene_problems(ctx, strip)[0])
        board = {"scenes": [{"layout": "grid"}, {"layout": "grid"}]}
        self.assertEqual(shapes.scene_problems(ctx, board), [])
        one_d = SimpleNamespace(outputs={"topic": {"topic": "Two Sum", "angle": "find two numbers in an array"}})
        self.assertEqual(shapes.scene_problems(one_d, strip), [])                  # an array drawn as a row is right


class ShapeTests(unittest.TestCase):
    def test_the_shape_is_named_from_the_words_when_no_reader(self):
        for text, want in (("Number of islands in a 2D grid", "grid"), ("Lowest common ancestor in a binary tree", "tree"),
                           ("Dijkstra shortest path", "graph"), ("Reverse a linked list", "linked_list"), ("Valid parentheses with a stack", "stack_queue"),
                           ("Merge overlapping intervals", "intervals"), ("Climbing stairs: how many ways", "ways"),
                           ("Longest palindromic substring", "string"), ("Two sum on a sorted array", "array"), ("CAP theorem", "other")):
            self.assertEqual(shapes.from_words(text), want, text)

    def test_a_shape_the_video_cannot_draw_stops_only_when_the_reader_named_it(self):
        self.assertIn("cannot draw a tree yet", shapes.stop_reason("tree", "reader"))
        self.assertEqual(shapes.stop_reason("tree", "words"), "")             # a guess from words never stops a run
        self.assertEqual(shapes.stop_reason("grid", "reader"), "")
        from postcrew.agents.topic import TopicAgent
        from postcrew.agents.base import AgentError
        ctx = SimpleNamespace(platform="youtube", category="assigned-short", cat={"media": "video", "label": "Short"},
                              run=SimpleNamespace(event=lambda *a, **k: None))
        e = {"topic": "Lowest common ancestor", "angle": "x", "owner_plan": {"title": "LCA", "shape": "tree", "statement": "..."}}
        with self.assertRaises(AgentError) as err:
            TopicAgent()._planned(ctx, e)
        self.assertTrue(err.exception.fatal)

    def test_the_video_works_the_problems_own_sample(self):
        st = {"examples": [{"input": "6 6\nBGBBGB\nGGGGGG\nBGBBGB\nGGGGGG\nBGBBGB\nBGBBGB", "output": "25"}]}
        ctx = SimpleNamespace(outputs={"topic": {"topic": "Two Pluses", "owner_plan": {"shape": "grid"}}})
        made_up = {"scenes": [{"layout": "grid", "grid": {"rows": ["GGG", "GGG", "GGG"]}}]}
        self.assertIn("BGBBGB / GGGGGG", shapes.example_problems(ctx, made_up, st)[0])
        real = {"scenes": [{"layout": "grid", "grid": {"rows": BOARD}}]}
        self.assertEqual(shapes.example_problems(ctx, real, st), [])
        arr = SimpleNamespace(outputs={"topic": {"topic": "Two Sum", "owner_plan": {"shape": "array"}}})
        st2 = {"examples": [{"input": "nums = [2,7,11,15], target = 9", "output": "[0,1]"}]}
        self.assertIn("['2', '7', '11', '15']", shapes.example_problems(arr, {"scenes": [{"layout": "trace", "cells": ["1", "2"]}]}, st2)[0])
        self.assertEqual(shapes.example_problems(arr, {"scenes": [{"layout": "trace", "cells": ["2", "7", "11", "15"]}]}, st2), [])

    def test_a_script_wrong_for_its_problem_goes_back_to_the_writer(self):
        from postcrew.agents.supervisor import Supervisor
        sup = Supervisor.__new__(Supervisor)
        sup.order = ["writer", "editor", "text_frames", "media", "quality"]
        d = sup._diagnose(SimpleNamespace(), "quality", ["REWRITE: grid drawn as a row"], {"rewrite": "grid drawn as a row"}, {})
        self.assertEqual((d["action"], d["target"]), ("rewind", "writer"))
        d = sup._diagnose(SimpleNamespace(), "quality", ["scenes redrawn"], {"redrawn": [3]}, {})
        self.assertEqual(d["target"], "text_frames")


class TimingAndColourTests(unittest.TestCase):
    """The Two Pluses rebuild: 'walk right' was timed at the 'Walk' of 'Walk left', so the four cells on the left never showed; and the
    voice said 'green cells are good, red cells are bad' over a board with no green or red."""

    def test_a_cue_is_found_where_its_words_are_said_together(self):
        from postcrew.render import timeline
        times = timeline.word_times("Walk left and you find four good cells. Walk right and the edge stops you after one.", 8)
        second_walk = [s for w, s, _ in times if w == "Walk"][1]
        self.assertEqual(timeline.cue_time("walk left", times), times[0][1])
        self.assertEqual(timeline.cue_time("walk right", times), second_walk)          # not the 'Walk' of 'Walk left'
        self.assertEqual(timeline.cue_time("edge", times), next(s for w, s, _ in times if w == "edge"))

    def test_steps_never_share_a_moment(self):
        p = gridviz.props(board_scene([step(say="walk", active=["1,1"]), step(say="walk", active=["1,2"]), step(say="walk", active=["1,3"])]),
                          lambda say, after: 0.0)
        self.assertEqual([s["t"] for s in p["steps"]], [0.0, 0.9, 1.8])

    def test_the_voice_names_only_colours_the_board_shows(self):
        v = board_scene([step(say="good and bad", out=["0,0"])])
        self.assertIn("green, red", gridviz.colour_problems(v, "Green cells are good, and red cells are bad.", 2)[0])
        coloured = dict(v, colors=["G=green", "B=red"])
        self.assertEqual(gridviz.colour_problems(coloured, "Green cells are good, and red cells are bad.", 2), [])
        self.assertEqual(gridviz.props(coloured, lambda s, a: 0.0)["colors"], {"G": "#22C55E", "B": "#EF4444"})
        two = board_scene([step(pluses=["1,1,1", "3,4,1"])])
        self.assertEqual(gridviz.colour_problems(two, "The blue plus and the orange plus.", 3), [])
        self.assertIn("grid.colors are", gridviz.problems(dict(v, colors=["G=greenish"]), 2)[0])


if __name__ == "__main__":
    unittest.main()


class ClosingCardTest(unittest.TestCase):
    def test_closing_is_drawn_with_icon_buttons(self):
        from postcrew.render import hyperframes
        self.assertEqual(hyperframes.engine_for({"layout": "statement", "part": "closing"}), "remotion")
        self.assertEqual(hyperframes.engine_for({"layout": "statement", "closing": True}), "remotion")
        self.assertEqual(hyperframes.engine_for({"layout": "statement"}), "hyperframes")

    def test_trailing_silence_is_not_a_sentence_pause(self):
        from unittest import mock
        from postcrew.render import timeline
        err = ("  Duration: 00:00:06.77, start: 0.000000, bitrate: 48 kb/s\n"
               "[silencedetect] silence_start: 1.68975\n[silencedetect] silence_end: 1.97383 | silence_duration: 0.28\n"
               "[silencedetect] silence_start: 3.23629\n[silencedetect] silence_end: 3.57358 | silence_duration: 0.33\n"
               "[silencedetect] silence_start: 6.42413\n[silencedetect] silence_end: 6.768 | silence_duration: 0.34\n")
        with mock.patch("shutil.which", return_value="/usr/bin/ffmpeg"), \
                mock.patch("subprocess.run", return_value=mock.Mock(stderr=err)):
            quiet = timeline._silences("v.mp3", "-35dB", 0.18)
        self.assertEqual(quiet[-1][1], float("inf"))
        n = "If this was useful, please like, comment and subscribe. And if you liked it, share it with someone who would find it helpful."
        words, ok = timeline.calibrate(timeline.word_times(n, 7.4), 7.4, quiet)
        self.assertTrue(ok)
        sub = next(s for w, s, _e in words if w.startswith("subscribe"))
        self.assertLess(sub, 3.3)   # said before the pause at 3.24 s, not stretched towards the end
