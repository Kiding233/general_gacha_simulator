from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

import numpy as np


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
    """流式结果收集器——边模拟边提取边丢弃，内存与模拟次数 N 无关。

    线程安全约束：此类设计为单线程使用。add_extractor 应在所有 on_result
    调用之前完成注册；on_result 不可并发调用。n_results += 1 非原子操作，
    多线程并发调用会产生数据竞争和提取结果错乱。
    """

    def __init__(self):
        self._extractors: Dict[str, Tuple[Callable, list]] = {}
        self.n_results = 0

    def add_extractor(self, name: str, extract_func: Callable[[Dict], Any]):
        """注册提取器。必须在首次 on_result 调用前完成所有注册。"""
        self._extractors[name] = (extract_func, [])

    def on_result(self, compact: Dict[str, Any]):
        """处理单次模拟结果。非线程安全——不可并发调用。"""
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
    draw_pity_names = compact.get('draw_pity_names', [])
    pool_resources_consumed = {}
    pool_resources_gained = {}
    pool_counter_max = {}
    pool_pity_names = {}
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
        if i < len(draw_pity_names) and draw_pity_names[i]:
            for name in draw_pity_names[i].split(','):
                pool_pity_names.setdefault(pid, set()).add(name)

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
        'pool_pity_names': {pid: sorted(names) for pid, names in pool_pity_names.items()},
    }


def extract_process(compact, target_ids, target_specs, gdr_key,
                    gdr_threshold, initial_resources=None,
                    desire_weights=None, miss_cost_weights=None,
                    card_value_weights=None, ssr_ids=None,
                    weapon_character_map=None):
    from .gdr import SuccessChecker
    from .process_trace import infer_events

    checker = SuccessChecker(
        target_specs, gdr_key, gdr_threshold,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
    )
    val = checker.compute_gdr(compact)

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
        'success': (val <= checker.gdr_threshold) if checker.lower_is_better else (val >= checker.gdr_threshold),
        'gdr_value': val,
    }


class WorkerLocalExtractor:
    """在 worker 进程内执行的提取器——每次 process() 返回提取包供主进程合并。

    与 DrawSequenceExtractor 不同：不内部累积状态，而是每次返回轻量提取包，
    由主进程负责合并。这样避免了跨进程状态同步的复杂性。
    """

    def __init__(self, pool_end_times=None, target_ids=None, ssr_ids=None,
                 target_specs=None, initial_resources=None, n_heatmap_bins=50,
                 max_keep=200):
        self._pool_end_times = dict(pool_end_times or {})
        self._target_ids = set(target_ids or [])
        self._ssr_ids = set(ssr_ids or [])
        self._target_specs = dict(target_specs or {})
        self._initial_resources = dict(initial_resources or {})
        self._n_heatmap_bins = n_heatmap_bins
        self._max_keep = max_keep
        self._target_count = sum(self._target_specs.values()) if self._target_specs else 1

        max_resource = max(self._initial_resources.get('draw_resource', 0), 1.0) * 2
        self._ach_bins = np.linspace(0, 1.05, n_heatmap_bins + 1)
        self._res_bins = np.linspace(0, max_resource, n_heatmap_bins + 1)

        # 预排序池结束时间（单次遍历用）
        self._sorted_pools = sorted(self._pool_end_times.items(), key=lambda x: x[1]) if self._pool_end_times else []
        self._n_pools = len(self._sorted_pools)

        # 保留序列计数（跨 compact 共享，前 max_keep 个才保留）
        self._kept_count = 0

    def process(self, compact: dict):
        """处理单次模拟结果，返回轻量提取包。"""
        if compact is None:
            return None

        # 1. 聚合提取（与原 extract_aggregate 一致）
        agg = extract_aggregate(compact)

        # 2. 提取序列（仅前 max_keep 个，节约传输）
        kept = None
        if self._kept_count < self._max_keep:
            kept = {
                'draw_card_ids': list(compact.get('draw_card_ids', [])),
                'draw_pool_ids': list(compact.get('draw_pool_ids', [])),
                'draw_times': list(compact.get('draw_times', [])),
                'draw_pity': list(compact.get('draw_pity', [])),
                'draw_resources_consumed': list(compact.get('draw_resources_consumed', [])),
                'draw_resources_gained': list(compact.get('draw_resources_gained', [])),
            }
            self._kept_count += 1

        # 3. 单次遍历：热力图分箱 + 累积快照 + 转变标记（1.3 合并优化）
        card_ids = compact.get('draw_card_ids', [])
        times = compact.get('draw_times', [])
        pity_flags = compact.get('draw_pity', [])
        draw_res_consumed = compact.get('draw_resources_consumed', [])
        draw_res_gained = compact.get('draw_resources_gained', [])

        n_draws = len(card_ids)
        heatmap_ach_bins = [0] * n_draws
        heatmap_res_bins = [0] * n_draws

        cumulative_snapshots = []   # 按池结束时间顺序的快照列表
        transition_flags = []       # 按池结束时间顺序的 bool 列表

        obtained = 0
        cum_consumed = {}
        cum_gained = {}
        cum_cards = {}
        cum_draws = 0
        cum_pity = 0
        pool_idx = 0

        for i in range(n_draws):
            cid = card_ids[i]
            t = times[i] if i < len(times) else float('inf')
            is_pity = pity_flags[i] if i < len(pity_flags) else False

            # 资源累积
            if i < len(draw_res_consumed) and draw_res_consumed[i]:
                for k, v in draw_res_consumed[i].items():
                    cum_consumed[k] = cum_consumed.get(k, 0) + v
            if i < len(draw_res_gained) and draw_res_gained[i]:
                for k, v in draw_res_gained[i].items():
                    cum_gained[k] = cum_gained.get(k, 0) + v

            # 目标计数
            if cid in self._target_ids:
                obtained += 1

            # 热力图分箱索引
            ach_val = obtained / self._target_count
            res_val = (self._initial_resources.get('draw_resource', 0)
                       + cum_gained.get('draw_resource', 0)
                       - cum_consumed.get('draw_resource', 0))
            ach_bin = np.digitize(ach_val, self._ach_bins) - 1
            heatmap_ach_bins[i] = max(0, min(self._n_heatmap_bins - 1, ach_bin))
            res_bin = np.digitize(res_val, self._res_bins) - 1
            heatmap_res_bins[i] = max(0, min(self._n_heatmap_bins - 1, res_bin))

            # 累积快照 + 转变：当前抽卡时间越过池结束时保存快照
            cum_draws += 1
            cum_cards[cid] = cum_cards.get(cid, 0) + 1
            if is_pity:
                cum_pity += 1

            while pool_idx < self._n_pools and t > self._sorted_pools[pool_idx][1]:
                pid = self._sorted_pools[pool_idx][0]
                pool_end_res = compact.get('pool_end_resources', {}).get(pid, {})
                cumulative_snapshots.append({
                    'pool_id': pid,
                    'cumulative_card_counts': dict(cum_cards),
                    'cumulative_draws': cum_draws,
                    'cumulative_pity_draws': cum_pity,
                    'cumulative_consumed': dict(cum_consumed),
                    'cumulative_gained': dict(cum_gained),
                    'pool_end_resource': pool_end_res.get('draw_resource', 0.0),
                })
                transition_flags.append(self._check_success(cum_cards))
                pool_idx += 1

        # 处理剩余池（所有抽卡在最后池结束前完成）
        while pool_idx < self._n_pools:
            pid = self._sorted_pools[pool_idx][0]
            pool_end_res = compact.get('pool_end_resources', {}).get(pid, {})
            cumulative_snapshots.append({
                'pool_id': pid,
                'cumulative_card_counts': dict(cum_cards),
                'cumulative_draws': cum_draws,
                'cumulative_pity_draws': cum_pity,
                'cumulative_consumed': dict(cum_consumed),
                'cumulative_gained': dict(cum_gained),
                'pool_end_resource': pool_end_res.get('draw_resource', 0.0),
            })
            transition_flags.append(self._check_success(cum_cards))
            pool_idx += 1

        return {
            'aggregate': agg,
            'kept': kept,
            'heatmap_ach_bins': heatmap_ach_bins,
            'heatmap_res_bins': heatmap_res_bins,
            'cumulative_snapshots': cumulative_snapshots,
            'transition_flags': transition_flags,
        }

    def _check_success(self, cumulative_cards: dict) -> bool:
        if not self._target_specs:
            return False
        for cid, qty in self._target_specs.items():
            if cumulative_cards.get(cid, 0) < qty:
                return False
        return True


def merge_extraction_packets(packets: list, heatmap_config: dict = None) -> dict:
    """合并多个 WorkerLocalExtractor.process() 返回的提取包。

    在主进程中调用，将各 worker 的轻量提取包合并为等价于
    SharedResultCollector + DrawSequenceExtractor 的累积输出。
    """
    max_keep = (heatmap_config or {}).get('max_keep', 200)

    merged_agg = []
    merged_kept = []
    merged_transitions = []
    merged_cum = {}
    merged_hach = {}
    merged_hres = {}
    n_results = 0

    for pkt in packets:
        if pkt is None:
            continue
        n_results += 1
        merged_agg.append(pkt.get('aggregate'))

        # 保留序列
        kept = pkt.get('kept')
        if kept is not None and len(merged_kept) < max_keep:
            merged_kept.append(kept)

        # 累积快照
        for snap in pkt.get('cumulative_snapshots', []):
            pid = snap.pop('pool_id', None)
            if pid:
                merged_cum.setdefault(pid, []).append(snap)

        # 转变标记
        merged_transitions.append(pkt.get('transition_flags', []))

        # 热力图：将分箱索引转为直方图累加
        ach_bins = pkt.get('heatmap_ach_bins', [])
        res_bins = pkt.get('heatmap_res_bins', [])
        n_bins = (heatmap_config or {}).get('n_heatmap_bins', 50)
        for i, b in enumerate(ach_bins):
            if i not in merged_hach:
                merged_hach[i] = np.zeros(n_bins, dtype=np.int32)
            merged_hach[i][b] += 1
        for i, b in enumerate(res_bins):
            if i not in merged_hres:
                merged_hres[i] = np.zeros(n_bins, dtype=np.int32)
            merged_hres[i][b] += 1

    return {
        'aggregates': merged_agg,
        'kept_sequences': merged_kept,
        'cumulative_snapshots': merged_cum,
        'transition_flags': merged_transitions,
        'heatmap_ach': merged_hach,
        'heatmap_res': merged_hres,
        'n_results': n_results,
    }


class DrawSequenceExtractor(StreamingAnalyzer):
    def __init__(self, max_keep=200, pool_end_times=None, target_ids=None,
                 ssr_ids=None, target_specs=None, initial_resources=None,
                 n_heatmap_bins=None):
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
        self._n_heatmap_bins = n_heatmap_bins or 50
        max_resource = max(self._initial_resources.get('draw_resource', 0), 1.0) * 2
        self._heatmap_bins = {
            'achievement': np.linspace(0, 1.05, self._n_heatmap_bins + 1),
            'resource': np.linspace(0, max_resource, self._n_heatmap_bins + 1),
        }
        # 资源分箱上限为 initial_resource × 2。含日收入的场景中实际资源可能超出此值，
        # 超出部分被 clip 到最后一个 bin，导致该 bin 异常偏高。
        # 此处的折衷：上限取 max(2×初始资源, 硬保底成本×2) 作为底线覆盖。
        self._resource_max_clip = max_resource

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
        return {
            'data': self._heatmap_data,
            'bins': getattr(self, '_heatmap_bins', {}),
        }

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
                self._heatmap_data[i] = {
                    'achievement': np.zeros(self._n_heatmap_bins, dtype=np.int32),
                    'resource': np.zeros(self._n_heatmap_bins, dtype=np.int32),
                }

            ach_bin = np.digitize(achievement_val, self._heatmap_bins['achievement']) - 1
            ach_bin = max(0, min(self._n_heatmap_bins - 1, ach_bin))
            self._heatmap_data[i]['achievement'][ach_bin] += 1

            res_bin = np.digitize(resource_val, self._heatmap_bins['resource']) - 1
            res_bin = max(0, min(self._n_heatmap_bins - 1, res_bin))
            self._heatmap_data[i]['resource'][res_bin] += 1

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
            pool_end_res = compact.get('pool_end_resources', {}).get(pool_id, {})
            self._cumulative_snapshots[pool_id].append({
                'cumulative_card_counts': cumulative_card_counts,
                'cumulative_draws': cumulative_draws,
                'cumulative_pity_draws': cumulative_pity,
                'cumulative_consumed': cumulative_consumed,
                'cumulative_gained': cumulative_gained,
                'pool_end_resource': pool_end_res.get('draw_resource', 0.0),
            })

    def _update_transition(self, compact):
        if not self._pool_end_times:
            return

        card_ids = compact.get('draw_card_ids', [])
        times = compact.get('draw_times', [])

        sorted_pools = sorted(self._pool_end_times.items(), key=lambda x: x[1])

        flags = []
        for pool_id, end_time in sorted_pools:
            cumulative = {}
            for i in range(len(card_ids)):
                if i < len(times) and times[i] > end_time:
                    break
                cid = card_ids[i]
                cumulative[cid] = cumulative.get(cid, 0) + 1

            success = True
            if not self._target_specs:
                success = False
            else:
                for cid, qty in self._target_specs.items():
                    if cumulative.get(cid, 0) < qty:
                        success = False
                        break
            flags.append(success)

        self._transition_flags.append(flags)
