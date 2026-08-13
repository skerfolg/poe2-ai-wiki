"""반사실 캠페인의 P0 게이트 — 「무엇이 빠졌나」를 세는 계약을 잠근다 (2026-08-13).

이 조사가 없으면 캠페인이 **231벌로 계획된다**. 실측은 딜 축 46벌이다(`damage_comparable`).
표본 수를 5배 부풀린 계획은 「다 했나」에 영영 예라고 답하지 못한다.
"""

from __future__ import annotations

import json

from pok.engine import corpus_fidelity as cf


def _raw(account: str, name: str, export: str = "code", level: int = 100) -> str:
    return json.dumps(
        {"pob_export": export, "raw": {"account": account, "name": name, "level": level}}
    )


class _Restored:
    def __init__(self, dropped=(), notes=("n1",), needs=("d1",)) -> None:
        self.notes = notes
        self.needs_decision = needs
        self.dropped_item_granted = dropped

    @property
    def faithful(self) -> bool:
        return not self.notes and not self.needs_decision

    @property
    def damage_comparable(self) -> bool:
        return not self.dropped_item_granted


def test_같은_캐릭터가_여러_컨셉에_겹쳐도_한_번만_센다(tmp_path, monkeypatch) -> None:
    """실측: 파일 300개 = 고유 231명. 겹친 것을 세면 표본이 부풀고 같은 빌드를 두 번 잰다."""
    monkeypatch.setattr(cf, "spec_from_pob", lambda _c: _Restored())
    for concept in ("class-Lich", "keypassives-Chaos_Inoculation"):
        d = tmp_path / "0-5" / concept
        d.mkdir(parents=True)
        (d / "a.json").write_text(_raw("acct-1", "Char"), encoding="utf-8")

    out = cf.survey("0-5", base=tmp_path)
    assert out["sample"]["files_seen"] == 2
    assert out["sample"]["unique_builds"] == 1, "겹친 캐릭터를 두 번 셌다"
    assert len(out["builds"]) == 1


def test_축별_표본_수를_따로_낸다(tmp_path, monkeypatch) -> None:
    """`faithful`은 게이트로 못 쓴다 — 실측 0/231이다(형식의 정보 손실)."""
    specs = {
        "clean": _Restored(),
        "dropped": _Restored(dropped=(("Purity of Fire", 2),)),
    }
    monkeypatch.setattr(cf, "spec_from_pob", lambda code: specs[code])
    d = tmp_path / "0-5" / "class-Titan"
    d.mkdir(parents=True)
    (d / "a.json").write_text(_raw("a-1", "A", export="clean"), encoding="utf-8")
    (d / "b.json").write_text(_raw("b-2", "B", export="dropped"), encoding="utf-8")

    out = cf.survey("0-5", base=tmp_path)
    assert out["usable"]["damage_comparable"] == 1
    assert out["usable"]["any_dropped_granted"] == 1
    assert out["usable"]["faithful"] == 0, "notes가 있으면 faithful이 아니다"
    # ⚠ 빠진 스킬 **이름**이 남아야 방어 축 오염을 판정할 수 있다(엔진은 판정하지 않는다)
    dropped = next(b for b in out["builds"] if b["build"] == "b-2/B")["dropped_granted"]
    assert dropped == [{"skill": "Purity of Fire", "supports_lost": 2}]


def test_복원_실패를_조용히_빼지_않는다(tmp_path, monkeypatch) -> None:
    def boom(_code: str):
        raise ValueError("깨진 코드")

    monkeypatch.setattr(cf, "spec_from_pob", boom)
    d = tmp_path / "0-5" / "class-Titan"
    d.mkdir(parents=True)
    (d / "a.json").write_text(_raw("a-1", "A"), encoding="utf-8")

    out = cf.survey("0-5", base=tmp_path)
    assert out["sample"]["restore_failed"] == 1
    assert out["failed"][0]["build"] == "a-1/A"
    assert "깨진 코드" in out["failed"][0]["error"], "사유가 없으면 고칠 수 없다"


def test_스냅샷이_없으면_사유를_담아_낸다(tmp_path, monkeypatch) -> None:
    """스탬프가 조용히 비면 「전제를 안 재고 측정했다」가 된다 — 재개 시 무효 판정 불가."""
    monkeypatch.setattr(cf, "spec_from_pob", lambda _c: _Restored())
    d = tmp_path / "0-5" / "class-Titan"
    d.mkdir(parents=True)
    (d / "a.json").write_text(_raw("a-1", "A"), encoding="utf-8")

    out = cf.survey("0-5", base=tmp_path)
    prov = out["provenance"]
    assert "pob_commit" in prov
    if not prov["pob_commit"]:
        assert prov.get("why"), "스탬프가 비었는데 사유가 없다"
