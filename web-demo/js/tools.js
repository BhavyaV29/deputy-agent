// In-browser reimplementations of Deputy's MCP tools. Same names, descriptions,
// argument shapes, and read/write semantics as the Python servers — just backed
// by the in-memory corpus in data.js instead of the filesystem. Read-only tools
// run freely; `add_note` is flagged `mutating`, so the loop gates it on approval.

import { NOTES, FILES, CALENDAR } from "./data.js";

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
  if (!matched.length) return `No notes matched '${query}'.`;
  return matched.map(({ note }) => `[${note.created}] ${note.text}`).join("\n");
}

function addNote({ text }) {
  const body = String(text ?? "").trim();
  if (!body) throw new ToolError("ValueError", "a note cannot be empty");
  const created = new Date().toISOString().slice(0, 19) + "+00:00";
  NOTES.push({ created, text: body });
  return `Saved note at ${created}.`;
}

function firstMatch(text, needle) {
  for (const raw of text.split("\n")) {
    if (raw.toLowerCase().includes(needle)) {
      const line = raw.trim();
      return line.length <= 200 ? line : line.slice(0, 200) + "...";
    }
  }
  return null;
}

function searchFiles({ query }) {
  const needle = String(query ?? "").trim().toLowerCase();
  if (!needle) return "Provide a non-empty query.";
  const matches = [];
  for (const rel of Object.keys(FILES).sort()) {
    if (rel.toLowerCase().includes(needle)) matches.push(`${rel} (filename)`);
    const line = firstMatch(FILES[rel], needle);
    if (line !== null) matches.push(`${rel}: ${line}`);
    if (matches.length >= MAX_MATCHES) break;
  }
  if (!matches.length) return `No files matched '${query}'.`;
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
  if (!events.length) return `No events between ${start} and ${end}.`;
  return events.map(formatEvent).join("\n");
}

const TOOLS = [
  {
    name: "search_files",
    description: "Search the workspace for files whose name or contents mention a phrase.",
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
    description: "Search saved notes for a phrase and return the ones that match.",
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
    description:
      "List calendar events for a date (YYYY-MM-DD) or inclusive range (YYYY-MM-DD..YYYY-MM-DD).",
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
