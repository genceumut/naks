// NAKS — NoAPIKeySystem, JavaScript/TypeScript client (single file, no dependencies, Node 18+).
//
// Answers your app's AI calls from your Claude subscription during development instead of paid API tokens.
//
//   import { ask } from "./naks-client.mjs";
//   const title = await ask("Suggest a short title for this note: ...", { task: "note-title" });
//   const tags  = await ask("Extract tags: ...", { schema: { type: "array", items: { type: "string" } } });
//
// Modes and env vars are the same as the Python client (see the naks_client.py docstring):
//   NAKS_MODE = chat (default) | cli | record | replay | api
// The same request produces the same id in Python and JS, so the cache is shared.

import { createHash } from "node:crypto";
import { spawnSync } from "node:child_process";
import { appendFileSync, existsSync, mkdirSync, mkdtempSync, readFileSync, readdirSync, renameSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { basename, delimiter, dirname, extname, isAbsolute, join, relative, resolve } from "node:path";

export const PROTOCOL_VERSION = 1;
export const MODES = ["chat", "cli", "record", "replay", "api"];

const MEDIA = { ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".gif": "image/gif", ".webp": "image/webp", ".pdf": "application/pdf" };

export class NaksPending extends Error {
  constructor(ids, naksDir) {
    super(`NAKS: ${ids.length} request(s) waiting for an answer (${ids.join(", ")}). ` +
          `Run /naks in a Claude chat, then run again. Folder: ${naksDir}`);
    this.name = "NaksPending";
    this.ids = ids;
    this.naksDir = naksDir;
  }
}

export class NaksMissing extends Error {
  constructor(id, naksDir) {
    super(`NAKS replay: no saved answer for '${id}' (${join(naksDir, "responses")}).`);
    this.name = "NaksMissing";
    this.id = id;
    this.naksDir = naksDir;
  }
}

const env = (k, d) => (process.env[k] === undefined || process.env[k] === "" ? d : process.env[k]);
const warn = (m) => console.error(`[naks] ${m}`);
const now = () => new Date().toISOString().replace(/\.\d{3}Z$/, "+00:00");
const today = () => new Date().toISOString().slice(0, 10);

function mode() {
  const m = (env("NAKS_MODE", "chat")).trim().toLowerCase();
  if (!MODES.includes(m)) throw new Error(`Unknown NAKS_MODE: ${m}. Options: ${MODES.join(", ")}`);
  return m;
}

// ------------------------------------------------------------------------- paths

function findRoot(start) {
  let p = resolve(start);
  while (true) {
    if (existsSync(join(p, ".naks")) || existsSync(join(p, ".git"))) return p;
    const parent = dirname(p);
    if (parent === p) return resolve(start);
    p = parent;
  }
}

function naksDir() {
  const d = process.env.NAKS_DIR ? resolve(process.env.NAKS_DIR) : join(findRoot(process.cwd()), ".naks");
  mkdirSync(join(d, "requests"), { recursive: true });
  mkdirSync(join(d, "responses"), { recursive: true });
  return d;
}

// ------------------------------------------------------------------------- request ids

// Same output as Python's json.dumps(sort_keys=True, ensure_ascii=False), so ids match.
function canonical(v) {
  if (v === null || v === undefined) return "null";
  if (Array.isArray(v)) return "[" + v.map(canonical).join(", ") + "]";
  if (typeof v === "object") {
    return "{" + Object.keys(v).sort().map((k) => JSON.stringify(k) + ": " + canonical(v[k])).join(", ") + "}";
  }
  return JSON.stringify(v);
}

function requestId(task, body) {
  const h = createHash("sha256").update(canonical(body), "utf8").digest("hex").slice(0, 12);
  const tr = { ç: "c", Ç: "C", ğ: "g", Ğ: "G", ı: "i", İ: "I", ö: "o", Ö: "O", ş: "s", Ş: "S", ü: "u", Ü: "U" };
  const t = (task || "task").replace(/[çÇğĞıİöÖşŞüÜ]/g, (c) => tr[c]).toLowerCase();
  const slug = t.replace(/[^a-z0-9-]/g, "-").slice(0, 40).replace(/^-+|-+$/g, ""); // keep file names ASCII (Turkish letters transliterated)
  return `${slug || "task"}-${h}`;
}

// Attachments are recorded as project-relative path + content hash (changing the file changes the id).
function fileEntries(files, d) {
  const root = dirname(resolve(d));
  return files.map((f) => {
    const p = resolve(f);
    if (!existsSync(p)) throw new Error(`NAKS attachment not found: ${f}`);
    const rel = relative(root, p);
    const path = rel.startsWith("..") || isAbsolute(rel) ? p : rel.split("\\").join("/");
    return { path, sha256: createHash("sha256").update(readFileSync(p)).digest("hex").slice(0, 16) };
  });
}

function build(d, prompt, { system = null, schema = null, inputs = null, format = null, files = null } = {}) {
  const body = {
    system,
    prompt,
    inputs,
    output: { format: format || (schema != null ? "json" : "text"), schema },
  };
  if (files && files.length) body.files = fileEntries(files, d);
  return body;
}

function writeJson(path, data) {
  const tmp = path.replace(/\.json$/, ".tmp");
  writeFileSync(tmp, JSON.stringify(data, null, 2), "utf8");
  renameSync(tmp, path);
}

function saveResponse(d, id, output, answeredBy) {
  writeJson(join(d, "responses", `${id}.json`), { naks: PROTOCOL_VERSION, id, answered_at: now(), answered_by: answeredBy, output });
}

function cached(d, id) {
  const res = join(d, "responses", `${id}.json`);
  if (!existsSync(res)) return [false, null];
  const data = JSON.parse(readFileSync(res, "utf8"));
  if (data.error) throw new Error(`NAKS request ${id} could not be answered: ${data.error}`);
  return [true, data.output];
}

function writeRequest(d, id, task, body) {
  const req = join(d, "requests", `${id}.json`);
  if (!existsSync(req)) {
    writeJson(req, { naks: PROTOCOL_VERSION, id, project: basename(dirname(d)), task, created_at: now(), ...body });
  }
}

// ------------------------------------------------------------------------- public API

/** Write the request (once) and return its id. Never waits or throws. */
export function submit(prompt, opts = {}) {
  const d = naksDir();
  const task = opts.task || "task";
  const body = build(d, prompt, opts);
  const id = requestId(task, body);
  writeRequest(d, id, task, body);
  return id;
}

/** Return the answer; throw NaksPending if there is none yet. */
export function get(id) {
  const d = naksDir();
  const [ok, out] = cached(d, id);
  if (!ok) throw new NaksPending([id], d);
  return out;
}

/** Ids of requests that have no answer yet. */
export function pending() {
  const d = naksDir();
  const stems = (sub) => readdirSync(join(d, sub)).filter((f) => f.endsWith(".json")).map((f) => f.slice(0, -5));
  const done = new Set(stems("responses"));
  return stems("requests").filter((id) => !done.has(id)).sort();
}

/**
 * Answer the question according to NAKS_MODE.
 * opts: { system, schema, inputs, task, format, files, wait }  — files: image (png/jpg/gif/webp) or PDF paths
 */
export async function ask(prompt, opts = {}) {
  const m = mode();
  if (m === "api") return callApi(prompt, opts);

  const d = naksDir();
  const task = opts.task || "task";
  const body = build(d, prompt, opts);
  const id = requestId(task, body);
  let [ok, out] = cached(d, id);
  if (ok) return out;

  if (m === "replay") throw new NaksMissing(id, d);

  if (m === "record") {
    out = await callApi(prompt, opts);
    saveResponse(d, id, out, "api:" + env("NAKS_MODEL", "claude-sonnet-5-5"));
    return out;
  }

  if (m === "cli") {
    let reason = cliUnavailable(d, opts.files);
    if (reason === null) {
      try {
        out = callCli(d, id, body);
        saveResponse(d, id, out, "claude-cli");
        return out;
      } catch (e) {
        reason = `claude -p failed: ${e.message}`;
      }
    }
    warn(`cli unavailable (${reason}); request queued for /naks.`);
  }

  // chat (and cli fallback)
  writeRequest(d, id, task, body);
  const wait = opts.wait ?? Number(env("NAKS_WAIT", 0));
  const deadline = Date.now() + wait * 1000;
  while (true) {
    [ok, out] = cached(d, id);
    if (ok) return out;
    if (Date.now() >= deadline) throw new NaksPending([id], d);
    await new Promise((r) => setTimeout(r, 2000));
  }
}

// ------------------------------------------------------------------------- cli mode (claude -p)

function which(cmd) {
  return (process.env.PATH || "").split(delimiter).some((p) => p && existsSync(join(p, cmd)));
}

function readUsage(d) {
  try { return JSON.parse(readFileSync(join(d, "cli-usage.json"), "utf8")); } catch { return {}; }
}

function cliUnavailable(d, files) {
  if (files && files.length) return "request has attachments";
  if (!which("claude")) return "claude not found (Claude Code not installed)";
  const limit = Number(env("NAKS_CLI_DAILY_LIMIT", 20));
  if ((readUsage(d)[today()] || 0) >= limit) return `daily cap reached (${limit})`;
  return null;
}

function cliCount(d) {
  const usage = readUsage(d);
  writeJson(join(d, "cli-usage.json"), { [today()]: (usage[today()] || 0) + 1 });
}

function userText(prompt, inputs) {
  let text = prompt;
  if (inputs != null) text += "\n\n<inputs>\n" + JSON.stringify(inputs, null, 2) + "\n</inputs>";
  return text;
}

function parseJsonText(text) {
  const m = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  return JSON.parse((m ? m[1] : text).trim());
}

function typeOk(value, schema) {
  const t = schema && typeof schema === "object" ? schema.type : undefined;
  if (t === "object") return value !== null && typeof value === "object" && !Array.isArray(value);
  if (t === "array") return Array.isArray(value);
  if (t === "string") return typeof value === "string";
  if (t === "boolean") return typeof value === "boolean";
  if (t === "null") return value === null;
  if (t === "number" || t === "integer") return typeof value === "number";
  return true;
}

function callCli(d, id, body) {
  const { schema, format } = body.output;
  const asJson = format === "json";
  let text = userText(body.prompt, body.inputs);
  if (asJson && schema == null) text += "\n\nReturn only valid JSON, nothing else.";
  const args = ["-p", "--output-format", "json", "--tools", "", "--no-session-persistence", "--strict-mcp-config",
                "--system-prompt", body.system || "You are a helpful assistant."];
  if (schema != null) args.push("--json-schema", JSON.stringify(schema));
  if (process.env.NAKS_CLI_MODEL) args.push("--model", process.env.NAKS_CLI_MODEL);
  // Use the subscription: if an API key is in the env, claude could use it and bill the API instead.
  const childEnv = { ...process.env };
  delete childEnv.ANTHROPIC_API_KEY;
  delete childEnv.ANTHROPIC_AUTH_TOKEN;
  const timeout = Number(env("NAKS_CLI_TIMEOUT", 180)) * 1000;

  let lastErr = null;
  for (let attempt = 0; attempt < 2; attempt++) { // retry once
    cliCount(d);
    const cwd = mkdtempSync(join(tmpdir(), "naks-cli-")); // empty dir: nothing to read
    const t0 = Date.now();
    const proc = spawnSync("claude", args, { input: text, encoding: "utf8", cwd, env: childEnv, timeout });
    rmSync(cwd, { recursive: true, force: true });
    appendFileSync(join(d, "cli-log.jsonl"),
      JSON.stringify({ at: now(), id, exit: proc.status, seconds: Math.round((Date.now() - t0) / 100) / 10 }) + "\n");
    let data;
    try { data = JSON.parse(proc.stdout); } catch {
      lastErr = (proc.stderr || proc.stdout || `exit code ${proc.status}`).trim().slice(0, 300);
      continue;
    }
    if (data.is_error || proc.status !== 0) {
      lastErr = String(data.result || data.error || `exit code ${proc.status}`).slice(0, 300);
      continue;
    }
    if (!asJson) return String(data.result ?? "").trim();
    let value;
    try {
      value = data.structured_output != null ? data.structured_output : parseJsonText(String(data.result ?? ""));
    } catch (e) {
      lastErr = `could not parse JSON: ${e.message}`;
      continue;
    }
    if (schema == null || typeOk(value, schema)) return value;
    lastErr = "answer does not match the schema";
  }
  throw new Error(lastErr || "unknown error");
}

// ------------------------------------------------------------------------- api mode

function fileBlock(f) {
  const media = MEDIA[extname(f).toLowerCase()];
  if (!media) throw new Error(`Unsupported attachment type: ${basename(f)}`);
  const source = { type: "base64", media_type: media, data: readFileSync(f).toString("base64") };
  return { type: media === "application/pdf" ? "document" : "image", source };
}

async function callApi(prompt, { system = null, schema = null, inputs = null, format = null, files = null } = {}) {
  const key = process.env.ANTHROPIC_API_KEY;
  if (!key) throw new Error("NAKS_MODE=api/record needs ANTHROPIC_API_KEY.");
  let text = userText(prompt, inputs);
  if (schema != null) text += "\n\nReturn only valid JSON matching this schema, nothing else:\n" + JSON.stringify(schema);
  const payload = {
    model: env("NAKS_MODEL", "claude-sonnet-5-5"),
    max_tokens: Number(env("NAKS_MAX_TOKENS", 4096)),
    messages: [{ role: "user", content: [...(files || []).map(fileBlock), { type: "text", text }] }],
    ...(system ? { system } : {}),
  };
  const r = await fetch(env("NAKS_API_URL", "https://api.anthropic.com/v1/messages"), {
    method: "POST",
    headers: { "x-api-key": key, "anthropic-version": "2023-06-01", "content-type": "application/json" },
    body: JSON.stringify(payload),
  });
  if (!r.ok) throw new Error(`Anthropic API ${r.status}: ${await r.text()}`);
  const out = await r.json();
  const result = out.content.filter((b) => b.type === "text").map((b) => b.text).join("").trim();
  if (schema != null || format === "json") return parseJsonText(result);
  return result;
}
