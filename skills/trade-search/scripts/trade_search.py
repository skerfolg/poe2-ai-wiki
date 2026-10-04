#!/usr/bin/env python3
"""One-shot, search-only PoE2 trade client (Python 3.12, standard library only)."""

from __future__ import annotations

import argparse
import base64
import gzip
import json
import math
import os
import re
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path

HOSTS = {"global": "https://www.pathofexile.com", "kakao": "https://poe.kakaogames.com"}
KINDS = ("stats", "items", "static", "filters", "leagues")
DEFAULT_CACHE = Path(__file__).resolve().parents[3] / "var/live/trade-search"
CACHE_SECONDS = 86400
MARGIN = 1.25
ITEM_FIELDS = (
    "id",
    "name",
    "typeLine",
    "baseType",
    "rarity",
    "frameType",
    "ilvl",
    "identified",
    "corrupted",
    "mirrored",
    "split",
    "duplicated",
    "verified",
    "w",
    "h",
    "icon",
    "league",
    "note",
    "properties",
    "additionalProperties",
    "requirements",
    "sockets",
    "implicitMods",
    "explicitMods",
    "craftedMods",
    "enchantMods",
    "fracturedMods",
    "runeMods",
    "desecratedMods",
    "utilityMods",
    "flavourText",
    "stackSize",
    "maxStackSize",
    "socketedItems",
    "extended",
)
# Only item-display fields from nested objects may cross the output boundary.
NESTED_FIELDS = {
    "name",
    "values",
    "displayMode",
    "type",
    "progress",
    "suffix",
    "group",
    "attr",
    "sColour",
    "colour",
    "category",
    "subcategories",
    "dps",
    "pdps",
    "edps",
    "ar",
    "ev",
    "es",
    "ward",
    "augments",
    "text",
    "value",
    "max",
    "min",
    # Trade2 also returns object-shaped modifiers; description holds their display text.
    "description",
    "domain",
    "hash",
    "mods",
    "tier",
    "level",
    "magnitudes",
}


class TradeError(Exception):
    def __init__(self, code, message, *, status="error", **details):
        super().__init__(message)
        self.output = {"status": status, "error": {"code": code, "message": message, **details}}


def stamp(now=None):
    return datetime.fromtimestamp(time.time() if now is None else now, UTC).isoformat()


def object_at(value, path):
    if not isinstance(value, dict):
        raise TradeError("invalid_query", f"{path} must be an object")
    return value


def validate_query(body):
    """Validate common structural mistakes without freezing the service's filter vocabulary."""
    object_at(body, "body")
    query = object_at(body.get("query"), "query")
    status = object_at(query.get("status"), "query.status")
    if not isinstance(status.get("option"), str) or not status["option"].strip():
        raise TradeError("invalid_query", "query.status.option must be a nonempty string")
    sorting = object_at(body.get("sort"), "sort")
    if not sorting or any(value not in ("asc", "desc") for value in sorting.values()):
        raise TradeError("invalid_query", "sort must contain asc/desc values")
    groups = query.get("stats")
    if not isinstance(groups, list):
        raise TradeError("invalid_query", "query.stats must be an array of groups")
    for index, group in enumerate(groups):
        path = f"query.stats[{index}]"
        object_at(group, path)
        if not isinstance(group.get("type"), str) or not group["type"]:
            raise TradeError("invalid_query", f"{path}.type must be a string")
        if not isinstance(group.get("filters"), list):
            raise TradeError("invalid_query", f"{path}.filters must be an array")
        if "value" in group:
            object_at(group["value"], f"{path}.value")
        for number, stat in enumerate(group["filters"]):
            subpath = f"{path}.filters[{number}]"
            object_at(stat, subpath)
            if not isinstance(stat.get("id"), str) or not stat["id"]:
                raise TradeError("invalid_query", f"{subpath}.id must be a nonempty string")
            if "value" in stat:
                object_at(stat["value"], f"{subpath}.value")
    if "filters" in query:
        for name, group in object_at(query["filters"], "query.filters").items():
            path = f"query.filters.{name}"
            object_at(group, path)
            for key, value in object_at(group.get("filters"), f"{path}.filters").items():
                object_at(value, f"{path}.filters.{key}")

    def walk(value, path):
        if isinstance(value, float) and not math.isfinite(value):
            raise TradeError("invalid_query", f"{path} must be finite")
        if isinstance(value, dict):
            for key in ("min", "max"):
                bound = value.get(key)
                if bound is not None and (
                    isinstance(bound, bool) or not isinstance(bound, int | float)
                ):
                    raise TradeError("invalid_query", f"{path}.{key} must be numeric or null")
            if (
                value.get("min") is not None
                and value.get("max") is not None
                and value["min"] > value["max"]
            ):
                raise TradeError("invalid_query", f"{path}.min must be <= max")
            if isinstance(value.get("option"), bool):
                raise TradeError("invalid_query", f"{path}.option uses strings, not JSON booleans")
            if "disabled" in value and not isinstance(value["disabled"], bool):
                raise TradeError("invalid_query", f"{path}.disabled must be a JSON boolean")
            for key, nested in value.items():
                walk(nested, f"{path}.{key}")
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, f"{path}[{index}]")

    walk(body, "body")
    return body


def browser_url(base, league, body=None, search_id=None):
    if search_id is None:
        packed = gzip.compress(
            json.dumps(body["query"], ensure_ascii=False, separators=(",", ":")).encode(), mtime=0
        )
        search_id = base64.urlsafe_b64encode(packed).decode().rstrip("=")
    return f"{base}/trade2/search/poe2/{urllib.parse.quote(league, safe='')}/" + (
        urllib.parse.quote(search_id, safe="")
    )


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def transport(method, url, headers, body):
    """No redirects, retries, browser credentials, logging, or secret-bearing error strings."""
    request = urllib.request.Request(url, data=body, headers=headers, method=method)
    opener = urllib.request.build_opener(NoRedirect())
    try:
        with opener.open(request, timeout=20) as response:
            return response.status, dict(response.headers), response.read()
    except urllib.error.HTTPError as exc:
        with exc:
            return exc.code, dict(exc.headers), exc.read(8192)
    except (OSError, ValueError, urllib.error.URLError) as exc:
        raise TradeError("network_error", "Trade request failed; no automatic retry") from exc


@contextmanager
def cache_lock(directory):
    """An OS lock releases on process exit; a contending invocation stops without polling."""
    directory.mkdir(parents=True, exist_ok=True)
    with (directory / ".lock").open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError as exc:
            raise TradeError(
                "cache_busy", "Another helper owns this cache; no request sent"
            ) from exc
        try:
            yield
        finally:
            handle.seek(0)
            if os.name == "nt":
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8-sig"))


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, allow_nan=False), encoding="utf-8")
    temporary.replace(path)


def triples(value):
    parsed = []
    for part in value.split(","):
        values = part.strip().split(":")
        if len(values) == 3 and all(number.strip().isdigit() for number in values):
            parsed.append([int(number) for number in values])
    return parsed


def retry_seconds(value, now):
    try:
        seconds = float(value)
        return max(0, seconds) if math.isfinite(seconds) else None
    except (ValueError, TypeError):
        try:
            return max(0, parsedate_to_datetime(value).timestamp() - now)
        except (TypeError, ValueError, OverflowError):
            return None


def api_error(raw, secret):
    """Only bounded API diagnostics, never arbitrary response bodies or action fields."""
    try:
        decoded = json.loads(raw)
    except (ValueError, UnicodeError):
        return {}
    error = decoded.get("error") if isinstance(decoded, dict) else None
    if not isinstance(error, dict):
        return {}
    projected = {}
    code, message = error.get("code"), error.get("message")
    if isinstance(code, int) and not isinstance(code, bool):
        projected["code"] = code
    elif isinstance(code, str):
        projected["code"] = redact(code, secret)[:80]
    if isinstance(message, str):
        projected["message"] = redact(message, secret)[:500]
    return {"api_error": projected} if projected else {}


class Client:
    def __init__(self, host, cache_dir, *, send=transport, clock=time.time, session=None):
        if host not in HOSTS:
            raise TradeError("invalid_host", "host must be global or kakao")
        self.host, self.base = host, HOSTS[host]
        self.directory = Path(cache_dir)
        self.send, self.clock, self.session = send, clock, session
        self.state_path = self.directory / f"{host}-rate-state.json"
        self.state = {"host": host, "endpoints": {}, "policies": {}}
        if self.state_path.exists():
            try:
                state = read_json(self.state_path)
                if (
                    state.get("host") != host
                    or not isinstance(state.get("endpoints"), dict)
                    or not isinstance(state.get("policies"), dict)
                ):
                    raise ValueError("shape")
                self.state = state
            except (OSError, ValueError, AttributeError) as exc:
                raise TradeError("invalid_rate_state", "Rate state cannot be read safely") from exc

    def check_cooldown(self, endpoint):
        policy = self.state["endpoints"].get(endpoint, endpoint)
        for state in (self.state, self.state["policies"].get(policy, {})):
            if state.get("stopped"):
                raise TradeError(
                    "rate_stop",
                    "429 had no usable Retry-After; manual review required",
                    status="rate_limited",
                    endpoint=endpoint,
                )
            remaining = state.get("next_allowed_at", 0) - self.clock()
            if remaining > 0:
                raise TradeError(
                    "cooldown",
                    "Saved server limit prevents a request",
                    status="rate_limited",
                    endpoint=endpoint,
                    retry_after_seconds=math.ceil(remaining),
                    next_allowed_at=stamp(state["next_allowed_at"]),
                )

    def observe(self, endpoint, status, headers):
        """Persist only public rate metadata. Space requests at 125% of each window/max."""
        now = self.clock()
        headers = {key.lower(): value for key, value in headers.items()}
        policy = headers.get("x-rate-limit-policy", self.state["endpoints"].get(endpoint, endpoint))
        self.state["endpoints"][endpoint] = policy
        prior = self.state["policies"].get(policy, {})
        rate = {
            "policy": policy,
            "observed_at": stamp(now),
            "next_allowed_at": prior.get("next_allowed_at", 0),
            "headers": {
                key: value for key, value in headers.items() if key.startswith("x-rate-limit-")
            },
            "rules": {},
        }
        rules = headers.get("x-rate-limit-rules", "").split(",")
        for rule in (name.strip().lower() for name in rules if name.strip()):
            limits = triples(headers.get(f"x-rate-limit-{rule}", ""))
            states = triples(headers.get(f"x-rate-limit-{rule}-state", ""))
            rate["rules"][rule] = {"limits": limits, "state": states}
            state_by_window = {values[1]: values for values in states}
            for maximum, window, restriction in limits:
                used, _, restricted = state_by_window.get(window, [0, window, 0])
                delay = window / maximum * MARGIN if maximum else window * MARGIN
                if used >= maximum:
                    delay = max(delay, window * MARGIN, restriction * MARGIN)
                if restricted:
                    delay = max(delay, restricted * MARGIN)
                rate["next_allowed_at"] = max(rate["next_allowed_at"], now + delay)
        # If a response omits known rules, continue applying the last observed pacing.
        if not rate["rules"] and prior.get("rules"):
            rate["rules"] = prior["rules"]
            for rule in rate["rules"].values():
                for maximum, window, _ in rule["limits"]:
                    delay = window / maximum * MARGIN if maximum else window * MARGIN
                    rate["next_allowed_at"] = max(rate["next_allowed_at"], now + delay)
        if status == 429:
            seconds = retry_seconds(headers.get("retry-after"), now)
            if seconds is None:
                self.state["stopped"] = True
            else:
                self.state["next_allowed_at"] = max(
                    self.state.get("next_allowed_at", 0), now + seconds * MARGIN
                )
                rate["next_allowed_at"] = max(rate["next_allowed_at"], now + seconds * MARGIN)
        self.state["policies"][policy] = rate
        write_json(self.state_path, redact(self.state, self.session))

    def reserve(self, endpoint):
        """A timeout may still consume a request, so preserve known pacing before sending."""
        policy = self.state["endpoints"].get(endpoint, endpoint)
        rate = self.state["policies"].get(policy)
        if rate is None:
            return
        for rule in rate.get("rules", {}).values():
            for maximum, window, _ in rule["limits"]:
                delay = window / maximum * MARGIN if maximum else window * MARGIN
                rate["next_allowed_at"] = max(rate.get("next_allowed_at", 0), self.clock() + delay)
        write_json(self.state_path, redact(self.state, self.session))

    def request(self, endpoint, method, path, body=None, *, authenticated=False):
        self.check_cooldown(endpoint)
        headers = {"Accept": "application/json", "User-Agent": "poe2-ai-wiki-trade-search/0.1"}
        payload = None
        if body is not None:
            headers["Content-Type"] = "application/json"
            payload = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        if authenticated and self.session:
            if any(char in self.session for char in "\r\n;"):
                raise TradeError("invalid_session", "POESESSID contains invalid cookie characters")
            headers["Cookie"] = "POESESSID=" + self.session
        self.reserve(endpoint)
        try:
            status, response_headers, raw = self.send(method, self.base + path, headers, payload)
        except TradeError:
            raise
        except Exception as exc:
            raise TradeError("network_error", "Trade request failed; no automatic retry") from exc
        self.observe(endpoint, status, response_headers)
        diagnostic = api_error(raw, self.session)
        if status == 429:
            response_headers = {key.lower(): value for key, value in response_headers.items()}
            seconds = retry_seconds(response_headers.get("retry-after"), self.clock())
            raise TradeError(
                "http_429",
                "Server rate limit; no retry or follow-up request",
                status="rate_limited",
                http_status=status,
                retry_after_seconds=seconds,
                **diagnostic,
            )
        if status in (401, 403):
            raise TradeError(
                "authentication_required",
                "Access denied; use the browser search link",
                http_status=status,
                **diagnostic,
            )
        if not 200 <= status < 300:
            raise TradeError(
                "http_error",
                "Trade endpoint returned an unsuccessful status",
                http_status=status,
                **diagnostic,
            )
        try:
            result = json.loads(raw)
        except (ValueError, UnicodeError) as exc:
            raise TradeError("invalid_response", "Trade endpoint did not return JSON") from exc
        if not isinstance(result, dict) or "error" in result:
            raise TradeError(
                "invalid_response", "Trade endpoint returned an unexpected object", **diagnostic
            )
        return result


def normalized(value):
    return re.sub(r"[\s#_]+", "", unicodedata.normalize("NFKC", value).casefold())


def catalog_entries(data):
    if not isinstance(data, dict):
        raise TradeError("invalid_response", "Catalog response must be an object")
    groups = data.get("result")
    if not isinstance(groups, list):
        raise TradeError("invalid_response", "Catalog result must be an array")
    for group in groups:
        if not isinstance(group, dict):
            raise TradeError("invalid_response", "Catalog group must be an object")
        key = "entries" if "entries" in group else "filters" if "filters" in group else None
        if key is None:
            yield {"group": None, "entry": group}
            continue
        if not isinstance(group[key], list):
            raise TradeError("invalid_response", "Catalog entries must be an array")
        context = {
            name: value for name, value in group.items() if name not in ("entries", "filters")
        }
        for entry in group[key]:
            if not isinstance(entry, dict):
                raise TradeError("invalid_response", "Catalog entry must be an object")
            yield {"group": context, "entry": entry}


def catalog(client, kind, text, limit, refresh):
    path = f"/api/trade2/data/{kind}"
    cache_path = client.directory / f"{client.host}-{kind}.json"
    cached = None
    if cache_path.exists() and not refresh:
        try:
            candidate = read_json(cache_path)
            if not isinstance(candidate, dict):
                raise ValueError("invalid cache envelope")
            epoch = candidate.get("fetched_epoch")
            if (
                candidate.get("host") != client.host
                or candidate.get("source_url") != client.base + path
                or not isinstance(candidate.get("fetched_at"), str)
                or not isinstance(epoch, int | float)
                or isinstance(epoch, bool)
                or not math.isfinite(epoch)
            ):
                raise ValueError("invalid cache metadata")
            list(catalog_entries(candidate.get("data")))
            if 0 <= client.clock() - epoch < CACHE_SECONDS:
                cached = candidate
        except (OSError, ValueError, TypeError, TradeError) as exc:
            raise TradeError(
                "invalid_catalog_cache",
                "Catalog cache is invalid; use --refresh to replace it with a server response",
            ) from exc
    was_cached = cached is not None
    if cached is None:
        data = client.request("data/" + kind, "GET", path)
        list(catalog_entries(data))  # Validate before preserving a response as a usable catalog.
        cached = {
            "host": client.host,
            "source_url": client.base + path,
            "fetched_at": stamp(client.clock()),
            "fetched_epoch": client.clock(),
            "data": data,
        }
        write_json(cache_path, cached)
    needles = [normalized(word) for word in text.split() if normalized(word)]
    matches = []
    for row in catalog_entries(cached["data"]):
        haystack = normalized(json.dumps(row, ensure_ascii=False))
        if all(needle in haystack for needle in needles):
            matches.append(row)
    return {
        "status": "ok",
        "kind": kind,
        "source_url": cached["source_url"],
        "fetched_at": cached["fetched_at"],
        "cached": was_cached,
        "matched": len(matches),
        "returned": min(limit, len(matches)),
        "entries": matches[:limit],
    }


def display_value(value):
    if isinstance(value, dict):
        return {key: display_value(nested) for key, nested in value.items() if key in NESTED_FIELDS}
    if isinstance(value, list):
        return [display_value(nested) for nested in value]
    return value


def project_item(item):
    return {
        key: (
            [project_item(nested) for nested in value if isinstance(nested, dict)]
            if key == "socketedItems" and isinstance(value, list)
            else display_value(value)
        )
        for key, value in item.items()
        if key in ITEM_FIELDS
    }


def project_listing(row):
    item, listing = row.get("item"), row.get("listing")
    if not isinstance(item, dict) or not isinstance(listing, dict):
        raise TradeError("invalid_response", "Fetch entry must contain item and listing objects")
    result = {"id": row["id"], "item": project_item(item), "listing": {}}
    if isinstance(listing.get("indexed"), str):
        result["listing"]["indexed"] = listing["indexed"]
    if isinstance(listing.get("price"), dict):
        result["listing"]["price"] = {
            key: value
            for key, value in listing["price"].items()
            if (key in ("type", "currency") and isinstance(value, str))
            or (
                key == "amount"
                and isinstance(value, int | float)
                and not isinstance(value, bool)
                and math.isfinite(value)
            )
        }
    account = listing.get("account")
    if isinstance(account, dict) and "online" in account:
        online = account["online"]
        if isinstance(online, dict):
            online = {
                key: value
                for key, value in online.items()
                if key in ("league", "status") and isinstance(value, str)
            }
        elif online is not None and not isinstance(online, bool):
            online = None
        result["listing"]["account"] = {"online": online}
    return result


def search(client, league, body, limit, output):
    path = "/api/trade2/search/poe2/" + urllib.parse.quote(league, safe="")
    data = client.request("search", "POST", path, body, authenticated=True)
    total, ids, search_id = data.get("total"), data.get("result"), data.get("id")
    if (
        not isinstance(total, int)
        or isinstance(total, bool)
        or total < 0
        or not isinstance(ids, list)
        or any(not isinstance(x, str) or not x for x in ids)
        or not isinstance(search_id, str)
        or not search_id
        or ("inexact" in data and not isinstance(data["inexact"], bool))
    ):
        raise TradeError(
            "invalid_response", "Search response requires id, nonnegative total, result IDs"
        )
    output.update(
        status="ok",
        search_id=search_id,
        total=total,
        returned=0,
        items=[],
        search_url=browser_url(client.base, league, search_id=search_id),
    )
    output.pop("browser_url_note", None)
    if "inexact" in data:
        output["inexact"] = data["inexact"]
    selected = ids[:limit]
    output["fetched_ids"] = selected
    if not selected:
        if total > 0 and limit > 0:
            output.update(
                status="partial",
                error={
                    "code": "no_results_available",
                    "message": "Search reported matches but supplied no listing IDs",
                },
            )
        return output
    encoded_ids = ",".join(urllib.parse.quote(value, safe="") for value in selected)
    fetch_path = (
        "/api/trade2/fetch/"
        + encoded_ids
        + "?"
        + urllib.parse.urlencode(
            {"query": search_id, "realm": "poe2"}, quote_via=urllib.parse.quote
        )
    )
    try:
        fetched = client.request("fetch", "GET", fetch_path, authenticated=True)
        rows = fetched.get("result")
        if not isinstance(rows, list):
            raise TradeError("invalid_response", "Fetch result must be an array")
        found = set()
        null_count = 0
        for row in rows:
            if row is None:
                null_count += 1
                continue
            if (
                not isinstance(row, dict)
                or not isinstance(row.get("id"), str)
                or row["id"] not in selected
                or row["id"] in found
            ):
                raise TradeError("invalid_response", "Fetch returned an invalid or unexpected ID")
            output["items"].append(project_listing(row))
            found.add(row["id"])
        output["null_entries"] = null_count
        output["missing_ids"] = [value for value in selected if value not in found]
        if null_count or output["missing_ids"]:
            output["status"] = "partial"
    except TradeError as exc:
        output.update(
            status="partial", fetch_status=exc.output["status"], error=exc.output["error"]
        )
    output["returned"] = len(output["items"])
    order = {identifier: index for index, identifier in enumerate(selected)}
    output["items"].sort(key=lambda item: order[item["id"]])
    return output


def redact(value, secret):
    if not secret:
        return value
    if isinstance(value, str):
        return value.replace(secret, "[REDACTED]")
    if isinstance(value, dict):
        return {redact(key, secret): redact(nested, secret) for key, nested in value.items()}
    if isinstance(value, list):
        return [redact(nested, secret) for nested in value]
    return value


def execute(args, *, send=transport, clock=time.time, session=None):
    """Testable entry point. The caller owns printing; no raw HTTP body ever reaches stderr."""
    output = {"host": args.host, "timestamp": stamp(clock()), "command": args.command}
    try:
        if args.host not in HOSTS:
            raise TradeError("invalid_host", "host must be global or kakao")
        if args.command in ("prepare", "search"):
            output["league"] = args.league
            if not args.league.strip():
                raise TradeError("invalid_league", "league must be nonempty")
            try:
                body = validate_query(read_json(Path(args.query)))
            except (OSError, ValueError) as exc:
                raise TradeError("invalid_query", "Query file must contain valid JSON") from exc
            output["request"] = {
                "method": "POST",
                "url": HOSTS[args.host]
                + "/api/trade2/search/poe2/"
                + urllib.parse.quote(args.league, safe=""),
                "body": body,
            }
            output["search_url"] = browser_url(HOSTS[args.host], args.league, body)
            output["browser_url_note"] = "Encoded link contains query only; sort is in request.body"
            if args.command == "prepare":
                output["status"] = "prepared"
                output["executed"] = False
                return redact(output, session)
        if args.command == "search" and not 0 <= args.limit <= 10:
            raise TradeError("invalid_limit", "Search limit must be from 0 to 10")
        if args.command == "catalog" and (args.kind not in KINDS or args.limit < 1):
            raise TradeError("invalid_catalog", "Use a supported kind and positive limit")
        with cache_lock(Path(args.cache_dir)):
            client = Client(args.host, args.cache_dir, send=send, clock=clock, session=session)
            if args.command == "catalog":
                output["request"] = {
                    "method": "GET",
                    "url": client.base + "/api/trade2/data/" + args.kind,
                }
                output.update(catalog(client, args.kind, args.text, args.limit, args.refresh))
            else:
                search(client, args.league, body, args.limit, output)
    except TradeError as exc:
        output.update(exc.output)
    except (OSError, ValueError, TypeError) as exc:
        output.update(
            status="error",
            error={
                "code": "local_error",
                "message": f"Local operation failed ({type(exc).__name__})",
            },
        )
    return redact(output, session)


class JsonParser(argparse.ArgumentParser):
    def error(self, message):
        raise TradeError("invalid_arguments", message)


def parser():
    root = JsonParser(description=__doc__)
    commands = root.add_subparsers(dest="command", required=True)
    for name in ("catalog", "prepare", "search"):
        command = commands.add_parser(name)
        command.add_argument("--host", choices=HOSTS, required=True)
        command.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
        if name == "catalog":
            command.add_argument("--kind", choices=KINDS, required=True)
            command.add_argument("--text", default="")
            command.add_argument("--limit", type=int, default=20)
            command.add_argument("--refresh", action="store_true")
        else:
            command.add_argument("--league", required=True)
            command.add_argument("--query", type=Path, required=True)
            if name == "search":
                command.add_argument("--limit", type=int, default=10)
    return root


def main(argv=None):
    secret = os.environ.get("POESESSID")
    try:
        result = execute(parser().parse_args(argv), session=secret)
    except TradeError as exc:
        result = {"timestamp": stamp(), **redact(exc.output, secret)}
    print(json.dumps(result, ensure_ascii=True, allow_nan=False))
    return 0 if result["status"] in ("ok", "prepared") else 1


if __name__ == "__main__":
    raise SystemExit(main())
