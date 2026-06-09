import functools
import itertools
import math
import statistics
from collections import Counter
from typing import Dict, List, Optional, Tuple

from .process_trace import SampleTrace, PoolEvent


def _z_from_conf_level(conf_level: float) -> float:
    """从置信水平计算 z 值（标准正态分位数）。"""
    alpha = 1.0 - conf_level
    return statistics.NormalDist().inv_cdf(1.0 - alpha / 2.0)


def wilson_ci(successes: int, total: int, conf_level: float = 0.95) -> Tuple[float, float]:
    """Wilson 得分区间 (Brown, Cai & DasGupta 2001)。

    在极端概率和小样本下覆盖率远优于 Wald 区间。N=0 时返回 [0, 1]。
    """
    if total == 0:
        return 0.0, 1.0
    z = _z_from_conf_level(conf_level)
    p = successes / total
    n = total
    z2 = z * z
    denom = 1.0 + z2 / n
    center = (p + z2 / (2.0 * n)) / denom
    margin = z * math.sqrt((p * (1.0 - p) + z2 / (4.0 * n)) / n) / denom
    return max(0.0, center - margin), min(1.0, center + margin)


def _resolve_event_type(ev: PoolEvent) -> str:
    et = ev.event_type
    if et == 'pity_hit' and ev.pity_name:
        return f'pity_hit:{ev.pity_name}'
    return et


def to_event_type_sequence(events: List[PoolEvent]) -> Tuple[str, ...]:
    return tuple(_resolve_event_type(ev) for ev in events)


def to_event_type_set(events: List[PoolEvent]) -> Tuple[str, ...]:
    return tuple(sorted(set(_resolve_event_type(ev) for ev in events)))


EVENT_TYPE_LABELS = {
    'pity_hit': '保底出',
    'early_hit': '提前出',
    'miss': '没出',
    'skip': '跳过',
    'ignore': '忽略',
    'exchange': '兑换',
    'no_exchange': '未兑换',
    'resource_draw': '资源抽取',
    'resource_ignore': '资源跳过',
}


def _build_dynamic_labels(counts) -> Dict[str, str]:
    labels = {}
    for et in counts:
        if et == 'pity_hit':
            labels[et] = '保底出'
        elif et.startswith('pity_hit:'):
            pity_name = et.split(':', 1)[1]
            labels[et] = f'保底出:{pity_name}'
        elif et in EVENT_TYPE_LABELS:
            labels[et] = EVENT_TYPE_LABELS[et]
        else:
            labels[et] = et
    return labels


def _get_event_label(event_type: str) -> str:
    if event_type == 'pity_hit':
        return '保底出'
    if event_type.startswith('pity_hit:'):
        return f'保底出:{event_type.split(":", 1)[1]}'
    return EVENT_TYPE_LABELS.get(event_type, event_type)


def get_event_type_order(event_types) -> list:
    base, pity = [], []
    for et in event_types:
        if et.startswith('pity_hit:'):
            pity.append(et)
        else:
            base.append(et)
    base_order = ['early_hit', 'miss', 'skip', 'ignore', 'exchange', 'no_exchange']
    base_sorted = [et for et in base_order if et in base] + sorted(set(base) - set(base_order))
    return base_sorted + sorted(pity)


def to_event_count_set(events: List[PoolEvent]) -> Tuple[Tuple[str, int], ...]:
    counts = Counter()
    for ev in events:
        counts[_resolve_event_type(ev)] += 1
    keys = get_event_type_order(counts.keys())
    return tuple((k, counts[k]) for k in keys)

CUSTOM_OPS = ('any', '=', '>=', '<=', '>', '<')


def to_custom_pattern(events: List[PoolEvent],
                      constraints: Optional[Dict[str, Tuple[str, int]]] = None) -> Dict[str, str]:
    if constraints is None:
        constraints = {}

    raw_counts = Counter()
    for ev in events:
        raw_counts[_resolve_event_type(ev)] += 1

    constrained_types = {et for et, (op, _) in constraints.items() if op != 'any'}
    dynamic_labels = _build_dynamic_labels(raw_counts)

    result = {}
    for event_type, label in dynamic_labels.items():
        count = raw_counts.get(event_type, 0)

        if constrained_types and event_type not in constrained_types:
            continue

        if event_type in constraints:
            op, n = constraints[event_type]
            if op == 'any':
                continue
            elif op == '>=':
                bucket = f'{label}≥{n}' if count >= n else f'{label}<{n}'
            elif op == '=':
                bucket = f'{label}={n}' if count == n else f'{label}≠{n}'
            elif op == '<=':
                bucket = f'{label}≤{n}' if count <= n else f'{label}>{n}'
            elif op == '>':
                bucket = f'{label}>{n}' if count > n else f'{label}≤{n}'
            elif op == '<':
                bucket = f'{label}<{n}' if count < n else f'{label}≥{n}'
            else:
                bucket = f'{label}={count}'
        else:
            bucket = f'{label}={count}'

        result[event_type] = bucket

    return result


def _enumerate_custom_combinations(constraints: Dict[str, Tuple[str, int]]) -> List[Dict[str, str]]:
    constrained_types = [et for et in constraints if constraints[et][0] != 'any']
    if not constrained_types:
        return []

    bucket_pairs = []
    for event_type in constrained_types:
        op, n = constraints[event_type]
        label = _get_event_label(event_type)
        if op == '>=':
            bucket_pairs.append([(event_type, f'{label}≥{n}'), (event_type, f'{label}<{n}')])
        elif op == '=':
            bucket_pairs.append([(event_type, f'{label}={n}'), (event_type, f'{label}≠{n}')])
        elif op == '<=':
            bucket_pairs.append([(event_type, f'{label}≤{n}'), (event_type, f'{label}>{n}')])
        elif op == '>':
            bucket_pairs.append([(event_type, f'{label}>{n}'), (event_type, f'{label}≤{n}')])
        elif op == '<':
            bucket_pairs.append([(event_type, f'{label}<{n}'), (event_type, f'{label}≥{n}')])

    combinations = []
    for combo in itertools.product(*bucket_pairs):
        result = {}
        for event_type, bucket in combo:
            result[event_type] = bucket
        combinations.append(result)

    return combinations


def to_raw_trajectory(events: List[PoolEvent]) -> Tuple[str, ...]:
    parts = []
    for ev in events:
        if ev.event_type == 'pity_hit' and ev.pity_name:
            parts.append(f'pity_hit:{ev.pity_name}')
        elif ev.event_type == 'early_hit' and ev.draws > 0:
            parts.append(f'early_hit({ev.draws})')
        else:
            parts.append(ev.event_type)
    return tuple(parts)


def to_success_sequence(pool_success: Dict[str, bool]) -> Tuple[bool, ...]:
    return tuple(pool_success.get(pid, False) for pid in sorted(pool_success.keys()))


def to_success_set(pool_success: Dict[str, bool]) -> Tuple[int, int]:
    vals = list(pool_success.values())
    return (sum(vals), len(vals) - sum(vals))


def to_success_count(pool_success: Dict[str, bool]) -> int:
    return sum(pool_success.values())


def to_success_custom(pool_success: Dict[str, bool], op: str = '>=', n: int = 1) -> str:
    total = sum(pool_success.values())
    if op == '>=':
        return f'≥{n}' if total >= n else f'<{n}'
    elif op == '=':
        return f'={n}' if total == n else f'≠{n}'
    elif op == '<=':
        return f'≤{n}' if total <= n else f'>{n}'
    elif op == '>':
        return f'>{n}' if total > n else f'≤{n}'
    elif op == '<':
        return f'<{n}' if total < n else f'≥{n}'
    return str(total)


def _enumerate_success_custom_buckets(op: str, n: int) -> List[str]:
    if op == '>=':
        return [f'≥{n}', f'<{n}']
    elif op == '=':
        return [f'={n}', f'≠{n}']
    elif op == '<=':
        return [f'≤{n}', f'>{n}']
    elif op == '>':
        return [f'>{n}', f'≤{n}']
    elif op == '<':
        return [f'<{n}', f'≥{n}']
    return []


EVENT_MODE_MAP = {
    'raw': to_raw_trajectory,
    'sequence': to_event_type_sequence,
    'set': to_event_type_set,
    'count_set': to_event_count_set,
    'custom': to_custom_pattern,
}

SUCCESS_MODE_MAP = {
    'sequence': to_success_sequence,
    'set': to_success_set,
    'count': to_success_count,
    'custom': to_success_custom,
}


def compute_aa(traces: List[SampleTrace],
               event_mode: str = 'sequence',
               constraints: Optional[Dict] = None) -> List[Dict]:
    base_func = EVENT_MODE_MAP.get(event_mode, to_event_type_sequence)
    if event_mode == 'custom' and constraints:
        key_func = functools.partial(base_func, constraints=constraints)
    else:
        key_func = base_func

    pattern_counts = Counter()
    for trace in traces:
        key = key_func(trace.events)
        pattern_counts[_hashable(key)] += 1

    total = len(traces)
    if total == 0:
        return []

    results = []
    cumulative = 0.0
    for pattern_key, count in pattern_counts.most_common():
        prob = count / total
        cumulative += prob
        results.append({
            'pattern': _unhashable(pattern_key),
            'count': count,
            'probability': prob,
            'cumulative_probability': cumulative,
        })

    if event_mode == 'custom' and constraints:
        non_any_constraints = {et: v for et, v in constraints.items() if v[0] != 'any'}
        if non_any_constraints:
            all_combos = _enumerate_custom_combinations(constraints)
            existing_keys = set()
            for r in results:
                pattern = r['pattern']
                if isinstance(pattern, dict):
                    ck = tuple(sorted(pattern.items()))
                    existing_keys.add(ck)

            for combo in all_combos:
                ck = tuple(sorted(combo.items()))
                if ck not in existing_keys:
                    results.append({
                        'pattern': combo,
                        'count': 0,
                        'probability': 0.0,
                        'cumulative_probability': cumulative,
                    })

    return results


def compute_bb(traces: List[SampleTrace],
               success_mode: str = 'count',
               success_n: Optional[int] = None,
               success_op: Optional[str] = None) -> List[Dict]:
    base_func = SUCCESS_MODE_MAP.get(success_mode, to_success_count)
    if success_mode == 'custom' and success_op is not None and success_n is not None:
        key_func = functools.partial(base_func, op=success_op, n=success_n)
    else:
        key_func = base_func

    pattern_counts = Counter()
    for trace in traces:
        key = key_func(trace.pool_success)
        pattern_counts[_hashable(key)] += 1

    total = len(traces)
    if total == 0:
        return {
            'pattern_table': [],
            'pool_success_rates': {},
            'all_fail_prob': 0.0,
            'all_success_prob': 0.0,
            'pool_ids': [],
            'total': 0,
        }

    pool_ids = sorted(set(pid for t in traces for pid in t.pool_success))
    pool_success_counts = Counter()
    for trace in traces:
        for pid in pool_ids:
            if trace.pool_success.get(pid, False):
                pool_success_counts[pid] += 1

    pool_success_rates = {
        pid: pool_success_counts[pid] / total for pid in pool_ids
    }

    all_fail = sum(1 for t in traces if not any(t.pool_success.values()))
    all_success = sum(1 for t in traces if all(t.pool_success.values()))

    results = []
    cumulative = 0.0
    for pattern_key, count in pattern_counts.most_common():
        prob = count / total
        cumulative += prob
        results.append({
            'pattern': _unhashable(pattern_key),
            'count': count,
            'probability': prob,
            'cumulative_probability': cumulative,
        })

    if success_mode == 'custom' and success_op is not None and success_n is not None:
        all_buckets = _enumerate_success_custom_buckets(success_op, success_n)
        existing_keys = set()
        for r in results:
            existing_keys.add(_hashable(r['pattern']))
        for bucket in all_buckets:
            if _hashable(bucket) not in existing_keys:
                results.append({
                    'pattern': bucket,
                    'count': 0,
                    'probability': 0.0,
                    'cumulative_probability': cumulative,
                })

    return {
        'pattern_table': results,
        'pool_success_rates': pool_success_rates,
        'all_fail_prob': all_fail / total,
        'all_success_prob': all_success / total,
        'pool_ids': pool_ids,
        'total': total,
    }


def compute_ab(traces: List[SampleTrace],
               event_mode: str = 'sequence',
               success_mode: str = 'count',
               constraints: Optional[Dict] = None,
               success_n: Optional[int] = None,
               success_op: Optional[str] = None,
               conf_level: float = 0.95) -> List[Dict]:
    base_event_func = EVENT_MODE_MAP.get(event_mode, to_event_type_sequence)
    if event_mode == 'custom' and constraints:
        event_func = functools.partial(base_event_func, constraints=constraints)
    else:
        event_func = base_event_func
    base_success_func = SUCCESS_MODE_MAP.get(success_mode, to_success_count)
    if success_mode == 'custom' and success_op is not None and success_n is not None:
        success_func = functools.partial(base_success_func, op=success_op, n=success_n)
    else:
        success_func = base_success_func

    pattern_data = {}
    for trace in traces:
        event_key = _hashable(event_func(trace.events))
        success_key = _hashable(success_func(trace.pool_success))

        if event_key not in pattern_data:
            pattern_data[event_key] = {
                'total': 0,
                'success_counts': Counter(),
            }
        pattern_data[event_key]['total'] += 1
        pattern_data[event_key]['success_counts'][success_key] += 1

    results = []
    for event_key, data in sorted(pattern_data.items(), key=lambda x: -x[1]['total']):
        total_in_pattern = data['total']
        success_dist = data['success_counts']

        overall_success = sum(
            1 for t in traces
            if _hashable(event_func(t.events)) == event_key and t.is_success
        )

        wi_lo, wi_hi = wilson_ci(overall_success, total_in_pattern, conf_level)
        results.append({
            'event_pattern': _unhashable(event_key),
            'success_distribution': {str(_unhashable(k)): v / total_in_pattern for k, v in success_dist.items()},
            'overall_success_prob': overall_success / total_in_pattern,
            'wilson_ci_lower': wi_lo,
            'wilson_ci_upper': wi_hi,
            'count': total_in_pattern,
            'success_count': overall_success,
            'failure_count': total_in_pattern - overall_success,
            'low_sample': total_in_pattern < 5,
        })

    return results


def compute_ba(traces: List[SampleTrace],
               event_mode: str = 'sequence',
               success_mode: str = 'count',
               constraints: Optional[Dict] = None,
               success_op: Optional[str] = None,
               conf_level: float = 0.95) -> List[Dict]:
    base_event_func = EVENT_MODE_MAP.get(event_mode, to_event_type_sequence)
    if event_mode == 'custom' and constraints:
        event_func = functools.partial(base_event_func, constraints=constraints)
    else:
        event_func = base_event_func

    success_group = {'success': [], 'failure': []}
    for trace in traces:
        group = 'success' if trace.is_success else 'failure'
        event_key = _hashable(event_func(trace.events))
        success_group[group].append(event_key)

    success_counts = Counter(success_group['success'])
    failure_counts = Counter(success_group['failure'])

    total_success = len(success_group['success'])
    total_failure = len(success_group['failure'])

    all_patterns = set(success_counts.keys()) | set(failure_counts.keys())

    results = []
    for pattern_key in sorted(all_patterns, key=lambda k: -(success_counts.get(k, 0) + failure_counts.get(k, 0))):
        sc = success_counts.get(pattern_key, 0)
        fc = failure_counts.get(pattern_key, 0)
        total_pattern = sc + fc

        p_given_success = sc / total_success if total_success > 0 else 0
        p_given_failure = fc / total_failure if total_failure > 0 else 0
        ratio = p_given_success / p_given_failure if p_given_failure > 0 else None

        p_s_lo, p_s_hi = wilson_ci(sc, total_success, conf_level) if total_success > 0 else (0.0, 1.0)
        p_f_lo, p_f_hi = wilson_ci(fc, total_failure, conf_level) if total_failure > 0 else (0.0, 1.0)

        results.append({
            'event_pattern': _unhashable(pattern_key),
            'p_given_success': p_given_success,
            'p_given_failure': p_given_failure,
            'ratio': ratio,
            'p_given_success_wilson_lower': p_s_lo,
            'p_given_success_wilson_upper': p_s_hi,
            'p_given_failure_wilson_lower': p_f_lo,
            'p_given_failure_wilson_upper': p_f_hi,
            'count': total_pattern,
            'low_sample': total_pattern < 5,
        })

    return results


def _hashable(obj):
    if isinstance(obj, dict):
        return tuple(sorted(obj.items()))
    if isinstance(obj, list):
        return tuple(obj)
    if isinstance(obj, set):
        return frozenset(obj)
    return obj


def _unhashable(obj):
    if isinstance(obj, tuple):
        if len(obj) > 0 and all(isinstance(item, tuple) and len(item) == 2 for item in obj):
            try:
                return dict(obj)
            except Exception:
                pass
        try:
            return list(obj)
        except Exception:
            return obj
    if isinstance(obj, frozenset):
        return set(obj)
    return obj
