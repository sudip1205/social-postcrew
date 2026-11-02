"""Research agent: finds primary sources for the topic and copies verbatim quotes the writer may rely on.

Three phases, so a quote can only come from text the verifier will see:
  1. search   the model uses WebSearch to choose up to 5 primary pages
  2. fetch    this program downloads those pages itself (not the model's summarizing WebFetch)
  3. extract  the model copies quotes from the downloaded text; no tools, nothing else to quote from
Validation then checks every quote is really in the page and every fact is backed by one.

A team of researchers (Settings > team.research) does this independently and in parallel, each in their own
style. Their verified sources and backed facts are combined; anything unverified is left out. Each member's
result is recorded on the roster (see team.py).
"""
import re
from concurrent.futures import ThreadPoolExecutor

from ..checks import STALE, norm, source_problems, verify_sources
from ..render import tracers
from . import team
from .base import Agent, AgentError, guidance_block

PAGE_CHARS = 14000

SEARCH_SCHEMA = {
    "type": "object",
    "properties": {
        "candidates": {"type": "array", "minItems": 1, "maxItems": 5, "items": {
            "type": "object",
            "properties": {"url": {"type": "string"}, "title": {"type": "string"},
                           "why": {"type": "string", "description": "what this page proves"}},
            "required": ["url", "title", "why"], "additionalProperties": False}},
        "notes": {"type": "string"},
    },
    "required": ["candidates", "notes"],
    "additionalProperties": False,
}

TRENDING_SCHEMA = {
    "type": "object",
    "properties": {
        "videos": {"type": "array", "maxItems": 6, "items": {
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "opening": {"type": "string", "description": "how it starts: the hook or the question it opens with"},
                "structure": {"type": "array", "items": {"type": "string"}, "maxItems": 8, "description": "its parts in order, from the chapters and description"},
                "covers": {"type": "array", "items": {"type": "string"}, "maxItems": 8},
                "works": {"type": "string", "description": "why viewers likely watch and like it"},
                "weak": {"type": "string", "description": "what it explains badly or leaves out"},
            },
            "required": ["id", "opening", "structure", "covers", "works", "weak"], "additionalProperties": False}},
        "common_topics": {"type": "array", "items": {"type": "string"}, "maxItems": 10, "description": "what almost every trending video covers: viewers expect it"},
        "gaps": {"type": "array", "items": {"type": "string"}, "maxItems": 6, "description": "what they miss or do badly: where this video can be better"},
        "outline": {"type": "array", "items": {"type": "string"}, "maxItems": 10, "description": "a suggested order of parts for OUR video, teaching students"},
        "title_patterns": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["videos", "common_topics", "gaps", "outline", "title_patterns"],
    "additionalProperties": False,
}

EXTRACT_SCHEMA = {
    "type": "object",
    "properties": {
        "sources": {"type": "array", "maxItems": 5, "items": {
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "title": {"type": "string"},
                "published": {"type": "string", "description": "YYYY-MM-DD if the page text shows it, else empty"},
                "excerpts": {"type": "array", "items": {"type": "string"}, "minItems": 1, "maxItems": 6,
                             "description": "20-300 chars each, copied character-for-character from the PAGE text"},
            },
            "required": ["url", "title", "published", "excerpts"], "additionalProperties": False}},
        "facts": {"type": "array", "items": {
            "type": "object",
            "properties": {"claim": {"type": "string"}, "source_url": {"type": "string"},
                           "quote": {"type": "string", "description": "one of that source's excerpts, exactly"}},
            "required": ["claim", "source_url", "quote"], "additionalProperties": False}},
        "notes": {"type": "string", "description": "caveats, what could not be verified"},
    },
    "required": ["sources", "facts", "notes"],
    "additionalProperties": False,
}


def page_text(raw):
    return re.sub(r"\s+", " ", raw or "").strip()


class ResearchAgent(Agent):
    id = "research"
    title = "Researcher"
    name = "Research team"
    role = "Chooses primary sources, downloads them itself, and quotes them verbatim; every quote is re-checked."

    def applies(self, ctx):
        return ctx.cat.get("research", "optional") != "off" or ctx.cat["media"] == "animation"

    def run(self, ctx, guidance):
        out = self._sources(ctx, guidance)
        if getattr(ctx, "platform", "linkedin") != "linkedin":   # a video: also study the videos that are already working on this topic
            try:
                trending = self._trending(ctx, ctx.outputs["topic"])
            except AgentError as e:
                if e.fatal:
                    raise
                ctx.run.event(self.id, "trending", f"the trending videos could not be studied: {str(e)[:160]}", level="warning")
                trending = None
            if trending:
                out = dict(out, trending=trending)
        return out

    def _trending(self, ctx, topic):
        """How the videos that are working right now on this topic are built: what they cover, how they open and end, what they miss. The numbers
        come from YouTube (trends.py), the analysis from one model call over their titles, descriptions, chapters and tags. {} when YouTube says nothing."""
        from .. import trends
        from .planner import load_plan
        entry = load_plan(ctx.ws, ctx.platform).get(ctx.day.isoformat()) or {}
        known = {v["id"]: v for v in (entry.get("research") or {}).get("videos", []) if v.get("id")}
        fresh = trends.niche_research(topic["topic"], max_videos=8, log=None)
        by = {v["id"]: v for v in fresh["videos"]}
        for vid, v in known.items():   # the videos that made this a plan, even if a new search no longer lists them
            by.setdefault(vid, dict(v, description="", tags=v.get("tags") or []))
        videos = sorted(by.values(), key=lambda v: -(v.get("views_per_day") or 0))[:6]
        if not videos:
            ctx.run.event(self.id, "trending", fresh.get("error") or "no trending videos found for this topic", level="warning")
            return {}
        rows = []
        for v in videos:
            rows.append(f"VIDEO {v['id']}: {v['title']} ({v.get('channel', '')}); {v['views']:,} views, "
                        + (f"{v['likes']:,} likes ({v['engagement_pct']}%), " if v.get("likes") is not None else "")
                        + f"{v.get('age_days', '?')} days old, {'a Short' if v.get('short') else 'long'}\n"
                        + (("  chapters: " + "; ".join(f"{c['at'] // 60}:{c['at'] % 60:02d} {c['title']}" for c in v["chapters"][:14]) + "\n") if v.get("chapters") else "")
                        + (f"  tags: {', '.join(v['tags'][:10])}\n" if v.get("tags") else "")
                        + (f"  description: {(v.get('description') or '')[:700]}\n" if v.get("description") else ""))
        prompt = (f"Topic: {topic['topic']}\nAngle: {topic.get('angle', '')}\nFormat: {ctx.video.get('format', 'short')} video, for students\n\n"
                  "THE VIDEOS THAT ARE WORKING NOW (read from YouTube today):\n" + "\n".join(rows))
        analysis = self.ask(ctx, self.prompt(ctx, "research_trending"), prompt, TRENDING_SCHEMA)
        ids = {v["id"] for v in videos}
        analysis["videos"] = [dict(a, **{k: next((v.get(k) for v in videos if v["id"] == a["id"]), None) for k in ("url", "views", "likes", "engagement_pct", "views_per_day")})
                              for a in analysis.get("videos", []) if a.get("id") in ids]
        analysis["metrics"] = trends.metrics(videos)
        ctx.run.event(self.id, "trending", f"studied {len(videos)} trending video(s): {len(analysis.get('common_topics', []))} common topics, "
                                           f"{len(analysis.get('gaps', []))} gap(s) to fill", {"videos": [v["id"] for v in videos]})
        return analysis

    def _sources(self, ctx, guidance):
        topic = ctx.outputs["topic"]
        if topic.get("algo"):  # trusted, built-in reference facts: no web needed
            return {"sources": [], "facts": [], "notes": "", "reference": tracers.TRACERS[topic["algo"]].facts()}
        members = team.active(ctx.ws, "research", ctx.cfg["team"]["research"])
        with ThreadPoolExecutor(max_workers=len(members)) as pool:
            results = list(pool.map(lambda m: self._member_run(ctx, guidance, m), members))
        fatal = next((r for r in results if isinstance(r, AgentError) and r.fatal), None)
        if fatal:
            raise fatal
        cands = []
        for m, r in zip(members, results):
            if isinstance(r, Exception):
                problems, r = [str(r)], None
            else:
                problems = self.validate(ctx, r)
            cands.append((m, r, problems))
            mine = [p for p in problems if not p.startswith(STALE)]   # a stale topic is not the researcher's fault
            team.record(ctx.ws, m["id"], ctx.run.status["run_id"], good=not mine, problems=mine)
            ctx.run.event(self.id, "member", f"{m['name']}: " + (f"{len(problems)} problem(s): {problems[0][:120]}"
                                                                 if problems else self.summary(r)),
                          {"member": m["id"], "problems": problems}, level="warning" if problems else "info")
        out = self.combine(cands)
        out["team"] = [{"member": m["id"], "name": m["name"], "problems": p[:4],
                        "verified": sum(1 for s in (r or {}).get("verified", []) if s["verified"]),
                        "facts": len((r or {}).get("facts", []))} for m, r, p in cands]
        return out

    def combine(self, cands):
        """Every verified source and every quote-backed fact from all members; if nobody has anything verified,
        the member with the fewest problems (so validation reports their problems to the supervisor)."""
        good = [(m, r) for m, r, _ in cands if r and any(s["verified"] for s in r.get("verified", []))]
        if not good:
            done = [(len(p), r) for _, r, p in cands if r]
            if not done:
                raise AgentError("; ".join(p[0] for _, _, p in cands)[:500])
            best = min(done, key=lambda x: x[0])[1]
            return {k: v for k, v in best.items() if k not in ("verified", "_pages")}
        sources, facts, notes, errors = {}, [], [], []
        for m, r in good:
            ok = {s["url"]: s for s in r["verified"] if s["verified"]}
            for s in r.get("sources", []):
                if s.get("url") not in ok:
                    continue
                have = sources.setdefault(s["url"], dict(s, excerpts=[]))
                found = {norm(e) for e in ok[s["url"]]["found"]}
                have["excerpts"] += [e for e in s.get("excerpts", []) if norm(e) in found and e not in have["excerpts"]]
                if not have.get("published") and s.get("published"):
                    have["published"] = s["published"]
            backed = {u: {norm(e) for e in s["found"]} for u, s in ok.items()}
            facts += [f for f in r.get("facts", []) if norm(f.get("quote", "")) in backed.get(f.get("source_url"), ())
                      and f["claim"] not in {x["claim"] for x in facts}]
            if r.get("notes"):
                notes.append(f"{m['name']}: {r['notes']}")
            errors += r.get("download_errors", [])
        for s in sources.values():
            s["excerpts"] = s["excerpts"][:8]
        return {"sources": list(sources.values())[:8], "facts": facts, "notes": " | ".join(notes)[:1500],
                "download_errors": errors}

    def _member_run(self, ctx, guidance, member):
        try:
            return self._research(ctx, guidance, member)
        except AgentError as e:
            return e
        except Exception as e:  # keep the other members' work
            return AgentError(f"{type(e).__name__}: {e}")

    def _research(self, ctx, guidance, member):
        topic = ctx.outputs["topic"]
        style = team.persona_block(ctx.ws, member)
        from .. import brief as briefmod
        ob = briefmod.of(ctx)
        refs = briefmod.reference_urls(ob)
        brief = (f"Topic: {topic['topic']}\nAngle: {topic['angle']}\nWhy now: {topic['why_now']}\n"
                 f"Post date: {ctx.day.isoformat()}\nCategory: {ctx.cat['label']} - {ctx.cat['brief']}\n"
                 + (briefmod.cat_context(ctx.cat) + "\n" if briefmod.cat_context(ctx.cat) else "") +
                 f"Research is {ctx.cat.get('research')} for this category."
                 + (f" Sources must be published within {ctx.cat['max_source_age_days']} days of the post date."
                    if ctx.cat.get("max_source_age_days") else "")
                 + (f"\nThe owner supplied these reference pages (read them first): {', '.join(refs)}" if refs else "")
                 + ("\nThe post's example is a REAL, PUBLIC incident: find the primary sources (the company's or "
                    "regulator's own write-up) and quote what they actually state." if ob.get("example_kind") == "incident"
                    and ob.get("example") else ""))
        # 1. search
        found = self.ask(ctx, self.prompt(ctx, "research") + style, brief + "\nSuggested queries:\n" +
                         "\n".join(f"- {q}" for q in topic.get("search_queries", [])) + guidance_block(guidance),
                         SEARCH_SCHEMA, tools=["WebSearch"], member=member)
        for u in reversed(refs):   # the owner's own references are always fetched
            if not any((c.get("url") or "").strip() == u for c in found["candidates"]):
                found["candidates"].insert(0, {"url": u, "title": "owner reference"})
        # 2. fetch, ourselves
        pages, failed = {}, []
        for c in found["candidates"][:5]:
            url = (c.get("url") or "").strip()
            if not url.startswith("https://"):
                failed.append(f"{url}: not https")
                continue
            try:
                text = page_text(ctx.fetch(url))
            except Exception as e:
                failed.append(f"{url}: could not download ({str(e)[:80]})")
                continue
            if len(text) < 200:
                failed.append(f"{url}: almost no readable text (page needs JavaScript?)")
                continue
            pages[url] = text
        ctx.run.event(self.id, "fetched", f"{member['name']}: downloaded {len(pages)} of "
                                          f"{len(found['candidates'])} pages", {"downloaded": list(pages), "failed": failed})
        if not pages:
            return {"sources": [], "facts": [], "notes": "no page could be downloaded: " + "; ".join(failed),
                    "candidates": found["candidates"], "download_errors": failed}
        # 3. extract quotes from exactly what we downloaded
        material = "\n\n".join(f"<page url=\"{u}\">\n{t[:PAGE_CHARS]}\n</page>" for u, t in pages.items())
        out = self.ask(ctx, self.prompt(ctx, "research_extract") + style,
                       brief + "\n\nPAGES (downloaded by the program; quote ONLY from these):\n" + material
                       + guidance_block(guidance), EXTRACT_SCHEMA, member=member)
        out["candidates"], out["download_errors"] = found["candidates"], failed
        ctx.page_cache.update(pages)
        return out

    def validate(self, ctx, out):
        if out.get("reference"):
            return []
        cache = ctx.page_cache

        def fetch(url):
            return cache[url] if url in cache else ctx.fetch(url)
        verified = verify_sources(out.get("sources", []), fetch)
        out["verified"] = [{k: v for k, v in s.items() if k != "page"} for s in verified]
        out["_pages"] = {s["url"]: s["page"] for s in verified if s["verified"]}
        mode = ctx.cat.get("research", "optional")
        problems = source_problems(verified, mode, ctx.cat.get("max_source_age_days"), ctx.day)
        if mode == "required":
            problems += [f"{s['url']}: {s['error']}" for s in verified if s.get("error")]
            if out.get("download_errors") and not verified:
                problems.append("pick pages that can be downloaded as plain HTML: " + "; ".join(out["download_errors"]))
        good = {s["url"]: {norm(e) for e in s["found"]} for s in verified if s["verified"]}
        bad = [f["claim"][:80] for f in out.get("facts", [])
               if f.get("source_url") not in good or norm(f.get("quote", "")) not in good[f["source_url"]]]
        if bad:
            problems.append(f"{len(bad)} fact(s) are not backed by a verified quote, e.g. {bad[0]!r}. "
                            f"Each fact's quote must be one of that source's excerpts, copied exactly")
        return list(dict.fromkeys(problems))

    def summary(self, out):
        if out.get("reference"):
            return "built-in algorithm facts"
        v = out.get("verified", [])
        who = f" from {len(out['team'])} researchers" if len(out.get("team", [])) > 1 else ""
        return f"{sum(1 for s in v if s['verified'])}/{len(v)} sources verified, {len(out.get('facts', []))} facts{who}"
