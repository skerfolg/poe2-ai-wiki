"""kb/store 쓰기 단일 경로 — B-6 (KB_DATA_MODEL §9 쓰기 계약).

정본 쓰기가 여기 하나로 모이므로, 파괴 사고를 막는 안전장치도 여기서만 검증하면 된다:
① 쓰기 후 자동 재검증 ② 근거 없는 레코드 감소 거부 ③ 원자적 쓰기.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path
from typing import Any

import pytest

from pok.common.paths import project_root
from pok.kb.store import (
    KBValidationError,
    KBWriteError,
    load,
    patch_records,
    write_record,
    write_shard,
)


def _rec(rid: str, **data: Any) -> dict[str, Any]:
    return {
        "id": rid,
        "type": "Support",
        "name": {"ko": rid, "en": rid},
        "tags": [],
        "data": data,
        "verification": "GAME_DATA",
        "sources": [{"src": "poe2db", "ref": "x", "patch": "t"}],
    }


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    shard = knowledge / "game-data" / "gems" / "supports.ndjson"
    shard.parent.mkdir(parents=True)
    shard.write_text(
        "".join(json.dumps(_rec(f"support.s{i}"), ensure_ascii=False) + "\n" for i in range(3)),
        encoding="utf-8",
    )
    return root


def _shard(root: Path) -> Path:
    return root / "knowledge" / "game-data" / "gems" / "supports.ndjson"


def test_근거_없는_레코드_감소는_거부(repo: Path) -> None:
    """안전장치 ②: 부분 갱신이 정본을 조용히 깎지 못한다 (실측 830건 손실의 재발 방지)."""
    before = _shard(repo).read_text(encoding="utf-8")
    with pytest.raises(KBWriteError, match="근거 없는 레코드 감소"):
        write_shard(_shard(repo), [_rec("support.s0")], root=repo)
    assert _shard(repo).read_text(encoding="utf-8") == before  # 파일 그대로


def test_명시적_삭제는_허용되고_보고된다(repo: Path) -> None:
    report = write_shard(
        _shard(repo),
        [_rec("support.s0"), _rec("support.s1")],
        allow_delete=["support.s2"],
        root=repo,
    )
    assert report.removed == ("support.s2",)
    assert len(_shard(repo).read_text(encoding="utf-8").splitlines()) == 2


def test_신규와_갱신을_구분해_보고한다(repo: Path) -> None:
    report = write_shard(
        _shard(repo),
        [
            _rec("support.s0"),  # 동일 — updated 아님
            _rec("support.s1", color="red"),  # 내용 변경
            _rec("support.s2"),
            _rec("support.s9"),  # 신규
        ],
        root=repo,
    )
    assert report.added == ("support.s9",)
    assert report.updated == ("support.s1",)
    assert "+1 ~1 -0" in report.summary


def test_샤드에_개별_레코드_쓰기는_차단(repo: Path) -> None:
    """실제 파괴 경로: 샤드 path에 레코드 하나를 쓰면 파일 전체가 한 줄이 된다."""
    with pytest.raises(KBWriteError, match="write_shard"):
        write_record(_shard(repo), _rec("support.s0"), root=repo)
    assert len(_shard(repo).read_text(encoding="utf-8").splitlines()) == 3


def test_쓰기_후_자동_재검증(repo: Path) -> None:
    """안전장치 ①: 스키마를 깨는 쓰기는 예외로 드러난다."""
    broken = {**_rec("support.s0"), "verification": "NOT_A_LABEL"}
    with pytest.raises(KBValidationError):
        write_shard(
            _shard(repo),
            [broken, _rec("support.s1"), _rec("support.s2")],
            root=repo,
        )


def test_patch는_배치를_몰라도_된다(repo: Path) -> None:
    """호출자가 샤드/개별 판단을 하지 않는다 — 그 판단의 분산이 B-6이 없앤 결함."""
    patch_records({"support.s1": {"color": "blue"}}, root=repo)
    got = {json.loads(ln)["id"]: json.loads(ln) for ln in _shard(repo).read_text().splitlines()}
    assert got["support.s1"]["data"]["color"] == "blue"
    assert len(got) == 3  # 나머지 보존


def test_patch_None은_키_삭제(repo: Path) -> None:
    """재적용 멱등: 소스에서 사라진 값이 눌러붙지 않는다."""
    patch_records({"support.s1": {"color": "blue", "cost": [1]}}, root=repo)
    patch_records({"support.s1": {"color": "red", "cost": None}}, root=repo)
    got = {json.loads(ln)["id"]: json.loads(ln) for ln in _shard(repo).read_text().splitlines()}
    assert got["support.s1"]["data"] == {"color": "red"}


def test_없는_id_패치는_예외(repo: Path) -> None:
    with pytest.raises(KBWriteError, match="KB에 없는 id"):
        patch_records({"support.ghost": {"color": "red"}}, root=repo)


def test_쓰기는_원자적이다(repo: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """안전장치 ③: 교체 직전에 죽어도 기존 파일이 남는다 (반토막 방지)."""
    before = _shard(repo).read_text(encoding="utf-8")

    def boom(*_a: object, **_k: object) -> None:
        raise KeyboardInterrupt

    monkeypatch.setattr("pok.kb.store.os.replace", boom)
    with pytest.raises(KeyboardInterrupt):
        write_shard(_shard(repo), [_rec(f"support.s{i}") for i in range(4)], root=repo)
    assert _shard(repo).read_text(encoding="utf-8") == before
    leftovers = list(_shard(repo).parent.glob(".*tmp"))
    assert not leftovers, f"임시 파일 잔존: {leftovers}"


def test_로드가_없는_레코드도_안전(repo: Path) -> None:
    """빈 샤드에 처음 쓰는 경우(신규 파일)."""
    new = repo / "knowledge" / "game-data" / "gems" / "skills.ndjson"
    report = write_shard(new, [{**_rec("skill.a"), "type": "Skill"}], root=repo)
    assert report.added == ("skill.a",)
    assert "skill.a" in load(repo).records


# ── B-7: 필드 층 소실 차단 ────────────────────────────────────────────
#
# B-6이 파일 층(레코드 감소)을 막았지만 같은 사고가 **층을 바꿔** 재발했다:
# 샤드 830건 → `_verification` 라벨 2건 → `promoted_to` 계보 1건.
# 원인은 하나다 — "부분 갱신"을 "전체 교체"로 수행한다. 여기서 끊는다.


def test_중첩_부분_갱신이_형제_키를_보존한다(repo: Path) -> None:
    """실측 손실(2026-08-04): 라벨 하나를 더하려다 형제 라벨 2건이 사라졌다."""
    patch_records({"support.s1": {"_verification": {"a": "GAME_DATA", "b": "IN_GAME"}}}, root=repo)
    patch_records({"support.s1": {"_verification": {"c": "POB_CODE"}}}, root=repo)
    got = {json.loads(ln)["id"]: json.loads(ln) for ln in _shard(repo).read_text().splitlines()}
    assert got["support.s1"]["data"]["_verification"] == {
        "a": "GAME_DATA",
        "b": "IN_GAME",
        "c": "POB_CODE",
    }


def test_같은_키는_새_값이_이긴다(repo: Path) -> None:
    """병합이 깊어도 갱신은 갱신이다 — 덮어쓰기 자체를 막는 게 아니다."""
    patch_records({"support.s1": {"_verification": {"a": "UNVERIFIED"}}}, root=repo)
    patch_records({"support.s1": {"_verification": {"a": "IN_GAME"}}}, root=repo)
    got = {json.loads(ln)["id"]: json.loads(ln) for ln in _shard(repo).read_text().splitlines()}
    assert got["support.s1"]["data"]["_verification"] == {"a": "IN_GAME"}


def test_근거_없는_필드_소실은_거부한다(repo: Path) -> None:
    """dict를 스칼라로 갈아끼우면 안쪽 값이 통째로 사라진다 — 조용히 넘어가지 않는다."""
    patch_records({"support.s1": {"req": {"str": 10, "dex": 20}}}, root=repo)
    with pytest.raises(KBWriteError, match="근거 없는 소실"):
        patch_records({"support.s1": {"req": 30}}, root=repo)
    got = {json.loads(ln)["id"]: json.loads(ln) for ln in _shard(repo).read_text().splitlines()}
    assert got["support.s1"]["data"]["req"] == {"str": 10, "dex": 20}  # 원본 보존


def test_명시한_삭제는_통과한다(repo: Path) -> None:
    """None은 근거 있는 삭제다 — 재적용 멱등성이 이 경로를 쓴다."""
    patch_records({"support.s1": {"req": {"str": 10, "dex": 20}}}, root=repo)
    patch_records({"support.s1": {"req": {"dex": None}}}, root=repo)
    got = {json.loads(ln)["id"]: json.loads(ln) for ln in _shard(repo).read_text().splitlines()}
    assert got["support.s1"]["data"]["req"] == {"str": 10}


def test_allow_drop으로_의도적_교체를_허용한다(repo: Path) -> None:
    """구조를 바꿔야 할 때가 있다 — 다만 근거를 남기게 한다."""
    patch_records({"support.s1": {"req": {"str": 10, "dex": 20}}}, root=repo)
    patch_records({"support.s1": {"req": 30}}, allow_drop=["req.str", "req.dex"], root=repo)
    got = {json.loads(ln)["id"]: json.loads(ln) for ln in _shard(repo).read_text().splitlines()}
    assert got["support.s1"]["data"]["req"] == 30


def test_소실_거부는_파일을_건드리지_않는다(repo: Path) -> None:
    """거부는 쓰기 전에 난다 — 반쯤 적용된 상태가 남으면 안 된다."""
    patch_records({"support.s1": {"req": {"str": 10}}}, root=repo)
    before = _shard(repo).read_text(encoding="utf-8")
    with pytest.raises(KBWriteError):
        patch_records(
            {"support.s1": {"req": 1}, "support.s2": {"color": "red"}},
            root=repo,
        )
    assert _shard(repo).read_text(encoding="utf-8") == before  # s2 갱신도 안 됐다


def test_여러_파일에_걸쳐도_한_건이라도_막히면_전부_취소(repo: Path) -> None:
    """검사와 쓰기가 섞이면 앞 파일만 써진 채 뒤에서 터진다 — 반쯤 적용 방지."""
    curated = repo / "knowledge" / "game-data" / "curated"
    curated.mkdir(parents=True, exist_ok=True)
    single = curated / "solo.json"
    single.write_text(
        json.dumps({**_rec("support.solo"), "data": {"keep": "me"}}, ensure_ascii=False),
        encoding="utf-8",
    )
    patch_records({"support.s1": {"req": {"str": 10}}}, root=repo)
    shard_before = _shard(repo).read_text(encoding="utf-8")

    with pytest.raises(KBWriteError, match="근거 없는 소실"):
        patch_records(
            {"support.solo": {"other": 1}, "support.s1": {"req": 99}},  # 뒤엣것이 막힌다
            root=repo,
        )
    assert json.loads(single.read_text(encoding="utf-8"))["data"] == {"keep": "me"}
    assert _shard(repo).read_text(encoding="utf-8") == shard_before


def test_dropping_a_parent_also_drops_its_children() -> None:
    """부모를 `None`으로 지우면 **자식도 근거 있는 삭제**다 (백로그 #38 부수 발견).

    자식 경로를 근거에서 빼면 「의도한 삭제」가 「근거 없는 소실」로 거부된다 —
    실측 2026-08-10: `{"pob_modeling": None}`이 자식 5개(`detail`·`kind`·`snapshot`…)
    때문에 막혀 **파싱 갭 재감사가 통째로 못 돌았다.**
    """
    from pok.kb.store import _apply_test_hook  # type: ignore[attr-defined]

    data = {"keep": 1, "pob_modeling": {"supported": False, "kind": "x", "detail": "y"}}
    merged = _apply_test_hook(data, {"pob_modeling": None})
    assert merged == {"keep": 1}, merged
