"""Apps (platforms): each has its own schedule, plan, topics and posts."""
import copy
import unittest
from datetime import date, datetime
from unittest import mock
from zoneinfo import ZoneInfo

from helpers import (TUESDAY, ScriptedLLM, TempWorkspace, fake_fetch, poster_spec, research, review, topic, writer)
from postcrew import platforms, scheduler
from postcrew.agents import credentials as cred_mod
from postcrew.agents import planner as planner_mod
from postcrew.agents.publisher import publish_due
from postcrew.crew import post_for, run_crew
from postcrew.workspace import validate_config

CLAUDE_OK = {"state": "ok", "message": "logged in"}


def with_youtube(ws, **schedule):
    """Switch YouTube on with the dev-tip category (the real video categories arrive with the YouTube crew)."""
    cfg = ws.config()
    yt = cfg["platforms"]["youtube"]
    yt["enabled"] = True
    yt["categories"] = {"dev-tip": copy.deepcopy(cfg["categories"]["dev-tip"])}
    yt["schedule"].update(days={"tue": "dev-tip"}, post_time="17:00", **schedule)
    ws.save_config(cfg)
    return ws.config()


class ScheduleTests(unittest.TestCase):
    base = {"post_time": "08:30", "days": {"mon": "a", "wed": "b"}}

    def test_weekly_uses_the_days_and_per_weekday_times(self):
        s = dict(self.base, day_times={"wed": "10:15"})
        self.assertEqual(platforms.slot(s, date(2026, 10, 12)), {"category": "a", "time": "08:30"})   # Monday
        self.assertEqual(platforms.slot(s, date(2026, 10, 14)), {"category": "b", "time": "10:15"})   # Wednesday
        self.assertIsNone(platforms.slot(s, date(2026, 10, 13)))                                      # Tuesday

    def test_every_n_days_cycles_the_rotation_from_the_start_date(self):
        s = dict(self.base, frequency="every_n_days", every_n=3, start_date="2026-10-12", rotation=["x", "y"])
        got = [(d.isoformat(), v["category"]) for d, v in platforms.upcoming(s, date(2026, 10, 11), 14)]
        self.assertEqual(got, [("2026-10-12", "x"), ("2026-10-15", "y"), ("2026-10-18", "x"), ("2026-10-21", "y"),
                               ("2026-10-24", "x")])

    def test_dates_mode_and_one_off_dates_with_their_own_time(self):
        s = dict(self.base, frequency="dates", dates=[{"date": "2026-11-03", "category": "b", "time": "21:00"}])
        self.assertEqual(platforms.slot(s, "2026-11-03"), {"category": "b", "time": "21:00"})
        self.assertIsNone(platforms.slot(s, "2026-10-12"))                       # weekly days do not apply here
        extra = dict(self.base, dates=[{"date": "2026-10-13"}])                  # a one-off Tuesday in weekly mode
        self.assertEqual(platforms.slot(extra, "2026-10-13"), {"category": "a", "time": "08:30"})
        self.assertEqual(platforms.slot(extra, "2026-10-12")["category"], "a")   # the usual days still apply


class ConfigTests(unittest.TestCase):
    def test_default_config_is_valid_and_youtube_starts_off(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            self.assertEqual(validate_config(cfg), [])
            self.assertEqual(platforms.enabled(cfg), ["linkedin"])

    def test_old_configs_without_platforms_still_load(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg.pop("platforms")
            (ws.root / "config.json").write_text(__import__("json").dumps(cfg))
            self.assertEqual(platforms.enabled(ws.config()), ["linkedin"])

    def test_an_enabled_app_is_validated_on_its_own_and_a_disabled_one_is_not(self):
        with TempWorkspace() as ws:
            cfg = ws.config()
            cfg["platforms"]["youtube"]["schedule"]["post_time"] = "25:00"
            self.assertEqual(validate_config(cfg), [])
            cfg["platforms"]["youtube"]["enabled"] = True
            errs = validate_config(cfg)
            self.assertTrue(any("platforms.youtube.schedule.post_time" in e for e in errs), errs)
            cfg["platforms"]["youtube"]["schedule"].update(post_time="17:00", days={})
            self.assertTrue(any("platforms.youtube.schedule.days" in e for e in validate_config(cfg)))

    def test_schedule_options_are_checked(self):
        with TempWorkspace() as ws:
            cfg = with_youtube(ws)
            yt = cfg["platforms"]["youtube"]["schedule"]
            yt.update(frequency="every_n_days", every_n=0, start_date="soon", dates=[{"date": "nope"}],
                      day_times={"funday": "9"})
            errs = " | ".join(validate_config(cfg))
            for frag in ("every_n", "start_date", "needs a date", "day_times"):
                self.assertIn(frag, errs)

    def test_view_gives_an_app_its_own_sections(self):
        with TempWorkspace() as ws:
            cfg = with_youtube(ws)
            v = platforms.view(cfg, "youtube")
            self.assertIn("dev-tip", v["categories"])
            self.assertIn("short-tip", v["categories"])
            self.assertEqual(v["schedule"]["post_time"], "17:00")
            self.assertEqual(v["profile"], cfg["profile"])
            self.assertIs(platforms.view(cfg, "linkedin"), cfg)


@mock.patch.object(cred_mod, "check_claude", return_value=CLAUDE_OK)
class CrewPerAppTests(unittest.TestCase):
    def test_posts_are_kept_per_app(self, _):
        with TempWorkspace() as ws:
            ws.save_queue([{"id": "a", "platform": "youtube", "date": str(TUESDAY), "status": "queued", "topic": "t"}])
            self.assertIsNotNone(post_for(ws, TUESDAY, "youtube"))
            self.assertIsNone(post_for(ws, TUESDAY, "linkedin"))     # the same date is still open on LinkedIn
            self.assertEqual(ws.recent_posts(10, "linkedin"), [])

    def test_linkedin_publishing_leaves_other_apps_to_their_own_client(self, _):
        with TempWorkspace() as ws:
            cfg = with_youtube(ws)
            ws.save_queue([{"id": "a", "platform": "youtube", "date": str(TUESDAY), "status": "queued", "topic": "t",
                            "scheduled_at": "2026-10-13T22:00:00+00:00", "text": "d", "media": None,
                            "youtube": {"title": "t", "format": "short", "seconds": 40, "description": "d", "tags": []}}])
            res = publish_due(ws, now=datetime.fromisoformat("2030-01-01T00:00:00+00:00"), log=lambda m: None)
            self.assertEqual([r["status"] for r in res], ["dry_run"])    # YouTube's practice mode, not LinkedIn's client

    def test_unknown_app_is_refused(self, _):
        with TempWorkspace() as ws:
            self.assertFalse(run_crew(ws, TUESDAY, "dev-tip", platform="myspace")["ok"])


class PlannerPerAppTests(unittest.TestCase):
    def test_each_app_keeps_its_own_plan(self):
        with TempWorkspace() as ws:
            planner_mod.set_entry(ws, "2026-10-13", {"category": "dev-tip", "topic": "On YouTube"}, "youtube")
            planner_mod.set_entry(ws, "2026-10-13", {"category": "dev-tip", "topic": "On LinkedIn"})
            self.assertEqual(planner_mod.load_plan(ws)["2026-10-13"]["topic"], "On LinkedIn")
            self.assertEqual(planner_mod.load_plan(ws, "youtube")["2026-10-13"]["topic"], "On YouTube")
            self.assertEqual(planner_mod.planned_for(ws, "2026-10-13", "dev-tip", "youtube")["topic"], "On YouTube")


class SchedulerPerAppTests(unittest.TestCase):
    def test_each_enabled_app_generates_on_its_own_schedule(self):
        with TempWorkspace() as ws:
            with_youtube(ws, generate_time="20:00", lead_days=1)
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            calls = []
            kw = dict(runner=lambda ws_, d, platform="linkedin": calls.append((platform, d.isoformat())),
                      publisher=lambda ws_: [], checker=lambda ws_: None,
                      planner=lambda ws_, d, platform="linkedin": calls.append(("plan", platform)))
            scheduler.tick(ws, datetime(2026, 10, 12, 19, 5, tzinfo=tz), **kw)    # Monday evening
            self.assertIn(("linkedin", "2026-10-13"), calls)
            self.assertNotIn(("youtube", "2026-10-13"), calls)                    # YouTube generates at 20:00
            scheduler.tick(ws, datetime(2026, 10, 12, 20, 5, tzinfo=tz), **kw)
            self.assertIn(("youtube", "2026-10-13"), calls)
            scheduler.tick(ws, datetime(2026, 10, 12, 20, 6, tzinfo=tz), **kw)
            self.assertEqual(calls.count(("youtube", "2026-10-13")), 1)

    def test_a_switched_off_app_is_never_scheduled(self):
        with TempWorkspace() as ws:
            tz = ZoneInfo(ws.config()["schedule"]["timezone"])
            calls = []
            scheduler.tick(ws, datetime(2026, 10, 12, 20, 5, tzinfo=tz),
                           runner=lambda ws_, d, platform="linkedin": calls.append(platform), publisher=lambda ws_: [],
                           checker=lambda ws_: None, planner=lambda *a, **k: None)
            self.assertEqual(calls, ["linkedin"])


if __name__ == "__main__":
    unittest.main()


class StudioPerAppTests(unittest.TestCase):
    def studio(self, ws):
        from postcrew.studio.server import Studio
        return Studio(ws)

    def test_overview_and_plan_follow_the_chosen_app(self):
        with TempWorkspace() as ws:
            with_youtube(ws, frequency="every_n_days", every_n=2, start_date="2026-10-01", rotation=["dev-tip"])
            st = self.studio(ws)
            o = st.overview("youtube")
            self.assertEqual(o["platform"], "youtube")
            self.assertEqual([a["id"] for a in o["platforms"] if a["enabled"]], ["linkedin", "youtube"])
            self.assertTrue(o["upcoming"] and all(u["category"] == "dev-tip" for u in o["upcoming"]))
            self.assertEqual(st.overview()["platform"], "linkedin")
            self.assertEqual(st.plan("youtube")["platform"], "youtube")
            with self.assertRaises(ValueError):
                st.overview("myspace")

    def test_plan_edits_land_in_the_chosen_apps_plan(self):
        from postcrew.crew import local_now
        with TempWorkspace() as ws:
            with_youtube(ws, frequency="every_n_days", every_n=1, start_date="2026-01-01", rotation=["dev-tip"])
            st = self.studio(ws)
            day = next(r for r in st.plan("youtube")["days"] if not r["past"])["date"]
            st.plan_save({"days": {day: {"topic": "Why hash maps are fast", "angle": "buckets"}}, "platform": "youtube"})
            self.assertEqual(planner_mod.load_plan(ws, "youtube")[day]["topic"], "Why hash maps are fast")
            self.assertEqual(planner_mod.load_plan(ws), {})
