"""② parse — poe2db 상세 HTML → 중간 레코드 (가공 최소, KB_INGEST §2).

파서는 소스 취약성의 격리벽: poe2db HTML이 바뀌면 이 파일만 고친다.
`From`(획득) 카드는 구현 판정 게이트(KI-8)의 신호 A라 필수 추출 대상이다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from bs4 import BeautifulSoup, Tag


@dataclass
class DetailPage:
    """poe2db 상세 페이지 1장의 파싱 결과 (us 기준; kr은 name만 씀)."""

    name: str
    description: str | None = None
    type_line: str | None = None
    tags: list[str] = field(default_factory=list)
    tier: int | None = None
    acquisition: list[str] = field(default_factory=list)  # From 카드 항목들 (신호 A)
    acquisition_count: int | None = None  # "From /N" 헤더의 N
    has_level_effect: bool = False
    # 코스트·점유 전수 (사용자 지시 2026-08-02 — 정신력 지출 장부의 원천)
    costs: list[dict[str, Any]] = field(default_factory=list)  # Cost: {resource,min,max[,pct]}
    reservation: list[dict[str, Any]] = field(default_factory=list)  # Reservation:
    additional_reservation: list[dict[str, Any]] = field(default_factory=list)  # 보조 젬
    cost_multiplier_pct: float | None = None  # 보조 젬 Cost Multiplier: 115%
    cast_time_s: float | None = None
    # 쿨다운(초) — **회전율·트리거 발동률의 기저값**이다. 안 실으면 지속 주력기와
    # 쿨기를 구분할 수 없다. 실측 2026-08-07(빌드 회차): 겨울의 눈을 시전시간
    # 1.4초로만 보고 "초당 1.07시전"을 전제해 생명력 유출·카오스 획득을 계산했는데
    # 실제로는 **10초 쿨다운**이었다. `quality_stats`엔 "Cooldown Recovery Rate"를
    # 이미 싣고 있었으니 **수정 모드는 있는데 수정 대상이 없던** 상태다.
    # None = 미수록, 0.0 = 쿨다운 없음(명시) — 둘을 구분한다.
    cooldown_s: float | None = None
    # 서술형 점유 — 라벨(`Reservation:`)이 아니라 문장으로 적히는 조건부 점유.
    # 예: "Reserves 60 Spirit per socketed Curse" (신성 모독). 페이지의 **버프 팝업**
    # 블록에 있어 메인 Stats만 보면 놓친다 (실증 2026-08-02, 백로그 B-4).
    conditional_reservation: list[dict[str, Any]] = field(default_factory=list)
    # 효과 문구 — **수치가 실려 있는 줄**. `description`(산문 요약)과 다른 것이다.
    # 파서가 오래도록 `.secDescrText`/og:description만 담아서, 젬 레코드에 "50% chance
    # to inflict Bleeding" 같은 배율이 통째로 없었다(실측 2026-08-05: Support 537건
    # 전량에 효과 수치 0건). Passive는 이미 `stats`로 담고 있었으니 규약도 이미 있었다.
    stats: list[str] = field(default_factory=list)  # .explicitMod
    implicit_stats: list[str] = field(default_factory=list)  # .implicitMod
    quality_stats: list[str] = field(default_factory=list)  # .qualityMod·.secondaryQualityMod


def _title_name(soup: BeautifulSoup) -> str:
    t = soup.title.get_text() if soup.title else ""
    return t.split(" - PoE2DB")[0].strip()


# 태그 토큰: 짧은 단어(구) — 숫자·콜론·긴 서술문 배제
_TAG_TOKEN = re.compile(r"^[A-Za-z][A-Za-z' ]{0,24}$")


def _extract_tags(stats_text: str) -> list[str]:
    """`.Stats` 선두의 태그 나열만 추출.

    페이지 유형별 종결자: 스킬 젬 = 'Tier:' / 서포트 젬 = 'Category :'.
    종결자 이전 구간을 쉼표로 나눠 **태그 형태 토큰만** 접두 스캔으로 취한다
    (첫 비태그 토큰에서 중단 — 설명문 유입 차단, 0.5.4b 763건 오염 실증 후 강화).
    """
    head = re.split(r"Tier:|Category\s*:", stats_text)[0]
    tags: list[str] = []
    for token in head.split(","):
        token = token.strip()
        if not token or not _TAG_TOKEN.match(token) or len(token.split()) > 3:
            break
        tags.append(token)
    return tags


# ── 코스트·점유 파싱 (Stats 텍스트) ──────────────────────────────────
# 값 형태: "30" | "(3 — 37)" (+선택 "%"), 자원: Mana·Life·Spirit·Energy Shield·Rage
_COST_VALUE = re.compile(
    r"\(?\s*(\d+(?:\.\d+)?)(?:\s*—\s*(\d+(?:\.\d+)?)\s*\))?\s*(%)?\s*"
    # Ward(룬 수호) 누락으로 으스스한 기둥의 코스트가 통째로 비어 있었다 —
    # 출처에는 `(15—81) Ward`가 있는데 자원 목록에 없어 못 읽었다(실측 2026-08-07).
    r"(Mana|Life|Spirit|Energy Shield|Rage|Ward)"
)
# 세그먼트 종결자: 다음 라벨/속성 시작 (Stats 텍스트는 라벨 나열이라 접두 구간만 취한다)
_SEG_END = (
    r"(?=Additional Reservation:|Reservation:|Cost Multiplier:|Cost:|Cast Time:|"
    r"Attack Time:|Critical|Projectile|Cooldown|Radius|Requires:|Support Requirements|"
    r"Tier:|Level:|$)"
)


def _cost_values(segment: str) -> list[dict[str, Any]]:
    """`(a—b) Resource` → 값. **a·b는 크기 순이 아니라 레벨 순이다.**

    출처의 두 수는 `(1레벨 값 — 최고레벨 값)`이고, 점유는 레벨이 오를수록 **줄어든다**
    — 실측 2026-08-07: 해골 방화범 `(90—39) Spirit`은 오기가 아니라 참값이다(PoB
    `spiritReservationFlat` 90→39). KB 점유 중 범위가 있는 8건이 **전부 감소형**이다.
    그래서 그 쌍을 `min`/`max`로만 적으면 이름이 거짓말을 한다 — 레벨 의미를 명시한
    `at_level_1`·`at_max_level`을 함께 싣고, `min`/`max`는 **실제 크기 순**으로 둔다.
    빌드 설계에 쓰는 값은 대개 `at_max_level`이다.
    """
    out = []
    for m in _COST_VALUE.finditer(segment):
        first = float(m.group(1))
        last = float(m.group(2)) if m.group(2) else first
        value: dict[str, Any] = {
            "resource": m.group(4),
            "min": min(first, last),
            "max": max(first, last),
            "at_level_1": first,
            "at_max_level": last,
        }
        if m.group(3):
            value["pct"] = True
        out.append(value)
    return out


def _segment(text: str, label: str) -> str:
    m = re.search(re.escape(label) + r"\s*(.*?)" + _SEG_END, text, re.S)
    return m.group(1) if m else ""


# 서술형 점유: "Reserves 60 Spirit per socketed Curse" / "Reserves 30 Spirit"
_RESERVES_SENTENCE = re.compile(
    r"Reserves\s+(\d+(?:\.\d+)?)\s*(%)?\s*(Mana|Life|Spirit|Energy Shield)"
    r"(?:\s+per\s+([A-Za-z ]{3,40}?))?(?=\s*(?:[.,]|Additional|Requires|$))",
    re.IGNORECASE,
)


def parse_conditional_reservation(text: str) -> list[dict[str, Any]]:
    """서술형 점유 문장 → [{resource, amount, per?, pct?}] (중복 제거).

    poe2db는 조건부 점유를 라벨이 아니라 문장으로 적는다 — 그리고 그 문장은
    메인 젬 팝업이 아니라 **버프 팝업** 블록에 있다. 페이지의 모든 `.Stats`를
    합쳐서 넘겨야 잡힌다.
    """
    out: list[dict[str, Any]] = []
    for m in _RESERVES_SENTENCE.finditer(text):
        entry: dict[str, Any] = {"resource": m.group(3), "amount": float(m.group(1))}
        if m.group(2):
            entry["pct"] = True
        if m.group(4):
            entry["per"] = " ".join(m.group(4).split())
        if entry not in out:
            out.append(entry)
    return out


def parse_stats_costs(stats_text: str) -> dict[str, Any]:
    """Stats 텍스트 → 코스트·점유·시전시간 (없는 항목은 빈 값).

    "Additional Reservation:"(보조 젬의 추가 점유)이 "Reservation:"을 포함하므로
    일반 점유는 'Additional ' 접두가 없는 위치만 매칭한다.
    """
    plain_reservation = ""
    m = re.search(r"(?<!Additional )Reservation:\s*(.*?)" + _SEG_END, stats_text, re.S)
    if m:
        plain_reservation = m.group(1)
    mult = re.search(r"Cost Multiplier:\s*(\d+(?:\.\d+)?)\s*%", stats_text)
    cast = re.search(r"Cast Time:\s*(\d+(?:\.\d+)?)\s*sec", stats_text)
    # poe2db 표기는 "Cooldown Time: 10.00 s" (Cast Time의 `sec`과 단위 표기가 다르다)
    cooldown = re.search(r"Cooldown Time:\s*(\d+(?:\.\d+)?)\s*s\b", stats_text)
    return {
        "costs": _cost_values(_segment(stats_text, "Cost:")),
        "reservation": _cost_values(plain_reservation),
        "additional_reservation": _cost_values(_segment(stats_text, "Additional Reservation:")),
        "cost_multiplier_pct": float(mult.group(1)) if mult else None,
        "cast_time_s": float(cast.group(1)) if cast else None,
        "cooldown_s": float(cooldown.group(1)) if cooldown else None,
    }


_INTERNAL_ID = re.compile(r"[a-z0-9%]+(?:_[a-z0-9%]+)+")
_MOD_SELECTORS = (
    ("stats", ".explicitMod"),
    ("implicit_stats", ".implicitMod"),
    ("quality_stats", ".qualityMod, .secondaryQualityMod"),
)


def _mod_lines(node: Tag) -> list[str]:
    """모드 div 하나 → 문구 줄들.

    구분자는 `<br>`다. `get_text("\n")`을 그냥 쓰면 인라인 태그(`<a>`·`<span
    class=mod-value>`)마다 줄이 갈려 `"Supported Skills have / 80 / % more…"`처럼
    조각난다 — 실측 2026-08-05. 그래서 `<br>`만 개행으로 바꾸고 나머지는 공백으로 잇는다.
    """
    clone = BeautifulSoup(str(node), "html.parser")
    for br in clone.find_all("br"):
        br.replace_with("\n")
    out: list[str] = []
    for chunk in clone.get_text(" ").split("\n"):
        line = " ".join(chunk.split())
        # 수치가 <span>으로 분리돼 "50 %"·"Bleeding , up to" 처럼 벌어진다 — 표기만 정리
        line = re.sub(r"\s+([%,.])", r"\1", line)
        # 내부 식별자(`receive_bleeding_chance_%_when_hit`)는 문구가 아니다
        if line and not _INTERNAL_ID.fullmatch(line):
            out.append(line)
    return out


def _collect_mods(soup: BeautifulSoup, page: DetailPage) -> None:
    """효과 문구를 전 `.Stats` 블록에서 모은다 (중복 제거).

    블록이 여러 벌 실리는 페이지가 있어(같은 내용 반복) 순서를 지키며 dedup한다.
    """
    for attr, selector in _MOD_SELECTORS:
        seen: list[str] = []
        for block in soup.select(".Stats"):
            for node in block.select(selector):
                for line in _mod_lines(node):
                    if line not in seen:
                        seen.append(line)
        if seen:
            setattr(page, attr, seen)


def parse_detail(html: str) -> DetailPage:
    soup = BeautifulSoup(html, "html.parser")
    page = DetailPage(name=_title_name(soup))

    og = soup.find("meta", property="og:description")
    if isinstance(og, Tag) and og.get("content"):
        page.description = str(og["content"]).strip()

    tl = soup.select_one(".typeLine")
    if tl is not None:
        page.type_line = tl.get_text(strip=True)

    _collect_mods(soup, page)

    stats = soup.select_one(".Stats")
    if stats is not None:
        text = stats.get_text(" ", strip=True)
        m = re.search(r"Tier:\s*(\d+)", text)
        if m:
            page.tier = int(m.group(1))
        page.tags = _extract_tags(text)
        for key, value in parse_stats_costs(text).items():
            setattr(page, key, value)
    # 조건부(서술형) 점유는 버프 팝업 블록에 있다 — 전 `.Stats`를 합쳐서 스캔
    all_stats = " ".join(b.get_text(" ", strip=True) for b in soup.select(".Stats"))
    page.conditional_reservation = parse_conditional_reservation(all_stats)

    for card in soup.select("div.card"):
        header = card.select_one(".card-header")
        if header is None:
            continue
        htext = header.get_text(strip=True)
        if htext.startswith("From"):
            m = re.search(r"From\s*/\s*(\d+)", htext)
            page.acquisition_count = int(m.group(1)) if m else 0
            page.acquisition = [
                a.get_text(strip=True) for a in card.find_all("a") if a.get_text(strip=True)
            ]
        elif htext.startswith("Level Effect"):
            page.has_level_effect = True
    return page


def parse_name_only(html: str) -> str:
    """kr 페이지에서 한국어 이름만 추출."""
    return _title_name(BeautifulSoup(html, "html.parser"))


def pob_gems_by_name(gems: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """PoB gems.json → 소문자 이름 → 젬 데이터 (신호 P 조회용)."""
    out: dict[str, dict[str, Any]] = {}
    for meta_id, gem in gems.items():
        name = str(gem.get("name", "")).strip()
        if name:
            out.setdefault(name.lower(), {**gem, "_meta_id": meta_id})
    return out
