// Node tests for the tolerant action parser in js/agent.js — no deps, no build:
//   node test/parse.test.mjs   (or: npm test)
//
// Focus is the small-model malformations the loop must recover from so a clean
// answer/action isn't lost to a raw dump: unescaped control chars inside a JSON
// string (the "Bad control character" 3B case), Python-style calls, single
// quotes, trailing commas, and prose wrapping.

import assert from "node:assert/strict";
import { parseAction } from "../js/agent.js";

// Minimal stand-in for the real tool registry: parseAction only needs get(name)
// to resolve a known tool and its positional params.
const registry = {
  get(name) {
    const tools = {
      read_file: { params: [{ name: "path" }], mutating: false },
      search_files: { params: [{ name: "query" }], mutating: false },
      search_notes: { params: [{ name: "query" }], mutating: false },
      list_events: { params: [{ name: "date_or_range" }], mutating: false },
      add_note: { params: [{ name: "text" }], mutating: true },
    };
    return tools[name] || null;
  },
};

let passed = 0;
function test(name, fn) {
  fn();
  passed += 1;
  console.log(`  ok  ${name}`);
}

// (4) The 3B calendar case: a correct final answer with an UNESCAPED literal
// newline inside the JSON string. Raw JSON.parse rejects it; the parser must
// still recover the answer, newline intact.
test("unescaped newline inside final string is recovered", () => {
  const raw = '{"final":"You have 2 events:\nStandup at 9:00\nReview at 14:00"}';
  assert.throws(() => JSON.parse(raw), "precondition: raw is invalid JSON");
  const action = parseAction(raw, registry);
  assert.equal(action.kind, "final");
  assert.equal(action.text, "You have 2 events:\nStandup at 9:00\nReview at 14:00");
});

test("unescaped tab and carriage return inside final string are recovered", () => {
  const raw = '{"final":"col1\tcol2\rnext"}';
  assert.throws(() => JSON.parse(raw));
  const action = parseAction(raw, registry);
  assert.equal(action.kind, "final");
  assert.equal(action.text, "col1\tcol2\rnext");
});

test("single-quoted JSON with an unescaped newline is recovered", () => {
  const raw = "{'final':'line one\nline two'}";
  const action = parseAction(raw, registry);
  assert.equal(action.kind, "final");
  assert.equal(action.text, "line one\nline two");
});

test("clean final passes through untouched", () => {
  const action = parseAction('{"final":"All done."}', registry);
  assert.equal(action.kind, "final");
  assert.equal(action.text, "All done.");
});

test("python-style read_file call is parsed as a tool action", () => {
  const action = parseAction("read_file(path='recipes/pasta.md')", registry);
  assert.equal(action.kind, "tool");
  assert.equal(action.tool, "read_file");
  assert.equal(action.args.path, "recipes/pasta.md");
});

test("single-quoted JSON tool call is parsed", () => {
  const action = parseAction("{'tool': 'search_files', 'args': {'query': 'pasta'}}", registry);
  assert.equal(action.kind, "tool");
  assert.equal(action.tool, "search_files");
  assert.equal(action.args.query, "pasta");
});

test("prose-wrapped tool call with a trailing comma is parsed", () => {
  const raw = 'Sure! {"tool":"list_events","args":{"date_or_range":"2026-09-03",}}';
  const action = parseAction(raw, registry);
  assert.equal(action.kind, "tool");
  assert.equal(action.tool, "list_events");
  assert.equal(action.args.date_or_range, "2026-09-03");
});

console.log(`\n${passed} passed`);
