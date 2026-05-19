from typing import List, Dict, Any
import numpy as np
from ..core import InfoVector, GeneralizedDropRate


class AnalysisService:
    def __init__(self, gdr_functions: List[GeneralizedDropRate] = None):
        self.gdr_functions = gdr_functions or []

    def compute_gdr_distribution(
        self, history: List[InfoVector]
    ) -> Dict[str, List[float]]:
        result = {gdr.name(): [] for gdr in self.gdr_functions}
        for t in range(len(history)):
            for gdr in self.gdr_functions:
                value = gdr.compute(t, history)
                result[gdr.name()].append(value)
        return result

    def compute_pmf(
        self, values: List[float], bins: int = 20
    ) -> Dict[str, Any]:
        hist, edges = np.histogram(values, bins=bins)
        pmf = hist / len(values) if len(values) > 0 else []
        return {
            'pmf': pmf.tolist(),
            'edges': edges.tolist(),
            'bin_centers': ((edges[:-1] + edges[1:]) / 2).tolist(),
        }

    def compute_cdf(
        self, values: List[float], bins: int = 20
    ) -> Dict[str, Any]:
        sorted_values = sorted(values)
        cdf = np.arange(1, len(sorted_values) + 1) / len(sorted_values)
        return {
            'cdf': cdf.tolist(),
            'values': sorted_values,
        }

    def compute_basic_stats(
        self, history: List[InfoVector]
    ) -> Dict[str, Any]:
        draw_history = [iv for iv in history if iv.action_type == 'draw']
        card_counts = {}
        for iv in draw_history:
            card_counts[iv.card_id] = card_counts.get(iv.card_id, 0) + 1

        total_resources_spent = {}
        for iv in draw_history:
            for resource, amount in iv.resources_consumed.items():
                total_resources_spent[resource] = total_resources_spent.get(resource, 0) + amount

        return {
            'total_draws': len(draw_history),
            'total_wait_time': sum(iv.time_elapsed for iv in history if iv.action_type == 'wait'),
            'card_counts': card_counts,
            'total_resources_spent': total_resources_spent,
        }

    def compute_time_series(
        self, history: List[InfoVector], value_name: str
    ) -> List[Dict[str, Any]]:
        result = []
        cumulative = 0
        for iv in history:
            if iv.action_type == 'draw':
                if iv.card_id == value_name:
                    cumulative += 1
            result.append({
                'action_index': iv.action_index,
                'real_time': iv.real_time_after,
                'cumulative': cumulative,
            })
        return result
