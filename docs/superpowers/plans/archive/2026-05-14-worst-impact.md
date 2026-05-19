# 最差后期影响分析 — 实现计划（修订版 v3）

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现"最差后期影响"分析模块，基于条件分布的下尾分位数评估最终剩余资源能支撑多少个新池子。

**Architecture:** 核心引擎 `WorstImpactAnalyzer` 计算两个维度（大保底覆盖、可抽新池子数分布+期望），UI 面板 `WorstImpactPanel` 提供配置和可视化，复用现有 `GachaService` 模拟引擎。

**Tech Stack:** Python, PyQt6, matplotlib, numpy, 现有模拟引擎复用

---

## 文件结构

| 文件 | 职责 |
|------|------|
| `gacha_simulator/core/worst_impact.py` | 核心分析引擎：条件分布构建、两个维度计算 |
| `gacha_simulator/gui/worst_impact_panel.py` | UI 面板：配置区、结果区、图表、表格 |
| `gacha_simulator/gui/main_window.py` | 集成：替换占位符、连接信号 |
| `tests/core/test_worst_impact.py` | 单元测试 |

---

## 关键发现（已调查）

**模拟结果数据结构**（来自 `gacha_service.py`）：

```python
sim_result = {
    'final_resources': {'draw_resource': 500, ...},  # ← 只用这个
    'card_counts': {'char_a': 1, 'char_b': 0, ...},
    'pool_end_pity_states': {'pool_1': {'counters': {'pity': 45}}},
    ...
}
```

**重要**：
1. 只使用 `final_resources`，不提取 `pool_end_resources`
2. "链式模拟" = 循环调用 `GachaService.run_simulation_compact`
3. 没有新的模拟引擎，只有对现有引擎的复用
4. `run_simulation_compact` 返回 `pool_end_pity_states` 而非 `final_pity_state`
5. `GachaService.__init__` 参数名是 `target_cards`（非 `target_set`）
6. `PityEngine` 构造需要 `(pool_specs, pity_defs, behaviors)` 三个参数
7. `Pool` 对象有 `rewards`、`available_until` 等属性，但没有 `bindings`
8. `TargetCard` 需要 `pool_ids` 参数

---

## Task 1: 核心分析引擎 `worst_impact.py`

**Files:**
- Create: `gacha_simulator/core/worst_impact.py`
- Test: `tests/core/test_worst_impact.py`

### Step 1.1: 实现辅助函数 `_check_success_from_counts`

```python
from typing import Dict, Set


def _check_success_from_counts(card_counts: Dict[str, int],
                                target_specs: Dict[str, int]) -> bool:
    for card_id, qty in target_specs.items():
        if card_counts.get(card_id, 0) < qty:
            return False
    return True
```

### Step 1.2: 实现 `ConditionalResourceDistribution`

```python
from typing import List, Dict
from ..core.distribution import EmpiricalDistribution


class ConditionalResourceDistribution:
    def __init__(self, simulation_results, target_specs,
                 resource='draw_resource'):
        self.success_resources: List[float] = []
        self.failure_resources: List[float] = []

        for r in simulation_results:
            is_success = _check_success_from_counts(
                r.get('card_counts', {}), target_specs
            )
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
```

### Step 1.3: 实现 `WorstImpactAnalyzer`

> v3 变更：删除模式B（阈值连续），只保留分布+期望模式。
> 原因：模式B用平均剩余资源做确定性近似，丢失不确定性信息，结果不如模式A准确。
> 而模式A的分布 P(X≥k) 已经能回答阈值问题，模式B完全冗余。

```python
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Dict, Optional, List, Set
from collections import defaultdict


DAY = 86400


@dataclass
class WorstImpactResult:
    worst_resource: float
    pity_coverage: float
    pool_distribution: Dict[int, float] = field(default_factory=dict)
    expected_pools: float = 0.0

    def get_p_ge(self, k: int) -> float:
        """P(X >= k)：至少连续成功k个池子的概率"""
        return sum(p for kk, p in self.pool_distribution.items() if kk >= k)

    def get_max_consecutive_at_threshold(self, threshold: float) -> int:
        """给定阈值，推导最大连续数（从分布中计算，无需额外模拟）"""
        for k in sorted(self.pool_distribution.keys(), reverse=True):
            if self.get_p_ge(k) >= threshold:
                return k
        return 0


class _TargetPoolEnd:
    def __init__(self, end_time: float):
        self.end_time = end_time

    def check(self, state, history=None, stats=None):
        return state.real_time >= self.end_time

    def description(self):
        return ""


class _DrawTargetStrategy:
    lookahead = None

    def __init__(self, target_card_ids: Set[str], pool_id: str):
        self.target_card_ids = target_card_ids
        self.pool_id = pool_id
        self.acquired: Dict[str, int] = {}

    def select_action(self, state, history, current_pools,
                      future_schedules, target_cards, stop_cond):
        from ..core.action import DrawAction, WaitAction

        for pool in current_pools:
            if pool.id == self.pool_id and state.can_afford(pool.cost):
                return DrawAction(pool_id=pool.id)

        wait_time = 86400
        for pool in current_pools:
            if (hasattr(pool, 'available_until') and pool.available_until
                    and pool.available_until > state.real_time):
                wait_time = min(wait_time, pool.available_until - state.real_time)
        if wait_time <= 0:
            wait_time = 3600
        return WaitAction(duration=wait_time)

    def observe(self, iv):
        if iv.action_type == 'draw' and iv.card_id:
            self.acquired[iv.card_id] = self.acquired.get(iv.card_id, 0) + 1


class WorstImpactAnalyzer:
    def __init__(self, simulation_results, target_specs, store):
        self.simulation_results = simulation_results
        self.target_specs = target_specs
        self.store = store
        self.cond_dist = None
        self._pity_engine = None
        self._ref_pool_entry = None
        self._featured_ids: Set[str] = set()
        self._ssr_ids: Set[str] = set()

    def analyze(self, condition='failure', alpha=0.05,
                num_simulations=500, progress_callback=None):
        self.cond_dist = ConditionalResourceDistribution(
            self.simulation_results, self.target_specs
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
        from ..core.pool import Pool, Reward
        from ..core.config_store import PoolEntry

        pool_entries = [pe for pe in self.store.pools if pe.enabled]
        if not pool_entries:
            return

        self._ref_pool_entry = pool_entries[0]
        pe = self._ref_pool_entry

        cost_str = getattr(pe, 'cost', 'draw_resource:160')
        parsed_cost = self._parse_cost_string(cost_str)

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
        for r, prob in rewards:
            rarity = r.extra_info.get('rarity', '').upper()
            featured = r.extra_info.get('featured', False)
            if rarity == 'SSR':
                self._ssr_ids.add(r.id)
                if featured:
                    self._featured_ids.add(r.id)

        if not self._featured_ids and self._ssr_ids:
            self._featured_ids = set(self._ssr_ids)

        pool_duration_days = pe.end_day - pe.start_day
        if pool_duration_days <= 0:
            pool_duration_days = 21

        self._pool_duration = pool_duration_days * DAY
        self._parsed_cost = parsed_cost
        self._rewards = rewards

        self._pity_engine = self._build_pity_engine()

    def _build_pity_engine(self):
        from ..core.pity import (
            PityEngine, PoolPitySpec, PityDefParsed,
            SoftPityBehavior, HardPityBehavior,
        )

        if not self.store.pity.enabled:
            return None

        pity_defs = {}
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

        import fnmatch
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

    @staticmethod
    def _parse_cost_string(cost_str):
        if not cost_str:
            return [{'draw_resource': 160}]
        parts = cost_str.split(',')
        result = []
        for part in parts:
            if ':' in part:
                rid, amt = part.split(':', 1)
                try:
                    result.append({rid.strip(): int(amt.strip())})
                except ValueError:
                    result.append({'draw_resource': 160})
            else:
                result.append({'draw_resource': 160})
        return result if result else [{'draw_resource': 160}]

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
        from ..core.pool import Pool, Reward

        pid = f'_worst_impact_pool_{pool_index}'
        available_from = 0
        available_until = self._pool_duration

        pool = Pool(
            id=pid,
            name=f'新池子#{pool_index}',
            cost=self._parsed_cost,
            rewards=self._rewards,
            available_from=available_from,
            available_until=available_until,
        )
        return pool

    def _build_target_card_set(self, pool_id: str):
        from ..core.target_card import TargetCard, TargetCardSet

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

        for sim_idx in range(num_simulations):
            current_resource = resource
            current_pity = dict(pity_state)
            consecutive = 0
            pool_index = 0

            while current_resource > 0:
                pool = self._create_new_pool(pool_index)
                target_set = self._build_target_card_set(pool.id)
                strategy = _DrawTargetStrategy(self._featured_ids, pool.id)
                stop_cond = _TargetPoolEnd(pool.available_until)

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
        from ..service.gacha_service import GachaService
        from ..core.state import GachaState
        from ..core.pity import PityState

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
        success = _check_success_from_counts(card_counts, self.target_specs)

        remaining_resource = result.get('final_resources', {}).get('draw_resource', 0)

        final_pity_state = {}
        pool_end_pity = result.get('pool_end_pity_states', {})
        if pool_end_pity:
            last_pool_id = pool.id
            if last_pool_id in pool_end_pity:
                final_pity_state = pool_end_pity[last_pool_id].get('counters', {})
            else:
                last_key = list(pool_end_pity.keys())[-1]
                final_pity_state = pool_end_pity[last_key].get('counters', {})

        return {
            'success': success,
            'remaining_resource': remaining_resource,
            'final_pity_state': final_pity_state,
        }
```

### Step 1.4: 编写单元测试

```python
import pytest
from gacha_simulator.core.worst_impact import (
    _check_success_from_counts,
    ConditionalResourceDistribution,
    WorstImpactResult,
)


def test_check_success_from_counts_all_obtained():
    assert _check_success_from_counts(
        {'char_a': 1, 'char_b': 2}, {'char_a': 1, 'char_b': 2}
    ) is True


def test_check_success_from_counts_partial():
    assert _check_success_from_counts(
        {'char_a': 1, 'char_b': 0}, {'char_a': 1, 'char_b': 1}
    ) is False


def test_check_success_from_counts_empty_targets():
    assert _check_success_from_counts({'char_a': 1}, {}) is True


def test_conditional_resource_distribution():
    simulation_results = [
        {
            'card_counts': {'char_a': 1, 'char_b': 1},
            'final_resources': {'draw_resource': 1000},
        },
        {
            'card_counts': {'char_a': 0, 'char_b': 1},
            'final_resources': {'draw_resource': 200},
        },
        {
            'card_counts': {'char_a': 1, 'char_b': 1},
            'final_resources': {'draw_resource': 800},
        },
    ]
    target_specs = {'char_a': 1, 'char_b': 1}
    dist = ConditionalResourceDistribution(simulation_results, target_specs)

    assert len(dist.success_resources) == 2
    assert len(dist.failure_resources) == 1
    assert dist.success_resources == [1000, 800]
    assert dist.failure_resources == [200]


def test_worst_case_resource_failure():
    simulation_results = [
        {'card_counts': {'a': 1}, 'final_resources': {'draw_resource': 1000}},
        {'card_counts': {'a': 0}, 'final_resources': {'draw_resource': 200}},
        {'card_counts': {'a': 0}, 'final_resources': {'draw_resource': 100}},
    ]
    target_specs = {'a': 1}
    dist = ConditionalResourceDistribution(simulation_results, target_specs)
    worst = dist.get_worst_case_resource('failure', 0.5)
    assert worst == 100


def test_worst_impact_result_dataclass():
    result = WorstImpactResult(
        worst_resource=500.0,
        pity_coverage=0.35,
        pool_distribution={0: 0.3, 1: 0.5, 2: 0.2},
        expected_pools=0.9,
    )
    assert result.worst_resource == 500.0
    assert result.pity_coverage == 0.35
    assert result.expected_pools == 0.9


def test_worst_impact_result_get_p_ge():
    result = WorstImpactResult(
        worst_resource=500.0,
        pity_coverage=0.35,
        pool_distribution={0: 0.1, 1: 0.35, 2: 0.4, 3: 0.15},
        expected_pools=1.6,
    )
    assert abs(result.get_p_ge(0) - 1.0) < 1e-9
    assert abs(result.get_p_ge(1) - 0.9) < 1e-9
    assert abs(result.get_p_ge(2) - 0.55) < 1e-9
    assert abs(result.get_p_ge(3) - 0.15) < 1e-9
    assert abs(result.get_p_ge(4) - 0.0) < 1e-9


def test_worst_impact_result_max_consecutive_at_threshold():
    result = WorstImpactResult(
        worst_resource=500.0,
        pity_coverage=0.35,
        pool_distribution={0: 0.1, 1: 0.35, 2: 0.4, 3: 0.15},
        expected_pools=1.6,
    )
    assert result.get_max_consecutive_at_threshold(1.0) == 0
    assert result.get_max_consecutive_at_threshold(0.9) == 1
    assert result.get_max_consecutive_at_threshold(0.5) == 2
    assert result.get_max_consecutive_at_threshold(0.1) == 3
```

---

## Task 2: UI 面板 `worst_impact_panel.py`

**Files:**
- Create: `gacha_simulator/gui/worst_impact_panel.py`
- Modify: `gacha_simulator/gui/main_window.py`

### Step 2.1: 创建面板框架

> v3 变更：删除模式选择（分布+期望/阈值连续）和成功率阈值配置。
> 只保留一种模式：分布+期望。表格中已包含 P(X≥k) 列，可回答阈值问题。

```python
import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QRadioButton, QButtonGroup,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap


class WorstImpactWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(self, analyzer, condition, alpha, num_simulations):
        super().__init__()
        self.analyzer = analyzer
        self.condition = condition
        self.alpha = alpha
        self.num_simulations = num_simulations

    def run(self):
        try:
            result = self.analyzer.analyze(
                condition=self.condition,
                alpha=self.alpha,
                num_simulations=self.num_simulations,
                progress_callback=self._progress,
            )
            self.finished.emit(result)
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(e)

    def _progress(self, msg, pct):
        self.progress.emit(msg, pct)


class WorstImpactPanel(QWidget):
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._store = None
        self._simulation_results = None
        self._target_specs = None
        self._worker = None
        self._setup_ui()

    def set_store(self, store):
        self._store = store

    def set_simulation_results(self, results, target_specs=None):
        self._simulation_results = results
        self._target_specs = target_specs
        if results:
            self.status_label.setText(f"已接收 {len(results)} 条模拟结果")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        config_group = QGroupBox("分析配置")
        config_form = QFormLayout(config_group)

        self.cond_all = QRadioButton("全部情形")
        self.cond_success = QRadioButton("成功情形")
        self.cond_failure = QRadioButton("失败情形")
        self.cond_btn_group = QButtonGroup(self)
        for btn in [self.cond_all, self.cond_success, self.cond_failure]:
            self.cond_btn_group.addButton(btn)
        self.cond_failure.setChecked(True)
        cond_layout = QHBoxLayout()
        cond_layout.addWidget(self.cond_all)
        cond_layout.addWidget(self.cond_success)
        cond_layout.addWidget(self.cond_failure)
        config_form.addRow("条件:", cond_layout)

        self.alpha_spin = QDoubleSpinBox()
        self.alpha_spin.setRange(0.01, 0.5)
        self.alpha_spin.setSingleStep(0.01)
        self.alpha_spin.setValue(0.05)
        self.alpha_spin.setDecimals(2)
        config_form.addRow("保守分位数 α:", self.alpha_spin)

        self.sim_spin = QSpinBox()
        self.sim_spin.setRange(50, 5000)
        self.sim_spin.setSingleStep(100)
        self.sim_spin.setValue(500)
        config_form.addRow("模拟次数:", self.sim_spin)

        left_layout.addWidget(config_group)

        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("开始分析")
        self.run_btn.clicked.connect(self._on_run)
        btn_layout.addWidget(self.run_btn)
        left_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("请先运行批量模拟")
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

        right = QWidget()
        right_layout = QVBoxLayout(right)

        summary_group = QGroupBox("结果摘要")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel("尚未运行分析")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "padding: 8px; background: #f5f5f5; border-radius: 4px;"
        )
        summary_layout.addWidget(self.summary_label)
        right_layout.addWidget(summary_group)

        self.chart_labels = {}

        chart1_group = QGroupBox("大保底资源覆盖")
        chart1_layout = QVBoxLayout(chart1_group)
        self.chart_label_coverage = QLabel()
        self.chart_label_coverage.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label_coverage.setMinimumHeight(200)
        chart1_layout.addWidget(self.chart_label_coverage)
        right_layout.addWidget(chart1_group)
        self.chart_labels["coverage"] = self.chart_label_coverage

        chart2_group = QGroupBox("新池子数分布")
        chart2_layout = QVBoxLayout(chart2_group)
        self.chart_label_dist = QLabel()
        self.chart_label_dist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label_dist.setMinimumHeight(200)
        chart2_layout.addWidget(self.chart_label_dist)
        right_layout.addWidget(chart2_group)
        self.chart_labels["distribution"] = self.chart_label_dist

        table_group = QGroupBox("详细数据")
        table_layout = QVBoxLayout(table_group)
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(5)
        self.detail_table.setHorizontalHeaderLabels(
            ["k", "P(X=k)", "P(X>=k)", "累计概率", "说明"]
        )
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.detail_table.verticalHeader().setVisible(False)
        table_layout.addWidget(self.detail_table)
        right_layout.addWidget(table_group)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([350, 650])

    def _on_run(self):
        if not self._simulation_results:
            self.status_label.setText("请先运行批量模拟")
            return

        if not self._target_specs:
            self.status_label.setText("缺少目标卡规格，请重新运行批量模拟")
            return

        if self.cond_success.isChecked():
            condition = 'success'
        elif self.cond_failure.isChecked():
            condition = 'failure'
        else:
            condition = 'all'

        from gacha_simulator.core.worst_impact import WorstImpactAnalyzer

        analyzer = WorstImpactAnalyzer(
            simulation_results=self._simulation_results,
            target_specs=self._target_specs,
            store=self._store,
        )

        self._worker = WorstImpactWorker(
            analyzer, condition,
            self.alpha_spin.value(),
            self.sim_spin.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self._worker.start()

    def _on_progress(self, msg, pct):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        self.status_update.emit(msg)

    def _on_finished(self, result):
        self.run_btn.setEnabled(True)
        if not result:
            return

        lines = [
            f"<b>保守资源:</b> {result.worst_resource:.0f}",
            f"<b>大保底覆盖:</b> {result.pity_coverage:.2f} 倍",
        ]
        if result.pool_distribution:
            lines.append(f"<b>期望新池子数:</b> {result.expected_pools:.2f}")
        self.summary_label.setText('<br>'.join(lines))

        if result.pool_distribution:
            self.detail_table.setRowCount(len(result.pool_distribution))
            cumulative = 0.0
            for i, (k, prob) in enumerate(sorted(result.pool_distribution.items())):
                self.detail_table.setItem(i, 0, QTableWidgetItem(str(k)))
                self.detail_table.setItem(i, 1, QTableWidgetItem(f"{prob:.2%}"))
                p_ge = result.get_p_ge(k)
                self.detail_table.setItem(i, 2, QTableWidgetItem(f"{p_ge:.2%}"))
                cumulative += prob
                self.detail_table.setItem(i, 3, QTableWidgetItem(f"{cumulative:.2%}"))
                self.detail_table.setItem(i, 4, QTableWidgetItem(
                    f"成功{k}个新池子" if k > 0 else "未成功"
                ))

        self._plot_charts(result)
        self.status_update.emit("最差后期影响分析完成")

    def _plot_charts(self, result):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from gacha_simulator.visualization.font_config import configure_chinese_font
        configure_chinese_font()

        fig, ax = plt.subplots(figsize=(4, 3))
        ax.barh(['大保底覆盖'], [result.pity_coverage], color='steelblue')
        ax.set_xlabel('覆盖倍数')
        ax.axvline(x=1.0, color='r', linestyle='--', label='1次保底')
        ax.legend()
        for i, v in enumerate([result.pity_coverage]):
            ax.text(v + 0.05, i, f'{v:.2f}', va='center', fontsize=10)
        plt.tight_layout()
        self._save_chart(fig, "coverage")

        if result.pool_distribution:
            fig, ax = plt.subplots(figsize=(6, 4))
            ks = sorted(result.pool_distribution.keys())
            probs = [result.pool_distribution[k] for k in ks]
            bars = ax.bar(ks, probs, color='coral')
            ax.set_xlabel('成功抽取新池子数 k')
            ax.set_ylabel('P(X = k)')
            ax.set_title(f'新池子数分布 (E[X] = {result.expected_pools:.2f})')
            ax.set_xticks(ks)
            ax.axvline(x=result.expected_pools, color='red', linestyle='--',
                      label=f'期望 = {result.expected_pools:.2f}')
            ax.legend()
            for bar, prob in zip(bars, probs):
                if prob > 0.01:
                    ax.text(bar.get_x() + bar.get_width()/2,
                           bar.get_height() + 0.005,
                           f'{prob:.1%}', ha='center', va='bottom', fontsize=8)
            plt.tight_layout()
            self._save_chart(fig, "distribution")

    def _save_chart(self, fig, key):
        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        fig.savefig(tmp.name, dpi=200, bbox_inches='tight')
        plt.close(fig)
        pixmap = QPixmap(tmp.name)
        if not pixmap.isNull():
            max_w = self.chart_labels[key].width() or 600
            max_h = self.chart_labels[key].height() or 400
            scaled = pixmap.scaled(max_w, max_h,
                                   Qt.AspectRatioMode.KeepAspectRatio,
                                   Qt.TransformationMode.SmoothTransformation)
            self.chart_labels[key].setPixmap(scaled)

    def _on_error(self, err):
        self.run_btn.setEnabled(True)
        self.status_label.setText(f"错误: {err}")
        import traceback
        traceback.print_exc()
```

### Step 2.2: 集成到主窗口

修改 `main_window.py`：

```python
from .worst_impact_panel import WorstImpactPanel

# 在 _setup_ui 中
self.worst_impact_panel = WorstImpactPanel()

# 在 _connect_signals 中
self.worst_impact_panel.status_update.connect(self.status_bar.showMessage)

# 在 on_simulation_finished 中
target_specs = {tc.card_id: getattr(tc, 'quantity', 1)
                for tc in getattr(self._store, 'target_cards', [])}
self.worst_impact_panel.set_simulation_results(results, target_specs)

# 在 _on_tab_changed 中
elif widget is self.worst_impact_panel:
    self.worst_impact_panel.set_store(self._store)
```

---

## Task 3: 测试

### Step 3.1: 运行单元测试

```bash
pytest tests/core/test_worst_impact.py -v
```

### Step 3.2: 运行集成测试

```bash
pytest tests/ -k "worst_impact" -v
```

### Step 3.3: 手动测试

1. 启动程序
2. 加载配置
3. 运行批量模拟
4. 切换到"最差影响"标签
5. 选择条件（失败情形）
6. 点击"开始分析"
7. 检查：
   - 大保底覆盖倍数图表
   - 新池子数分布PMF图表
   - 详细数据表格（含P(X=k)、P(X>=k)）
   - 进度条正常更新

---

## 修订记录

| 日期 | 修订内容 |
|------|----------|
| 2026-05-14 | 初始版本，三个维度 |
| 2026-05-14 | 删除"连续可抽池子数"维度，改为"可抽池子数分布+期望" |
| 2026-05-14 | 更新数据模型：使用 `final_resources` 而非 `pool_end_resources` |
| 2026-05-14 | 添加 `ConditionalPityDistribution` |
| 2026-05-14 | 简化"链式模拟"说明：明确复用现有 `GachaService` |
| 2026-05-14 | 删除 `ConditionalPityDistribution`，改为从配置读取初始保底 |
| 2026-05-14 | 最终版：只用最终资源，两种分析模式，复用现有引擎 |
| 2026-05-14 | **v2 修订**：修复12项问题 |
| 2026-05-14 | **v3 修订**：删除模式B（阈值连续），只保留分布+期望 |

### v3 变更说明

**删除模式B的原因**：

模式B（阈值连续）用平均剩余资源做确定性近似，丢失了剩余资源的不确定性信息，结果不如模式A准确。而模式A的分布 P(X≥k) 已经能直接回答阈值问题——找到最大的 k 使得 P(X≥k) ≥ threshold 即可。

因此模式B在准确性和信息量上都不如模式A，属于冗余设计。

**具体变更**：
- `WorstImpactAnalyzer.analyze()` 删除 `mode` 和 `threshold` 参数
- 删除 `_compute_max_consecutive` 方法
- `WorstImpactResult` 删除 `max_consecutive_threshold` 字段
- `WorstImpactResult` 新增 `get_p_ge(k)` 和 `get_max_consecutive_at_threshold(threshold)` 方法
- UI 删除模式选择和成功率阈值配置
- `WorstImpactWorker` 删除 `mode` 和 `threshold` 参数
- 表格中 P(X≥k) 改用 `result.get_p_ge(k)` 计算
