"""#150 — `server_info`가 서버 런타임 안에서 영구 정지하던 자리.

`asyncio.run(mcp.list_tools())`를 워커 스레드에서 돌리면 **새 루프**가 서버 루프에 묶인
코루틴을 기다린다 — 스탠드얼론에선 0.0초, 서버 안에선 영원히 안 돌아온다. 폴백의
`ThreadPoolExecutor` `with` 블록은 `shutdown(wait=True)`라 `timeout=10`이 아무것도 못 풀었다.

기존 시험은 `server.server_info()`를 **직접** 불러 행복 경로만 밟았다. 여기서는 인메모리
FastMCP 클라이언트로 **서버 래퍼를 실제로 지나** 부른다 — 강제 지점이 실제 실행 경로를
안 밟으면 강제가 아니다(§0). 실측: 수정 전엔 15초 상한에서 TimeoutError, 수정 후 0.4초.
"""

from __future__ import annotations

import asyncio
import json
import time
from typing import Any

from pok.mcp.server import mcp


def _via_client(timeout_s: float) -> tuple[dict[str, Any], float]:
    """`server_info`를 인메모리 클라이언트(= 서버 런타임)로 부른다 — (결과, 소요 초)."""
    from fastmcp import Client

    async def main() -> tuple[Any, float]:
        async with Client(mcp) as client:
            started = time.perf_counter()
            result = await asyncio.wait_for(client.call_tool("server_info", {}), timeout=timeout_s)
            return result, time.perf_counter() - started

    result, elapsed = asyncio.run(main())
    data = result.data if isinstance(result.data, dict) else json.loads(result.content[0].text)
    return dict(data), elapsed


def test_서버_런타임_안에서도_server_info가_돌아온다() -> None:
    """#150 — 서버 안에서 부르면 응답도 진행도 없이 멈추던 자리. 이제 상한 안에 돌아온다.

    KB 콜드 로드(30~60초, 이 도구의 `kb_skipped_copies`가 부른다)는 결함과 무관한 비용이라
    먼저 데워 두고, 서버 경로만 잰다.
    """
    from pok.kb.store import load as store_load

    store_load()
    info, elapsed = _via_client(timeout_s=60)
    assert elapsed < 30, f"서버 경로가 {elapsed:.1f}초 — 교착이 돌아왔는지 볼 것"
    assert info["tool_count"] > 20, info
    assert isinstance(info["tools"], dict)
    assert "axes" in info["tools"]["check_constraints"], "지문이 비면 D-2가 재발한다"


def test_지문_등록부는_FastMCP_스키마와_같다() -> None:
    """등록부(동기)와 FastMCP가 실제로 내는 inputSchema가 **어긋나면 안 된다**.

    `server_info`가 루프에 의존하지 않으려고 자기 등록부를 쓰는데, 그것이 FastMCP의
    스키마와 조용히 갈리면 「이 프로세스가 실제로 받는 인자」라는 약속이 깨진다.
    스탠드얼론(루프 없음)에선 `list_tools()`가 정상이므로 여기서 대조한다.
    """
    from pok.mcp import server

    expected = {
        t.name: sorted((getattr(t, "parameters", None) or {}).get("properties", {}))
        for t in asyncio.run(mcp.list_tools())
    }
    assert server.server_info()["tools"] == expected
    # 주입 인자(FastMCP Context)는 클라이언트가 주는 것이 아니다 — 지문에서 빠져야 한다
    assert "ctx" not in expected["assemble_pob"]
