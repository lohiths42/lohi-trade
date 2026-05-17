def test_research_providers_registry_import():
    import importlib

    pkg = importlib.import_module("src.research.providers")
    # Ensure registry module exists and can be imported
    reg = importlib.import_module("src.research.providers.registry")
    # registry exposes LLM_FACTORIES / get_llm / register_llm etc.
    assert any(
        hasattr(reg, name)
        for name in ("LLM_FACTORIES", "get_llm", "register_llm", "EMBEDDINGS_FACTORIES")
    )
