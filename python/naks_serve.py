"""
naks serve — local OpenAI- and Anthropic-compatible endpoint (Python 3.9+, no dependencies).

Your project keeps using its own SDK; you only point the base URL here.
Requests go to NAKS and are answered according to NAKS_MODE (chat, cli, record, replay, api).

    cd your-project
    NAKS_MODE=cli python3 /path/to/naks/python/naks_serve.py        # default port 4141

In your project:
    OpenAI SDK:     base_url = "http://127.0.0.1:4141/v1",  api_key = "naks"
    Anthropic SDK:  base_url = "http://127.0.0.1:4141",     api_key = "naks"
    (or env vars: OPENAI_BASE_URL / ANTHROPIC_BASE_URL — bin/naks-dev sets these for you)

Supported: /v1/chat/completions, /v1/messages, /v1/models, streaming (the full answer is streamed as
one chunk), base64 images, JSON schema (response_format / output_format) and structured output via a
single tool. Real multi-step tool loops, embeddings and audio are not supported.

Env vars: NAKS_PORT (4141), NAKS_SERVE_WAIT (seconds to hold a request open in chat mode, 540 —
shorter than SDK timeouts), plus all naks_client variables.
Send an X-NAKS-Task header to name a request (the name shows up in the cache file name).
"""

from __future__ import annotations

import base64
import binascii
import hashlib
import json
import os
import sys
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import naks_client as naks  # noqa: E402

CONVERSATION_PROMPT = "Reply as the assistant to the last user message in the conversation below."
EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/gif": ".gif", "image/webp": ".webp",
       "application/pdf": ".pdf"}


class Unsupported(Exception):
    pass


# --------------------------------------------------------------------------- helpers

def _save_attachment(media_type: str, b64: str) -> str:
    """Write a base64 attachment under .naks/files/ and return its path (content hash is the file name)."""
    try:
        raw = base64.b64decode(b64)
    except (binascii.Error, ValueError) as e:
        raise Unsupported(f"could not decode base64 attachment: {e}")
    ext = EXT.get(media_type)
    if not ext:
        raise Unsupported(f"unsupported attachment type: {media_type}")
    d = naks._naks_dir() / "files"
    d.mkdir(exist_ok=True)
    p = d / (hashlib.sha256(raw).hexdigest()[:16] + ext)
    if not p.exists():
        p.write_bytes(raw)
    return str(p)


def _to_ask(system: str | None, turns: list[dict], files: list[str]) -> dict:
    """Turn a conversation into a NAKS request: single user message → prompt; multi-turn → inputs.messages."""
    if len(turns) == 1 and turns[0]["role"] == "user":
        return {"prompt": turns[0]["content"], "system": system, "inputs": None, "files": files or None}
    return {"prompt": CONVERSATION_PROMPT, "system": system, "inputs": {"messages": turns}, "files": files or None}


def _pick_tool(tools: list[dict], choice: Any, name_of, forced_name) -> dict | None:
    """Find the single tool used for structured output; None if there isn't one."""
    if not tools:
        return None
    forced = forced_name(choice)
    if forced:
        for t in tools:
            if name_of(t) == forced:
                return t
    if len(tools) == 1:
        return tools[0]
    return None


# --------------------------------------------------------------------------- OpenAI

def _openai_text(content: Any, files: list[str]) -> str:
    if isinstance(content, str) or content is None:
        return content or ""
    parts = []
    for part in content:
        kind = part.get("type")
        if kind == "text":
            parts.append(part.get("text", ""))
        elif kind == "image_url":
            url = (part.get("image_url") or {}).get("url", "")
            if url.startswith("data:") and ";base64," in url:
                head, b64 = url[5:].split(";base64,", 1)
                files.append(_save_attachment(head, b64))
            else:
                parts.append(f"[image: {url}]")
        else:
            raise Unsupported(f"unsupported content type: {kind}")
    return "\n".join(p for p in parts if p)


def openai_request(body: dict) -> tuple[dict, dict | None]:
    files: list[str] = []
    system_parts, turns = [], []
    for m in body.get("messages", []):
        role = m.get("role")
        text = _openai_text(m.get("content"), files)
        if role in ("system", "developer"):
            system_parts.append(text)
        elif role == "tool":
            turns.append({"role": "user", "content": f"[tool result]\n{text}"})
        else:
            if m.get("tool_calls"):
                calls = [f"[tool call {c['function']['name']}: {c['function']['arguments']}]" for c in m["tool_calls"]]
                text = "\n".join([text, *calls]).strip()
            turns.append({"role": role, "content": text})
    req = _to_ask("\n\n".join(system_parts) or None, turns, files)

    rf = body.get("response_format") or {}
    if rf.get("type") == "json_schema":
        req["schema"] = (rf.get("json_schema") or {}).get("schema", {})
    elif rf.get("type") == "json_object":
        req["format"] = "json"

    tool = _pick_tool(body.get("tools") or [], body.get("tool_choice"),
                      lambda t: (t.get("function") or {}).get("name"),
                      lambda c: (c.get("function") or {}).get("name") if isinstance(c, dict) else None)
    if body.get("tools") and tool is None:
        raise Unsupported("real tool loops with multiple tools are not supported")
    if tool:
        req["schema"] = (tool.get("function") or {}).get("parameters") or {"type": "object"}
    return req, tool


def openai_response(body: dict, rid: str, output: Any, tool: dict | None) -> dict:
    msg: dict[str, Any] = {"role": "assistant", "content": None}
    finish = "stop"
    if tool:
        name = tool["function"]["name"]
        msg["tool_calls"] = [{"id": f"call_{rid}", "type": "function",
                              "function": {"name": name, "arguments": json.dumps(output, ensure_ascii=False)}}]
        finish = "tool_calls"
    else:
        msg["content"] = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
    return {"id": f"chatcmpl-naks-{rid}", "object": "chat.completion", "created": int(time.time()),
            "model": body.get("model", "naks"),
            "choices": [{"index": 0, "message": msg, "finish_reason": finish}],
            "usage": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}}


def openai_stream(resp: dict) -> list[str]:
    base = {k: resp[k] for k in ("id", "created", "model")} | {"object": "chat.completion.chunk"}
    msg = resp["choices"][0]["message"]
    delta: dict[str, Any] = {"role": "assistant"}
    if msg.get("tool_calls"):
        delta["tool_calls"] = [dict(c, index=0) for c in msg["tool_calls"]]
    else:
        delta["content"] = msg["content"]
    chunks = [
        base | {"choices": [{"index": 0, "delta": delta, "finish_reason": None}]},
        base | {"choices": [{"index": 0, "delta": {}, "finish_reason": resp["choices"][0]["finish_reason"]}],
                "usage": resp["usage"]},
    ]
    return [f"data: {json.dumps(c, ensure_ascii=False)}\n\n" for c in chunks] + ["data: [DONE]\n\n"]


def openai_error(status: int, message: str) -> dict:
    return {"error": {"message": message, "type": "naks_error", "code": status}}


# --------------------------------------------------------------------------- Anthropic

def _anthropic_text(content: Any, files: list[str]) -> str:
    if isinstance(content, str) or content is None:
        return content or ""
    parts = []
    for block in content:
        kind = block.get("type")
        if kind == "text":
            parts.append(block.get("text", ""))
        elif kind in ("image", "document"):
            src = block.get("source") or {}
            if src.get("type") == "base64":
                files.append(_save_attachment(src.get("media_type", ""), src.get("data", "")))
            elif src.get("type") == "text":
                parts.append(src.get("data", ""))
            else:
                parts.append(f"[{kind}: {src.get('url', src.get('type'))}]")
        elif kind == "tool_use":
            parts.append(f"[tool call {block.get('name')}: {json.dumps(block.get('input'), ensure_ascii=False)}]")
        elif kind == "tool_result":
            inner = block.get("content")
            parts.append("[tool result]\n" + (_anthropic_text(inner, files) if inner is not None else ""))
        elif kind in ("thinking", "redacted_thinking"):
            continue
        else:
            raise Unsupported(f"unsupported content type: {kind}")
    return "\n".join(p for p in parts if p)


def anthropic_request(body: dict) -> tuple[dict, dict | None]:
    files: list[str] = []
    system = body.get("system")
    if isinstance(system, list):
        system = "\n\n".join(b.get("text", "") for b in system if b.get("type") == "text")
    turns = [{"role": m.get("role"), "content": _anthropic_text(m.get("content"), files)}
             for m in body.get("messages", [])]
    req = _to_ask(system or None, turns, files)

    fmt = body.get("output_format") or (body.get("output_config") or {}).get("format") or {}
    if fmt.get("type") == "json_schema":
        req["schema"] = fmt.get("schema", {})

    tool = _pick_tool(body.get("tools") or [], body.get("tool_choice"),
                      lambda t: t.get("name"),
                      lambda c: c.get("name") if isinstance(c, dict) and c.get("type") == "tool" else None)
    if body.get("tools") and tool is None:
        raise Unsupported("real tool loops with multiple tools are not supported")
    if tool:
        req["schema"] = tool.get("input_schema") or {"type": "object"}
    return req, tool


def anthropic_response(body: dict, rid: str, output: Any, tool: dict | None) -> dict:
    if tool:
        content = [{"type": "tool_use", "id": f"toolu_naks_{rid}", "name": tool["name"], "input": output}]
        stop = "tool_use"
    else:
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        content = [{"type": "text", "text": text}]
        stop = "end_turn"
    return {"id": f"msg_naks_{rid}", "type": "message", "role": "assistant", "model": body.get("model", "naks"),
            "content": content, "stop_reason": stop, "stop_sequence": None,
            "usage": {"input_tokens": 0, "output_tokens": 0}}


def anthropic_stream(resp: dict) -> list[str]:
    def ev(name: str, data: dict) -> str:
        return f"event: {name}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

    start = dict(resp, content=[], stop_reason=None)
    out = [ev("message_start", {"type": "message_start", "message": start})]
    block = resp["content"][0]
    if block["type"] == "tool_use":
        out.append(ev("content_block_start", {"type": "content_block_start", "index": 0,
                                              "content_block": dict(block, input={})}))
        out.append(ev("content_block_delta", {"type": "content_block_delta", "index": 0, "delta": {
            "type": "input_json_delta", "partial_json": json.dumps(block["input"], ensure_ascii=False)}}))
    else:
        out.append(ev("content_block_start", {"type": "content_block_start", "index": 0,
                                              "content_block": {"type": "text", "text": ""}}))
        out.append(ev("content_block_delta", {"type": "content_block_delta", "index": 0,
                                              "delta": {"type": "text_delta", "text": block["text"]}}))
    out.append(ev("content_block_stop", {"type": "content_block_stop", "index": 0}))
    out.append(ev("message_delta", {"type": "message_delta",
                                    "delta": {"stop_reason": resp["stop_reason"], "stop_sequence": None},
                                    "usage": {"output_tokens": 0}}))
    out.append(ev("message_stop", {"type": "message_stop"}))
    return out


def anthropic_error(status: int, message: str) -> dict:
    return {"type": "error", "error": {"type": "naks_error", "message": message}}


# --------------------------------------------------------------------------- server

ROUTES = {
    "/v1/chat/completions": (openai_request, openai_response, openai_stream, openai_error, "openai"),
    "/v1/messages": (anthropic_request, anthropic_response, anthropic_stream, anthropic_error, "anthropic"),
}


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, fmt, *args):  # quiet; we print our own log lines
        pass

    def _send(self, status: int, payload: Any = None, sse: list[str] | None = None) -> None:
        data = "".join(sse).encode() if sse is not None else json.dumps(payload, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "text/event-stream" if sse is not None else "application/json")
        self.send_header("content-length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        path = self.path.split("?")[0].rstrip("/")
        if path in ("/v1/models", "/models"):
            return self._send(200, {"object": "list", "data": [{"id": "naks", "object": "model", "owned_by": "naks",
                                                                 "type": "model", "display_name": "NAKS"}]})
        if path in ("", "/health"):
            return self._send(200, {"naks": "ok", "mode": naks._mode()})
        self._send(404, {"error": {"message": f"unknown path: {path}"}})

    def do_POST(self):
        path = self.path.split("?")[0].rstrip("/")
        if path == "/chat/completions":
            path = "/v1/chat/completions"
        if path == "/v1/messages/count_tokens":
            return self._send(200, {"input_tokens": 0})
        if path not in ROUTES:
            return self._send(404, {"error": {"message": f"unknown path: {path}"}})
        to_req, to_resp, to_stream, to_err, kind = ROUTES[path]
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length", 0))) or b"{}")
        except ValueError:
            return self._send(400, to_err(400, "invalid JSON"))

        task = self.headers.get("x-naks-task") or f"serve-{kind}"
        try:
            req, tool = to_req(body)
            rid, _ = naks._build(naks._naks_dir(), req["prompt"], req["system"], req.get("schema"),
                                 req["inputs"], task, req.get("format"), req["files"])
            wait = float(os.environ.get("NAKS_SERVE_WAIT", "540"))
            if naks._mode() in ("chat", "cli") and not naks._cached(naks._naks_dir(), rid)[0]:
                note = "answering via claude -p" if naks._mode() == "cli" else "waiting: run /naks in a Claude chat"
                print(f"[naks] {rid} {note}", file=sys.stderr, flush=True)
            output = naks.ask(req["prompt"], system=req["system"], schema=req.get("schema"), inputs=req["inputs"],
                              task=task, format=req.get("format"), files=req["files"], wait=wait)
        except Unsupported as e:
            return self._send(400, to_err(400, f"NAKS: {e}"))
        except (naks.NaksPending, naks.NaksMissing) as e:
            # 424: SDKs don't auto-retry it (they retry 5xx, which would multiply the wait)
            return self._send(424, to_err(424, str(e)))
        except Exception as e:  # noqa: BLE001
            return self._send(500, to_err(500, f"NAKS: {type(e).__name__}: {e}"))

        resp = to_resp(body, rid, output, tool)
        if body.get("stream"):
            return self._send(200, sse=to_stream(resp))
        self._send(200, resp)


def main() -> None:
    port = int(os.environ.get("NAKS_PORT", sys.argv[1] if len(sys.argv) > 1 else "4141"))
    d = naks._naks_dir()
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"[naks] serve: http://127.0.0.1:{port}  mode={naks._mode()}  dir={d}", file=sys.stderr, flush=True)
    print(f"[naks] OpenAI: base_url=http://127.0.0.1:{port}/v1   Anthropic: base_url=http://127.0.0.1:{port}"
          f"   api_key=naks", file=sys.stderr, flush=True)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
