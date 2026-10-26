"""ZDM-44: a fresh beer clone has a run layout, an env contract, and a reported missing catalog."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_run_layout_keeps_secrets_and_the_catalog_out_of_the_image() -> None:
    dockerfile = _text("Dockerfile")
    compose = _text("docker-compose.yml")
    ignore = _text(".dockerignore")
    assert "COPY .env" not in dockerfile
    assert "COPY data" not in dockerfile
    assert "python:3.12-slim" in dockerfile
    assert "8090:8090" in compose
    assert 'HOST: "0.0.0.0"' in compose
    assert "http://host.docker.internal:8080" in compose
    assert "host.docker.internal:host-gateway" in compose
    assert "./data:/app/data" in compose
    assert "container_name: demo-beer-sample" in compose
    url_lines = [
        line
        for line in compose.splitlines()
        if "ZEUS_URL" in line and not line.strip().startswith("#")
    ]
    assert url_lines
    assert all(":8080" in line and ":9091" not in line for line in url_lines)
    assert ".env" in ignore.splitlines()
    assert "data" in ignore.splitlines()


def test_env_contract_names_the_beer_user_and_keeps_the_password_empty() -> None:
    example = _text(".env.example")
    gitignore = _text(".gitignore")
    config = json.loads(_text("config.json"))
    assert "HOST=127.0.0.1" in example
    assert "ZEUS_USERNAME=tester_beer" in example
    assert "ZEUS_PASSWORD=" in example
    assert "LLM_API_KEY=" in example
    assert "LLM_BASE_URL=https://api.x.ai/v1" in example
    assert "LLM_MODEL=grok-4.5-latest" in example
    assert "ZEUS_URL=http://localhost:8080" in example
    assert "data/" in gitignore.splitlines()
    assert ".env" in gitignore.splitlines()
    assert config["zeus"]["username"] == "tester_beer"
    assert config["zeus"]["password_env"] == "ZEUS_PASSWORD"
    assert config["zeus"]["url"] == "http://localhost:8080"
    assert config["chat_requests_dir"] == "data/chat_requests"
    assert config["llm"]["base_url"] == "LLM_BASE_URL"
    assert config["llm"]["model"] == "LLM_MODEL"
    assert config["llm"]["api_key_env"] == "LLM_API_KEY"
    assert config["client_floor"] == "client-floor-6.1"
    assert config["settings"]["durable_sessions"] is False


def test_pour_reports_a_missing_catalog_and_syncs_the_scope_file() -> None:
    main = _text("main.py")
    search = main.split("async def _run_search", 1)[1].split("async def healthz", 1)[0]
    assert "await rt.catalog.sync()" in main
    assert "await rt.catalog.load_for_turn(cfg.settings.mode, target=cfg.target)" in search
    call = search.split("await rt.catalog.load_for_turn", 1)[1]
    assert "base_id" not in call.split("run_turn", 1)[0]
    assert "run_turn(" in call


def test_pin_copy_matches_the_scope_file_and_skips_a_bad_base_id(tmp_path: Path) -> None:
    from main import _copy_live_pin

    scope = tmp_path / "beer-sample__default"
    scope.mkdir()
    body = {
        "_format": "zeus.chat_request.v2",
        "_lineage": {"base_id": "base-6.1"},
        "verbs": [],
    }
    scope_file = scope / "chat_request_analytics_v2.json"
    scope_file.write_text(json.dumps(body), encoding="utf-8")
    dest = _copy_live_pin(tmp_path, "beer-sample", "_default", "analytics")
    assert dest == tmp_path / "chat_request_analytics_base-6.1.json"
    assert dest is not None
    assert dest.read_bytes() == scope_file.read_bytes()
    again = _copy_live_pin(tmp_path, "beer-sample", "_default", "analytics")
    assert again == dest

    broken = tmp_path / "other__default"
    broken.mkdir()
    (broken / "chat_request_analytics_v2.json").write_text(
        json.dumps({"_lineage": {"base_id": "../escape"}}),
        encoding="utf-8",
    )
    assert _copy_live_pin(tmp_path, "other", "_default", "analytics") is None
    assert _copy_live_pin(tmp_path, "missing", "_default", "analytics") is None
