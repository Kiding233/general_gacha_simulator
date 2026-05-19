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
from .state import GachaState
from .action import DrawAction, WaitAction
from .target_card import TargetCard, TargetCardSet
from .stop_condition import StopCondition
from .strategy import Strategy
from ..service.gacha_service import GachaService

import fnmatch


DAY = 86400



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


class _TargetPoolEnd(StopCondition):
    def __init__(self, end_time: float):
        self.end_time = end_time

    def check(self, state, history, stats=None):
        return state.real_time >= self.end_time

    def description(self):
        return ""


class _TargetAcquiredOrPoolEnd(StopCondition):
    def __init__(self, end_time: float, target_card_ids: Set[str]):
        self.end_time = end_time
        self.target_card_ids = target_card_ids

    def check(self, state, history, stats=None):
        if state.real_time >= self.end_time:
            return True
        if stats is not None and self.target_card_ids:
            for cid in self.target_card_ids:
                if stats.card_counts.get(cid, 0) < 1:
                    return False
            return True
        return False

    def description(self):
        return ""


class _DrawTargetStrategy(Strategy):
    lookahead = None

    def __init__(self, target_card_ids: Set[str], pool_id: str):
        self.target_card_ids = target_card_ids
        self.pool_id = pool_id
        self.acquired: Dict[str, int] = {}

    @classmethod
    def description(cls) -> str:
        return "最差影响分析：从目标池抽卡"

    def select_action(self, state, history, current_pools,
                      future_schedules, target_cards, stop_cond):
        for pool in current_pools:
            if pool.id == self.pool_id and state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in current_pools:
            if (pool.available_until is not None
                    and pool.available_until > state.real_time):
                wait_time = min(wait_time, pool.available_until - state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)

    def observe(self, iv):
        if iv.action_type == 'draw' and iv.card_id:
            self.acquired[iv.card_id] = self.acquired.get(iv.card_id, 0) + 1


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
        self._pool_duration = 21 * DAY
        self._parsed_cost = [{'draw_resource': 160}]
        self._rewards = []

    def analyze(self, condition='failure', alpha=0.05,
                num_simulations=500, progress_callback=None):
        success_checker = self._build_success_checker()
        self._success_checker = success_checker
        self.cond_dist = ConditionalResourceDistribution(
            self.simulation_results, success_checker
        )

        worst_resource = self.cond_dist.get_worst_case_resource(condition, alpha)
        pity_coverage = self._compute_pity_coverage(worst_resource)

        self._prepare_pool_info()

        pity_state = self._get_initial_pity_state()

        result = self._compute_pool_distribution(
            worst_resource, pity_state, num_simulations, progress_callback
        )
        return WorstImpactResult(
            worst_resource=worst_resource,
            pity_coverage=pity_coverage,
            pool_distribution=result['distribution'],
            expected_pools=result['expected'],
        )

    def _compute_pity_coverage(self, resource):
        pity_cost = self._get_pity_cost()
        return resource / pity_cost if pity_cost > 0 else float('inf')

    def _build_success_checker(self):
        from .gdr import SuccessChecker
        self._checker = SuccessChecker(
            target_specs=self.target_specs,
            gdr_key=self.gdr_key,
            gdr_threshold=self.gdr_threshold,
            desire_weights=self.desire_weights,
            miss_cost_weights=self.miss_cost_weights,
            card_value_weights=self.card_value_weights,
            ssr_ids=self._ssr_ids,
        )
        return self._checker.is_success

    def _check_pool_success(self, card_counts):
        if not self._featured_ids:
            return False
        for cid in self._featured_ids:
            if card_counts.get(cid, 0) < 1:
                return False
        return True

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
        for pool_entry in pool_entries:
            if pool_entry.distribution:
                for de in pool_entry.distribution:
                    rarity = de.rarity.upper()
                    if rarity == 'SSR':
                        self._ssr_ids.add(de.card_id)
                        if de.featured:
                            self._featured_ids.add(de.card_id)

        if not self._featured_ids and self._ssr_ids:
            self._featured_ids = set(self._ssr_ids)

        pool_duration_days = pe.end_day - pe.start_day
        if pool_duration_days <= 0:
            pool_duration_days = 21

        self._pool_duration = pool_duration_days * DAY
        self._rewards = rewards

        self._pity_engine = self._build_pity_engine()

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
        for r, prob in rewards:
            rarity = r.extra_info.get('rarity', '').upper()
            featured = r.extra_info.get('featured', False)
            if rarity == 'SSR':
                self._ssr_ids.add(r.id)
                if featured:
                    self._featured_ids.add(r.id)

        if not self._featured_ids and self._ssr_ids:
            self._featured_ids = set(self._ssr_ids)

        self._rewards = rewards
        self._pity_engine = self._build_pity_engine()

    def _build_pity_engine(self):
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
        for pool_idx in range(100):
            pid = f'_worst_impact_pool_{pool_idx}'
            matching = []
            resolved_per_pity = {}
            for pdef in pity_defs.values():
                if fnmatch.fnmatch(pid, pdef.pools):
                    matching.append(pdef.name)
                    if pdef.target_distribution:
                        resolved_per_pity[pdef.name] = self._resolve_targets(
                            pdef.target_distribution
                        )

            pool_specs[pid] = PoolPitySpec(
                pity_names=matching,
                featured_ids=self._featured_ids,
                ssr_ids=self._ssr_ids,
                resolved_targets=resolved_per_pity,
            )

        return PityEngine(pool_specs, pity_defs, behaviors)

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

    def _create_new_pool(self, pool_index: int):
        pid = f'_worst_impact_pool_{pool_index}'
        pool = Pool(
            id=pid,
            name=f'新池子#{pool_index}',
            cost=self._parsed_cost,
            rewards=self._rewards,
            available_from=0,
            available_until=self._pool_duration,
        )
        return pool

    def _build_target_card_set(self, pool_id: str):
        targets = []
        for card_id in self._featured_ids:
            targets.append(TargetCard(
                card_id=card_id,
                pool_ids=[pool_id],
                quantity_needed=1,
            ))
        return TargetCardSet(targets)

    def _compute_pool_distribution(self, resource, pity_state,
                                    num_simulations, progress_callback=None):
        success_counts = defaultdict(int)
        total_steps = num_simulations
        max_pools = 99

        for sim_idx in range(num_simulations):
            current_resource = resource
            current_pity = dict(pity_state)
            consecutive = 0
            pool_index = 0

            while current_resource > 0 and pool_index < max_pools:
                pool = self._create_new_pool(pool_index)
                target_set = self._build_target_card_set(pool.id)
                strategy = _DrawTargetStrategy(self._featured_ids, pool.id)
                stop_cond = _TargetAcquiredOrPoolEnd(
                    pool.available_until, self._featured_ids
                )

                result = self._run_single_simulation(
                    pool, current_resource, current_pity,
                    target_set, strategy, stop_cond
                )
                if result['success']:
                    consecutive += 1
                    current_resource = result['remaining_resource']
                    current_pity = result['final_pity_state']
                    pool_index += 1
                else:
                    break

            success_counts[consecutive] += 1

            if progress_callback and (sim_idx + 1) % max(1, total_steps // 20) == 0:
                pct = int((sim_idx + 1) / total_steps * 100)
                progress_callback(f"模拟中: {sim_idx + 1}/{total_steps}", pct)

        n = num_simulations
        distribution = {k: count / n for k, count in sorted(success_counts.items())}
        expected = sum(k * prob for k, prob in distribution.items())

        return {'distribution': distribution, 'expected': expected}

    def _run_single_simulation(self, pool, resource, pity_state,
                                target_set, strategy, stop_cond):
        pity_state_obj = PityState()
        if pity_state:
            for cname, cval in pity_state.items():
                pity_state_obj.counters[cname] = cval

        service = GachaService(
            pools=[pool],
            strategy=strategy,
            stop_condition=stop_cond,
            target_cards=target_set,
            pity_engine=self._pity_engine,
            pity_state=pity_state_obj,
        )
        state = GachaState(resources={'draw_resource': resource})
        result = service.run_simulation_compact(state)

        card_counts = result.get('card_counts', {})
        success = self._check_pool_success(card_counts)

        remaining_resource = result.get('final_resources', {}).get('draw_resource', 0)

        final_pity_state = dict(pity_state)
        pool_end_pity = result.get('pool_end_pity_states', {})
        final_pity_from_result = result.get('final_pity_state', {})
        if pool_end_pity:
            if pool.id in pool_end_pity:
                final_pity_state = pool_end_pity[pool.id].get('counters', {})
            else:
                last_key = list(pool_end_pity.keys())[-1]
                final_pity_state = pool_end_pity[last_key].get('counters', {})
        elif final_pity_from_result:
            final_pity_state = final_pity_from_result.get('counters', {})

        return {
            'success': success,
            'remaining_resource': remaining_resource,
            'final_pity_state': final_pity_state,
        }
