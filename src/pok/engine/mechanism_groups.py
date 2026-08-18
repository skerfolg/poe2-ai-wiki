"""메커니즘 그룹 — 「이 빌드가 무엇을 쓰나」로 노드의 조건부 가치를 가른다.

## 왜 필요한가

노드 가치를 전 빌드로 뭉쳐 중앙값을 내면 **조건부 노드가 0으로 희석된다**. 권능 충전
노드는 권능을 안 쓰는 빌드에서 진짜 0이고 쓰는 빌드에서 크다. 실측 2026-08-18:
「쓸모없어 보이던」 92종 중 27종이 **작동할 땐 30% 넘게** 아팠다(Mind Over Matter는
작동률 1.4%에 작동시 36.6%). 축을 더 재도 이건 안 고쳐진다 — 필요한 것은 **조건**이다.

## 세 층을 가른다 (사용자 요구 2026-08-18: 「발견될 때마다 업데이트되는 구조」)

1. **정의**(이 파일) — 담체 목록을 **KB에서 파생**한다. 젬의 `tags`(게임 데이터에서
   온 52종)와 효과 문구를 본다. 새 젬이 KB에 들어오면 **자동으로 합류**한다.
2. **예외** — 태그로 안 잡히는 것만 `knowledge/ingest/mechanism-groups.json`에 적는다.
   갱신이 일어나는 **유일한 손질 지점**이다.
3. **증거**(코퍼스) — 「어느 노드를 켜나」는 반사실 관측에서 재계산한다. 여기 안 적는다.

⛔ **목록을 손으로 들지 않는다.** 실측: 손으로 든 초안의 `trigger` 그룹에 젬이 2종뿐이었는데
KB 태그로 뽑으면 **106종**이다(치명타 시 시전·소환수 사망 시 시전이 빠져 있었다).
사람이 드는 목록은 조용히 낡는다.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from pok.common.paths import knowledge_dir

OVERRIDES = "mechanism-groups.json"

# 태그에서 바로 오는 그룹 — 게임 데이터가 이미 분류해 둔 것이라 우리가 정하지 않는다
_TAG_GROUPS: dict[str, str] = {
    "trigger": "발동",
    "meta": "발동",
    "curse": "저주",
    "mark": "저주",
    "minion": "하수인",
    "companion": "동료",
    "totem": "토템",
    "remnant": "잔재",
    "shapeshift": "변신",
    "warcry": "함성",
    "herald": "전령",
    "aura": "오라",
}

# 태그에 없는 메커니즘 — **효과 문구**로 잡는다. 게임이 이름 붙인 고유명사만 쓴다
_TEXT_GROUPS: dict[str, str] = {
    r"\bPower Charge": "권능 충전",
    r"\bFrenzy Charge": "격분 충전",
    r"\bEndurance Charge": "인내 충전",
    r"\bRage\b": "격노",
    r"\bPresence\b": "발현",
    r"\bSpirit\b": "정신력",
    r"Energy Shield": "에너지 실드",
    r"\bMana\b": "마나",
}
_TEXT_PATTERNS = [(re.compile(p, re.I), name) for p, name in _TEXT_GROUPS.items()]


@dataclass(frozen=True)
class Group:
    """한 메커니즘과 그 담체들. **증거(어느 노드를 켜나)는 여기 없다** — 코퍼스 몫이다."""

    name: str
    gems: tuple[str, ...]
    source: dict[str, str]  # 젬 이름 → 어디서 왔나(태그 / 문구 / 예외)

    @property
    def curated(self) -> tuple[str, ...]:
        """예외 파일이 넣은 것 — 여기가 크면 태그가 갭이라는 뜻이다."""
        return tuple(g for g, s in self.source.items() if s == "예외")


def _gem_records(kb: Path) -> Iterable[dict[str, Any]]:
    for path in (kb / "game-data" / "gems").glob("*.ndjson"):
        for line in path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                yield json.loads(line)


def load_overrides(kb: Path | None = None) -> dict[str, list[str]]:
    """손질 지점. 없으면 빈 것 — 파일이 없다고 실패하지 않는다."""
    path = (kb or knowledge_dir()) / "ingest" / OVERRIDES
    if not path.exists():
        return {}
    doc = json.loads(path.read_text(encoding="utf-8"))
    return {str(k): [str(v) for v in vs] for k, vs in (doc.get("groups") or {}).items()}


def derive(kb: Path | None = None) -> dict[str, Group]:
    """KB에서 그룹을 파생한다 — **매번 다시 만든다**(손으로 든 목록은 낡는다)."""
    root = kb or knowledge_dir()
    members: dict[str, dict[str, str]] = {}
    for record in _gem_records(root):
        name = str(record["name"]["en"])
        data = record.get("data") or {}
        text = " ".join(
            [str(data.get("description") or ""), *(str(s) for s in data.get("stats") or [])]
        )
        for tag in record.get("tags") or []:
            group = _TAG_GROUPS.get(str(tag))
            if group:
                members.setdefault(group, {}).setdefault(name, "태그")
        for pattern, group in _TEXT_PATTERNS:
            if pattern.search(text):
                members.setdefault(group, {}).setdefault(name, "문구")

    for group, gems in load_overrides(root).items():
        for gem in gems:
            members.setdefault(group, {}).setdefault(gem, "예외")

    return {
        name: Group(name=name, gems=tuple(sorted(src)), source=src)
        for name, src in sorted(members.items())
    }


def groups_of(gem_names: Iterable[str], groups: dict[str, Group]) -> set[str]:
    """이 빌드가 든 젬들 → 어느 메커니즘을 쓰나. **조건을 고르는 자리**다."""
    want = set(gem_names)
    return {name for name, group in groups.items() if want & set(group.gems)}


def main(argv: list[str] | None = None) -> int:  # pragma: no cover - 보고용
    import argparse

    from pok.common.stdio import force_utf8_stdio

    force_utf8_stdio()
    ap = argparse.ArgumentParser(description="메커니즘 그룹 — KB에서 파생한 담체 목록")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    groups = derive()
    if args.json:
        print(
            json.dumps(
                {n: {"gems": g.gems, "curated": g.curated} for n, g in groups.items()},
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    for name, group in sorted(groups.items(), key=lambda kv: -len(kv[1].gems)):
        mark = f" (예외 {len(group.curated)})" if group.curated else ""
        print(f"{name:<12} 젬 {len(group.gems):>3}종{mark}")
        print(f"   {', '.join(group.gems[:6])}{' …' if len(group.gems) > 6 else ''}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
