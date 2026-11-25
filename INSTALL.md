# Setting up NAKS

This guide takes you from nothing to a project answering its AI calls from your Claude subscription. Commands are for macOS and Linux. On Windows, use WSL.

[Türkçe](INSTALL.tr.md) · [Back to README](README.md)

**Contents**
1. [Check the basics](#1-check-the-basics)
2. [Get NAKS](#2-get-naks)
3. [Try the demo](#3-try-the-demo)
4. [Install the Claude skills](#4-install-the-claude-skills) (for chat mode)
5. [Set up Claude Code](#5-set-up-claude-code) (for cli mode)
6. [Connect your first project](#6-connect-your-first-project)
7. [Troubleshooting](#7-troubleshooting)
8. [Uninstall](#8-uninstall)

You don't need both step 4 and step 5. Chat mode needs step 4, cli mode needs step 5, and you can add the other one later.

---

## 1. Check the basics

```bash
python3 --version   # 3.9 or newer
git --version
node --version      # only if you'll use the JavaScript client (18 or newer)
```

You also need a Claude plan (Pro, Max, Team, …).

## 2. Get NAKS

Clone it into the folder where you keep your projects. This guide uses `~/Projects`. If yours is different, use your own path everywhere below.

```bash
mkdir -p ~/Projects
git clone https://github.com/genceumut/naks ~/Projects/naks
```

**Optional: make `naks-dev` available everywhere.** Without this step you run it with its full path (`~/Projects/naks/bin/naks-dev`). With it, you just type `naks-dev`:

```bash
echo 'export PATH="$HOME/Projects/naks/bin:$PATH"' >> ~/.zshrc   # use ~/.bashrc if you use bash
source ~/.zshrc
naks-dev        # should print: Usage: naks-dev <command> [args] ...
```

## 3. Try the demo

```bash
cd ~/Projects/naks
python3 examples/demo.py
```

You should see `2 request(s) queued in .naks/requests/`. NAKS saved two questions and is waiting for answers. Steps 4 and 5 set up the two ways to answer them.

## 4. Install the Claude skills

*Needed for chat mode.* In chat mode you answer waiting questions by typing `/naks` in a Claude chat. For that, Claude needs the `/naks` skill and access to your projects folder.

**a. Install the Claude desktop app** from [claude.ai/download](https://claude.ai/download) and sign in.

**b. Give Claude your projects folder.** In a chat in the desktop app, choose **Add folder** from the **+** menu and pick `~/Projects`. You can also skip this step: the first time you run `/naks`, Claude asks for access to the folder.

**c. Fill in the skill templates.** Open `skill/naks/SKILL.md` and `skill/naksify/SKILL.md`. At the top of each, set:
- `PROJECTS`: your projects folder (`~/Projects`)
- `GITHUB_OWNER`: your GitHub username (only used for `/naks github …`)
- `NAKS_HOME`: where NAKS is (`~/Projects/naks`, only in naksify)

**d. Package each skill as a ZIP.** Claude expects the skill's folder at the top level of the ZIP:

```bash
cd ~/Projects/naks/skill
zip -r naks.zip naks
zip -r naksify.zip naksify
```

**e. Upload them.** In Claude, go to **Customize → Skills**, click **+**, then **Create skill → Upload**, and choose `naks.zip`. Repeat for `naksify.zip`. Make sure both are switched on.

**f. Answer the demo.** In a Claude desktop chat, type:

```
/naks naks
```

Claude finds the two waiting questions, answers them and writes the answer files. Then:

```bash
python3 examples/demo.py   # now prints the title and tags
```

Run it again: the answers come from disk instantly, and no model is called.

## 5. Set up Claude Code

*Needed for cli mode.* In cli mode, NAKS answers questions right away by running Claude Code (`claude -p`) on your machine.

**a. Install Claude Code:**

```bash
curl -fsSL https://claude.ai/install.sh | bash
# or, with Homebrew:  brew install --cask claude-code
```

Open a new terminal and check it: `claude --version`.

**b. Log in with your Claude account.** Run `claude` once and choose to sign in with your Claude subscription, not an API key. Then exit with `/exit`.

**c. Test it through NAKS:**

```bash
cd ~/Projects/naks
NAKS_MODE=cli python3 -c "import sys; sys.path.insert(0, 'python'); from naks_client import ask; print(ask('Say hello in exactly 3 words', task='hello'))"
```

You should get a three-word answer after a few seconds. Run it again and the answer comes from disk immediately. NAKS counts the calls in `.naks/cli-usage.json` (default limit 20 per day; change it with `NAKS_CLI_DAILY_LIMIT`).

> NAKS removes `ANTHROPIC_API_KEY` from Claude Code's environment, so cli mode can't bill your API account by accident even if the key is set in your shell.

## 6. Connect your first project

First check whether the project calls an LLM through the official SDKs:

```bash
cd ~/Projects/your-project
grep -rn --include='*.py' --include='*.ts' --include='*.js' -E 'anthropic|openai' . --exclude-dir=node_modules | head
```

**If it uses `anthropic` / `@anthropic-ai/sdk` / `openai`: no code changes needed.** Run your usual command through `naks-dev`:

```bash
naks-dev npm run dev                        # chat mode
NAKS_MODE=cli naks-dev python3 main.py      # cli mode
```

In chat mode the SDK call stays open while it waits. Type `/naks your-project` in Claude and the call returns with the answer. If nobody answers within 9 minutes, the call fails with HTTP 424 and the question stays queued for later.

Add these lines to the project's `.gitignore`:

```
.naks/cli-usage.json
.naks/cli-log.jsonl
.naks/*.tmp
```

**If it uses something else (a custom HTTP client, LangChain, …), or you're writing new code:** copy `python/naks_client.py` or `js/naks-client.mjs` into the project and call `ask()`. See the [README](README.md#option-2-call-naks-from-code-ask). Or type `/naksify your-project` in Claude and let it do the conversion on a copy.

**In production**, set `NAKS_MODE=api` (with `ANTHROPIC_API_KEY`) when you use `ask()`, or don't use `naks-dev` at all when you use an SDK.

## 7. Troubleshooting

| Problem | Fix |
|---|---|
| `naks-dev: command not found` | Do the optional PATH step in [2](#2-get-naks), or use the full path `~/Projects/naks/bin/naks-dev`. |
| `NaksPending: … request(s) waiting` | This is expected in chat mode. Type `/naks <project>` in Claude, then run again. |
| `/naks` says nothing is pending | Check that Claude has access to the right folder and that `PROJECTS` in the skill matches it. The questions are in `<project>/.naks/requests/`. |
| `[naks] cli unavailable (claude not found …)` | Install Claude Code ([5](#5-set-up-claude-code)) and open a new terminal. |
| `[naks] cli unavailable (daily cap reached …)` | The day's limit is used up, so the question was queued for `/naks`. Raise `NAKS_CLI_DAILY_LIMIT` if you need to. |
| `[naks] cli unavailable (claude -p failed: …)` | Run `claude` once and make sure you're logged in with your Claude account. |
| `Address already in use` / port 4141 busy | Another `naks serve` is running (`naks-dev` reuses it), or set `NAKS_PORT=4142`. |
| HTTP 424 from the SDK | Chat mode waited too long for `/naks`. The question is still queued: answer it and rerun. Raise `NAKS_SERVE_WAIT` for longer waits. |
| The SDK still calls the real API | The project hard-codes `base_url` / `baseURL`. Remove it, or use `ask()` / `/naksify`. |
| `HTTP 400 … tool loops with multiple tools are not supported` | The project runs a real multi-tool agent loop. That isn't supported. Use `record` mode for that part. |

## 8. Uninstall

```bash
rm -rf ~/Projects/naks
# remove the PATH line from ~/.zshrc (or ~/.bashrc) if you added it
# delete the .naks/ folders in your projects if you don't want the saved answers
```

Remove the skills in Claude under **Customize → Skills**.
