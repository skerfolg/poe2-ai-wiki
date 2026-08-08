"""PoB 스냅샷 핀이 **여러 곳에 흩어져 있다** — 전부 같은 커밋을 가리켜야 한다.

`manifest.json`의 `pob_commit`이 정본 핀이고 `resolve_snapshot()`이 그것을 읽는다.
그런데 같은 값이 CI 워크플로 2개와 소스 상수 5곳에 **손으로 복사돼 있다**. 하나만
빠뜨리면 조용히 갈라진다: 계산은 새 스냅샷으로 도는데 카탈로그 검증은 옛 파일을
읽는 식이라, 증거 체인(AD-2 — 새 버전은 새 클론)이 거짓이 된다.

스냅샷 교체 절차를 문서(`skills/pob-snapshot/`)에만 두면 안 지켜진다(철칙 5).
그래서 **목록을 여기 코드로 두고 어긋나면 실패시킨다** — 문서의 체크리스트가 아니라
테스트가 빠뜨림을 잡는다.

⛔ `knowledge/game-data/**`의 `sources[].pob`는 **여기 대상이 아니다.** 그건 그
레코드를 **언제 어느 커밋에서 긁었는가**의 증거라, 스냅샷을 올렸다고 덮으면 계보가
거짓이 된다. 재수집이 값을 바꿀 때 그 경로가 갱신한다.
"""

from __future__ import annotations

import re

from pok.common.paths import project_root
from pok.kb.ingest import ailments, merge
from pok.pob import catalog
from pok.pob.versions import pinned_commit

# 핀이 복사돼 있는 곳 — 스냅샷을 바꾸면 **전부** 함께 바꿔야 한다.
# 소스 텍스트에서 찾는 것들(상수가 아니라 경로 문자열로 박혀 있다)
_TEXT_SITES = (
    ".github/workflows/ci.yml",
    ".github/workflows/pob-smoke.yml",
    "src/pok/kb/ingest/__main__.py",
)


def test_소스_상수가_manifest와_같은_커밋() -> None:
    full = pinned_commit()
    short = full[:7]
    assert short == catalog._POB_DIR, "pob/catalog.py"
    assert short == ailments._POB_DIR, "kb/ingest/ailments.py"
    assert full == merge.POB_COMMIT, "kb/ingest/merge.py"


def test_워크플로와_하드코딩_경로가_같은_커밋() -> None:
    """`external/pob/<short>` 경로가 소스에 직접 박힌 곳까지 본다."""
    full = pinned_commit()
    short = full[:7]
    root = project_root()
    for rel in _TEXT_SITES:
        text = (root / rel).read_text(encoding="utf-8")
        assert short in text, f"{rel}: 현재 핀({short})이 없다 — 스냅샷 교체 시 빠뜨렸다"


def test_다른_커밋이_섞여_있지_않다() -> None:
    """옛 핀이 남아 있으면 '고쳤다'는 착각이 그대로 통과한다.

    실측 2026-08-08: 핀 사이트가 8곳이라 손으로 세면 반드시 하나를 놓친다.
    """
    full = pinned_commit()
    root = project_root()
    stray: list[str] = []
    for rel in (*_TEXT_SITES, "src/pok/pob/catalog.py", "src/pok/kb/ingest/ailments.py"):
        text = (root / rel).read_text(encoding="utf-8")
        for found in re.findall(r"external/pob/([0-9a-f]{7,40})", text):
            if not full.startswith(found):
                stray.append(f"{rel}: {found}")
        for found in re.findall(r"POB_COMMIT:?\s*[=:]?\s*\"?([0-9a-f]{40})\"?", text):
            if found != full:
                stray.append(f"{rel}: {found}")
    assert not stray, f"manifest와 다른 PoB 커밋이 남아 있다: {stray}"
