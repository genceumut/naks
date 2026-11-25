# NAKS — No API Key System

**Build and iterate on AI features using your Claude subscription instead of paying for API tokens.**

When you're prototyping something that calls an LLM, most of the calls are throwaway: you tweak a prompt, rerun the script, fix a bug, rerun again. Paying per token for all of that adds up, even though you already pay for a Claude plan. NAKS sits between your code and the model API during development. It answers your app's AI calls from your subscription, caches every answer so the same question is never asked twice, and gets out of the way in production.

```
your code ──ask() / SDK──▶ NAKS ──▶ cached?  ── yes ──▶ answer
                                     │ no
                    ┌────────────────┼──────────────────┬───────────────┐
                    ▼                ▼                  ▼               ▼
                  chat              cli              record           api
           queue it; answer    `claude -p`,     real API once,    real API,
           with /naks in a     right away        then cached      no cache
           Claude chat         (daily cap)                       (production)
                    └────────────────┴──────────────────┘
                                     ▼
                         .naks/responses/<id>.json
```

[Türkçe README](README.tr.md)

## Highlights

- **Zero code changes for SDK projects.** `naks-dev npm run dev` starts a local endpoint that speaks the Anthropic (`/v1/messages`) and OpenAI (`/v1/chat/completions`) APIs and points the official SDKs at it.
- **Two ways to answer from your subscription.** Queue requests and answer a whole batch in one go from a Claude chat (`/naks`). Or answer small requests instantly through Claude Code (`claude -p`), behind a daily cap.
- **Content-addressed cache.** Every request gets an id from a SHA-256 hash of its content. Answers are plain JSON files, so you can read them, diff them and commit them as fixtures.
- **One switch to production.** `NAKS_MODE=api` calls the real API with your key, with no cache in the way. `record` and `replay` modes cover fixtures and CI.
- **Zero dependencies.** Single-file Python (3.9+) and JavaScript (Node 18+) clients. Python and JS share the same cache.

## Quick start

```bash
git clone https://github.com/genceumut/naks ~/naks
export PATH="$HOME/naks/bin:$PATH"        # add to your shell profile
```

### Option 1: no code changes (`naks-dev`)

If your project uses the official Anthropic or OpenAI SDK, prefix your usual command:

```bash
cd your-project
naks-dev npm run dev                         # chat mode: answer with /naks
NAKS_MODE=cli naks-dev python3 generate.py   # cli mode: answered right away by claude -p
```

`naks-dev` starts `naks serve` on `127.0.0.1:4141`. It sets `ANTHROPIC_BASE_URL`, `OPENAI_BASE_URL` and dummy API keys for your command, and stops the server when the command exits. Your code believes it is talking to the real API.

The endpoint supports text, streaming, base64 images and PDFs, JSON schema output (`response_format` / `output_format`) and structured output through a single tool. Multi-tool agent loops, embeddings and audio are not supported.

### Option 2: call NAKS directly (`ask()`)

Copy one file into your project. There are no other dependencies.

```python
from naks_client import ask, NaksPending

title = ask("Suggest a 5-word title for this note:\n" + note, task="note-title")
tags = ask("Extract 2-4 tags.", inputs={"note": note},
           schema={"type": "array", "items": {"type": "string"}}, task="tags")
summary = ask("Summarize this slide in one sentence.", files=["slides/p3.png"], task="slide-summary")
```

```js
import { ask } from "./naks-client.mjs";   // types: naks-client.d.mts
const tags = await ask("Extract 2-4 tags.", { inputs: { note }, schema: { type: "array", items: { type: "string" } }, task: "tags" });
```

In chat mode the loop works like this:
1. Run your code. Unanswered requests are written to `.naks/requests/` and `NaksPending` is raised.
2. In a Claude chat, say `/naks` (see [Claude skills](#claude-skills)). Claude answers every pending request.
3. Run your code again. Answers now come from disk.

Changing the prompt, system message, inputs, schema or an attached file changes the id, so the new request gets asked. If nothing changes, the request is never asked again.

## Modes

Set with `NAKS_MODE`. Every mode except `api` checks the cache first.

| Mode | On a cache miss | Use it for |
|---|---|---|
| `chat` (default) | Writes the request and raises `NaksPending` (or holds the HTTP request open). You answer with `/naks` in Claude. | Batches, requests with images, anything you want to look at |
| `cli` | Answers right away with `claude -p` from your subscription | Small, one-off requests while developing |
| `record` | Calls the real API and saves the answer | Capturing real model output as fixtures, paying once |
| `replay` | Raises `NaksMissing` and never asks anything new | Tests and CI |
| `api` | Calls the real API directly, without the cache | Production |

### `cli` mode safeguards

`claude -p` runs with every tool disabled, in an empty temporary directory, with no MCP servers and no saved session, so it can only produce text. `ANTHROPIC_API_KEY` is removed from its environment so it can never fall back to billing your API account.

Calls are capped per day by `NAKS_CLI_DAILY_LIMIT` (default 20), and every call is logged to `.naks/cli-log.jsonl`. A request falls back to `chat` when:
- the daily cap is reached
- the request has attachments
- `claude` isn't installed
- the call fails twice or returns output that doesn't match the schema

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NAKS_MODE` | `chat` | See above |
| `NAKS_DIR` | nearest parent with `.git`/`.naks`, + `/.naks` | Where requests and answers live |
| `NAKS_WAIT` | `0` | Seconds `ask()` polls for an answer in chat mode |
| `NAKS_MODEL` | `claude-sonnet-5-5` | Model for `api` / `record` |
| `NAKS_CLI_DAILY_LIMIT` | `20` | Max `claude -p` calls per day |
| `NAKS_CLI_TIMEOUT` | `180` | Seconds per `claude -p` call |
| `NAKS_CLI_MODEL` | Claude Code default | Model for `cli` |
| `NAKS_PORT` | `4141` | Port for `naks serve` |
| `NAKS_SERVE_WAIT` | `540` | Seconds `naks serve` holds a request open in chat mode. Shorter than the default SDK timeouts. When it runs out, the endpoint answers HTTP 424, which SDKs don't auto-retry. |

Suggested `.gitignore` entries for projects using NAKS: `.naks/cli-usage.json`, `.naks/cli-log.jsonl`, `.naks/*.tmp`. Ignore `.naks/requests/` too if your prompts contain anything you don't want in git.

## Claude skills

NAKS ships two [Claude skills](https://docs.claude.com) as templates in [`skill/`](skill/). Add them to Claude as skills and adjust the paths and GitHub owner to your setup.

- **`/naks`** finds pending requests in your projects folder (through the Claude desktop app's folder access) or in a GitHub repo, answers them as a plain model call would, and writes the answer files.
- **`/naksify <project>`** looks at an existing project. If `naks-dev` is enough, it just tells you the command. Otherwise it creates a copy under `naks-at-your-service/<project>/` and rewrites the AI calls in the copy to use `ask()`. The original project is never modified.

The skills work in the Claude apps when they can reach your files (for example through the desktop app). Any client that can read and write the `.naks/` folders can answer requests, because the protocol is just JSON files.

## Protocol

`.naks/requests/<id>.json`

```json
{
  "naks": 1,
  "id": "tags-3f2a9c1b7d4e",
  "project": "my-app",
  "task": "tags",
  "created_at": "2026-11-24T10:45:00+00:00",
  "system": "Optional system prompt",
  "prompt": "Extract 2-4 tags.",
  "inputs": { "note": "..." },
  "output": { "format": "json", "schema": { "type": "array", "items": { "type": "string" } } },
  "files": [{ "path": "slides/p3.png", "sha256": "…" }]
}
```

`.naks/responses/<id>.json`

```json
{ "naks": 1, "id": "tags-3f2a9c1b7d4e", "answered_at": "…", "answered_by": "claude-chat", "output": ["work", "meeting"] }
```

- **Id:** `<task slug>-<first 12 hex chars of SHA-256>` over the canonical JSON of `system`, `prompt`, `inputs`, `output` and `files`. The Python and JS clients produce identical ids.
- **`output.format`:** `text`, `markdown` or `json`. When a schema is given, the default is `json`.
- **`answered_by`:** `claude-chat` (`/naks`), `claude-cli` (`cli` mode) or `api:<model>` (`record` mode).
- **Errors:** if a request can't be answered, the response file contains `"error": "…"` instead of `output`.
- **Endpoint requests:** requests that come through `naks serve` get `serve-anthropic-…` / `serve-openai-…` ids. Send an `X-NAKS-Task` header to name them yourself. Base64 attachments are stored under `.naks/files/`.

## Terms of service and responsible use

NAKS is built to stay on the conservative side of how consumer AI plans may be used:

- **No credential reuse.** NAKS never extracts, copies or proxies OAuth tokens or web sessions, and never automates a chat web UI. Answers come either from you working in an official Claude app (`chat` mode) or from the official Claude Code CLI on your own machine (`cli` mode).
- **Personal development only.** Use it for your own development work. Don't put it in front of end users, share one subscription across people, or run it as a service. Production traffic should use `NAKS_MODE=api` with your own API key.
- **Be measured with `cli` mode.** As of November 2026, Anthropic's help center says `claude -p` usage on a Claude plan draws from your plan's usage limits ([source](https://support.claude.com/en/articles/15036540)). Anthropic's policies on programmatic and third-party use of subscriptions changed several times in 2026, so check the current [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) and usage policies yourself. Keep the daily cap low, and don't wire `cli` mode into scheduled or unattended jobs.

You are responsible for how you use NAKS with your own accounts. This project is not affiliated with or endorsed by Anthropic or OpenAI.

## Limitations

- An answer from a chat or from `claude -p` is not byte-for-byte what the raw API would return, and parameters like `temperature` don't apply. It's great for intermediate output, test data, classification and drafts. Do your final prompt tuning with `record` or `api`.
- `chat` mode isn't real-time: answers arrive when you run `/naks`.
- `naks serve` handles one structured-output tool per request, not real multi-tool agent loops. Embeddings, audio and image generation are not supported (those paths return 404).
- `cli` mode needs Claude Code installed and logged in on the machine running your code.

## Project layout

```
bin/naks-dev            run any command with SDK calls routed through NAKS
python/naks_client.py   Python client (ask, submit, get, pending)
python/naks_serve.py    local Anthropic/OpenAI-compatible endpoint
js/naks-client.mjs      JavaScript client (+ naks-client.d.mts types)
skill/                  Claude skill templates (/naks, /naksify)
examples/demo.py        minimal example
```

## License

MIT
