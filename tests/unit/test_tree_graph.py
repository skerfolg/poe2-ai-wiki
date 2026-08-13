"""engine/tree/graph — 실제 KB 트리(5,130 노드)로 경로 도구 검증."""

from __future__ import annotations

import pytest

from pok.common.paths import knowledge_dir
from pok.engine.tree.graph import TreeGraph


@pytest.fixture(scope="module")
def graph() -> TreeGraph:
    return TreeGraph(knowledge_dir())


def test_로드_규모(graph: TreeGraph) -> None:
    # KB 수록분 실측 4,553 (원시 트리 5,130에서 제외 기준 적용 후 + 시드 승격분)
    assert len(graph.nodes) > 4500
    # 실측 고정값: Behemoth(5642)는 노터블
    assert graph.nodes[5642].name_en == "Behemoth"
    assert graph.nodes[5642].kind == "notable"


def test_시작점_인접이_양방향(graph: TreeGraph) -> None:
    start = graph.start_of("Witch")
    assert start == 54447
    assert 4739 in graph.adj[start]
    assert start in graph.adj[4739]


def test_최단_경로(graph: TreeGraph) -> None:
    # P3 실증 경로와 동일해야 한다: 시작→61419 소켓 = 10칸
    path = graph.shortest_path({graph.start_of("Witch")}, 61419)
    assert path is not None
    assert len(path) == 10
    assert path[-1] == 61419


def test_connect_anchors_전체_연결(graph: TreeGraph) -> None:
    # P3 빌드의 타깃 13개 — 스크래치 스크립트 실측(본 트리 62pt)과 동일 규모
    targets = [
        51184,
        36302,
        57110,
        5501,
        19125,
        2138,
        14934,
        10398,
        57204,
        34168,
        38614,
        44293,
        49220,
    ]
    allocated, paths = graph.connect_anchors("Witch", targets)
    assert set(targets) <= set(allocated)
    assert len(allocated) == 62  # 그리디 결과 재현 (결정적)
    # 모든 경로의 끝은 해당 타깃
    for t, p in paths.items():
        assert p == [] or p[-1] == t


def test_connect_anchors_비연결은_거부(graph: TreeGraph) -> None:
    """⚠ 예전엔 8415(Sanguimancy, 블러드 메이지)를 무연결 사례로 썼는데 **그게
    결함이었다**(실측 2026-08-12). 형제 전직 5종은 클래스 시작에 링크돼 있는데
    블러드 메이지(59822)만 빠져 있어 못 닿았던 것이지, 「어센던시 노드는 본 트리와
    무연결」이 규칙인 게 아니다 — 그 전제로 시험이 깨진 동작을 정답으로 박아 뒀다.

    진짜 무연결은 **0.5에 없는 계열**(Shadow·Marauder·Duelist·Templar)이다.
    그쪽 클래스 시작 자체가 `CLASS_START`에 없어 권역이 통째로 고아다.

    ⚠ 전직 노드로는 이걸 못 시험한다(#69 이후) — 전직을 안 주면 **소유권 검사가
    먼저** 거부하므로 연결성까지 가지 않는다. 그래서 전직 소속이 아닌 고아 노드를
    쓴다(22개 있다). 두 거부를 한 시험에 겹쳐 두면 어느 쪽이 일했는지 알 수 없다.
    """
    with pytest.raises(ValueError, match="연결 불가"):
        graph.connect_anchors("Witch", [3367])  # 전직 소속 아님 · 본 트리에서 고아

    # 0.5에 없는 계열(Assassin/Shadow1)은 이제 소유권 게이트가 먼저 잡는다.
    with pytest.raises(ValueError, match="ascendancy를 줘야"):
        graph.connect_anchors("Witch", [5162])


def test_candidates_거리와_종류(graph: TreeGraph) -> None:
    out = graph.candidates({graph.start_of("Witch")}, max_dist=5)
    assert out, "반경 5 안에 노터블이 있어야 한다"
    kinds = {n.kind for _, n, _ in out}
    assert kinds <= {"notable", "keystone", "jewel-socket"}
    # 실측: Raw Power(51184)는 거리 5
    by_id = {nid: d for nid, _, d in out}
    assert by_id.get(51184) == 5


def test_어센던시_경로_비용_v6_기계_검증(graph: TreeGraph) -> None:
    """v6 전직 예산 가정의 기계 검증 (2026-08-02) — 단방향 저장된 어센던시
    엣지가 그래프에서 양방향으로 펼쳐져야 이 경로가 나온다 (tree merge 재실행
    시 어센던시 연결 보존을 지키는 회귀 게이트)."""
    start = 32699  # Infernalist 시작 허브 (Witch1)
    pact = graph.shortest_path({start}, 13174)  # 화염술의 맹약
    assert pact is not None and len(pact) == 2  # v6: 계약 2포인트
    have = {start, *pact}
    beidat = graph.shortest_path(have, 46644)  # 베이다트의 의지
    assert beidat is not None and len(beidat) == 4  # v6: 뒤바뀐 육체 경유 4포인트
    core = have | set(beidat)
    for target in (34419, 18158):  # 웃는 번제 / 불꽃을 가져오는 자
        branch = graph.shortest_path(core, target)
        assert branch is not None and len(branch) == 2  # 각 +2 → 합 10 > 예산 8 (분기 강제)


# 해금 제약 (B-13, 실측 2026-08-07) — 오라클 전용 노터블 「힘 소진」이 인퍼널리스트
# 빌드의 치명타 병목 해법으로 사용자에게 제시됐다. 차단이 파이프라인 끝에만 있으면
# 세션은 그 전에 이미 잘못된 설계 결론을 낸다.
_EXHAUST_ALL_POWER = 11428  # Oracle 전용 (unlock_constraint.ascendancy)
_PATH_OF_THE_RENEGADE = 51850  # 선행 노드 3개 요구 (ascendancy 없음)
_RENEGADE_PREREQS = (50239, 9535, 61309)


def test_전직_표기는_무엇이든_실명으로_해소된다(graph: TreeGraph) -> None:
    """빌드 스펙은 코드("Witch1"), unlock_constraint는 실명("Oracle") — 잇지 못하면
    대조 자체가 성립하지 않는다."""
    assert graph.resolve_ascendancy("Druid1") == "Oracle"
    assert graph.resolve_ascendancy("오라클") == "Oracle"
    assert graph.resolve_ascendancy("Oracle") == "Oracle"
    assert graph.resolve_ascendancy("Witch1") == "Infernalist"
    assert graph.resolve_ascendancy(None) is None
    # 모르는 표기는 **원문 그대로** — None으로 떨구면 "제약 없음"으로 읽혀 잠긴 노드가 샌다
    assert graph.resolve_ascendancy("Nonsense") == "Nonsense"


def test_전직을_주면_자기_해금_노드를_후보로_받는다(graph: TreeGraph) -> None:
    """미지정 기본값(전량 배제)은 안전하지만 **과잉**이다 — 오라클 빌드가 자기
    노터블 42개를 못 본다. optimize_tree가 전직을 안 넘겨 실제로 그랬다(B-13)."""
    near = {graph.start_of("Witch")}
    default = graph.candidates(near, max_dist=40)
    assert not [n for _, n, _ in default if n.unlock_constraint], "미지정이면 전량 배제"

    oracle = {nid for nid, _, _ in graph.candidates(near, max_dist=40, ascendancy_name="Oracle")}
    assert _EXHAUST_ALL_POWER in oracle
    # 코드로 줘도 같은 판정이어야 한다 (빌드 스펙이 드는 값이 코드다)
    by_code = {nid for nid, _, _ in graph.candidates(near, max_dist=40, ascendancy_name="Druid1")}
    assert by_code == oracle
    # 남의 전직에게는 여전히 잠겨 있다
    infernal = {nid for nid, _, _ in graph.candidates(near, max_dist=40, ascendancy_name="Witch1")}
    assert _EXHAUST_ALL_POWER not in infernal


def test_선행노드형_제약은_선행을_찍어야_후보다(graph: TreeGraph) -> None:
    """`unlock_constraint`에 ascendancy 없이 nodes만 있는 꼴 — 전직 대조로는 걸러지지
    않아 본 트리 후보로 샜다(실측 2026-08-07: 2건)."""
    node = graph.nodes[_PATH_OF_THE_RENEGADE]
    assert node.locked_to is None, "전직 제약이 아니다 — 그래서 이전 검사가 놓쳤다"
    assert set(node.requires_nodes) == set(_RENEGADE_PREREQS)

    near = {graph.start_of("Ranger")}
    without = {nid for nid, _, _ in graph.candidates(near, max_dist=60)}
    assert _PATH_OF_THE_RENEGADE not in without, "선행 없이 후보에 들면 안 된다"
    withal = {nid for nid, _, _ in graph.candidates(near | set(_RENEGADE_PREREQS), max_dist=60)}
    assert _PATH_OF_THE_RENEGADE in withal, "선행을 다 찍었으면 열려야 한다"


def test_블러드_메이지의_혈액술은_공짜다(graph: TreeGraph) -> None:
    """사용자 판정 2026-08-12: "블러드 메이지는 기본으로 혈액술 어센던시가 할당되어
    있다. 블러드 메이지만 유일하게 하나를 기본 할당하고 시작해 총 9포인트가 된다."

    실측이 뒷받침한다 — 래더 표본에서 블러드 메이지만 전직 **노터블 5개**(다른 전직
    4개)이고 Sanguimancy(8415)는 10/10 보유다. 포인트를 안 쓰므로 경로 비용에서 뺀다.
    """
    assert graph.granted_nodes("Blood Mage") == frozenset({8415})
    assert graph.granted_nodes("Lich") == frozenset()

    allocated, _paths = graph.connect_anchors("Witch", [26383], ascendancy="Blood Mage")
    assert 26383 in allocated
    assert 8415 not in allocated, "공짜 노드를 포인트로 세면 예산이 틀어진다"


def test_남의_전직_노드는_거부한다(graph: TreeGraph) -> None:
    """실측 2026-08-12: `connect_anchors("Witch", [11495])`가 **성공했다** — 11495는
    마셜 아티스트 시작 노드다. 본 트리를 빙 돌아 남의 전직 권역으로 들어간다.
    인게임에서는 불가능하고, 그렇게 나온 트리는 만들 수 없는 빌드다.

    후보 선정과 출고 게이트가 막고 있었지만 이 함수를 **직접 부르는 경로**는
    뚫려 있었다.
    """
    with pytest.raises(ValueError, match="다른 전직"):
        graph.connect_anchors("Witch", [11495], ascendancy="Blood Mage")
    # 자기 전직 노드는 통과해야 한다 — 게이트가 정상을 막으면 안 된다(형태 ⑤)
    allocated, _ = graph.connect_anchors("Witch", [26383], ascendancy="Blood Mage")
    assert 26383 in allocated


def test_전직을_모르면_전직_노드를_거부한다(graph: TreeGraph) -> None:
    """#69 남은 구멍: 소유권 검사가 **인자를 주면만** 돌았다.

    `ascendancy=`를 주면 남의 전직 노드를 막지만, **안 주면 검사가 통째로 꺼졌다** —
    호출자가 전직을 모르는 경로가 실재하므로 그쪽이 그대로 구멍이었다. 규율을
    「주면 검사」로 두면 인자를 빠뜨리는 것만으로 게이트가 사라진다(철칙 5).
    모르면 통과가 아니라 **거부**여야 한다.
    """
    with pytest.raises(ValueError, match="ascendancy를 줘야"):
        graph.connect_anchors("Witch", [26383])  # Sunder the Flesh — 블러드 메이지 노터블
    with pytest.raises(ValueError, match="ascendancy를 줘야"):
        graph.connect_anchors("Witch", [11495])  # 남의 전직(마셜 아티스트) — 예전엔 통과했다

    # ⚠ 일반 패시브만 잇는 호출은 종전대로 전직 없이 된다 — 게이트가 정상을 막으면
    #    호출부가 아무 전직이나 넣어 우회하고, 그러면 검사가 있으나 마나가 된다(형태 ⑤).
    allocated, _ = graph.connect_anchors("Witch", [14934])
    assert 14934 in allocated


def test_전직_포인트_상한은_관측치이고_전직마다_다르다(graph: TreeGraph) -> None:
    """#68: 「블러드 메이지만 9, 나머지 8」이라는 전제가 **실측으로 뒤집혔다**.

    래더 230벌에서 9포인트가 48벌 나왔고, 그게 6종에 몰려 있다(우연이라기엔 치우쳤다).
    블러드 메이지는 오히려 8 + 혈액술(공짜) = 9칸이라 **포인트로는 8**이다.
    표가 다시 「전 전직 8」로 뭉개지면 여기서 걸린다.
    """
    assert graph.ascendancy_point_cap("Acolyte of Chayula") == 9
    assert graph.ascendancy_point_cap("Smith of Kitava") == 9
    assert graph.ascendancy_point_cap("Blood Mage") == 8, "공짜 노드는 포인트가 아니다"
    assert graph.ascendancy_point_cap("Stormweaver") == 8
    # 코드 표기로도 같은 답이 나와야 한다 — 호출부가 무엇을 들고 오는지 모른다.
    assert graph.ascendancy_point_cap("Monk3") == 9
    # 전직을 모르면 무제한이 아니라 기본값 — 모른다고 판단을 끄면 조용해진다.
    assert graph.ascendancy_point_cap(None) == 8
