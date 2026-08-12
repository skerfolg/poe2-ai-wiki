"""래더 수집기의 계약을 잠근다 (#67 5차).

수집기가 조용히 틀리는 방식은 셋이고, 셋 다 **결과가 그럴듯해 보인다**:

1. 목록에서 캐릭터가 아닌 문자열(CSS 토큰 등)을 집어 온다 → 없는 캐릭터를 조회한다
2. PoB 코드가 비어 있는데 저장한다 → 나중에 파싱 단계에서야 발견된다
3. 같은 갱신본을 덮어쓴다 → append-only가 깨져 **재생성 불가 데이터가 사라진다**
"""

from __future__ import annotations

import json

import pytest

from pok.artifacts.ladder import (
    CharacterRef,
    LadderError,
    _columns,
    _refs_from_columns,
    store_character,
)


def _varint(n: int) -> bytes:
    out = bytearray()
    while True:
        b = n & 0x7F
        n >>= 7
        out.append(b | (0x80 if n else 0))
        if not n:
            return bytes(out)


def _s(field_no: int, text: str) -> bytes:
    raw = text.encode("utf-8")
    return _varint(field_no << 3 | 2) + _varint(len(raw)) + raw


def _msg(field_no: int, body: bytes) -> bytes:
    return _varint(field_no << 3 | 2) + _varint(len(body)) + body


def _column(name: str, values: list[str]) -> bytes:
    """실제 응답의 컬럼 꼴: `[컬럼id, 컬럼id, 값…]` (실측 2026-08-12)."""
    body = b"".join(_s(1, s) for s in [name, name, *values])
    return _msg(12, body)


def _response(columns: bytes) -> bytes:
    return _msg(1, columns)


def test_계정과_캐릭터명을_같은_행으로_잇는다() -> None:
    """응답이 **열 지향**이라 행 단위로 읽으면 조용히 틀린다.

    실제로 그렇게 틀렸다 — 계정 옆 문자열을 캐릭터명으로 집었더니 스키마 문자열
    `"account"`가 잡혀서 `.../character?name=account`로 404를 맞았다.
    """
    payload = _response(
        _column("class", ["Chronomancer"])
        + _column("name", ["сильнейшийнегр", "BoBerCully", "게살크로노맨서"])
        + _column("account", ["HoodwinkTheSlayer-7436", "WOualey-0844", "hjkuyirt-6839"])
    )
    refs = _refs_from_columns(_columns(payload))

    assert [(r.rank, r.account, r.name) for r in refs] == [
        (1, "HoodwinkTheSlayer-7436", "сильнейшийнегр"),
        (2, "WOualey-0844", "BoBerCully"),
        (3, "hjkuyirt-6839", "게살크로노맨서"),
    ]


def test_컬럼이_없으면_빈_목록() -> None:
    """poe.ninja가 구조를 바꾸면 **빈 목록**이어야 한다 — 호출부가 사유와 함께 멈춘다.
    조용히 일부만 내면 "상위 10명을 모았다"고 착각한 채 진행된다."""
    assert _refs_from_columns(_columns(_response(_column("class", ["Chronomancer"])))) == []
    assert _columns(b"\xff\xff\xff\xff\xff\xff\xff\xff") == {}


def _doc(pob: str = "eNrt" + "x" * 200, rev: str = "2026-08-11T21:35:51Z") -> dict:
    return {
        "account": "WOualey-0844",
        "name": "BoBerCully",
        "level": 100,
        "class": "Chronomancer",
        "pathOfBuildingExport": pob,
        "lastSeenUtc": rev,
        "updatedUtc": rev,
    }


def test_pob_코드가_없으면_저장하지_않는다(tmp_path) -> None:
    """코드가 없는 레코드를 쌓으면 **수집이 된 것처럼 보이는 구멍**이 남는다."""
    ref = CharacterRef(1, "WOualey-0844", "BoBerCully")
    for broken in (
        {"pathOfBuildingExport": None},
        {"pathOfBuildingExport": ""},
        {"pathOfBuildingExport": "short"},
    ):
        doc = _doc() | broken
        with pytest.raises(LadderError):
            store_character(doc, league_slug="runesofaldur", ref=ref, query={}, base=tmp_path)


def test_같은_갱신본은_덮어쓰지_않는다(tmp_path) -> None:
    """append-only — PoB 코드는 나중에 다시 못 가져오므로 덮어쓰기는 곧 소실이다."""
    ref = CharacterRef(1, "WOualey-0844", "BoBerCully")
    path, first = store_character(
        _doc(), league_slug="runesofaldur", ref=ref, query={"class": "Chronomancer"}, base=tmp_path
    )
    assert first is True

    again, second = store_character(
        _doc(pob="eNrt" + "y" * 200),
        league_slug="runesofaldur",
        ref=ref,
        query={"class": "Chronomancer"},
        base=tmp_path,
    )
    assert (again, second) == (path, False)
    assert json.loads(path.read_text(encoding="utf-8"))["pob_export"].endswith("x")

    # 캐릭터가 갱신되면 **새 파일**로 쌓인다 (같은 캐릭터의 시간축이 보존된다)
    _, third = store_character(
        _doc(rev="2026-08-12T09:00:00Z"),
        league_slug="runesofaldur",
        ref=ref,
        query={"class": "Chronomancer"},
        base=tmp_path,
    )
    assert third is True
    assert len(list((tmp_path / "0-5" / "class-Chronomancer").glob("*.json"))) == 2


def test_출처와_측정을_섞지_않는다(tmp_path) -> None:
    """레벨·DPS는 PoB 코드 안에 있다 — 목록에서 긁어 담으면 진실이 둘이 된다.

    저장 페이로드가 담는 수치는 **출처(언제 관측됐나)**뿐이어야 한다.
    """
    ref = CharacterRef(3, "WOualey-0844", "BoBerCully")
    path, _ = store_character(
        _doc(), league_slug="runesofaldur", ref=ref, query={"class": "Chronomancer"}, base=tmp_path
    )
    saved = json.loads(path.read_text(encoding="utf-8"))
    assert saved["rank_in_query"] == 3
    # 원시도 **시즌**으로 재운다 — 정본이 시즌으로 갈리는데 원시가 슬러그면 못 잇는다
    assert path.parent == tmp_path / "0-5" / "class-Chronomancer"
    assert saved["character_last_seen_utc"] and saved["collected_utc"]
    assert set(saved) == {
        "source",
        "league_slug",
        "season",
        "concept",
        "query",
        "rank_in_query",
        "collected_utc",
        "character_last_seen_utc",
        "character_updated_utc",
        "pob_export",
        "raw",
    }


def test_모르는_리그는_추측하지_않고_멈춘다(tmp_path) -> None:
    """슬러그→시즌 대응표에 없으면 실패해야 한다.

    조용히 슬러그 이름으로 쌓으면 **시즌 대조가 안 되는 원시 뭉치**가 남는다 —
    정본은 시즌(`0-5/`)으로 갈리는데 원시만 슬러그(`runesofaldur/`)로 갈렸던
    상태가 정확히 그 문제였다(사용자 승인 2026-08-12로 시즌 기준 통일).
    """
    ref = CharacterRef(1, "WOualey-0844", "BoBerCully")
    with pytest.raises(LadderError, match="시즌을 모른다"):
        store_character(_doc(), league_slug="somenewleague", ref=ref, query={}, base=tmp_path)


def test_한_빌드_안의_중복은_한_번만_센다() -> None:
    """묻는 것은 「몇 명이 쓰나」이지 「몇 번 끼나」가 아니다.

    한 빌드가 같은 보조를 3군데 끼웠다고 채택률이 3배가 되면 **불변/가변 판정이
    통째로 틀어진다** — 이 데이터의 값어치가 바로 그 판정이다.
    """
    from pok.engine.ladder_aggregate import _tally

    out = _tally([["A", "A", "A", "B"], ["A"], ["B"]])
    assert out == [
        {"ref": "A", "share": 66.7, "count": 2},
        {"ref": "B", "share": 66.7, "count": 2},
    ]


def test_두_단어_컨셉도_id가_스키마를_통과한다() -> None:
    """수집 디렉터리 이름은 **그대로 id가 될 수 없다**.

    디렉터리는 `_safe()`가 공백을 `_`로 바꿔 만드는데(`skills-Herald_of_Ice`)
    envelope의 entityId는 `[a-z0-9-]`만 받는다. 실측 2026-08-12: 그 차이로
    정본이 깨져 수집 작업이 중단됐다 — 앵커 표 8종 중 5종이 두 단어 이상이라
    **이 경로는 예외가 아니라 다수다**.
    """
    import re

    from pok.common.paths import knowledge_dir
    from pok.engine.ladder_aggregate import profile_id_slug

    pattern = json.loads((knowledge_dir() / "schema" / "record.schema.json").read_text("utf-8"))[
        "$defs"
    ]["entityId"]["pattern"]

    for concept in (
        "skills-Herald_of_Ice",
        "keypassives-Mind_Over_Matter",
        "skills-Arc__skillmodes-Totem",
        "skillmodes-Totem",
    ):
        rid = f"usage-profile.{profile_id_slug(f'0-5-{concept}')}"
        assert re.match(pattern, rid), f"{concept} → {rid}가 entityId 패턴에 걸린다"
