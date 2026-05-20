from dataclasses import dataclass, field
from typing import List, Optional, Dict, Any
import uuid
from ..core import (
    GachaState, Pool, Action, DrawAction, WaitAction,
    InfoVector, Strategy, StopCondition, PoolSchedule,
    TargetCardSet, ResourceGainFunction
)
from ..core.pity import PityEngine, PityState
from ..core.pool import NO_CARD_ID as _NO_CARD_ID


class SimulationStats:
    __slots__ = ('total_actions', 'total_draws', 'total_waits',
                 'total_resources_consumed', 'total_resources_gained',
                 'card_counts', 'pool_draw_counts', 'pity_triggers',
                 'last_draw_card_id', 'last_action_time')

    def __init__(self):
        self.total_actions = 0
        self.total_draws = 0
        self.total_waits = 0
        self.total_resources_consumed = {}
        self.total_resources_gained = {}
        self.card_counts = {}
        self.pool_draw_counts = {}
        self.pity_triggers = 0
        self.last_draw_card_id = None
        self.last_action_time = 0.0

    def on_draw(self, card_id: str, pool_id: str):
        self.total_actions += 1
        self.total_draws += 1
        self.last_draw_card_id = card_id
        self.last_action_time += 1
        cc = self.card_counts
        cc[card_id] = cc.get(card_id, 0) + 1
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
        schedule_manager: Optional['PoolScheduleManager'] = None,
        resource_gain: Optional[ResourceGainFunction] = None,
        pity_engine: Optional[PityEngine] = None,
        pity_state: Optional[PityState] = None,
    ):
        self.pools = {p.id: p for p in pools}
        self.strategy = strategy
        self.stop_condition = stop_condition
        self.target_cards = target_cards
        self.schedule_manager = schedule_manager
        self.resource_gain = resource_gain
        self.pity_engine = pity_engine
        self.pity_state = pity_state or PityState()
        self.session_id = str(uuid.uuid4())
        self._pools_list = list(self.pools.values())

    def run_simulation(
        self, initial_state: GachaState, max_iterations: int = 100000,
        lightweight: bool = False
    ) -> List[InfoVector]:
        state = initial_state.clone()
        history: List[InfoVector] = []
        pity_state = self.pity_state.clone()
        stats = SimulationStats()
        pools_list = self._pools_list
        real_time = state.real_time
        resources = state.resources
        _check = self.stop_condition.check
        _strategy = self.strategy.select_action
        _strategy_obj = self.strategy
        _target_cards = self.target_cards
        _stop = self.stop_condition
        _pools = self.pools
        _session = self.session_id
        _append = history.append
        _schedule_mgr = self.schedule_manager
        _lookahead = self.strategy.lookahead
        _resource_gain = self.resource_gain
        _pity_engine = self.pity_engine
        _IV = InfoVector
        _isinstance = isinstance
        _DrawAction = DrawAction
        _WaitAction = WaitAction

        for iteration in range(max_iterations):
            if _check(state, history, stats):
                break

            current_pools = [p for p in pools_list
                           if (p.available_from is None or real_time >= p.available_from)
                           and (p.available_until is None or real_time <= p.available_until)]

            future_schedules = []
            if _schedule_mgr and _lookahead:
                future_schedules = _schedule_mgr.get_future_schedules(real_time, _lookahead)

            action = _strategy(state, history, current_pools, future_schedules, _target_cards, _stop)

            if _isinstance(action, _DrawAction):
                pool = _pools.get(action.pool_id)
                if not pool:
                    raise ValueError(f"Pool not found: {action.pool_id}")

                rt_before = real_time
                cost = pool.cost
                spent = state.spend(cost)
                if spent is None:
                    continue

                probabilities = {r.id: p for r, p in pool.rewards}
                original_probs = probabilities.copy() if _pity_engine else None
                if _pity_engine:
                    probabilities = _pity_engine.before_draw(
                        pool.id, pity_state, probabilities
                    )
                    pool._apply_probabilities(probabilities)

                reward = pool.draw()

                pity_triggered = False
                if original_probs is not None:
                    for card_id, orig_prob in original_probs.items():
                        new_prob = probabilities.get(card_id, 0)
                        if new_prob > orig_prob * 1.01:
                            pity_triggered = True
                            break

                stats.on_draw(reward.id, pool.id)

                if hasattr(_strategy_obj, 'acquired') and reward.id != _NO_CARD_ID:
                    _strategy_obj.acquired[reward.id] = _strategy_obj.acquired.get(reward.id, 0) + 1

                rg = reward.resources_gained
                if rg:
                    for k in rg:
                        resources[k] = resources.get(k, 0) + rg[k]

                _append(_IV(
                    action_type='draw', card_id=reward.id, pool_id=pool.id,
                    resources_consumed=spent.copy(),
                    resources_gained=rg.copy() if rg else _EMPTY_DICT,
                    real_time_before=rt_before, real_time_after=real_time,
                    time_elapsed=1, pity_state=_EMPTY_DICT if lightweight else pity_state.to_dict(),
                    action_index=stats.total_actions - 1, session_id=_session,
                    pity_triggered=pity_triggered,
                ))

            elif _isinstance(action, _WaitAction):
                rt_before = real_time
                real_time += action.duration
                state.real_time = real_time

                rg = {}
                if _resource_gain:
                    rg = _resource_gain.compute(action.duration, state)
                    for k in rg:
                        resources[k] = resources.get(k, 0) + rg[k]

                stats.on_wait(action.duration)

                _append(_IV(
                    action_type='wait', card_id=None, pool_id=None,
                    resources_consumed=_EMPTY_DICT, resources_gained=rg,
                    real_time_before=rt_before, real_time_after=real_time,
                    time_elapsed=action.duration, pity_state=_EMPTY_DICT,
                    action_index=stats.total_actions - 1, session_id=_session,
                ))

            else:
                raise ValueError(f"Unknown action type: {action}")

        state.real_time = real_time
        state.resources = resources
        return history

    def run_simulation_compact(
        self, initial_state: GachaState, max_iterations: int = 100000,
    ) -> Dict[str, Any]:
        state = initial_state.clone()
        pity_state = self.pity_state.clone()
        stats = SimulationStats()
        pools_list = self._pools_list
        real_time = state.real_time
        resources = state.resources
        _check = self.stop_condition.check
        _strategy = self.strategy.select_action
        _strategy_obj = self.strategy
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

        draw_card_ids = []
        draw_pool_ids = []
        draw_times = []
        draw_pity = []
        draw_pity_names = []
        draw_pity_counter_max = []
        draw_resources_consumed = []
        draw_resources_gained = []
        wait_times_list = []
        total_consumed = {}
        total_gained = {}
        card_counts = {}
        pool_draw_counts = {}
        pool_card_counts = {}
        pool_pity_counts = {}
        _pending_wait_gains = {}

        pool_end_resources = {}
        pool_end_pity_states = {}
        pool_end_times_sorted = sorted(
            [(p.id, p.available_until) for p in pools_list if p.available_until],
            key=lambda x: x[1]
        )
        recorded_pool_ends = set()

        for iteration in range(max_iterations):
            if _check(state, [], stats):
                break

            current_pools = [p for p in pools_list
                           if (p.available_from is None or real_time >= p.available_from)
                           and (p.available_until is None or real_time <= p.available_until)]

            future_schedules = []
            if _schedule_mgr and _lookahead:
                future_schedules = _schedule_mgr.get_future_schedules(real_time, _lookahead)

            action = _strategy(state, [], current_pools, future_schedules, _target_cards, _stop)

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
                        for pname in spec.pity_names:
                            behavior = _pity_engine.behaviors.get(pname)
                            if behavior is None:
                                continue
                            cv = pity_state.get(pname)
                            if hasattr(behavior, 'start_at') and cv >= behavior.start_at:
                                triggered_pity_name = pname
                                break

                pool_spec = _pity_engine.get_spec(pool.id) if _pity_engine else None
                pool_counter_max = 0
                if pool_spec:
                    for pname in pool_spec.pity_names:
                        cv = pity_state.get(pname)
                        pool_counter_max = max(pool_counter_max, cv)

                if _pity_engine:
                    _pity_engine.after_draw(pool.id, pity_state, reward.id)

                draw_card_ids.append(reward.id)
                draw_pool_ids.append(pool.id)
                draw_times.append(real_time)
                draw_pity.append(pity_triggered)
                draw_pity_names.append(triggered_pity_name)
                draw_pity_counter_max.append(pool_counter_max)

                stats.on_draw(reward.id, pool.id)
                if pity_triggered:
                    stats.pity_triggers += 1

                if hasattr(_strategy_obj, 'acquired') and reward.id != _NO_CARD_ID:
                    _strategy_obj.acquired[reward.id] = _strategy_obj.acquired.get(reward.id, 0) + 1

                rg = reward.resources_gained
                if rg:
                    for k, v in rg.items():
                        resources[k] = resources.get(k, 0) + v
                        total_gained[k] = total_gained.get(k, 0) + v

                for k, v in spent.items():
                    total_consumed[k] = total_consumed.get(k, 0) + v

                draw_resources_consumed.append(dict(spent))
                combined_gained = dict(rg) if rg else {}
                for k, v in _pending_wait_gains.items():
                    combined_gained[k] = combined_gained.get(k, 0) + v
                draw_resources_gained.append(combined_gained)
                _pending_wait_gains.clear()

                cc = card_counts
                cc[reward.id] = cc.get(reward.id, 0) + 1
                pc = pool_draw_counts
                pc[pool.id] = pc.get(pool.id, 0) + 1

                pcc = pool_card_counts.get(pool.id, {})
                pcc[reward.id] = pcc.get(reward.id, 0) + 1
                pool_card_counts[pool.id] = pcc

                if pity_triggered:
                    ppc = pool_pity_counts
                    ppc[pool.id] = ppc.get(pool.id, 0) + 1

            elif _isinstance(action, _WaitAction):
                real_time += action.duration
                state.real_time = real_time

                if _resource_gain:
                    rg = _resource_gain.compute(action.duration, state)
                    for k, v in rg.items():
                        resources[k] = resources.get(k, 0) + v
                        total_gained[k] = total_gained.get(k, 0) + v
                        _pending_wait_gains[k] = _pending_wait_gains.get(k, 0) + v

                for pid, pet in pool_end_times_sorted:
                    if pid not in recorded_pool_ends and real_time >= pet:
                        pool_end_resources[pid] = dict(resources)
                        pool_end_pity_states[pid] = pity_state.to_dict()
                        recorded_pool_ends.add(pid)

                stats.on_wait(action.duration)
                wait_times_list.append(action.duration)

            for pid, pet in pool_end_times_sorted:
                if pid not in recorded_pool_ends and real_time >= pet:
                    pool_end_resources[pid] = dict(resources)
                    pool_end_pity_states[pid] = pity_state.to_dict()
                    recorded_pool_ends.add(pid)

        state.real_time = real_time
        state.resources = resources

        # 循环结束后，记录尚未记录的池结束资源（最后一个池可能没有被 WaitAction 触发）
        for pid, pet in pool_end_times_sorted:
            if pid not in recorded_pool_ends and real_time >= pet:
                pool_end_resources[pid] = dict(resources)
                pool_end_pity_states[pid] = pity_state.to_dict()
                recorded_pool_ends.add(pid)

        return {
            'draw_card_ids': draw_card_ids,
            'draw_pool_ids': draw_pool_ids,
            'draw_times': draw_times,
            'draw_pity': draw_pity,
            'draw_pity_names': draw_pity_names,
            'draw_pity_counter_max': draw_pity_counter_max,
            'draw_resources_consumed': draw_resources_consumed,
            'draw_resources_gained': draw_resources_gained,
            'wait_durations': wait_times_list,
            'total_consumed': total_consumed,
            'total_gained': total_gained,
            'card_counts': card_counts,
            'pool_draw_counts': pool_draw_counts,
            'pool_card_counts': pool_card_counts,
            'pool_pity_counts': pool_pity_counts,
            'total_draws': stats.total_draws,
            'total_waits': stats.total_waits,
            'pity_triggers': stats.pity_triggers,
            'final_resources': dict(resources),
            'final_time': real_time,
            'final_pity_state': pity_state.to_dict(),
            'pool_end_resources': pool_end_resources,
            'pool_end_pity_states': pool_end_pity_states,
        }
