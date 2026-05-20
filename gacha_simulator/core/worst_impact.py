from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, List, Set, Optional
from collections import defaultdict

from .distribution import EmpiricalDistribution
from .pool import Pool, Reward, parse_cost_string
from .pity import (
    PityEngine, PityState, PoolPitySpec, PityDefParsed,
    SoftPityBehavior, HardPityBehavior,
)
from .action import DrawAction, WaitAction
from .target_card import TargetCard, TargetCardSet
from .stop_condition import StopCondition, AllPoolsEndCondition, ConsecutivePoolTargetCondition
from .strategy import Strategy, StrategyContext, STRATEGY_REGISTRY
from .schedule import PoolSchedule, PoolScheduleManager

import fnmatch


DAY = 86400
MAX_POOLS = 99


class ConditionalResourceDistribution:
    def __init__(self, simulation_results, success_checker,
                 resource='draw_resource'):
        self.success_resources: List[float] = []
        self.failure_resources: List[float] = []

        for r in simulation_results:
            is_success = success_checker(r)
            final_res = r.get('final_resources', {})
            res_val = final_res.get(resource, 0.0)

            if is_success:
                self.success_resources.append(res_val)
            else:
                self.failure_resources.append(res_val)

    def get_conditional_distribution(self, condition='all'):
        if condition == 'success':
            samples = self.success_resources
        elif condition == 'failure':
            samples = self.failure_resources
        else:
            samples = self.success_resources + self.failure_resources
        return EmpiricalDistribution(samples)

    def get_worst_case_resource(self, condition='all', alpha=0.05):
        dist = self.get_conditional_distribution(condition)
        return dist.quantile(alpha)


@dataclass
class WorstImpactResult:
    worst_resource: float
    pity_coverage: float
    pool_distribution: Dict[int, float] = field(default_factory=dict)
    expected_pools: float = 0.0

    def get_p_ge(self, k: int) -> float:
        return sum(p for kk, p in self.pool_distribution.items() if kk >= k)

    def get_max_consecutive_at_threshold(self, threshold: float) -> int:
        for k in sorted(self.pool_distribution.keys(), reverse=True):
            if self.get_p_ge(k) >= threshold:
                return k
        return 0


class DrawTargetStrategy(Strategy):
    lookahead = None

    def __init__(self, target_card_ids: Set[str], pool_id: str,
                 quantity_needed: int = 1):
        self.target_card_ids = target_card_ids
        self.pool_id = pool_id
        self.quantity_needed = quantity_needed

    @classmethod
    def description(cls) -> str:
        return "最差影响分析：从目标池抽卡，抽到后等待下一池"

    def select_action(self, ctx: StrategyContext):
        for cid in self.target_card_ids:
            if ctx.acquired.get(cid, 0) < self.quantity_needed:
                break
        else:
            wait_time = 86400
            for pool in ctx.current_pools:
                if (pool.available_until is not None
                        and pool.available_until > ctx.state.real_time
                        and pool.id != self.pool_id):
                    wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
            if wait_time <= 0 or wait_time == 86400:
                wait_time = 3600
            return WaitAction(duration=wait_time)

        for pool in ctx.current_pools:
            if pool.id == self.pool_id and ctx.state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in ctx.current_pools:
            if (pool.available_until is not None
                    and pool.available_until > ctx.state.real_time):
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


STRATEGY_REGISTRY['draw_target']['class'] = DrawTargetStrategy


class SequentialDrawTargetStrategy(Strategy):
    lookahead = None

    def __init__(self, pool_targets: Dict[str, str], quantity_needed: int = 1):
        self.pool_targets = pool_targets
        self.quantity_needed = quantity_needed

    @classmethod
    def description(cls) -> str:
        return "最差影响分析：顺序抽取每池目标卡，抽到后等待下一池"

    def select_action(self, ctx: StrategyContext):
        for pool in ctx.current_pools:
            target_cid = self.pool_targets.get(pool.id)
            if target_cid is None:
                continue
            if ctx.acquired.get(target_cid, 0) < self.quantity_needed:
                if ctx.state.can_afford(pool.cost):
                    return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in ctx.current_pools:
            if (pool.available_until is not None
                    and pool.available_until > ctx.state.real_time):
                wait_time = min(wait_time, pool.available_until - ctx.state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)


STRATEGY_REGISTRY['sequential_draw_target'] = {
    'display_name': '顺序池目标策略',
    'description': '最差影响分析专用：按池子顺序抽取目标卡',
    'class': SequentialDrawTargetStrategy,
    'internal': True,
}


class WorstImpactAnalyzer:
    def __init__(self, simulation_results, target_specs, store,
                 gdr_key='all_targets', gdr_threshold=1.0,
                 custom_pool_config=None,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None):
        self.simulation_results = simulation_results
        self.target_specs = target_specs
        self.store = store
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.custom_pool_config = custom_pool_config
        self.desire_weights = desire_weights or {}
        self.miss_cost_weights = miss_cost_weights or {}
        self.card_value_weights = card_value_weights or {}
        self.cond_dist = None
        self._pity_engine = None
        self._ref_pool_entry = None
        self._featured_ids: Set[str] = set()
        self._ssr_ids: Set[str] = set()
        self._standard_ssr_ids: Set[str] = set()
        self._featured_prob: float = 0.0
        self._pool_duration = 21 * DAY
        self._parsed_cost = [{'draw_resource': 160}]
        self._rewards = []
        self._main_ssr_ids: Set[str] = set()
        for cd in store.card_defs:
            if getattr(cd, 'rarity', '').upper() == 'SSR':
                self._main_ssr_ids.add(cd.card_id)
        if not self._main_ssr_ids:
            for pe in store.pools:
                for de in getattr(pe, 'distribution', []):
                    if getattr(de, 'rarity', '').upper() == 'SSR' and de.card_id != '_no_card':
                        self._main_ssr_ids.add(de.card_id)

    def analyze(self, condition='failure', alpha=0.05,
                num_simulations=500, progress_callback=None):
        self._prepare_pool_info()

        main_checker = self._build_success_checker(
            target_specs=self.target_specs,
            ssr_ids=self._main_ssr_ids,
        )

        self.cond_dist = ConditionalResourceDistribution(
            self.simulation_results, main_checker.is_success
        )

        worst_resource = self.cond_dist.get_worst_case_resource(condition, alpha)
        pity_coverage = self._compute_pity_coverage(worst_resource)

        result = self._compute_pool_distribution(
            worst_resource, num_simulations, progress_callback
        )

        return WorstImpactResult(
            worst_resource=worst_resource,
            pity_coverage=pity_coverage,
            pool_distribution=result['distribution'],
            expected_pools=result['expected'],
        )

    def prepare_simulation_config(self, worst_resource: float, pool_index: int = 0) -> dict:
        self._prepare_pool_info()

        i = pool_index
        pid = f'_worst_impact_pool_{i}'
        featured_id = f'_wi_featured_{i}'

        new_rewards = []
        for r, prob in self._rewards:
            if r.id in self._featured_ids:
                new_r = Reward(
                    id=featured_id,
                    name=f'限定#{i}',
                    resources_gained=dict(r.resources_gained) if r.resources_gained else {},
                    extra_info=dict(r.extra_info) if r.extra_info else {},
                )
                new_rewards.append((new_r, prob))
            else:
                new_rewards.append((r, prob))

        start_time = 0
        end_time = self._pool_duration

        pool = Pool(
            id=pid,
            name=f'新池子#{i}',
            cost=self._parsed_cost,
            rewards=new_rewards,
            available_from=start_time,
            available_until=end_time,
        )

        schedule = PoolSchedule(
            pool_id=pid,
            available_from=start_time,
            available_until=end_time,
        )
        schedule_mgr = PoolScheduleManager([schedule])

        pool_ssr_ids = {featured_id} | self._standard_ssr_ids

        card_defs = [{
            'card_id': featured_id,
            'name': f'限定#{i}',
            'rarity': 'SSR',
            'pools': [pid],
        }]
        for r, prob in self._rewards:
            if r.id not in self._featured_ids:
                rarity = r.extra_info.get('rarity', '').upper()
                card_defs.append({
                    'card_id': r.id,
                    'name': r.name or r.id,
                    'rarity': rarity,
                    'pools': [pid],
                })
                if rarity == 'SSR':
                    pool_ssr_ids.add(r.id)

        target_specs = {featured_id: 1}

        pity_engine = self._build_single_pool_pity_engine(pool_index, featured_id, pool_ssr_ids)

        pity_state_init = None
        init_pity = self._get_initial_pity_state()
        if init_pity:
            pity_state_init = {'counters': init_pity}

        strategy = DrawTargetStrategy(
            target_card_ids={featured_id},
            pool_id=pid,
            quantity_needed=1,
        )

        return {
            'pools': [pool],
            'schedule_mgr': schedule_mgr,
            'end_time': end_time,
            'pity_engine': pity_engine,
            'resource_gain': None,
            'pity_state_init': pity_state_init,
            'card_defs': card_defs,
            'target_specs': target_specs,
            'initial_resources': {'draw_resource': worst_resource},
            'ssr_ids': pool_ssr_ids,
            'stop_condition': AllPoolsEndCondition(end_time),
            'strategy': strategy,
            'featured_id': featured_id,
        }

    def _compute_pool_distribution(self, resource, num_simulations, progress_callback=None):
        success_counts = defaultdict(int)
        total_steps = num_simulations
        max_pools = MAX_POOLS

        from gacha_simulator.service.batch_simulator import run_batch_parallel
        from .streaming import SharedResultCollector, extract_aggregate

        current_resource = resource
        pity_state = self._get_initial_pity_state()

        for pool_index in range(max_pools):
            sim_cfg = self.prepare_simulation_config(current_resource, pool_index)
            featured_id = sim_cfg['featured_id']

            collector = SharedResultCollector()
            collector.add_extractor('aggregate', extract_aggregate)

            run_batch_parallel(
                pools=sim_cfg['pools'],
                schedule_mgr=sim_cfg['schedule_mgr'],
                end_time=sim_cfg['end_time'],
                pity_engine=sim_cfg['pity_engine'],
                resource_gain=sim_cfg.get('resource_gain'),
                pity_state_init=sim_cfg.get('pity_state_init'),
                card_defs=sim_cfg['card_defs'],
                target_specs=sim_cfg['target_specs'],
                initial_resources=sim_cfg['initial_resources'],
                num_simulations=num_simulations,
                max_workers=1,
                seed=42 + pool_index,
                progress_callback=lambda done, total, pi=pool_index: progress_callback(
                    f"池{pi+1}: {done}/{total}", int((pi * num_simulations + done) / (max_pools * num_simulations) * 100)
                ) if progress_callback else None,
                on_result=collector.on_result,
                ssr_ids=sim_cfg['ssr_ids'],
                stop_condition=sim_cfg['stop_condition'],
                strategy=sim_cfg['strategy'],
            )

            aggregate_data = collector.get_extracted('aggregate')
            n_success = 0
            total_remaining = 0.0
            n_with_results = len(aggregate_data)

            for result in aggregate_data:
                card_counts = result.get('card_counts', {})
                if card_counts.get(featured_id, 0) >= 1:
                    n_success += 1
                remaining = result.get('final_resources', {}).get('draw_resource', 0)
                total_remaining += remaining

            success_rate = n_success / max(n_with_results, 1)

            if progress_callback:
                pct = int((pool_index + 1) / max_pools * 100)
                progress_callback(f"池{pool_index+1}完成: 成功率={success_rate:.1%}", pct)

            if success_rate <= 0:
                break

            avg_remaining = total_remaining / max(n_success, 1)
            current_resource = avg_remaining

            for sim_idx in range(num_simulations):
                if sim_idx < n_success:
                    pass
                else:
                    break
            else:
                pass

            for _ in range(n_success):
                pass

            for _ in range(num_simulations - n_success):
                pass

        for sim_idx in range(num_simulations):
            pass

        distribution = {k: count / num_simulations for k, count in sorted(success_counts.items())}
        expected = sum(k * prob for k, prob in distribution.items())

        return {'distribution': distribution, 'expected': expected}

    def _compute_pity_coverage(self, resource):
        pity_cost = self._get_pity_cost()
        return resource / pity_cost if pity_cost > 0 else float('inf')

    def _build_success_checker(self, target_specs=None, ssr_ids=None):
        from .gdr import SuccessChecker
        self._checker = SuccessChecker(
            target_specs=target_specs or self.target_specs,
            gdr_key=self.gdr_key,
            gdr_threshold=self.gdr_threshold,
            desire_weights=self.desire_weights,
            miss_cost_weights=self.miss_cost_weights,
            card_value_weights=self.card_value_weights,
            ssr_ids=ssr_ids or self._ssr_ids,
        )
        return self._checker

    def _get_pity_cost(self):
        if not self.store.pity.enabled or not self.store.pity.pities:
            return 90 * 160
        p = self.store.pity.pities[0]
        params = p.params if isinstance(p.params, dict) else {}
        end = int(params.get('end', '90'))
        cost = 160
        if self.store.pools:
            c = self.store.pools[0].cost
            if isinstance(c, str) and ':' in c:
                try:
                    cost = int(c.split(':')[1])
                except ValueError:
                    pass
        return end * cost

    def _prepare_pool_info(self):
        if self.custom_pool_config and self.custom_pool_config.get('distribution'):
            self._apply_custom_pool_config()
            return

        pool_entries = [pe for pe in self.store.pools if pe.enabled]
        if not pool_entries:
            return

        self._ref_pool_entry = pool_entries[-1]
        pe = self._ref_pool_entry

        cost_str = getattr(pe, 'cost', 'draw_resource:160')
        self._parsed_cost = parse_cost_string(cost_str)

        rewards = []
        if pe.distribution:
            for de in pe.distribution:
                r = Reward(
                    id=de.card_id,
                    name='',
                    resources_gained=dict(de.resources_gained) if de.resources_gained else {},
                    extra_info={'rarity': de.rarity, 'featured': de.featured},
                )
                prob = de.probability
                rewards.append((r, prob))

        self._featured_ids = set()
        self._ssr_ids = set()
        self._featured_prob = 0.0
        for r, prob in rewards:
            rarity = r.extra_info.get('rarity', '').upper()
            featured = r.extra_info.get('featured', False)
            if rarity == 'SSR':
                self._ssr_ids.add(r.id)
                if featured:
                    self._featured_ids.add(r.id)
                    self._featured_prob += prob

        if not self._featured_ids and self._ssr_ids:
            self._featured_ids = set(self._ssr_ids)
            self._featured_prob = sum(
                prob for r, prob in rewards
                if r.id in self._ssr_ids
            )

        self._standard_ssr_ids = self._ssr_ids - self._featured_ids

        pool_duration_days = pe.end_day - pe.start_day
        if pool_duration_days <= 0:
            pool_duration_days = 21

        self._pool_duration = pool_duration_days * DAY
        self._rewards = rewards

    def _apply_custom_pool_config(self):
        cfg = self.custom_pool_config
        duration_days = cfg.get('duration_days', 21)
        self._pool_duration = duration_days * DAY

        cost_str = cfg.get('cost', 'draw_resource:160')
        self._parsed_cost = parse_cost_string(cost_str)

        rewards = []
        for d in cfg.get('distribution', []):
            r = Reward(
                id=d.get('card_id', ''),
                name='',
                resources_gained=d.get('resources_gained', {}),
                extra_info={'rarity': d.get('rarity', 'R'), 'featured': d.get('featured', False)},
            )
            rewards.append((r, d.get('probability', 0.0)))

        self._featured_ids = set()
        self._ssr_ids = set()
        self._featured_prob = 0.0
        for r, prob in rewards:
            rarity = r.extra_info.get('rarity', '').upper()
            featured = r.extra_info.get('featured', False)
            if rarity == 'SSR':
                self._ssr_ids.add(r.id)
                if featured:
                    self._featured_ids.add(r.id)
                    self._featured_prob += prob

        if not self._featured_ids and self._ssr_ids:
            self._featured_ids = set(self._ssr_ids)
            self._featured_prob = sum(
                prob for r, prob in rewards
                if r.id in self._ssr_ids
            )

        self._standard_ssr_ids = self._ssr_ids - self._featured_ids
        self._rewards = rewards

    def _build_pity_engine(self, all_featured_ids=None, all_ssr_ids=None, pool_targets=None):
        if not self.store.pity.enabled:
            return None

        pity_defs: Dict[str, PityDefParsed] = {}
        behaviors = {}
        for pd in self.store.pity.pities:
            params = pd.params if isinstance(pd.params, dict) else {}
            target_dist = pd.target_distribution if isinstance(pd.target_distribution, dict) else {}
            name = pd.name
            btype = getattr(pd, 'btype', 'soft')
            reset = getattr(pd, 'reset_condition', 'any_ssr')
            pools_pattern = getattr(pd, 'pools', '*')

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

        pool_specs = {}
        for pool_idx in range(MAX_POOLS):
            pid = f'_worst_impact_pool_{pool_idx}'
            matching = []
            resolved_per_pity = {}
            for pdef in pity_defs.values():
                if fnmatch.fnmatch(pid, pdef.pools):
                    matching.append(pdef.name)
                    if pdef.target_distribution:
                        resolved_per_pity[pdef.name] = self._resolve_targets_for_pool(
                            pdef.target_distribution, pool_idx,
                            all_featured_ids, all_ssr_ids, pool_targets,
                        )

            pool_featured = {f'_wi_featured_{pool_idx}'} if all_featured_ids else self._featured_ids
            pool_ssr = (pool_featured | self._standard_ssr_ids) if all_ssr_ids else self._ssr_ids

            pool_specs[pid] = PoolPitySpec(
                pity_names=matching,
                featured_ids=pool_featured,
                ssr_ids=pool_ssr,
                resolved_targets=resolved_per_pity,
            )

        return PityEngine(pool_specs, pity_defs, behaviors)

    def _resolve_targets_for_pool(self, target_dist, pool_idx,
                                   all_featured_ids, all_ssr_ids, pool_targets):
        if not target_dist:
            return {}
        featured_id = f'_wi_featured_{pool_idx}'
        pool_ssr = {featured_id} | self._standard_ssr_ids

        resolved = {}
        for key, weight in target_dist.items():
            k = key.lower()
            if k in ('limited_ssr', 'featured'):
                resolved[featured_id] = resolved.get(featured_id, 0) + weight
            elif k in ('standard_ssr', 'offrate'):
                for cid in self._standard_ssr_ids:
                    resolved[cid] = resolved.get(cid, 0) + weight
            elif k == 'ssr':
                for cid in pool_ssr:
                    resolved[cid] = resolved.get(cid, 0) + weight
            else:
                resolved[key] = resolved.get(key, 0) + weight
        return resolved

    def _resolve_targets(self, target_dist):
        resolved = {}
        for key, weight in target_dist.items():
            k = key.lower()
            if k in ('limited_ssr', 'featured'):
                for cid in self._featured_ids:
                    resolved[cid] = resolved.get(cid, 0) + weight
            elif k in ('standard_ssr', 'offrate'):
                for cid in (self._ssr_ids - self._featured_ids):
                    resolved[cid] = resolved.get(cid, 0) + weight
            elif k == 'ssr':
                for cid in self._ssr_ids:
                    resolved[cid] = resolved.get(cid, 0) + weight
            else:
                resolved[key] = resolved.get(key, 0) + weight
        return resolved

    def _get_initial_pity_state(self):
        if not self.store.pity.enabled:
            return {}
        state = {}
        counter_init = getattr(self.store.pity, 'counter_init', {})
        if isinstance(counter_init, dict):
            for k, v in counter_init.items():
                if v > 0:
                    state[k] = v
        elif isinstance(counter_init, int) and counter_init > 0:
            for p in self.store.pity.pities:
                state[p.name] = counter_init
        return state
