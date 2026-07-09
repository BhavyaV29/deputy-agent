// The bounded ReAct loop, ported to the browser: plan an action, gate it, act,
// observe, repeat until the model answers or the step ceiling is hit. It emits
// one event per transition so the UI can stream the run and the audit can record
// it — the loop itself knows nothing about the DOM or where actions come from
// (a real WebLLM model or a canned script both satisfy the `model.act` seam).

import { systemPrompt, observationMessage, denialMessage, repeatMessage, finalizeMessage } from "./prompts.js";
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
// or failing that any prose the model wrote — but never a leftover tool-call
// blob, which would read as gibberish to the user.
function extractFinalText(raw, registry) {
  try {
    const action = parseAction(raw, registry);
    if (action.kind === "final") return action.text.trim() || null;
    return null;
  } catch {
    /* not a valid action — fall back to whatever prose it produced */
  }
  const cleaned = cleanText(raw);
  if (!cleaned || cleaned.startsWith("{")) return null;
  return cleaned.length >= 8 ? cleaned : null;
}

// The guaranteed floor: even if the model never cooperates, stitch the real
// tool observations into an answer so the UI never shows "no answer".
function deterministicSummary(goal, findings) {
  const useful = findings
    .map((f) => String(f.observation).trim())
    .filter((text) => text && !/^(No (files|notes|events)\b|Provide a non-empty)/i.test(text));
  if (!useful.length) {
    return `I searched your notes, files, and calendar but couldn't find anything that answers "${goal}". Try different keywords, or run the scripted demo with ?fallback=1.`;
  }
  return `Here's what I found for "${goal}":\n\n${useful.join("\n\n")}`;
}

function extractJson(raw) {
  const text = String(raw).trim();
  try {
    return JSON.parse(text);
  } catch {
    // Small models sometimes wrap the object in prose or a code fence; recover
    // the first balanced {...} span rather than failing the whole step.
  }
  const start = text.indexOf("{");
  if (start === -1) throw new Error("no JSON object in output");
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
      if (depth === 0) return JSON.parse(text.slice(start, i + 1));
    }
  }
  throw new Error("unterminated JSON object in output");
}

export function parseAction(raw, registry) {
  const payload = extractJson(raw);
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

    emit({ type: "action_planned", step, action });

    if (action.kind === "final") {
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
