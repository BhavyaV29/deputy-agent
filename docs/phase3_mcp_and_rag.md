# Phase 3: real tools via MCP + on-device RAG

Phase 2 built the agent core: a bounded ReAct loop whose every step is
constrained to an action schema derived from a `ToolRegistry`. Phase 3 fills
that registry with tools that do real, useful work — reached over MCP — and adds
retrieval over the user's own files. The loop itself is unchanged: because the
action schema and system prompt are generated from the registry, any tool put
into it is immediately usable.

## Architecture

| Module | Responsibility |
| --- | --- |
| `deputy/config.py` | `DeputyConfig`: workspace root, notes/calendar paths, index path, embeddings model, web-search flag — from env with local defaults. All runtime state lives under `data/` (gitignored). |
| `deputy/mcp/host.py` | `McpHost`: connects to stdio MCP servers and exposes **blocking** `list_tools()` / `call_tool()`. It owns a private event loop on a daemon thread; one caretaker coroutine opens and later closes every session (anyio needs enter/exit on one task) while calls are dispatched onto the loop and awaited. |
| `deputy/mcp/adapter.py` | `register_mcp_tools()`: maps each discovered MCP tool (name, description, `inputSchema`, `readOnlyHint`) onto a native `Tool` whose handler dispatches back through the host, then registers it. |
| `deputy/servers/` | The built-in stdio servers: `files`, `notes`, `calendar`, `web` (opt-in). Tool logic is in plain functions (unit-tested directly); the MCP shell reads its configured location from the environment. |
| `deputy/rag/` | `chunk` (structure-aware splitting), `store` (sqlite-vec), `search` (the `search_docs` tool), `index` (the `python -m deputy.rag.index` entrypoint). |
| `deputy/app.py` | `assistant_registry()`: launches the servers as subprocesses, adapts their tools, and adds the native `search_docs` tool — yielding one registry the Phase-2 `Agent` runs against. |

MCP tools and the retrieval tool land in the *same* registry and are
indistinguishable to the loop; `search_docs` is native (in-process) because it
needs the injected `Embedder`, while the file/note/calendar tools are real MCP
servers reached over stdio.

## Built-in tools and their safety constraints

| Tool | Server | Mutating | Constraint |
| --- | --- | --- | --- |
| `search_files(query)` | files | no | Confined to the workspace root. |
| `read_file(path)` | files | no | Every path is resolved and checked to fall under the root; `..`, absolute paths, and symlinks that point outside are rejected (`PathEscapeError`). |
| `search_notes(query)` | notes | no | Keyword match over the local note store. |
| `add_note(text)` | notes | **yes** | Append-only JSONL under `data/`. Declared `readOnlyHint=False`, so the host tags it `mutating` for the Phase-4 gate. |
| `list_events(date_or_range)` | calendar | no | Read-only over a local JSON store; a single date or an inclusive `A..B` range. |
| `web_search(query)` | web | no | **Opt-in**: only registered when `DEPUTY_WEB_SEARCH_ENABLED` is set. The only tool that touches the network. |

Side-effect metadata is carried by a single `Tool.mutating` flag (default
`False`). For MCP tools it is derived from the standard `readOnlyHint` /
`destructiveHint` annotations. Absent hints mean read-only: the gate stays
reserved for genuine writes rather than desensitizing the user with prompts on
every lookup. Phase 4 will read this flag; it is not gated yet.

## RAG design

- **Embeddings:** `nomic-embed-text` via Ollama in production, behind the
  `Embedder` protocol so tests inject a deterministic fake and never hit the
  network. The embedding dimension is learned from the first vector at index
  time, so the store adapts to whatever model is configured.
- **Store:** sqlite-vec. Chunk text and metadata (path, ordinal) live in an
  ordinary table; embeddings live in a sibling `vec0` virtual table keyed by the
  same rowid, so nearest-neighbour search is a join.
- **Chunking:** paragraph-first, with oversized paragraphs split on words;
  consecutive chunks carry a trailing paragraph of overlap so a match that
  straddles a boundary is still retrievable.
- **Retrieval:** `search_docs` prefers vector search and falls back to keyword
  search when the embedder is offline or returns nothing. Every hit carries its
  source path so the agent can cite it and open the file for more.

## Flagship tasks

Two end-to-end tasks exercise the whole surface, driven by `qwen2.5:3b`.

### (a) Find a topic across your files and summarize with sources

`search_files` locates the mentions, `search_docs` pulls the passages, and the
model summarizes — citing the files.

```
$ python -m deputy --real "Find everywhere sqlite-vec is mentioned across my files
  and summarize what I've written about it, with the source file paths."

[1] plan: ToolCall(tool='search_files', args={'query': 'sqlite-vec'})
[1] search_files -> (ok) meetings/2026-07-08-review.md: - Retrieval landed on sqlite-vec after ruling out a flat numpy scan. Keeping the
                        projects/deputy.md: sqlite-vec. The `search_docs` tool returns the closest passages together with
[2] plan: ToolCall(tool='search_docs', args={'query': 'sqlite-vec'})
[2] search_docs -> (ok) [1] projects/deputy.md ... [2] meetings/2026-07-08-review.md ... [3] projects/deputy.md ... [4] reading.md
[3] finished (answered): sqlite-vec is mentioned in two documents:
  1. In 'projects/deputy.md': The Deputy tool uses sqlite-vec for retrieval, storing chunk text alongside vector embeddings in a table for easy matching.
  2. In 'meetings/2026-07-08-review.md': ... uses sqlite-vec after ruling out other methods like flat numpy scan.
```

### (b) What's on my calendar, and any related notes?

`list_events` reads the day, `search_notes` finds the related note by shared
terms, and the model connects them.

```
$ python -m deputy --real "What's on my calendar for 2026-07-08?
  Then check my notes for anything related to those events."

[1] plan: ToolCall(tool='list_events', args={'date_or_range': '2026-07-08..2026-07-08'})
[1] list_events -> (ok) 2026-07-08 09:30-10:00  Phase 3 review @ home office
                        2026-07-08 13:00-13:30  Lunch with Sam
[2] plan: ToolCall(tool='search_notes', args={'query': 'Phase 3 review @ home office\nLunch with Sam'})
[2] search_notes -> (ok) [2026-07-07T21:02:23+00:00] prep slides for the Phase 3 review
[3] finished (answered): Your calendar has a meeting at home office on July 8th for the Phase 3 review.
  Your note mentions preparing slides for that meeting.
```

## Reproducing the demos

```bash
export DEPUTY_WORKSPACE_ROOT="$(pwd)/sample_workspace"
export DEPUTY_CALENDAR_PATH="$(pwd)/sample_workspace/calendar.json"

# 1. Build the on-device index over the sample corpus.
uv run python -m deputy.rag.index sample_workspace

# 2. Seed a note (exercises the mutating add_note tool).
uv run python -m deputy --real "Please save a note: prep slides for the Phase 3 review"

# 3. Run the flagship tasks.
uv run python -m deputy --real "Find everywhere sqlite-vec is mentioned across my files and summarize with sources."
uv run python -m deputy --real "What's on my calendar for 2026-07-08? Then check my notes for anything related."
```

## Decisions and deviations

- **Embeddings model:** `nomic-embed-text` (274 MB, 768-dim) — small, fast, and
  a solid default for local text retrieval.
- **Vector store:** sqlite-vec over a hand-rolled numpy scan. It keeps
  everything in one local file, scales past a toy corpus, and lets keyword
  fallback share the same database.
- **Web search:** off by default and unregistered unless explicitly enabled, so
  the assistant is fully on-device out of the box.
- **`search_docs` is native, not MCP:** it depends on the injected `Embedder`;
  routing it through a subprocess would mean a second Ollama client with no
  benefit. It still enters the same registry as the MCP tools.
- **`search_notes` uses keyword, not substring, matching:** models pass verbose
  queries, and a note is relevant if it shares terms — a whole-string substring
  match missed obviously-related notes in testing.
