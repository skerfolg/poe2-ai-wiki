"""표준 출력 인코딩 고정 — 크로스플랫폼(D21, Windows+macOS).

**왜 필요한가**: Windows의 Python 기본 stdout은 로케일 코드페이지다(한국어
환경이면 `cp949`). cp949는 em dash(`—`)·`⚠`·`⛔`·`≈`를 **인코딩하지 못해**
출력 순간 `UnicodeEncodeError`로 죽는다. 이 레포는 그 문자들을 사용자 메시지와
레코드에 상시 쓴다 — 예로 `engine/ladder_aggregate.py`는 `sample.basis`에 em
dash를 **무조건** 넣고, 그 레코드가 CLI stdout으로 나간다(실측 2026-08-13).

**OS별로 분기하지 않는다.** macOS는 이미 UTF-8이라 이 호출이 no-op이고,
분기를 두면 한쪽에서만 도는 경로가 생겨 오히려 검증이 얇아진다.

**환경변수로는 강제할 수 없다.** `PYTHONUTF8`·`PYTHONIOENCODING`은 인터프리터
기동 **전에** 정해져야 해서 프로세스 안에서 켤 수 없고, 세션 설정에 넣어도 그
설정을 읽는 호스트만 덮는다(사용자가 직접 친 명령·다른 호스트가 띄운 MCP
서버는 그대로 노출된다). 그래서 강제 지점을 **진입점 코드**에 둔다(철칙 5).
"""

from __future__ import annotations

import sys


def force_utf8_stdio() -> None:
    """`stdout`·`stderr`을 UTF-8로 고정한다 — 진입점에서 **가장 먼저** 부른다.

    멱등하다(이미 UTF-8이면 아무 일도 안 한다). 되돌릴 필요가 없으므로 실패해도
    올리지 않는다 — 재설정 불가는 **고정 이전 상태 그대로**라는 뜻이고, 여기서
    예외를 올리면 인코딩과 무관한 이유로 CLI 전체가 죽는다.
    """
    for stream in (sys.stdout, sys.stderr):
        # pytest capture 등 TextIOWrapper가 아닌 스트림엔 reconfigure가 없다.
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is None:
            continue
        try:
            reconfigure(encoding="utf-8")
        except (OSError, ValueError):  # 이미 닫혔거나 분리된 스트림
            continue
