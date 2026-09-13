from pathlib import Path

from smart_service_agent.config import get_settings


def test_loads_selected_environment_file(monkeypatch) -> None:
    config_file = Path(__file__).parents[1] / "config" / "test.env"
    monkeypatch.setenv("APP_CONFIG_FILE", str(config_file))
    get_settings.cache_clear()

    settings = get_settings()

    assert settings.app_env == "test"
    assert settings.app_port == 8001
    assert settings.app_reload is False
    assert settings.mongodb_database == "smart_service_agent_test"
    assert settings.mongodb_timeout_ms == 3000

    get_settings.cache_clear()
