"""메타 젬 에너지 규칙 수록 — 백로그 B-9 나머지 절반 (B-10 계산기의 입력).

빌드 테스트 2회차에서 세션이 트리거 빌드의 발동률을 **손계산**했다. PoB
`CalcTriggers.lua`에 메타 젬 에너지 모델이 아예 없어서 오라클이 못 재기 때문인데,
그 손계산의 입력이 KB에도 없었다.

수집해 보니 진짜 갭은 Monster Power가 아니라 **젬 `description`이 요약본**이라는
것이었다. KB에는 `"Gains Energy when you Freeze, Shock, or Ignite"`만 있고
계수 10·1·1이 빠져 있었다 — 원시 스냅샷에는 처음부터 다 있었다.

## 구조화 범위 (사용자 결정 2026-08-05, A안)

에너지 문구는 **전량 원문으로** 담고, 그중 `N Energy per Power` 형태만 구조화한다.
형태가 6종이라(고정·이동거리·소환수 Power·자원 등) 전부 스키마로 만들면 7번째가
나왔을 때 **조용히 누락**된다 — 이 프로젝트가 반복해서 다친 실패다(룬 소켓 0%가
"통과"로 기록되고, 빈 검색이 "KB에 없다"로 읽힌 것과 같은 형태).

그래서 **커버리지를 리포트로 낸다**: 에너지 문구가 있는데 구조화하지 못한 젬이
몇 건인지. 지금은 9/20이고, 패치로 형태가 바뀌면 그 수가 움직여 신호가 된다.
(currency ingest의 "⑦ 정보량 하한"과 같은 원리 — 자동 제외하지 않고 드러낸다.)

수록 필드 (data):
  energy_per_power        {"Freeze": 10.0, "Ignite": 1.0}  Power당 에너지 (구조화분)
  max_energy_per_100ms    10.0    소켓 스킬 기본 시전시간 0.1초당 최대 에너지
  max_energy_flat         500.0   최대 에너지가 고정인 젬 (Feral Invocation 등)
  energy_stats            [원문…]  에너지 관련 stat 문구 전량 (구조화 실패분 포함)
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from bs4 import BeautifulSoup

from pok.common.paths import knowledge_dir
from pok.kb.store import load as store_load
from pok.kb.store import patch_records

# "Gains 10 Energy per Power of enemies you Freeze with Hits from Skills"
_PER_POWER = re.compile(
    r"Gains?\s+([\d.]+)\s+Energy\s+per\s+Power\s+of\s+enemies\s+you\s+(\w+)", re.I
)
# "Has 10 maximum Energy per 0.1 seconds of base cast time"
_MAX_PER_TIME = re.compile(
    r"Has\s+([\d.]+)\s+maximum\s+Energy\s+per\s+([\d.]+)\s+seconds?\s+of\s+base\s+cast\s+time", re.I
)
# "Maximum Energy is 500"
_MAX_FLAT = re.compile(r"Maximum\s+Energy\s+is\s+([\d.]+)", re.I)
# 문장 경계는 **블록 개행**이다. 마침표로 자르면 `0.1 seconds`의 소수점에서 끊겨
# "Has 10 maximum Energy per 0"이 되고, 줄 단위로 자르면 수치가 별도 태그라
# "Has 10 maximum Energy per"에서 조각난다 — 둘 다 실측 2026-08-05.
_ENERGY_SENTENCE = re.compile(r"(?:Gains?|Has|Maximum)\b[^\n]{0,150}?Energy[^\n]{0,70}", re.I)
# 요약문(수치 없음)과 소켓 안내 문구는 stat이 아니다
_NOT_A_STAT = re.compile(r"Place into a Skill|generic ongoing trigger|ActiveSkills", re.I)
_TAG_MARKER = "GeneratesEnergy"


def _stat_text(raw_html: str) -> str:
    """`.Stats` 블록들을 개행으로 이어붙인 문자열.

    **평문 전체를 훑지 않는다**: og:description 요약이 먼저 잡혀
    `"gains Energy when you Block"`(수치 없음)이 들어오고 실제 문구
    `"Gains 25 Energy when you Block"`은 뒤로 밀린다(실측 2026-08-05).
    블록 안은 공백으로 잇는다 — 수치가 별도 태그라 줄로 자르면 조각난다.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    blocks = [" ".join(b.get_text(" ", strip=True).split()) for b in soup.select(".Stats")]
    return "\n".join(blocks)


def parse_energy(raw_html: str) -> dict[str, Any]:
    """상세 페이지 원문 → 에너지 규칙. 판단하지 않고 문구에 있는 것만 낸다."""
    if _TAG_MARKER not in raw_html:
        return {}
    text = _stat_text(raw_html)
    out: dict[str, Any] = {}

    per_power = {verb.capitalize(): float(n) for n, verb in _PER_POWER.findall(text)}
    if per_power:
        out["energy_per_power"] = dict(sorted(per_power.items()))

    if (m := _MAX_PER_TIME.search(text)) is not None:
        amount, seconds = float(m.group(1)), float(m.group(2))
        # 0.1초 단위로 정규화 — 표기가 바뀌어도 계산기 쪽 단위가 흔들리지 않게
        out["max_energy_per_100ms"] = round(amount * 0.1 / seconds, 4) if seconds else amount
    if (m := _MAX_FLAT.search(text)) is not None:
        out["max_energy_flat"] = float(m.group(1))

    # 문구는 **전량** 담는다 — 구조화하지 못한 형태도 정보를 잃지 않게.
    # 단 수치 없는 줄은 요약이라 정보가 아니다("gains Energy when you Block").
    stats: list[str] = []
    for match in _ENERGY_SENTENCE.finditer(text):
        line = " ".join(match.group().split())
        if not re.search(r"\d", line) or _NOT_A_STAT.search(line) or line in stats:
            continue
        stats.append(line)
    if stats:
        out["energy_stats"] = stats[:12]
    return out


def _slug_of(record: dict[str, Any]) -> str | None:
    for src in record.get("sources", []):
        ref = str(src.get("ref", ""))
        if src.get("src") == "poe2db" and "/us/" in ref:
            return ref.rsplit("/us/", 1)[1]
    return None


def apply_meta_energy(
    raw_dir: Path,
    knowledge: Path | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """수집된 상세 페이지에서 에너지 규칙을 뽑아 젬 레코드에 붙인다 (오프라인)."""
    pages = raw_dir / "poe2db" / "us"
    store = store_load((knowledge or knowledge_dir()).parent)
    updates: dict[str, dict[str, Any]] = {}
    structured: list[str] = []
    unstructured: list[dict[str, Any]] = []

    for record in store.records.values():
        slug = _slug_of(record.raw)
        if slug is None:
            continue
        page = pages / f"{slug}.html"
        if not page.exists():
            continue
        raw_html = page.read_text(encoding="utf-8", errors="replace")
        if _TAG_MARKER not in raw_html:
            continue
        # 분모는 **태그 보유 젬**으로 고정한다 — 파싱이 실패해 분모까지 줄면
        # 커버리지가 좋아 보이는 착시가 난다(0/0 = 100%가 되는 종류의 거짓말)
        parsed = parse_energy(raw_html)
        if parsed:
            updates[record.id] = parsed
        if parsed.get("energy_per_power"):
            structured.append(record.id)
        else:
            # 에너지는 쓰는데 Power형이 아니다 — 계산기가 다루지 못하는 형태다.
            # **자동 제외하지 않고 드러낸다**: 이 수가 움직이면 형태가 바뀐 신호다.
            unstructured.append({"id": record.id, "stats": parsed.get("energy_stats", [])[:2]})

    if write and updates:
        patch_records(updates, root=(knowledge or knowledge_dir()).parent)

    total = len(structured) + len(unstructured)
    return {
        "total_energy_gems": total,
        "structured": len(structured),
        "coverage_pct": round(len(structured) / total * 100.0, 1) if total else 0.0,
        "structured_ids": sorted(structured),
        # 커버리지 미달분 — 리포트에만 남기고 배제하지 않는다(문구는 이미 수록됨)
        "unstructured": sorted(unstructured, key=lambda u: str(u["id"])),
    }
