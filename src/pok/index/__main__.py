"""명시적 인덱스 CLI — self-healing의 보조 (CI·수동 재빌드용).

사용: python -m pok.index build | rebuild | search <질의>
"""

from __future__ import annotations

import argparse
import sys

from pok.common.paths import index_db_path
from pok.common.stdio import force_utf8_stdio
from pok.index.build import build_index
from pok.index.search import ensure_index, search


def main(argv: list[str] | None = None) -> int:
    force_utf8_stdio()
    ap = argparse.ArgumentParser(prog="pok.index")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build", help="self-healing 판정 후 필요 시 빌드")
    sub.add_parser("rebuild", help="무조건 재빌드")
    sp = sub.add_parser("search", help="빠른 검색 (압축 히트)")
    sp.add_argument("query")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        print(f"index: {ensure_index()}")
    elif args.cmd == "rebuild":
        index_db_path().unlink(missing_ok=True)
        print(f"index: {build_index()}")
    elif args.cmd == "search":
        for h in search(args.query):
            tags = ", ".join(h.tags)
            print(f"{h.id}\t{h.type}\t{h.name_ko} / {h.name_en}\t[{tags}]\t{h.verification}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
