"""Default configuration for a new workspace. `postcrew init` writes this to workspace/config.json.

Everything here can be changed in the Studio (Settings tab) or by editing config.json.
Secrets (LinkedIn app, tokens, Telegram) never live here; they go to workspace/secrets.json.
"""

AGENT_IDS = ["planner", "topic", "research", "writer", "reviewer", "media", "editor", "formatter", "publisher", "supervisor", "credentials"]

DEFAULT_CONFIG = {
    "version": 1,
    "profile": {
        "name": "",
        "handle": "",            # shown on posters, e.g. linkedin.com/in/your-name
        "audience": "software engineers and technology leaders",
        "voice": "Plain words, short paragraphs, concrete. Helpful, never salesy.",
        "about": [],             # TRUE facts about you the writer may use. It never invents experience.
        "blocklist": ["my employer", "my company", "confidential", "proprietary", "internal only", "NDA"],
    },
    "schedule": {
        "timezone": "America/Chicago",
        "generate_time": "19:00",   # the crew writes the post the evening before ...
        "post_time": "08:30",       # ... and it is published the next morning
        "lead_days": 1,
        "credential_check_time": "09:00",
        "days": {"mon": "algorithm", "tue": "ai-news", "wed": "build-guide", "thu": "tool-spotlight",
                 "fri": "security", "sat": "dev-tip", "sun": "week-recap"},
        # How often to post: weekly (the days above), every_n_days (from start_date, cycling `rotation`) or dates
        # (only the dates listed). `dates` adds one-off days in any mode; `day_times` gives a weekday its own time.
        "frequency": "weekly",
        "every_n": 2,
        "start_date": "",
        "rotation": [],
        "dates": [],                     # [{"date": "2026-11-03", "category": "dev-tip", "time": "10:00"}]
        "day_times": {},                 # {"sat": "10:30"}
    },
    "planning": {
        # The Week Planner drafts the rest of this week's topics on this day, so you can review and change them.
        "enabled": True,
        "weekday": "mon",
        "time": "10:00",
        "focus": "",                     # optional direction for the whole plan, e.g. "Kubernetes week"
    },
    "publishing": {
        # auto_with_veto: queued posts go out at post_time unless you veto them.
        # manual: nothing is published until you click Approve.  immediate: publish as soon as it passes review.
        "approval": "auto_with_veto",
        # dry_run: the publisher logs exactly what it would send and sends nothing. Turn off when you are ready.
        "dry_run": True,
        "linkedin_api_version": "202601",
    },
    "platforms": {
        # LinkedIn is configured by the settings above. Every other app has its own schedule, plan, topics and
        # publishing settings here, and is switched on separately.
        "linkedin": {"enabled": True},
        "youtube": {
            "enabled": False,
            "schedule": {
                "timezone": "America/Chicago", "generate_time": "19:00", "post_time": "17:00", "lead_days": 2,
                "days": {}, "frequency": "weekly", "every_n": 3, "start_date": "", "rotation": [], "dates": [],
                "day_times": {},
            },
            "planning": {"enabled": True, "weekday": "mon", "time": "10:00", "focus": ""},
            "publishing": {
                "approval": "manual", "dry_run": True,
                "visibility": "public",          # what the video is once it goes live: public | unlisted | private
                "category_id": "28",             # YouTube's own category number (28 = Science & Technology)
                "made_for_kids": False,
            },
            # The default kind of video: "short" (vertical, up to 60 s) or "long" (16:9). A topic, a plan day or a single
            # run may override format and target_seconds.
            "video": {
                "format": "short", "target_seconds": 45,
                "voice": {"provider": "elevenlabs", "voice_id": "", "voice_name": "", "model": "eleven_multilingual_v2",
                          "speed": 1.0},
                "renderer": "ffmpeg",            # ffmpeg: built-in slides. blackboard: drawn by hand to the voice. mcp: an animation MCP server
                "mcp": {"command": "", "args": [], "tool": "", "timeout_s": 600},
                "captions": True,
            },
            "categories": {},   # the topics you create in Settings > Topics (YOUTUBE_EXAMPLE_TOPICS has four to copy from)
        },
    },
    "llm": {
        # claude-code: your Claude Pro / Max / Team login through the Claude Code CLI (no API key).
        # anthropic | openai: their APIs, with an API key (Credentials tab). openai-compatible: Ollama, LM Studio,
        # OpenRouter, Groq, vLLM, Azure OpenAI ... at api.base_url (no web search there).
        "backend": "claude-code",
        "claude_path": "claude",
        "api": {
            "base_url": "",              # openai-compatible: e.g. http://localhost:11434/v1 (Ollama); openai: optional
            "max_output_tokens": 16000,
            # Agents ask for a tier (opus = strongest, sonnet = balanced, haiku = fastest) or a full model id.
            "models": {
                "anthropic": {"opus": "claude-opus-5-5", "sonnet": "claude-sonnet-5-5",
                              "haiku": "claude-haiku-4-5-20251001"},
                "openai": {"opus": "gpt-5", "sonnet": "gpt-5-mini", "haiku": "gpt-5-nano"},
                "openai-compatible": {"opus": "", "sonnet": "", "haiku": ""},
            },
            # USD per million tokens, for the cost shown per run and the budget caps. Check your provider's
            # current price list; a model missing here counts as $0 (web searches still count).
            "prices": {
                "claude-opus-5-5": {"input": 5.0, "output": 25.0},
                "claude-sonnet-5-5": {"input": 3.0, "output": 15.0},
                "claude-haiku-4-5-20251001": {"input": 1.0, "output": 5.0},
                "gpt-5": {"input": 1.25, "output": 10.0},
                "gpt-5-mini": {"input": 0.25, "output": 2.0},
                "gpt-5-nano": {"input": 0.05, "output": 0.4},
            },
        },
        "defaults": {"model": "sonnet", "timeout_s": 600, "max_budget_usd": 1.0},
        "agents": {
            "planner": {"model": "sonnet", "timeout_s": 600, "max_budget_usd": 1.0},
            "topic": {"model": "sonnet", "timeout_s": 300, "max_budget_usd": 0.5},
            "research": {"model": "sonnet", "timeout_s": 900, "max_budget_usd": 1.5},
            "writer": {"model": "sonnet", "timeout_s": 600, "max_budget_usd": 1.0},
            # the Pre-reviewer must predict the Editor, so both use the same, steadier model
            "reviewer": {"model": "sonnet", "timeout_s": 300, "max_budget_usd": 0.4},
            "media": {"model": "haiku", "timeout_s": 300, "max_budget_usd": 0.3},
            "editor": {"model": "sonnet", "timeout_s": 300, "max_budget_usd": 0.4},
            "supervisor": {"model": "haiku", "timeout_s": 180, "max_budget_usd": 0.2},
        },
    },
    "pipeline": {
        "max_attempts_per_step": 4,     # tries per agent before the supervisor gives up on it
        "max_total_attempts": 16,       # tries across the whole run (rewinds included)
        "max_run_budget_usd": 5.0,      # hard stop for one post
        "review_runs": 3,               # the editor reviews this many times and keeps the worst score
        "min_overall": 80,
        "min_subscore": 70,
    },
    "team": {
        # Several Researchers and Writers work on each post; the best combination goes to the Editor.
        "research": 2,                  # researchers per post; their verified sources are combined
        "writer": 2,                    # writers per post; the best draft is chosen
        "pre_review": True,             # score every draft (and polish the best one) before the Editor sees it
        "pre_review_margin": 5,         # polish the best draft unless it beats the passing score by this much
        "polish_rounds": 2,             # at most this many polishes before the Editor sees the draft
        "fire_window": 6,               # judge a member on their last N posts ...
        "fire_min_success": 0.34,       # ... and replace them if fewer than this share were good
    },
    "notifications": {
        "desktop": True,                 # macOS / Linux desktop notification
        "email": False,                  # Gmail; needs gmail_address + gmail_app_password in secrets
        "telegram": False,               # needs telegram_bot_token + telegram_chat_id in secrets
        "warn_days_before_expiry": 7,
        "studio_url": "http://localhost:8765",  # where links in emails point (your port, or your SSH tunnel)
    },
    "categories": {
        "algorithm": {
            "label": "Algorithm in Java (animation)", "media": "animation", "research": "off",
            "min_chars": 500, "max_chars": 1800, "fact_check": False,
            "brief": "Use the supplied algorithm facts only. Order: hook '<Title> in <N> lines of Java, animated step "
                     "by step.' (N = non-empty lines of the shown code); 'How it works:' the steps, numbered; 'Why it "
                     "matters:' one short paragraph; 'The catch:' the watch-out; one real-life use; a question; "
                     "hashtags (#Java #Algorithms #SoftwareEngineering + one topic tag). No sources, no first comment. "
                     "Say the Java shown is real and the animation follows each step; never claim it was recorded live.",
        },
        "ai-news": {
            "label": "Latest AI news", "media": "poster", "layouts": ["points"], "kicker": "AI NEWS",
            "research": "required", "max_source_age_days": 10, "min_chars": 500, "max_chars": 1800,
            "fact_check": True, "plan_ahead": False,  # news a week old is stale: picked the day before
            "brief": "The most useful AI development of the last 7 days for working professionals. Hook: the single "
                     "most concrete sourced fact (a name, number, date or capability), not a general statement. What "
                     "happened: facts from the sources only, in the sources' own tense and with their qualifiers "
                     "(announced, plans to, in preview, says). 'What it means in real life': clearly your opinion "
                     "('I'd try...', 'If this takes off...') or a quoted fact, never a prediction stated as fact. 2-3 "
                     "concrete things the reader could try, written as suggestions; a question; hashtags. "
                     "first_comment = the primary source URL.",
        },
        "build-guide": {
            "label": "Complete how-to: build something cool", "media": "poster", "layouts": ["steps"],
            "kicker": "BUILD IT", "research": "optional", "min_chars": 1400, "max_chars": 2900, "fact_check": False,
            "brief": "A COMPLETE how-to a reader can finish in 20-40 minutes with free tools. What you will build and "
                     "why; what you need; numbered steps with the exact commands and code (plain indented text, under "
                     "~25 lines of code in total, correct and runnable); what you should see when it works; where to "
                     "take it next; a question; hashtags. Use the official docs you opened so commands are current.",
        },
        "tool-spotlight": {
            "label": "Tool or open-source project worth trying", "media": "poster", "layouts": ["points"],
            "kicker": "TOOL SPOTLIGHT", "research": "required", "min_chars": 500, "max_chars": 1800,
            "fact_check": True,
            "brief": "One real open-source project or developer tool updated in the last 12 months. What it does, how "
                     "to try it in two minutes (the exact command from its README), and when NOT to use it. Never "
                     "state star counts, users or benchmarks unless quoted. first_comment = repo or docs URL.",
        },
        "security": {
            "label": "Security and identity explained", "media": "poster", "layouts": ["flow", "points"],
            "kicker": "SECURITY & IDENTITY", "research": "optional", "min_chars": 800, "max_chars": 2200,
            "fact_check": False,
            "brief": "An identity and access explainer (OAuth 2.0 + PKCE, OIDC vs OAuth, SAML vs OIDC, JWT pitfalls, "
                     "refresh token rotation, passkeys, session vs token auth, phishing-resistant MFA, RBAC vs ABAC). "
                     "Well-established facts and correct RFC numbers only. Hook; the flow in 4-6 numbered steps; 'The "
                     "common mistake'; 'Do this instead'; a question; hashtags.",
        },
        "briefed": {
            "label": "Deep dive from your brief (real-world example + system animation)", "media": "auto",
            "research": "optional", "fact_check": False, "briefing": "auto",
            "context": "AI and identity security for practitioners: how authentication, authorization and SSO change when "
                       "AI agents act on behalf of people. Real-world, generic scenarios; the author is an identity "
                       "platform engineering leader.",
            "plan_context": "Plan a series: each day one concrete problem, the system involved and one change to make. "
                            "Alternate stories (before/after), walkthroughs and checklists. Do not repeat a component "
                            "flow used earlier in the week.",
            "brief": "A deep dive built from the owner's brief for the day (Plan > Brief): the real-world example, the "
                     "writing pattern and the system animation come from it. Without a brief: one concrete scenario, "
                     "the flow in 4-6 numbered steps, what goes wrong, the fix, a question, hashtags.",
        },
        "dev-tip": {
            "label": "Quick developer tip with code", "media": "poster", "layouts": ["code"], "kicker": "DEV TIP",
            "research": "off", "min_chars": 400, "max_chars": 1500, "fact_check": False,
            "brief": "One practical tip with 4-12 lines of correct code: a gotcha, a before/after, or a shortcut. Hook; "
                     "the problem; the fix; why it works; a question; hashtags. The code on the poster must be exactly "
                     "what the post describes.",
        },
        "week-recap": {
            "label": "Week in review plus one thing to try", "media": "poster", "layouts": ["points"],
            "kicker": "WEEK IN REVIEW", "research": "off", "min_chars": 500, "max_chars": 1600, "fact_check": False,
            "brief": "Hook ('This week on the page: ...'), the three most useful takeaways from the posts of the last 7 "
                     "days (one line each, drawn only from those posts), ONE small thing to try this week, a question, "
                     "hashtags. No new factual claims.",
        },
    },
}

# Secrets live in workspace/secrets.json (chmod 600). These are the keys the Studio knows about.
SECRET_KEYS = ["linkedin_client_id", "linkedin_client_secret", "linkedin_access_token", "linkedin_token_expires_at",
               "linkedin_person_urn", "linkedin_name", "gmail_address", "gmail_app_password", "email_to",
               "telegram_bot_token", "telegram_chat_id", "anthropic_api_key", "openai_api_key", "llm_api_key",
               "youtube_client_id", "youtube_client_secret", "youtube_refresh_token", "youtube_channel_title",
               "elevenlabs_api_key"]


# Four YouTube topics to copy from. They are NOT part of the default settings: YouTube starts with no topics, and only the
# topics you create in Settings > Topics appear in the weekly schedule. The tests use them as a ready-made set.
YOUTUBE_EXAMPLE_TOPICS = {
                "short-tip": {
                    "label": "Short: one quick tip", "media": "video", "research": "off", "fact_check": False,
                    "format": "short", "target_seconds": 40, "kicker": "QUICK TIP",
                    "brief": "A vertical Short with ONE practical tip. Hook in the first 3 seconds (the problem or a "
                             "surprising result, never 'hi guys'), the tip in 2-4 steps, what the viewer will see when it "
                             "works, then one line asking them to try it. Short sentences, spoken words, no filler.",
                },
                "explainer": {
                    "label": "Long: explain one idea", "media": "video", "research": "optional", "fact_check": False,
                    "format": "long", "target_seconds": 480, "kicker": "EXPLAINED",
                    "brief": "A 16:9 explainer a mid-level professional can follow in one watch. Cold open with the problem "
                             "(15 s), why it matters, the idea built up in 3-5 scenes with one concrete example, the common "
                             "mistake, what to do next. One idea per scene; narration as you would say it aloud.",
                },
                "tutorial": {
                    "label": "Long: step-by-step tutorial", "media": "video", "research": "optional", "fact_check": False,
                    "format": "long", "target_seconds": 600, "kicker": "TUTORIAL",
                    "brief": "A complete tutorial the viewer can finish with free tools. What we build and what you need, "
                             "numbered steps each with the exact command or code on screen (correct and runnable, short), "
                             "what you should see when it works, where to take it next.",
                },
                "news-brief": {
                    "label": "Short: this week's news, sourced", "media": "video", "research": "required", "fact_check": True,
                    "format": "short", "target_seconds": 55, "kicker": "NEWS", "max_source_age_days": 10,
                    "brief": "A vertical Short on the most useful development of the last 7 days: the sourced fact first, what "
                             "happened in the sources' own tense and qualifiers, what it means (labelled as opinion), one "
                             "thing to try. Every number must come from a verified source.",
                },
}
