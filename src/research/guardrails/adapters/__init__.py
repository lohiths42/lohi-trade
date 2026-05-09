"""Opt-in Guardrail adapters (design §3.6, Req 16.8).

Wraps third-party guardrail frameworks behind the same `Guardrail`
protocol: LangChain Runnable + OutputParser, Guardrails-AI `Guard`,
and NVIDIA NeMo-Guardrails Rails. Users choose an adapter via
`research.guardrails.adapter` in `config/settings.yaml`; the default
remains the framework-light `PydanticGuardrail`.
"""
