"""PoB 계산 도구 — 결정적 래퍼 (지능 없음, AD-3).

compute_pob: BuildSpec 하나를 계산해 결과를 돌려준다 (RC1: validation은 floor).
evaluate_delta: 변경안들의 스탯 델타를 실측한다 (AD-8 반프록시 — 효율은
에이전트가 추측하지 않고 여기서 측정해 읽는다). 변경안이 여러 개면 상주
데몬으로 기동 비용을 상각한다.

"무엇을 바꿀지"의 판단은 skills/+에이전트의 몫 — 여기는 측정만 한다.
"""

from __future__ import annotations

from dataclasses import dataclass

from pok.pob.buildxml import BuildSpec
from pok.pob.daemon import PobDaemon
from pok.pob.runner import PobResult, run_build


def compute_pob(spec: BuildSpec, *, use_cache: bool = True) -> PobResult:
    """단발 계산 (캐시 경로). 적법성 신호(pruned_nodes)는 결과에 포함된다."""
    return run_build(spec, use_cache=use_cache)


@dataclass(frozen=True)
class Delta:
    """변경안 하나의 실측 델타. 스탯 부재(nil→값 등)는 0 취급이 아니라 None."""

    label: str
    result: PobResult
    changes: dict[str, tuple[float | None, float | None]]  # stat → (base, variant)

    def diff(self, stat: str) -> float | None:
        base, variant = self.changes.get(stat, (None, None))
        if base is None or variant is None:
            return None
        return variant - base


def evaluate_delta(
    base: BuildSpec,
    variants: dict[str, BuildSpec],
    *,
    stats: tuple[str, ...] = (),
) -> tuple[PobResult, list[Delta]]:
    """base 대비 변경안들의 스탯 델타 실측.

    stats를 주면 그 스탯만 changes에 담고, 비우면 양쪽에 존재하는 모든 스탯.
    반환: (base 결과, 변경안별 Delta — variants 삽입 순서 유지).
    """
    with PobDaemon() as daemon:
        base_result = daemon.compute_build(base)
        deltas: list[Delta] = []
        for label, spec in variants.items():
            result = daemon.compute_build(spec)
            keys = stats or tuple(sorted(set(base_result.stats) | set(result.stats)))
            changes = {
                k: (base_result.stats.get(k), result.stats.get(k))
                for k in keys
                if base_result.stats.get(k) != result.stats.get(k) or stats
            }
            deltas.append(Delta(label=label, result=result, changes=changes))
    return base_result, deltas
