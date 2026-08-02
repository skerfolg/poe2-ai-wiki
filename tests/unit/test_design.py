"""artifacts/design — BUILD_DESIGN §4 기계 가독 계약 (lenient 파서)."""

from __future__ import annotations

from pathlib import Path

import pytest

from pok.artifacts.design import parse_design
from pok.common.paths import project_root

_MINI = """# 테스트 빌드 설계

- 갱신일: 2026-08-02
- 문서 버전: v1
- 상태: 색상 장부 확인 / 점유 계산 전
- 운용 목표: 맵핑 1버튼

## 제약 원장

점유 공식:

```text
실제 점유율 = 66% ÷ (1 + 총 점유 효율)
```

| 스킬 | 빨강 | 파랑 |
|---|---:|---:|
| 불씨 | 3 | 1 |
| CoEA | 3 | 1 |

## 확정

- 인퍼널리스트
- 로우라이프

## 잠정 선택

- 불씨 5보조 세트

## 미검증

- 자가 점화 차단 여부

## 다음 결정 순서

1. 색상 장부 인게임 확인
2. 점유 정보창 확인
"""


def test_미니_문서_전_요소_추출() -> None:
    d = parse_design(_MINI)
    assert (d.version, d.updated, d.goal) == ("v1", "2026-08-02", "맵핑 1버튼")
    assert d.status is not None and d.status.startswith("색상 장부")
    assert d.has_constraints and not d.warnings
    assert d.confirmed == ("인퍼널리스트", "로우라이프")
    assert d.tentative == ("불씨 5보조 세트",)
    assert d.unverified == ("자가 점화 차단 여부",)
    assert d.queue == ("색상 장부 인게임 확인", "점유 정보창 확인")
    assert len(d.formulas) == 1 and "66%" in d.formulas[0].text
    assert d.formulas[0].heading == "제약 원장"
    assert d.tables[0].header == ("스킬", "빨강", "파랑")
    assert d.tables[0].rows == (("불씨", "3", "1"), ("CoEA", "3", "1"))


def test_누락은_실패가_아니라_경고() -> None:
    d = parse_design("# 빈 문서\n\n본문뿐.\n")
    assert d.version is None and not d.has_constraints
    joined = "\n".join(d.warnings)
    assert "문서 버전" in joined and "제약" in joined and "미검증" in joined and "큐" in joined


def test_v6_실문서_추출(v6_path: Path | None = None) -> None:
    """실증: 규격의 원형(v6)이 계약 그대로 파싱되는가 (문서 없으면 skip)."""
    path = project_root() / "artifacts" / "builds" / "20260731-ember-fusillade-설계v6" / "design.md"
    if not path.exists():
        pytest.skip("v6 설계 문서 없음 (artifacts는 로컬 산출물)")
    d = parse_design(path.read_text(encoding="utf-8"))
    assert d.version == "v6" and d.updated == "2026-07-31"
    assert d.has_constraints and not d.warnings
    assert len(d.queue) == 16  # v6 §15 다음 결정 순서
    assert len(d.unverified) >= 20  # §14 미검증 = P5 가설 목록 (D29)
    assert any("66" in f.text for f in d.formulas)  # §5 점유 공식
