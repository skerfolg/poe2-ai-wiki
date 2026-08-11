"""문서의 **기각 결정**과 스펙을 대조한다 — 백로그 #58 ② (2026-08-11).

세션을 건너오는 것은 스펙 파일이고 결정은 `design.md`에 쌓이는데, 스펙은 언제나
「적법」하므로 이어받은 세션은 그 위에 얹는다. 그래서 **기각된 것이 계승된다.**

실측(이관 5차): 선행 문서 §11.3-b가 복점관(`item.the-auspex`)을 「민첩 230 부족,
기각」으로 판정했는데 `spec_geared5.json`에 **그대로 남아** 그 위에서 장비 5슬롯
실측 전체가 나왔다. 매 호출 `items_legal: True`였다 — 적법성은 「기각했었나」를
모른다. 보고자는 이번 회차에 그것을 "새로 발견"한 줄 알고 이관했다.

## 무엇을 기각으로 읽는가 — **모호하지 않은 것만**

문서 규약은 있다(BUILD_DESIGN §388 「폐기는 삭제가 아니라 기록」 — `#### 폐기: 이름`).
그런데 실제 문서는 표·산문으로도 적는다. 넓게 읽으면 "채택/기각 판정"(할 일 문장)
같은 것까지 잡혀 **거짓 경고**가 나고, 거짓 경고는 참 경고의 신호를 죽인다(§0 ⑤).
그래서 이름이 확정적으로 읽히는 두 자리만 본다:

1. `#### 폐기: <이름>` · `### 폐기 유지: <이름>` — 제목
2. 표의 행 — 어느 칸이 정확히 `기각`이거나 `기각 (…)`로 시작할 때 **첫 칸**이 이름

⛔ 산문은 안 읽는다. "…는 소스 판독으로 기각됐다" 같은 문장에서 대상을 확정적으로
집어낼 방법이 없다 — 지어내느니 놓치는 편이 낫다(놓친 것은 사람이 채울 수 있지만
거짓 경고는 도구 전체의 신뢰를 깎는다).
"""

from __future__ import annotations

import re
from typing import Any

# `#### 폐기: 이름` · `### 폐기 유지: 이름`
_DISCARD_HEADING = re.compile(
    "^#{2,6}\\s*폐기(?:\\s*유지)?\\s*[:\uff1a]\\s*(.+?)\\s*$", re.M
)  # 전각 콜론도 받는다
# 표 칸이 정확히 `기각`이거나 `기각 (사유…)`로 시작
_REJECT_CELL = re.compile("^기각(?:\\s*[(\uff08].*)?$")  # 전각 괄호도 받는다


def _table_rejections(text: str) -> list[str]:
    """표 행에서 기각된 이름 — 어느 칸이 `기각`이면 **첫 칸**이 대상이다."""
    out: list[str] = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped.startswith("|"):
            continue
        cells = [c.strip() for c in stripped.strip("|").split("|")]
        if len(cells) < 2 or not any(_REJECT_CELL.match(c) for c in cells[1:]):
            continue
        name = _strip_markup(cells[0])
        if name and not set(name) <= {"-", ":", " "}:  # 구분줄 제외
            out.append(name)
    return out


def _strip_markup(text: str) -> str:
    """`**이름**`·`` `이름` ``·`[이름](링크)` → 이름."""
    text = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", text)
    return text.replace("**", "").replace("`", "").strip()


def rejected_names(design_text: str) -> tuple[str, ...]:
    """문서가 **기각으로 기록한** 이름들 (중복 제거, 등장 순)."""
    found = [_strip_markup(m.group(1)) for m in _DISCARD_HEADING.finditer(design_text)]
    found.extend(_table_rejections(design_text))
    return tuple(dict.fromkeys(n for n in found if n))


def _spec_item_names(spec: dict[str, Any]) -> list[tuple[str, str]]:
    """스펙에 실린 아이템 → (슬롯, 이름). PoB 텍스트는 2번째 줄이 이름이다."""
    out: list[tuple[str, str]] = []
    for item in spec.get("items") or []:
        lines = [ln.strip() for ln in str(item.get("text", "")).splitlines() if ln.strip()]
        if len(lines) >= 2:
            out.append((str(item.get("slot", "?")), lines[1]))
        # 베이스명도 본다 — 유니크가 아니면 이름 줄이 임의 문자열이다
        if len(lines) >= 3:
            out.append((str(item.get("slot", "?")), lines[2]))
    return out


def rejected_but_present(spec: dict[str, Any], design_text: str) -> list[dict[str, str]]:
    """문서가 기각했는데 **스펙에 아직 있는** 것 — 결정과 스펙이 갈라진 자리.

    이름 대조는 정확 일치(대소문자·공백만 정규화)다. 부분 일치로 넓히면
    「검은 화염」이 「검은 화염의 서약」을 잡는 식으로 거짓 경고가 난다.
    """
    rejected = {n.casefold(): n for n in rejected_names(design_text)}
    if not rejected:
        return []
    out: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    for slot, name in _spec_item_names(spec):
        key = name.casefold()
        if key in rejected and (slot, key) not in seen:
            seen.add((slot, key))
            out.append(
                {
                    "slot": slot,
                    "name": name,
                    "why": (
                        f"설계 문서가 {rejected[key]!r}를 **기각으로 기록**했는데 스펙에 아직 있다 "
                        f"— 적법성은 「기각했었나」를 모른다. 되살린 것이면 문서에 사유를 "
                        f"적고, 아니면 스펙에서 뺄 것"
                    ),
                }
            )
    return out


def find_design_doc(slug: str, *, root: Any = None) -> str | None:
    """이 조립 슬러그에 대응하는 `design.md` 본문 — 없으면 `None`.

    **인자를 새로 만들지 않는다.** 호출자가 넘겨야 하는 인자는 안 넘기면 그만이고,
    그러면 규율에 강제 지점이 없는 것과 같다(철칙 5). 조립 슬러그와 설계 폴더 이름이
    같은 규칙(`YYYYMMDD-<slug>`)을 쓰므로 **자동으로 찾는다**.

    조립은 매번 새 `build_id`를 만들지만(`-2`·`-3`), 설계 문서는 세션이 유지하는
    폴더에 있다 — 그래서 접미 숫자를 떼고 슬러그로 맞춘다. 여러 개면 가장 최근.
    """
    from pok.artifacts.store import slugify
    from pok.common.paths import artifacts_dir

    # `slugify`는 소문자로 낮추는데 **기존 폴더는 원래 대소문자**로 있다
    # (`…-인퍼널리스트-A-집정관-…`) — 맞춰 보려면 양쪽을 다 낮춰야 한다.
    target = slugify(slug).casefold()
    builds = artifacts_dir(root) / "builds"
    if not builds.is_dir():
        return None
    hits = [
        d
        for d in builds.iterdir()
        if d.is_dir()
        and (d / "design.md").exists()
        and re.sub(r"-\d+$", "", d.name).casefold().endswith(f"-{target}")
    ]
    if not hits:
        return None
    newest = max(hits, key=lambda d: d.name)
    return (newest / "design.md").read_text(encoding="utf-8", errors="replace")


def rejection_record_gap(design_text: str) -> str | None:
    """기각을 **말은 하는데 규약 형식으로 안 적은** 문서 — 그러면 아무도 못 읽는다.

    실측 2026-08-11: `artifacts/builds` 문서 14개 중 규약대로 적은 것은 **4개**이고
    9개는 산문에만 있다. 복점관 기각이 계승된 것도 그 9개 중 하나에서였다 —
    「기각했다」가 문서에 있어도 **기계가 읽을 수 없으면 없는 것과 같다**.

    규약: `#### 폐기: <이름>` (BUILD_DESIGN §388) 또는 표의 `기각` 칸.
    """
    mentions = len(re.findall(r"기각|폐기", design_text))
    if not mentions or rejected_names(design_text):
        return None
    return (
        f"「기각」·「폐기」를 {mentions}회 말하는데 **규약 형식 기록이 0건**이다 — "
        f"산문은 기계가 읽지 못해 다음 세션이 기각된 것을 그대로 계승한다"
        f"(실측: 그렇게 복점관이 5슬롯 실측 전체에 남았다). "
        f"`#### 폐기: <이름>` 제목이나 표의 `기각` 칸으로 적을 것 (BUILD_DESIGN §388)"
    )
