"""런타임의 PoB 소스 직독을 경계 안에 가둔다 (#63 P4).

`external/pob`는 **gitignore된 파생물**이다 — 게임 사실의 판정이 거기 걸리면
철칙 2(파생을 진실로 취급 금지) 위반이고, `search_kb`로 닿지 않으며, CI처럼
데이터가 없는 환경에서 통째로 죽는다(#62에서 통합 테스트 5건이 그랬다).

게임 사실은 `kb/ingest/`가 패치 때 KB에 수록하고, 런타임은 KB를 읽는다
(`kb/skill_facts.py`가 그 본보기다). PoB 소스를 직접 읽어도 되는 곳은:

- `kb/pob_pin.py` — 핀·경로의 **정의** (손대는 곳은 여기 하나)
- `kb/ingest/**` — 수집기 (패치 때만 돈다)
- `pob/catalog.py` — "PoB에 실재하는가"라는 **계산기 계약 검증**(gem_ids·config_vars).
  존재 검증은 PoB가 옳은 권위다 — 게임 사실이 아니다
- `pob/uniques.py` — 유니크 아이템 **원문**의 정본은 PoB다(#34 B, AD-1) — 변형과
  모드 줄의 연결이 KB에 없고, 그 텍스트는 계산기 입력이다
- `pob/versions.py` — 스냅샷 해석 (계산 실행 경로)

여기 안 드는 파일이 걸리면: 그 사실을 `kb/ingest/`로 수집해 KB에 넣고
KB에서 읽어라. 목록에 추가하는 것은 구조 결정이다 — 사용자 합의가 필요하다(철칙 1).
"""

from __future__ import annotations

import re
from pathlib import Path

SRC = Path(__file__).resolve().parents[2] / "src" / "pok"

# 접촉 감지 2종: 핀 모듈에서 경로 함수를 가져가거나, 스냅샷 경로를 직접 조립하거나.
# (`POB_COMMIT` 상수만 가져가는 것은 출처 표기용이라 접촉이 아니다.)
_PIN_IMPORT = re.compile(r"from pok\.kb\.pob_pin import [^\n]*(pob_src_dir|pob_root)")
_PATH_LITERAL = re.compile(r"[\"']external/pob|\"external\"\s*/\s*\"pob\"")

_ALLOWED_FILES = {
    "kb/pob_pin.py",
    "pob/catalog.py",
    "pob/uniques.py",
    "pob/versions.py",
}
_ALLOWED_PREFIX = "kb/ingest/"


def _touchers() -> set[str]:
    out: set[str] = set()
    for path in sorted(SRC.rglob("*.py")):
        text = path.read_text(encoding="utf-8")
        if _PIN_IMPORT.search(text) or _PATH_LITERAL.search(text):
            out.add(path.relative_to(SRC).as_posix())
    return out


def test_pob_source_is_read_only_inside_the_boundary() -> None:
    offenders = {
        f for f in _touchers() if f not in _ALLOWED_FILES and not f.startswith(_ALLOWED_PREFIX)
    }
    assert not offenders, (
        f"PoB 소스를 경계 밖에서 읽는다: {sorted(offenders)} — 게임 사실이면 "
        "kb/ingest/ 수집기로 KB에 수록하고 kb/skill_facts.py처럼 KB에서 읽을 것. "
        "경계 목록 추가는 구조 결정이라 사용자 합의가 필요하다(철칙 1·5)"
    )


def test_the_allowlist_does_not_rot() -> None:
    """허용 목록의 파일이 접촉을 끊었으면 목록에서도 빼야 한다 — 죽은 예외는 구멍이 된다."""
    touching = _touchers()
    stale = {f for f in _ALLOWED_FILES if f not in touching}
    assert not stale, f"더는 PoB 소스를 읽지 않는데 허용 목록에 남아 있다: {sorted(stale)}"
