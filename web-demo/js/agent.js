// The bounded ReAct loop, ported to the browser: plan an action, gate it, act,
// observe, repeat until the model answers or the step ceiling is hit. It emits
// one event per transition so the UI can stream the run and the audit can record
// it — the loop itself knows nothing about the DOM or where actions come from
// (a real WebLLM model or a canned script both satisfy the `model.act` seam).

import { systemPrompt, observationMessage, denialMessage } from "./prompts.js";

const MAX_STEPS = 8;

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
export async function runAgent({ goal, model, registry, approve, onEvent, maxSteps = MAX_STEPS }) {
  const emit = (event) => onEvent && onEvent(event);
  const messages = [
    { role: "system", content: systemPrompt(registry.tools) },
    { role: "user", content: goal },
  ];

  for (let step = 1; step <= maxSteps; step += 1) {
    emit({ type: "thinking", step });

    let raw;
    try {
      raw = await model.act(messages);
    } catch (err) {
      emit({ type: "error", step, message: `${err?.name || "Error"}: ${err?.message || err}` });
      return;
    }

    let action;
    try {
      action = parseAction(raw, registry);
    } catch (err) {
      messages.push({ role: "assistant", content: String(raw) });
      messages.push({
        role: "user",
        content: `That was not a valid action (${err.message}). Reply with a single JSON object.`,
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
      emit({ type: "action_denied", step, tool: action.tool, args: action.args, reason: decision.reason });
      messages.push({ role: "user", content: denialMessage(action.tool, decision.reason) });
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
    emit({ type: "tool_observed", step, tool: action.tool, args: action.args, ok, observation, reason: decision.reason });
    messages.push({ role: "user", content: observationMessage(action.tool, observation) });
  }

  emit({ type: "run_finished", step: maxSteps, answer: null, reason: "max_steps" });
}
