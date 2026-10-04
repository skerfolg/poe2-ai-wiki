"""Behavioral tests for the search-only skill helper; never contact the live service."""

import base64
import copy
import gzip
import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "skills/trade-search/scripts/trade_search.py"
SPEC = importlib.util.spec_from_file_location("trade_search_skill", SCRIPT)
trade = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(trade)


def rich_query():
    return {
        "query": {
            "status": {"option": "onlineleague"},
            "name": {"option": "테스트", "discriminator": "variant"},
            "type": "Diamond",
            "stats": [
                {
                    "type": "count",
                    "disabled": False,
                    "value": {"min": 2},
                    "filters": [
                        {
                            "id": "explicit.stat_1",
                            "value": {"min": 50, "max": None},
                            "disabled": False,
                        },
                        {"id": "explicit.stat_2", "value": {"option": 4}},
                    ],
                },
                {"type": "not", "filters": [{"id": "pseudo.stat_other"}], "disabled": True},
            ],
            "filters": {
                "misc_filters": {
                    "disabled": False,
                    "filters": {"identified": {"option": "false"}, "gem_level": {"min": 20}},
                },
                "trade_filters": {
                    "filters": {
                        "price": {"min": None, "max": 4, "option": "divine"},
                        "sale_type": {"option": "any"},
                    }
                },
                "future_filters": {"filters": {"new_filter": {"option": "new"}}},
            },
        },
        "sort": {"price": "desc"},
    }


class FakeTransport:
    def __init__(self, *responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, method, url, headers, body):
        self.calls.append((method, url, headers, body))
        assert self.responses, "Unexpected follow-up HTTP request"
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        status, response_headers, value = response
        return status, response_headers, json.dumps(value).encode()


def arguments(tmp_path, command="search", *, host="global", limit=10, body=None):
    path = tmp_path / "query.json"
    path.write_text(json.dumps(body or rich_query()), encoding="utf-8")
    args = [command, "--host", host, "--cache-dir", str(tmp_path / "cache")]
    if command == "catalog":
        args += ["--kind", "stats", "--limit", str(limit)]
    else:
        args += ["--league", "금지 의식 /?#", "--query", str(path)]
        if command == "search":
            args += ["--limit", str(limit)]
    return trade.parser().parse_args(args)


def search_response(ids=None, **changes):
    result = {"id": "opaque/+?id", "result": ids or [], "total": len(ids or [])}
    result.update(changes)
    return 200, {}, result


def listing(identifier):
    return {
        "id": identifier,
        "item": {
            "name": "Test",
            "typeLine": "Diamond",
            "ilvl": 82,
            "explicitMods": ["+50 to maximum Life"],
            "properties": [{"name": "Quality", "values": [["20%", 0]], "whisper_token": "NO"}],
            "extended": {"dps": 200, "whisper_token": "NO"},
            "socketedItems": [{"name": "Rune", "secret": "NO"}],
            "secret": "NO",
        },
        "listing": {
            "indexed": "2026-10-01T00:00:00Z",
            "price": {"amount": 2, "currency": "divine", "type": "~price", "token": "NO"},
            "account": {
                "name": "PRIVATE",
                "online": {"league": "Standard", "status": "afk", "token": "NO"},
                "secret": "NO",
            },
            "whisper": "NO",
            "whisper_token": "NO",
            "hideout_token": "NO",
        },
        "action": "NO",
    }


RATE_HEADERS = {
    "X-Rate-Limit-Policy": "shared-search-policy",
    "X-Rate-Limit-Rules": "Ip,Account",
    "X-Rate-Limit-Ip": "5:10:60,600:21600:3600",
    "X-Rate-Limit-Ip-State": "1:10:0,1:21600:0",
    "X-Rate-Limit-Account": "10:60:300",
    "X-Rate-Limit-Account-State": "1:60:0",
}


def test_prepare_preserves_rich_body_without_network_or_cache(tmp_path):
    args = arguments(tmp_path, "prepare")
    send = FakeTransport()
    result = trade.execute(args, send=send, clock=lambda: 1000)
    assert result["status"] == "prepared"
    assert result["executed"] is False
    assert result["request"]["body"] == rich_query()
    assert not send.calls
    assert not args.cache_dir.exists()
    encoded = result["search_url"].rsplit("/", 1)[1]
    decoded = json.loads(
        gzip.decompress(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    )
    assert decoded == rich_query()["query"]
    assert "sort" in result["browser_url_note"]


def test_cli_prepare_preserves_unicode_with_non_utf8_stdout(tmp_path):
    body = rich_query()
    body["query"]["name"] = "Legacy of Mjölner"
    query_path = tmp_path / "query.json"
    query_path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    completed = subprocess.run(
        [
            sys.executable,
            str(SCRIPT),
            "prepare",
            "--host",
            "global",
            "--league",
            "Standard",
            "--query",
            str(query_path),
        ],
        env={**os.environ, "PYTHONIOENCODING": "cp949:strict", "PYTHONUTF8": "0"},
        capture_output=True,
        check=False,
        timeout=20,
    )
    assert completed.returncode == 0, completed.stderr
    assert completed.stderr == b""
    result = json.loads(completed.stdout.decode("ascii"))
    assert result["status"] == "prepared"
    assert result["executed"] is False
    assert result["request"]["body"] == body


@pytest.mark.parametrize(
    "change",
    [
        lambda q: q["query"]["filters"]["trade_filters"]["filters"]["price"].update(min=5, max=2),
        lambda q: q["query"]["filters"]["trade_filters"]["filters"]["price"].update(min=True),
        lambda q: q["query"]["filters"]["trade_filters"]["filters"]["price"].update(
            max=float("inf")
        ),
        lambda q: q["query"]["status"].update(option=True),
        lambda q: q["query"]["stats"][0].update(disabled="false"),
        lambda q: q["query"]["stats"][0]["filters"][0].update(disabled="false"),
        lambda q: q["query"]["filters"]["misc_filters"]["filters"]["identified"].update(
            option=False
        ),
        lambda q: q["query"]["filters"]["misc_filters"].update(filters=[]),
        lambda q: q["query"].update(stats={}),
    ],
)
def test_invalid_query_stops_before_http(tmp_path, change):
    body = rich_query()
    change(body)
    args = arguments(tmp_path, body=body)
    send = FakeTransport()
    result = trade.execute(args, send=send)
    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_query"
    assert not send.calls


def test_search_quoted_paths_one_fetch_and_safe_projection(tmp_path):
    send = FakeTransport(
        search_response(["id/+?", "gone", "absent"], inexact=True),
        (200, {}, {"result": [listing("id/+?"), None]}),
    )
    args = arguments(tmp_path)
    result = trade.execute(args, send=send, session="SESSION")
    assert result["status"] == "partial"
    assert result["search_id"] == "opaque/+?id"
    assert result["total"] == 3 and result["returned"] == 1
    assert result["inexact"] is True
    assert result["null_entries"] == 1 and result["missing_ids"] == ["gone", "absent"]
    assert len(send.calls) == 2
    assert send.calls[0][1].endswith("/%EA%B8%88%EC%A7%80%20%EC%9D%98%EC%8B%9D%20%2F%3F%23")
    assert send.calls[1][1].endswith("/id%2F%2B%3F,gone,absent?query=opaque%2F%2B%3Fid&realm=poe2")
    assert result["search_url"].endswith("/opaque%2F%2B%3Fid")
    assert json.loads(send.calls[0][3]) == rich_query()
    assert send.calls[0][2]["Cookie"] == "POESESSID=SESSION"
    serialized = json.dumps(result)
    assert "NO" not in serialized and "PRIVATE" not in serialized and "SESSION" not in serialized
    assert result["items"][0]["item"]["explicitMods"] == ["+50 to maximum Life"]
    assert result["items"][0]["listing"]["account"]["online"]["status"] == "afk"


@pytest.mark.parametrize(
    "data",
    [
        {},
        {"id": "id", "total": 0},
        {"id": "id", "total": -1, "result": []},
        {"id": "id", "total": True, "result": []},
        {"id": "id", "total": 0, "result": {}},
        {"id": "id", "total": 1, "result": [None]},
        {"id": "id", "total": 1, "result": ["a"], "inexact": "true"},
    ],
)
def test_schema_drift_is_not_zero_hits(tmp_path, data):
    send = FakeTransport((200, {}, data))
    result = trade.execute(arguments(tmp_path), send=send)
    assert result["status"] == "error" and result["error"]["code"] == "invalid_response"
    assert "total" not in result
    assert len(send.calls) == 1


def test_zero_results_and_limit_zero_are_successful(tmp_path):
    for response, limit in [(search_response(), 10), (search_response(["a"], total=100), 0)]:
        send = FakeTransport(response)
        result = trade.execute(arguments(tmp_path, limit=limit), send=send)
        assert result["status"] == "ok" and result["returned"] == 0
        assert len(send.calls) == 1


@pytest.mark.parametrize("status", [401, 403, 302, 500])
def test_http_failure_returns_browser_link_once(tmp_path, status):
    send = FakeTransport((status, {}, {"secret": "DO NOT OUTPUT"}))
    result = trade.execute(arguments(tmp_path), send=send)
    assert result["status"] == "error"
    assert result["error"]["http_status"] == status
    assert result["search_url"].startswith(trade.HOSTS["global"])
    assert "DO NOT OUTPUT" not in json.dumps(result)
    assert len(send.calls) == 1


def test_429_retry_after_stops_followups_and_next_invocation(tmp_path):
    args = arguments(tmp_path)
    send = FakeTransport((429, {"Retry-After": "20"}, {}))
    result = trade.execute(args, send=send, clock=lambda: 1000)
    assert result["status"] == "rate_limited"
    assert result["error"]["retry_after_seconds"] == 20
    stopped = trade.execute(args, send=send, clock=lambda: 1010)
    assert stopped["error"]["retry_after_seconds"] == 15
    assert len(send.calls) == 1
    send.responses.append(search_response())
    assert trade.execute(args, send=send, clock=lambda: 1026)["status"] == "ok"


def test_429_without_retry_after_persists_stop(tmp_path):
    args = arguments(tmp_path)
    send = FakeTransport((429, {}, {}))
    assert trade.execute(args, send=send, clock=lambda: 1000)["status"] == "rate_limited"
    result = trade.execute(args, send=send, clock=lambda: 99999999)
    assert result["error"]["code"] == "rate_stop"
    assert len(send.calls) == 1


def test_long_window_pacing_persists_and_isolates_hosts(tmp_path):
    args = arguments(tmp_path)
    send = FakeTransport((200, RATE_HEADERS, search_response()[2]), search_response())
    assert trade.execute(args, send=send, clock=lambda: 1000)["status"] == "ok"
    result = trade.execute(args, send=send, clock=lambda: 1001)
    assert result["status"] == "rate_limited"
    assert result["error"]["retry_after_seconds"] == 44  # 21600/600 * 1.25 = 45.
    args.host = "kakao"
    assert trade.execute(args, send=send, clock=lambda: 1001)["status"] == "ok"
    assert len(send.calls) == 2
    state = json.loads((args.cache_dir / "global-rate-state.json").read_text())
    assert state["policies"]["shared-search-policy"]["rules"]["ip"]["limits"][1] == [
        600,
        21600,
        3600,
    ]


@pytest.mark.parametrize(
    ("state", "expected"), [("5:10:0,1:21600:0", 75), ("1:10:90,1:21600:0", 113)]
)
def test_exhausted_and_restricted_rate_state(tmp_path, state, expected):
    headers = {**RATE_HEADERS, "X-Rate-Limit-Ip-State": state}
    args = arguments(tmp_path)
    send = FakeTransport((200, headers, search_response()[2]))
    trade.execute(args, send=send, clock=lambda: 1000)
    result = trade.execute(args, send=send, clock=lambda: 1000)
    assert result["error"]["retry_after_seconds"] == expected


def test_fetch_rate_limit_preserves_search_success(tmp_path):
    send = FakeTransport(search_response(["a"]), (429, {"Retry-After": "30"}, {}))
    result = trade.execute(arguments(tmp_path), send=send, clock=lambda: 1000)
    assert result["status"] == "partial" and result["fetch_status"] == "rate_limited"
    assert result["search_id"] == "opaque/+?id" and result["total"] == 1
    assert result["search_url"].endswith("opaque%2F%2B%3Fid")
    assert len(send.calls) == 2


def test_known_shared_policy_prevents_fetch_and_lock_prevents_concurrent_use(tmp_path):
    args = arguments(tmp_path)
    args.cache_dir.mkdir()
    (args.cache_dir / "global-rate-state.json").write_text(
        json.dumps(
            {"host": "global", "endpoints": {"fetch": "shared-search-policy"}, "policies": {}}
        )
    )
    send = FakeTransport((200, RATE_HEADERS, search_response(["a"])[2]))
    result = trade.execute(args, send=send, clock=lambda: 1000)
    assert result["status"] == "partial" and result["error"]["code"] == "cooldown"
    assert len(send.calls) == 1
    with trade.cache_lock(args.cache_dir):
        result = trade.execute(args, send=send)
    assert result["error"]["code"] == "cache_busy"


def test_catalog_filter_projection_raw_cache_and_no_cookie(tmp_path):
    entries = [
        {"id": "explicit.stat_1", "text": "+# to Maximum Life"},
        {"id": "explicit.stat_2", "text": "Speed"},
    ]
    data = {"result": [{"id": "explicit", "label": "Explicit", "entries": entries}]}
    send = FakeTransport((200, {}, data))
    args = arguments(tmp_path, "catalog")
    args.text = "maximumlife"
    result = trade.execute(args, send=send, session="PRIVATESESSION", clock=lambda: 1000)
    assert result["matched"] == result["returned"] == 1
    assert result["entries"][0]["group"]["id"] == "explicit"
    assert "Cookie" not in send.calls[0][2]
    raw_cache = json.loads((args.cache_dir / "global-stats.json").read_text())
    assert raw_cache["data"] == data
    assert raw_cache["source_url"].endswith("/api/trade2/data/stats")
    args.text = "explicit.stat_2"
    result = trade.execute(args, send=send, clock=lambda: 1001)
    assert result["cached"] and result["entries"][0]["entry"]["text"] == "Speed"
    assert len(send.calls) == 1
    assert "PRIVATESESSION" not in "".join(
        path.read_text() for path in args.cache_dir.glob("*.json")
    )


def test_catalog_options_leagues_and_default_limit(tmp_path):
    filters = {
        "result": [
            {
                "id": "misc_filters",
                "filters": [
                    {
                        "id": "corrupted",
                        "option": {
                            "options": [
                                {"id": "false", "text": "No"},
                                {"id": "true", "text": "Yes"},
                            ]
                        },
                    }
                ],
            }
        ]
    }
    leagues = {"result": [{"id": "Standard", "text": "Standard", "realm": "poe2"}]}
    many = {"result": [{"id": "group", "entries": [{"id": str(x)} for x in range(30)]}]}
    send = FakeTransport((200, {}, filters), (200, {}, leagues), (200, {}, many))
    args = arguments(tmp_path, "catalog", limit=20)
    args.kind = "filters"
    result = trade.execute(args, send=send)
    assert len(result["entries"][0]["entry"]["option"]["options"]) == 2
    args.kind = "leagues"
    result = trade.execute(args, send=send)
    assert result["entries"][0] == {"group": None, "entry": leagues["result"][0]}
    args.kind = "items"
    result = trade.execute(args, send=send)
    assert result["matched"] == 30 and result["returned"] == 20


def test_auth_secret_never_appears_in_errors_or_response(tmp_path):
    args = arguments(tmp_path)
    send = FakeTransport(RuntimeError("POESESSID=PRIVATESESSION"))
    result = trade.execute(args, send=send, session="PRIVATESESSION")
    assert result["error"]["code"] == "network_error"
    assert "PRIVATESESSION" not in json.dumps(result)
    row = listing("a")
    row["item"]["name"] = "PRIVATESESSION"
    send = FakeTransport(search_response(["a"]), (200, {}, {"result": [row]}))
    result = trade.execute(args, send=send, session="PRIVATESESSION")
    assert result["items"][0]["item"]["name"] == "[REDACTED]"
    assert "PRIVATESESSION" not in "".join(
        path.read_text() for path in args.cache_dir.glob("*.json")
    )


def test_redirect_handler_never_follows_redirects():
    assert (
        trade.NoRedirect().redirect_request(
            None, None, 302, "Found", {}, "https://attacker.invalid"
        )
        is None
    )


def test_unknown_host_and_limit_rejected_without_http(tmp_path):
    args = arguments(tmp_path)
    args.host = "https://attacker.invalid"
    result = trade.execute(args, send=FakeTransport())
    assert result["error"]["code"] == "invalid_host"
    args.host = "global"
    args.limit = 11
    assert trade.execute(args, send=FakeTransport())["error"]["code"] == "invalid_limit"


def test_query_validation_does_not_modify_input():
    body = rich_query()
    before = copy.deepcopy(body)
    assert trade.validate_query(body) == before


def test_retry_after_supports_http_date():
    assert trade.retry_seconds("Thu, 01 Jan 1970 00:20:00 GMT", 1000) == 200
    assert trade.retry_seconds("invalid", 1000) is None


def test_timeout_preserves_known_pacing_and_rate_headers_redact_secret(tmp_path):
    args = arguments(tmp_path)
    headers = {**RATE_HEADERS, "X-Rate-Limit-Debug": "PRIVATESESSION"}
    send = FakeTransport((200, headers, search_response()[2]), TimeoutError("PRIVATESESSION"))
    trade.execute(args, send=send, clock=lambda: 1000, session="PRIVATESESSION")
    state_text = (args.cache_dir / "global-rate-state.json").read_text()
    assert "PRIVATESESSION" not in state_text
    result = trade.execute(args, send=send, clock=lambda: 1050, session="PRIVATESESSION")
    assert result["error"]["code"] == "network_error"
    result = trade.execute(args, send=send, clock=lambda: 1051, session="PRIVATESESSION")
    assert result["error"]["code"] == "cooldown"
    assert result["error"]["retry_after_seconds"] == 44
    assert len(send.calls) == 2


def test_anonymous_search_omits_auth_and_refresh_reloads_catalog(tmp_path):
    send = FakeTransport(search_response())
    trade.execute(arguments(tmp_path), send=send)
    assert "Cookie" not in send.calls[0][2]
    data = {"result": [{"id": "Standard", "realm": "poe2"}]}
    send = FakeTransport((200, {}, data), (200, {}, data))
    args = arguments(tmp_path, "catalog")
    args.kind = "leagues"
    assert not trade.execute(args, send=send)["cached"]
    args.refresh = True
    assert not trade.execute(args, send=send)["cached"]
    assert len(send.calls) == 2


def test_malformed_fetch_preserves_search_and_useful_rows(tmp_path):
    send = FakeTransport(
        search_response(["a", "b"]), (200, {}, {"result": [listing("a"), {"id": "wrong"}]})
    )
    result = trade.execute(arguments(tmp_path), send=send)
    assert result["status"] == "partial" and result["fetch_status"] == "error"
    assert result["error"]["code"] == "invalid_response"
    assert result["returned"] == 1 and result["total"] == 2
    assert result["search_id"] == "opaque/+?id"


def test_api_error_keeps_bounded_redacted_diagnostics(tmp_path):
    data = {
        "error": {
            "code": 2,
            "message": "Invalid PRIVATESESSION filter: " + "x" * 600,
            "whisper_token": "NO",
        },
        "raw": "NO",
    }
    send = FakeTransport((400, {}, data))
    result = trade.execute(arguments(tmp_path), send=send, session="PRIVATESESSION")
    error = result["error"]
    assert error["http_status"] == 400 and error["api_error"]["code"] == 2
    assert error["api_error"]["message"].startswith("Invalid [REDACTED] filter")
    assert len(error["api_error"]["message"]) == 500
    assert "PRIVATESESSION" not in json.dumps(result) and "NO" not in json.dumps(result)
    assert trade.api_error(b"<html>unknown error</html>", None) == {}


def test_positive_total_without_ids_is_partial(tmp_path):
    send = FakeTransport(search_response([], total=10))
    result = trade.execute(arguments(tmp_path), send=send)
    assert result["status"] == "partial" and result["total"] == 10
    assert result["error"]["code"] == "no_results_available"
    assert len(send.calls) == 1


def test_fetch_order_follows_search_not_response_order(tmp_path):
    send = FakeTransport(
        search_response(["a", "b"]), (200, {}, {"result": [listing("b"), listing("a")]})
    )
    result = trade.execute(arguments(tmp_path), send=send)
    assert result["status"] == "ok"
    assert [row["id"] for row in result["items"]] == ["a", "b"]


@pytest.mark.parametrize("cache_data", ["missing", []])
def test_corrupt_catalog_cache_returns_structured_error_without_http(tmp_path, cache_data):
    args = arguments(tmp_path, "catalog")
    args.cache_dir.mkdir()
    cached = {
        "host": args.host,
        "source_url": trade.HOSTS[args.host] + "/api/trade2/data/stats",
        "fetched_at": trade.stamp(1000),
        "fetched_epoch": 1000,
    }
    if cache_data != "missing":
        cached["data"] = cache_data
    (args.cache_dir / "global-stats.json").write_text(json.dumps(cached))
    send = FakeTransport()
    result = trade.execute(args, send=send, clock=lambda: 1001)
    assert result["status"] == "error"
    assert result["error"]["code"] == "invalid_catalog_cache"
    assert "--refresh" in result["error"]["message"]
    assert not send.calls
    args.refresh = True
    send.responses.append((200, {}, {"result": []}))
    assert trade.execute(args, send=send, clock=lambda: 1001)["status"] == "ok"


@pytest.mark.parametrize("data", [[], None, "wrong"])
def test_catalog_projection_rejects_nonobject_envelope(data):
    with pytest.raises(trade.TradeError) as raised:
        list(trade.catalog_entries(data))
    assert raised.value.output["error"]["code"] == "invalid_response"


def test_modern_modifier_display_survives_projection_without_action_tokens(tmp_path):
    row = listing("a")
    modern = {
        "description": "+124 to maximum Life",
        "domain": "explicit",
        "hash": "stat.explicit.stat_3299347043",
        "mods": [
            {
                "name": "Athlete's",
                "tier": "P1",
                "level": 60,
                "magnitudes": [{"min": "120", "max": "149", "action_token": "DROP"}],
                "whisper_token": "DROP",
            }
        ],
        "hideout_token": "DROP",
    }
    row["item"]["explicitMods"] = [modern, "+30% to Fire Resistance"]
    row["item"]["runeMods"] = [
        {"description": "20% increased Energy Shield", "domain": "rune", "hash": "stat.rune.test"}
    ]
    row["item"]["sockets"] = [{"group": 0, "attr": "S", "sColour": "W", "whisper_token": "DROP"}]
    send = FakeTransport(search_response(["a"]), (200, {}, {"result": [row]}))
    result = trade.execute(arguments(tmp_path), send=send)
    item = result["items"][0]["item"]
    assert result["status"] == "ok"
    assert item["explicitMods"][0] == {
        "description": "+124 to maximum Life",
        "domain": "explicit",
        "hash": "stat.explicit.stat_3299347043",
        "mods": [
            {
                "name": "Athlete's",
                "tier": "P1",
                "level": 60,
                "magnitudes": [{"min": "120", "max": "149"}],
            }
        ],
    }
    assert item["explicitMods"][1] == "+30% to Fire Resistance"
    assert item["runeMods"][0]["description"] == "20% increased Energy Shield"
    assert item["sockets"] == [{"group": 0, "attr": "S", "sColour": "W"}]
    assert "DROP" not in json.dumps(result)
