"""Default configuration for a new workspace. `postcrew init` writes this to workspace/config.json.

Everything here can be changed in the Studio (Settings tab) or by editing config.json.
Secrets (LinkedIn app, tokens, Telegram) never live here; they go to workspace/secrets.json.
"""

AGENT_IDS = ["planner", "topic", "research", "writer", "media", "editor", "formatter", "publisher", "supervisor", "credentials"]

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
    },
    "planning": {
        # The Week Planner drafts next week's topics on this day, so you can review and change them.
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
    "llm": {
        "backend": "claude-code",
        "claude_path": "claude",
        "defaults": {"model": "sonnet", "timeout_s": 600, "max_budget_usd": 1.0},
        "agents": {
            "planner": {"model": "sonnet", "timeout_s": 600, "max_budget_usd": 1.0},
            "topic": {"model": "sonnet", "timeout_s": 300, "max_budget_usd": 0.5},
            "research": {"model": "sonnet", "timeout_s": 900, "max_budget_usd": 1.5},
            "writer": {"model": "sonnet", "timeout_s": 600, "max_budget_usd": 1.0},
            "media": {"model": "haiku", "timeout_s": 300, "max_budget_usd": 0.3},
            "editor": {"model": "haiku", "timeout_s": 300, "max_budget_usd": 0.3},
            "supervisor": {"model": "haiku", "timeout_s": 180, "max_budget_usd": 0.2},
        },
    },
    "pipeline": {
        "max_attempts_per_step": 3,     # tries per agent before the supervisor gives up on it
        "max_total_attempts": 10,       # tries across the whole run (rewinds included)
        "max_run_budget_usd": 5.0,      # hard stop for one post
        "review_runs": 3,               # the editor reviews this many times and keeps the worst score
        "min_overall": 80,
        "min_subscore": 70,
    },
    "notifications": {
        "desktop": True,                 # macOS / Linux desktop notification
        "email": False,                  # Gmail; needs gmail_address + gmail_app_password in secrets
        "telegram": False,               # needs telegram_bot_token + telegram_chat_id in secrets
        "warn_days_before_expiry": 7,
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
            "brief": "The most useful AI development of the last 7 days for working professionals. Hook with the key "
                     "fact; what happened (facts from the sources only); 'What it means in real life'; 2-3 concrete "
                     "things the reader could try, written as suggestions; a question; hashtags. first_comment = the "
                     "primary source URL.",
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
               "telegram_bot_token", "telegram_chat_id"]
