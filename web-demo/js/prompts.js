// Prompt text for the loop, ported from Deputy's prompts.py. Observations are
// threaded back as plain user turns so the loop stays model-agnostic rather than
// leaning on any one runtime's native tool-calling.

import { signature } from "./tools.js";
import { TODAY, CALENDAR_START, CALENDAR_END } from "./data.js";

export function systemPrompt(tools) {
  const catalog = tools.map((tool) => `- ${signature(tool)}: ${tool.description}`).join("\n");
  return [
    "You are Deputy, a private on-device assistant. Reach the user's goal in as few",
    "steps as possible, using tools only when they help.",
    "",
    `Tools:\n${catalog}`,
    "",
    "Reply on every turn with exactly one JSON object and nothing else \u2014 no",
    "prose, no explanation, no markdown, no code fences. Use either",
    '  {"tool": "<name>", "args": {...}}  to run a tool, or',
    '  {"final": "<answer>"}              to answer the goal.',
    "",
    "Rules:",
    "- The moment the observations are enough to answer, reply with {\"final\": ...}. Prefer answering over calling another tool.",
    "- Never repeat a tool call with the same arguments you already used; it returns the same thing.",
    "- Searches take plain space-separated keywords, not key:value or structured queries. If a search finds nothing, retry with simpler/different keywords or a different tool; if it still finds nothing, answer from what you know.",
    "- Once a note is saved, do not save it again.",
    `- Today is ${TODAY}. Sample calendar events run from ${CALENDAR_START} to ${CALENDAR_END}; for "the next few days" call list_events with date_or_range "${CALENDAR_START}..${CALENDAR_END}".`,
    "",
    "Examples of valid replies:",
    '  {"tool": "search_files", "args": {"query": "pasta"}}',
    `  {"tool": "list_events", "args": {"date_or_range": "${CALENDAR_START}..${CALENDAR_END}"}}`,
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

export function repeatMessage(tool, priorObservation) {
  return [
    `You already called \`${tool}\` with those exact arguments. It returned:`,
    priorObservation,
    'Do not repeat it. Either use different arguments or a different tool, or if you have enough to answer now, reply with {"final": "<answer>"}.',
  ].join("\n");
}

export function finalizeMessage(goal) {
  return [
    "Stop calling tools now. Using only the observations above, give your best final",
    `answer to the user's request: "${goal}".`,
    'Reply with a single JSON object {"final": "<answer>"} and nothing else.',
  ].join("\n");
}
