# AI providers

Every agent needs an AI model. Postcrew can use four kinds of provider; pick one in **Settings > Advanced >
AI provider**, then add its key (if any) on **Credentials**.

| Provider (`llm.backend`) | You need | Billing | Web search for research |
|---|---|---|---|
| `claude-code`: **Claude Pro / Max / Team plan** (default) | [Claude Code](https://claude.com/claude-code), logged in | your plan's usage limits; no extra bill | yes (Claude's) |
| `anthropic`: **Claude API** | an Anthropic API key | pay per use | yes (Anthropic's server-side tool) |
| `openai`: **OpenAI API** | an OpenAI API key | pay per use | yes (OpenAI's built-in tool) |
| `openai-compatible`: **any OpenAI-compatible server**: Ollama, LM Studio, OpenRouter, Groq, Together, vLLM, Azure OpenAI and others | its address, and a key if it needs one | depends on the server; local models are free | no (see below) |

Nothing else changes when you switch: the same agents, prompts, checks, review and limits apply.

## Model tiers

Each agent asks for a **tier**, so one setting works with every provider:

| Tier | Meant for | Claude API | OpenAI API |
|---|---|---|---|
| `opus` | strongest | `claude-opus-5-5` | `gpt-5` |
| `sonnet` | balanced (most agents) | `claude-sonnet-5-5` | `gpt-5-mini` |
| `haiku` | fastest and cheapest | `claude-haiku-4-5-20251001` | `gpt-5-nano` |

Change the mapping in **Settings > Advanced > AI provider** (the three model fields appear after you choose an
API provider and save), or in `config.json` under `llm.api.models.<provider>`. You can also type a full model
id for one agent in the **AI models** table instead of a tier, for example `gpt-5` for the Editor only.

## Claude Pro / Max / Team plan (Claude Code)

The default. Install [Claude Code](https://claude.com/claude-code), run `claude` once and log in. No key is
stored in Postcrew. The costs Postcrew shows are what the same work would cost at API prices; on a plan,
it counts towards your usage limits instead. When a limit is reached, the run stops with a clear message and
you can run it again after the limit resets.

## Claude API

1. Create a key at [console.anthropic.com/settings/keys](https://console.anthropic.com/settings/keys) and add
   credit to the account.
2. **Settings > Advanced > AI provider**: choose **Claude API**, then save.
3. **Credentials > AI provider**: paste the key, click **Save key**, then **Test with a tiny call**.

You can also set the environment variable `ANTHROPIC_API_KEY` instead of saving the key.

## OpenAI API

1. Create a key at [platform.openai.com/api-keys](https://platform.openai.com/api-keys) and add credit.
2. **Settings > Advanced > AI provider**: choose **OpenAI API**, then save.
3. **Credentials > AI provider**: paste the key, **Save key**, **Test with a tiny call**.

Environment variable: `OPENAI_API_KEY`. To use a different OpenAI endpoint (for example a proxy), set the
**Server address**.

## OpenAI-compatible servers

Any server that speaks OpenAI's Chat Completions API (`POST <address>/chat/completions`).

1. **Settings > Advanced > AI provider**: choose **OpenAI-compatible**, enter the **Server address**, and save.
2. Fill in the three model fields (the same model three times is fine), and save again.
3. **Credentials**: paste the key if the server needs one (local servers usually don't), then **Test with a
   tiny call**.

| Server | Address | Key | Example models |
|---|---|---|---|
| [Ollama](https://ollama.com) (local) | `http://localhost:11434/v1` | none | `qwen3:32b`, `llama3.3:70b` |
| [LM Studio](https://lmstudio.ai) (local) | `http://localhost:1234/v1` | none | the model you loaded |
| [OpenRouter](https://openrouter.ai) | `https://openrouter.ai/api/v1` | yes | `anthropic/claude-sonnet-5-5`, `openai/gpt-5` |
| [Groq](https://groq.com) | `https://api.groq.com/openai/v1` | yes | see their model list |
| vLLM | `http://<host>:8000/v1` | if you set one | the model you serve |

Environment variable for the key: `LLM_API_KEY`.

**No web search.** These servers can't search the web. When a researcher would search, it is told so and
suggests pages it knows (official announcements, docs, release notes, repositories) instead. Postcrew still
downloads every page and checks every quote, so a page that doesn't exist or doesn't say what was claimed is
rejected. Fresh news works best with a provider that can search; evergreen categories (how-tos, dev tips,
security explainers, algorithms) work well anywhere.

**Use capable models.** The agents must follow long instructions and return valid JSON. Small local models
(under about 14B parameters) often fail the Editor or the format checks; Postcrew then retries and, at the
limits, gives up on the day rather than posting something weak.

## Cost estimates

API providers report tokens, and Postcrew turns them into dollars with the prices in `llm.api.prices` (USD per
million input and output tokens; web searches count $0.01 each). These prices are what Postcrew uses for the
cost shown per run and for the budget caps (`max_budget_usd` per call, `max_run_budget_usd` per post).

The built-in prices are estimates. **Check your provider's current price list** and update `config.json`,
for example:

```json
{ "llm": { "api": { "prices": { "gpt-5": { "input": 1.25, "output": 10.0 },
                                 "qwen3:32b": { "input": 0, "output": 0 } } } } }
```

A model that is not in the table counts as $0, so the budget caps can't stop it. Add its prices if you pay for it.

## Other settings

| Key | Default | What it does |
|---|---|---|
| `llm.api.base_url` | `""` | The server address: required for `openai-compatible`; optional for `openai`. |
| `llm.api.max_output_tokens` | `16000` | Longest answer per call (API providers). Raise it if you see "the answer was cut off". |
| `llm.agents.<id>.timeout_s` | per agent | Seconds to wait for one answer. Local models are slower; raise this for them. |

Rate limits and temporary errors (HTTP 429, 5xx, Anthropic's 529 "overloaded") are retried automatically. A
rejected key or an account with no credit stops the run with a message telling you what to fix.
