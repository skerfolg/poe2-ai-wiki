"""통합 시험은 **PoB 없이도 수집 가능**해야 한다 (2026-08-22).

CI에는 `external/pob` 스냅샷도 LuaJIT도 없다. 그래서 통합 시험은 `skipif`로 환경을
확인하고 건너뛴다 — 파일 머리의 `pytestmark`든 함수별 데코레이터든 **형태는 자유이고
존재가 강제다**.

⛔ 이걸 빠뜨리면 **CI가 통째로 빨간불이 된다** — 실측: 내가 만든
`test_flask_charm_active.py`가 가드 없이 데몬을 띄워 macOS·Windows 양쪽이 깨졌다.
문서에 적는 방식으로는 안 지켜지므로(철칙 5) 여기서 잠근다.
"""

from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
# PoB를 안 쓰는 통합 시험 — 가드가 없어도 된다. 추가할 땐 근거와 함께 적을 것.
_NO_POB: frozenset[str] = frozenset()


def test_PoB를_쓰는_통합_시험은_환경_가드를_가진다() -> None:
    missing = []
    for path in sorted((_ROOT / "tests" / "integration").glob("test_*.py")):
        if path.name in _NO_POB:
            continue
        text = path.read_text(encoding="utf-8")
        uses_pob = any(token in text for token in ("PobDaemon", "resolve_snapshot", "compute_pob"))
        # ⚠ 형태를 하나로 못 박지 않는다 — 이 레포엔 `pytestmark`와 함수별 데코레이터가
        #   둘 다 쓰인다. 처음엔 `pytestmark`만 찾다 멀쩡한 시험 5개를 위반으로 잡았다.
        #   강제할 것은 「환경을 보고 건너뛰는가」이지 그 표기법이 아니다.
        if uses_pob and "skipif" not in text:
            missing.append(path.name)
    assert not missing, (
        f"환경 가드 없는 통합 시험: {missing} — "
        "`pytest.mark.skipif(not _env_ready(), ...)`를 붙일 것"
        "(파일 머리 pytestmark 또는 함수별 데코레이터). "
        "없으면 PoB 스냅샷이 없는 CI에서 통째로 실패한다"
    )
