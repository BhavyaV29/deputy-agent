// Preset goals and their canned "thoughts". In fallback mode a `scriptedModel`
// replays these action-by-action through the *real* agent loop, so tool calls,
// observations, the approval gate, and the audit are all genuine — only the
// model's decisions are pre-recorded instead of generated on-device.

import { sleep } from "./util.js";

function lastWasDenial(messages) {
  const last = messages[messages.length - 1];
  return Boolean(last && last.role === "user" && /declined/i.test(last.content));
}

export const SCENARIOS = [
  {
    id: "review",
    label: "Prep for today's review",
    goal: "Check my notes and calendar for the Phase 3 review, then save a reminder to prep the slides.",
    hint: "read-only lookups + a gated write",
    script: [
      '{"tool": "search_notes", "args": {"query": "Phase 3 review"}}',
      '{"tool": "list_events", "args": {"date_or_range": "2026-07-08"}}',
      '{"tool": "add_note", "args": {"text": "Prep slides for the Phase 3 review — today 09:30, home office"}}',
      (messages) =>
        lastWasDenial(messages)
          ? '{"final": "Your Phase 3 review is today at 09:30 in the home office. I did not save a new reminder because the write was declined — but you already have a note to prep the slides."}'
          : '{"final": "Your Phase 3 review is today at 09:30 in the home office. You already had a note to prep the slides, and I saved a reminder to have them ready before 09:30."}',
    ],
  },
  {
    id: "pasta",
    label: "Find a weeknight dinner",
    goal: "What can I cook tonight? Find a quick pasta recipe in my files.",
    hint: "read-only, no approval needed",
    script: [
      '{"tool": "search_files", "args": {"query": "pasta"}}',
      '{"tool": "read_file", "args": {"path": "recipes/weeknight-pasta.md"}}',
      '{"final": "Try the weeknight pasta: warm garlic in olive oil without browning it, add a pinch of chilli, a tin of tomatoes and a little salt, and simmer while the pasta cooks. Reserve a mug of pasta water, toss the pasta off the heat until the sauce coats, and finish with plenty of parmesan."}',
    ],
  },
  {
    id: "week",
    label: "Look at the next few days",
    goal: "What's on my calendar over the next few days?",
    hint: "a single calendar lookup",
    script: [
      '{"tool": "list_events", "args": {"date_or_range": "2026-07-08..2026-07-10"}}',
      '{"final": "Over the next few days: today (8 Jul) the Phase 3 review at 09:30 and lunch with Sam at 13:00; on the 9th a dentist appointment at 11:00; and on the 10th a grocery run at 16:00."}',
    ],
  },
];

export function getScenario(id) {
  return SCENARIOS.find((scenario) => scenario.id === id) || null;
}

export function scriptedModel(script, { delayMs = 650 } = {}) {
  let index = 0;
  return {
    kind: "scripted",
    async act(messages) {
      await sleep(delayMs);
      const step = script[Math.min(index, script.length - 1)];
      index += 1;
      return typeof step === "function" ? step(messages) : step;
    },
  };
}
