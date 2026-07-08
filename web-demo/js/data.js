// The demo's entire universe. These fake notes, files, and calendar events live
// only in this browser tab's memory — they mirror Deputy's real MCP tools
// (files / notes / calendar) but are never read from disk or sent over a network.
// `add_note` mutates NOTES in place, which is exactly why it needs approval.

export const TODAY = "2026-07-08";

export const NOTES = [
  { created: "2026-07-07T21:02:23+00:00", text: "prep slides for the Phase 3 review" },
  { created: "2026-07-07T21:32:53+00:00", text: "buy oat milk on the way home" },
];

const DEPUTY_MD = `# Deputy

A private, on-device assistant. It runs a small local model through a bounded
ReAct loop and reaches its tools over MCP, so the same loop can drive real
servers without knowing anything about them.

## Retrieval

Documents are chunked and embedded with nomic-embed-text, then stored in
sqlite-vec. The \`search_docs\` tool returns the closest passages together with
their source file paths, so an answer can always be traced back to where it
came from. When the embedder is offline a keyword search stands in.

## Safety

The files server is confined to one workspace root: any path that resolves
outside it — through \`..\`, an absolute path, or a symlink — is rejected rather
than served. Tools that write, like \`add_note\`, are tagged as mutating so a
later phase can require approval before they run.
`;

const PASTA_MD = `# Weeknight pasta

Warm garlic in olive oil, but don't let it brown. Add a pinch of chilli, then
a tin of tomatoes and a little salt. Let it simmer while the pasta cooks.

Reserve a mug of the pasta water before draining. Toss the pasta through the
sauce off the heat, loosening with the water until it coats, and finish with
plenty of parmesan.
`;

const REVIEW_MD = `# Phase 3 review — 8 Jul 2026

Present: me, one patient rubber duck.

- The MCP host now talks to stdio servers and adapts each discovered tool into
  the registry, so the agent loop picks them up unchanged.
- Retrieval landed on sqlite-vec after ruling out a flat numpy scan. Keeping the
  chunk text in a plain table beside the vector table makes a match a simple
  join on rowid.
- Decision: web search stays opt-in and off by default. On-device first.
- Next up: the trust surface — an approval gate that reads the mutating flag.
`;

const READING_MD = `# Reading list

- *Designing Data-Intensive Applications* — reread the chapter on storage and
  indexes before the next round of retrieval work.
- A survey paper on approximate nearest-neighbour search; directly relevant to
  how \`search_docs\` scales past a few thousand chunks.
- Something undemanding for the train home.
`;

export const FILES = {
  "projects/deputy.md": DEPUTY_MD,
  "recipes/weeknight-pasta.md": PASTA_MD,
  "meetings/2026-07-08-review.md": REVIEW_MD,
  "reading.md": READING_MD,
};

export const CALENDAR = [
  { date: "2026-07-08", start: "09:30", end: "10:00", title: "Phase 3 review", location: "home office" },
  { date: "2026-07-08", start: "13:00", end: "13:30", title: "Lunch with Sam", location: "" },
  { date: "2026-07-09", start: "11:00", end: "12:00", title: "Dentist", location: "" },
  { date: "2026-07-10", start: "16:00", end: "17:00", title: "Grocery run", location: "" },
];
