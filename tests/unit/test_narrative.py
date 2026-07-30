"""⑤ 서술 트랙: wiki 산출물 코드 게이트 (픽스처, 네트워크 없음)."""

from __future__ import annotations

import json
import shutil
from pathlib import Path

from pok.common.paths import project_root
from pok.kb.ingest.narrative import check_wiki_docs, curated_targets

_SEED = {
    "id": "skill.testspark",
    "type": "Skill",
    "name": {"ko": "테스트", "en": "Testspark"},
    "tags": [],
    "data": {"category": "spell"},
    "verification": "UNVERIFIED",
    "sources": [{"src": "poe2db", "ref": "x", "patch": "t"}],
}


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    knowledge = root / "knowledge"
    root.mkdir()
    (root / "pyproject.toml").write_text("", encoding="utf-8")
    shutil.copytree(project_root() / "knowledge" / "schema", knowledge / "schema")
    (knowledge / "game-data" / "skills").mkdir(parents=True)
    (knowledge / "game-data" / "skills" / "testspark.json").write_text(
        json.dumps(_SEED), encoding="utf-8"
    )
    (knowledge / "wiki" / "skills").mkdir(parents=True)
    return knowledge


def _doc(
    id_: str = "skill.testspark",
    label: str = "UNVERIFIED",
    revid: str = "123",
    verified_by: str = "",
) -> str:
    vb = f"verified_by: {verified_by}\n" if verified_by else ""
    return f"---\nid: {id_}\nlabel: {label}\n{vb}source_revid: {revid}\n---\n\n# 본문\n"


def test_curated_targets_are_individual_json_only(tmp_path: Path) -> None:
    """큐레이션 대상 = 개별 JSON 파일만 (벌크 NDJSON은 서술 없음, KI-7 §6-1)."""
    knowledge = _repo(tmp_path)
    bulk = knowledge / "game-data" / "gems"
    bulk.mkdir()
    (bulk / "skills.ndjson").write_text(
        json.dumps({**_SEED, "id": "skill.bulkone"}) + "\n", encoding="utf-8"
    )
    targets = curated_targets(knowledge)
    assert [t["id"] for t in targets] == ["skill.testspark"], "NDJSON 레코드는 제외"


def test_check_wiki_docs_gates(tmp_path: Path) -> None:
    knowledge = _repo(tmp_path)
    w = knowledge / "wiki" / "skills"
    (w / "ok.md").write_text(_doc(), encoding="utf-8")
    (w / "bad-id.md").write_text(_doc(id_="skill.ghost"), encoding="utf-8")
    (w / "bad-label.md").write_text(_doc(label="TRUSTED"), encoding="utf-8")
    (w / "no-front.md").write_text("# front-matter 없음\n", encoding="utf-8")
    # 승격 근거 규칙: UNVERIFIED 초과 라벨은 verified_by 필수
    (w / "promoted-ok.md").write_text(
        _doc(label="SUPPORTED_INFERENCE", verified_by="model-spotcheck 2026-07-30"),
        encoding="utf-8",
    )
    (w / "promoted-bad.md").write_text(_doc(label="IN_GAME"), encoding="utf-8")

    result = check_wiki_docs(knowledge)
    assert result["checked"] == 6
    errors = "\n".join(result["errors"])
    assert "skill.ghost" in errors and "가 KB에 없음" in errors
    assert "TRUSTED" in errors and "어휘 밖" in errors
    assert "front-matter 없음" in errors
    assert "promoted-bad.md" in errors and "verified_by 없음" in errors, (
        "근거 없는 승격은 게이트가 거부"
    )
    assert "ok.md" not in errors, "정상 문서는 통과"
    assert "promoted-ok.md" not in errors, "근거 있는 승격은 통과"
