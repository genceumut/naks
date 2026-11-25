"""
NAKS — NoAPIKeySystem, Python client (single file, no dependencies).

Answers your app's AI calls from your Claude subscription during development instead of paid API tokens.

    from naks_client import ask

    title = ask("Suggest a short title for this note: ...", task="note-title")
    tags  = ask("Extract tags: ...", schema={"type": "array", "items": {"type": "string"}})
    desc  = ask("Describe this page.", files=["pages/p1.png"])   # image / PDF attachment

Modes (env var NAKS_MODE). Every mode except api checks the cache first:
    chat    (default) on a miss, writes the request to .naks/requests/; you answer it with /naks in a Claude chat
    cli     on a miss, answers immediately via `claude -p` (your subscription). Falls back to chat when the
            daily cap is reached, the request has attachments, or claude is unavailable/fails
    record  on a miss, calls the real API and saves the answer (pay once)
    replay  only uses saved answers; raises NaksMissing on a miss (tests / CI)
    api     calls the real API directly, no cache (production)

Other environment variables:
    NAKS_DIR               location of the .naks folder (default: nearest parent with .git or .naks)
    NAKS_WAIT              seconds to poll for an answer in chat mode (default 0)
    NAKS_MODEL             model for api/record modes (default claude-sonnet-5-5)
    NAKS_CLI_DAILY_LIMIT   max claude -p calls per day in cli mode (default 20)
    NAKS_CLI_TIMEOUT       seconds per claude -p call (default 180)
    NAKS_CLI_MODEL         model for cli mode (default: Claude Code's default)

Command line:
    python3 naks_client.py            lists pending requests
    python3 naks_serve.py             local OpenAI/Anthropic-compatible endpoint (separate file)
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable

PROTOCOL_VERSION = 1
MODES = ("chat", "cli", "record", "replay", "api")
__all__ = ["ask", "submit", "get", "pending", "NaksPending", "NaksMissing"]

_MEDIA = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
          ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf"}


class NaksPending(Exception):
    """No answer yet. Run /naks in a Claude chat, then run your code again."""

    def __init__(self, ids: list[str], naks_dir: Path):
        self.ids = ids
        self.naks_dir = naks_dir
        super().__init__(
            f"NAKS: {len(ids)} request(s) waiting for an answer ({', '.join(ids)}). "
            f"Run /naks in a Claude chat, then run again. Folder: {naks_dir}"
        )


class NaksMissing(Exception):
    """No saved answer in replay mode."""

    def __init__(self, rid: str, naks_dir: Path):
        self.id = rid
        self.naks_dir = naks_dir
        super().__init__(f"NAKS replay: no saved answer for '{rid}' ({naks_dir / 'responses'}).")


def _mode() -> str:
    m = os.environ.get("NAKS_MODE", "chat").strip().lower() or "chat"
    if m not in MODES:
        raise ValueError(f"Unknown NAKS_MODE: {m}. Options: {', '.join(MODES)}")
    return m


def _warn(msg: str) -> None:
    print(f"[naks] {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- paths

def _find_root(start: Path) -> Path:
    for p in [start, *start.parents]:
        if (p / ".naks").is_dir() or (p / ".git").exists():
            return p
    return start


def _naks_dir() -> Path:
    env = os.environ.get("NAKS_DIR")
    d = Path(env) if env else _find_root(Path.cwd()) / ".naks"
    (d / "requests").mkdir(parents=True, exist_ok=True)
    (d / "responses").mkdir(parents=True, exist_ok=True)
    return d


def _project_name(d: Path) -> str:
    return d.resolve().parent.name


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# --------------------------------------------------------------------------- request ids

_TR = str.maketrans("çÇğĞıİöÖşŞüÜ", "cCgGiIoOsSuU")  # keep file names ASCII (Turkish letters transliterated)


def _request_id(task: str, body: dict) -> str:
    canonical = json.dumps(body, sort_keys=True, ensure_ascii=False)
    h = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:12]
    t = (task or "task").translate(_TR).lower()
    slug = "".join(c if (c.isascii() and c.isalnum()) or c == "-" else "-" for c in t)[:40].strip("-")
    return f"{slug or 'task'}-{h}"


def _file_entries(files: Iterable[str | Path], d: Path) -> list[dict]:
    """Record attachments as project-relative path + content hash (changing the file changes the id)."""
    root = d.resolve().parent
    out = []
    for f in files:
        p = Path(f).resolve()
        if not p.is_file():
            raise FileNotFoundError(f"NAKS attachment not found: {f}")
        try:
            rel = p.relative_to(root).as_posix()
        except ValueError:
            rel = p.as_posix()
        out.append({"path": rel, "sha256": hashlib.sha256(p.read_bytes()).hexdigest()[:16]})
    return out


def _build(d: Path, prompt: str, system: str | None, schema: Any, inputs: Any,
           task: str, fmt: str | None, files: Iterable[str | Path] | None) -> tuple[str, dict]:
    output_format = fmt or ("json" if schema is not None else "text")
    body: dict[str, Any] = {
        "system": system,
        "prompt": prompt,
        "inputs": inputs,
        "output": {"format": output_format, "schema": schema},
    }
    if files:
        body["files"] = _file_entries(files, d)
    return _request_id(task, body), body


def _write_json(path: Path, data: dict) -> None:
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def _save_response(d: Path, rid: str, output: Any, answered_by: str) -> None:
    _write_json(d / "responses" / f"{rid}.json", {
        "naks": PROTOCOL_VERSION, "id": rid, "answered_at": _now(), "answered_by": answered_by, "output": output,
    })


def _cached(d: Path, rid: str) -> tuple[bool, Any]:
    res = d / "responses" / f"{rid}.json"
    if not res.exists():
        return False, None
    data = json.loads(res.read_text(encoding="utf-8"))
    if data.get("error"):
        raise RuntimeError(f"NAKS request {rid} could not be answered: {data['error']}")
    return True, data.get("output")


# --------------------------------------------------------------------------- public API

def submit(prompt: str, *, system: str | None = None, schema: Any = None, inputs: Any = None,
           task: str = "task", format: str | None = None,
           files: Iterable[str | Path] | None = None) -> str:
    """Write the request (once) and return its id. Never waits or raises."""
    d = _naks_dir()
    rid, body = _build(d, prompt, system, schema, inputs, task, format, files)
    _write_request(d, rid, task, body)
    return rid


def _write_request(d: Path, rid: str, task: str, body: dict) -> None:
    req = d / "requests" / f"{rid}.json"
    if not req.exists():
        _write_json(req, {"naks": PROTOCOL_VERSION, "id": rid, "project": _project_name(d),
                          "task": task, "created_at": _now(), **body})


def get(rid: str) -> Any:
    """Return the answer; raise NaksPending if there is none yet."""
    d = _naks_dir()
    ok, out = _cached(d, rid)
    if not ok:
        raise NaksPending([rid], d)
    return out


def pending() -> list[str]:
    """Ids of requests that have no answer yet."""
    d = _naks_dir()
    done = {p.stem for p in (d / "responses").glob("*.json")}
    return sorted(p.stem for p in (d / "requests").glob("*.json") if p.stem not in done)


def ask(prompt: str, *, system: str | None = None, schema: Any = None, inputs: Any = None,
        task: str = "task", format: str | None = None,
        files: Iterable[str | Path] | None = None, wait: float | None = None) -> Any:
    """
    Answer the question according to NAKS_MODE (see module docstring). With a schema the result is
    parsed JSON; otherwise a str. files: image (png/jpg/gif/webp) or PDF paths.
    """
    files = list(files) if files else None
    mode = _mode()
    if mode == "api":
        return _call_api(prompt, system, schema, inputs, format, files)

    d = _naks_dir()
    rid, body = _build(d, prompt, system, schema, inputs, task, format, files)
    ok, out = _cached(d, rid)
    if ok:
        return out

    if mode == "replay":
        raise NaksMissing(rid, d)

    if mode == "record":
        out = _call_api(prompt, system, schema, inputs, format, files)
        _save_response(d, rid, out, "api:" + os.environ.get("NAKS_MODEL", "claude-sonnet-5-5"))
        return out

    if mode == "cli":
        reason = _cli_unavailable(d, files)
        if reason is None:
            try:
                out = _call_cli(d, rid, body)
                _save_response(d, rid, out, "claude-cli")
                return out
            except Exception as e:  # noqa: BLE001 — any failure falls back to chat
                reason = f"claude -p failed: {e}"
        _warn(f"cli unavailable ({reason}); request queued for /naks.")

    # chat (and cli fallback)
    _write_request(d, rid, task, body)
    wait = float(os.environ.get("NAKS_WAIT", "0")) if wait is None else wait
    deadline = time.monotonic() + wait
    while True:
        ok, out = _cached(d, rid)
        if ok:
            return out
        if time.monotonic() >= deadline:
            raise NaksPending([rid], d)
        time.sleep(2)


# --------------------------------------------------------------------------- cli mode (claude -p)

def _cli_usage_path(d: Path) -> Path:
    return d / "cli-usage.json"


def _cli_unavailable(d: Path, files: list | None) -> str | None:
    if files:
        return "request has attachments"
    if not shutil.which("claude"):
        return "claude not found (Claude Code not installed)"
    limit = int(os.environ.get("NAKS_CLI_DAILY_LIMIT", "20"))
    try:
        usage = json.loads(_cli_usage_path(d).read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        usage = {}
    if usage.get(date.today().isoformat(), 0) >= limit:
        return f"daily cap reached ({limit})"
    return None


def _cli_count(d: Path) -> None:
    p = _cli_usage_path(d)
    try:
        usage = json.loads(p.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        usage = {}
    today = date.today().isoformat()
    usage = {today: usage.get(today, 0) + 1}  # keep only today
    _write_json(p, usage)


def _user_text(prompt: str, inputs: Any) -> str:
    text = prompt
    if inputs is not None:
        text += "\n\n<inputs>\n" + json.dumps(inputs, ensure_ascii=False, indent=2) + "\n</inputs>"
    return text


def _parse_json_text(text: str) -> Any:
    m = re.search(r"```(?:json)?\s*(.*?)```", text, re.S)
    return json.loads((m.group(1) if m else text).strip())


def _type_ok(value: Any, schema: Any) -> bool:
    t = schema.get("type") if isinstance(schema, dict) else None
    py = {"object": dict, "array": list, "string": str, "boolean": bool, "null": type(None)}
    if t in py:
        return isinstance(value, py[t])
    if t in ("number", "integer"):
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    return True


def _call_cli(d: Path, rid: str, body: dict) -> Any:
    schema = body["output"]["schema"]
    as_json = body["output"]["format"] == "json"
    text = _user_text(body["prompt"], body["inputs"])
    if as_json and schema is None:
        text += "\n\nReturn only valid JSON, nothing else."
    cmd = ["claude", "-p", "--output-format", "json", "--tools", "",
           "--no-session-persistence", "--strict-mcp-config",
           "--system-prompt", body["system"] or "You are a helpful assistant."]
    if schema is not None:
        cmd += ["--json-schema", json.dumps(schema, ensure_ascii=False)]
    if os.environ.get("NAKS_CLI_MODEL"):
        cmd += ["--model", os.environ["NAKS_CLI_MODEL"]]
    # Use the subscription: if an API key is in the env, claude could use it and bill the API instead.
    env = {k: v for k, v in os.environ.items() if k not in ("ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN")}
    timeout = float(os.environ.get("NAKS_CLI_TIMEOUT", "180"))

    last_err = None
    for _ in range(2):  # retry once
        _cli_count(d)
        t0 = time.monotonic()
        with tempfile.TemporaryDirectory(prefix="naks-cli-") as cwd:  # empty dir: nothing to read
            proc = subprocess.run(cmd, input=text, capture_output=True, text=True,
                                  cwd=cwd, env=env, timeout=timeout)
        _cli_log(d, rid, proc.returncode, time.monotonic() - t0)
        try:
            data = json.loads(proc.stdout)
        except ValueError:
            last_err = (proc.stderr or proc.stdout or f"exit code {proc.returncode}").strip()[:300]
            continue
        if data.get("is_error") or proc.returncode != 0:
            last_err = str(data.get("result") or data.get("error") or f"exit code {proc.returncode}")[:300]
            continue
        if not as_json:
            return str(data.get("result", "")).strip()
        try:
            value = data["structured_output"] if data.get("structured_output") is not None \
                else _parse_json_text(str(data.get("result", "")))
        except ValueError as e:
            last_err = f"could not parse JSON: {e}"
            continue
        if schema is None or _type_ok(value, schema):
            return value
        last_err = "answer does not match the schema"
    raise RuntimeError(last_err or "unknown error")


def _cli_log(d: Path, rid: str, code: int, secs: float) -> None:
    with open(d / "cli-log.jsonl", "a", encoding="utf-8") as f:
        f.write(json.dumps({"at": _now(), "id": rid, "exit": code, "seconds": round(secs, 1)}) + "\n")


# --------------------------------------------------------------------------- api mode

def _call_api(prompt: str, system: str | None, schema: Any, inputs: Any, fmt: str | None,
              files: list[str | Path] | None) -> Any:
    key = os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise RuntimeError("NAKS_MODE=api/record needs ANTHROPIC_API_KEY.")
    text = _user_text(prompt, inputs)
    if schema is not None:
        text += ("\n\nReturn only valid JSON matching this schema, nothing else:\n"
                 + json.dumps(schema, ensure_ascii=False))
    content: list[dict] = []
    for f in files or []:
        p = Path(f)
        media = _MEDIA.get(p.suffix.lower())
        if not media:
            raise ValueError(f"Unsupported attachment type: {p.name}")
        src = {"type": "base64", "media_type": media, "data": base64.b64encode(p.read_bytes()).decode()}
        content.append({"type": "document" if media == "application/pdf" else "image", "source": src})
    content.append({"type": "text", "text": text})
    payload = {
        "model": os.environ.get("NAKS_MODEL", "claude-sonnet-5-5"),
        "max_tokens": int(os.environ.get("NAKS_MAX_TOKENS", "4096")),
        "messages": [{"role": "user", "content": content}],
    }
    if system:
        payload["system"] = system
    req = urllib.request.Request(
        os.environ.get("NAKS_API_URL", "https://api.anthropic.com/v1/messages"),
        data=json.dumps(payload).encode("utf-8"),
        headers={"x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=300) as r:
        out = json.loads(r.read())
    result = "".join(b.get("text", "") for b in out.get("content", []) if b.get("type") == "text").strip()
    if schema is not None or fmt == "json":
        return _parse_json_text(result)
    return result


if __name__ == "__main__":
    ids = pending()
    print(f"{len(ids)} pending request(s)" + (":" if ids else "."))
    for i in ids:
        print("  -", i)
