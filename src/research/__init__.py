"""Lohi-Research: multi-agent, RAG-based research subsystem for Indian equities.

This package hosts the Orchestrator, Sub_Agents, RAG pipeline, memory layers,
Guardrail_Layer, Judge_LLM, validators, versioned prompts, snapshot cache,
and worker processes described in the Lohi-Research design (see
`.kiro/specs/lohi-research-dashboard/design.md`, §3). It sits alongside the
existing LOHI-TRADE stack (Commander, Soldier, gateway) and integrates with
it rather than replacing it.
"""
