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

- 자가 점화 차단 여부 — 증명: 지옥불꽃 활성 상태에서 자가 점화 디버프가 뜨는지 인게임 관측

## 결정 관문

1. 로우라이프가 점유만으로 유지되는가
2. 색상 과반이 5보조 세트에서 성립하는가

## 다음 결정 순서

1. 색상 장부 인게임 확인
2. 점유 정보창 확인
"""


def test_미니_문서_전_요소_추출() -> None:
    d = parse_design(_MINI)
    assert (d.version, d.updated, d.goal) == ("v1", "2026-08-02", "맵핑 1버튼")
    assert len(d.gates) == 2  # 컨셉을 언제 접을지의 기준 (계약 v2)
    assert d.unverified[0].actionable  # 판정 조건이 붙은 가설 = 실행 가능
    assert "인게임 관측" in d.unverified[0].proof
    assert d.unverified[0].claim == "자가 점화 차단 여부"  # 조건은 claim에서 분리된다
    assert d.status is not None and d.status.startswith("색상 장부")
    assert d.has_constraints and not d.warnings
    assert d.confirmed == ("인퍼널리스트", "로우라이프")
    assert d.tentative == ("불씨 5보조 세트",)
    assert len(d.unverified) == 1
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
    assert d.has_constraints
    assert len(d.queue) == 16  # v6 §15 다음 결정 순서
    assert len(d.unverified) >= 20  # §14 미검증 = P5 가설 목록 (D29)
    # v6는 계약 v1 시절 문서라 판정 조건·결정 관문이 없다 — 그게 THOR에서 배운
    # 갭의 실증이다(가설이 큐에 쌓이기만 하고 검증이 실행되지 않았다).
    assert all(not h.actionable for h in d.unverified)
    assert d.gates == ()
    assert any("판정 조건 없는 가설" in w for w in d.warnings)
    assert any("결정 관문" in w for w in d.warnings)
    assert any("66" in f.text for f in d.formulas)  # §5 점유 공식


# ── 계약 v2: 가설 판정 조건 + 결정 관문 (2026-08-04) ──────────────────


def test_판정_조건_표지_세_가지를_받는다() -> None:
    """`증명`/`판정`/`검증` — 문서를 쓰는 사람이 표현을 고를 수 있어야 한다."""
    for marker in ("증명", "판정", "검증"):
        d = parse_design(f"## 미검증\n\n- 어떤 주장 — {marker}: 관측 조건\n")
        assert d.unverified[0].claim == "어떤 주장"
        assert d.unverified[0].proof == "관측 조건" and d.unverified[0].actionable


def test_굵게_표기와_중점_구분자도_받는다() -> None:
    d = parse_design("## 미검증\n\n- 주장 · **증명**: 조건\n")
    assert d.unverified[0].claim == "주장" and d.unverified[0].proof == "조건"


def test_조건_없는_가설은_실행_불가로_표시된다() -> None:
    """가설만 적으면 큐에 쌓이기만 하고 검증이 실행되지 않는다 (v6가 그랬다)."""
    d = parse_design("## 미검증\n\n- 조건 없는 주장\n")
    h = d.unverified[0]
    assert h.claim == "조건 없는 주장" and h.proof == "" and not h.actionable
    assert any("판정 조건 없는 가설 1건" in w for w in d.warnings)


def test_확정_잠정에는_판정_조건을_떼지_않는다() -> None:
    """이미 판정된 것에 붙은 근거 서술까지 분해하면 본문이 훼손된다."""
    d = parse_design("## 확정\n\n- 로우라이프 — 증명: 인게임 확인\n")
    assert d.confirmed == ("로우라이프 — 증명: 인게임 확인",)


def test_결정_관문은_번호_목록으로_모인다() -> None:
    d = parse_design("## 13. 결정 관문\n\n1. 트리거가 충분히 빠른가\n2. 공격이 쓸모 있는가\n")
    assert d.gates == ("트리거가 충분히 빠른가", "공격이 쓸모 있는가")


def test_계속_조건도_같은_섹션으로_인식한다() -> None:
    assert parse_design("## 계속 조건\n\n1. 관문 하나\n").gates == ("관문 하나",)


def test_관문_없으면_경고한다() -> None:
    """관문이 없으면 성립하는 한 계속 파게 된다 — v6→v7이 그랬다."""
    assert any("결정 관문" in w for w in parse_design("# 문서\n").warnings)


def test_관문_섹션은_큐와_섞이지_않는다() -> None:
    """둘 다 번호 목록이라 섹션 경계가 흐려지면 서로를 오염시킨다."""
    doc = "## 결정 관문\n\n1. 관문 A\n\n## 다음 결정 순서\n\n1. 큐 A\n2. 큐 B\n"
    d = parse_design(doc)
    assert d.gates == ("관문 A",) and d.queue == ("큐 A", "큐 B")
