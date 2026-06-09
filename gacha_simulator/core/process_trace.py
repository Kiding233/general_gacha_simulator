from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set


@dataclass
class PoolEvent:
    pool_id: str
    pool_type: str
    event_type: str
    pity_name: Optional[str] = None
    draws: int = 0
    counter_max: int = 0


@dataclass
class SampleTrace:
    events: List[PoolEvent] = field(default_factory=list)
    pool_success: Dict[str, bool] = field(default_factory=dict)
    is_success: bool = False
    gdr_value: float = 0.0
    pool_gdr_values: Dict[str, float] = field(default_factory=dict)


def infer_events(compact: Dict, target_ids: Set[str],
                 pool_types: Optional[Dict[str, str]] = None,
                 pool_target_map: Optional[Dict[str, Set[str]]] = None) -> Dict[str, PoolEvent]:
    if pool_types is None:
        pool_types = {}
    if pool_target_map is None:
        pool_target_map = {}
    pool_ids_list = compact.get('draw_pool_ids', [])
    card_ids = compact.get('draw_card_ids', [])
    pity_flags = compact.get('draw_pity', [])
    pity_names = compact.get('draw_pity_names', [])
    pity_counter_max = compact.get('draw_pity_counter_max', [])
    pool_card_counts = compact.get('pool_card_counts', {})
    pool_draw_counts = compact.get('pool_draw_counts', {})
    pool_pity_counts = compact.get('pool_pity_counts', {})
    pool_counter_max = compact.get('pool_counter_max', {})
    pool_pity_names = compact.get('pool_pity_names', {})

    if pool_ids_list:
        return _infer_from_draw_sequence(
            pool_ids_list, card_ids, pity_flags, pity_names,
            pity_counter_max, pool_card_counts, pool_draw_counts, target_ids,
            pool_types=pool_types, pool_target_map=pool_target_map,
        )
    else:
        return _infer_from_aggregate(
            pool_draw_counts, pool_card_counts, pool_pity_counts, target_ids,
            pool_counter_max, pool_types=pool_types,
            pool_pity_names=pool_pity_names, pool_target_map=pool_target_map,
        )


def _resolve_skip_ignore(pool_id, pool_card_counts, target_ids, pool_target_map):
    """判定 0 抽池应为 skip（有目标但未抽）还是 ignore（无目标可抽）。

    优先使用 pool_target_map（池→可掉落目标卡映射）精确判定；
    未提供时回退旧启发式（基于已获得卡 + target_ids 非空）。
    """
    if pool_target_map:
        has_target = bool(pool_target_map.get(pool_id, set()))
        return 'skip' if has_target else 'ignore'
    has_target_in_pool = any(cid in target_ids for cid in pool_card_counts.get(pool_id, {}))
    return 'skip' if (has_target_in_pool or target_ids) else 'ignore'


def _infer_from_draw_sequence(pool_ids_list, card_ids, pity_flags, pity_names,
                               pity_counter_max, pool_card_counts,
                               pool_draw_counts, target_ids,
                               pool_types=None, pool_target_map=None):
    if pool_types is None:
        pool_types = {}
    if pool_target_map is None:
        pool_target_map = {}
    pool_data = {}
    for pool_id in set(pool_ids_list):
        pool_data[pool_id] = {
            'target_count': 0,
            'pity_count': 0,
            'pity_names': set(),
            'counter_max': 0,
            'draws': 0,
        }

    for i, pid in enumerate(pool_ids_list):
        pd = pool_data[pid]
        pd['draws'] += 1
        if card_ids[i] in target_ids:
            pd['target_count'] += 1
        if pity_flags[i]:
            pd['pity_count'] += 1
        if i < len(pity_names) and pity_names[i]:
            for name in pity_names[i].split(','):
                pd['pity_names'].add(name)
        if i < len(pity_counter_max):
            pd['counter_max'] = max(pd['counter_max'], pity_counter_max[i])

    result = {}
    for pool_id, pd in pool_data.items():
        pdc = pool_draw_counts.get(pool_id, 0)
        pool_type = pool_types.get(pool_id, '角色')

        if pool_type == '资源':
            result[pool_id] = PoolEvent(
                pool_id=pool_id,
                pool_type='resource',
                event_type='resource_draw' if pdc > 0 else 'resource_ignore',
            )
            continue

        if pool_type == '兑换':
            result[pool_id] = PoolEvent(
                pool_id=pool_id,
                pool_type='exchange',
                event_type='exchange' if pdc > 0 else 'no_exchange',
            )
            continue

        if pdc == 0:
            event_type = _resolve_skip_ignore(pool_id, pool_card_counts, target_ids, pool_target_map)
        elif pd['target_count'] > 0 and pd['pity_count'] > 0:
            pity_name_str = ','.join(sorted(pd['pity_names'])) if pd['pity_names'] else None
            event_type = 'pity_hit'
            result[pool_id] = PoolEvent(
                pool_id=pool_id,
                pool_type='draw',
                event_type=event_type,
                pity_name=pity_name_str,
                draws=pd['draws'],
                counter_max=pd['counter_max'],
            )
            continue
        elif pd['target_count'] > 0:
            event_type = 'early_hit'
        else:
            event_type = 'miss'

        result[pool_id] = PoolEvent(
            pool_id=pool_id,
            pool_type='draw',
            event_type=event_type,
            draws=pd['draws'],
            counter_max=pd['counter_max'],
        )

    for pool_id in set(pool_draw_counts.keys()) - set(pool_ids_list):
        pool_type = pool_types.get(pool_id, '角色')
        if pool_type == '资源':
            pdc = pool_draw_counts.get(pool_id, 0)
            result[pool_id] = PoolEvent(
                pool_id=pool_id,
                pool_type='resource',
                event_type='resource_draw' if pdc > 0 else 'resource_ignore',
            )
            continue
        if pool_type == '兑换':
            pdc = pool_draw_counts.get(pool_id, 0)
            result[pool_id] = PoolEvent(
                pool_id=pool_id,
                pool_type='exchange',
                event_type='exchange' if pdc > 0 else 'no_exchange',
            )
            continue
        result[pool_id] = PoolEvent(
            pool_id=pool_id,
            pool_type='draw',
            event_type=_resolve_skip_ignore(pool_id, pool_card_counts, target_ids, pool_target_map),
        )

    return result


def _infer_from_aggregate(pool_draw_counts, pool_card_counts, pool_pity_counts, target_ids,
                          pool_counter_max=None, pool_types=None, pool_pity_names=None,
                          pool_target_map=None):
    if pool_counter_max is None:
        pool_counter_max = {}
    if pool_types is None:
        pool_types = {}
    if pool_pity_names is None:
        pool_pity_names = {}
    if pool_target_map is None:
        pool_target_map = {}
    result = {}
    all_pool_ids = set(pool_draw_counts.keys())

    for pool_id in all_pool_ids:
        pdc = pool_draw_counts.get(pool_id, 0)
        pcc = pool_card_counts.get(pool_id, {})
        ppc = pool_pity_counts.get(pool_id, 0)
        pcm = pool_counter_max.get(pool_id, 0)
        pool_type = pool_types.get(pool_id, '角色')

        if pool_type == '资源':
            result[pool_id] = PoolEvent(
                pool_id=pool_id,
                pool_type='resource',
                event_type='resource_draw' if pdc > 0 else 'resource_ignore',
            )
            continue

        if pool_type == '兑换':
            result[pool_id] = PoolEvent(
                pool_id=pool_id,
                pool_type='exchange',
                event_type='exchange' if pdc > 0 else 'no_exchange',
            )
            continue

        if pdc == 0:
            event_type = _resolve_skip_ignore(pool_id, pool_card_counts, target_ids, pool_target_map)
            pity_name = None
        else:
            target_in_pool = sum(cnt for cid, cnt in pcc.items() if cid in target_ids)
            names = pool_pity_names.get(pool_id, [])
            pity_name = ','.join(names) if names else None
            if target_in_pool > 0 and ppc > 0:
                event_type = 'pity_hit'
            elif target_in_pool > 0:
                event_type = 'early_hit'
            else:
                event_type = 'miss'

        result[pool_id] = PoolEvent(
            pool_id=pool_id,
            pool_type='draw',
            event_type=event_type,
            pity_name=pity_name,
            draws=pdc,
            counter_max=pcm,
        )

    return result


def compute_pool_gdr_cumulative(cum_snapshot: Dict, pool_id: str,
                                 target_specs: Dict[str, int], gdr_key: str,
                                 **kwargs) -> Optional[float]:
    from .gdr import compute_gdr_from_cumulative
    try:
        return compute_gdr_from_cumulative(
            cum_snapshot, target_specs, gdr_key, **kwargs
        )
    except Exception:
        return None


def compute_pool_gdr_single_pool(aggregate: Dict, pool_id: str,
                                  target_specs: Dict[str, int], gdr_key: str,
                                  ssr_ids: Optional[Set[str]] = None,
                                  weapon_character_map: Optional[Dict] = None,
                                  **kwargs) -> Optional[float]:
    from .gdr import compute_gdr_from_compact

    pool_card_counts = aggregate.get('pool_card_counts', {})
    pool_draw_counts = aggregate.get('pool_draw_counts', {})
    pool_pity_counts = aggregate.get('pool_pity_counts', {})
    pool_res_consumed = aggregate.get('pool_resources_consumed', {})
    pool_res_gained = aggregate.get('pool_resources_gained', {})

    pcc = pool_card_counts.get(pool_id, {})
    card_counts = {}
    for cid, cnt in pcc.items():
        card_counts[cid] = card_counts.get(cid, 0) + cnt

    pseudo_compact = {
        'card_counts': card_counts,
        'total_draws': pool_draw_counts.get(pool_id, 0),
        'total_consumed': dict(pool_res_consumed.get(pool_id, {})),
        'total_gained': dict(pool_res_gained.get(pool_id, {})),
        'final_resources': dict(pool_res_gained.get(pool_id, {})),
        'pity_triggers': pool_pity_counts.get(pool_id, 0),
        'pool_card_counts': {pool_id: pcc},
        'pool_draw_counts': {pool_id: pool_draw_counts.get(pool_id, 0)},
        'pool_pity_counts': {pool_id: pool_pity_counts.get(pool_id, 0)},
    }

    try:
        return compute_gdr_from_compact(
            pseudo_compact, target_specs, gdr_key,
            ssr_ids=ssr_ids,
            weapon_character_map=weapon_character_map,
            **kwargs,
        )
    except Exception:
        return None
