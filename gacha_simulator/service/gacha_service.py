from typing import List, Optional, Union
import time
import uuid
from ..core import (
    GachaState, Pool, DrawAction, WaitAction,
    InfoVector, Strategy, StrategyContext, StopCondition, TargetCardSet, ResourceGainFunction, CompactResult,
    SimulationCollector, InfoVectorCollector, CompactCollector,
)
from ..core.pity import PityEngine, PityState
from ..core.pool import NO_CARD_ID as _NO_CARD_ID, compute_bonus_resources


class SimulationStats:
    __slots__ = ('total_actions', 'total_draws', 'total_waits',
                 'total_resources_consumed', 'total_resources_gained',
                 'card_counts', 'acquired_counts', 'pool_draw_counts', 'pity_triggers',
                 'last_draw_card_id', 'last_action_time',
                 'last_draw_pity_triggered')

    def __init__(self):
        self.total_actions = 0
        self.total_draws = 0
        self.total_waits = 0
        self.total_resources_consumed = {}
        self.total_resources_gained = {}
        self.card_counts = {}
        self.acquired_counts = {}
        self.pool_draw_counts = {}
        self.pity_triggers = 0
        self.last_draw_card_id = None
        self.last_action_time = 0.0
        self.last_draw_pity_triggered = False

    def on_draw(self, card_id: str, pool_id: str, pity_triggered: bool = False):
        self.total_actions += 1
        self.total_draws += 1
        self.last_draw_card_id = card_id
        self.last_action_time += 1
        self.last_draw_pity_triggered = pity_triggered
        cc = self.card_counts
        cc[card_id] = cc.get(card_id, 0) + 1
        if card_id != _NO_CARD_ID:
            ac = self.acquired_counts
            ac[card_id] = ac.get(card_id, 0) + 1
        pc = self.pool_draw_counts
        pc[pool_id] = pc.get(pool_id, 0) + 1

    def on_wait(self, duration: float):
        self.total_actions += 1
        self.total_waits += 1
        self.last_action_time += duration


_EMPTY_DICT = {}


class GachaService:
    def __init__(
        self,
        pools: List[Pool],
        strategy: Strategy,
        stop_condition: StopCondition,
        target_cards: TargetCardSet,
        schedule_manager: Optional['PoolScheduleManager'] = None,  # noqa: F821
        resource_gain: Optional[ResourceGainFunction] = None,
        pity_engine: Optional[PityEngine] = None,
        pity_state: Optional[PityState] = None,
        ssr_ids: Optional[set] = None,
        card_defs: Optional[List] = None,
    ):
        self.pools = {p.id: p for p in pools}
        self.strategy = strategy
        self.stop_condition = stop_condition
        self.target_cards = target_cards
        self.schedule_manager = schedule_manager
        self.resource_gain = resource_gain
        self.pity_engine = pity_engine
        self.pity_state = pity_state or PityState()
        self.ssr_ids = ssr_ids or set()
        self.card_defs = card_defs or []
        self.session_id = str(uuid.uuid4())
        self._pools_list = list(self.pools.values())

    def run_simulation(
        self,
        initial_state: GachaState,
        max_iterations: int = 100000,
        lightweight: bool = False,
        collector: Optional[SimulationCollector] = None,
    ) -> Union[List[InfoVector], CompactResult]:
        if collector is None:
            collector = InfoVectorCollector(
                session_id=self.session_id, lightweight=lightweight
            )

        state = initial_state.clone()
        pity_state = self.pity_state.clone()
        stats = SimulationStats()
        _initial_counts = {}
        for cd in self.card_defs:
            ic = cd.get('initial_count', 0) if isinstance(cd, dict) else getattr(cd, 'initial_count', 0)
            if ic > 0:
                cid = cd['card_id'] if isinstance(cd, dict) else cd.card_id
                _initial_counts[cid] = ic
        pools_list = self._pools_list
        real_time = state.real_time
        resources = state.resources
        _check = self.stop_condition.check
        _strategy = self.strategy
        _target_cards = self.target_cards
        _stop = self.stop_condition
        _pools = self.pools
        _schedule_mgr = self.schedule_manager
        _lookahead = self.strategy.lookahead
        _resource_gain = self.resource_gain
        _pity_engine = self.pity_engine
        _isinstance = isinstance
        _DrawAction = DrawAction
        _WaitAction = WaitAction
        _is_compact = isinstance(collector, CompactCollector)

        pool_end_times_sorted = sorted(
            [(p.id, p.available_until) for p in pools_list if p.available_until],
            key=lambda x: x[1]
        ) if _is_compact else []
        recorded_pool_ends = set() if _is_compact else None
        _pending_wait_gains = {} if _is_compact else None
        total_consumed = {} if _is_compact else None
        total_gained = {} if _is_compact else None

        for iteration in range(max_iterations):
            if _check(state, [], stats):
                break

            current_pools = [p for p in pools_list
                           if (p.available_from is None or real_time >= p.available_from)
                           and (p.available_until is None or real_time <= p.available_until)]

            future_schedules = []
            if _schedule_mgr and _lookahead:
                future_schedules = _schedule_mgr.get_future_schedules(real_time, _lookahead)

            ctx = StrategyContext(
                state=state,
                current_pools=current_pools,
                all_pools=pools_list,
                future_schedules=future_schedules,
                target_cards=_target_cards,
                stop_condition=_stop,
                _pity_engine=_pity_engine,
                _pity_state=pity_state,
                acquired=dict(stats.acquired_counts),
                pool_draw_counts=dict(stats.pool_draw_counts),
                total_draws=stats.total_draws,
                last_draw_pity_triggered=stats.last_draw_pity_triggered,
                ssr_ids=self.ssr_ids,
            )

            action = _strategy.select_action(ctx)

            if _isinstance(action, _DrawAction):
                pool = _pools.get(action.pool_id)
                if not pool:
                    raise ValueError(f"Pool not found: {action.pool_id}")

                cost = pool.cost
                spent = state.spend(cost)
                if spent is None:
                    continue

                probabilities = {r.id: p for r, p in pool.rewards}
                original_probs = probabilities.copy() if _pity_engine else None
                if _pity_engine:
                    cached_probs = ctx._pity_cache.get(pool.id)
                    if cached_probs is not None:
                        probabilities = cached_probs
                    else:
                        probabilities = _pity_engine.before_draw(
                            pool.id, pity_state, probabilities
                        )
                    pool._apply_probabilities(probabilities)

                reward = pool.draw()

                pity_triggered = False
                triggered_pity_name = None
                if original_probs is not None:
                    for card_id, orig_prob in original_probs.items():
                        new_prob = probabilities.get(card_id, 0)
                        if new_prob > orig_prob * 1.01:
                            pity_triggered = True
                            break

                if _pity_engine and pity_triggered:
                    spec = _pity_engine.get_spec(pool.id)
                    if spec:
                        triggered_names = []
                        for pname in spec.pity_names:
                            behavior = _pity_engine.behaviors.get(pname)
                            if behavior is None:
                                continue
                            cv = pity_state.get(pname)
                            if behavior.is_active(cv):
                                triggered_names.append(pname)
                        triggered_pity_name = ','.join(triggered_names) if triggered_names else None

                pool_spec = _pity_engine.get_spec(pool.id) if _pity_engine else None
                pool_counter_max = 0
                if pool_spec:
                    for pname in pool_spec.pity_names:
                        cv = pity_state.get(pname)
                        pool_counter_max = max(pool_counter_max, cv)

                if _pity_engine:
                    _pity_engine.after_draw(pool.id, pity_state, reward.id)

                stats.on_draw(reward.id, pool.id, pity_triggered)
                if pity_triggered:
                    stats.pity_triggers += 1

                rg = dict(reward.resources_gained or {})
                if reward.first_time_bonus or reward.nth_time_bonus or reward.excess_bonus:
                    ac_new = stats.acquired_counts.get(reward.id, 0)
                    init = _initial_counts.get(reward.id, 0)
                    total_before = init + ac_new - 1
                    total_after = init + ac_new
                    bonus = compute_bonus_resources(reward, total_before, total_after)
                    for k, v in bonus.items():
                        rg[k] = rg.get(k, 0) + v
                if rg:
                    for k, v in rg.items():
                        resources[k] = resources.get(k, 0) + v

                if _is_compact:
                    for k, v in spent.items():
                        total_consumed[k] = total_consumed.get(k, 0) + v
                    if rg:
                        for k, v in rg.items():
                            total_gained[k] = total_gained.get(k, 0) + v
                    combined_gained = dict(rg)
                    for k, v in _pending_wait_gains.items():
                        combined_gained[k] = combined_gained.get(k, 0) + v
                    _pending_wait_gains.clear()
                else:
                    combined_gained = rg.copy() if rg else _EMPTY_DICT

                collector.on_draw(
                    card_id=reward.id, pool=pool, spent=spent,
                    resources_gained=rg, pity_triggered=pity_triggered,
                    triggered_pity_name=triggered_pity_name,
                    pity_counter_max=pool_counter_max,
                    real_time=real_time, pity_state=pity_state,
                    combined_gained=combined_gained,
                )

            elif _isinstance(action, _WaitAction):
                rt_before = real_time
                real_time += action.duration
                state.real_time = real_time

                rg = {}
                if _resource_gain:
                    rg = _resource_gain.compute(action.duration, state)
                    for k, v in rg.items():
                        resources[k] = resources.get(k, 0) + v
                    if _is_compact:
                        for k, v in rg.items():
                            total_gained[k] = total_gained.get(k, 0) + v
                            _pending_wait_gains[k] = _pending_wait_gains.get(k, 0) + v

                if _is_compact:
                    for pid, pet in pool_end_times_sorted:
                        if pid not in recorded_pool_ends and real_time >= pet:
                            collector.on_pool_end(pid, dict(resources), pity_state.to_dict())
                            recorded_pool_ends.add(pid)

                stats.on_wait(action.duration)

                collector.on_wait(
                    duration=action.duration, resources_gained=rg,
                    real_time_before=rt_before, real_time_after=real_time,
                )

            else:
                raise ValueError(f"Unknown action type: {action}")

            if _is_compact:
                for pid, pet in pool_end_times_sorted:
                    if pid not in recorded_pool_ends and real_time >= pet:
                        collector.on_pool_end(pid, dict(resources), pity_state.to_dict())
                        recorded_pool_ends.add(pid)

        state.real_time = real_time
        state.resources = resources

        if _is_compact:
            for pid, pet in pool_end_times_sorted:
                if pid not in recorded_pool_ends and real_time >= pet:
                    collector.on_pool_end(pid, dict(resources), pity_state.to_dict())
                    recorded_pool_ends.add(pid)

            result = collector.get_result()
            result.total_consumed = total_consumed
            result.total_gained = total_gained
            result.total_draws = stats.total_draws
            result.total_waits = stats.total_waits
            result.pity_triggers = stats.pity_triggers
            result.final_resources = dict(resources)
            result.final_time = real_time
            result.pool_types = {pid: p.pool_type for pid, p in self.pools.items()}
            result.strategy_name = type(self.strategy).__name__
            result.generated_at = time.time()
            return result

        return collector.get_result()

    def run_simulation_compact(
        self, initial_state: GachaState, max_iterations: int = 100000,
    ) -> CompactResult:
        return self.run_simulation(
            initial_state, max_iterations=max_iterations,
            collector=CompactCollector(),
        )
