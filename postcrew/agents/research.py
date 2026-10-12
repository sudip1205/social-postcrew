"""Research agent: finds primary sources for the topic and copies verbatim quotes the writer may rely on.

Three phases, so a quote can only come from text the verifier will see:
  1. search   the model uses WebSearch to choose up to 5 primary pages
  2. fetch    this program downloads those pages itself (not the model's summarizing WebFetch)
  3. extract  the model copies quotes from the downloaded text; no tools, nothing else to quote from
Validation then checks every quote is really in the page and every fact is backed by one.
"""
import re

from ..checks import norm, source_problems, verify_sources
from ..render import tracers
from .base import Agent, guidance_block

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
    role = "Chooses primary sources, downloads them itself, and quotes them verbatim; every quote is re-checked."

    def applies(self, ctx):
        return ctx.cat.get("research", "optional") != "off" or ctx.cat["media"] == "animation"

    def run(self, ctx, guidance):
        topic = ctx.outputs["topic"]
        if topic.get("algo"):  # trusted, built-in reference facts: no web needed
            return {"sources": [], "facts": [], "notes": "", "reference": tracers.TRACERS[topic["algo"]].facts()}
        brief = (f"Topic: {topic['topic']}\nAngle: {topic['angle']}\nWhy now: {topic['why_now']}\n"
                 f"Post date: {ctx.day.isoformat()}\nCategory: {ctx.cat['label']} - {ctx.cat['brief']}\n"
                 f"Research is {ctx.cat.get('research')} for this category."
                 + (f" Sources must be published within {ctx.cat['max_source_age_days']} days of the post date."
                    if ctx.cat.get("max_source_age_days") else ""))
        # 1. search
        found = self.ask(ctx, self.prompt(ctx, "research"), brief + "\nSuggested queries:\n" +
                         "\n".join(f"- {q}" for q in topic.get("search_queries", [])) + guidance_block(guidance),
                         SEARCH_SCHEMA, tools=["WebSearch"])
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
        ctx.run.event(self.id, "fetched", f"downloaded {len(pages)} of {len(found['candidates'])} pages",
                      {"downloaded": list(pages), "failed": failed})
        if not pages:
            return {"sources": [], "facts": [], "notes": "no page could be downloaded: " + "; ".join(failed),
                    "candidates": found["candidates"], "download_errors": failed}
        # 3. extract quotes from exactly what we downloaded
        material = "\n\n".join(f"<page url=\"{u}\">\n{t[:PAGE_CHARS]}\n</page>" for u, t in pages.items())
        out = self.ask(ctx, self.prompt(ctx, "research_extract"),
                       brief + "\n\nPAGES (downloaded by the program; quote ONLY from these):\n" + material
                       + guidance_block(guidance), EXTRACT_SCHEMA)
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
        return f"{sum(1 for s in v if s['verified'])}/{len(v)} sources verified, {len(out.get('facts', []))} facts"
