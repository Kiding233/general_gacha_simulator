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
from .target_card import TargetCard, TargetCardSet
from .stop_condition import StopCondition, ResourceThresholdCondition, TimeLimitCondition, CompositeStopCondition, PoolFailedCondition
from .schedule import PoolSchedule, PoolScheduleManager
from .strategy import SmartStrategy
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
        self._num_new_pools = 20

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

    def _check_pool_success(self, pool_card_counts, pool_idx):
        if not self._featured_ids:
            return False
        for cid in self._featured_ids:
            virtual_id = f'{cid}__pool_{pool_idx}'
            if pool_card_counts.get(virtual_id, 0) < 1:
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
        for pool_idx in range(self._num_new_pools):
            pid = f'_worst_impact_pool_{pool_idx}'
            matching = []
            resolved_per_pity = {}
            for pdef in pity_defs.values():
                if fnmatch.fnmatch(pid, pdef.pools):
                    matching.append(pdef.name)
                    if pdef.target_distribution:
                        resolved_per_pity[pdef.name] = self._resolve_targets(
                            pdef.target_distribution, pool_idx
                        )

            virtual_featured = {f'{cid}__pool_{pool_idx}' for cid in self._featured_ids}
            virtual_ssr = {f'{cid}__pool_{pool_idx}' for cid in self._ssr_ids}

            pool_specs[pid] = PoolPitySpec(
                pity_names=matching,
                featured_ids=virtual_featured,
                ssr_ids=virtual_ssr,
                resolved_targets=resolved_per_pity,
            )

        return PityEngine(pool_specs, pity_defs, behaviors)

    def _resolve_targets(self, target_dist, pool_idx=None):
        resolved = {}
        for key, weight in target_dist.items():
            k = key.lower()
            if k in ('limited_ssr', 'featured'):
                for cid in self._featured_ids:
                    vid = f'{cid}__pool_{pool_idx}' if pool_idx is not None else cid
                    resolved[vid] = resolved.get(vid, 0) + weight
            elif k in ('standard_ssr', 'offrate'):
                for cid in (self._ssr_ids - self._featured_ids):
                    vid = f'{cid}__pool_{pool_idx}' if pool_idx is not None else cid
                    resolved[vid] = resolved.get(vid, 0) + weight
            elif k == 'ssr':
                for cid in self._ssr_ids:
                    vid = f'{cid}__pool_{pool_idx}' if pool_idx is not None else cid
                    resolved[vid] = resolved.get(vid, 0) + weight
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

    def _build_sequential_pools(self):
        pools = []
        schedules = []
        for pool_idx in range(self._num_new_pools):
            pid = f'_worst_impact_pool_{pool_idx}'
            pool_rewards = []
            for r, prob in self._rewards:
                rid = r.id
                if rid in self._featured_ids:
                    rid = f'{rid}__pool_{pool_idx}'
                pool_rewards.append((Reward(
                    id=rid,
                    name=r.name,
                    resources_gained=r.resources_gained,
                    extra_info=r.extra_info,
                ), prob))
            pool = Pool(
                id=pid,
                name=f'新池子#{pool_idx + 1}',
                cost=self._parsed_cost,
                rewards=pool_rewards,
                available_from=pool_idx * self._pool_duration,
                available_until=(pool_idx + 1) * self._pool_duration,
            )
            pools.append(pool)
            schedules.append(PoolSchedule(
                pool_id=pid,
                available_from=pool.available_from,
                available_until=pool.available_until,
            ))
        schedule_mgr = PoolScheduleManager(schedules)
        return pools, schedule_mgr

    def _build_target_card_set(self):
        targets = []
        for pool_idx in range(self._num_new_pools):
            pid = f'_worst_impact_pool_{pool_idx}'
            for card_id in self._featured_ids:
                targets.append(TargetCard(
                    card_id=f'{card_id}__pool_{pool_idx}',
                    pool_ids=[pid],
                    quantity_needed=1,
                ))
        return TargetCardSet(targets)

    def _compute_pool_distribution(self, resource, pity_state,
                                    num_simulations, progress_callback=None):
        pools, schedule_mgr = self._build_sequential_pools()
        target_set = self._build_target_card_set()
        end_time = self._num_new_pools * self._pool_duration

        pool_end_times = []
        featured_ids_map = {}
        for pool_idx in range(self._num_new_pools):
            pid = f'_worst_impact_pool_{pool_idx}'
            pool_obj = pools[pool_idx]
            pool_end_times.append((pid, pool_obj.available_until))
            featured_ids_map[pid] = {
                f'{cid}__pool_{pool_idx}' for cid in self._featured_ids
            }

        pool_failed_cond = PoolFailedCondition(pool_end_times, featured_ids_map)

        stop_cond = CompositeStopCondition([
            ResourceThresholdCondition('draw_resource', 0, '<='),
            TimeLimitCondition(end_time),
            pool_failed_cond,
        ], mode='any')

        success_counts = defaultdict(int)

        for sim_idx in range(num_simulations):
            strategy = SmartStrategy(target_set, all_pools=pools)

            pity_state_obj = PityState()
            if pity_state:
                for cname, cval in pity_state.items():
                    pity_state_obj.counters[cname] = cval

            service = GachaService(
                pools=pools,
                strategy=strategy,
                stop_condition=stop_cond,
                target_cards=target_set,
                schedule_manager=schedule_mgr,
                pity_engine=self._pity_engine,
                pity_state=pity_state_obj,
            )
            state = GachaState(resources={'draw_resource': resource})
            result = service.run_simulation_compact(state)

            pool_card_counts = result.get('pool_card_counts', {})
            consecutive = 0
            for pool_idx in range(self._num_new_pools):
                pid = f'_worst_impact_pool_{pool_idx}'
                pcc = pool_card_counts.get(pid, {})
                if self._check_pool_success(pcc, pool_idx):
                    consecutive += 1
                else:
                    break

            success_counts[consecutive] += 1

            if progress_callback and (sim_idx + 1) % max(1, num_simulations // 20) == 0:
                pct = int((sim_idx + 1) / num_simulations * 100)
                progress_callback(f"模拟中: {sim_idx + 1}/{num_simulations}", pct)

        n = num_simulations
        distribution = {k: count / n for k, count in sorted(success_counts.items())}
        expected = sum(k * prob for k, prob in distribution.items())

        return {'distribution': distribution, 'expected': expected}
