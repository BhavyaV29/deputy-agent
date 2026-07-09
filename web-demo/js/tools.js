// In-browser reimplementations of Deputy's MCP tools. Same names, descriptions,
// argument shapes, and read/write semantics as the Python servers — just backed
// by the in-memory corpus in data.js instead of the filesystem. Read-only tools
// run freely; `add_note` is flagged `mutating`, so the loop gates it on approval.

import { NOTES, FILES, CALENDAR, TODAY, CALENDAR_START, CALENDAR_END } from "./data.js";

const MIN_TERM_LEN = 3;
const MAX_READ_CHARS = 10_000;
const MAX_MATCHES = 20;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}$/;

class ToolError extends Error {
  constructor(name, message) {
    super(message);
    this.name = name;
  }
}

function terms(query) {
  const tokens = String(query).toLowerCase().match(/[a-z0-9]+/g) || [];
  const long = tokens.filter((t) => t.length >= MIN_TERM_LEN);
  return long.length ? long : tokens;
}

function searchNotes({ query }) {
  const wanted = terms(query ?? "");
  if (!wanted.length) return "Provide a non-empty query.";
  const scored = NOTES.map((note) => {
    const haystack = note.text.toLowerCase();
    const score = wanted.reduce((acc, term) => acc + (haystack.includes(term) ? 1 : 0), 0);
    return { score, note };
  });
  const matched = scored.filter((s) => s.score > 0).sort((a, b) => b.score - a.score);
  if (!matched.length) return `No notes matched '${query}'. Try simpler keywords, e.g. "review".`;
  return matched.map(({ note }) => `[${note.created}] ${note.text}`).join("\n");
}

function addNote({ text }) {
  const body = String(text ?? "").trim();
  if (!body) throw new ToolError("ValueError", "a note cannot be empty");
  const created = new Date().toISOString().slice(0, 19) + "+00:00";
  NOTES.push({ created, text: body });
  return `Saved note at ${created}.`;
}

function firstMatch(text, tokens) {
  for (const raw of text.split("\n")) {
    const line = raw.toLowerCase();
    if (tokens.some((token) => line.includes(token))) {
      const trimmed = raw.trim();
      return trimmed.length <= 200 ? trimmed : trimmed.slice(0, 200) + "...";
    }
  }
  return null;
}

// Keyword search, not a structured query: tokenize whatever the model sends
// (even a hallucinated `cuisine:main,ingredients:pasta` DSL) and match a file
// if its name or text contains ANY token, so "pasta" still finds the recipe.
function searchFiles({ query }) {
  const wanted = terms(query ?? "");
  if (!wanted.length) return 'Provide a non-empty query, e.g. search_files(query="pasta").';
  const matches = [];
  for (const rel of Object.keys(FILES).sort()) {
    if (wanted.some((token) => rel.toLowerCase().includes(token))) matches.push(`${rel} (filename)`);
    const line = firstMatch(FILES[rel], wanted);
    if (line !== null) matches.push(`${rel}: ${line}`);
    if (matches.length >= MAX_MATCHES) break;
  }
  if (!matches.length) return `No files matched '${query}'. Try simpler keywords, e.g. "pasta".`;
  return matches.join("\n");
}

function readFile({ path }) {
  const candidate = String(path ?? "");
  // Mirror the files server's confinement: reject traversal and absolute paths
  // rather than serving anything outside the (virtual) workspace root.
  if (candidate.startsWith("/") || candidate.split("/").includes("..")) {
    throw new ToolError("PathEscapeError", `path '${candidate}' escapes the workspace`);
  }
  const key = candidate.replace(/^\.\//, "");
  if (!(key in FILES)) throw new ToolError("FileNotFoundError", `no such file: ${candidate}`);
  const text = FILES[key];
  return text.length > MAX_READ_CHARS ? text.slice(0, MAX_READ_CHARS) + "\n... (truncated)" : text;
}

function parseRange(spec) {
  const trimmed = String(spec ?? "").trim();
  const [lo, hi] = trimmed.includes("..")
    ? trimmed.split("..", 2).map((p) => p.trim())
    : [trimmed, trimmed];
  for (const part of [lo, hi]) {
    if (!ISO_DATE.test(part)) throw new ToolError("ValueError", `invalid isoformat string: '${part}'`);
  }
  return [lo, hi];
}

function formatEvent(event) {
  const where = event.location ? ` @ ${event.location}` : "";
  return `${event.date} ${event.start}-${event.end}  ${event.title}${where}`;
}

function listEvents({ date_or_range }) {
  const [start, end] = parseRange(date_or_range);
  const events = CALENDAR.filter((e) => start <= e.date && e.date <= end).sort((a, b) =>
    `${a.date} ${a.start}`.localeCompare(`${b.date} ${b.start}`),
  );
  // Tell the model exactly which range holds data, so a single wrong-date guess
  // becomes a self-correcting hint instead of eight identical empty lookups.
  if (!events.length) {
    return `No events between ${start} and ${end}. Scheduled events run from ${CALENDAR_START} to ${CALENDAR_END} \u2014 call list_events(date_or_range="${CALENDAR_START}..${CALENDAR_END}") to see them.`;
  }
  return events.map(formatEvent).join("\n");
}

const TOOLS = [
  {
    name: "search_files",
    description:
      'Search files by simple space-separated KEYWORDS (not a structured query). Matches a file if its name or text contains any keyword. Example: search_files(query="pasta").',
    params: [{ name: "query", type: "string" }],
    mutating: false,
    handler: searchFiles,
  },
  {
    name: "read_file",
    description: "Read a text file from the workspace by its path relative to the root.",
    params: [{ name: "path", type: "string" }],
    mutating: false,
    handler: readFile,
  },
  {
    name: "search_notes",
    description:
      'Search saved notes by simple space-separated KEYWORDS. Example: search_notes(query="review slides").',
    params: [{ name: "query", type: "string" }],
    mutating: false,
    handler: searchNotes,
  },
  {
    name: "add_note",
    description: "Save a short note for later. Use for facts the user asks you to remember.",
    params: [{ name: "text", type: "string" }],
    mutating: true,
    handler: addNote,
  },
  {
    name: "list_events",
    description: `List calendar events for a single date (YYYY-MM-DD) or an inclusive range (YYYY-MM-DD..YYYY-MM-DD). For several days use a range, e.g. list_events(date_or_range="${CALENDAR_START}..${CALENDAR_END}"). Today is ${TODAY}.`,
    params: [{ name: "date_or_range", type: "string" }],
    mutating: false,
    handler: listEvents,
  },
];

export function signature(tool) {
  const params = tool.params.map((p) => `${p.name}: ${p.type}`).join(", ");
  return `${tool.name}(${params})`;
}

export function createRegistry() {
  const byName = new Map(TOOLS.map((tool) => [tool.name, tool]));
  return {
    tools: TOOLS,
    get: (name) => byName.get(name),
  };
}
