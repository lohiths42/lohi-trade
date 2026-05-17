def test_import_config_module():
    # Smoke test: importing should not raise and should expose load_config/get_config
    import importlib

    cfg = importlib.import_module("src.utils.config")
    assert hasattr(cfg, "load_config")
    assert hasattr(cfg, "get_config")
