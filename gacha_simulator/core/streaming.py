from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple


class StreamingAnalyzer(ABC):
    @abstractmethod
    def on_result(self, compact: Dict[str, Any]) -> None: ...

    @abstractmethod
    def get_result(self) -> Any: ...


class StreamingSuccessCounter(StreamingAnalyzer):
    def __init__(self, target_specs, gdr_key, gdr_threshold,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None, ssr_ids=None,
                 weapon_character_map=None):
        from .gdr import SuccessChecker
        self._checker = SuccessChecker(
            target_specs, gdr_key, gdr_threshold,
            desire_weights, miss_cost_weights, card_value_weights,
            ssr_ids, weapon_character_map,
        )
        self.total = 0
        self.success = 0

    def on_result(self, compact):
        self.total += 1
        if self._checker.is_success(compact):
            self.success += 1

    def get_probability(self) -> float:
        return self.success / self.total if self.total > 0 else 0.0

    def get_result(self):
        return self.get_probability()


class SharedResultCollector:
    def __init__(self):
        self._extractors: Dict[str, Tuple[Callable, list]] = {}
        self.n_results = 0

    def add_extractor(self, name: str, extract_func: Callable[[Dict], Any]):
        self._extractors[name] = (extract_func, [])

    def on_result(self, compact: Dict[str, Any]):
        if compact is None:
            return
        for name, (extract_func, acc) in self._extractors.items():
            acc.append(extract_func(compact))
        self.n_results += 1

    def get_extracted(self, name: str) -> list:
        if name in self._extractors:
            return self._extractors[name][1]
        return []

    def reset(self):
        for name, (extract_func, acc) in self._extractors.items():
            acc.clear()
        self.n_results = 0


def extract_aggregate(compact):
    pool_ids_list = compact.get('draw_pool_ids', [])
    draw_res_consumed = compact.get('draw_resources_consumed', [])
    draw_res_gained = compact.get('draw_resources_gained', [])
    draw_pity_counter_max = compact.get('draw_pity_counter_max', [])
    pool_resources_consumed = {}
    pool_resources_gained = {}
    pool_counter_max = {}
    for i, pid in enumerate(pool_ids_list):
        if pid not in pool_resources_consumed:
            pool_resources_consumed[pid] = {}
            pool_resources_gained[pid] = {}
            pool_counter_max[pid] = 0
        if i < len(draw_res_consumed) and draw_res_consumed[i]:
            for k, v in draw_res_consumed[i].items():
                pool_resources_consumed[pid][k] = pool_resources_consumed[pid].get(k, 0) + v
        if i < len(draw_res_gained) and draw_res_gained[i]:
            for k, v in draw_res_gained[i].items():
                pool_resources_gained[pid][k] = pool_resources_gained[pid].get(k, 0) + v
        if i < len(draw_pity_counter_max):
            pool_counter_max[pid] = max(pool_counter_max[pid], draw_pity_counter_max[i])

    return {
        'card_counts': dict(compact.get('card_counts', {})),
        'pool_draw_counts': dict(compact.get('pool_draw_counts', {})),
        'pool_card_counts': dict(compact.get('pool_card_counts', {})),
        'pool_pity_counts': dict(compact.get('pool_pity_counts', {})),
        'total_draws': compact.get('total_draws', 0),
        'total_consumed': dict(compact.get('total_consumed', {})),
        'total_gained': dict(compact.get('total_gained', {})),
        'final_resources': dict(compact.get('final_resources', {})),
        'final_time': compact.get('final_time', 0),
        'pity_triggers': compact.get('pity_triggers', 0),
        'pool_end_resources': dict(compact.get('pool_end_resources', {})),
        'pool_end_pity_states': dict(compact.get('pool_end_pity_states', {})),
        'pool_resources_consumed': pool_resources_consumed,
        'pool_resources_gained': pool_resources_gained,
        'pool_counter_max': pool_counter_max,
    }


def extract_process(compact, target_ids, target_specs, gdr_key,
                    gdr_threshold, initial_resources=None,
                    desire_weights=None, miss_cost_weights=None,
                    card_value_weights=None, ssr_ids=None,
                    weapon_character_map=None):
    from .gdr import SuccessChecker, compute_gdr_from_compact
    from .process_trace import infer_events

    checker = SuccessChecker(
        target_specs, gdr_key, gdr_threshold,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
    )

    val = compute_gdr_from_compact(
        compact, target_specs, gdr_key,
        desire_weights=desire_weights,
        miss_cost_weights=miss_cost_weights,
        card_value_weights=card_value_weights,
        ssr_ids=ssr_ids,
        weapon_character_map=weapon_character_map,
    )

    pool_events = infer_events(compact, target_ids)

    return {
        'pool_events': {pid: ev.event_type for pid, ev in pool_events.items()},
        'pool_event_details': {
            pid: {
                'event_type': ev.event_type,
                'pity_name': ev.pity_name,
                'draws': ev.draws,
                'counter_max': ev.counter_max,
            }
            for pid, ev in pool_events.items()
        },
        'success': checker.is_success(compact),
        'gdr_value': val,
    }


class DrawSequenceExtractor(StreamingAnalyzer):
    def __init__(self, max_keep=200, pool_end_times=None, target_ids=None,
                 ssr_ids=None, target_specs=None, initial_resources=None):
        self._max_keep = max_keep
        self._kept = []
        self._heatmap_data = {}
        self._cumulative_snapshots = {}
        self._transition_flags = []
        self._pool_end_times = pool_end_times or {}
        self._target_ids = target_ids or set()
        self._ssr_ids = ssr_ids or set()
        self._target_specs = target_specs or {}
        self._initial_resources = initial_resources or {}

    def on_result(self, compact):
        if compact is None:
            return
        if len(self._kept) < self._max_keep:
            self._kept.append({
                'draw_card_ids': list(compact.get('draw_card_ids', [])),
                'draw_pool_ids': list(compact.get('draw_pool_ids', [])),
                'draw_times': list(compact.get('draw_times', [])),
                'draw_pity': list(compact.get('draw_pity', [])),
                'draw_resources_consumed': list(compact.get('draw_resources_consumed', [])),
                'draw_resources_gained': list(compact.get('draw_resources_gained', [])),
            })

        self._update_heatmap(compact)
        self._update_cumulative(compact)
        self._update_transition(compact)

    def __call__(self, compact):
        self.on_result(compact)
        return None

    def get_result(self):
        return {
            'kept_sequences': self._kept,
            'heatmap_data': self._heatmap_data,
            'cumulative_snapshots': self._cumulative_snapshots,
            'transition_flags': self._transition_flags,
        }

    def get_kept_sequences(self):
        return self._kept

    def get_heatmap_data(self):
        return self._heatmap_data

    def get_cumulative_snapshots(self):
        return self._cumulative_snapshots

    def get_transition_flags(self):
        return self._transition_flags

    def _update_heatmap(self, compact):
        card_ids = compact.get('draw_card_ids', [])
        draw_resources_consumed = compact.get('draw_resources_consumed', [])
        draw_resources_gained = compact.get('draw_resources_gained', [])
        target_count = sum(self._target_specs.values()) if self._target_specs else 1

        obtained = 0
        cumulative_consumed = {}
        cumulative_gained = {}

        for i, cid in enumerate(card_ids):
            if cid in self._target_ids:
                obtained += 1

            if i < len(draw_resources_consumed) and draw_resources_consumed[i]:
                for k, v in draw_resources_consumed[i].items():
                    cumulative_consumed[k] = cumulative_consumed.get(k, 0) + v
            if i < len(draw_resources_gained) and draw_resources_gained[i]:
                for k, v in draw_resources_gained[i].items():
                    cumulative_gained[k] = cumulative_gained.get(k, 0) + v

            achievement_val = obtained / target_count
            resource_val = (
                self._initial_resources.get('draw_resource', 0)
                + cumulative_gained.get('draw_resource', 0)
                - cumulative_consumed.get('draw_resource', 0)
            )

            if i not in self._heatmap_data:
                self._heatmap_data[i] = {'achievement': [], 'resource': []}
            self._heatmap_data[i]['achievement'].append(achievement_val)
            self._heatmap_data[i]['resource'].append(resource_val)

    def _update_cumulative(self, compact):
        if not self._pool_end_times:
            return

        card_ids = compact.get('draw_card_ids', [])
        pool_ids = compact.get('draw_pool_ids', [])
        pity_flags = compact.get('draw_pity', [])
        times = compact.get('draw_times', [])
        draw_resources_consumed = compact.get('draw_resources_consumed', [])
        draw_resources_gained = compact.get('draw_resources_gained', [])

        sorted_pools = sorted(self._pool_end_times.items(), key=lambda x: x[1])

        for pool_id, end_time in sorted_pools:
            cumulative_card_counts = {}
            cumulative_draws = 0
            cumulative_pity = 0
            cumulative_consumed = {}
            cumulative_gained = {}

            for i in range(len(card_ids)):
                if i < len(times) and times[i] > end_time:
                    break
                cid = card_ids[i]
                cumulative_draws += 1
                cumulative_card_counts[cid] = cumulative_card_counts.get(cid, 0) + 1
                if i < len(pity_flags) and pity_flags[i]:
                    cumulative_pity += 1
                if i < len(draw_resources_consumed) and draw_resources_consumed[i]:
                    for k, v in draw_resources_consumed[i].items():
                        cumulative_consumed[k] = cumulative_consumed.get(k, 0) + v
                if i < len(draw_resources_gained) and draw_resources_gained[i]:
                    for k, v in draw_resources_gained[i].items():
                        cumulative_gained[k] = cumulative_gained.get(k, 0) + v

            if pool_id not in self._cumulative_snapshots:
                self._cumulative_snapshots[pool_id] = []
            self._cumulative_snapshots[pool_id].append({
                'cumulative_card_counts': cumulative_card_counts,
                'cumulative_draws': cumulative_draws,
                'cumulative_pity_draws': cumulative_pity,
                'cumulative_consumed': cumulative_consumed,
                'cumulative_gained': cumulative_gained,
            })

    def _update_transition(self, compact):
        if not self._pool_end_times:
            return

        card_ids = compact.get('draw_card_ids', [])
        times = compact.get('draw_times', [])

        sorted_pools = sorted(self._pool_end_times.items(), key=lambda x: x[1])

        flags = []
        for pool_id, end_time in sorted_pools:
            obtained = 0
            total_needed = sum(self._target_specs.values()) or 1
            for i in range(len(card_ids)):
                if i < len(times) and times[i] > end_time:
                    break
                if card_ids[i] in self._target_ids:
                    obtained += 1
            flags.append(obtained >= total_needed)

        self._transition_flags.append(flags)
