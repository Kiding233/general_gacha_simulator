#!/usr/bin/env python3
"""
统一批量模拟模块

为 gacha_panel、strategy_panel、resource_search_panel 提供共享的并行批量模拟能力。
使用 multiprocessing.Pool + initializer 模式，静态环境通过 initializer 传入，
动态参数（target_specs, initial_resources）通过任务参数传入。
"""

import random
import traceback
from typing import List, Dict, Any, Optional, Callable
from multiprocessing import Pool as MPPool
from dataclasses import dataclass, field as dc_field

from gacha_simulator.core.stop_condition import StopCondition, AllPoolsEndCondition
from gacha_simulator.core.strategy import (
    STRATEGY_REGISTRY, create_strategy,
)


@dataclass
class SimulationEnv:
    pools: list
    schedule_mgr: Any
    end_time: float
    pity_engine: Any
    resource_gain: Any
    pity_state_init: Optional[dict]
    card_defs: list
    initial_resources: Dict[str, float]
    target_ids: set = dc_field(default_factory=set)
    ssr_ids: set = dc_field(default_factory=set)
    all_drawable_ids: list = dc_field(default_factory=list)
    pool_end_times: Dict[str, float] = dc_field(default_factory=dict)
    gdr_context: Any = None
    daily_income: float = 0.0


def _build_pity_engine_from_gui(pity_config, pools, pool_featured_map=None, pool_ssr_map=None, pool_type_map=None):
    from gacha_simulator.core.pity import (
        PityEngine, PityState, PoolPitySpec,
        PityDefParsed, SoftPityBehavior, HardPityBehavior,
    )
    if not pity_config.get('enabled', True):
        return None

    pities_cfg = pity_config.get('pities', [])

    pity_defs = {}
    behaviors = {}
    for p in pities_cfg:
        name = p.get('name', 'pity')
        btype = p.get('type', 'soft')
        target_dist = p.get('target_distribution', {})
        reset = p.get('reset', 'any_ssr')
        pools_pattern = p.get('pools', '*')
        params = p.get('params', {})

        pdef = PityDefParsed(
            name=name,
            btype=btype,
            params=params,
            target_distribution=target_dist,
            reset_condition=reset,
            pools=pools_pattern,
        )
        pity_defs[name] = pdef

        if btype == 'soft':
            behaviors[name] = SoftPityBehavior(
                start_at=int(params.get('start', '74')),
                end_at=int(params.get('end', '90')),
                func_type=params.get('func', 'linear'),
                target_distribution=target_dist,
            )
        elif btype == 'hard':
            behaviors[name] = HardPityBehavior(
                threshold=int(params.get('threshold', '90')),
                target_distribution=target_dist,
            )

    def _featured(pid, pool):
        if pool_featured_map and pid in pool_featured_map:
            return pool_featured_map[pid]
        featured = set()
        if pool.rewards:
            featured.add(pool.rewards[0][0].id)
        return featured

    def _ssr_all(pid, pool):
        if pool_ssr_map and pid in pool_ssr_map:
            return pool_ssr_map[pid]
        ssr_all = set()
        if pool.rewards:
            ssr_all.add(pool.rewards[0][0].id)
        return ssr_all

    def _resolve_targets(pool, featured_ids, ssr_ids, target_dist):
        if not target_dist:
            return {}
        sr_ids = set()
        r_ids = set()
        for r, prob in pool.rewards:
            rid = r.id
            if rid in ssr_ids:
                continue
            if prob <= 0.05:
                sr_ids.add(rid)
            else:
                r_ids.add(rid)

        resolved = {}
        for key, weight in target_dist.items():
            k = key.lower()
            if k == 'limited_ssr' or k == 'featured':
                for cid in featured_ids:
                    resolved[cid] = resolved.get(cid, 0) + weight
            elif k == 'standard_ssr' or k == 'offrate':
                for cid in (ssr_ids - featured_ids):
                    resolved[cid] = resolved.get(cid, 0) + weight
            elif k == 'ssr':
                for cid in ssr_ids:
                    resolved[cid] = resolved.get(cid, 0) + weight
            elif k == 'sr':
                for cid in sr_ids:
                    resolved[cid] = resolved.get(cid, 0) + weight
            elif k == 'r':
                for cid in r_ids:
                    resolved[cid] = resolved.get(cid, 0) + weight
            else:
                resolved[key] = resolved.get(key, 0) + weight
        return resolved

    pool_specs = {}
    import fnmatch
    for pool in pools:
        pid = pool.id
        featured = _featured(pid, pool)
        ssr_all = _ssr_all(pid, pool)

        matching = []
        resolved_per_pity = {}
        for pdef in pity_defs.values():
            if fnmatch.fnmatch(pid, pdef.pools):
                matching.append(pdef.name)
                if pdef.target_distribution:
                    resolved_per_pity[pdef.name] = _resolve_targets(
                        pool, featured, ssr_all, pdef.target_distribution)

        pool_specs[pid] = PoolPitySpec(
            pity_names=matching,
            featured_ids=featured,
            ssr_ids=ssr_all,
            resolved_targets=resolved_per_pity,
        )

    return PityEngine(pool_specs, pity_defs, behaviors)


# --- Worker 全局变量（每个子进程内共享）---
_wk_pools = None
_wk_schedule_mgr = None
_wk_end_time = None
_wk_pity_engine = None
_wk_resource_gain = None
_wk_pity_state_init = None
_wk_card_defs = None
_wk_strategy_name = 'smart'
_wk_strategy_params = {}
_wk_ssr_ids = set()
_wk_stop_condition = None


def _wk_init(
    pools,
    schedule_mgr,
    end_time,
    pity_engine,
    resource_gain,
    pity_state_init,
    card_defs,
    strategy_name,
    strategy_params,
    ssr_ids=None,
    stop_condition=None,
):
    global _wk_pools, _wk_schedule_mgr, _wk_end_time
    global _wk_pity_engine, _wk_resource_gain, _wk_pity_state_init, _wk_card_defs
    global _wk_strategy_name, _wk_strategy_params, _wk_ssr_ids, _wk_stop_condition
    _wk_pools = pools
    _wk_schedule_mgr = schedule_mgr
    _wk_end_time = end_time
    _wk_pity_engine = pity_engine
    _wk_resource_gain = resource_gain
    _wk_pity_state_init = pity_state_init
    _wk_card_defs = card_defs
    _wk_strategy_name = strategy_name
    _wk_strategy_params = strategy_params
    _wk_ssr_ids = ssr_ids or set()
    _wk_stop_condition = stop_condition


# --- 单次模拟执行 ---
def _wk_run_single(args) -> Optional[Dict[str, Any]]:
    """
    Worker 执行的单次模拟函数。
    args = (seed, target_specs, initial_resources)
    """
    seed, target_specs, initial_resources = args
    try:
        from gacha_simulator.core import GachaState, TargetCard, TargetCardSet
        from gacha_simulator.service import GachaService

        random.seed(seed)

        card_def_map = {c['card_id']: c for c in _wk_card_defs} if _wk_card_defs else {}
        targets = []
        for card_id, qty in target_specs.items():
            pools = card_def_map.get(card_id, {}).get('pools', [])
            targets.append(TargetCard(card_id=card_id, pool_ids=pools, quantity_needed=qty))

        target_set = TargetCardSet(targets)
        strategy = create_strategy(_wk_strategy_name, _wk_strategy_params)
        if _wk_stop_condition is not None:
            stop_cond = _wk_stop_condition
        else:
            stop_cond = AllPoolsEndCondition(_wk_end_time)

        pity_state = None
        if _wk_pity_state_init:
            from gacha_simulator.core.pity import PityState
            pity_state = PityState()
            counters = _wk_pity_state_init.get('counters', {})
            for cname, cval in counters.items():
                pity_state.counters[cname] = cval

        service = GachaService(
            _wk_pools, strategy, stop_cond, target_set,
            schedule_manager=_wk_schedule_mgr,
            pity_engine=_wk_pity_engine,
            resource_gain=_wk_resource_gain,
            pity_state=pity_state,
            ssr_ids=_wk_ssr_ids,
        )
        state = GachaState(resources=dict(initial_resources))
        return service.run_simulation_compact(state)
    except Exception:
        traceback.print_exc()
        return None


# --- 公共批量模拟接口 ---
def run_batch_parallel(
    pools,
    schedule_mgr,
    end_time,
    pity_engine,
    resource_gain,
    pity_state_init,
    card_defs,
    target_specs: Dict[str, int],
    initial_resources: Dict[str, float],
    num_simulations: int,
    max_workers: int,
    seed: int = 0,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    strategy_name: str = 'smart',
    strategy_params: Optional[dict] = None,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
    ssr_ids: Optional[set] = None,
    stop_condition=None,
) -> List[Optional[Dict[str, Any]]]:
    if max_workers <= 1:
        _wk_init(
            pools, schedule_mgr, end_time, pity_engine,
            resource_gain, pity_state_init, card_defs,
            strategy_name, strategy_params or {},
            ssr_ids=ssr_ids,
            stop_condition=stop_condition,
        )
        results = [] if on_result is None else None
        n_failed = 0
        for i in range(num_simulations):
            s = seed + i if seed >= 0 else random.randint(0, 999999)
            result = _wk_run_single((s, target_specs, initial_resources))
            if on_result is not None:
                if result is not None:
                    on_result(result)
                else:
                    n_failed += 1
            else:
                results.append(result)
            if progress_callback:
                progress_callback(i + 1, num_simulations)
        if n_failed > 0:
            print(f"[WARNING] {n_failed}/{num_simulations} simulations failed")
        return results if on_result is None else []

    seeds = [seed + i if seed >= 0 else random.randint(0, 999999) for i in range(num_simulations)]
    tasks = [(s, target_specs, initial_resources) for s in seeds]

    chunksize = max(1, num_simulations // (max_workers * 4))

    with MPPool(
        processes=max_workers,
        initializer=_wk_init,
        initargs=(pools, schedule_mgr, end_time, pity_engine, resource_gain, pity_state_init, card_defs, strategy_name, strategy_params or {}, ssr_ids, stop_condition),
    ) as mp_pool:
        results = [] if on_result is None else None
        n_failed = 0
        for i, result in enumerate(mp_pool.imap_unordered(_wk_run_single, tasks, chunksize=chunksize)):
            if on_result is not None:
                if result is not None:
                    on_result(result)
                else:
                    n_failed += 1
            else:
                results.append(result)
            if progress_callback:
                progress_callback(i + 1, num_simulations)
        if n_failed > 0:
            print(f"[WARNING] {n_failed}/{num_simulations} simulations failed")

    return results if on_result is None else []


class SimulationEnvBuilder:
    @staticmethod
    def from_config_store(config_store) -> SimulationEnv:
        from gacha_simulator.core.pool import Pool, Reward, parse_cost_string
        from gacha_simulator.core.schedule import PoolScheduleManager, PoolSchedule
        from gacha_simulator.core.resource_gain import (
            PeriodicResourceGain, ScheduleResourceGain, CompositeResourceGain,
        )

        DAY = 86400
        pool_entries = config_store.pools
        schedules = []
        pools = []
        pool_featured_map = {}
        pool_ssr_map = {}

        for pe in pool_entries:
            pid = pe.pool_id
            start_day = pe.start_day or 0
            end_day = pe.end_day if pe.end_day > start_day else (start_day + 21)

            rewards = []
            featured_ids = set()
            ssr_ids = set()
            for de in getattr(pe, 'distribution', []):
                rg = dict(getattr(de, 'resources_gained', {}) or {})
                rwd = Reward(id=de.card_id, name=getattr(de, 'card_id', ''), resources_gained=rg)
                rewards.append((rwd, de.probability / 100.0))
                if de.featured and de.card_id != '_no_card':
                    featured_ids.add(de.card_id)
                if de.rarity.upper() == 'SSR' and de.card_id != '_no_card':
                    ssr_ids.add(de.card_id)

            if not ssr_ids:
                _fallback_ssr_id = f"{pid}_ssr"
                ssr_ids = {_fallback_ssr_id}
                if not rewards:
                    rewards.append((Reward(id=_fallback_ssr_id, name='', resources_gained={}), 0.006))
            if not featured_ids:
                featured_ids = set(ssr_ids)

            pool_featured_map[pid] = featured_ids
            pool_ssr_map[pid] = ssr_ids

            cost_str = getattr(pe, 'cost', 'draw_resource:160')
            parsed_cost = parse_cost_string(cost_str) if cost_str else [{'draw_resource': 160}]
            exchange_cid = getattr(pe, 'exchange_card_id', None)
            pool = Pool(
                id=pid,
                name=getattr(pe, 'name', pid),
                cost=parsed_cost,
                rewards=rewards,
                available_from=start_day * DAY,
                available_until=end_day * DAY,
                is_exchange=bool(exchange_cid),
                exchange_card_id=exchange_cid,
            )
            pools.append(pool)
            schedules.append(PoolSchedule(
                pool_id=pid,
                available_from=start_day * DAY,
                available_until=end_day * DAY,
            ))

        schedule_mgr = PoolScheduleManager(schedules)
        end_time = max(s.available_until for s in schedules) if schedules else 0

        pity_cfg_dict = {'enabled': True, 'pities': []}
        pc = config_store.pity
        if pc and hasattr(pc, 'pities'):
            pity_cfg_dict['enabled'] = getattr(pc, 'enabled', True)
            for pd in pc.pities:
                pentry = {
                    'name': pd.name,
                    'type': getattr(pd, 'btype', 'soft'),
                    'params': dict(getattr(pd, 'params', {}) or {}),
                    'target_distribution': dict(getattr(pd, 'target_distribution', {}) or {}),
                    'reset': getattr(pd, 'reset_condition', 'any_ssr'),
                    'pools': getattr(pd, 'pools', '*'),
                }
                pity_cfg_dict['pities'].append(pentry)

        if hasattr(pc, 'counter_init') and pc.counter_init:
            pity_cfg_dict['counter_init'] = dict(pc.counter_init)

        pity_engine = _build_pity_engine_from_gui(
            pity_cfg_dict, pools, pool_featured_map, pool_ssr_map, {})

        initial_resources = {}
        ir_raw = config_store.initial_resources
        if isinstance(ir_raw, dict):
            initial_resources = dict(ir_raw)
        elif isinstance(ir_raw, list):
            for ir in ir_raw:
                rid = getattr(ir, 'resource_id', 'draw_resource')
                amt = getattr(ir, 'amount', 0)
                if amt > 0:
                    initial_resources[rid] = initial_resources.get(rid, 0) + float(amt)

        resource_gain = SimulationEnvBuilder._build_resource_gain(config_store, end_time)

        counter_init_cfg = pity_cfg_dict.get('counter_init', 0)
        pity_state_init = None
        init_counters = {}
        if isinstance(counter_init_cfg, int) and counter_init_cfg > 0 and pity_engine:
            for cname in pity_engine.pity_defs:
                init_counters[cname] = counter_init_cfg
        elif isinstance(counter_init_cfg, dict) and pity_engine:
            for k, v in counter_init_cfg.items():
                if v > 0 and k in pity_engine.pity_defs:
                    init_counters[k] = v
        if init_counters:
            pity_state_init = {'counters': init_counters}

        card_defs = []
        for cd in config_store.card_defs:
            card_defs.append({
                'card_id': cd.card_id,
                'name': getattr(cd, 'name', ''),
                'rarity': getattr(cd, 'rarity', 'r'),
                'pools': list(getattr(cd, 'pools', [])),
            })

        target_ids = set()
        for tc in getattr(config_store, 'target_cards', []):
            target_ids.add(tc.card_id)

        ssr_ids = set()
        for cd in config_store.card_defs:
            if getattr(cd, 'rarity', '').upper() == 'SSR':
                ssr_ids.add(cd.card_id)
        if not ssr_ids:
            for pid, ssr_set in pool_ssr_map.items():
                ssr_ids.update(ssr_set)

        all_drawable_ids = [r.id for p in pools for r, _ in p.rewards]
        pool_end_times = {s.pool_id: s.available_until for s in schedules}

        from gacha_simulator.core.gdr import GDRContext
        target_specs = {tc.card_id: getattr(tc, 'quantity', 1) for tc in getattr(config_store, 'target_cards', [])}
        gdr_context = GDRContext(
            target_specs=target_specs,
            ssr_ids=ssr_ids,
            all_drawable_ids=all_drawable_ids,
            initial_resources=dict(initial_resources),
            resource_gain_per_day={'draw_resource': 0},
        )

        return SimulationEnv(
            pools=pools,
            schedule_mgr=schedule_mgr,
            end_time=end_time,
            pity_engine=pity_engine,
            resource_gain=resource_gain,
            pity_state_init=pity_state_init,
            card_defs=card_defs,
            initial_resources=initial_resources,
            target_ids=target_ids,
            ssr_ids=ssr_ids,
            all_drawable_ids=all_drawable_ids,
            pool_end_times=pool_end_times,
            gdr_context=gdr_context,
        )

    @staticmethod
    def _build_resource_gain(config_store, end_time):
        from gacha_simulator.core.resource_gain import (
            PeriodicResourceGain, ScheduleResourceGain, CompositeResourceGain,
        )
        gain_functions = []
        schedule = {}
        total_days = int(end_time / 86400) + 1 if end_time else 30

        for rule in getattr(config_store, 'gain_rules', []):
            rule_type = getattr(rule, 'rule_type', 'every_n_days')
            param = getattr(rule, 'param', '1')
            gains = getattr(rule, 'gains', {}) or {}
            for rid, amount in gains.items():
                amount = float(amount)
                if amount <= 0:
                    continue
                if rule_type.startswith('every_n_days'):
                    n_part = rule_type.split(':', 1)[1] if ':' in rule_type else param
                    n = int(n_part) if n_part else 1
                    for day in range(0, total_days, n):
                        if day not in schedule:
                            schedule[day] = {}
                        schedule[day][rid] = schedule[day].get(rid, 0) + amount
                elif rule_type.startswith('weekly'):
                    import datetime
                    wday_part = rule_type.split(':', 1)[1] if ':' in rule_type else param
                    target_wday = int(wday_part) if wday_part else 1
                    for day in range(total_days):
                        try:
                            d = datetime.date.fromordinal(day + 735000)
                            if d.isoweekday() == target_wday:
                                if day not in schedule:
                                    schedule[day] = {}
                                schedule[day][rid] = schedule[day].get(rid, 0) + amount
                        except Exception:
                            pass
                elif rule_type.startswith('monthly_day:'):
                    target_day = int(rule_type.split(':', 1)[1]) if ':' in rule_type else 1
                    for month_start in range(0, total_days, 30):
                        day = month_start + target_day - 1
                        if 0 <= day < total_days:
                            if day not in schedule:
                                schedule[day] = {}
                            schedule[day][rid] = schedule[day].get(rid, 0) + amount
                elif rule_type.startswith('monthly_week:'):
                    week_param = rule_type.split(':', 1)[1] if ':' in rule_type else '1-1'
                    parts = week_param.split('-')
                    week_num = int(parts[0]) if len(parts) >= 1 and parts[0] else 1
                    wday = int(parts[1]) if len(parts) >= 2 and parts[1] else 1
                    import datetime
                    for month_start in range(0, total_days, 30):
                        for d_offset in range(30):
                            day = month_start + d_offset
                            if day >= total_days:
                                break
                            try:
                                dt = datetime.date.fromordinal(day + 735000)
                                if dt.isoweekday() == wday:
                                    week_of_month = (d_offset // 7) + 1
                                    if week_of_month == week_num:
                                        if day not in schedule:
                                            schedule[day] = {}
                                        schedule[day][rid] = schedule[day].get(rid, 0) + amount
                            except Exception:
                                pass

        for override in getattr(config_store, 'day_overrides', []):
            day = getattr(override, 'day', 0)
            gains = getattr(override, 'gains', {}) or {}
            for rid, amount in gains.items():
                amount = float(amount)
                if amount > 0 and 0 <= day < total_days:
                    if day not in schedule:
                        schedule[day] = {}
                    schedule[day][rid] = schedule[day].get(rid, 0) + amount

        if schedule:
            gain_functions.append(ScheduleResourceGain(schedule, total_days))

        if gain_functions:
            if len(gain_functions) == 1:
                return gain_functions[0]
            return CompositeResourceGain(gain_functions)
        return None
