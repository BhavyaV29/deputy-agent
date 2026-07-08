// Prompt text for the loop, ported from Deputy's prompts.py. Observations are
// threaded back as plain user turns so the loop stays model-agnostic rather than
// leaning on any one runtime's native tool-calling.

import { signature } from "./tools.js";
import { TODAY } from "./data.js";

export function systemPrompt(tools) {
  const catalog = tools.map((tool) => `- ${signature(tool)}: ${tool.description}`).join("\n");
  return [
    "You are Deputy, a private on-device assistant. Reach the user's goal one step",
    "at a time, using tools when they help.",
    "",
    `Tools:\n${catalog}`,
    "",
    "Reply on every turn with exactly one JSON object and nothing else \u2014 no",
    "prose, no explanation, no markdown, no code fences. Use either",
    '  {"tool": "<name>", "args": {...}}  to run a tool, or',
    '  {"final": "<answer>"}              once you can answer the goal.',
    "Base each step on the observations returned by earlier tool calls.",
    `Today is ${TODAY}.`,
    "",
    "Examples of valid replies:",
    '  {"tool": "search_notes", "args": {"query": "grocery"}}',
    '  {"tool": "list_events", "args": {"date_or_range": "2026-07-08"}}',
    '  {"final": "You have a dentist appointment on 2026-07-09 at 11:00."}',
  ].join("\n");
}

export function observationMessage(tool, observation) {
  return `Observation from \`${tool}\`:\n${observation}`;
}

export function denialMessage(tool, reason) {
  const detail = reason ? ` (${reason})` : "";
  return `Your request to run \`${tool}\` was declined${detail}. Choose a different action.`;
}
