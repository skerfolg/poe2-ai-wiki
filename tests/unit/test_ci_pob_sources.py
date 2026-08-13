"""CI가 받는 PoB 소스 목록은 **카탈로그가 읽는 파일과 함께 움직인다** (2026-08-13).

실측: #68이 `quest_config_vars()`로 `Data/QuestRewards.lua`를 읽기 시작했는데
`.github/workflows/ci.yml`의 내려받기 목록에 없어 러너에서 pytest 16건이
FileNotFoundError로 죽었다. 로컬은 PoB 전체 클론이 있어 아무도 못 봤고, CI는
mypy에서 먼저 죽어 이 실패가 **보이지도 않았다**.

「목록을 같이 늘려라」는 ci.yml 주석에도 적혀 있(게 됐)지만, 문서에만 있는 규율은
이 레포에서 안 지켜지는 것이 증명돼 있다(철칙 5 — 규율은 강제 지점이 있어야 한다).
그래서 감지를 여기 둔다. 카탈로그가 새 파일을 열면 이 테스트가 먼저 막는다.
"""

from __future__ import annotations

import re

from pok.common.paths import project_root

# `(pob_src(root) / "Data" / "Gems.lua")` 꼴 — 카탈로그는 이 한 가지 형태로만 연다.
_READ = re.compile(r'pob_src\(root\)\s*/\s*"([^"]+)"\s*/\s*"([^"]+)"')
# 워크플로의 내려받기 목록: `for f in <경로들>; do`. **주석이 아니라 목록**을 봐야 한다 —
# 파일 전체에서 문자열을 찾으면 이 실패를 설명하는 주석에도 걸려 통과해 버린다(실측).
_LIST = re.compile(r"for f in\s+(.+?);\s*do", re.DOTALL)


def _downloaded(workflow: str) -> set[str]:
    m = _LIST.search(workflow)
    assert m, "ci.yml에서 PoB 소스 내려받기 목록을 못 찾았다 — 이 테스트가 낡았다"
    # 줄 잇는 `\`는 토큰이 아니다 — 경로만 남긴다.
    return {t for t in m.group(1).split() if t != "\\"}


def test_catalog가_여는_파일은_전부_ci가_받는다() -> None:
    root = project_root()
    catalog = (root / "src" / "pok" / "pob" / "catalog.py").read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "ci.yml").read_text(encoding="utf-8")

    needed = {f"{d}/{f}" for d, f in _READ.findall(catalog)}
    assert needed, "카탈로그에서 PoB 파일 읽기를 하나도 못 찾았다 — 이 테스트가 낡았다"

    missing = sorted(needed - _downloaded(workflow))
    assert not missing, (
        f"카탈로그가 읽는데 CI가 받지 않는 PoB 소스: {missing} — "
        "ci.yml의 「PoB catalog sources」 목록에 추가할 것 "
        "(러너에는 전체 클론이 없어 이 파일들만 존재한다)"
    )
