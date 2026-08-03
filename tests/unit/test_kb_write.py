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
