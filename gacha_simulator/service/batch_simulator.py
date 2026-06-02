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


class BatchResult:
    """批量模拟结果容器——向后兼容 list 接口，同时携带 worker 提取数据。"""

    __slots__ = ('results', 'extraction')

    def __init__(self, results, extraction=None):
        self.results = results if results is not None else []
        self.extraction = extraction

    def __getitem__(self, i):
        return self.results[i]

    def __len__(self):
        return len(self.results)

    def __iter__(self):
        return iter(self.results)

    def __bool__(self):
        return bool(self.results)

    def __repr__(self):
        return f"BatchResult(n={len(self.results)}, extraction={'yes' if self.extraction else 'no'})"


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
    strategy_name: str = 'smart'
    strategy_params: Dict[str, Any] = dc_field(default_factory=dict)
    stop_condition: Any = None
    return_compact: bool = True


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
_wk_env: Optional[SimulationEnv] = None
_wk_target_set = None
_wk_extractor = None
_wk_return_compact = True


def _wk_init(env: SimulationEnv, target_specs: Dict[str, int] = None):
    """子进程 initializer——将 SimulationEnv 注入子进程全局变量，预构建不可变数据。"""
    global _wk_env, _wk_target_set, _wk_extractor, _wk_return_compact
    _wk_env = env
    _wk_return_compact = getattr(env, 'return_compact', True)

    # 预导入模拟核心模块，消除首次 _run_single 调用的懒加载开销。
    # 在 Windows spawn 模式下，每个 worker 是全新 Python 进程，
    # 首次 import GachaState/GachaService 合计约 200-500ms。
    import gacha_simulator.core as _core  # noqa: F401
    import gacha_simulator.service as _svc  # noqa: F401

    if target_specs:
        from gacha_simulator.core import TargetCard, TargetCardSet
        card_def_map = {c['card_id']: c for c in env.card_defs} if env.card_defs else {}
        targets = []
        for card_id, qty in target_specs.items():
            pools = card_def_map.get(card_id, {}).get('pools', [])
            targets.append(TargetCard(card_id=card_id, pool_ids=pools, quantity_needed=qty))
        _wk_target_set = TargetCardSet(targets)
    else:
        from gacha_simulator.core import TargetCardSet
        _wk_target_set = TargetCardSet([])

    # 预构建 WorkerLocalExtractor（每个 worker 一份，并行提取）
    from gacha_simulator.core.streaming import WorkerLocalExtractor
    _wk_extractor = WorkerLocalExtractor(
        pool_end_times=env.pool_end_times,
        target_ids=env.target_ids,
        ssr_ids=env.ssr_ids,
        target_specs=target_specs or {},
        initial_resources=env.initial_resources,
        n_heatmap_bins=getattr(env, 'n_heatmap_bins', 50),
        max_keep=min(200, max(10, len(target_specs or {}) * 2 + 10)),
    )


# --- 单次模拟执行（纯函数，不依赖全局变量）---
def _run_single(env: SimulationEnv, target_set, seed: int, initial_resources: Dict[str, float]) -> Optional[Dict[str, Any]]:
    """执行一次模拟。env 和 target_set 通过参数显式传入，不依赖全局变量。"""
    from gacha_simulator.core import GachaState
    from gacha_simulator.service import GachaService

    random.seed(seed)

    strategy = create_strategy(env.strategy_name, env.strategy_params)
    if env.stop_condition is not None:
        stop_cond = env.stop_condition
    else:
        stop_cond = AllPoolsEndCondition(env.end_time)

    pity_state = None
    if env.pity_state_init:
        from gacha_simulator.core.pity import PityState
        pity_state = PityState()
        counters = env.pity_state_init.get('counters', {})
        for cname, cval in counters.items():
            pity_state.counters[cname] = cval

    service = GachaService(
        env.pools, strategy, stop_cond, target_set,
        schedule_manager=env.schedule_mgr,
        pity_engine=env.pity_engine,
        resource_gain=env.resource_gain,
        pity_state=pity_state,
        ssr_ids=env.ssr_ids,
        card_defs=env.card_defs,
    )
    state = GachaState(resources=dict(initial_resources))
    return service.run_simulation_compact(state)


def _wk_run_single(args):
    """子进程 worker 入口——模拟 + 本地提取。

    return_compact=True（默认）时返回 (compact, extraction) 元组以兼容 on_result 回调。
    return_compact=False 时只返回 extraction，节省 pickle 传输开销。
    """
    seed, initial_resources = args
    try:
        compact = _run_single(_wk_env, _wk_target_set, seed, initial_resources)
    except Exception:
        traceback.print_exc()
        return (None, None) if _wk_return_compact else None

    if compact is None:
        return (None, None) if _wk_return_compact else None

    extraction = None
    if _wk_extractor is not None:
        try:
            extraction = _wk_extractor.process(compact)
        except Exception:
            traceback.print_exc()

    if _wk_return_compact:
        return (compact, extraction)
    return extraction


# --- 公共批量模拟接口 ---
def run_batch_parallel(
    env: SimulationEnv,
    target_specs: Dict[str, int],
    initial_resources: Dict[str, float],
    num_simulations: int,
    max_workers: int,
    seed: int = 0,
    progress_callback: Optional[Callable[[int, int], None]] = None,
    strategy_name: str = '',
    strategy_params: Optional[dict] = None,
    on_result: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> List[Optional[Dict[str, Any]]]:
    """批量并行模拟。

    env: 模拟环境（池、保底、资源等静态配置）。
    target_specs / initial_resources: 每次模拟的动态参数。
    strategy_name / strategy_params: 可为空，为空时使用 env 中的默认值。
    """
    if strategy_name:
        env.strategy_name = strategy_name
    if strategy_params is not None:
        env.strategy_params = strategy_params

    # 构建 TargetCardSet（单/多进程共用）
    if target_specs:
        from gacha_simulator.core import TargetCard, TargetCardSet
        card_def_map = {c['card_id']: c for c in env.card_defs} if env.card_defs else {}
        targets = []
        for card_id, qty in target_specs.items():
            pools = card_def_map.get(card_id, {}).get('pools', [])
            targets.append(TargetCard(card_id=card_id, pool_ids=pools, quantity_needed=qty))
        target_set = TargetCardSet(targets)
    else:
        from gacha_simulator.core import TargetCardSet
        target_set = TargetCardSet([])

    if max_workers <= 1:
        # 单进程路径：直接调用 _run_single，不污染全局变量
        results = [] if on_result is None else None
        n_failed = 0
        for i in range(num_simulations):
            s = seed + i if seed >= 0 else random.randint(0, 999999)
            try:
                result = _run_single(env, target_set, s, initial_resources)
            except Exception:
                traceback.print_exc()
                result = None
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
        return BatchResult(results if on_result is None else [], None)

    seeds = [seed + i if seed >= 0 else random.randint(0, 999999) for i in range(num_simulations)]
    tasks = [(s, initial_resources) for s in seeds]

    # 降低 chunksize 以加快首次进度回调。
    # 原公式 max(1, N/(W*4)) 对 N=1000/W=18 给出 14，首次进度需等 14 次模拟完成。
    # 改为 divisor=16 后，chunksize≈4，首次进度约 1 秒内出现，同时保持合理 IPC 效率。
    chunksize = max(1, num_simulations // (max_workers * 16))

    with MPPool(
        processes=max_workers,
        initializer=_wk_init,
        initargs=(env, target_specs),
    ) as mp_pool:
        results = [] if on_result is None else None
        extraction_packets = []
        n_failed = 0
        for i, result in enumerate(mp_pool.imap_unordered(_wk_run_single, tasks, chunksize=chunksize)):
            # 解包 worker 返回值：
            # - tuple (compact, extraction)：return_compact=True 路径（兼容 on_result 回调）
            # - 非 tuple：return_compact=False 路径，直接是 extraction_packet
            if isinstance(result, tuple) and len(result) == 2:
                compact, ext_pkt = result
            else:
                compact = None
                ext_pkt = result

            if on_result is not None:
                if compact is not None:
                    on_result(compact)
                else:
                    n_failed += 1
            elif compact is not None:
                results.append(compact)

            if ext_pkt is not None:
                extraction_packets.append(ext_pkt)

            if progress_callback:
                progress_callback(i + 1, num_simulations)
        if n_failed > 0:
            print(f"[WARNING] {n_failed}/{num_simulations} simulations failed")

    # 合并 worker 提取结果
    merged_extraction = None
    if extraction_packets:
        from gacha_simulator.core.streaming import merge_extraction_packets
        n_heatmap_bins = getattr(env, 'n_heatmap_bins', 50)
        merged_extraction = merge_extraction_packets(
            extraction_packets,
            heatmap_config={'n_heatmap_bins': n_heatmap_bins, 'max_keep': 200},
        )

    raw_results = results if on_result is None else []
    return BatchResult(raw_results, merged_extraction)


class SimulationEnvBuilder:
    @staticmethod
    def _infer_pool_type(pool_id: str, pool_type: str = '') -> str:
        """根据 pool_id 推断池子类型：角色/武器/兑换/资源。"""
        if pool_type and pool_type in ('角色', '武器', '兑换', '资源'):
            return pool_type
        pid = pool_id.lower()
        if '武器' in pid or 'weapon' in pid or pid.startswith('pool_w'):
            return '武器'
        if '兑换' in pid or 'exchange' in pid or pid.startswith('pool_e'):
            return '兑换'
        if '资源' in pid or 'resource' in pid:
            return '资源'
        return pool_type or '角色'

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
                ft = dict(getattr(de, 'first_time_bonus', {}) or {})
                nth = dict(getattr(de, 'nth_time_bonus', {}) or {})
                xs = dict(getattr(de, 'excess_bonus', {}) or {})
                rwd = Reward(id=de.card_id, name=getattr(de, 'card_id', ''),
                             resources_gained=rg, first_time_bonus=ft,
                             nth_time_bonus=nth, excess_bonus=xs)
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
            ptype = getattr(pe, 'pool_type', '') or SimulationEnvBuilder._infer_pool_type(pid, '')
            pool = Pool(
                id=pid,
                name=getattr(pe, 'name', pid),
                cost=parsed_cost,
                rewards=rewards,
                available_from=start_day * DAY,
                available_until=end_day * DAY,
                is_exchange=bool(exchange_cid),
                exchange_card_id=exchange_cid,
                pool_type=ptype,
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
                'initial_count': getattr(cd, 'initial_count', 0),
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

        strategy_name = getattr(config_store, 'strategy_name', 'smart') or 'smart'
        strategy_params = dict(getattr(config_store, 'strategy_params', {}) or {})

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
            strategy_name=strategy_name,
            strategy_params=strategy_params,
        )

    @staticmethod
    def from_dict(config: dict) -> 'SimulationEnv':
        """从字典构造 SimulationEnv（供 worst_impact.py 等不使用 ConfigStore 的调用方使用）。"""
        return SimulationEnv(
            pools=config['pools'],
            schedule_mgr=config['schedule_mgr'],
            end_time=config['end_time'],
            pity_engine=config['pity_engine'],
            resource_gain=config.get('resource_gain'),
            pity_state_init=config.get('pity_state_init'),
            card_defs=config['card_defs'],
            initial_resources=config.get('initial_resources', {}),
            ssr_ids=config.get('ssr_ids', set()),
            strategy_name=config.get('strategy_name', 'smart'),
            strategy_params=config.get('strategy_params', {}),
            stop_condition=config.get('stop_condition'),
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
