# Spike: tool-call reliability under constrained decoding

- **Model:** `qwen2.5:3b` (via Ollama)
- **Date:** 2026-07-08
- **Prompts:** 24 labeled requests x 3 repetitions per condition
- **Mechanism:** Ollama structured outputs — the `format` field set to the tool-call JSON Schema (constrained) vs. omitted (unconstrained)
- **Sampling:** temperature 1.0, seeds shared across conditions
- **Schema-valid:** output parses as JSON and matches the tool-call schema (known tool + exactly its typed arguments)
- **Tool-selection:** the chosen tool matches the labeled expectation

| Condition | Schema-valid | Tool-selection | Avg latency | Tokens/s | Samples |
| --- | --- | --- | --- | --- | --- |
| unconstrained | 98.6% | 90.3% | 1.35s | 18.7 | 72 |
| constrained | 100.0% | 91.7% | 1.32s | 18.5 | 72 |

**Verdict.** Bet HOLDS: constrained decoding reached 100.0% schema-valid vs 98.6% unconstrained (+1.4%).

## Reading the results

- The `format` schema constrains *shape*, not *choice*: it forces every constrained sample to be a well-formed call to some tool, which is why schema validity is pinned at 100%. It does not decide *which* tool fits, so tool-selection tracks the model's routing ability and is essentially the same in both conditions.
- The unconstrained gap is small — this model is a capable tool-caller — but non-zero, and the failures are schema violations (malformed or over-decorated JSON). That is exactly the class of error that breaks an agent loop, and constrained decoding removes it by construction rather than by prompt engineering.
