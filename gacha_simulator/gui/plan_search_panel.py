"""方案搜索面板 —— 三合一统一面板（替代 StrategyPanel + ResourceSearchPanel + RetreatSearchPanel）

阶段 D 实施（P8 面板合并计划 v8）
"""

from __future__ import annotations
import os
import traceback
from typing import Dict, List, Optional
from dataclasses import dataclass

from PyQt6.QtCore import Qt, QThread, pyqtSignal, QObject, QEvent
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QFormLayout,
    QRadioButton, QComboBox, QLineEdit, QSpinBox, QDoubleSpinBox,
    QPushButton, QLabel, QTableWidget, QTableWidgetItem, QHeaderView,
    QStackedWidget, QProgressBar, QSplitter, QScrollArea, QButtonGroup,
)


class WheelEventFilter(QObject):
    """阻止 QComboBox/QSpinBox/QDoubleSpinBox 在未聚焦时响应鼠标滚轮。

    直接安装在各控件上：未聚焦时吞掉滚轮事件，防止在 ScrollArea 中滚动时误触值变更。
    """
    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.Wheel and not obj.hasFocus():
            return True  # 吞掉事件，阻止值变更
        return super().eventFilter(obj, event)


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

    def select(self, index: int) -> Optional[SearchSnapshot]:
        """跳转到指定索引的快照。"""
        if 0 <= index < len(self._snapshots):
            self._current_index = index
            return self.current
        return None

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
        direction: str = 'backward',  # 仅 Pareto 模式使用：'forward' | 'backward'
        from_pool_id: Optional[str] = None,
        base_resource: float = 0.0,
        pity_counter_init: Optional[Dict[str, int]] = None,
        target_specs: Optional[Dict[str, int]] = None,
        candidate_specs: Optional[Dict[str, int]] = None,
        add_order: Optional[Dict[str, float]] = None,
        remove_order: Optional[Dict[str, float]] = None,
        success_threshold: float = 0.95,
        gdr_key: str = 'all_targets',
        gdr_threshold: float = 1.0,
        num_simulations: int = 500,
        max_workers: int = 4,
        max_binary_iterations: int = 20,
        precision_draws: int = 1,
        strategy_name: str = 'smart',
        strategy_params: Optional[Dict] = None,
        upper_bound: float = 8000,
        lower_bound: float = 0.0,
    ):
        super().__init__()
        self.config_store = config_store
        self.search_mode = search_mode
        self.direction = direction
        self.from_pool_id = from_pool_id
        self.base_resource = base_resource
        self.pity_counter_init = pity_counter_init or {}
        self.target_specs = target_specs or {}
        self.candidate_specs = candidate_specs or {}
        self.add_order = add_order or {}            # 搜索排序用（来自方案搜索面板）
        self.remove_order = remove_order or {}      # 搜索排序用（来自方案搜索面板）
        self.success_threshold = success_threshold
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.num_simulations = num_simulations
        self.max_workers = max_workers
        self.max_binary_iterations = max_binary_iterations
        self.precision_draws = precision_draws
        self.strategy_name = strategy_name
        self.strategy_params = strategy_params or {}
        self.upper_bound = upper_bound
        self.lower_bound = lower_bound

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
                add_order=self.add_order,
                remove_order=self.remove_order,
                success_threshold=self.success_threshold,
                gdr_key=self.gdr_key,
                gdr_threshold=self.gdr_threshold,
                num_simulations=self.num_simulations,
                max_workers=self.max_workers,
                max_binary_iterations=self.max_binary_iterations,
                precision_draws=self.precision_draws,
                strategy_name=self.strategy_name,
                strategy_params=self.strategy_params,
                upper_bound=self.upper_bound,
                lower_bound=self.lower_bound,
                progress_callback=lambda msg, pct: self.progress.emit(msg, pct),
            )

            if self.search_mode == 'min_resource':
                result = self._engine.search_min_resource(self.target_specs)
            elif self.search_mode == 'forward':
                result = self._engine.search_max_targets_forward(self.candidate_specs)
            elif self.search_mode == 'backward':
                result = self._engine.search_max_targets(self.target_specs)
            elif self.search_mode == 'pareto':
                result = self._engine.search_pareto(self.target_specs, direction=self.direction)
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

        from .chart_webview import ChartWebView
        self.chart_view = ChartWebView()
        layout.addWidget(self.chart_view, 1)

        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(6)
        self.steps_table.setHorizontalHeaderLabels(["迭代", "阶段", "资源值", "成功率", "下界", "上界"])
        self.steps_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.steps_table)

    def display(self, result, precision_draws: int = 1, success_threshold: float = 0.95):
        """显示最少资源搜索结果"""
        r = result.min_resource
        cost = result.cost_per_draw if result.cost_per_draw > 0 else 160
        draws = r / cost if cost > 0 else 0
        precision_val = cost * precision_draws  # 精度 = 单抽成本 × 精度抽数

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

            # 行着色——成功率≥阈值绿色，否则红色（与旧 ResourceSearchPanel 一致）
            if step.success_probability >= success_threshold:
                for col in range(6):
                    item = self.steps_table.item(i, col)
                    if item:
                        item.setBackground(QColor(220, 255, 220))
            else:
                for col in range(6):
                    item = self.steps_table.item(i, col)
                    if item:
                        item.setBackground(QColor(255, 220, 220))

        # 绘制二分搜索过程图
        self._draw_chart(result, cost, success_threshold)

    def _draw_chart(self, result, cost, success_threshold: float = 0.95):
        """绘制最少资源二分搜索过程散点图——复用 chart_spec 抽象层。"""
        import numpy as np
        from ..visualization.chart_spec import scatter_multi, ScatterTrace, ChartAnnotation

        steps = result.binary_steps
        if not steps:
            self.chart_view.show_message("无搜索步骤数据")
            return

        resources = [s.resource_value / cost for s in steps]
        probs = [s.success_probability for s in steps]
        phases = [s.phase for s in steps]

        # 按阶段分组
        traces = []
        search_x, search_y = [], []
        binary_x, binary_y = [], []
        verify_x, verify_y = [], []
        for x, y, p in zip(resources, probs, phases):
            if '搜索' in p or '上界' in p or '基线' in p:
                search_x.append(x)
                search_y.append(y)
            elif '二分' in p:
                binary_x.append(x)
                binary_y.append(y)
            elif '验证' in p or '最终' in p:
                verify_x.append(x)
                verify_y.append(y)

        if search_x:
            traces.append(ScatterTrace(
                x=np.array(search_x), y=np.array(search_y), mode='markers',
                name='搜索上界', marker_symbol='square', marker_size=9,
                marker_color='#FF9800',
            ))
        if binary_x:
            traces.append(ScatterTrace(
                x=np.array(binary_x), y=np.array(binary_y), mode='markers',
                name='二分搜索', marker_symbol='circle', marker_size=7,
                marker_color='#2196F3',
            ))
        if verify_x:
            traces.append(ScatterTrace(
                x=np.array(verify_x), y=np.array(verify_y), mode='markers',
                name='最终验证', marker_symbol='diamond', marker_size=6,
                marker_color='#4CAF50',
            ))

        annotations = [
            ChartAnnotation(type='hline', value=success_threshold, color='#999',
                           dash='dash', text=f'阈值 {success_threshold:.0%}'),
            ChartAnnotation(type='vline', value=result.min_resource / cost,
                           color='#4CAF50', dash='dot',
                           text=f'最少资源 ≈{result.min_resource / cost:.1f}抽'),
        ]

        spec = scatter_multi(
            traces=traces,
            title='最少资源二分搜索过程',
            xlabel='额外抽数', ylabel='成功率',
            annotations=annotations,
        )
        self.chart_view.set_chart(spec)


class TargetResultPage(QWidget):
    """最多目标卡结果页（从 StrategyPanel 迁移，参数化前进/后退标签）"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("尚未搜索")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        from .chart_webview import ChartWebView
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
            self.chart_view.show_message("无结果")
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

        # 绘制成功率随步数变化图
        self._draw_chart(points, labels['direction'])

    def _draw_chart(self, points, direction_label):
        """绘制最多目标卡搜索过程——成功率随步数变化，复用 chart_spec 抽象层。"""
        import numpy as np
        from ..visualization.chart_spec import scatter_multi, ScatterTrace, ChartAnnotation

        probs = [p.success_probability for p in points]
        steps = list(range(len(points)))

        traces = [ScatterTrace(
            x=np.array(steps), y=np.array(probs), mode='lines+markers',
            name=direction_label, marker_size=8, marker_color='#2196F3',
            line_color='#2196F3',
        )]
        annotations = [
            ChartAnnotation(type='hline', value=probs[-1], color='#999',
                           dash='dash', text=f'最终 {probs[-1]:.0%}'),
        ]

        spec = scatter_multi(
            traces=traces,
            title=f'最多目标卡搜索过程（{direction_label}）',
            xlabel='步骤', ylabel='成功率',
            annotations=annotations,
        )
        self.chart_view.set_chart(spec)


class ParetoResultPage(QWidget):
    """解空间结果页——沿单一排序路径探索的资源-目标分布"""

    def __init__(self):
        super().__init__()
        layout = QVBoxLayout(self)

        self.summary_label = QLabel("尚未搜索")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        from .chart_webview import ChartWebView
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
            self.chart_view.show_message("无结果")
            return

        best = points[-1]
        self.summary_label.setText(
            f"<b>模式:</b> 解空间 &nbsp;|&nbsp; "
            f"<b>起始池:</b> {result.from_pool_id or '(从头开始)'} &nbsp;|&nbsp; "
            f"<b>最优方案:</b> {len(best.target_specs)} 目标卡 + {result.base_resource + best.extra_resource:,.0f} 资源, "
            f"P={best.success_probability:.2%}"
        )
        self.summary_label.setToolTip(
            "沿单一排序路径探索的解空间分布。非严格 Pareto 前沿——可能遗漏非支配解。"
            "前进法和后退法可能产生不同的解空间。"
        )

        self.detail_table.setRowCount(len(points))
        for i, pt in enumerate(points):
            specs_str = ', '.join(f"{k}×{v}" for k, v in pt.target_specs.items()) or "(无)"
            self.detail_table.setItem(i, 0, QTableWidgetItem(f"{pt.extra_resource:,.0f}"))
            self.detail_table.setItem(i, 1, QTableWidgetItem(specs_str))
            self.detail_table.setItem(i, 2, QTableWidgetItem(f"{pt.success_probability:.2%}"))
            total = result.base_resource + pt.extra_resource
            self.detail_table.setItem(i, 3, QTableWidgetItem(f"{total:,.0f}"))

        # 绘制资源-目标权衡曲线
        self._draw_chart(points, result)

    def _draw_chart(self, points, result):
        """绘制资源-目标权衡散点图——复用 chart_spec.scatter_colored。"""
        import numpy as np
        from ..visualization.chart_spec import scatter_colored

        extra_resources = np.array([p.extra_resource for p in points], dtype=float)
        target_counts = np.array([sum(p.target_specs.values()) for p in points], dtype=float)
        probs = np.array([p.success_probability for p in points], dtype=float)

        # 按资源升序、目标数升序排列，确保连线沿 Pareto 前沿的正确走向
        sort_idx = np.lexsort((target_counts, extra_resources))
        extra_resources = extra_resources[sort_idx]
        target_counts = target_counts[sort_idx]
        probs = probs[sort_idx]

        spec = scatter_colored(
            x=extra_resources, y=target_counts,
            color_values=probs,
            title='解空间',
            xlabel='额外资源', ylabel='目标卡数量',
            colorscale='RdYlGn', colorbar_title='成功率',
            mode='lines+markers',
            line_color='black',
        )
        self.chart_view.set_chart(spec)


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
        self._config_panel = None  # 配置面板引用（如脆弱性结果填充、保底水位等）
        self._worker: Optional[PlanSearchWorker] = None
        self._snapshots = SnapshotManager()
        self._browsing_history = False  # 快照翻看模式标志

        self._setup_ui()
        self._connect_signals()

    # ── UI 构建 ────────────────────────────────────────────────────────────

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # ── 左栏：配置区（可滚动）──
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setMinimumWidth(380)

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
        splitter.addWidget(scroll)

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

        splitter.addWidget(right)
        splitter.setSizes([420, 780])  # 默认比例：左栏 ~35%

        main_layout.addWidget(splitter)

        # 安装滚轮过滤器——阻止下拉框/数字框在未聚焦时响应滚轮
        self._wheel_filter = WheelEventFilter(self)
        for w in self.findChildren((QComboBox, QSpinBox, QDoubleSpinBox)):
            w.installEventFilter(self._wheel_filter)

    def _setup_mode_group(self, parent_layout):
        group = QGroupBox("搜索模式")
        layout = QHBoxLayout(group)

        self.mode_group = QButtonGroup(self)
        self.mode_resource = QRadioButton("最少资源")
        self.mode_target = QRadioButton("最多目标卡")
        self.mode_pareto = QRadioButton("Pareto")
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
        self.resource_combo.setCurrentIndex(4)  # 默认「自定义」（匹配旧 retreat_search_panel 行为）
        self.resource_manual = QLineEdit("0")
        self.resource_manual.setMaximumWidth(120)
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
        group = QGroupBox("搜索优先级配置")
        layout = QVBoxLayout(group)

        hint = QLabel("前进法按「加入顺序」升序 · 后退法按「删除顺序」升序\n"
                      "数值仅用于排列卡牌处理顺序，不代表绝对价值比例。")
        hint.setStyleSheet("color: #888; font-size: 11px;")
        layout.addWidget(hint)

        self.weight_table = QTableWidget()
        self.weight_table.setColumnCount(3)
        self.weight_table.setHorizontalHeaderLabels(["卡ID", "加入顺序", "删除顺序"])
        self.weight_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.weight_table.setMinimumHeight(220)
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

        from gacha_simulator.core.gdr import populate_gdr_combo
        self.gdr_combo = QComboBox()
        self.gdr_combo.setMaxVisibleItems(30)
        populate_gdr_combo(self.gdr_combo, resource_defs=self._store.resource_defs if self._store else None)
        self.gdr_combo.currentIndexChanged.connect(self._on_gdr_changed)
        gdr_row = QHBoxLayout()
        gdr_row.addWidget(self.gdr_combo)
        gdr_row.addWidget(QLabel("阈值:"))
        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(-9999999.0, 9999999.0)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setSingleStep(0.05)
        self.gdr_threshold_spin.setDecimals(2)
        gdr_row.addWidget(self.gdr_threshold_spin)
        # 阈值变化时重新检查 Type 2 退化警告
        self.gdr_threshold_spin.valueChanged.connect(self._update_gdr_hint)
        form.addRow("GDR指标:", gdr_row)

        self._gdr_hint_label = QLabel()
        self._gdr_hint_label.setStyleSheet("color: #c0392b; font-size: 11px; padding: 2px 0;")
        self._gdr_hint_label.setWordWrap(True)
        self._gdr_hint_label.setVisible(False)
        form.addRow("", self._gdr_hint_label)

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

        self.run_btn = QPushButton("开始搜索")
        self.run_btn.setStyleSheet("background: #4CAF50; color: white; font-weight: bold; padding: 6px 20px;")
        btn_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("停止")
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
        self.resource_combo.currentTextChanged.connect(self._on_resource_mode_changed)

    # ── 模式切换 ──────────────────────────────────────────────────────────

    def _on_mode_changed(self, btn_id, checked):
        if not checked:
            return
        mode = {0: 'resource', 1: 'target', 2: 'pareto'}.get(btn_id, 'target')

        # 权重表：最少资源灰显
        is_target = mode in ('target', 'pareto')
        self.weight_table.setEnabled(is_target)
        self.dir_forward.setEnabled(mode in ('target', 'pareto'))
        self.dir_backward.setEnabled(mode in ('target', 'pareto'))

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
        """选择起始池时——从脆弱性结果填充资源预设和保底水位（复用旧 retreat_search_panel 逻辑）。"""
        is_head = (self.pool_combo.currentData() is None)
        self.resource_combo.setEnabled(not is_head)
        self.pity_table.setEnabled(not is_head)

        if is_head:
            self.pity_table.setRowCount(0)
            self.resource_manual.setText("0")
            self.resource_manual.setEnabled(False)
            # 恢复通用预设
            self.resource_combo.clear()
            self.resource_combo.addItems(["50%分位", "均值", "25%分位", "75%分位", "自定义"])
            return

        # 从脆弱性结果中查找匹配的池
        pool_id = self.pool_combo.currentData()
        pr = self._find_vulnerability_pool(pool_id)
        if pr is not None:
            self._update_resource_presets(pr)
            self._update_pity_table(pr)
        else:
            # 池子存在但无脆弱性数据——清除保底表并恢复通用资源预设
            self.pity_table.setRowCount(0)
            self.resource_combo.clear()
            self.resource_combo.addItems(["50%分位", "均值", "25%分位", "75%分位", "自定义"])
            self.resource_manual.setText("0")
            self.resource_manual.setEnabled(False)
            self._on_resource_mode_changed(-1)

    def _find_vulnerability_pool(self, pool_id: str):
        """在脆弱性结果中查找指定池。"""
        if self._vulnerability_result is None:
            return None
        for pr in self._vulnerability_result.pool_results:
            if pr.pool_id == pool_id:
                return pr
        return None

    def _update_resource_presets(self, pr):
        """填充资源预设下拉（复用旧 retreat_search_panel._update_resource_presets 逻辑）。

        使用 currentText() 而非 currentIndex() 保存选中项——头模式下为 5 项列表，
        池模式下为 7 项 VI 列表，索引映射会错位导致选中 VI下限 而显示负值。
        """
        items = ["VI下限", "VI均值", "VI上限", "25%分位", "50%分位", "75%分位", "自定义"]
        self.resource_combo.blockSignals(True)
        current_text = self.resource_combo.currentText()
        self.resource_combo.clear()
        self.resource_combo.addItems(items)
        idx = self.resource_combo.findText(current_text)
        if idx < 0:
            idx = 6  # 默认「自定义」（匹配旧 retreat_search_panel 行为）
        self.resource_combo.setCurrentIndex(idx)
        self.resource_combo.blockSignals(False)
        self._on_resource_mode_changed(-1)

    def _update_pity_table(self, pr):
        """填充保底水位表（复用旧 retreat_search_panel._update_pity_table 逻辑）。"""
        self.pity_table.setRowCount(0)
        if not pr.pity_stats_at_pool_end:
            return
        for i, (cname, snap) in enumerate(pr.pity_stats_at_pool_end.items()):
            self.pity_table.insertRow(i)
            self.pity_table.setItem(i, 0, QTableWidgetItem(cname))
            self.pity_table.setItem(i, 1, QTableWidgetItem(f"{snap.mean:.1f}"))
            self.pity_table.setItem(i, 2, QTableWidgetItem(f"{snap.median:.1f}"))
            self.pity_table.setItem(i, 3, QTableWidgetItem(f"{snap.p25:.1f}"))
            self.pity_table.setItem(i, 4, QTableWidgetItem(f"{snap.p75:.1f}"))
            default_val = int(round(snap.mean))
            spin = QSpinBox()
            spin.setRange(0, 99999)
            spin.setValue(default_val)
            spin.installEventFilter(self._wheel_filter)
            self.pity_table.setCellWidget(i, 5, spin)

    def _get_selected_resource(self):
        """根据当前资源预设计算基准资源值（复用旧 retreat_search_panel._get_selected_resource 逻辑）。"""
        mode = self.resource_combo.currentText()
        if mode == "自定义":
            try:
                return float(self.resource_manual.text() or '0')
            except ValueError:
                return 0.0
        pool_id = self.pool_combo.currentData()
        if not pool_id:
            return 0.0
        pr = self._find_vulnerability_pool(pool_id)
        if pr is None:
            return 0.0
        if mode in ("VI下限", "VI均值", "VI上限"):
            if pr.vulnerability_intervals:
                vi = pr.vulnerability_intervals[0]
                return {"VI下限": vi.lower, "VI均值": vi.mean, "VI上限": vi.upper}[mode]
        elif mode in ("25%分位", "50%分位", "75%分位"):
            if pr.resource_values_all:
                import numpy as np
                pct = {"25%分位": 25, "50%分位": 50, "75%分位": 75}[mode]
                return float(np.percentile(pr.resource_values_all, pct))
        return 0.0

    def _on_resource_mode_changed(self, index):
        """资源预设切换时更新手动输入框的值。"""
        mode = self.resource_combo.currentText()
        if mode == "自定义":
            self.resource_manual.setEnabled(True)
            self.resource_manual.setText("0")
        else:
            val = self._get_selected_resource()
            self.resource_manual.setText(f"{val:.0f}")
            self.resource_manual.setEnabled(False)

    def _on_gdr_changed(self, index):
        """GDR 指标变化时：更新默认阈值 + 运行兼容性检查。"""
        from gacha_simulator.core.gdr import get_default_threshold
        key = self.gdr_combo.currentData()
        if key is None:
            return
        default = get_default_threshold(key)
        self.gdr_threshold_spin.setValue(default)
        self._update_gdr_hint()

    def _update_gdr_hint(self):
        """更新 GDR 兼容性提示——不修改阈值，仅检查当前状态。

        调用时机：
        - GDR 下拉框切换时（_on_gdr_changed 末尾）
        - 搜索完成恢复控件时（_set_controls_enabled）
        - 阈值 spinbox 变动时（valueChanged 信号）
        """
        from gacha_simulator.core.gdr import resolve_gdr_definition
        key = self.gdr_combo.currentData()
        gdr_def = resolve_gdr_definition(key)
        incompatible = gdr_def is not None and not gdr_def.compatible_with_min_resource

        hints = []
        if incompatible:
            if gdr_def.lower_is_better:
                hints.append("⚠ 此指标的 p(r) 随资源递减，与「最少资源」搜索方向相反——请切换到连续型 GDR（如「简单目标达成率」）")
            else:
                hints.append("⚠ 此指标的 p(r) 恒为常数，无法区分不同资源水平的好坏——请切换到连续型 GDR（如「简单目标达成率」）")

        current_threshold = self.gdr_threshold_spin.value()
        if key in {'resource_remaining', 'pity_draws'} and current_threshold <= 0.0:
            hints.append("当前阈值 0.0 可能使所有资源水平都满足条件——请设置有意义的阈值")

        if key in {'resource_efficiency', 'draw_conversion_efficiency'}:
            hints.append("零资源时未定义（除零），极低资源区间结果可能不可靠")

        self._gdr_hint_label.setText(' | '.join(hints))
        self._gdr_hint_label.setVisible(bool(hints))

    # ── 搜索触发 ──────────────────────────────────────────────────────────

    def _on_run_clicked(self):
        try:
            if self._worker is not None and self._worker.isRunning():
                return
            if self._store is None:
                self.status_update.emit("请先在配置页加载或创建配置")
                return

            mode_id = self.mode_group.checkedId()

            # 不兼容 GDR 拦截
            from gacha_simulator.core.gdr import resolve_gdr_definition
            gdr_key = self.gdr_combo.currentData() or 'all_targets'
            gdr_def = resolve_gdr_definition(gdr_key)
            if gdr_def is not None and not gdr_def.compatible_with_min_resource:
                self.status_label.setText("GDR不兼容")
                return
            mode_map = {0: 'min_resource', 1: None, 2: 'pareto'}
            search_mode = mode_map.get(mode_id)
            if search_mode is None:
                # 最多目标卡：根据方向决定 forward/backward
                search_mode = 'forward' if self.dir_forward.isChecked() else 'backward'

            # Pareto 模式读取方向（前进/后退），其他模式忽略此参数
            direction = 'forward' if self.dir_forward.isChecked() else 'backward'

            # 构建搜索排序字典（来自方案搜索面板的「加入顺序/删除顺序」列）
            add_order = {}
            remove_order = {}
            for row in range(self.weight_table.rowCount()):
                cid = self.weight_table.item(row, 0)
                add_spin = self.weight_table.cellWidget(row, 1)
                remove_spin = self.weight_table.cellWidget(row, 2)
                if cid:
                    cid_text = cid.text()
                    if add_spin:
                        try:
                            add_order[cid_text] = float(add_spin.value())
                        except (ValueError, AttributeError):
                            add_order[cid_text] = 1.0
                    if remove_spin:
                        try:
                            remove_order[cid_text] = float(remove_spin.value())
                        except (ValueError, AttributeError):
                            remove_order[cid_text] = 1.0

            from_pool_id = None if self.pool_combo.currentData() is None else self.pool_combo.currentData()

            base_resource = 0.0
            pity_init = {}
            if from_pool_id is not None and self._vulnerability_result is not None:
                base_resource = self._get_selected_resource()
                for row in range(self.pity_table.rowCount()):
                    ctr = self.pity_table.item(row, 0)
                    spin = self.pity_table.cellWidget(row, 5)
                    if ctr and spin:
                        pity_init[ctr.text()] = spin.value()

            target_specs = self._collect_target_specs()
            if not target_specs:
                self.status_label.setText("请先在配置中添加目标卡")
                self.status_update.emit("请先在配置中添加目标卡")
                return

            self._worker = PlanSearchWorker(
                config_store=self._store,
                search_mode=search_mode,
                direction=direction,
                from_pool_id=from_pool_id,
                base_resource=base_resource,
                pity_counter_init=pity_init,
                target_specs=target_specs,
                candidate_specs=target_specs,
                add_order=add_order,
                remove_order=remove_order,
                success_threshold=self.success_threshold_spin.value(),
                gdr_key=self.gdr_combo.currentData() or 'all_targets',
                gdr_threshold=self.gdr_threshold_spin.value(),
                num_simulations=self.num_simulations_spin.value(),
                max_workers=self.max_workers_spin.value(),
                max_binary_iterations=self.max_iter_spin.value(),
                precision_draws=self.precision_spin.value(),
                strategy_name=self._store.strategy_name if self._store else 'smart',
                strategy_params=self._store.strategy_params if self._store else None,
                upper_bound=float(self.upper_bound_spin.value()),
                lower_bound=float(self.lower_bound_spin.value()),
            )

            self._worker.progress.connect(self._on_progress)
            self._worker.finished.connect(self._on_finished)
            self._worker.error.connect(self._on_error)

            self._browsing_history = False
            self._set_controls_enabled(False)
            self.progress_bar.setVisible(True)
            self.progress_bar.setValue(0)
            self._worker.start()
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.status_label.setText(f"启动搜索失败: {e}")

    def _collect_target_specs(self) -> Dict[str, int]:
        """从配置的 target_cards 中收集目标规格（数量来自配置，权重表仅用于顺序）。"""
        specs = {}
        if self._store is not None and hasattr(self._store, 'target_cards'):
            for tc in self._store.target_cards:
                if hasattr(tc, 'card_id'):
                    specs[tc.card_id] = getattr(tc, 'quantity', 1)
        return specs

    def _on_stop_clicked(self):
        """请求停止搜索——设置标志位后由 _on_finished 恢复 UI，不阻塞 GUI 线程。"""
        if self._worker:
            self._worker.stop()
            self.status_label.setText("正在停止...")

    # ── 进度 / 完成 / 错误 ─────────────────────────────────────────────────

    def _on_progress(self, msg, pct):
        self.status_label.setText(msg)
        self.progress_bar.setValue(pct)
        self.status_update.emit(msg)

    def _on_finished(self, result):
        self._set_controls_enabled(True)
        self.progress_bar.setVisible(False)
        try:
            self.status_label.setText("搜索完成")
            self.status_update.emit("方案搜索完成")

            if result is None or not result.points:
                self.status_label.setText("搜索已停止" if result is None else "无可行方案")
                return

            # 推送快照
            import datetime
            mode_labels = {'min_resource': '最少资源', 'forward': '最多目标卡·前进', 'backward': '最多目标卡·后退', 'pareto': '解空间'}
            mode_display = mode_labels.get(result.search_mode, result.search_mode)
            if result.search_mode == 'pareto':
                dir_label = '前进' if getattr(result, 'direction', 'backward') == 'forward' else '后退'
                mode_display = f'解空间·{dir_label}'
            timestamp = datetime.datetime.now().strftime('%H:%M')
            name = f"{mode_display} @{timestamp}"

            snapshot = SearchSnapshot(name=name, result=result)
            self._snapshots.push(snapshot)
            self._refresh_snapshot_bar()

            # 显示结果
            self._display_result(result)
        except Exception:
            import traceback
            traceback.print_exc()
            self.status_label.setText("结果展示失败，请查看控制台")

    def _on_error(self, err):
        self._set_controls_enabled(True)
        self.progress_bar.setVisible(False)
        self.status_label.setText(f"错误: {err}")
        self.status_update.emit(f"搜索失败: {err}")

    # ── 结果显示 ──────────────────────────────────────────────────────────

    def _display_result(self, result):
        """根据结果的 search_mode 显示到对应页面（而非当前单选按钮状态）"""
        mode = result.search_mode
        page_map = {'min_resource': 0, 'forward': 1, 'backward': 1, 'pareto': 2}
        page_idx = page_map.get(mode, 1)

        if mode == 'min_resource':
            self.resource_page.display(
                result,
                precision_draws=self.precision_spin.value(),
                success_threshold=self.success_threshold_spin.value(),
            )
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
            # setCurrentIndex 触发 _on_snapshot_selected → _display_result，此处不重复调用
            self.snapshot_combo.setCurrentIndex(self._snapshots.current_index)

    def _on_snapshot_next(self):
        snap = self._snapshots.next()
        if snap:
            self.snapshot_combo.setCurrentIndex(self._snapshots.current_index)

    def _on_snapshot_selected(self, index):
        """ComboBox 手动选择快照——通过 select() API 设置索引。"""
        snap = self._snapshots.select(index)
        if snap:
            # 进入历史翻看模式：禁用配置控件，但保留运行按钮可用（允许退出翻看开始新搜索）
            self._browsing_history = True
            self._set_controls_enabled(False)
            self.run_btn.setEnabled(True)
            self.stop_btn.setEnabled(False)
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

        # 重新填充 GDR 下拉框以反映多资源类型展开（_setup_ui 时 store 尚为 None）
        if hasattr(self, 'gdr_combo'):
            from gacha_simulator.core.gdr import populate_gdr_combo
            old_key = self.gdr_combo.currentData()
            self.gdr_combo.blockSignals(True)
            populate_gdr_combo(self.gdr_combo, resource_defs=store.resource_defs)
            if old_key:
                idx = self.gdr_combo.findData(old_key)
                if idx >= 0:
                    self.gdr_combo.setCurrentIndex(idx)
            self.gdr_combo.blockSignals(False)
            self._on_gdr_changed(self.gdr_combo.currentIndex())

        # 更新策略标签
        strategy_name = getattr(store, 'strategy_name', 'smart') or 'smart'
        from gacha_simulator.core.strategy import strategy_key_to_type
        self.strategy_label.setText(strategy_key_to_type(strategy_name))

        # 更新权重表
        self._populate_weight_table(store)

        # 更新起始池下拉
        self.pool_combo.clear()
        self.pool_combo.addItem("(从头开始)", None)
        # 从配置中填充所有池子
        pool_names = self._get_pool_names(store)
        for pe in getattr(store, 'pools', []):
            if pe.enabled:
                display = pool_names.get(pe.pool_id, pe.pool_id)
                self.pool_combo.addItem(display, pe.pool_id)

        # 从配置中自动检测单抽成本
        from gacha_simulator.core.retreat_search import get_cost_per_draw
        detected_cost = get_cost_per_draw([pe for pe in getattr(store, 'pools', []) if pe.enabled])
        if detected_cost > 0:
            self.cost_per_draw_spin.setValue(int(detected_cost))

    def _get_pool_names(self, store) -> Dict[str, str]:
        """池ID → 显示名映射"""
        names = {}
        for pe in getattr(store, 'pools', []):
            names[pe.pool_id] = getattr(pe, 'name', pe.pool_id) or pe.pool_id
        return names

    def set_vulnerability_result(self, vuln_result):
        """接收 VulnerabilityResult，填充起始池下拉和保底水位数据"""
        self._vulnerability_result = vuln_result
        if vuln_result is None:
            return

        # 追加剧中池子（仅含 vulnerability_intervals 的池，与旧 retreat_search_panel 一致）
        current_ids = {self.pool_combo.itemData(i) for i in range(self.pool_combo.count())}
        for pr in vuln_result.pool_results:
            if pr.pool_id not in current_ids and pr.vulnerability_intervals:
                # 尝试从 store 获取池名称，否则用 pool_id
                display = self._get_pool_name(pr.pool_id) if self._store else pr.pool_id
                self.pool_combo.addItem(display, pr.pool_id)

    def _get_pool_name(self, pool_id: str) -> str:
        """从 store 查找池的显示名"""
        if self._store is None:
            return pool_id
        for pe in getattr(self._store, 'pools', []):
            if pe.pool_id == pool_id:
                return getattr(pe, 'name', pool_id) or pool_id
        return pool_id

    def set_config_panel(self, config_panel):
        """接收配置面板引用——用于脆弱性结果填充、保底水位等辅助功能。"""
        self._config_panel = config_panel

    def _set_controls_enabled(self, enabled: bool):
        """P8 状态机：搜索中 / 历史翻看中禁用所有配置控件，仅「停止」按钮可用。"""
        self.mode_resource.setEnabled(enabled)
        self.mode_target.setEnabled(enabled)
        self.mode_pareto.setEnabled(enabled)
        self.pool_combo.setEnabled(enabled)
        self.resource_combo.setEnabled(enabled)
        self.resource_manual.setEnabled(enabled)
        self.pity_table.setEnabled(enabled)
        self.weight_table.setEnabled(enabled)
        self.dir_forward.setEnabled(enabled)
        self.dir_backward.setEnabled(enabled)
        self.gdr_combo.setEnabled(enabled)
        self.gdr_threshold_spin.setEnabled(enabled)
        self.success_threshold_spin.setEnabled(enabled)
        self.num_simulations_spin.setEnabled(enabled)
        self.max_workers_spin.setEnabled(enabled)
        self.cost_per_draw_spin.setEnabled(enabled)
        self.upper_bound_spin.setEnabled(enabled)
        self.lower_bound_spin.setEnabled(enabled)
        self.precision_spin.setEnabled(enabled)
        self.max_iter_spin.setEnabled(enabled)
        self.run_btn.setEnabled(enabled)

        if enabled:
            # 重新应用模式/池子特定的灰显规则
            mode_id = self.mode_group.checkedId()
            self._on_mode_changed(mode_id, True)
            self._on_pool_changed(self.pool_combo.currentIndex())
            # 重新检查 GDR 兼容性——避免将 incompatible 按钮错误启用（不重置阈值）
            self._update_gdr_hint()

        self.stop_btn.setEnabled(not enabled)

    def _populate_weight_table(self, store):
        """从 ConfigStore 填充搜索优先级表（加入顺序/删除顺序）。

        注意：此表的数值仅用于搜索排序，与配置页的 GDR 权重（抽取意愿/错失代价）
        完全独立。默认值均为 1.0（等优先级）。
        """
        # 收集所有目标卡
        target_cards = set()
        if hasattr(store, 'target_cards') and store.target_cards:
            for tc in store.target_cards:
                cid = tc.card_id if hasattr(tc, 'card_id') else str(tc)
                target_cards.add(cid)

        # 如果 target_cards 为空，尝试从所有池的 distribution 中收集卡ID
        if not target_cards:
            for pe in getattr(store, 'pools', []):
                for dist_entry in getattr(pe, 'distribution', []):
                    cid = getattr(dist_entry, 'card_id', None)
                    if cid and cid != '_no_card':
                        target_cards.add(cid)

        all_cards = sorted(target_cards)
        self.weight_table.setRowCount(len(all_cards))
        for i, cid in enumerate(all_cards):
            self.weight_table.setItem(i, 0, QTableWidgetItem(cid))

            add_spin = QDoubleSpinBox()
            add_spin.setRange(0.0, 100.0)
            add_spin.setValue(1.0)
            add_spin.setSingleStep(0.1)
            add_spin.installEventFilter(self._wheel_filter)
            self.weight_table.setCellWidget(i, 1, add_spin)

            remove_spin = QDoubleSpinBox()
            remove_spin.setRange(0.0, 100.0)
            remove_spin.setValue(1.0)
            remove_spin.setSingleStep(0.1)
            remove_spin.installEventFilter(self._wheel_filter)
            self.weight_table.setCellWidget(i, 2, remove_spin)
