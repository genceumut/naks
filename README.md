# NAKS — No API Key System

**Develop AI features on your Claude subscription instead of paying for API tokens.**

[Türkçe](README.tr.md) · [Setup guide](INSTALL.md)

## The problem

When you build something that calls an LLM, most of the calls during development are throwaway. You tweak a prompt and rerun, fix a parsing bug and rerun, rerun again to check the UI. Every one of those calls costs API tokens, even though you probably already pay for a Claude plan that you use every day.

## What NAKS does

NAKS sits between your code and the model API **while you develop**:

1. Your code asks a question, either through its normal Anthropic/OpenAI SDK or through NAKS's tiny `ask()` function.
2. If NAKS has answered that exact question before, the answer comes straight from a local file. No model is called.
3. If not, the question is answered from **your Claude subscription**, in one of two ways you choose:
   - **Chat mode (default):** the question is saved to a file. When you're ready, you type `/naks` in a Claude chat, and Claude answers every waiting question at once and writes the answers back.
   - **CLI mode:** the question is answered on the spot by Claude Code (`claude -p`) on your machine, up to a daily limit you set.
4. Every answer is saved, so rerunning your code costs nothing.

In production you flip one setting (`NAKS_MODE=api`), and the same code calls the real API with your API key, as normal.

```
your code ──ask() / SDK──▶ NAKS ──▶ answered before? ── yes ──▶ answer from disk
                                     │ no
                    ┌────────────────┼──────────────────┬───────────────┐
                    ▼                ▼                  ▼               ▼
                  chat              cli              record           api
           queue it; answer    `claude -p`,     real API once,    real API,
           with /naks in a     right away        then saved       no cache
           Claude chat         (daily cap)                       (production)
                    └────────────────┴──────────────────┘
                                     ▼
                         .naks/responses/<id>.json
```

**Good for:** prototypes, prompt iteration, generating test data and fixtures, scripts and pipelines you rerun often, side projects.
**Not for:** production traffic, serving other users, real-time chat UIs (in chat mode answers arrive when you run `/naks`), or multi-step agents that call tools in a loop.

> **Note on "OpenAI-compatible":** NAKS accepts requests in OpenAI's API format so that projects written with the OpenAI SDK work without changes. Those requests are still answered by **Claude**, not by GPT models.

## What you need

| | Needed for |
|---|---|
| A Claude plan (Pro, Max, …) | Everything: answers come from your subscription |
| Python 3.9+ | Everything (NAKS itself has no other dependencies) |
| [Claude desktop app](https://claude.ai/download) with your projects folder added, plus the `/naks` skill | Chat mode: Claude reads the waiting questions from your disk |
| [Claude Code](https://code.claude.com/docs/en/setup), logged in with your Claude account | CLI mode |
| Node 18+ | Only if you use the JavaScript client |
| An API key | Only for `record` and `api` modes |

The [setup guide](INSTALL.md) walks through all of it step by step.

## Quick start

```bash
git clone https://github.com/genceumut/naks ~/Projects/naks
export PATH="$HOME/Projects/naks/bin:$PATH"   # optional: lets you type `naks-dev` anywhere
python3 ~/Projects/naks/examples/demo.py       # prints "2 request(s) queued"
```

Then say `/naks naks` in a Claude chat, run the demo again, and the answers appear. This needs the `/naks` skill and the Claude desktop app with your projects folder added, which the [setup guide](INSTALL.md) covers. Or skip the chat and answer through Claude Code: `NAKS_MODE=cli python3 -c "import sys; sys.path.insert(0, '$HOME/Projects/naks/python'); from naks_client import ask; print(ask('Say hello in 3 words'))"`.

## Connect a project

### Option 1: no code changes (`naks-dev`)

If your project uses the official **Anthropic** or **OpenAI** SDK, put `naks-dev` in front of the command you already use:

```bash
cd your-project
naks-dev npm run dev                         # chat mode: answer with /naks
NAKS_MODE=cli naks-dev python3 generate.py   # cli mode: answered right away by claude -p
```

`naks-dev` starts a small local server (`naks serve`, port 4141) that speaks the Anthropic and OpenAI APIs. It points your SDK at that server through `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`, with a dummy API key, and stops the server when your command exits. Your code doesn't know the difference.

The server supports normal requests, streaming, images and PDFs, JSON-schema output and structured output through a single tool.

### Option 2: call NAKS from code (`ask()`)

For new code, or projects that don't use an official SDK, copy one file into your project. It has no dependencies.

```python
from naks_client import ask   # python/naks_client.py

title = ask("Suggest a 5-word title for this note:\n" + note, task="note-title")
tags = ask("Extract 2-4 tags.", inputs={"note": note},
           schema={"type": "array", "items": {"type": "string"}}, task="tags")
summary = ask("Summarize this slide in one sentence.", files=["slides/p3.png"], task="slide-summary")
```

```js
import { ask } from "./naks-client.mjs";   // js/naks-client.mjs (+ naks-client.d.mts types)
const tags = await ask("Extract 2-4 tags.", { inputs: { note }, schema: { type: "array", items: { type: "string" } }, task: "tags" });
```

In chat mode, an unanswered `ask()` raises `NaksPending` with a message telling you to run `/naks`. Run your code, say `/naks`, run it again. Changing the prompt, system prompt, inputs, schema or an attached file makes a new question. Anything unchanged is never asked twice.

### Option 3: let Claude do it (`/naksify`)

With the `/naksify` skill installed, say `/naksify my-project` in Claude. It checks whether Option 1 is enough and gives you the command. If it isn't, it makes a converted copy under `naks-at-your-service/my-project/` and leaves the original untouched.

## Modes

Set with the `NAKS_MODE` environment variable. Every mode except `api` looks for a saved answer first.

| Mode | When there's no saved answer | Use it for |
|---|---|---|
| `chat` (default) | Saves the question and waits for `/naks` | Batches, questions with images, anything you want to look at |
| `cli` | Answers right away with `claude -p` | Small one-off questions while you work |
| `record` | Calls the real API once and saves the answer | Capturing real model output as fixtures |
| `replay` | Fails with `NaksMissing` and never asks anything new | Tests and CI |
| `api` | Calls the real API directly, without the cache | Production |

### Safeguards in `cli` mode

- **Text only.** `claude -p` runs with all tools disabled, in an empty temporary folder, with no MCP servers and no saved session.
- **No API billing.** `ANTHROPIC_API_KEY` is removed from its environment, so Claude Code can't quietly bill your API account instead of using your plan.
- **Daily cap.** At most `NAKS_CLI_DAILY_LIMIT` calls per day (default 20). Every call is logged to `.naks/cli-log.jsonl`.
- **Fallback to chat mode** when the cap is reached, the question has attachments, Claude Code isn't installed, or a call fails twice.

### Settings

| Variable | Default | Purpose |
|---|---|---|
| `NAKS_MODE` | `chat` | See above |
| `NAKS_DIR` | `.naks` in the project root (the nearest folder with `.git` or `.naks`) | Where questions and answers are stored |
| `NAKS_WAIT` | `0` | Seconds `ask()` waits for an answer in chat mode before raising `NaksPending` |
| `NAKS_MODEL` | `claude-sonnet-5-5` | Model for `api` / `record` |
| `NAKS_CLI_DAILY_LIMIT` | `20` | Max `claude -p` calls per day |
| `NAKS_CLI_TIMEOUT` | `180` | Seconds per `claude -p` call |
| `NAKS_CLI_MODEL` | Claude Code's default | Model for `cli` |
| `NAKS_PORT` | `4141` | Port for `naks serve` / `naks-dev` |
| `NAKS_SERVE_WAIT` | `540` | Seconds the server keeps a request open in chat mode. After that it replies HTTP 424, which SDKs don't auto-retry. |

## Claude skills

Two skills live in [`skill/`](skill/). The [setup guide](INSTALL.md#4-install-the-claude-skills) shows how to add them to Claude.

- **`/naks`** finds waiting questions in your projects (through the Claude desktop app's folder access, or a GitHub repo), answers each one the way a plain API call would, and writes the answer files.
- **`/naksify <project>`** connects an existing project, as described in [Option 3](#option-3-let-claude-do-it-naksify).

The protocol is plain JSON files, so anything that can read and write `.naks/` can answer questions.

## FAQ

**Is this allowed?** NAKS is designed to stay on the conservative side. See [Responsible use](#responsible-use) below. In short: personal development only, no credential copying, official Claude apps only.

**Will answers match what the API would return?** Not byte-for-byte, and API settings like `temperature` don't apply. They're great for building and testing. For final prompt tuning, use `record` or `api` mode.

**Should I commit the `.naks/` folder?** Answers in `.naks/responses/` work well as test fixtures. Don't commit `.naks/requests/` if your prompts contain anything private. Always ignore `.naks/cli-usage.json` and `.naks/cli-log.jsonl`.

**Can I answer from GitHub instead of my computer?** Yes. Push `.naks/requests/`, say `/naks github your-repo`, and Claude commits the answers. Then `git pull`.

**Does it work with my ChatGPT subscription?** Not today. NAKS answers with Claude.

## Responsible use

- **No credential reuse.** NAKS never extracts, copies or proxies OAuth tokens or web sessions, and never automates a chat website. Answers come from you working in an official Claude app (`chat` mode) or from the official Claude Code CLI on your own machine (`cli` mode).
- **Personal development only.** Don't put it in front of end users, share one subscription between people, or run it as a service. Production traffic should use `NAKS_MODE=api` with your own API key.
- **Be measured with `cli` mode.** As of November 2026, Anthropic's help center says `claude -p` usage on a Claude plan draws from your plan's usage limits ([source](https://support.claude.com/en/articles/15036540)). Anthropic's rules on programmatic use of subscriptions changed several times in 2026, so check the current [Consumer Terms](https://www.anthropic.com/legal/consumer-terms) yourself. Keep the daily cap low, and don't use `cli` mode for scheduled or unattended jobs.

You're responsible for how you use NAKS with your own accounts. NAKS is not affiliated with or endorsed by Anthropic or OpenAI.

## Limitations

- Chat mode isn't real-time: answers arrive when you run `/naks`.
- `naks serve` supports one tool per request for structured output, not multi-step tool loops. Embeddings, audio and image generation aren't supported.
- CLI mode needs Claude Code installed and logged in on the machine that runs your code.

## How it works (protocol)

Each question is a JSON file named by a hash of its content:

```json
// .naks/requests/tags-3f2a9c1b7d4e.json
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

```json
// .naks/responses/tags-3f2a9c1b7d4e.json
{ "naks": 1, "id": "tags-3f2a9c1b7d4e", "answered_at": "…", "answered_by": "claude-chat", "output": ["work", "meeting"] }
```

- **Id:** `<task>-<first 12 hex chars of SHA-256>` of `system`, `prompt`, `inputs`, `output` and `files`. The Python and JS clients produce the same ids, so they share answers.
- **`output.format`:** `text`, `markdown` or `json`. It defaults to `json` when a schema is given.
- **`answered_by`:** `claude-chat`, `claude-cli` or `api:<model>`.
- **Errors:** an unanswerable question gets `"error": "…"` instead of `output`.
- **Server requests:** questions that came through `naks serve` have `serve-anthropic-…` / `serve-openai-…` ids. Send an `X-NAKS-Task` header to name them. Images sent as base64 are stored under `.naks/files/`.

## Project layout

```
bin/naks-dev            run any command with its SDK calls routed through NAKS
python/naks_client.py   Python client: ask, submit, get, pending
python/naks_serve.py    local Anthropic/OpenAI-compatible server
js/naks-client.mjs      JavaScript client (+ naks-client.d.mts types)
skill/                  Claude skills: /naks and /naksify
examples/demo.py        two-question demo
INSTALL.md              step-by-step setup
```

## License

[MIT](LICENSE)
