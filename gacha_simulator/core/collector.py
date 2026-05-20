from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from .info_vector import InfoVector
    from .pool import Pool
    from .pity import PityState
    from .result_types import CompactResult


class SimulationCollector(ABC):
    @abstractmethod
    def on_draw(
        self,
        card_id: str,
        pool: 'Pool',
        spent: Dict[str, float],
        resources_gained: Dict[str, float],
        pity_triggered: bool,
        triggered_pity_name: Optional[str],
        pity_counter_max: int,
        real_time: float,
        pity_state: 'PityState',
        combined_gained: Dict[str, float],
    ) -> None:
        pass

    @abstractmethod
    def on_wait(
        self,
        duration: float,
        resources_gained: Dict[str, float],
        real_time_before: float,
        real_time_after: float,
    ) -> None:
        pass

    @abstractmethod
    def on_pool_end(self, pool_id: str, resources: Dict[str, float],
                    pity_state_dict: Dict[str, Any]) -> None:
        pass

    @abstractmethod
    def get_result(self) -> Any:
        pass


class InfoVectorCollector(SimulationCollector):
    def __init__(self, session_id: str = '', lightweight: bool = False):
        self._history: List['InfoVector'] = []
        self._session_id = session_id
        self._lightweight = lightweight
        self._action_index = 0

    def on_draw(self, card_id, pool, spent, resources_gained, pity_triggered,
                triggered_pity_name, pity_counter_max, real_time, pity_state,
                combined_gained):
        from .info_vector import InfoVector
        self._history.append(InfoVector(
            action_type='draw', card_id=card_id, pool_id=pool.id,
            resources_consumed=spent.copy(),
            resources_gained=resources_gained,
            real_time_before=real_time, real_time_after=real_time,
            time_elapsed=1,
            pity_state={} if self._lightweight else pity_state.to_dict(),
            action_index=self._action_index, session_id=self._session_id,
            pity_triggered=pity_triggered,
        ))
        self._action_index += 1

    def on_wait(self, duration, resources_gained, real_time_before, real_time_after):
        from .info_vector import InfoVector
        self._history.append(InfoVector(
            action_type='wait', card_id=None, pool_id=None,
            resources_consumed={}, resources_gained=resources_gained,
            real_time_before=real_time_before, real_time_after=real_time_after,
            time_elapsed=duration, pity_state={},
            action_index=self._action_index, session_id=self._session_id,
        ))
        self._action_index += 1

    def on_pool_end(self, pool_id, resources, pity_state_dict):
        pass

    def get_result(self) -> List['InfoVector']:
        return self._history


class CompactCollector(SimulationCollector):
    def __init__(self):
        from .result_types import CompactResult
        self._result = CompactResult()

    def on_draw(self, card_id, pool, spent, resources_gained, pity_triggered,
                triggered_pity_name, pity_counter_max, real_time, pity_state,
                combined_gained):
        r = self._result
        r.draw_card_ids.append(card_id)
        r.draw_pool_ids.append(pool.id)
        r.draw_times.append(real_time)
        r.draw_pity.append(pity_triggered)
        r.draw_pity_names.append(triggered_pity_name)
        r.draw_pity_counter_max.append(pity_counter_max)
        r.draw_resources_consumed.append(dict(spent))
        r.draw_resources_gained.append(combined_gained)

        cc = r.card_counts
        cc[card_id] = cc.get(card_id, 0) + 1
        pc = r.pool_draw_counts
        pc[pool.id] = pc.get(pool.id, 0) + 1

        pcc = r.pool_card_counts.get(pool.id, {})
        pcc[card_id] = pcc.get(card_id, 0) + 1
        r.pool_card_counts[pool.id] = pcc

        if pity_triggered:
            ppc = r.pool_pity_counts
            ppc[pool.id] = ppc.get(pool.id, 0) + 1

    def on_wait(self, duration, resources_gained, real_time_before, real_time_after):
        self._result.wait_durations.append(duration)

    def on_pool_end(self, pool_id, resources, pity_state_dict):
        self._result.pool_end_resources[pool_id] = dict(resources)
        self._result.pool_end_pity_states[pool_id] = pity_state_dict

    def get_result(self) -> 'CompactResult':
        return self._result
