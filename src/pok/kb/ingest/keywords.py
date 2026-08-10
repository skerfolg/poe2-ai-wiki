"""키워드(메커니즘) 정의 수집 — 상태 이상 계층의 빈 칸 (이관 건 2026-08-05).

빌드 세션이 "절개 1중첩당 출혈 확률 10%, 최대 10, 출혈 유발 시 초기화"를 KB에서
찾지 못했다. 젬 페이지는 *"1 Incision을 부여한다"*까지만 말하고, 그 규칙은
**Incision이라는 메커니즘 자체의 정의**다. 우리는 젬·아이템 페이지만 긁고 그 층을
수집 대상에 넣지 않았다 — `type=Mechanic`이 5건뿐이었던 이유다.

정의는 이미 우리가 받은 원시 HTML 안에 **링크로** 있었다:

    <a class="KeywordPopups" href="Bleeding"
       data-hover="https://cdn.poe2db.tw/cache2/us/Poe_Data_KeywordPopups_hover/<sha256>">

`data-hover`가 정의 조각의 주소다. 전 원시 페이지에서 **고유 키워드 493개**가 나온다.

## 핫링크 방지

CDN은 `Referer` 없이는 403을 준다. poe2db 페이지에서 온 요청임을 밝히면 200이다 —
브라우저가 팝업을 띄울 때와 같은 조건이라 우회가 아니라 정상 사용이다.

## 수집 규율

기존 fetch와 같은 rate(`DEFAULT_RATE_SECONDS`)를 지킨다. 원시 응답은
`artifacts/ingest-raw/<patch>/poe2db/keywords/<슬러그>.html`에 그대로 남겨,
파싱을 고칠 때 재수집이 필요 없게 한다(KI 원시 스냅샷 원칙).
"""

from __future__ import annotations

import html as html_mod
import re
import time
from pathlib import Path
from typing import Any

import httpx
from bs4 import BeautifulSoup, SoupStrainer

from pok.common.paths import knowledge_dir
from pok.kb.ingest.sources import DEFAULT_RATE_SECONDS, POE2DB_BASE, USER_AGENT
from pok.kb.store import write_record

_HOVER_ATTR = "data-hover"
_SLUG_SAFE = re.compile(r"[^A-Za-z0-9_.-]")
# 정의가 아니라 카탈로그 안내인 것들 — 수록해도 판단에 쓸 수 없다
_NOT_A_MECHANIC = re.compile(r"^(Support_Gem_|Item_Class|.*_Categories$)")
# poe2db 슬러그와 기존 레코드 id가 어긋나는 것 — 새 레코드를 만들지 않고 합친다
_ALIAS = {"Bleeding": "mechanic.bleed"}


_ANCHOR_ONLY = SoupStrainer("a")


def collect_links(raw_dir: Path) -> dict[str, str]:
    """원시 스냅샷 전량 → {키워드 슬러그: hover URL} (네트워크 없음).

    ⚠ **먼저 만난 것을 취하면 안 된다.** 같은 키워드라도 페이지마다 `data-hover`가
    다르게 붙는다: 스킬 페이지는 CDN 팝업 조각(`https://…`)을 주는데 아이템 분류
    페이지(`Amulets`·`Charms`·`Bows`…)는 **검색 쿼리**(`?s=Data\\KeywordPopups/…`)를
    준다. 후자는 정의 조각이 아니라서 `fetch_definitions`가 건너뛴다.

    선입선출이면 **어느 키워드가 수집되는지를 파일명 알파벳 순서가 정한다** —
    `Amulets.html`이 먼저 와서 열화된 링크를 선점한다. 실측 2026-08-08: 슬러그 493개
    중 **90개**가 그렇게 버려졌고, 그중 하나가 `Archon_Buff`였다(집정관 버프 지속
    10초·회복 20초가 거기 있다 — 백로그 #3이 "출처 갭"으로 오분류된 이유).
    그래서 http 후보를 **우선**한다.
    """
    pages = raw_dir / "poe2db" / "us"
    out: dict[str, str] = {}
    for path in sorted(pages.glob("*.html")):
        # ⚡ 트리를 **`<a>`만** 만든다(`SoupStrainer`). 문서 전량 파싱은 페이지당 29ms라
        # 1,079장이면 31초이고, 그게 이 함수를 쓰는 테스트의 55초짜리 병목이었다.
        # 파싱 자체는 파서가 온전히 하므로 결과가 같다 — 전량 대조로 확인했다.
        #
        # ⚠ 정규식으로 `<a …>`를 떼어내는 방법을 먼저 시도했다가 **틀렸다**:
        # `data-hover` 값 안에 `>`가 있어 `[^>]*`가 태그를 자른다. 파싱은 파서에게.
        soup = BeautifulSoup(
            path.read_text(encoding="utf-8", errors="replace"),
            "html.parser",
            parse_only=_ANCHOR_ONLY,
        )
        for anchor in soup.select(f"a.KeywordPopups[{_HOVER_ATTR}]"):
            slug = str(anchor.get("href") or "").strip()
            hover = str(anchor.get(_HOVER_ATTR) or "").strip()
            if not slug or not hover or _NOT_A_MECHANIC.match(slug):
                continue
            if slug not in out or (_usable(hover) and not _usable(out[slug])):
                out[slug] = hover
    return out


def _usable(url: str) -> bool:
    """받아올 수 있는 팝업 조각 주소인가.

    두 가지가 걸러진다:
    - `?s=Data\\KeywordPopups/…` — 팝업이 아니라 **검색 페이지**(홈페이지가 온다)
    - 숫자가 `#`로 치환된 것 — 일부 스냅샷 페이지가 `cdn.poe#db.tw`처럼 훼손된 채로
      온다. http로 시작해 정상처럼 보이지만 호스트가 해석되지 않아 **DNS 오류로
      죽는다**. 훼손본을 골라 버리면 원인이 "수집 실패"로 잘못 보인다 —
      실측 2026-08-08: 3건(`Freeze_Threshold`·`Maximum_Resistances`·`Recoup`)이
      그렇게 3회 재시도를 낭비했다. 이 셋은 어느 페이지에도 성한 http가 없다.
    """
    return url.startswith("http") and "#" not in url


def fetch_definitions(
    raw_dir: Path,
    *,
    rate_seconds: float = DEFAULT_RATE_SECONDS,
    limit: int | None = None,
    refresh: bool = False,
) -> dict[str, Any]:
    """hover 조각을 받아 원시로 저장한다. 이미 받은 것은 건너뛴다(멱등)."""
    links = collect_links(raw_dir)
    out_dir = raw_dir / "poe2db" / "keywords"
    out_dir.mkdir(parents=True, exist_ok=True)

    fetched, skipped, failed = 0, 0, []
    no_popup: list[str] = []  # 팝업 조각이 없는 키워드 — 조용히 빠지지 않게 센다
    with httpx.Client(
        headers={"User-Agent": USER_AGENT, "Referer": f"{POE2DB_BASE}/us/"},
        timeout=20,
        follow_redirects=True,
    ) as client:
        for i, (slug, url) in enumerate(sorted(links.items())):
            if limit is not None and fetched >= limit:
                break
            path = out_dir / f"{_SLUG_SAFE.sub('_', slug)}.html"
            if path.exists() and not refresh:
                skipped += 1
                continue
            if not url.startswith("http"):
                # `?s=Data\\KeywordPopups/…` 형태는 팝업 조각이 아니라 **검색 쿼리**다.
                # 받으면 홈페이지가 와서 엉뚱한 정의가 수록된다 — 실측 2026-08-05.
                no_popup.append(slug)
                continue
            try:
                response = client.get(url)
                response.raise_for_status()
            except Exception as exc:
                failed.append({"slug": slug, "error": f"{type(exc).__name__}: {exc}"})
                continue
            path.write_text(response.text, encoding="utf-8")
            fetched += 1
            if rate_seconds > 0 and i + 1 < len(links):
                time.sleep(rate_seconds)
    return {
        "linked": len(links),
        "fetched": fetched,
        "skipped_existing": skipped,
        "no_popup_fragment": sorted(no_popup),
        "failed": failed,
        "out_dir": str(out_dir),
    }


def parse_definition(raw_html: str) -> dict[str, Any]:
    """hover 조각 → {name, lines}. 판단하지 않고 문장만 정리한다.

    구조는 `.card-header`(제목) + `.keyword-body`(정의)다. 통짜 텍스트를 줄로
    자르면 제목과 정의 첫 문장이 한 줄로 붙는다 — 실측 2026-08-05.
    """
    soup = BeautifulSoup(raw_html, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    header = soup.select_one(".card-header")
    body = soup.select_one(".keyword-body") or soup
    name = " ".join(header.get_text(" ", strip=True).split()) if header else ""

    lines: list[str] = []
    for chunk in html_mod.unescape(body.get_text(" ")).split("\n"):
        line = " ".join(chunk.split())
        line = re.sub(r"\s+([%,.])", r"\1", line)
        if line and line != name and line not in lines:
            lines.append(line)
    if not name and lines:
        name = lines.pop(0)
    if not name or not lines:
        return {}
    return {"name": name, "lines": lines}


def _record_id(slug: str) -> str:
    return _ALIAS.get(slug) or ("mechanic." + _SLUG_SAFE.sub("-", slug).replace("_", "-").lower())


def _record(slug: str, parsed: dict[str, Any], patch: str) -> dict[str, Any]:
    rid = _record_id(slug)
    return {
        "id": rid,
        "type": "Mechanic",
        "name": {"ko": parsed["name"], "en": parsed["name"]},
        "tags": ["mechanic", "keyword"],
        "data": {"kind": "keyword", "stats": parsed["lines"]},
        "verification": "GAME_DATA",
        "sources": [
            {"src": "poe2db", "ref": f"{POE2DB_BASE}/us/{slug}", "patch": patch},
        ],
    }


def ingest_keywords(
    raw_dir: Path,
    patch: str = "0.5.4b",
    root: Path | None = None,
    *,
    write: bool = True,
) -> dict[str, Any]:
    """받아 둔 hover 조각 → `Mechanic` 레코드 (오프라인).

    이미 다른 경로로 수록된 메커니즘(상태이상 9종·점유·트리거 등)은 **덮지 않고 합친다** —
    PoB 쪽은 `scales_from`·상수 같은 구조화 값이고 poe2db 쪽은 규칙 문장이라 서로를
    대신하지 못한다. 버리면 "출혈은 이동 중 100% 추가 피해" 같은 문장이 사라진다.
    """
    from pok.kb.store import load as store_load
    from pok.kb.store import patch_records

    pages = raw_dir / "poe2db" / "keywords"
    if not pages.exists():
        return {"written": [], "count": 0, "note": "hover 조각 없음 — fetch 먼저"}

    existing = set(store_load(root).records)
    out_dir = knowledge_dir(root) / "game-data" / "mechanics" / "keywords"
    written: list[str] = []
    merged: dict[str, dict[str, Any]] = {}
    empty: list[str] = []

    for path in sorted(pages.glob("*.html")):
        parsed = parse_definition(path.read_text(encoding="utf-8", errors="replace"))
        if not parsed:
            empty.append(path.stem)
            continue
        record = _record(path.stem, parsed, patch)
        if record["id"] in existing:
            # 문장 정의를 기존 구조화 레코드에 얹는다 (덮어쓰기 아님)
            merged[record["id"]] = {"keyword_stats": parsed["lines"]}
            continue
        written.append(record["id"])
        if write:
            out_dir.mkdir(parents=True, exist_ok=True)
            write_record(out_dir / f"{path.stem}.json", record, root=root)
    if write and merged:
        patch_records(merged, root=root)
    return {
        "written": written,
        "count": len(written),
        # 조용히 넘기지 않는다 — 이 수가 움직이면 파서나 상류가 바뀐 신호다
        "merged_into_existing": sorted(merged),
        "empty_definition": sorted(empty),
    }
