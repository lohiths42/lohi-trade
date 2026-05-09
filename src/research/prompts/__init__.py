"""Versioned, immutable-at-runtime prompt templates (design §3.9).

Hosts every Sub_Agent prompt and the Judge prompt as versioned files under
`prompts/v<N>/`. Templates enforce closed-book retrieval-grounded answering,
cite-every-claim, and the `Refusal_Policy`. The `loader` module loads a
template by version and freezes it into an immutable dataclass so prompts
cannot be mutated at runtime (Req 16.6, 16.25).
"""
