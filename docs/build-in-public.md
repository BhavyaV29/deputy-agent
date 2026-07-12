# Build-in-public drafts

Staged, ready-to-post launch content for Deputy — technical, specific, honest. Lead with the interesting
bits, skip the hype. This is Deputy's canonical in-repo copy; a separate cross-project posting queue may
stage these next to other work, so keep this file focused on Deputy alone.

Two links belong in every post:

- **Live demo (no install):** <https://deputy-web-demo.onrender.com>
- **Repo:** <https://github.com/BhavyaV29/deputy-agent>

The live demo opens with a scripted browser walkthrough over a sandboxed sample corpus — plan → tool →
observation → answer, with the mutating step paused for an in-page **Approve / Deny**. The browser-side
tools and gate are live; only the model decisions are pre-recorded. Optional experimental WebGPU mode
downloads a WebLLM model and uses prompted, tolerantly parsed JSON rather than runtime-constrained
decoding. No prompt or sample data is sent to a backend. All evaluation numbers below apply to the real
Python/Ollama app and come from this repo's [eval](eval_results.md) and test suite.

Suggested cadence: post **Stage 1** first, then **Stage 2** a few days later once people have clicked
through, and **Stage 3** to close the arc. Each stage stands alone, so order isn't load-bearing.

---

## Stage 1 — Launch

### LinkedIn

I built **Deputy**: a private AI agent that runs entirely on your own machine.

It works your own files, calendar, and notes, runs a small local model through Ollama, and — the part I
care most about — asks before it does anything that writes. No cloud, no API keys; nothing leaves your
device unless you explicitly opt in.

You can walk through the whole loop in your browser right now, no install. The default demo uses
pre-recorded model decisions over a sandboxed sample corpus, while its tools, observations, approval
pause, and audit run live. An optional experimental mode downloads a WebLLM model for on-device WebGPU
inference; no prompt or sample data is sent to a backend.

▶ Live demo: https://deputy-web-demo.onrender.com
Code + architecture notes: https://github.com/BhavyaV29/deputy-agent

More soon on the one decision that made a 3B local model reliable enough to trust in a loop.

### X / Twitter

I built Deputy: a private AI agent that runs entirely on your own machine.

Works your own files, runs a small local model, and asks before it writes anything. No cloud, no API
keys — nothing leaves the device unless you opt in.

Try the browser walkthrough, no install — scripted by default, with optional experimental WebGPU:
▶ https://deputy-web-demo.onrender.com
Code: https://github.com/BhavyaV29/deputy-agent

---

## Stage 2 — Technical deep-dive

### X / Twitter thread

**1/**
Deputy is a private AI agent that runs a small model entirely on your machine. The hard part wasn't
intelligence — it was reliability.

Here's the one decision that made a 3B model trustworthy inside an agent loop. 🧵

**2/**
The wall you hit first with a *small local* agent isn't reasoning, it's format.

A 3B model constantly emits *almost*-valid JSON — an extra sentence, a trailing comma — and one bad step
crashes the whole loop.

**3/**
The fix in the Python/Ollama app: constrained decoding.

Every step is decoded against a JSON schema (one branch per tool + a final-answer branch), passed to the
model runtime so it can *only* produce a valid tool call or an answer.

qwen2.5:3b, same suite:
• task success 29% → 88%
• schema-valid steps 71% → 100%
• loop crashes 11 → 0

**4/**
The subtle part: the schema constrains *shape*, not *choice*. It removes malformed-JSON failures by
construction — not by prompt-tweaking or retries — while which tool to call still tracks the model.

Boring lever, huge payoff.

**5/**
Safety is enforced by the loop, not the model's goodwill.

Confined local reads run free; writes and external calls pause for a yes/no you actually see. Every step
appends to a plain-text audit log you can `tail` live. In the eval, writes stayed 100% gated *even when
decoding was degraded* — because the gate isn't the model's job.

**6/**
The stack, all Python:
• Ollama (qwen2.5:3b) for the local model
• tools over MCP (files, notes, calendar, opt-in web)
• on-device RAG: sqlite-vec + nomic-embed-text, answers cite their source files
• FastAPI loopback UI with a live action stream + in-browser approvals

**7/**
It's tested like a product, not a demo: 207 tests run offline, plus one opt-in Ollama integration test.
Every external dep (model, MCP, network) sits behind a protocol with a fake, so the default suite runs
with no Ollama — and a separate eval runs the *real* Python agent to measure reliability.

**8/**
Try the browser walkthrough (scripted by default; optional experimental WebGPU):
https://deputy-web-demo.onrender.com

Writeup, architecture doc, and the eval methodology:
https://github.com/BhavyaV29/deputy-agent

Happy to talk through any of the design decisions.

### LinkedIn

I spent the last stretch building **Deputy** — a private, on-device AI agent, written in Python — and I
want to share the one engineering decision that made it actually work.

**The premise:** an assistant that runs a small local model (via Ollama), can search and act on your own
files, and — crucially — asks before it does anything that writes. No cloud dependency; nothing leaves
your machine unless you explicitly opt in.

**The problem:** small local models are surprisingly capable, but they're unreliable at *format*. They'll
emit almost-valid JSON — an extra sentence here, a stray comma there — and in an agent loop, one
malformed step crashes the whole run. That's the real wall, not reasoning.

**The fix in the Python/Ollama app:** constrained decoding. Every step is decoded against a JSON schema
(one branch per available tool, plus a final-answer branch) passed straight to the model runtime, so the
output can only ever be a well-formed tool call or an answer. Measured on the same task suite with
qwen2.5:3b:

• End-to-end task success: 29% → 88%
• Schema-valid steps: 71% → 100%
• Loop crashes from parse failures: 11 → 0

The insight I keep coming back to: the schema constrains *shape*, not *choice*. It eliminates a whole
class of failure by construction, while the model's judgment about *which* tool to use is untouched.

I also treated the trust surface as a first-class feature, not a toggle: approval gates on any write, an
append-only audit log you can read in plain text, and local-first routing where cloud escalation is
impossible unless you explicitly wire it in — and fully logged when you do. In the eval, every attempted
write stayed behind the gate even when decoding was deliberately degraded, because approval is enforced
by the loop rather than requested from the model.

Rounding it out: tools over MCP, on-device retrieval with sqlite-vec and citations back to source files,
and a loopback FastAPI UI with a live action stream and in-browser approvals. 207 tests run offline
against fakes, with one opt-in Ollama integration test, plus a reliability eval that exercises the real
Python agent.

Try the scripted browser walkthrough, no install: https://deputy-web-demo.onrender.com
Code and architecture notes: https://github.com/BhavyaV29/deputy-agent

Always happy to talk agents, local models, or reliability engineering.

---

## Stage 3 — What I learned

### LinkedIn

The most useful thing I learned building **Deputy** (a local-model AI agent): with small models,
reliability is a *format* problem before it's an *intelligence* problem.

A 3B model is smart enough to pick the right tool. What it can't do reliably is emit clean JSON on every
single step — and in an agent loop, one malformed step crashes the whole run. I spent far less time on
prompting than I expected, and far more on making bad output impossible.

The lever that worked in the Python/Ollama app: constrained decoding. Pass a JSON schema to the runtime
(one branch per tool + a final-answer branch) so the model can only ever produce a valid call or an
answer. Same task suite, qwen2.5:3b: task success 29% → 88%, schema-valid steps 71% → 100%, loop crashes
11 → 0.

The framing I keep reusing: it constrains *shape*, not *choice*. You remove a whole class of failure by
construction, without touching the model's judgment about which tool to use.

Second lesson: put safety in the loop, not the prompt. Writes pause for a human yes/no and every action
lands in an append-only audit log — so the guarantee holds even when the model's output degrades, not
just when it cooperates.

Try the scripted browser walkthrough (no install): https://deputy-web-demo.onrender.com
Code: https://github.com/BhavyaV29/deputy-agent

### X / Twitter

Building a local-model agent taught me: reliability is a *format* problem before it's an *intelligence*
problem.

A 3B model picks the right tool fine. It just can't emit clean JSON every step — and one bad step crashes
the loop.

In the Python/Ollama app, constrained decoding fixed it (shape, not choice): task success 29% → 88%.

Demo: https://deputy-web-demo.onrender.com
Code: https://github.com/BhavyaV29/deputy-agent

---

## Bonus — one-liner (single post, either platform)

Constrained decoding is the most underrated reliability lever for local-model agents.

In Deputy's Python/Ollama app, I pass a JSON schema (one branch per tool + a final-answer branch) to the
runtime so my on-device agent can only ever emit a valid tool call or an answer.

qwen2.5:3b, same task suite:
• task success 29% → 88%
• schema-valid steps 71% → 100%
• loop crashes 11 → 0

It fixes *shape*, not *choice* — you remove the malformed-output failures without touching the model's
judgment.

Try it: https://deputy-web-demo.onrender.com · Code: https://github.com/BhavyaV29/deputy-agent

---

### Posting notes

- **Two links, every post.** The live demo (<https://deputy-web-demo.onrender.com>) and the repo
  (<https://github.com/BhavyaV29/deputy-agent>) should both be present — the demo is the hook, the repo
  is the proof.
- **Lead with the demo.** People clicking through and hitting the approval pause themselves lands harder
  than any screenshot or canned clip — point them straight at the live demo link.
- **Numbers are real.** They come from `docs/eval_results.md` (qwen2.5:3b, grammar vs freeform). Don't
  round them up.
- **Tone check.** Keep it matter-of-fact. The reliability delta and the trust story sell themselves.
