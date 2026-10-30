"""The daily clean-up: it deletes what is old, and never the settings, the history, the queue's files or anything a queued post uses."""
import json
import os
import sys
import time
import unittest
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).parent))
from helpers import TempWorkspace  # noqa: E402

from postcrew import cleanup, scheduler  # noqa: E402

DAY = 86400


def make(path, days_old, size=100):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"x" * size)
    t = time.time() - days_old * DAY
    os.utime(path, (t, t))
    return path


class CleanupTests(unittest.TestCase):
    def test_what_is_older_than_thirty_days_goes_and_the_rest_stays(self):
        with TempWorkspace() as ws:
            r = ws.root
            make(r / "runs" / "old-run" / "video.mp4", 40)
            make(r / "runs" / "old-run" / "frames" / "f1.png", 40)
            make(r / "runs" / "new-run" / "video.mp4", 5)
            make(r / "media" / "old.mp4", 45)
            make(r / "media" / "new.mp4", 3)
            make(r / "cache" / "voice" / "old.mp3", 31)
            make(r / "cache" / "voice" / "new.mp3", 1)
            make(r / "config.backup-before-x.json", 60)
            res = cleanup.clean(ws, 30)
            self.assertFalse((r / "runs" / "old-run").exists())
            self.assertFalse((r / "media" / "old.mp4").exists())
            self.assertFalse((r / "cache" / "voice" / "old.mp3").exists())
            self.assertFalse((r / "config.backup-before-x.json").exists())
            for kept in ("runs/new-run/video.mp4", "media/new.mp4", "cache/voice/new.mp3"):
                self.assertTrue((r / kept).exists(), kept)
            self.assertEqual(res["areas"], {"runs": 1, "media": 1, "cache": 1, "backups": 1})
            self.assertEqual(ws.state("cleanup")["removed"], 4)

    def test_settings_history_queue_and_state_are_never_touched_whatever_their_age(self):
        with TempWorkspace() as ws:
            r = ws.root
            ws.add_history({"id": "p1", "date": "2020-01-01", "topic": "Old topic"})
            for f in ("config.json", "secrets.json", "history.json", "queue.json", "studio-token"):
                make(r / f, 400) if not (r / f).exists() else os.utime(r / f, (time.time() - 400 * DAY,) * 2)
            make(r / "state" / "plan.json", 400)
            cleanup.clean(ws, 1, videos=True)
            for f in ("config.json", "secrets.json", "history.json", "queue.json", "studio-token", "state/plan.json"):
                self.assertTrue((r / f).exists(), f)
            self.assertEqual(ws.history()[0]["topic"], "Old topic")

    def test_a_post_still_in_the_queue_keeps_its_video_picture_and_run(self):
        with TempWorkspace() as ws:
            r = ws.root
            video, poster = make(r / "media" / "q.mp4", 90), make(r / "media" / "q.png", 90)
            make(r / "runs" / "queued-run" / "video.mp4", 90)
            make(r / "runs" / "queued-run" / "status.json", 90)
            make(r / "media" / "other.mp4", 90)
            ws.save_queue([{"id": "q", "status": "awaiting_approval", "media": "media/q.mp4", "poster_image": "media/q.png", "run_id": "queued-run"}])
            cleanup.clean(ws, 30, videos=True)
            self.assertTrue(video.exists() and poster.exists())
            self.assertTrue((r / "runs" / "queued-run" / "video.mp4").exists())
            self.assertFalse((r / "media" / "other.mp4").exists())

    def test_videos_mode_clears_finished_videos_frames_and_demo_folders_at_any_age(self):
        with TempWorkspace() as ws:
            r = ws.root
            make(r / "media" / "2026.mp4", 1)
            make(r / "media" / "2026.png", 1)                       # a picture is not a video
            make(r / "runs" / "run1" / "frames" / "a.png", 1)
            make(r / "runs" / "run1" / "voice" / "s0.wav", 1)
            make(r / "runs" / "run1" / "events.jsonl", 1)           # the log stays: the Workflow view lists runs
            make(r / "demo-explainer" / "demo.mp4", 1)
            make(r / "two-sum.mp4", 1)
            make(r / "cache" / "voice" / "abc.mp3", 1)              # the voice cache saves money: only age removes it
            res = cleanup.clean(ws, 30, videos=True)
            for gone in ("media/2026.mp4", "runs/run1/frames", "runs/run1/voice/s0.wav", "demo-explainer", "two-sum.mp4"):
                self.assertFalse((r / gone).exists(), gone)
            for kept in ("media/2026.png", "runs/run1/events.jsonl", "cache/voice/abc.mp3"):
                self.assertTrue((r / kept).exists(), kept)
            self.assertGreater(res["removed"], 4)

    def test_a_dry_run_deletes_nothing_and_says_what_would_go(self):
        with TempWorkspace() as ws:
            f = make(ws.root / "media" / "old.mp4", 99, size=2_000_000)
            res = cleanup.clean(ws, 30, dry_run=True)
            self.assertTrue(f.exists())
            self.assertEqual((res["removed"], res["freed_mb"]), (1, 2.0))
            self.assertEqual(res["examples"], ["media/old.mp4"])
            self.assertEqual(ws.state("cleanup", {}), {})   # a dry run leaves no record

    def test_a_link_out_of_the_workspace_is_removed_but_never_followed(self):
        import tempfile
        with TempWorkspace() as ws, tempfile.TemporaryDirectory() as outside:
            target = make(Path(outside) / "precious.mp4", 99)
            link = ws.root / "media" / "link.mp4"
            link.parent.mkdir(exist_ok=True)
            link.symlink_to(target)
            os.utime(link, (time.time() - 99 * DAY,) * 2, follow_symlinks=False)
            cleanup.clean(ws, 30)
            self.assertTrue(target.exists())

    def test_the_scheduler_cleans_once_a_day_after_the_set_time(self):
        with TempWorkspace() as ws:
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            calls = []
            kw = dict(runner=lambda *a, **k: None, publisher=lambda *a, **k: [], checker=lambda *a, **k: None, planner=lambda *a, **k: None,
                      cleaner=lambda w: calls.append(1))
            scheduler.tick(ws, datetime(2026, 11, 3, 3, 0, tzinfo=tz), **kw)     # before 03:30
            self.assertEqual(calls, [])
            self.assertIn("clean up", scheduler.tick(ws, datetime(2026, 11, 3, 3, 31, tzinfo=tz), **kw))
            scheduler.tick(ws, datetime(2026, 11, 3, 9, 0, tzinfo=tz), **kw)     # not again the same day
            self.assertEqual(len(calls), 1)
            scheduler.tick(ws, datetime(2026, 11, 4, 3, 31, tzinfo=tz), **kw)
            self.assertEqual(len(calls), 2)

    def test_it_can_be_switched_off_and_its_settings_are_checked(self):
        from postcrew.workspace import validate_config
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["cleanup"] = {"enabled": False, "keep_days": 30, "time": "03:30"}
            ws.save_config(cfg)
            f = make(ws.root / "media" / "old.mp4", 99)
            self.assertIsNone(cleanup.run_cleanup(ws))
            self.assertTrue(f.exists())
            cfg["cleanup"] = {"enabled": True, "keep_days": 0, "time": "25:00"}
            self.assertEqual(len(validate_config(cfg)), 2)


if __name__ == "__main__":
    unittest.main()
