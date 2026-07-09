// The bounded ReAct loop, ported to the browser: plan an action, gate it, act,
// observe, repeat until the model answers or the step ceiling is hit. It emits
// one event per transition so the UI can stream the run and the audit can record
// it — the loop itself knows nothing about the DOM or where actions come from
// (a real WebLLM model or a canned script both satisfy the `model.act` seam).

import {
  systemPrompt,
  observationMessage,
  denialMessage,
  repeatMessage,
  finalizeMessage,
  unfinishedWorkMessage,
  toolInFinalMessage,
} from "./prompts.js";
import { withDeadline } from "./util.js";

const MAX_STEPS = 8;
// A single on-device turn should never run this long; if it does the decode has
// stalled, so we abort it and surface the failure rather than hang forever.
const STEP_TIMEOUT_MS = 60_000;
// A weak model can keep emitting non-JSON. Rather than burn every step retrying,
// give up after this many consecutive misses and synthesize an answer instead.
const MAX_PARSE_RETRIES = 3;
// Consecutive steps that add no new information (repeated calls, denials) before
// we stop looping and force a final answer. Small models otherwise loop forever.
const MAX_NO_PROGRESS = 3;

// A stable key for an (action) so repeated calls are detected regardless of the
// order the model happens to emit the argument keys in.
function callKey(tool, args) {
  const sorted = {};
  for (const key of Object.keys(args || {}).sort()) sorted[key] = args[key];
  return `${tool}(${JSON.stringify(sorted)})`;
}

function cleanText(raw) {
  return String(raw ?? "")
    .replace(/```[a-z]*\n?/gi, "")
    .replace(/```/g, "")
    .trim();
}

// Pull a usable final answer out of a synthesis turn: a proper {"final": ...},
// or failing that any prose the model wrote — but never a tool-call blob or a
// leftover action, which would read as gibberish to the user.
function extractFinalText(raw, registry) {
  try {
    const action = parseAction(raw, registry);
    if (action.kind === "final") {
      const text = action.text.trim();
      return text && !looksLikeToolCall(text, registry) ? text : null;
    }
    return null; // a tool action is not an answer
  } catch {
    /* not a valid action — fall back to whatever prose it produced */
  }
  const cleaned = cleanText(raw);
  if (!cleaned || cleaned.startsWith("{") || looksLikeToolCall(cleaned, registry)) return null;
  return cleaned.length >= 8 ? cleaned : null;
}

// Which observation groups actually bear on the goal, so the deterministic
// fallback reports only what's relevant (a "what's on my calendar" question must
// not echo pasta files). An empty set means we couldn't classify the goal, so we
// include everything as a best effort rather than hiding real work.
function relevantTools(goal) {
  const g = String(goal).toLowerCase();
  const set = new Set();
  if (/\b(calendar|schedule|agenda|upcoming|events?|meeting|appointment|today|tomorrow|week|days?)\b/.test(g)) {
    set.add("list_events");
  }
  if (/\b(notes?|remember|remind|reminder|save)\b/.test(g)) set.add("search_notes");
  if (/\b(files?|recipe|read|document|doc|pasta|cook|dinner|meal)\b/.test(g)) {
    set.add("search_files");
    set.add("read_file");
  }
  return set;
}

// The guaranteed floor, reached ONLY when the model never produced a clean
// synthesis. Be honest about that rather than dressing a raw dump up as the
// answer, and scope the gathered observations to what's relevant to the goal.
function deterministicSummary(goal, findings) {
  const isNoise = (text) =>
    !text ||
    /^(No (files|notes|events)\b|Provide a non-empty)/i.test(text) ||
    /^(ValueError|FileNotFoundError|PathEscapeError|Error)\b/.test(text);
  const excerpt = (text) => {
    const t = String(text).trim();
    return t.length > 280 ? `${t.slice(0, 280).trimEnd()}\u2026` : t;
  };

  const relevant = relevantTools(goal);
  const include = (tool) => relevant.size === 0 || relevant.has(tool);

  const calendar = [];
  const notes = [];
  const files = [];
  const saved = [];
  for (const f of findings) {
    if (f.tool === "add_note") {
      const text = String(f.args?.text ?? "").trim();
      if (text) saved.push(text);
      continue;
    }
    const obs = String(f.observation ?? "").trim();
    if (isNoise(obs)) continue;
    if (f.tool === "list_events") {
      if (include("list_events")) calendar.push(excerpt(obs));
    } else if (f.tool === "search_notes") {
      if (include("search_notes")) notes.push(excerpt(obs));
    } else if (include("search_files") || include("read_file")) {
      files.push(excerpt(obs)); // search_files / read_file
    }
  }

  const sections = [];
  if (calendar.length) sections.push(`Calendar:\n${[...new Set(calendar)].join("\n")}`);
  if (notes.length) sections.push(`Notes:\n${[...new Set(notes)].join("\n")}`);
  if (files.length) sections.push(`Files:\n${[...new Set(files)].join("\n")}`);

  const out = ["The on-device model couldn't complete this cleanly \u2014 here's what it managed:"];
  if (sections.length) out.push(sections.join("\n\n"));
  if (saved.length) {
    out.push(`It did save a reminder: ${[...new Set(saved)].map((t) => `"${t}"`).join("; ")}.`);
  }
  if (out.length === 1) {
    return `The on-device model couldn't complete this cleanly, and it didn't gather anything relevant to "${goal}". Try again, pick a larger model, or use the scripted walkthrough (?fallback=1).`;
  }
  return out.join("\n\n");
}

// The first balanced {...} span in the text, or null. Lets us recover an object
// even when the model wraps it in prose or a code fence.
function firstObjectSpan(text) {
  const start = text.indexOf("{");
  if (start === -1) return null;
  let depth = 0;
  let inString = false;
  let escaped = false;
  for (let i = start; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (escaped) escaped = false;
      else if (ch === "\\") escaped = true;
      else if (ch === '"') inString = false;
    } else if (ch === '"') {
      inString = true;
    } else if (ch === "{") {
      depth += 1;
    } else if (ch === "}") {
      depth -= 1;
      if (depth === 0) return text.slice(start, i + 1);
    }
  }
  return null;
}

// Best-effort repair of the malformations small models emit that otherwise trip
// JSON.parse ("Expected ',' or '}'…"): single-quoted strings/keys, trailing
// commas, and unquoted keys. Only ever applied after strict parsing has failed.
function relaxJson(text) {
  return text
    .replace(/'([^']*)'/g, '"$1"')
    .replace(/,\s*([}\]])/g, "$1")
    .replace(/([{,]\s*)([A-Za-z_]\w*)(\s*:)/g, '$1"$2"$3');
}

// Escape raw control characters (literal newline/tab/CR, etc.) that appear INSIDE
// a double-quoted string — JSON forbids them unescaped ("Bad control character in
// string literal"), yet small models happily emit a real newline inside a final
// answer. Structural whitespace between tokens is left untouched.
function escapeControlChars(text) {
  let out = "";
  let inString = false;
  let escaped = false;
  for (let i = 0; i < text.length; i += 1) {
    const ch = text[i];
    if (inString) {
      if (escaped) {
        out += ch;
        escaped = false;
        continue;
      }
      if (ch === "\\") {
        out += ch;
        escaped = true;
        continue;
      }
      if (ch === '"') {
        out += ch;
        inString = false;
        continue;
      }
      const code = text.charCodeAt(i);
      if (code < 0x20) {
        const map = { 8: "\\b", 9: "\\t", 10: "\\n", 12: "\\f", 13: "\\r" };
        out += map[code] || `\\u${code.toString(16).padStart(4, "0")}`;
        continue;
      }
      out += ch;
    } else {
      if (ch === '"') inString = true;
      out += ch;
    }
  }
  return out;
}

function tryParse(text) {
  try {
    return JSON.parse(text);
  } catch {
    return undefined;
  }
}

function extractJson(raw) {
  const text = String(raw).trim();
  // Prefer the first balanced {...} span (drops surrounding prose/fences), then
  // the whole text. For each, try as-is, then apply best-effort repairs: escaping
  // unescaped control chars and relaxing single-quotes/commas/bare keys.
  for (const base of [firstObjectSpan(text), text]) {
    if (!base) continue;
    const variants = [base, escapeControlChars(base), relaxJson(base), escapeControlChars(relaxJson(base))];
    for (const variant of variants) {
      const parsed = tryParse(variant);
      if (parsed !== undefined) return parsed;
    }
  }
  throw new Error("no JSON object in output");
}

function actionFromObject(payload, registry) {
  if (typeof payload !== "object" || payload === null || Array.isArray(payload)) {
    throw new Error("action must be a JSON object");
  }
  const keys = Object.keys(payload).sort();
  if (keys.length === 1 && keys[0] === "final") {
    if (typeof payload.final !== "string") throw new Error("'final' must be a string");
    return { kind: "final", text: payload.final };
  }
  if (keys.length === 2 && keys[0] === "args" && keys[1] === "tool") {
    if (typeof payload.tool !== "string") throw new Error("'tool' must be a string");
    if (!registry.get(payload.tool)) throw new Error(`unknown tool '${payload.tool}'`);
    if (typeof payload.args !== "object" || payload.args === null || Array.isArray(payload.args)) {
      throw new Error("'args' must be an object");
    }
    return { kind: "tool", tool: payload.tool, args: payload.args };
  }
  throw new Error("action keys must be {tool, args} or {final}");
}

// Recover a Python-style tool call some small models emit instead of JSON, e.g.
// read_file(path='recipes/x.md') or search_files("pasta"). Only matches a call
// to a KNOWN tool so prose that merely contains parentheses is left alone.
function parseCallExpression(raw, registry) {
  const text = cleanText(raw);
  const match = text.match(/([A-Za-z_]\w*)\s*\(([\s\S]*)\)/);
  if (!match) return null;
  const name = match[1];
  const tool = registry.get(name);
  if (!tool) return null;

  const body = match[2].trim();
  const args = {};
  if (body) {
    const kw = [...body.matchAll(/([A-Za-z_]\w*)\s*=\s*("([^"]*)"|'([^']*)'|[^,]+)/g)];
    if (kw.length) {
      for (const g of kw) {
        const value = g[3] ?? g[4] ?? g[2].trim().replace(/^['"]|['"]$/g, "");
        args[g[1]] = value;
      }
    } else if (tool.params.length) {
      // A single positional argument maps to the tool's first parameter.
      args[tool.params[0].name] = body.replace(/^['"]|['"]$/g, "");
    }
  }
  return { kind: "tool", tool: name, args };
}

export function parseAction(raw, registry) {
  let payload;
  try {
    payload = extractJson(raw);
  } catch {
    const call = parseCallExpression(raw, registry);
    if (call) return call;
    throw new Error("no JSON object in output");
  }
  return actionFromObject(payload, registry);
}

// Does this string read as a tool invocation rather than an answer? Used to stop
// a mis-formatted "final" (a bare read_file(...) etc.) from reaching the user.
function looksLikeToolCall(text, registry) {
  const t = String(text).trim();
  const whole = t.match(/^([A-Za-z_]\w*)\s*\([\s\S]*\)$/);
  if (whole && registry.get(whole[1])) return true;
  const namesToolCall = registry.tools.some((tool) => t.includes(tool.name));
  const hasArgKey = /\b(path|query|date_or_range|text)\s*=/.test(t);
  return namesToolCall && hasArgKey;
}

// If a "final" is actually a (mis-placed) tool call, return that tool action so
// the loop can execute it instead of showing the call text as the answer.
function reinterpretFinalAsAction(text, registry) {
  try {
    const inner = parseAction(text, registry);
    if (inner.kind === "tool") return inner;
  } catch {
    /* not a recoverable action */
  }
  return null;
}

// Which required action, if any, is still missing when the model tries to finish.
// Governs a bounded nudge (see the loop), never an unbounded retry.
function missingRequiredWork(goal, attempts) {
  const g = String(goal).toLowerCase();
  const attempted = (name) => [...attempts.keys()].some((key) => key.startsWith(`${name}(`));
  const needsSave = /\b(save|remember|remind|reminder)\b/.test(g);
  if (needsSave && !attempted("add_note")) return "save";
  const needsCalendar = !needsSave && /\b(calendar|schedule|agenda|upcoming|events?)\b/.test(g);
  if (needsCalendar && !attempted("list_events")) return "calendar";
  return null;
}

// approve: async (request) => boolean. Only ever called for mutating tools;
// read-only calls are auto-approved here, exactly like Deputy's policy approver.
export async function runAgent({
  goal,
  model,
  registry,
  approve,
  onEvent,
  maxSteps = MAX_STEPS,
  stepTimeoutMs = STEP_TIMEOUT_MS,
}) {
  const emit = (event) => onEvent && onEvent(event);
  const messages = [
    { role: "system", content: systemPrompt(registry.tools) },
    { role: "user", content: goal },
  ];

  // Every (tool,args) we've already resolved this run, plus the useful ones for
  // the fallback summary. `noProgress` counts steps that added nothing new.
  const attempts = new Map();
  const findings = [];
  let parseFailures = 0;
  let noProgress = 0;

  const think = () => withDeadline(stepTimeoutMs, (signal) => model.act(messages, { signal }));

  // One last generation constrained to "answer from what you have", with a
  // deterministic summary behind it, so a run always ends with something useful.
  async function finalize(reason, step) {
    emit({ type: "finalizing", step, reason });
    // Keep roles alternating (as the loop otherwise does) by folding the
    // instruction into a trailing user turn rather than stacking a second one.
    const instruction = finalizeMessage(goal);
    const last = messages[messages.length - 1];
    if (last && last.role === "user") last.content = `${last.content}\n\n${instruction}`;
    else messages.push({ role: "user", content: instruction });

    let answer = null;
    try {
      emit({ type: "thinking", step });
      const raw = await think();
      console.debug("[deputy] finalize output:", raw);
      answer = extractFinalText(raw, registry);
    } catch (err) {
      console.warn("[deputy] finalize generation failed:", err);
    }
    if (!answer) answer = deterministicSummary(goal, findings);
    emit({ type: "run_finished", step, answer, reason });
  }

  for (let step = 1; step <= maxSteps; step += 1) {
    emit({ type: "thinking", step });

    let raw;
    try {
      raw = await think();
      console.debug("[deputy] step", step, "output:", raw);
    } catch (err) {
      console.error("[deputy] step", step, "generation failed:", err);
      emit({ type: "error", step, message: `${err?.name || "Error"}: ${err?.message || err}` });
      return;
    }

    let action;
    try {
      action = parseAction(raw, registry);
      parseFailures = 0;
    } catch (err) {
      parseFailures += 1;
      messages.push({ role: "assistant", content: String(raw) });
      if (parseFailures >= MAX_PARSE_RETRIES) {
        console.warn("[deputy] no valid action after", parseFailures, "tries; forcing a final answer");
        return finalize("unparsed", step);
      }
      messages.push({
        role: "user",
        content: `That was not a valid action (${err.message}). Reply with a single JSON object and nothing else.`,
      });
      emit({ type: "parse_retry", step, detail: err.message });
      continue;
    }

    // A "final" whose text is really a tool call (a small-model mis-format) must
    // never reach the user: re-interpret it as that action, or re-prompt for one.
    if (action.kind === "final" && looksLikeToolCall(action.text, registry)) {
      const asTool = reinterpretFinalAsAction(action.text, registry);
      if (asTool) {
        action = asTool;
      } else {
        messages.push({ role: "assistant", content: String(raw) });
        parseFailures += 1;
        if (parseFailures >= MAX_PARSE_RETRIES) return finalize("unparsed", step);
        messages.push({ role: "user", content: toolInFinalMessage() });
        emit({ type: "parse_retry", step, detail: "tool call placed in final" });
        continue;
      }
    }

    emit({ type: "action_planned", step, action });

    if (action.kind === "final") {
      // Don't let the model quit before doing the work the task requires. Nudge
      // once; the no-progress / max-steps guards keep this from ever looping.
      const missing = missingRequiredWork(goal, attempts);
      if (missing) {
        messages.push({ role: "assistant", content: String(raw) });
        messages.push({ role: "user", content: unfinishedWorkMessage(missing) });
        emit({
          type: "nudge",
          step,
          detail:
            missing === "save"
              ? "No reminder saved yet \u2014 asking Deputy to save it before answering."
              : "Calendar not checked yet \u2014 asking Deputy to look it up before answering.",
        });
        noProgress += 1;
        if (noProgress >= MAX_NO_PROGRESS) return finalize("no_progress", step);
        continue;
      }
      emit({ type: "run_finished", step, answer: action.text, reason: "answered" });
      return;
    }

    messages.push({ role: "assistant", content: String(raw) });
    const tool = registry.get(action.tool);
    const key = callKey(action.tool, action.args);

    // Repeat guard (also covers mutating dedup): don't re-run or re-approve a
    // call we already resolved; nudge the model to change course or finish.
    if (attempts.has(key)) {
      emit({ type: "repeat", step, tool: action.tool, detail: `Already ran ${key}. Asking Deputy to try something else.` });
      messages.push({ role: "user", content: repeatMessage(action.tool, attempts.get(key)) });
      noProgress += 1;
      if (noProgress >= MAX_NO_PROGRESS) return finalize("no_progress", step);
      continue;
    }

    let decision;
    if (!tool.mutating) {
      decision = { approved: true, reason: "auto-approved: read-only" };
    } else {
      emit({ type: "approval_request", step, tool: action.tool, args: action.args, description: tool.description });
      let approved = false;
      try {
        approved = Boolean(await approve({ tool: action.tool, args: action.args, description: tool.description }));
      } catch {
        approved = false;
      }
      decision = { approved, reason: approved ? "approved by operator" : "declined by operator" };
      emit({ type: "approval_resolved", step, tool: action.tool, approved, reason: decision.reason });
    }

    if (!decision.approved) {
      attempts.set(key, `declined by the operator`);
      emit({ type: "action_denied", step, tool: action.tool, args: action.args, reason: decision.reason });
      messages.push({ role: "user", content: denialMessage(action.tool, decision.reason) });
      noProgress += 1;
      if (noProgress >= MAX_NO_PROGRESS) return finalize("no_progress", step);
      continue;
    }

    let observation;
    let ok;
    try {
      observation = tool.handler(action.args);
      ok = true;
    } catch (err) {
      observation = `${err?.name || "Error"}: ${err?.message || err}`;
      ok = false;
    }
    attempts.set(key, String(observation));
    if (ok) findings.push({ tool: action.tool, args: action.args, observation });
    noProgress = 0;
    emit({ type: "tool_observed", step, tool: action.tool, args: action.args, ok, observation, reason: decision.reason });
    messages.push({ role: "user", content: observationMessage(action.tool, observation) });
  }

  return finalize("max_steps", maxSteps);
}
