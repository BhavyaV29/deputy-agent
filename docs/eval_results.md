# Eval: task-level reliability under constrained decoding

- **Date:** 2026-07-08
- **Models:** `qwen2.5:3b`, `llama3.2:3b` (via Ollama)
- **Suite:** 17 end-to-end tasks spanning tool selection, multi-step reasoning, RAG retrieval, approval-gating, graceful failure, and refusal
- **Primary axis:** constrained decoding on (`grammar`) vs off (`freeform`) — the action schema is passed to Ollama's `format` field, or dropped, exactly as in the Phase-1 spike, but now measured over whole tasks rather than single calls
- **Sampling:** temperature 0.0, seed 0, fixed across configs for reproducibility
- **Grading:** deterministic programmatic checks (answer content/regex, tool selection, approval-gating events); no LLM judge
- **Schema-valid:** the step parsed back into a typed action the loop can run (`parse_action` succeeds) — the task-level analog of the spike's call-level check, and precisely the property whose absence breaks the loop
- **Trust metric:** fraction of attempted mutating calls that stayed behind the approval gate; any ungated mutation counts as a failure

## Results

| Model | Decoding | Success | Tool-select | Schema-valid | Avg steps | Avg latency | Tokens/s | Trust | Crashes |
| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |
| `qwen2.5:3b` | grammar | 88.2% | 82.4% | 100.0% | 2.4 | 1.70s | 20.8 | 100.0% | 0 |
| `qwen2.5:3b` | freeform | 29.4% | 88.2% | 71.1% | 2.5 | 1.53s | 25.8 | 100.0% | 11 |
| `llama3.2:3b` | grammar | 88.2% | 88.2% | 100.0% | 2.2 | 1.24s | 25.7 | 100.0% | 0 |
| `llama3.2:3b` | freeform | 82.4% | 94.1% | 94.3% | 2.1 | 1.33s | 20.9 | 100.0% | 2 |

### Success by category

| Category | `qwen2.5:3b` grammar | `qwen2.5:3b` freeform | `llama3.2:3b` grammar | `llama3.2:3b` freeform |
| --- | --- | --- | --- | --- |
| tool_selection | 100.0% | 25.0% | 100.0% | 100.0% |
| multi_step | 33.3% | 0.0% | 33.3% | 33.3% |
| rag | 100.0% | 33.3% | 100.0% | 100.0% |
| approval_gating | 100.0% | 66.7% | 100.0% | 100.0% |
| graceful_failure | 100.0% | 0.0% | 100.0% | 100.0% |
| refusal | 100.0% | 50.0% | 100.0% | 50.0% |

## Interpretation

- **`qwen2.5:3b`.** Constrained decoding held schema validity at 100.0% vs 71.1% unconstrained (+28.9 pts), with task success 88.2% vs 29.4% (+58.8 pts). Unconstrained runs raised out of the loop 11 time(s) vs 0 constrained — the parse failures that constrained decoding removes by construction. Latency was 1.70s vs 1.53s per call. The trust metric stayed at 100.0% in both modes (3 mutating call(s) attempted, 0 ungated): every write was gated regardless of how the step was decoded.
- **`llama3.2:3b`.** Constrained decoding held schema validity at 100.0% vs 94.3% unconstrained (+5.7 pts), with task success 88.2% vs 82.4% (+5.9 pts). Unconstrained runs raised out of the loop 2 time(s) vs 0 constrained — the parse failures that constrained decoding removes by construction. Latency was 1.24s vs 1.33s per call. The trust metric stayed at 100.0% in both modes (3 mutating call(s) attempted, 0 ungated): every write was gated regardless of how the step was decoded.
- **Reading tool-selection.** Selection accuracy is scored over the tools the model *planned*, independent of whether the task ultimately succeeded. An unconstrained run often plans the right first tool and only then emits an unparseable step, so its tool-selection can match or exceed the constrained run even as task success collapses — schema validity, crashes, and success are where the cost of dropping the grammar actually lands.
