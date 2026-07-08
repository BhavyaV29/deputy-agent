# Build-in-public drafts

Drafts for sharing Deputy while job-hunting. Technical, specific, honest — lead with the interesting
bits, skip the hype. The links below are filled in, but the demo URL is the **expected Render Static
Site URL (`https://deputy-web-demo.onrender.com`) — confirm it after your first deploy** and update it
here if your service name differs. Attach the demo capture from [`media/`](media/README.md) before posting.

All numbers below are from this repo's [eval](eval_results.md) and test suite — keep them accurate if
you edit.

---

## 1. X / Twitter thread

**1/**
I built Deputy: a private AI agent that runs entirely on your own machine, works your own files, and
asks before it does anything that writes.

No cloud, no API keys. Nothing leaves the device unless you opt in.

A thread on how it works — and the one decision that made it reliable.

**2/**
The hard part of a *small local* agent isn't intelligence, it's reliability.

A 3B model constantly emits *almost*-valid JSON — an extra sentence, a trailing comma — and one bad step
crashes the whole loop. That's the wall you hit first.

**3/**
The fix: constrained decoding.

Every step is decoded against a JSON schema (one branch per tool + a final-answer branch), passed to the
model runtime so it can *only* produce a valid tool call or an answer.

qwen2.5:3b, same suite:
• task success 29% → 88%
• schema-valid steps 71% → 100%
• loop crashes 11 → 0

**4/**
The subtle part: the schema constrains *shape*, not *choice*. It removes malformed-JSON failures by
construction — not by prompt-tweaking or retries — while routing quality still tracks the model.

Boring lever, huge payoff.

**5/**
Safety is enforced by the loop, not the model's goodwill.

Reads run free; writes pause for a yes/no you actually see. Every step appends to a plain-text audit log
you can `tail` live. In the eval, writes stayed 100% gated *even when decoding was degraded* — because
the gate isn't the model's job.

**6/**
The stack, all Python:
• Ollama (qwen2.5:3b) for the local model
• tools over MCP (files, notes, calendar, opt-in web)
• on-device RAG: sqlite-vec + nomic-embed-text, answers cite their source files
• FastAPI loopback UI with a live action stream + in-browser approvals

**7/**
It's tested like a product, not a demo: 199 tests, all offline. Every external dep (model, MCP, network)
sits behind a protocol with a fake, so the suite runs with no Ollama — and a separate eval runs the
*real* agent to measure reliability.

**8/**
Writeup, architecture doc, and the eval methodology are in the repo:
https://github.com/BhavyaV29/deputy-agent

Demo (start a task → live action stream → approval gate → audit view):
https://deputy-web-demo.onrender.com

Happy to talk through any of the design decisions.

---

## 2. LinkedIn post

I spent the last stretch building **Deputy** — a private, on-device AI agent, written in Python — and I
want to share the one engineering decision that made it actually work.

**The premise:** an assistant that runs a small local model (via Ollama), can search and act on your own
files, and — crucially — asks before it does anything that writes. No cloud dependency; nothing leaves
your machine unless you explicitly opt in.

**The problem:** small local models are surprisingly capable, but they're unreliable at *format*. They'll
emit almost-valid JSON — an extra sentence here, a stray comma there — and in an agent loop, one
malformed step crashes the whole run. That's the real wall, not reasoning.

**The fix:** constrained decoding. Every step is decoded against a JSON schema (one branch per available
tool, plus a final-answer branch) passed straight to the model runtime, so the output can only ever be a
well-formed tool call or an answer. Measured on the same task suite with qwen2.5:3b:

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
and a loopback FastAPI UI with a live action stream and in-browser approvals. 199 tests, all runnable
offline against fakes, plus a reliability eval that exercises the real agent.

Writeup and architecture notes here: https://github.com/BhavyaV29/deputy-agent

Always happy to talk agents, local models, or reliability engineering.

---

## 3. Short standalone post (X or LinkedIn)

Constrained decoding is the most underrated reliability lever for local-model agents.

I passed a JSON schema (one branch per tool + a final-answer branch) to the runtime so my on-device
agent can only ever emit a valid tool call or an answer.

qwen2.5:3b, same task suite:
• task success 29% → 88%
• schema-valid steps 71% → 100%
• loop crashes 11 → 0

It fixes *shape*, not *choice* — so you remove the malformed-output failures without touching the model's
judgment. Writeup: https://github.com/BhavyaV29/deputy-agent

---

### Posting notes

- **Attach the demo.** The thread/post is far stronger with the capture from `docs/media/` — the approval
  pause is the moment that lands.
- **Numbers are real.** They come from `docs/eval_results.md` (qwen2.5:3b, grammar vs freeform). Don't
  round them up.
- **Tone check.** Keep it matter-of-fact. The reliability delta and the trust story sell themselves.
