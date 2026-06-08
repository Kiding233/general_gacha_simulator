"""方案搜索面板 —— 三合一统一面板（替代 StrategyPanel + ResourceSearchPanel + RetreatSearchPanel）

阶段 D 实施（P8 面板合并计划 v8）
"""

from __future__ import annotations
import os
import traceback
from typing import Dict, List, Optional
from dataclasses import dataclass, field

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QRadioButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QStackedWidget, QProgressBar, QSplitter, QScrollArea, QButtonGroup,
)


# ═══════════════════════════════════════════════════════════════════════════════
# 快照系统
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class SearchSnapshot:
    name: str
    result: object  # PlanSearchResult
    chart_json: Optional[str] = None  # Plotly JSON（惰性渲染时用）


class SnapshotManager:
    """内存快照管理器——上限 20 条，跨模式共存，按时间排序"""

    def __init__(self, max_snapshots: int = 20):
        self._snapshots: List[SearchSnapshot] = []
        self._current_index: int = -1
        self._max = max_snapshots

    @property
    def count(self) -> int:
        return len(self._snapshots)

    @property
    def current(self) -> Optional[SearchSnapshot]:
        if 0 <= self._current_index < len(self._snapshots):
            return self._snapshots[self._current_index]
        return None

    @property
    def current_index(self) -> int:
        return self._current_index

    def push(self, snapshot: SearchSnapshot):
        if len(self._snapshots) >= self._max:
            self._snapshots.pop(0)
        self._snapshots.append(snapshot)
        self._current_index = len(self._snapshots) - 1

    def prev(self) -> Optional[SearchSnapshot]:
        if self._current_index > 0:
            self._current_index -= 1
        return self.current

    def next(self) -> Optional[SearchSnapshot]:
        if self._current_index < len(self._snapshots) - 1:
            self._current_index += 1
        return self.current

    def delete_current(self) -> Optional[SearchSnapshot]:
        if 0 <= self._current_index < len(self._snapshots):
            self._snapshots.pop(self._current_index)
            if self._current_index >= len(self._snapshots):
                self._current_index = len(self._snapshots) - 1
        return self.current

    def clear(self):
        self._snapshots.clear()
        self._current_index = -1

    def all_labels(self) -> List[str]:
        return [s.name for s in self._snapshots]


# ═══════════════════════════════════════════════════════════════════════════════
# Worker
# ═══════════════════════════════════════════════════════════════════════════════

class PlanSearchWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(
        self,
        config_store,
        *,
        search_mode: str,          # 'min_resource' | 'forward' | 'backward' | 'pareto'
        from_pool_id: Optional[str] = None,
        base_resource: float = 0.0,
        pity_counter_init: Optional[Dict[str, int]] = None,
        target_specs: Optional[Dict[str, int]] = None,
        candidate_specs: Optional[Dict[str, int]] = None,
        desire_weights: Optional[Dict[str, float]] = None,
        miss_cost_weights: Optional[Dict[str, float]] = None,
        card_value_weights: Optional[Dict[str, float]] = None,
        success_threshold: float = 0.95,
        gdr_key: str = 'all_targets',
        gdr_threshold: float = 1.0,
        num_simulations: int = 500,
        max_workers: int = 4,
        max_binary_iterations: int = 20,
        precision_draws: int = 1,
        strategy_name: str = 'smart',
        strategy_params: Optional[Dict] = None,
    ):
        super().__init__()
        self.config_store = config_store
        self.search_mode = search_mode
        self.from_pool_id = from_pool_id
        self.base_resource = base_resource
        self.pity_counter_init = pity_counter_init or {}
        self.target_specs = target_specs or {}
        self.candidate_specs = candidate_specs or {}
        self.desire_weights = desire_weights or {}
        self.miss_cost_weights = miss_cost_weights or {}
        self.card_value_weights = card_value_weights or {}
        self.success_threshold = success_threshold
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.num_simulations = num_simulations
        self.max_workers = max_workers
        self.max_binary_iterations = max_binary_iterations
        self.precision_draws = precision_draws
        self.strategy_name = strategy_name
        self.strategy_params = strategy_params or {}

    def stop(self):
        if hasattr(self, '_engine') and self._engine is not None:
            self._engine.stop()

    def run(self):
        try:
            from gacha_simulator.core.retreat_search import PlanSearchEngine

            self._engine = PlanSearchEngine(
                config_store=self.config_store,
                from_pool_id=self.from_pool_id,
                base_resource=self.base_resource,
                pity_counter_init=self.pity_counter_init,
                desire_weights=self.desire_weights,
                miss_cost_weights=self.miss_cost_weights,
                card_value_weights=self.card_value_weights,
                success_threshold=self.success_threshold,
                gdr_key=self.gdr_key,
                gdr_threshold=self.gdr_threshold,
                num_simulations=self.num_simulations,
                max_workers=self.max_workers,
                max_binary_iterations=self.max_binary_iterations,
                precision_draws=self.precision_draws,
                strategy_name=self.strategy_name,
                strategy_params=self.strategy_params,
                progress_callback=lambda msg, pct: self.progress.emit(msg, pct),
            )

            if self.search_mode == 'min_resource':
                result = self._engine.search_min_resource(self.target_specs)
            elif self.search_mode == 'forward':
                result = self._engine.search_max_targets_forward(self.candidate_specs)
            elif self.search_mode == 'backward':
                result = self._engine.search_max_targets(self.target_specs)
            elif self.search_mode == 'pareto':
                result = self._engine.search_pareto(self.target_specs)
            else:
                raise ValueError(f"未知搜索模式: {self.search_mode}")

            self.finished.emit(result)

        except Exception as e:
            detailed = f"{type(e).__name__}: {e}\n\n{traceback.format_exc()}"
            traceback.print_exc()

            class DetailedError(Exception):
                def __init__(self, msg):
                    self.msg = msg
                def __str__(self):
                    return self.msg

            self.error.emit(DetailedError(detailed))


# ═══════════════════════════════════════════════════════════════════════════════
# 结果页面
# ═══════════════════════════════════════════════════════════════════════════════

class ResourceResultPage(QWidget):
    """最少资源结果页（从 ResourceSearchPanel 迁移）"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("尚未搜索")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        from gacha_simulator.visualization.plotly_charts import ChartWebView
        self.chart_view = ChartWebView()
        layout.addWidget(self.chart_view, 1)

        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(6)
        self.steps_table.setHorizontalHeaderLabels(["迭代", "阶段", "资源值", "成功率", "下界", "上界"])
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.steps_table)

    def display(self, result):
        """显示最少资源搜索结果"""
        r = result.min_resource
        cost = result.cost_per_draw if result.cost_per_draw > 0 else 160
        draws = r / cost if cost > 0 else 0
        precision_val = cost  # precision_draws=1 → ±1 抽精度

        self.summary_label.setText(
            f"<b>最少资源:</b> {r:,.0f} (≈{draws:.1f} 抽) &nbsp;|&nbsp; "
            f"<b>成功率:</b> {result.final_success_probability:.2%} &nbsp;|&nbsp; "
            f"<b>单抽成本:</b> {cost:.0f} &nbsp;|&nbsp; "
            f"<b>精度:</b> ±{precision_val:.0f} &nbsp;|&nbsp; "
            f"<b>迭代:</b> {result.total_iterations} 次 &nbsp;|&nbsp; "
            f"<b>目标:</b> {result.target_specs}"
        )

        self.steps_table.setRowCount(len(result.binary_steps))
        for i, step in enumerate(result.binary_steps):
            self.steps_table.setItem(i, 0, QTableWidgetItem(str(step.iteration)))
            self.steps_table.setItem(i, 1, QTableWidgetItem(step.phase))
            self.steps_table.setItem(i, 2, QTableWidgetItem(f"{step.resource_value:,.0f}"))
            self.steps_table.setItem(i, 3, QTableWidgetItem(f"{step.success_probability:.2%}"))
            self.steps_table.setItem(i, 4, QTableWidgetItem(f"{step.lo_bound:,.0f}"))
            self.steps_table.setItem(i, 5, QTableWidgetItem(f"{step.hi_bound:,.0f}"))


class TargetResultPage(QWidget):
    """最多目标卡结果页（从 StrategyPanel 迁移，参数化前进/后退标签）"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("尚未搜索")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        from gacha_simulator.visualization.plotly_charts import ChartWebView
        self.chart_view = ChartWebView()
        layout.addWidget(self.chart_view, 1)

        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(5)
        self.steps_table.setHorizontalHeaderLabels(["步骤", "操作", "卡ID", "目标集大小", "成功率"])
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.steps_table)

    def display(self, result, direction: str = 'forward'):
        """显示最多目标卡搜索结果。direction: 'forward' | 'backward'"""
        points = result.points
        if not points:
            self.summary_label.setText("无结果")
            return

        best = points[-1]
        if direction == 'forward':
            labels = {"add": "+ 添加", "direction": "前进法"}
        else:
            labels = {"add": "− 移除", "direction": "后退法"}

        self.summary_label.setText(
            f"<b>方向:</b> {labels['direction']} &nbsp;|&nbsp; "
            f"<b>最终目标集:</b> {', '.join(best.target_specs.keys()) or '(无)'} &nbsp;|&nbsp; "
            f"<b>成功率:</b> {best.success_probability:.2%} &nbsp;|&nbsp; "
            f"<b>共 {len(points)} 步</b>"
        )

        self.steps_table.setRowCount(len(points))
        prev_size = 0
        for i, pt in enumerate(points):
            size = len(pt.target_specs)
            if direction == 'forward':
                added = [k for k in pt.target_specs if k not in (points[i-1].target_specs if i > 0 else {})]
                card_id = ', '.join(added) if added else list(pt.target_specs.keys())[0] if pt.target_specs else '—'
                op = "− 移除" if size < prev_size else "+ 添加"
            else:
                removed = [k for k in (points[i-1].target_specs if i > 0 else {}) if k not in pt.target_specs]
                card_id = ', '.join(removed) if removed else '—'
                op = "− 移除"

            self.steps_table.setItem(i, 0, QTableWidgetItem(str(i + 1)))
            self.steps_table.setItem(i, 1, QTableWidgetItem(op))
            self.steps_table.setItem(i, 2, QTableWidgetItem(card_id))
            self.steps_table.setItem(i, 3, QTableWidgetItem(str(size)))
            self.steps_table.setItem(i, 4, QTableWidgetItem(f"{pt.success_probability:.2%}"))
            prev_size = size


class ParetoResultPage(QWidget):
    """Pareto 前沿结果页（从 RetreatSearchPanel 迁移）"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("尚未搜索")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        from gacha_simulator.visualization.plotly_charts import ChartWebView
        self.chart_view = ChartWebView()
        layout.addWidget(self.chart_view, 1)

        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(4)
        self.detail_table.setHorizontalHeaderLabels(["所需资源", "目标卡集合", "成功率", "总资源"])
        self.detail_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.detail_table)

    def display(self, result):
        """显示 Pareto 搜索结果"""
        points = result.points
        if not points:
            self.summary_label.setText("无结果")
            return

        best = points[-1]
        self.summary_label.setText(
            f"<b>模式:</b> Pareto前沿 &nbsp;|&nbsp; "
            f"<b>起始池:</b> {result.from_pool_id or '(从头开始)'} &nbsp;|&nbsp; "
            f"<b>最优方案:</b> {len(best.target_specs)} 目标卡 + {result.base_resource + best.extra_resource:,.0f} 资源, "
            f"P={best.success_probability:.2%}"
        )

        self.detail_table.setRowCount(len(points))
        for i, pt in enumerate(points):
            specs_str = ', '.join(f"{k}×{v}" for k, v in pt.target_specs.items()) or "(无)"
            self.detail_table.setItem(i, 0, QTableWidgetItem(f"{pt.extra_resource:,.0f}"))
            self.detail_table.setItem(i, 1, QTableWidgetItem(specs_str))
            self.detail_table.setItem(i, 2, QTableWidgetItem(f"{pt.success_probability:.2%}"))
            total = result.base_resource + pt.extra_resource
            self.detail_table.setItem(i, 3, QTableWidgetItem(f"{total:,.0f}"))


# ═══════════════════════════════════════════════════════════════════════════════
# 主面板
# ═══════════════════════════════════════════════════════════════════════════════

class PlanSearchPanel(QWidget):
    """方案搜索面板——三合一（v8 设计）"""
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._store = None
        self._vulnerability_result = None
        self._worker: Optional[PlanSearchWorker] = None
        self._snapshots = SnapshotManager()

        self._setup_ui()
        self._connect_signals()

    # ── UI 构建 ────────────────────────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        # ── 左栏：配置区（可滚动）──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(360)
        scroll.setMaximumWidth(420)

        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(8)

        # ① 搜索模式
        self._setup_mode_group(left_layout)
        # ② 起始状态
        self._setup_source_group(left_layout)
        # ③ 目标卡权重配置
        self._setup_weight_group(left_layout)
        # ④ 搜索参数
        self._setup_params_group(left_layout)
        # ⑤ 按钮 + 进度
        self._setup_action_bar(left_layout)

        left_layout.addStretch()
        scroll.setWidget(left)
        main_layout.addWidget(scroll)

        # ── 右栏：结果区 ──
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(8)

        # 快照导航栏
        self._setup_snapshot_bar(right_layout)

        # QStackedWidget（3 个结果页）
        self.result_stack = QStackedWidget()
        self.resource_page = ResourceResultPage()
        self.target_page = TargetResultPage()
        self.pareto_page = ParetoResultPage()
        self.result_stack.addWidget(self.resource_page)   # index 0
        self.result_stack.addWidget(self.target_page)      # index 1
        self.result_stack.addWidget(self.pareto_page)      # index 2
        right_layout.addWidget(self.result_stack, 1)

        main_layout.addWidget(right, 1)

    def _setup_mode_group(self, parent_layout):
        group = QGroupBox("搜索模式")
        layout = QHBoxLayout(group)

        self.mode_group = QButtonGroup(self)
        self.mode_resource = QRadioButton("最少资源")
        self.mode_target = QRadioButton("最多目标卡")
        self.mode_pareto = QRadioButton("Pareto前沿")
        self.mode_group.addButton(self.mode_resource, 0)
        self.mode_group.addButton(self.mode_target, 1)
        self.mode_group.addButton(self.mode_pareto, 2)
        self.mode_target.setChecked(True)

        layout.addWidget(self.mode_resource)
        layout.addWidget(self.mode_target)
        layout.addWidget(self.mode_pareto)
        parent_layout.addWidget(group)

    def _setup_source_group(self, parent_layout):
        group = QGroupBox("起始状态")
        form = QFormLayout(group)

        self.pool_combo = QComboBox()
        self.pool_combo.addItem("(从头开始)")
        form.addRow("起始池:", self.pool_combo)

        # 基准资源
        resource_row = QHBoxLayout()
        self.resource_combo = QComboBox()
        self.resource_combo.addItems(["50%分位", "均值", "25%分位", "75%分位", "自定义"])
        self.resource_manual = QLineEdit("0")
        self.resource_manual.setMaximumWidth(80)
        self.resource_manual.setEnabled(False)
        resource_row.addWidget(self.resource_combo)
        resource_row.addWidget(self.resource_manual)
        form.addRow("基准资源:", resource_row)

        # 保底水位
        pity_group = QGroupBox("保底水位")
        pity_layout = QVBoxLayout(pity_group)
        self.pity_table = QTableWidget()
        self.pity_table.setColumnCount(6)
        self.pity_table.setHorizontalHeaderLabels(["计数器", "均值", "中位", "25%", "75%", "初始值"])
        self.pity_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.pity_table.setMaximumHeight(120)
        pity_layout.addWidget(self.pity_table)
        form.addRow(pity_group)

        parent_layout.addWidget(group)

    def _setup_weight_group(self, parent_layout):
        group = QGroupBox("目标卡权重配置")
        layout = QVBoxLayout(group)

        hint = QLabel("前进法按「抽取意愿」降序 · 后退法按「错失代价」升序")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        self.weight_table = QTableWidget()
        self.weight_table.setColumnCount(3)
        self.weight_table.setHorizontalHeaderLabels(["卡ID", "抽取意愿", "错失代价"])
        self.weight_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.weight_table.setMaximumHeight(180)
        layout.addWidget(self.weight_table)

        # 搜索方向
        dir_layout = QHBoxLayout()
        dir_layout.addWidget(QLabel("搜索方向:"))
        self.dir_group = QButtonGroup(self)
        self.dir_forward = QRadioButton("前进法")
        self.dir_backward = QRadioButton("后退法")
        self.dir_group.addButton(self.dir_forward, 0)
        self.dir_group.addButton(self.dir_backward, 1)
        self.dir_forward.setChecked(True)
        dir_layout.addWidget(self.dir_forward)
        dir_layout.addWidget(self.dir_backward)
        dir_layout.addStretch()
        layout.addLayout(dir_layout)

        parent_layout.addWidget(group)

    def _setup_params_group(self, parent_layout):
        group = QGroupBox("搜索参数")
        form = QFormLayout(group)

        self.strategy_label = QLabel("Smart")
        self.strategy_label.setStyleSheet("border: 1px solid #ccc; padding: 3px 8px; background: #f5f5f5;")
        form.addRow("当前策略:", self.strategy_label)

        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY
        gdr_keys = list(UNIFIED_GDR_REGISTRY.keys())
        self.gdr_combo = QComboBox()
        self.gdr_combo.addItems(gdr_keys)
        if 'all_targets' in gdr_keys:
            self.gdr_combo.setCurrentText('all_targets')
        gdr_row = QHBoxLayout()
        gdr_row.addWidget(self.gdr_combo)
        gdr_row.addWidget(QLabel("阈值:"))
        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(0.0, 1.0)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setSingleStep(0.05)
        gdr_row.addWidget(self.gdr_threshold_spin)
        form.addRow("GDR指标:", gdr_row)

        self.success_threshold_spin = QDoubleSpinBox()
        self.success_threshold_spin.setRange(0.0, 1.0)
        self.success_threshold_spin.setValue(0.95)
        self.success_threshold_spin.setSingleStep(0.01)
        form.addRow("成功率阈值:", self.success_threshold_spin)

        self.num_simulations_spin = QSpinBox()
        self.num_simulations_spin.setRange(10, 100000)
        self.num_simulations_spin.setValue(1000)
        self.num_simulations_spin.setSingleStep(100)
        form.addRow("模拟次数:", self.num_simulations_spin)

        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, os.cpu_count() or 16)
        self.max_workers_spin.setValue(max(1, (os.cpu_count() or 8) - 2))
        form.addRow("并行进程:", self.max_workers_spin)

        # 二分搜索参数（子区域）
        self.binary_group = QGroupBox("二分搜索参数")
        binary_form = QFormLayout(self.binary_group)
        self.upper_bound_spin = QSpinBox()
        self.upper_bound_spin.setRange(1, 99999999)
        self.upper_bound_spin.setValue(55000)
        self.upper_bound_spin.setSingleStep(1000)
        binary_form.addRow("起始上界:", self.upper_bound_spin)

        self.lower_bound_spin = QSpinBox()
        self.lower_bound_spin.setRange(0, 99999999)
        self.lower_bound_spin.setValue(0)
        self.lower_bound_spin.setSingleStep(1000)
        binary_form.addRow("起始下界:", self.lower_bound_spin)

        self.precision_spin = QSpinBox()
        self.precision_spin.setRange(1, 100)
        self.precision_spin.setValue(1)
        binary_form.addRow("精度(抽):", self.precision_spin)

        self.max_iter_spin = QSpinBox()
        self.max_iter_spin.setRange(1, 100)
        self.max_iter_spin.setValue(30)
        binary_form.addRow("最大迭代:", self.max_iter_spin)

        self.cost_per_draw_spin = QSpinBox()
        self.cost_per_draw_spin.setRange(1, 9999999)
        self.cost_per_draw_spin.setValue(160)
        self.cost_per_draw_spin.setToolTip(
            "每抽消耗的资源数量。多池成本不同时此值为近似值，不影响搜索正确性（搜索在资源空间运行）。"
        )
        binary_form.addRow("单抽成本:", self.cost_per_draw_spin)

        form.addRow(self.binary_group)
        parent_layout.addWidget(group)

    def _setup_action_bar(self, parent_layout):
        btn_layout = QHBoxLayout()

        self.run_btn = QPushButton("▶ 开始搜索")
        self.run_btn.setStyleSheet("background: #4CAF50; color: white; font-weight: bold; padding: 6px 20px;")
        btn_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("⏹ 停止")
        self.stop_btn.setStyleSheet("background: #f44336; color: white; padding: 6px 12px;")
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)

        parent_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        parent_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("")
        self.status_label.setStyleSheet("color: #666; font-size: 11px;")
        parent_layout.addWidget(self.status_label)

    def _setup_snapshot_bar(self, parent_layout):
        bar = QHBoxLayout()

        bar.addWidget(QLabel("结果快照:"))
        self.snapshot_prev_btn = QPushButton("<")
        self.snapshot_prev_btn.setFixedWidth(30)
        bar.addWidget(self.snapshot_prev_btn)

        self.snapshot_combo = QComboBox()
        self.snapshot_combo.setMinimumWidth(200)
        bar.addWidget(self.snapshot_combo)

        self.snapshot_next_btn = QPushButton(">")
        self.snapshot_next_btn.setFixedWidth(30)
        bar.addWidget(self.snapshot_next_btn)

        self.snapshot_del_btn = QPushButton("×")
        self.snapshot_del_btn.setFixedWidth(30)
        self.snapshot_del_btn.setStyleSheet("color: #f44336; font-weight: bold;")
        bar.addWidget(self.snapshot_del_btn)

        self.snapshot_count_label = QLabel("0个快照")
        self.snapshot_count_label.setStyleSheet("color: #999; font-size: 10px;")
        bar.addWidget(self.snapshot_count_label)

        bar.addStretch()
        parent_layout.addLayout(bar)

    # ── 信号连接 ──────────────────────────────────────────────────────────

    def _connect_signals(self):
        self.mode_group.idToggled.connect(self._on_mode_changed)
        self.run_btn.clicked.connect(self._on_run_clicked)
        self.stop_btn.clicked.connect(self._on_stop_clicked)

        self.snapshot_prev_btn.clicked.connect(self._on_snapshot_prev)
        self.snapshot_next_btn.clicked.connect(self._on_snapshot_next)
        self.snapshot_combo.currentIndexChanged.connect(self._on_snapshot_selected)
        self.snapshot_del_btn.clicked.connect(self._on_snapshot_delete)

        self.pool_combo.currentIndexChanged.connect(self._on_pool_changed)
        self.resource_combo.currentTextChanged.connect(self._on_resource_combo_changed)

    # ── 模式切换 ──────────────────────────────────────────────────────────

    def _on_mode_changed(self, btn_id, checked):
        if not checked:
            return
        mode = {0: 'resource', 1: 'target', 2: 'pareto'}.get(btn_id, 'target')

        # 权重表：最少资源灰显
        is_target = mode in ('target', 'pareto')
        self.weight_table.setEnabled(is_target)
        self.dir_forward.setEnabled(mode == 'target')
        self.dir_backward.setEnabled(mode == 'target')

        # Pareto 默认后退法
        if mode == 'pareto':
            self.dir_backward.setChecked(True)

        # 二分参数：目标模式灰显
        is_binary = mode in ('resource', 'pareto')
        self.binary_group.setEnabled(is_binary)

        # 结果区切换
        page_map = {'resource': 0, 'target': 1, 'pareto': 2}
        self.result_stack.setCurrentIndex(page_map.get(mode, 1))

    def _on_pool_changed(self, index):
        is_head = (index <= 0)
        self.resource_combo.setEnabled(not is_head)
        self.resource_manual.setEnabled(not is_head and self.resource_combo.currentText() == "自定义")
        self.pity_table.setEnabled(not is_head)

        if is_head:
            self.pity_table.setRowCount(0)
            self.resource_manual.setText("0")

    def _on_resource_combo_changed(self, text):
        self.resource_manual.setEnabled(text == "自定义")

    # ── 搜索触发 ──────────────────────────────────────────────────────────

    def _on_run_clicked(self):
        if self._worker is not None and self._worker.isRunning():
            return
        if self._store is None:
            self.status_update.emit("请先在配置页加载或创建配置")
            return

        mode_id = self.mode_group.checkedId()
        mode_map = {0: 'min_resource', 1: None, 2: 'pareto'}
        search_mode = mode_map.get(mode_id)
        if search_mode is None:
            # 最多目标卡：根据方向决定 forward/backward
            search_mode = 'forward' if self.dir_forward.isChecked() else 'backward'

        # 构建权重字典
        desire_weights = {}
        miss_cost_weights = {}
        for row in range(self.weight_table.rowCount()):
            cid = self.weight_table.item(row, 0)
            desire = self.weight_table.cellWidget(row, 1)
            miss = self.weight_table.cellWidget(row, 2)
            if cid:
                cid_text = cid.text()
                if desire:
                    try:
                        desire_weights[cid_text] = float(desire.value())
                    except (ValueError, AttributeError):
                        desire_weights[cid_text] = 1.0
                if miss:
                    try:
                        miss_cost_weights[cid_text] = float(miss.value())
                    except (ValueError, AttributeError):
                        miss_cost_weights[cid_text] = 1.0

        pool_index = self.pool_combo.currentIndex()
        from_pool_id = None if pool_index <= 0 else self.pool_combo.currentText()

        base_resource = 0.0
        pity_init = {}
        if from_pool_id is not None and self._vulnerability_result is not None:
            # 从脆弱性结果中提取基准资源
            try:
                base_resource = float(self.resource_manual.text() or "0")
            except ValueError:
                base_resource = 0.0
            for row in range(self.pity_table.rowCount()):
                ctr = self.pity_table.item(row, 0)
                spin = self.pity_table.cellWidget(row, 5)
                if ctr and spin:
                    pity_init[ctr.text()] = spin.value()

        target_specs = self._collect_target_specs()

        self._worker = PlanSearchWorker(
            config_store=self._store,
            search_mode=search_mode,
            from_pool_id=from_pool_id,
            base_resource=base_resource,
            pity_counter_init=pity_init,
            target_specs=target_specs,
            candidate_specs=target_specs,
            desire_weights=desire_weights,
            miss_cost_weights=miss_cost_weights,
            success_threshold=self.success_threshold_spin.value(),
            gdr_key=self.gdr_combo.currentText(),
            gdr_threshold=self.gdr_threshold_spin.value(),
            num_simulations=self.num_simulations_spin.value(),
            max_workers=self.max_workers_spin.value(),
            max_binary_iterations=self.max_iter_spin.value(),
            precision_draws=self.precision_spin.value(),
            strategy_name=self._store.strategy_name if self._store else 'smart',
            strategy_params=self._store.strategy_params if self._store else None,
        )

        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setVisible(True)
        self.progress_bar.setValue(0)
        self._worker.start()

    def _collect_target_specs(self) -> Dict[str, int]:
        """从权重表中收集目标规格（每个卡数量固定为 1）"""
        specs = {}
        for row in range(self.weight_table.rowCount()):
            item = self.weight_table.item(row, 0)
            if item and item.text():
                specs[item.text()] = 1
        return specs

    def _on_stop_clicked(self):
        if self._worker:
            self._worker.stop()
            self._worker.wait()

    # ── 进度 / 完成 / 错误 ─────────────────────────────────────────────────

    def _on_progress(self, msg, pct):
        self.status_label.setText(msg)
        self.progress_bar.setValue(pct)
        self.status_update.emit(msg)

    def _on_finished(self, result):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText("搜索完成")
        self.status_update.emit("方案搜索完成")

        if result is None or not result.points:
            self.status_label.setText("搜索已停止" if result is None else "无可行方案")
            return

        # 推送快照
        import datetime
        mode_labels = {'min_resource': '最少资源', 'forward': '最多目标卡·前进', 'backward': '最多目标卡·后退', 'pareto': 'Pareto'}
        mode_display = mode_labels.get(result.search_mode, result.search_mode)
        if result.search_mode == 'pareto':
            direction = '后退' if self.dir_backward.isChecked() else '前进'
            mode_display = f'Pareto·{direction}'
        timestamp = datetime.datetime.now().strftime('%H:%M')
        name = f"{mode_display} @{timestamp}"

        snapshot = SearchSnapshot(name=name, result=result)
        self._snapshots.push(snapshot)
        self._refresh_snapshot_bar()

        # 显示结果
        self._display_result(result)

    def _on_error(self, err):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"错误: {err}")
        self.status_update.emit(f"搜索失败: {err}")

    # ── 结果显示 ──────────────────────────────────────────────────────────

    def _display_result(self, result):
        mode = result.search_mode
        mode_id = self.mode_group.checkedId()
        page_idx = {0: 0, 1: 1, 2: 2}.get(mode_id, 1)

        if mode == 'min_resource':
            self.resource_page.display(result)
        elif mode in ('forward', 'backward'):
            direction = 'forward' if mode == 'forward' else 'backward'
            self.target_page.display(result, direction)
        elif mode == 'pareto':
            self.pareto_page.display(result)

        self.result_stack.setCurrentIndex(page_idx)

    # ── 快照导航 ──────────────────────────────────────────────────────────

    def _refresh_snapshot_bar(self):
        labels = self._snapshots.all_labels()
        self.snapshot_combo.blockSignals(True)
        self.snapshot_combo.clear()
        self.snapshot_combo.addItems(labels)
        if self._snapshots.current_index >= 0:
            self.snapshot_combo.setCurrentIndex(self._snapshots.current_index)
        self.snapshot_combo.blockSignals(False)
        self.snapshot_count_label.setText(f"{self._snapshots.count}个快照")

    def _on_snapshot_prev(self):
        snap = self._snapshots.prev()
        if snap:
            self.snapshot_combo.setCurrentIndex(self._snapshots.current_index)
            self._display_result(snap.result)

    def _on_snapshot_next(self):
        snap = self._snapshots.next()
        if snap:
            self.snapshot_combo.setCurrentIndex(self._snapshots.current_index)
            self._display_result(snap.result)

    def _on_snapshot_selected(self, index):
        if index >= 0 and index < self._snapshots.count:
            self._snapshots._current_index = index
            snap = self._snapshots.current
            if snap:
                self._display_result(snap.result)

    def _on_snapshot_delete(self):
        snap = self._snapshots.delete_current()
        self._refresh_snapshot_bar()
        if snap:
            self._display_result(snap.result)
        elif self._snapshots.count == 0:
            pass  # 全部删除，结果区保持原样

    # ── 外部接口 ──────────────────────────────────────────────────────────

    def set_store(self, store):
        """接收 ConfigStore，更新 UI 控件"""
        self._store = store
        if store is None:
            return

        # 更新策略标签
        strategy_name = getattr(store, 'strategy_name', 'smart') or 'smart'
        self.strategy_label.setText(strategy_name)

        # 更新权重表
        self._populate_weight_table(store)

        # 更新起始池下拉
        self.pool_combo.clear()
        self.pool_combo.addItem("(从头开始)")

        # 重置脆弱性数据
        self._vulnerability_result = None

    def set_vulnerability_result(self, vuln_result):
        """接收 VulnerabilityResult，填充起始池下拉和保底水位数据"""
        self._vulnerability_result = vuln_result
        if vuln_result is None:
            return

        # 追加剧中池子
        current_items = {self.pool_combo.itemText(i) for i in range(self.pool_combo.count())}
        for pr in vuln_result.pool_results:
            if pr.pool_id not in current_items:
                self.pool_combo.addItem(pr.pool_id)

    def _populate_weight_table(self, store):
        """从 ConfigStore 填充权重表"""
        # 收集所有目标卡
        target_cards = set()
        if hasattr(store, 'targets') and store.targets:
            if isinstance(store.targets, dict):
                target_cards = set(store.targets.keys())
            elif isinstance(store.targets, list):
                target_cards = {t if isinstance(t, str) else str(t) for t in store.targets}

        # 从 GDR 配置中获取权重
        desire_defaults = getattr(store, 'desire_weights', {}) or {}
        miss_cost_defaults = getattr(store, 'miss_cost_weights', {}) or {}

        # 如果 targets 为空，尝试从所有池的奖励卡中收集
        if not target_cards:
            for pe in getattr(store, 'pools', []):
                for reward in getattr(pe, 'rewards', []):
                    if hasattr(reward, 'id'):
                        target_cards.add(reward.id)

        all_cards = sorted(target_cards)
        self.weight_table.setRowCount(len(all_cards))
        for i, cid in enumerate(all_cards):
            self.weight_table.setItem(i, 0, QTableWidgetItem(cid))

            desire_spin = QDoubleSpinBox()
            desire_spin.setRange(0.0, 100.0)
            desire_spin.setValue(desire_defaults.get(cid, 1.0))
            desire_spin.setSingleStep(0.1)
            self.weight_table.setCellWidget(i, 1, desire_spin)

            miss_spin = QDoubleSpinBox()
            miss_spin.setRange(0.0, 100.0)
            miss_spin.setValue(miss_cost_defaults.get(cid, 1.0))
            miss_spin.setSingleStep(0.1)
            self.weight_table.setCellWidget(i, 2, miss_spin)
