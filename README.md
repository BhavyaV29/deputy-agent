# Deputy

**A private, on-device AI agent that works your own files and runs tasks — and asks before it acts.**

Deputy runs a small local model (via [Ollama](https://ollama.com)) in a bounded agent loop, calls
tools through [MCP](https://modelcontextprotocol.io), retrieves from your own documents on-device, and
records every action behind approval gates before anything is written. Nothing leaves your machine
unless you explicitly opt in.

```text
$ uv run python -m deputy --real "What's on my calendar for 2026-07-08, and any related notes?"
[1] plan: list_events(date_or_range='2026-07-08..2026-07-08')
[1] list_events -> (ok) 2026-07-08 09:30-10:00  Phase 3 review @ home office ...
[2] plan: search_notes(query='Phase 3 review')
[2] search_notes -> (ok) [2026-07-07] prep slides for the Phase 3 review
[3] finished (answered): You have the Phase 3 review at 09:30; your notes mention prepping slides for it.
```

---

## Why

Most "AI assistants" are a text box wired to someone else's server. Deputy is the opposite bet:

- **Private by default.** The model, your files, the vector index, and the audit log all live on your
  machine. The only tool that touches the network is web search, and it is off unless you turn it on.
- **Works your own stuff.** Point it at a folder and it can search and read your files, look up your
  calendar, remember notes, and answer questions grounded in your own documents (with citations).
- **Asks before it acts.** Reads run freely; anything that *writes* or has a side effect pauses for a
  yes/no you actually see — in the terminal or the browser — and every step is appended to a plain-text
  audit log you can `tail` while it works.
- **Reliable enough to trust the loop.** Every model step is emitted under **constrained decoding**
  (a JSON schema passed to the runtime), so the agent can only ever produce a well-formed tool call or
  a final answer. On the reliability suite this lifts end-to-end task success from **29% → 88%** for
  `qwen2.5:3b` (see [Reliability](#reliability)).

---

## Features

Everything below is implemented and tested in this repo.

| Capability | What it does | Where |
| --- | --- | --- |
| **Bounded ReAct loop** | Plan → act → observe, up to a step ceiling; emits a structured event per transition. | `deputy/agent.py` |
| **Constrained tool-calling** | Each step is decoded against an `anyOf` schema — one branch per tool (name pinned, args typed) plus a final-answer branch — so output is always parseable into a typed action. | `deputy/actions.py`, `deputy/model.py` |
| **Local model runtime** | Blocking Ollama client behind a `ChatModel` protocol; tests inject a fake and never hit the network. | `deputy/model.py` |
| **Tools over MCP** | A synchronous host drives async stdio MCP servers; discovered tools are adapted into native `Tool`s, indistinguishable to the loop. | `deputy/mcp/` |
| **Built-in servers** | `files` (confined search/read), `notes` (add/search), `calendar` (read-only lookups), `web` (opt-in search — the only networked tool). | `deputy/servers/` |
| **On-device RAG** | Structure-aware chunking → Ollama embeddings → `sqlite-vec` store; `search_docs` prefers vector search, falls back to keyword, and cites source paths. | `deputy/rag/` |
| **Approval gates** | Policy approver auto-approves reads, requires sign-off for writes, honours per-tool trust overrides; deciding *whether* to ask is split from *how* to ask (CLI prompt or browser button). | `deputy/approvals.py` |
| **Audit log** | Append-only, `fsync`-ed JSONL under `data/`: planned actions, observations, approvals, denials, and exactly what any cloud escalation sent. Sensitive fields redacted. | `deputy/audit.py` |
| **Local-first routing** | The router *is* a `ChatModel`: local by default, with strictly opt-in, auditable cloud escalation that can't fire unless a cloud model was explicitly wired in. | `deputy/routing.py` |
| **Optional self-check** | A critic asks the model to grade its own draft (also under constrained decoding) before answering. | `deputy/critic.py` |
| **Local web UI** | FastAPI on loopback: chat, a live SSE action stream, in-browser approvals, and an audit view. | `deputy/web/` |
| **Reliability eval** | Runs the *real* agent over a task suite with constrained decoding on vs off, scoring success, schema validity, and a trust metric. | `deputy/eval/` |

---

## Architecture

```mermaid
flowchart TD
    User([You]) --> IF

    subgraph IF[Interfaces]
        CLI["CLI<br/>python -m deputy"]
        WEB["Web UI<br/>FastAPI · loopback only"]
        EVAL["Eval harness<br/>python -m deputy.eval"]
    end

    IF --> LOOP

    subgraph CORE[Agent core]
        LOOP["Bounded ReAct loop<br/>plan → act → observe"]
        SCHEMA["Action schema<br/>1 branch per tool + final"]
        CRITIC["Critic<br/>optional self-check"]
        LOOP --- SCHEMA
        LOOP --- CRITIC
    end

    LOOP -->|"constrained chat()"| ROUTER
    subgraph MODEL[Model layer]
        ROUTER["ModelRouter<br/>local-first"]
        OLLAMA["Ollama<br/>qwen2.5:3b + nomic-embed-text"]
        CLOUD["Cloud model<br/>opt-in only"]
        ROUTER -->|default| OLLAMA
        ROUTER -.->|"escalate + audit"| CLOUD
    end

    LOOP <-->|"tool call / observation"| REG
    subgraph TOOLS[Tools]
        REG["ToolRegistry<br/>single source of truth"]
        MCP["MCP host + adapter"]
        SRV["files · notes · calendar · web"]
        RAG["search_docs<br/>sqlite-vec + embeddings"]
        REG --- MCP --- SRV
        REG --- RAG
    end

    LOOP --> GATE
    subgraph TRUST[Trust surface]
        GATE["Approval gate<br/>writes need sign-off"]
        AUDIT["Audit log<br/>append-only JSONL"]
    end
    GATE -.->|"prompt (writes only)"| IF
    LOOP --> AUDIT
    ROUTER --> AUDIT
```

### Request → answer, step by step

1. **Goal in.** The CLI or web UI hands the loop a goal and builds an action schema from the tool
   registry — the registry is the single source of truth, so the model is only ever offered tools that
   actually exist.
2. **Plan (constrained).** The loop calls the model with that schema in the runtime's `format` field.
   Decoding is constrained, so the response is guaranteed to parse into either a **tool call** or a
   **final answer**.
3. **Gate.** If it's a tool call, the approval policy decides: reads are auto-approved; writes pause for
   a human yes/no (terminal prompt or a browser button). A denial becomes an observation and the loop
   re-plans.
4. **Act & observe.** An approved call runs (over MCP or in-process); its result — or a caught fault —
   is threaded back as the next observation. Repeat until the goal is met or the step ceiling is hit.
5. **Answer (optionally self-checked).** On a final answer, an optional critic grades the draft against
   the goal and can send it back for another pass.
6. **Audit throughout.** Every planned action, observation, approval decision, denial, and any cloud
   escalation is appended to the audit log as it happens.

A deeper treatment — each layer, the alternatives considered, and why the current design — lives in
[`docs/architecture.md`](docs/architecture.md).

---

## Quick start

**Prerequisites:** [Ollama](https://ollama.com), Python 3.12, and [`uv`](https://docs.astral.sh/uv/).

```bash
# 1. Pull the models Deputy uses (chat + embeddings). Make sure `ollama serve` is running.
ollama pull qwen2.5:3b
ollama pull nomic-embed-text

# 2. Install dependencies into a local venv.
uv sync

# 3. (optional) Build an on-device index over some documents — try the bundled sample corpus.
uv run python -m deputy.rag.index sample_workspace

# 4a. Run the CLI.
uv run python -m deputy "what is 12 * (3 + 4)?"                    # trivial demo tools
uv run python -m deputy --real "what's on my calendar for 2026-07-08?"   # real tools + RAG

# 4b. …or launch the local web UI (chat, live action stream, approvals, audit view).
uv run python -m deputy.web                                        # http://127.0.0.1:8000
```

The web server binds `127.0.0.1` only — Deputy is local-first, so the UI is never reachable off-host.

### Common flags

| Flag | CLI | Web | Meaning |
| --- | --- | --- | --- |
| `--real` | ✓ | (always on) | Use the built-in MCP servers + RAG instead of the demo tools. |
| `--model` | ✓ | ✓ | Ollama chat model tag (default `qwen2.5:3b`). |
| `--max-steps` | ✓ | ✓ | Step ceiling for the loop (default `8`). |
| `--critic` | ✓ | ✓ | Self-check the draft answer before returning it. |
| `--yes` | ✓ | — | Auto-approve writes (non-interactive scripting). |
| `--port` | — | ✓ | Loopback port for the web UI (default `8000`). |

---

## Usage examples

**Find a topic across your files and summarize with sources.** `search_files` locates the mentions,
`search_docs` pulls the passages, and the model summarizes — citing the files.

```text
$ uv run python -m deputy --real "Find everywhere sqlite-vec is mentioned across my files and summarize, with sources."
[1] plan: search_files(query='sqlite-vec')
[1] search_files -> (ok) meetings/2026-07-08-review.md ... projects/deputy.md ...
[2] plan: search_docs(query='sqlite-vec')
[2] search_docs -> (ok) [1] projects/deputy.md ... [2] meetings/2026-07-08-review.md ...
[3] finished (answered): sqlite-vec is referenced in two docs: projects/deputy.md (used for retrieval,
    storing chunk text beside vector embeddings) and meetings/2026-07-08-review.md (chosen over a flat scan).
```

**Save a note — a write, so it pauses for approval.**

```text
$ uv run python -m deputy --real "Please save a note: prep slides for the Phase 3 review"
[1] plan: add_note(text='prep slides for the Phase 3 review')
[approval] write `add_note(text='prep slides for the Phase 3 review')` — Save a short note for later.
approve? [y/N] y
[1] add_note -> (ok) Saved note at 2026-07-08T21:02:23+00:00.
[2] finished (answered): Saved your note.
```

Add `--yes` to auto-approve writes when scripting. Every one of these steps also lands in the audit log
at `data/audit.jsonl`.

---

## Reliability

Constrained decoding is the load-bearing reliability lever. The eval harness runs the **real** agent
over a 17-task suite (tool selection, multi-step reasoning, RAG, approval-gating, graceful failure,
refusal) with the action schema passed to the runtime (`grammar`) vs dropped (`freeform`), and grades
the outcomes with deterministic programmatic checks — no LLM judge.

**`qwen2.5:3b`, constrained vs unconstrained decoding:**

| Metric | freeform | grammar | Δ |
| --- | --- | --- | --- |
| Task success | 29.4% | **88.2%** | +58.8 pts |
| Schema-valid steps | 71.1% | **100.0%** | +28.9 pts |
| Loop crashes (parse failures) | 11 | **0** | −11 |
| Trust (mutations gated) | 100.0% | 100.0% | — |

The action schema constrains *shape*, not *choice*: it forces every step into a well-formed call or a
final answer, removing the malformed-JSON errors that otherwise break an agent loop by construction
rather than by prompt-tweaking. The **trust metric stays at 100% in both modes** — every attempted
write was gated regardless of how the step was decoded, because approval is enforced by the loop, not
by the model's cooperation.

Full tables (including `llama3.2:3b` and a per-category breakdown) are in
[`docs/eval_results.md`](docs/eval_results.md); the original call-level spike is in
[`docs/spike_results.md`](docs/spike_results.md). Reproduce with:

```bash
uv run python -m deputy.eval --model qwen2.5:3b
```

---

## Trust & privacy

Deputy's trust surface is a first-class part of the design, not a setting:

- **Local by default.** The model, embeddings, index, notes, calendar, and audit log are all on-device
  under `data/` (gitignored). Cloud escalation is impossible unless a cloud model is *explicitly* wired
  in — a misconfigured policy alone can never push data off the machine.
- **Approval gates on writes.** Read-only tools run freely; mutating tools (e.g. `add_note`) require a
  yes/no. Trust is configurable per tool (`allow` / `prompt` / `deny`) via `DEPUTY_TRUST`.
- **A real audit trail.** Every meaningful moment is one JSON line you can `tail` in real time.
  Known-sensitive fields are redacted; tool output is summarized to keep the log lean.
- **Opt-in cloud, fully logged.** If you enable escalation (`DEPUTY_CLOUD_ENABLED=1` **and** a key),
  every escalation records the reason, provider, model, a preview, and a SHA-256 digest of exactly what
  crossed the boundary — *before* the request leaves.

```bash
# Fully local (default): no configuration needed.
# Opt into cloud escalation for large transcripts:
export DEPUTY_CLOUD_ENABLED=1
export DEPUTY_CLOUD_API_KEY=sk-...          # required; without it, escalation stays off
export DEPUTY_TRUST="add_note=deny"         # example: never allow note writes
```

---

## Demo

Two ways to see Deputy work: run the **in-browser demo** below (no install), or record the local web UI.

### Try it in your browser — no install

[`web-demo/`](web-demo/) is a self-contained, static demo that runs Deputy's whole agent loop **entirely client-side**: a small model (Qwen2.5-0.5B) runs in your browser via WebLLM/WebGPU over a sandboxed sample corpus, streaming plan → tool → observation → answer, pausing the mutating step for an in-page **Approve / Deny**, and logging every action — nothing leaves the tab. It mirrors the privacy story the real app makes on your own machine.

- **Live demo:** `<add your deployed URL here>` — publish the `web-demo/` folder to any static host (GitHub Pages / Netlify / Vercel), no build step.
- **Run locally:** `cd web-demo && python3 -m http.server 8000`, then open `http://localhost:8000`.
- **No WebGPU?** It auto-detects and falls back to a scripted transcript so it always works; force that path with `?fallback=1`.

### Web UI capture

> **Placeholder — record and drop your own capture here.** No screenshots are committed yet.

![Deputy web UI demo](docs/media/demo.gif)

To record the demo (web UI), capture this end-to-end flow into `docs/media/demo.gif`:

1. `uv run python -m deputy.web` and open `http://127.0.0.1:8000`.
2. **Start a task** in the chat box, e.g. *"Save a note: call the dentist tomorrow, then confirm."*
3. Watch the **live action stream** — each step's plan and the tool observation appear as they happen.
4. **Hit an approval** — the mutating `add_note` call pauses with **Approve / Deny** buttons.
5. **Approve it**, and let the run finish with a final answer.
6. Switch to the **Audit** tab to show the recorded run: planned actions, the approval decision, and
   the observation.

See [`docs/media/README.md`](docs/media/README.md) for exact capture tips and the expected filenames.

---

## Project layout

```text
src/deputy/
  agent.py         bounded ReAct loop
  actions.py       action schema + parser (constrained decoding contract)
  model.py         Ollama client + ChatModel/Embedder protocols
  tools.py         Tool + ToolRegistry
  prompts.py       system prompt + transcript text
  approvals.py     approval policy + prompter seam
  audit.py         append-only JSONL audit log (write + query)
  routing.py       local-first ModelRouter + opt-in cloud client
  critic.py        optional answer self-check
  config.py        env-driven runtime config
  app.py           assembles the real agent (servers + RAG + trust surface)
  demo.py          trivial tools for driving the loop without --real
  mcp/             synchronous host + adapter over async MCP servers
  servers/         built-in stdio MCP servers (files/notes/calendar/web)
  rag/             chunk / store (sqlite-vec) / search / index
  web/             FastAPI loopback UI (SSE stream, approvals, audit)
  eval/            reliability eval harness
  spike/           the Phase-1 constrained-decoding spike
tests/             189 tests
docs/              architecture, eval results, build-in-public notes
sample_workspace/  a small corpus to index and query out of the box
```

---

## Development

```bash
uv run pytest -q        # 189 tests
uv run ruff check .     # lint
uv run mypy             # strict type-checking
```

The agent core depends only on protocols (`ChatModel`, `Embedder`, and the tool/approval/event seams),
so the whole suite runs offline against fakes and never needs a live Ollama.

Packaging Deputy as a standalone desktop command is documented in
[`docs/packaging.md`](docs/packaging.md).

---

## Status & license

Working end-to-end across its core phases (agent core, MCP tools, on-device RAG, trust surface, web UI,
and a reliability eval), with 189 passing tests and clean `ruff` + strict `mypy`. It is a personal
project and a focused demonstration rather than a supported product.

Licensed under the [MIT License](LICENSE).
