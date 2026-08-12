"""poe.ninja 래더에서 **PoB 공유 코드만** 수집한다 (#67 5차).

## 경계 — 이 모듈은 해석하지 않는다

층이 셋이고 여기는 맨 아래다:

    수집기(여기)  URL → PoB 코드 + 출처       ← 판단 없음, 결정적
    parse_pob     코드 → 구조화               ← 이미 있다
    에이전트·skills  구조화 → 8축 해석          ← 판단이라 코드가 아니다 (철칙 3)

그래서 여기서 하는 일은 「가져와서·검증하고·append-only로 쌓기」뿐이다.
레벨·DPS·EHP를 목록에서 긁지 않는다 — **PoB 코드 안에 있으므로 두 개의 진실을
만들 이유가 없다**. 여기 담는 수치는 전부 출처(provenance)이지 측정이 아니다.

## 왜 append-only인가

**PoB 코드는 나중에 다시 못 가져온다.** poe.ninja 스냅샷은 갱신되고 캐릭터는
리스펙되거나 사라진다. 지금 0.4를 소급할 수 있는 건 poe.ninja가 Time machine을
갖고 있어서지 우리가 보관해서가 아니다 — 우리 쪽 보관이 없으면 다음 시즌에
같은 일을 못 한다. `var/`(파생 캐시)가 아니라 재생성 불가 산출물이다.

## 같은 빌드 10벌은 중복이 아니다

한 컨셉의 상위 N명을 모으면 축마다 **불변(10/10=필수) vs 가변(3/10=자유석)**이
갈린다. 그 차이가 곧 「어디까지 바꿔도 되는가」 = 생성에 필요한 문법이다.
그래서 이 수집기는 **중복 제거를 하지 않는다** — 겹쳐 읽는 것이 목적이다.
(단 같은 캐릭터의 같은 갱신본은 한 번만 쌓는다. 그건 중복이 맞다.)

⚠ 차이의 사인은 둘이고 겉보기가 같다 — **설계 선택**("둘 다 된다")과
**예산·진행도**("나머지는 못 낀다"). 구분에 필요한 재료(레벨·장비)는 PoB 코드
안에 있으니, 구분은 해석 층의 몫이고 여기서는 재료를 빠뜨리지만 않으면 된다.
"""

from __future__ import annotations

import gzip
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from pok.common.paths import artifacts_dir

_BASE = "https://poe.ninja"
_UA = "poe2-ai-wiki/ladder-collector (research; contact via github.com/skerfolg)"
# poe.ninja 경로에 박힌 캐시 토큰. 값은 아무거나 통하지만(실측) 형태는 고정이다.
_TOKEN_RE = re.compile(r"\b\d{3,5}-\d{8}-\d{4,6}\b")
# 계정 표기는 `이름-태그` 꼴이다. CSS 토큰(coolgrey-100 등)과 갈라야 한다.
_ACCOUNT_RE = re.compile(r"\A[^\s#/]{3,32}-\d{3,5}\Z")

_MIN_INTERVAL_S = 0.7  # 남의 서버다 — 순차 + 간격

# 리그 슬러그 → 시즌. poe.ninja는 패치 번호를 주지 않으므로 **여기가 유일한 대응표**다.
# 정본(`knowledge/game-data/builds/<시즌>/`)이 시즌으로 갈리는데 원시가 슬러그로 갈리면
# 시즌이 쌓였을 때 "이 PoB 코드가 어느 시즌 것인가"를 이을 방법이 없다 — 그래서 원시도
# 시즌으로 재운다. 새 리그가 열리면 여기에 한 줄 추가한다.
_SEASON_BY_SLUG: dict[str, str] = {
    "runesofaldur": "0-5",
    "runesofaldurhc": "0-5",
    "runesofaldurssf": "0-5",
    "runesofaldurhcssf": "0-5",
    "vaal": "0-4",
    "vaalhc": "0-4",
    "vaalssf": "0-4",
    "vaalhcssf": "0-4",
}


class LadderError(RuntimeError):
    """수집이 진행될 수 없는 상태 — 조용히 빈 결과를 내지 않는다."""


@dataclass(frozen=True)
class CharacterRef:
    """목록에서 얻은 식별자. **순위는 질의 기준의 순서일 뿐** 강함이 아니다."""

    rank: int
    account: str
    name: str


@dataclass
class CollectReport:
    """무엇이 새로 쌓였고 무엇이 왜 빠졌는지 — 빠진 것을 말하지 않으면 전량으로 읽힌다."""

    league: str
    query: dict[str, str]
    requested: int
    written: list[str] = field(default_factory=list)
    skipped_same_revision: list[str] = field(default_factory=list)
    failed: list[dict[str, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "league": self.league,
            "query": self.query,
            "requested": self.requested,
            "written": self.written,
            "skipped_same_revision": self.skipped_same_revision,
            "failed": self.failed,
        }


# ──────────────────────────── HTTP ────────────────────────────


def _get(url: str, *, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": _UA, "Accept-Encoding": "gzip"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            if resp.headers.get("content-encoding") == "gzip":
                raw = gzip.decompress(raw)
            return raw
    except urllib.error.URLError as exc:  # 네트워크·404 전부 여기로
        raise LadderError(f"요청 실패: {url} — {exc}") from exc


def snapshot_token(league_slug: str) -> str:
    """API 경로에 필요한 캐시 토큰을 빌드 목록 페이지 HTML에서 뽑는다.

    JS 렌더 없이 원문 HTML에 박혀 있으므로 브라우저가 필요 없다.
    """
    html = _get(f"{_BASE}/poe2/builds/{league_slug}").decode("utf-8", "replace")
    found = _TOKEN_RE.findall(html)
    if not found:
        raise LadderError(
            f"{league_slug} 페이지에서 스냅샷 토큰을 못 찾았다 — "
            "poe.ninja가 경로 형식을 바꿨을 수 있다"
        )
    return found[0]


# ─────────────────────── protobuf (최소 판독) ───────────────────────
#
# 목록 엔드포인트는 `application/x-protobuf`인데 스키마가 공개돼 있지 않다.
# 와이어 포맷 자체는 스키마 없이도 **모호하지 않게** 읽힌다(태그=필드번호<<3|타입).
# 그래서 정규식으로 바이트를 훑지 않고 구조를 실제로 파싱한다 — 정규식은
# 문자열 비슷한 것이면 뭐든 집어서 CSS 토큰까지 딸려 온다.


def _read_varint(buf: bytes, i: int) -> tuple[int, int]:
    val = shift = 0
    while i < len(buf):
        b = buf[i]
        i += 1
        val |= (b & 0x7F) << shift
        if not b & 0x80:
            return val, i
        shift += 7
        if shift > 63:
            break
    raise ValueError("varint 손상")


def _iter_fields(buf: bytes):
    i = 0
    while i < len(buf):
        tag, i = _read_varint(buf, i)
        field_no, wire = tag >> 3, tag & 7
        if field_no == 0:
            raise ValueError("필드 번호 0")
        if wire == 0:
            val, i = _read_varint(buf, i)
            yield field_no, wire, val
        elif wire == 1:
            val, i = buf[i : i + 8], i + 8
            yield field_no, wire, val
        elif wire == 2:
            ln, i = _read_varint(buf, i)
            if ln < 0 or i + ln > len(buf):
                raise ValueError("길이 초과")
            yield field_no, wire, buf[i : i + ln]
            i += ln
        elif wire == 5:
            val, i = buf[i : i + 4], i + 4
            yield field_no, wire, val
        else:
            raise ValueError(f"알 수 없는 wire type {wire}")


def _strings_of(buf: bytes) -> list[str] | None:
    """이 메시지가 직접 가진 UTF-8 문자열 필드들. 파싱 불가면 None."""
    out: list[str] = []
    try:
        for _, wire, val in _iter_fields(buf):
            if wire == 2 and isinstance(val, bytes):
                try:
                    s = val.decode("utf-8")
                except UnicodeDecodeError:
                    continue
                if s and s.isprintable():
                    out.append(s)
    except ValueError:
        return None
    return out


def _columns(buf: bytes) -> dict[str, list[str]]:
    """응답은 **행이 아니라 열**이다 (실측 2026-08-12).

    각 컬럼은 `[컬럼id, 컬럼id, 값…]` 꼴이고, `name`·`account` 컬럼이 각각
    순위 순 값 배열을 갖는다. 행 단위로 읽으려 하면 계정 옆의 문자열이 캐릭터명이
    아니라 **스키마 문자열("account")**이라 엉뚱한 값을 집는다 — 실제로 그렇게 틀렸다.
    """
    out: dict[str, list[str]] = {}
    try:
        top = [v for _, w, v in _iter_fields(buf) if w == 2 and isinstance(v, bytes)]
    except ValueError:
        return out
    for body in top:
        try:
            subs = [v for _, w, v in _iter_fields(body) if w == 2 and isinstance(v, bytes)]
        except ValueError:
            continue
        for sub in subs:
            ss = _strings_of(sub)
            if not ss or len(ss) < 3 or ss[0] != ss[1]:
                continue
            out.setdefault(ss[0], ss[2:])
    return out


def _refs_from_columns(cols: dict[str, list[str]]) -> list[CharacterRef]:
    accounts, names = cols.get("account") or [], cols.get("name") or []
    if not accounts or not names:
        return []
    refs: list[CharacterRef] = []
    for rank, (acct, name) in enumerate(zip(accounts, names, strict=False), start=1):
        if not _ACCOUNT_RE.match(acct) or not name.strip():
            continue
        refs.append(CharacterRef(rank, acct, name))
    return refs


def search_characters(
    league_slug: str,
    *,
    filters: dict[str, str] | None = None,
    limit: int = 10,
    token: str | None = None,
) -> list[CharacterRef]:
    """컨셉을 필터로 주면 상위 N명을 순위 순으로 낸다.

    필터는 poe.ninja의 질의 파라미터를 그대로 쓴다 — 예 `{"class": "Chronomancer"}`,
    `{"skill": "Cast on Critical"}`. **컨셉 정의가 곧 필터다.**
    """
    token = token or snapshot_token(league_slug)
    overview = _overview_of(league_slug)
    params = {"overview": overview, **(filters or {})}
    url = f"{_BASE}/poe2/api/builds/{token}/search?{urllib.parse.urlencode(params)}"
    found = _refs_from_columns(_columns(_get(url)))
    if not found:
        raise LadderError(
            f"목록이 비었다 — 필터를 확인할 것({params}). "
            "poe.ninja가 protobuf 구조를 바꿨을 가능성도 있다"
        )
    return found[:limit]


def _overview_of(league_slug: str) -> str:
    """`runesofaldur` → `runes-of-aldur`. API는 하이픈 꼴을 받는다."""
    state = json.loads(_get(f"{_BASE}/poe2/api/data/index-state"))
    for group in state.values():
        if not isinstance(group, list):
            continue
        for lg in group:
            if isinstance(lg, dict) and lg.get("url") == league_slug:
                name = str(lg.get("name") or "")
                return name.lower().replace(" ", "-")
    raise LadderError(f"리그 슬러그를 index-state에서 못 찾았다: {league_slug}")


def fetch_character(
    league_slug: str, ref: CharacterRef, *, token: str | None = None
) -> dict[str, Any]:
    """캐릭터 1건의 원본 JSON. `pathOfBuildingExport`가 여기 들어 있다."""
    token = token or snapshot_token(league_slug)
    params = {
        "account": ref.account,
        "name": ref.name,
        "overview": _overview_of(league_slug),
        "timeMachine": "",
    }
    url = f"{_BASE}/poe2/api/builds/{token}/character?{urllib.parse.urlencode(params)}"
    return json.loads(_get(url))


# ──────────────────────────── 저장 ────────────────────────────


def ladder_dir(root: Path | None = None) -> Path:
    return artifacts_dir(root) / "ladder"


def _safe(part: str) -> str:
    """캐릭터명에 한글·키릴·이모지가 들어온다 — 파일명으로 쓸 수 있게만 다듬는다."""
    cleaned = re.sub(r"[^\w.-]+", "_", part, flags=re.UNICODE).strip("_")
    return cleaned[:80] or "unnamed"


def season_of(league_slug: str) -> str:
    """리그 슬러그 → 시즌. 모르는 리그면 **추측하지 않고 멈춘다**.

    빠뜨린 채 진행하면 슬러그 이름의 디렉터리가 조용히 하나 더 생기고, 나중에
    시즌 대조가 안 되는 원시 뭉치가 남는다.
    """
    season = _SEASON_BY_SLUG.get(league_slug)
    if not season:
        raise LadderError(
            f"리그 슬러그 '{league_slug}'의 시즌을 모른다 — "
            "ladder._SEASON_BY_SLUG에 등록할 것(원시도 시즌으로 재운다)"
        )
    return season


def concept_slug(filters: dict[str, str] | None) -> str:
    """질의 필터 → 디렉터리 이름. **컨셉 정의가 곧 필터**이므로 그대로 이름이 된다.

    필터 없이 모으면(리그 전체 상위 N) `_all`로 간다.
    """
    if not filters:
        return "_all"
    parts = [f"{_safe(k)}-{_safe(v)}" for k, v in sorted(filters.items())]
    return "__".join(parts)[:120]


def _record_path(base: Path, league_slug: str, doc: dict[str, Any], concept: str) -> Path:
    rev = str(doc.get("updatedUtc") or doc.get("lastSeenUtc") or "unknown")[:19]
    stem = f"{_safe(str(doc.get('account')))}__{_safe(str(doc.get('name')))}__{_safe(rev)}"
    return base / season_of(league_slug) / concept / f"{stem}.json"


def store_character(
    doc: dict[str, Any],
    *,
    league_slug: str,
    ref: CharacterRef,
    query: dict[str, str],
    base: Path | None = None,
) -> tuple[Path, bool]:
    """append-only 저장. 이미 있는 갱신본이면 (경로, False)."""
    base = base or ladder_dir()
    concept = concept_slug(query)
    path = _record_path(base, league_slug, doc, concept)
    if path.exists():
        return path, False
    pob = doc.get("pathOfBuildingExport")
    if not isinstance(pob, str) or len(pob) < 100:
        raise LadderError(
            f"{ref.account}/{ref.name}: PoB 코드가 없거나 너무 짧다 — 저장하지 않는다"
        )
    payload = {
        "source": "poe.ninja",
        "league_slug": league_slug,
        "season": season_of(league_slug),
        "concept": concept,
        "query": query,
        "rank_in_query": ref.rank,
        "collected_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        # ↓ poe.ninja가 준 출처 시각. 우리 수집 시각과 **다르다** — 캐릭터 스냅샷은
        #   며칠 전 것일 수 있어서 패치 경계와 대조하려면 둘 다 있어야 한다.
        "character_last_seen_utc": doc.get("lastSeenUtc"),
        "character_updated_utc": doc.get("updatedUtc"),
        "pob_export": pob,
        "raw": doc,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return path, True


def collect(
    league_slug: str,
    *,
    filters: dict[str, str] | None = None,
    limit: int = 10,
    base: Path | None = None,
) -> CollectReport:
    """컨셉 하나에 대해 상위 N명의 PoB 코드를 쌓는다.

    중복 제거는 **하지 않는다** — 같은 빌드 여러 벌이 이 수집의 목적이다.
    """
    query = dict(filters or {})
    token = snapshot_token(league_slug)
    refs = search_characters(league_slug, filters=filters, limit=limit, token=token)
    report = CollectReport(league=league_slug, query=query, requested=limit)
    base = base or ladder_dir()
    for ref in refs:
        time.sleep(_MIN_INTERVAL_S)
        who = f"{ref.account}/{ref.name}"
        try:
            doc = fetch_character(league_slug, ref, token=token)
            path, is_new = store_character(
                doc, league_slug=league_slug, ref=ref, query=query, base=base
            )
        except LadderError as exc:
            report.failed.append({"character": who, "why": str(exc)})
            continue
        (report.written if is_new else report.skipped_same_revision).append(
            f"{who} → {path.name}" if is_new else who
        )
    return report
