from typing import List, Dict, Set, Optional, Any, Callable
from dataclasses import dataclass, field
import warnings
from .gdr import GDRContext, _count_draws, _total_resource_consumed


@dataclass
class PoolSnapshot:
    pool_id: str
    draw_count: int
    target_card_draws: int
    pity_draws: int
    resources_consumed: Dict[str, float]
    cards_obtained: Dict[str, int] = field(default_factory=dict)


@dataclass
class CumulativeSnapshot:
    pool_id: str
    pool_end_time: float
    cumulative_draws: int
    cumulative_target_cards: int
    cumulative_pity_draws: int
    cumulative_resources_consumed: Dict[str, float]
    target_achievement_rate: float
    ssr_collection_rate: float
    resource_remaining: float


def compute_per_pool_snapshots(history, ctx: GDRContext, target_ids: Set[str] = None) -> Dict[str, PoolSnapshot]:
    if target_ids is None:
        target_ids = set(ctx.target_specs.keys())
    snapshots: Dict[str, PoolSnapshot] = {}
    for iv in history:
        if iv.action_type != 'draw' or not iv.pool_id:
            continue
        pid = iv.pool_id
        if pid not in snapshots:
            snapshots[pid] = PoolSnapshot(
                pool_id=pid, draw_count=0, target_card_draws=0,
                pity_draws=0, resources_consumed={},
            )
        snap = snapshots[pid]
        snap.draw_count += 1
        if iv.card_id in target_ids:
            snap.target_card_draws += 1
        if iv.pity_triggered:
            snap.pity_draws += 1
        for k, v in iv.resources_consumed.items():
            snap.resources_consumed[k] = snap.resources_consumed.get(k, 0) + v
        if iv.card_id:
            snap.cards_obtained[iv.card_id] = snap.cards_obtained.get(iv.card_id, 0) + 1
    return snapshots


def compute_cumulative_snapshots(
    history, ctx: GDRContext,
    pool_end_times: Dict[str, float],
    target_ids: Set[str] = None,
    ssr_ids: Set[str] = None,
) -> List[CumulativeSnapshot]:
    if target_ids is None:
        target_ids = set(ctx.target_specs.keys())
    if ssr_ids is None:
        ssr_ids = ctx.ssr_ids

    sorted_pools = sorted(pool_end_times.items(), key=lambda x: x[1])
    results = []
    total_target_qty = sum(ctx.target_specs.values())

    for pool_id, end_time in sorted_pools:
        draws_up_to = [iv for iv in history if iv.action_type == 'draw' and iv.real_time_after <= end_time]
        cumulative_draws = len(draws_up_to)
        cumulative_target = sum(1 for iv in draws_up_to if iv.card_id in target_ids)
        cumulative_pity = sum(1 for iv in draws_up_to if iv.pity_triggered)
        cumulative_consumed: Dict[str, float] = {}
        for iv in draws_up_to:
            for k, v in iv.resources_consumed.items():
                cumulative_consumed[k] = cumulative_consumed.get(k, 0) + v

        tar_rate = cumulative_target / total_target_qty if total_target_qty > 0 else 0.0
        unique_ssr = len(set(iv.card_id for iv in draws_up_to if iv.card_id in ssr_ids))
        ssr_rate = unique_ssr / len(ssr_ids) if ssr_ids else 0.0

        res_remaining = 0.0
        for resource, initial in ctx.initial_resources.items():
            gained = sum(iv.resources_gained.get(resource, 0) for iv in history if iv.real_time_after <= end_time)
            consumed = cumulative_consumed.get(resource, 0)
            res_remaining += initial + gained - consumed

        results.append(CumulativeSnapshot(
            pool_id=pool_id,
            pool_end_time=end_time,
            cumulative_draws=cumulative_draws,
            cumulative_target_cards=cumulative_target,
            cumulative_pity_draws=cumulative_pity,
            cumulative_resources_consumed=cumulative_consumed,
            target_achievement_rate=tar_rate,
            ssr_collection_rate=ssr_rate,
            resource_remaining=res_remaining,
        ))
    return results


def compute_per_pool_snapshots_batch(
    histories, ctx: GDRContext, target_ids: Set[str] = None
) -> Dict[str, List[PoolSnapshot]]:
    result: Dict[str, List[PoolSnapshot]] = {}
    for h in histories:
        snaps = compute_per_pool_snapshots(h, ctx, target_ids)
        for pid, snap in snaps.items():
            if pid not in result:
                result[pid] = []
            result[pid].append(snap)
    return result


def compute_cumulative_snapshots_batch(
    histories, ctx: GDRContext,
    pool_end_times: Dict[str, float],
    target_ids: Set[str] = None,
    ssr_ids: Set[str] = None,
) -> Dict[str, List[CumulativeSnapshot]]:
    result: Dict[str, List[CumulativeSnapshot]] = {}
    for h in histories:
        snaps = compute_cumulative_snapshots(h, ctx, pool_end_times, target_ids, ssr_ids)
        for snap in snaps:
            if snap.pool_id not in result:
                result[snap.pool_id] = []
            result[snap.pool_id].append(snap)
    return result


def per_pool_summary_stats(
    batch_snaps: Dict[str, List[PoolSnapshot]],
) -> Dict[str, Dict[str, float]]:
    result = {}
    for pid, snaps in batch_snaps.items():
        if not snaps:
            continue
        draws = [s.draw_count for s in snaps]
        targets = [s.target_card_draws for s in snaps]
        pity = [s.pity_draws for s in snaps]
        n = len(snaps)
        result[pid] = {
            'mean_draws': sum(draws) / n,
            'mean_target_cards': sum(targets) / n,
            'mean_pity_draws': sum(pity) / n,
            'pity_count': sum(pity) / n,
            'target_count': sum(targets) / n,
        }
    return result


def cumulative_gdr_at_pool_ends(
    batch_cum: Dict[str, List[CumulativeSnapshot]],
) -> Dict[str, Dict[str, List[float]]]:
    result = {}
    for pid, snaps in batch_cum.items():
        if not snaps:
            continue
        result[pid] = {
            'target_achievement_rate': [s.target_achievement_rate for s in snaps],
            'ssr_collection_rate': [s.ssr_collection_rate for s in snaps],
            'resource_remaining': [s.resource_remaining for s in snaps],
            'cumulative_draws': [float(s.cumulative_draws) for s in snaps],
            'cumulative_pity_draws': [float(s.cumulative_pity_draws) for s in snaps],
        }
    return result


@dataclass
class TransitionMatrix:
    from_pool_id: str
    to_pool_id: str
    success_to_success: float
    success_to_fail: float
    fail_to_success: float
    fail_to_fail: float
    success_rate_before: float
    success_rate_after: float


def compute_transition_matrices(
    histories, ctx: GDRContext,
    pool_end_times: Dict[str, float],
    target_ids: Set[str] = None,
    success_func: Callable = None,
) -> List[TransitionMatrix]:
    """[deprecated] 基于 InfoVector 历史路径的转移矩阵计算。

    请改用 compute_transition_matrices_from_flags() + compute_transition_flags_from_gdr()。
    """
    warnings.warn(
        "compute_transition_matrices() 已废弃，请使用 "
        "compute_transition_matrices_from_flags() + compute_transition_flags_from_gdr()",
        DeprecationWarning, stacklevel=2,
    )
    sorted_pools = sorted(pool_end_times.items(), key=lambda x: x[1])
    pool_ids_ordered = [pid for pid, _ in sorted_pools]

    n_sims = len(histories)
    if n_sims == 0:
        return []

    if success_func is None:
        if target_ids is None:
            target_ids = set(ctx.target_specs.keys())
        total_target_qty = sum(ctx.target_specs.values())

        def success_func(history, end_time):
            obtained = 0
            for iv in history:
                if iv.action_type == 'draw' and iv.real_time_after <= end_time and iv.card_id in target_ids:
                    obtained += 1
            return obtained >= total_target_qty

    success_flags_per_sim: List[List[bool]] = []
    for h in histories:
        flags = []
        for pool_id, end_time in sorted_pools:
            flags.append(success_func(h, end_time))
        success_flags_per_sim.append(flags)

    return compute_transition_matrices_from_flags(success_flags_per_sim, pool_ids_ordered)


def compute_transition_matrices_from_flags(
    success_flags_per_sim: List[List[bool]],
    pool_ids_ordered: List[str],
) -> List[TransitionMatrix]:
    """从布尔矩阵计算转移矩阵（纯函数）。

    Args:
        success_flags_per_sim: [模拟索引][池索引] → 该池结束时是否成功
        pool_ids_ordered: 按结束时间排序的池ID列表
    """
    n_sims = len(success_flags_per_sim)
    if n_sims == 0:
        return []

    n_pools = len(pool_ids_ordered)
    results = []
    for i in range(n_pools):
        to_pid = pool_ids_ordered[i]
        from_pid = pool_ids_ordered[i - 1] if i > 0 else '(初始)'

        if i == 0:
            before = [False] * n_sims
        else:
            before = [
                success_flags_per_sim[s][i - 1]
                if s < len(success_flags_per_sim) and i - 1 < len(success_flags_per_sim[s])
                else False
                for s in range(n_sims)
            ]
        after = [
            success_flags_per_sim[s][i]
            if s < len(success_flags_per_sim) and i < len(success_flags_per_sim[s])
            else False
            for s in range(n_sims)
        ]

        ss = sum(1 for b, a in zip(before, after) if b and a)
        sf = sum(1 for b, a in zip(before, after) if b and not a)
        fs = sum(1 for b, a in zip(before, after) if not b and a)
        ff = sum(1 for b, a in zip(before, after) if not b and not a)

        s_before = sum(1 for b in before if b)
        s_after = sum(1 for a in after if a)

        results.append(TransitionMatrix(
            from_pool_id=from_pid,
            to_pool_id=to_pid,
            success_to_success=ss / s_before if s_before > 0 else 0,
            success_to_fail=sf / s_before if s_before > 0 else 0,
            fail_to_success=fs / (n_sims - s_before) if (n_sims - s_before) > 0 else 0,
            fail_to_fail=ff / (n_sims - s_before) if (n_sims - s_before) > 0 else 0,
            success_rate_before=s_before / n_sims,
            success_rate_after=s_after / n_sims,
        ))
    return results


def compute_transition_flags_from_gdr(
    cumulative_snapshots: Dict[str, List[Dict]],
    pool_ids_ordered: List[str],
    target_specs: Dict[str, int],
    gdr_key: str = 'all_targets',
    threshold: float = 1.0,
    scope: str = 'cumulative',
    aggregates: List[Dict] = None,
    ssr_ids: Set[str] = None,
    **gdr_kwargs,
) -> List[List[bool]]:
    """通过 GDR 框架逐池判定成功/失败，替代硬编码的 _compute_transition_flags()。"""
    from .process_trace import compute_pool_gdr_cumulative, compute_pool_gdr_single_pool

    if scope == 'cumulative':
        n_sims = len(next(iter(cumulative_snapshots.values()), [])) if cumulative_snapshots else 0
    else:
        n_sims = len(aggregates) if aggregates else 0

    if n_sims == 0:
        return []

    from .gdr import UNIFIED_GDR_REGISTRY
    gdr_defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
    lower_is_better = gdr_defn.lower_is_better if gdr_defn else False

    flags_per_sim = [[] for _ in range(n_sims)]
    for pool_id in pool_ids_ordered:
        for sim_idx in range(n_sims):
            if scope == 'cumulative':
                snaps = cumulative_snapshots.get(pool_id, [])
                snap = snaps[sim_idx] if sim_idx < len(snaps) else {}
                val = compute_pool_gdr_cumulative(
                    snap, pool_id, target_specs, gdr_key,
                    ssr_ids=ssr_ids, **gdr_kwargs,
                )
            else:
                agg = aggregates[sim_idx] if aggregates and sim_idx < len(aggregates) else {}
                val = compute_pool_gdr_single_pool(
                    agg, pool_id, target_specs, gdr_key,
                    ssr_ids=ssr_ids, **gdr_kwargs,
                )
            if val is None:
                flags_per_sim[sim_idx].append(False)
            elif lower_is_better:
                flags_per_sim[sim_idx].append(val <= threshold)
            else:
                flags_per_sim[sim_idx].append(val >= threshold)
    return flags_per_sim
