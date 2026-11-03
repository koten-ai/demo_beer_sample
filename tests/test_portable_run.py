"""ZDM-44: a fresh beer clone has a run layout, an env contract, and a reported missing catalog."""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def _text(name: str) -> str:
    return (ROOT / name).read_text(encoding="utf-8")


def test_pour_keeps_joined_place_and_sends_the_question() -> None:
    html = _text("static/index.html")
    main = _text("main.py")
    readme = _text("README.md")
    assert "function subline(card, searching)" in html
    assert 'params.set("entity"' not in html
    assert "Entity type:" not in main
    assert "joined entity" in readme
    assert "def _joined_brewery" in main


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
    assert "./.env:/app/.env:ro" in compose
    assert "env_file:" not in compose
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
    search = main.split("async def _search_turn", 1)[1].split("async def _run_search", 1)[0]
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


_CDN_TRACE = (
    "https://koten-static-cdn.nyc3.cdn.digitaloceanspaces.com/"
    "zeus_client_chat_trace/latest/zeus_client_chat_trace.js"
)
_V2_TOOLS = [
    "describe",
    "explain",
    "get",
    "find",
    "set",
    "order",
    "enrich",
    "project",
    "traverse",
    "search",
    "analyze",
    "return",
]


def test_page_loads_the_cdn_trace_and_wires_it_on_pour() -> None:
    html = _text("static/index.html")
    assert _CDN_TRACE in html
    assert "/static/zeus_client_chat_trace.js" not in html
    assert "pageDebugEnabled" not in html
    assert 'params.set("debug", debug)' in html
    config = html.split("window.ZeusTraceConfig", 1)[1].split("</script>", 1)[0]
    assert "http://zeus-dev.local:9091" in config
    assert "toolOrder" not in config
    assert "text_search" not in config
    assert "enabled" not in config
    assert "pipeline" not in config
    search = html.split("function search(", 1)[1].split("function escapeHtml", 1)[0]
    assert "appendTraceCard" in search
    assert "openDebugPanel" in search
    assert "/api/search?" in search
    load_list = html.split("function loadList(", 1)[1].split("function goPage", 1)[0]
    assert "appendTraceCard" not in load_list
    assert "/api/beers" in load_list or "/api/breweries" in load_list
    beers = html.split("function loadList(", 1)[0]
    assert "appendTraceCard" not in beers


def test_readme_documents_the_debug_pour_trace() -> None:
    readme = _text("README.md")
    assert "?debug=true" in readme
    assert "lightning toggle" in readme
    assert "zeus_client_chat_trace/latest" in readme
    assert "do not mount a trace card" in readme


def test_debug_query_enabled_uses_the_truthy_set() -> None:
    from pour_trace import debug_query_enabled

    assert debug_query_enabled("true") is True
    assert debug_query_enabled("TRUE") is True
    assert debug_query_enabled("1") is True
    assert debug_query_enabled("yes") is True
    assert debug_query_enabled("on") is True
    assert debug_query_enabled(True) is True
    assert debug_query_enabled("false") is False
    assert debug_query_enabled("0") is False
    assert debug_query_enabled("") is False
    assert debug_query_enabled(None) is False


def _pour_turn():
    from zeus_client import DebugBundle, TurnResult, TurnStatus

    return TurnResult(
        answer="Duvel is on tap.",
        status=TurnStatus.OK,
        structured=None,
        session=None,
        debug=DebugBundle(
            turn_id="turn_1",
            public_trace={"turn_id": "turn_1"},
            hops=(
                {
                    "name": "find",
                    "result_json": {
                        "rows": [
                            {
                                "name": "Duvel",
                                "style": "Belgian Strong Ale",
                                "abv": 8.5,
                                "brewery": "Duvel Moortgat",
                                "city": "Breendonk",
                            }
                        ]
                    },
                },
            ),
            notes=("semantic_cache.off",),
            detective={"version": 1, "overview": {"headline": "ok"}},
            preferred_req_id="req-pref",
            req_ids=("req-pref",),
        ),
        error=None,
        messages=(),
    )


def _install_pour(monkeypatch, turn):
    from types import SimpleNamespace

    import main

    calls: list[dict] = []

    async def fake_run_turn(message, **kwargs):
        calls.append({"message": message, "kwargs": kwargs})
        return turn

    async def fake_load(*_args, **_kwargs):
        return {}

    async def quiet(_rt):
        return None

    fake_rt = SimpleNamespace(
        config=SimpleNamespace(
            target=SimpleNamespace(
                bucket="beer-sample", scope="_default", collection="_default"
            ),
            settings=SimpleNamespace(mode="analytics", durable_sessions=False),
            llm=SimpleNamespace(model="grok-4.5-latest", provider="xai"),
        ),
        agent=SimpleNamespace(run_turn=fake_run_turn),
        catalog=SimpleNamespace(load_for_turn=fake_load),
    )
    monkeypatch.setattr(main, "_runtime", lambda: fake_rt)
    monkeypatch.setattr(main, "_sync_catalog", quiet)
    monkeypatch.setattr(main, "_pour_enabled", lambda: True)
    monkeypatch.setattr(main, "_cache_ttl", lambda: 600.0)
    main._cache.clear()
    return main, calls


def test_trace_payload_merges_notes_and_skips_hops_already_present() -> None:
    from zeus_client import DebugBundle, TurnResult, TurnStatus

    from pour_trace import trace_payload

    rich = TurnResult(
        answer="x",
        status=TurnStatus.OK,
        structured=None,
        session=None,
        debug=DebugBundle(
            public_trace={
                "hops": [{"name": "search"}],
                "notes": ["kept"],
                "session": {"id": "s"},
            },
            hops=({"name": "find"},),
            notes=("added",),
            detective={"version": 2},
            preferred_req_id="req-1",
        ),
        error=None,
        messages=(),
    )
    trace = trace_payload(rich)
    assert trace["hops"] == [{"name": "search"}]
    assert trace["notes"] == ["kept", "added"]
    assert trace["detective"]["version"] == 2
    assert trace["session"]["id"] == "s"
    assert trace["session"]["preferred_req_id"] == "req-1"

    empty = TurnResult(
        answer="x",
        status=TurnStatus.OK,
        structured=None,
        session=None,
        debug=DebugBundle(
            public_trace={},
            hops=({"name": "find"},),
            detective=None,
            preferred_req_id=None,
        ),
        error=None,
        messages=(),
    )
    filled = trace_payload(empty)
    assert filled["hops"] == [{"name": "find"}]
    assert "detective" not in filled
    assert "session" not in filled


def test_debug_true_pours_with_rewind_and_trace(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    main, calls = _install_pour(monkeypatch, _pour_turn())
    with TestClient(main.app) as client:
        res = client.get("/api/search", params={"q": "Duvel", "limit": 5, "debug": "true"})
    assert res.status_code == 200
    body = res.json()
    assert len(calls) == 1
    assert calls[0]["kwargs"]["rewind"] is True
    assert "chat_request" not in calls[0]["kwargs"]
    assert calls[0]["kwargs"]["enable_sessions"] is False
    assert body["rewind"] is True
    assert body["trace"]["session"]["preferred_req_id"] == "req-pref"
    assert body["trace"]["detective"]["version"] == 1
    assert "semantic_cache.off" in body["trace"]["notes"]
    assert body["trace"]["hops"][0]["name"] == "find"
    assert body["chat_id"].startswith("beer_")
    assert body["answer"] == "Duvel is on tap."
    assert body["target"] == "beer-sample/_default/_default"
    assert body["mode"] == "analytics"
    assert body["model"] == "grok-4.5-latest"
    assert body["provider"] == "xai"
    assert body["tool_order"]["v1"] == [
        "text_search",
        "get_by_keys",
        "find_nodes",
        "return_result",
    ]
    assert body["tool_order"]["v2"] == _V2_TOOLS
    assert "pipeline" not in body["tool_order"]["v2"]
    assert main._cache == {}


def test_omitted_or_false_debug_leaves_rewind_off(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    main, calls = _install_pour(monkeypatch, _pour_turn())
    with TestClient(main.app) as client:
        omitted = client.get("/api/search", params={"q": "Porter"})
        falsey = client.get("/api/search", params={"q": "Wheat", "debug": "false"})
        off = client.get("/api/search", params={"q": "Pilsner", "debug": "0"})
    assert [call["kwargs"]["rewind"] for call in calls] == [False, False, False]
    for res in (omitted, falsey, off):
        assert res.status_code == 200
        body = res.json()
        assert body["rewind"] is False
        assert "trace" in body
    assert main._cache


def test_debug_pour_does_not_reuse_or_fill_the_cache(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    main, calls = _install_pour(monkeypatch, _pour_turn())
    with TestClient(main.app) as client:
        plain = client.get("/api/search", params={"q": "Lager", "limit": 3})
        assert plain.json()["rewind"] is False
        cached = client.get("/api/search", params={"q": "Lager", "limit": 3})
        assert cached.json()["chat_id"] == plain.json()["chat_id"]
        assert len(calls) == 1
        debug = client.get(
            "/api/search", params={"q": "Lager", "limit": 3, "debug": "true"}
        )
        assert debug.status_code == 200
        assert debug.json()["rewind"] is True
        assert "trace" in debug.json()
        assert debug.json()["chat_id"] != plain.json()["chat_id"]
        assert len(calls) == 2
        assert calls[1]["kwargs"]["rewind"] is True
        again = client.get("/api/search", params={"q": "Lager", "limit": 3})
        assert again.json()["rewind"] is False
        assert again.json()["chat_id"] == plain.json()["chat_id"]
        assert len(calls) == 2
    main._cache.clear()
    calls.clear()
    with TestClient(main.app) as client:
        first = client.get("/api/search", params={"q": "Stout", "debug": "1"})
        assert first.json()["rewind"] is True
        assert main._cache == {}
        second = client.get("/api/search", params={"q": "Stout"})
        assert second.json()["rewind"] is False
        assert len(calls) == 2
        assert calls[0]["kwargs"]["rewind"] is True
        assert calls[1]["kwargs"]["rewind"] is False


def test_detail_routes_stay_rewind_off(monkeypatch) -> None:
    from fastapi.testclient import TestClient

    _main, calls = _install_pour(monkeypatch, _pour_turn())
    with TestClient(_main.app) as client:
        beer = client.get("/api/beer/duvel", params={"debug": "true"})
        brewery = client.get("/api/brewery/moortgat", params={"debug": "yes"})
    assert beer.status_code == 200
    assert brewery.status_code == 200
    assert calls[0]["kwargs"]["rewind"] is False
    assert calls[1]["kwargs"]["rewind"] is False
    assert "Get the beer with id duvel" == calls[0]["message"]
    for body in (beer.json(), brewery.json()):
        assert "rewind" not in body
        assert "trace" not in body
        assert "tool_order" not in body
        assert "chat_id" not in body
    pour = client.get(
        "/api/search",
        params={"q": "Get the beer with id duvel", "limit": 1},
    )
    assert pour.status_code == 200
    assert "trace" in pour.json()
    assert len(calls) == 3
    again = client.get("/api/beer/duvel")
    assert "trace" not in again.json()
    assert len(calls) == 3
