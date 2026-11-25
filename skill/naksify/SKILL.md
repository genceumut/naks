---
name: naksify
description: Connects an existing project to NAKS: suggests the zero-change naks-dev route, or makes a copy whose AI calls go through NAKS. Use with /naksify project-name or /naksify github repo-name.
---

# /naksify — connect an existing project to NAKS

Goal: make a project's AI calls (Anthropic, OpenAI and similar providers) work without an API key during development, through NAKS (https://github.com/genceumut/naks). **The original project is never modified.** Pending requests are answered with the `/naks` skill.

> Template: set these to your own values before adding this skill to Claude.
>
> - `PROJECTS = ~/Projects` (your projects folder)
> - `NAKS_HOME = ~/Projects/naks` (your NAKS clone)
> - `GITHUB_OWNER = your-github-username`

## 0. Where to work

- `/naksify <project>`: `PROJECTS/<project>` on the user's computer, reached through the Claude desktop app (`get_device_info`, and `device_request_folder_access` if the folder isn't connected). Copies go to `PROJECTS/naks-at-your-service/<name>/`, where `<name>` is the project's folder name. For nested projects use the last folder name (`client/web` → `naks-at-your-service/web/`). If that name is taken by another project's copy, prefix the parent folder name (`client-web`).
- `/naksify github <repo>`: `GITHUB_OWNER/<repo>`. Call `add_repo` with `access: push` and clone it. The "copy" is a new `naks` branch. Never push to the default branch.

Take the client files from `NAKS_HOME`, or from the NAKS GitHub repo.

**Never read or print `.env`, `.env.local` or similar secret files.** Exclude them from every scan.

## 1. Find the AI calls (read-only)

```bash
cd <project>
grep -rnIE --exclude-dir={node_modules,.git,.venv,venv,__pycache__,build,dist,.next,Pods,.dart_tool,DerivedData,.naks} \
  --exclude='.env*' --exclude='*.lock' --exclude='*lock.json' --exclude='*.tsbuildinfo' \
  -e 'anthropic|openai|generativeai|GoogleGenerativeAI|@google/genai|messages\.(create|stream)|chat\.completions|responses\.create|generateText|generateObject|streamText|streamObject|langchain|api\.anthropic\.com|api\.openai\.com|generativelanguage\.googleapis|_API_KEY' .
```

Read every file that matches. For each call, note: the file and function, the language, the SDK, what is sent (system prompt, messages, images, schema or tool definitions, streaming) and how the code uses the result.

If there are no AI calls, say so and stop.

Before changing anything, record the original's state: `git -C <project> status --short` (skip this if the project isn't a git repo). You'll compare against it in step 5.

## 2. Route A: no copy needed (`naks-dev`)

`naks-dev` starts a local endpoint and points the official SDKs at it through environment variables, without any code changes. Route A is enough when all of these hold:
- Every call goes through the official Anthropic SDK (`anthropic`, `@anthropic-ai/sdk`) or the OpenAI SDK (`openai`).
- `base_url` / `baseURL` isn't hard-coded. If it comes from settings, the setting is empty, so the SDKs read `ANTHROPIC_BASE_URL` / `OPENAI_BASE_URL`.
- The calls run in Node or Python, not in an Edge runtime or the browser.
- No real multi-tool loops, embeddings or audio. A single tool for structured output, streaming, images and JSON schema are all supported.

If Route A fits, don't create a copy. Give the user the command and stop, for example: `cd <project> && naks-dev npm run dev`, with `NAKS_MODE=cli` in front for immediate answers. Pending requests collect in the project's `.naks/` folder and are answered with `/naks <project>`. Suggest adding `.naks/` to the project's `.gitignore`. If the user still wants a copy, or a condition fails, continue with Route B.

## 2b. Route B: decide where to change the copy

- **Find the lowest shared layer.** If all calls go through one provider, client class or wrapper function (`make_client`, `LLMClient`, `callClaude` and so on), change **only that layer**: write a NAKS-backed equivalent and make the project use it. Leave the callers alone.
- With no shared layer, change each call site.
- **Keep signatures and return types.** The rest of the code shouldn't notice anything. If the original read `resp.content[0].text` and returned a string, the new code returns a string. If callers expect a response object, return a small object with the same fields.

## 3. Convert the calls

Create the copy first. Use `tar`, because it needs no delete permission:

```bash
cd $HOME/mnt/<projects-folder-name> && mkdir -p naks-at-your-service && [ ! -e naks-at-your-service/<name> ] && mkdir naks-at-your-service/<name> && \
tar -C <project> --exclude=node_modules --exclude=.git --exclude=.venv --exclude=venv --exclude=__pycache__ \
  --exclude=.next --exclude=dist --exclude=build --exclude=Pods --exclude=.dart_tool --exclude=DerivedData --exclude=.naks \
  -cf - . | tar -C naks-at-your-service/<name> -xf -
```

Then run `mkdir -p .naks/requests .naks/responses` at the copy's root. The copy has no `.git`, so the client finds the project root through this folder.

If `naks-at-your-service/<name>` already exists, don't overwrite it. Ask the user whether to recreate it or add the new calls to the existing copy. On GitHub, run `git checkout -b naks`. If a `naks` branch already exists, ask too.

Add the client to the copy:
- Python: put `naks_client.py` next to the calling module or in the project's package (for example `src/<pkg>/naks_client.py`) and import it to match the project's layout.
- JS/TS: put `naks-client.mjs` and `naks-client.d.mts` in `src/lib/` or a similar folder.

Mapping:

| Original | NAKS |
|---|---|
| `system` | `system` |
| Single user message | `prompt` |
| Multi-turn `messages` (including repair / retry loops) | `prompt`: "Reply as the assistant to the last user message in the conversation below." plus `inputs: {"messages": [...]}` without images |
| Image or PDF content blocks | `files=[path, ...]`. If the image is in memory (base64 or bytes), first write it to `.naks/files/<sha256-first16>.<ext>` and pass that path |
| JSON mode, `response_format`, zod / pydantic schema, `output_format` | `schema=<JSON Schema>`. Use `z.toJSONSchema()` for zod v4, `Model.model_json_schema()` for pydantic |
| A single tool used for structured output (`tools=[...]`, then reading `tool_use`) | `schema=tool["input_schema"]`. Put the returned dict where the code read `block.input` |
| Streaming (`.stream()`, `finalMessage()`, `stream=True`) | A plain `await ask(...)`. If the code consumes chunks, hand it the full text as one chunk |
| `model`, `temperature`, `max_tokens`, `betas`, `fallbacks` | Drop them, with a short note on that line such as `# NAKS: not used in chat mode` |
| Cost / usage logging | Keep it working with zero usage. Log `provider` as `"naks"` |
| Reading the API key, creating the client, exiting when the key is missing | Remove from the copy. The copy must run without a key |

Derive `task` from the calling function or stage (`script-stage`, `deck-generate` and so on). It must be stable, with no dates or random values, or the cache won't work.

Handling `NaksPending`:
- In CLI and script flows, let it propagate. Its message already says to run /naks. Make sure broad `except Exception` blocks don't swallow it: catch `NaksPending` before them and re-raise.
- In web servers (Next.js routes, FastAPI or Flask endpoints), catch it in the handler and return HTTP `202` with `{"naks": "pending", "ids": [...], "message": "run /naks in a Claude chat"}`. Surface it through the app's existing error display.

**Not converted (v1).** Leave these in place and list them in the report:
- Real tool loops (the model calls a tool, the code runs it, the result goes back to the model)
- Embeddings, image generation, speech (TTS/STT) and video APIs
- Code that runs in the browser, an Edge runtime or a mobile app (no `fs`), including direct calls from Swift or Dart. Suggest moving the call to a Node or Python backend.

UIs that expect live streaming (chat screens, for example) are converted and work, but the answer only arrives after `/naks`. Note this in the report.

## 4. Write `NAKS.md` in the copy

Put a `NAKS.md` at the copy's root covering:
- which original it came from, and the date
- the files that changed, and what changed in each, briefly
- the calls that weren't converted, and why
- how to run it: install dependencies (`npm install`, `pip install -e .`), run the command, run `/naks <name>` when `NaksPending` appears, then run again
- that production should use the original project, not the copy

## 5. Verify

- Python: run `python3 -m py_compile` on the changed files. If the project installs, run its tests, unless they would call a real API.
- JS: `node --check` only works on `.js` / `.mjs`. In TS projects `node_modules` isn't copied, so type-checking isn't possible. Say so in the report.
- Check the original is untouched: `git -C <project> status --short` must match what you recorded in step 1.
- Check that only the planned files changed: `diff -ru --exclude=NAKS.md --exclude='naks_client.py' --exclude='naks-client.*' --exclude=node_modules --exclude=.git --exclude=.naks <project> naks-at-your-service/<name> | head -200`.

## 6. Commit (GitHub mode only)

Commit with the user's own git identity and push the `naks` branch. Never push to the default branch.

```bash
git add -A
git commit -m "naks: NAKS version"
git push -u origin naks
```

## 7. Report

Keep it short:
- Which route was chosen (A: `naks-dev`, B: copy) and why
- Where the copy is (folder or branch)
- How many calls were converted, and at which layer
- What wasn't converted, and why
- What was verified and what couldn't be
- One line for the first run: the command to run, then `/naks <name>`
