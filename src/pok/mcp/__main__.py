"""python -m pok.mcp — stdio MCP 서버 실행 (P2)."""

from pok.common.stdio import force_utf8_stdio
from pok.mcp.server import main

force_utf8_stdio()  # main()도 부르지만 멱등하다 — 진입점마다 거는 규칙을 지킨다
main()
