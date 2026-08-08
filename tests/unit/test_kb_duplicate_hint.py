"""중복 id 메시지가 **어느 쪽이 정본이 아닌지** 말하는가 (백로그 #21).

macOS 사본(`… 2.json`) 2개가 생겨 KB 조회가 **전부** 막힌 사고가 있었다. 무관한
레코드 2건의 중복이 16,000여 건의 조회를 차단했고, 원인을 찾는 데 몇 분이 걸렸다 —
무인 세션이었으면 그대로 멈췄을 것이다.

메시지가 사람을 **반대 방향으로** 보낸 것이 특히 나빴다: 파일을 이름순으로 읽으므로
사본(`Life_Loss 2.json`)이 먼저 등재되고 **원본이 "중복"으로 고발**됐다. 그대로 따르면
진짜 레코드를 지운다.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from pok.kb.store import KBValidationError, _untracked, load

_RECORD = {
    "id": "mechanic.dup-probe",
    "type": "Mechanic",
    "name": {"ko": "중복 탐침", "en": "Dup Probe"},
    "tags": [],
    "data": {"kind": "keyword", "stats": ["probe"]},
    "verification": "UNVERIFIED",
    "sources": [{"src": "poe2db", "ref": "https://example.invalid/probe", "patch": "0.5.4b"}],
}


@pytest.fixture
def kb_repo(tmp_path: Path) -> Path:
    """스키마를 실제 정본에서 빌려 온 최소 KB + git 저장소."""
    from pok.common.paths import knowledge_dir, schema_dir

    root = tmp_path / "repo"
    kdir = root / "knowledge"
    (kdir / "game-data" / "mechanics").mkdir(parents=True)
    dst = kdir / "schema"
    dst.mkdir()
    for path in schema_dir().rglob("*"):
        target = dst / path.relative_to(schema_dir())
        target.parent.mkdir(parents=True, exist_ok=True)
        if path.is_file():
            target.write_bytes(path.read_bytes())
    assert knowledge_dir() != kdir
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    return root


def _write(root: Path, name: str, record: dict[str, object]) -> Path:
    path = root / "knowledge" / "game-data" / "mechanics" / name
    path.write_text(json.dumps(record, ensure_ascii=False), encoding="utf-8")
    return path


def test_미추적_사본을_지목한다(kb_repo: Path) -> None:
    """추적본과 사본이 함께 있으면 **사본 쪽**을 미추적으로 짚어야 한다."""
    _write(kb_repo, "probe.json", _RECORD)
    subprocess.run(["git", "-C", str(kb_repo), "add", "-A"], check=True)
    _write(kb_repo, "probe 2.json", _RECORD)  # 사본은 커밋하지 않는다 = 미추적
    _untracked.cache_clear()

    with pytest.raises(KBValidationError) as excinfo:
        load(kb_repo)
    message = str(excinfo.value)
    assert "git 미추적" in message
    assert "probe 2.json" in message
    # 정본이 어느 쪽인지 말해야 한다 — 이걸 안 하면 사람이 원본을 지운다
    assert "정본은 probe.json 쪽이다" in message


def test_둘_다_추적본이면_추측하지_않는다(kb_repo: Path) -> None:
    """진짜 중복(둘 다 커밋됨)에 "사본일 것"이라고 말하면 그게 오도다."""
    _write(kb_repo, "probe.json", _RECORD)
    _write(kb_repo, "probe-b.json", _RECORD)
    subprocess.run(["git", "-C", str(kb_repo), "add", "-A"], check=True)
    _untracked.cache_clear()

    with pytest.raises(KBValidationError) as excinfo:
        load(kb_repo)
    message = str(excinfo.value)
    assert "중복 id mechanic.dup-probe" in message
    assert "git 미추적" not in message


def test_git이_아니어도_죽지_않는다(tmp_path: Path) -> None:
    """판정할 수 없으면 **아무 말도 하지 않는다** — 없는 근거를 지어내지 않는다."""
    _untracked.cache_clear()
    assert _untracked(tmp_path / "없는곳") == frozenset()
