"""Comments: the first comment falls back to LinkedIn's older API, and the Replier answers new comments on recent posts."""
import io
import json
import unittest
import urllib.error
from datetime import datetime, timedelta, timezone

from postcrew import engage
from postcrew.linkedin import LinkedIn, LinkedInError
from postcrew.llm import LLMResult

from helpers import TempWorkspace

POST = "urn:li:ugcPost:1"
ME = "urn:li:person:abc123"


class Resp:
    def __init__(self, status=201, body=b"", headers=None):
        self.status, self.body, self.headers = status, body, headers or {}

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def opener_refusing_rest(calls):
    def opener(req, timeout=0):
        calls.append((req.get_method(), req.full_url, dict(req.header_items())))
        if "/rest/" in req.full_url:
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(
                b'{"code":"ACCESS_DENIED","message":"Not enough permissions to access: partnerApiSocialActions.CREATE.20260101"}'))
        return Resp(201, b"", {"x-restli-id": "urn:li:comment:(urn:li:ugcPost:1,9)"})
    return opener


class FirstCommentTests(unittest.TestCase):
    def test_a_refused_versioned_call_is_sent_to_the_older_api_without_a_version(self):
        calls = []
        li = LinkedIn("tok", opener=opener_refusing_rest(calls))
        urn = li.add_comment(ME, POST, "https://example.com/source")
        self.assertEqual(urn, "urn:li:comment:(urn:li:ugcPost:1,9)")
        self.assertEqual([c[1].split("/socialActions")[0] for c in calls], ["https://api.linkedin.com/rest", "https://api.linkedin.com/v2"])
        self.assertIn("Linkedin-version", calls[0][2])
        self.assertNotIn("Linkedin-version", calls[1][2])            # the older API takes no version header

    def test_a_reply_is_posted_under_its_comment(self):
        calls = []
        li = LinkedIn("tok", opener=opener_refusing_rest(calls))
        li.add_comment(ME, POST, "thanks", parent="urn:li:comment:(urn:li:ugcPost:1,5)")
        self.assertIn("urn%3Ali%3Acomment%3A%28urn%3Ali%3AugcPost%3A1%2C5%29/comments", calls[-1][1])

    def test_both_refusals_are_reported(self):
        def opener(req, timeout=0):
            raise urllib.error.HTTPError(req.full_url, 403, "Forbidden", {}, io.BytesIO(b'{"code":"ACCESS_DENIED"}'))
        with self.assertRaises(LinkedInError) as e:
            LinkedIn("tok", opener=opener).add_comment(ME, POST, "x")
        self.assertEqual(e.exception.status, 403)
        self.assertIn("versioned API said", str(e.exception))


class FakeLI:
    comments_by = {}
    sent = []
    deny = False

    def __init__(self, token, version="202601"):
        pass

    def person_urn(self):
        return ME

    def comments(self, urn, count=50):
        if FakeLI.deny:
            raise LinkedInError("HTTP 403 ACCESS_DENIED", 403)
        return FakeLI.comments_by.get(urn, [])

    def add_comment(self, owner, post_urn, text, parent=None):
        FakeLI.sent.append({"post": post_urn, "text": text, "parent": parent})
        return f"urn:li:comment:(sent,{len(FakeLI.sent)})"


class FakeLLM:
    def __init__(self):
        self.prompts = []

    def call(self, agent_id, system, prompt, schema, **kw):
        self.prompts.append((agent_id, system, prompt))
        out = []
        for line in prompt.splitlines():
            if line.startswith("{"):
                c = json.loads(line)
                spam = "crypto" in c["text"]
                out.append({"comment": c["comment"], "reply": "" if spam else f"Good point about {c['text'][:10]}", "skip": spam,
                            "why": "spam" if spam else "adds a point"})
        return LLMResult(data={"replies": out}, cost_usd=0, model="fake", turns=1)


def comment(n, text, actor="urn:li:person:other", replies=0):
    return {"urn": f"urn:li:comment:({POST},{n})", "id": str(n), "actor": actor, "text": text, "created": 1000 + n, "parent": None,
            "replies": replies}


class ReplierTests(unittest.TestCase):
    def setUp(self):
        FakeLI.comments_by, FakeLI.sent, FakeLI.deny = {}, [], False

    def ws_with_post(self, ws, days_ago=1, dry_run=False, mode="review"):
        cfg = ws.config()
        cfg["publishing"]["dry_run"] = dry_run
        cfg["engage"] = {**engage.DEFAULTS, "replies": mode}
        ws.save_config(cfg)
        ws.update_secrets(linkedin_access_token="tok", linkedin_person_urn=ME)
        when = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(timespec="seconds")
        ws.add_history({"id": "p1", "platform": "linkedin", "topic": "Quantization", "text": "Pick 4-bit for memory.", "urn": POST,
                        "first_comment": "https://example.com/src", "published_at": when, "date": when[:10]})

    def test_new_comments_get_draft_replies_and_spam_and_my_own_are_left_out(self):
        with TempWorkspace() as ws:
            self.ws_with_post(ws)
            FakeLI.comments_by[POST] = [comment(1, "What about 8-bit for accuracy?"), comment(2, "Earn crypto fast, DM me"),
                                        comment(3, "Thanks all!", actor=ME)]
            llm = FakeLLM()
            res = engage.check(ws, client_factory=FakeLI, llm=llm)
            self.assertEqual(res, {"new": 2, "sent": 0, "drafted": 1, "skipped": 1})
            rows = engage.load(ws)["comments"]
            self.assertEqual(rows[comment(1, "")["urn"]]["status"], "drafted")
            self.assertEqual(rows[comment(2, "")["urn"]]["status"], "skipped")
            self.assertNotIn(comment(3, "")["urn"], rows)                       # my own comment
            self.assertIn("Pick 4-bit for memory.", llm.prompts[0][2])         # the Replier reads the post
            self.assertEqual(FakeLI.sent, [])                                    # review: nothing sent until I send it
            self.assertEqual(engage.check(ws, client_factory=FakeLI, llm=llm)["new"], 0)   # seen once only
            self.assertEqual(len(llm.prompts), 1)

    def test_sending_a_changed_reply_posts_it_under_the_comment(self):
        with TempWorkspace() as ws:
            self.ws_with_post(ws)
            FakeLI.comments_by[POST] = [comment(1, "What about 8-bit?")]
            engage.check(ws, client_factory=FakeLI, llm=FakeLLM())
            urn = comment(1, "")["urn"]
            row = engage.send(ws, urn, "8-bit keeps more accuracy; 4-bit saves memory.", client_factory=FakeLI)
            self.assertEqual(row["status"], "sent")
            self.assertEqual(FakeLI.sent, [{"post": POST, "text": "8-bit keeps more accuracy; 4-bit saves memory.", "parent": urn}])
            engage.send(ws, urn, client_factory=FakeLI)
            self.assertEqual(len(FakeLI.sent), 1)                                # never twice

    def test_auto_sends_and_practice_mode_sends_nothing(self):
        with TempWorkspace() as ws:
            self.ws_with_post(ws, mode="auto")
            FakeLI.comments_by[POST] = [comment(1, "Nice breakdown")]
            self.assertEqual(engage.check(ws, client_factory=FakeLI, llm=FakeLLM())["sent"], 1)
            self.assertEqual(len(FakeLI.sent), 1)
        with TempWorkspace() as ws:
            self.ws_with_post(ws, mode="auto", dry_run=True)
            FakeLI.comments_by[POST] = [comment(1, "Nice breakdown")]
            FakeLI.sent = []
            engage.check(ws, client_factory=FakeLI, llm=FakeLLM())
            self.assertEqual(FakeLI.sent, [])
            self.assertEqual(engage.load(ws)["comments"][comment(1, "")["urn"]]["status"], "dry_run")

    def test_a_comment_i_already_answered_and_old_posts_are_left_alone(self):
        with TempWorkspace() as ws:
            self.ws_with_post(ws)
            c = comment(1, "Great post", replies=1)
            FakeLI.comments_by[POST] = [c]
            FakeLI.comments_by[c["urn"]] = [comment(5, "Thank you!", actor=ME)]
            engage.check(ws, client_factory=FakeLI, llm=FakeLLM())
            self.assertEqual(engage.load(ws)["comments"][c["urn"]]["status"], "answered")
        with TempWorkspace() as ws:
            self.ws_with_post(ws, days_ago=30)
            FakeLI.comments_by[POST] = [comment(1, "late comment")]
            self.assertEqual(engage.check(ws, client_factory=FakeLI, llm=FakeLLM())["new"], 0)

    def test_no_access_says_so_once_and_waits_a_day(self):
        with TempWorkspace() as ws:
            self.ws_with_post(ws)
            FakeLI.deny = True
            res = engage.check(ws, client_factory=FakeLI, llm=FakeLLM())
            self.assertIn("Community Management API", res["blocked"])
            self.assertFalse(engage.load(ws)["access"]["ok"])
            FakeLI.deny = False
            FakeLI.comments_by[POST] = [comment(1, "hi")]
            self.assertIn("blocked", engage.check(ws, client_factory=FakeLI, llm=FakeLLM()))            # within the day
            later = datetime.now(timezone.utc) + timedelta(hours=25)
            self.assertEqual(engage.check(ws, client_factory=FakeLI, llm=FakeLLM(), at=later)["drafted"], 1)
            self.assertTrue(engage.load(ws)["access"]["ok"])

    def test_the_schedule_checks_only_when_linkedin_is_connected_and_replies_are_on(self):
        with TempWorkspace() as ws:
            self.assertFalse(engage.due(ws))
            self.ws_with_post(ws)
            self.assertTrue(engage.due(ws))
            engage.check(ws, client_factory=FakeLI, llm=FakeLLM())
            self.assertFalse(engage.due(ws))                                     # checked a moment ago
            cfg = ws.config()
            cfg["engage"]["replies"] = "off"
            ws.save_config(cfg)
            self.assertFalse(engage.due(ws, datetime.now(timezone.utc) + timedelta(hours=2)))


if __name__ == "__main__":
    unittest.main()
