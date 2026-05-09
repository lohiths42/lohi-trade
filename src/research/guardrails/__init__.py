"""Guardrail_Layer — input/output filtering for every Sub_Agent (design §3.6).

Filters every user prompt and every Sub_Agent output against a versioned
ruleset covering prompt-injection detection, system-prompt-override
rejection, tool-allowlist enforcement, rate limiting, PII redaction, and
banned-content blocking (Req 16.1–16.11). Default implementation is
framework-light (`PydanticGuardrail`); LangChain, Guardrails-AI, and
NeMo-Guardrails are supported as opt-in adapters behind the same contract.
"""
