# Lohi-Research Refusal Policy

Lohi-Research is a **research assistant**, not a trading assistant. It
produces retrieval-grounded research briefs with inline citations; it
does not recommend trades, name price targets, or take actions on
accounts. This document describes that policy, enumerates what the
system refuses and what it does, and explains how the policy is
enforced end to end (Req 16.29, design §3.13, §10.1).

The canonical text of the policy lives in
[`src/research/guardrails/refusal_policy.py`](../../src/research/guardrails/refusal_policy.py)
as the `REFUSAL_POLICY_BLOCK` constant. This doc is the human-readable
companion and is referenced from the UI `RefusalBanner` component.

---

## 1. Policy block (verbatim)

The following text is the exact value of
`REFUSAL_POLICY_BLOCK` in `src/research/guardrails/refusal_policy.py`.
Any change to it propagates automatically to every Sub_Agent prompt
and to the dashboard `RefusalBanner`.

```
Lohi-Research is a research assistant. It does not provide buy/sell/hold recommendations, price targets, trade suggestions, order placement, fund transfers, or code execution.
All answers are grounded in retrieved source documents with inline citations.
```

---

## 2. What Lohi-Research refuses

The system will decline the following categories of request and will
**not** produce the requested output:

- **Buy / sell / hold recommendations** — no "should I buy RELIANCE?",
  no "is TCS a hold right now?", no directional advice for individual
  symbols or baskets.
- **Price targets** — no 12-month target, no intraday target, no
  fair-value number dressed as advice.
- **Trade suggestions** — no "good entry here", no "wait for a
  pullback to X", no option strategies, no pair trades.
- **Order placement instructions** — no broker commands, no "place a
  limit order at Y", no basket-upload templates.
- **Fund transfer actions** — no "move funds to your margin account",
  no bank-transfer workflows.
- **Arbitrary code execution** — no shell commands, no script
  generation intended to execute against broker APIs, no SQL that
  mutates state.

## 3. What Lohi-Research does

The system **will**:

- Produce **retrieval-grounded research briefs** with inline
  `[cite:<chunk_id>]` markers that resolve to specific document chunks
  in the Vector_Store (Req 3.11, Req 14.1).
- Emit **structured sections** per brief: `summary`, `thesis`,
  `risks`, `financial_highlights`, `management_commentary`,
  `technical_view`, `peers`, `macro_context` (Req 1.5).
- Score every brief with the `Judge_LLM` for groundedness, citation
  coverage, contradiction, and off-policy content; set
  `safe_to_display=false` when a brief fails those checks (Req 16.16,
  Req 16.17).
- Enforce the refusal policy at the prompt, gateway, and UI layers so
  the policy is visible and consistent wherever the system is used.

---

## 4. Enforcement pipeline

The refusal policy is enforced in the following order on every
request:

1. **Input guardrail (`Guardrail_Layer`)** — user prompts are scanned
   by the `PydanticGuardrail` against the versioned ruleset at
   [`src/research/guardrails/rules/v1.yaml`](../../src/research/guardrails/rules/v1.yaml).
   Prompts that match refusal patterns (rule IDs in the `RP-###`
   family) are rejected before reaching the Orchestrator, with
   `action=refuse` and the matching `rule_id` recorded in
   `research_guardrail_decisions` (Req 16.1–16.4, Req 16.11).
2. **Sub_Agent prompts** — every Sub_Agent template under
   `src/research/prompts/v1/` embeds `{{REFUSAL_POLICY_BLOCK}}` inside
   its `<refusal_policy>` fenced section (design §3.9, Req 16.6). The
   loader freezes prompts into immutable dataclasses so runtime
   mutation is impossible.
3. **Judge_LLM (online)** — after the Report_Synthesizer produces a
   brief, the `Judge_LLM` scans its content for off-policy findings.
   When any are detected, it sets `safe_to_display=false` on the
   `JudgeReport`, which triggers a single re-synthesis pass; if that
   also fails, the brief is labelled `quality=low` and the unsupported
   sections are redacted (Req 16.12, Req 16.16, Req 16.18, Req 16.19).
4. **Rule-based judge (offline)** — when `LOHI_RESEARCH_OFFLINE=true`,
   `src/research/judge/rule_based.py` runs the refusal classifier
   regex (same `RP-###` rule IDs) plus citation-coverage and
   numeric-fidelity checks instead of invoking a cloud Judge. The
   `JudgeReport` shape is identical, so downstream code does not
   branch (Req 16.22).
5. **UI** — the [`RefusalBanner`](../../Lohi-TRADE%20Web%20App%20Design/src/components/research/RefusalBanner.tsx)
   component surfaces the policy whenever `safe_to_display=false` on
   a brief, a run returns a refusal, or the guardrail fires on input
   (design §3.13, Req 16.29).

A single user prompt that violates the policy therefore fails fast at
step 1, without reaching any LLM. A brief that drifts off-policy
during synthesis is caught at step 3 (or step 4 offline) and either
repaired via re-synthesis or redacted before display.

---

## 5. `RefusalResult` shape

Every refusal is a validated `RefusalResult` Pydantic model. Its
fields are stable across the Guardrail_Layer, the refusal classifier,
and the gateway response envelope:

```python
class RefusalResult(BaseModel):
    reason: str         # machine-readable snake_case reason
    rule_id: str        # matches an id in rules/v1.yaml (e.g. "RP-001")
    user_message: str   # defaults to REFUSAL_POLICY_BLOCK
```

- `reason` — internal, used for metrics and dashboard filtering (for
  example `"trade_advice"`, `"jailbreak_attempt"`). Not user-facing.
- `rule_id` — the identifier of the rule that fired. Trace it back to
  the exact row in
  [`src/research/guardrails/rules/v1.yaml`](../../src/research/guardrails/rules/v1.yaml).
  The v1 ruleset defines:

  | rule_id | name | phase | action |
  |---|---|---|---|
  | `JB-001` | `system_prompt_override` | input | refuse |
  | `JB-002` | `prompt_leak` | input | refuse |
  | `RP-001` | `trade_advice` | input | refuse |
  | `TA-001` | `tool_allowlist` | output | modify |
  | `PII-001` | `pan_redaction` | output | modify |

- `user_message` — user-visible text. Defaults to
  `REFUSAL_POLICY_BLOCK`, which is what the dashboard displays unless
  a caller has a strictly narrower message to surface.

The `refuse(reason, rule_id, user_message=None)` helper in
`refusal_policy.py` constructs a canonical `RefusalResult` — every
call site should prefer it over building the model directly.

---

## 6. Updating the policy

The refusal policy is defined in **exactly one place**:

1. Edit `REFUSAL_POLICY_BLOCK` in
   [`src/research/guardrails/refusal_policy.py`](../../src/research/guardrails/refusal_policy.py).
2. If the change introduces a new refusal category, add a matching
   `RP-###` rule to
   [`src/research/guardrails/rules/v1.yaml`](../../src/research/guardrails/rules/v1.yaml).
3. Keep this document in sync with the policy text.

Because every Sub_Agent template interpolates
`{{REFUSAL_POLICY_BLOCK}}` at load time and the `RefusalBanner`
component reads the same constant via the gateway's refusal payload,
the edit propagates to both the model prompts and the UI banner
without any additional plumbing.

---

## See also

- [`docs/research/PROVIDERS.md`](PROVIDERS.md) — per-provider
  data-locality notes; informs which models run where the refusal
  policy is evaluated.
- [`docs/CONFIGURATION.md`](../CONFIGURATION.md#lohi-research) — the
  `research.guardrails.*` and `research.judge.*` config keys that
  govern enforcement.
- [`src/research/guardrails/refusal_policy.py`](../../src/research/guardrails/refusal_policy.py)
  — canonical `REFUSAL_POLICY_BLOCK`, `RefusalResult`, and `refuse()`.
- [`src/research/guardrails/rules/v1.yaml`](../../src/research/guardrails/rules/v1.yaml)
  — versioned regex ruleset and `rule_id` registry.
