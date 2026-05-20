#!/usr/bin/env python3
"""
资源搜索面板 - 二分搜索最少资源使得成功率≥阈值
"""

import sys
import os
import traceback
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QComboBox, QTextEdit
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from gacha_simulator.core.config_store import ConfigStore
from gacha_simulator.core.forward_backward import ResourceSearchStep, ResourceSearchResult
from gacha_simulator.core.gdr import populate_gdr_combo, get_default_threshold


class ResourceSearchWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(object)

    def __init__(self, target_specs, success_threshold, num_simulations,
                 initial_resource_hint, resource_lo, max_iterations, precision_draws,
                 gdr_key, gdr_threshold,
                 config_store, max_workers=4,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None,
                 cost_per_draw_override=None):
        super().__init__()
        self.target_specs = target_specs
        self.success_threshold = success_threshold
        self.num_simulations = num_simulations
        self.initial_resource_hint = initial_resource_hint
        self.resource_lo = resource_lo
        self.max_iterations = max_iterations
        self.precision_draws = precision_draws
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.config_store = config_store
        self.max_workers = max_workers
        self.desire_weights = desire_weights
        self.miss_cost_weights = miss_cost_weights
        self.card_value_weights = card_value_weights
        self.cost_per_draw_override = cost_per_draw_override
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def _build_simulation_env(self):
        from .batch_simulator import SimulationEnvBuilder
        env = SimulationEnvBuilder.from_config_store(self.config_store)
        self._sim_env = {
            'pools': env.pools,
            'schedule_mgr': env.schedule_mgr,
            'end_time': env.end_time,
            'pity_engine': env.pity_engine,
            'resource_gain': env.resource_gain,
            'pity_state_init': env.pity_state_init,
            'card_defs': env.card_defs,
            'initial_resources': env.initial_resources,
            'ssr_ids': env.ssr_ids,
        }
        self._actual_cost_per_draw = self._extract_cost_per_draw(env.pools)
        self._display_cost_per_draw = self.cost_per_draw_override if self.cost_per_draw_override else self._actual_cost_per_draw
        self._initial_resources_backup = dict(env.initial_resources)


    @staticmethod
    def _extract_cost_per_draw(pools):
        if not pools:
            return 160
        for p in pools:
            cost = p.cost
            if isinstance(cost, list) and cost:
                for opt in cost:
                    if isinstance(opt, dict):
                        return float(list(opt.values())[0])
            elif isinstance(cost, dict):
                return float(list(cost.values())[0])
        return 160

    @staticmethod
    def _extract_cost_per_draw_from_entries(pool_entries):
        if not pool_entries:
            return 160
        for pe in pool_entries:
            cost_str = getattr(pe, 'cost', '')
            if not cost_str:
                continue
            try:
                parts = cost_str.split(':')
                if len(parts) == 2:
                    return float(parts[1])
            except (ValueError, IndexError):
                continue
        return 160

    def _simulate_with_resource(self, resource_value):
        from .batch_simulator import run_batch_parallel
        from ..core.strategy import strategy_type_to_key
        ir = dict(self._initial_resources_backup)
        ir['draw_resource'] = resource_value
        histories = run_batch_parallel(
            pools=self._sim_env['pools'],
            schedule_mgr=self._sim_env['schedule_mgr'],
            end_time=self._sim_env['end_time'],
            pity_engine=self._sim_env['pity_engine'],
            resource_gain=self._sim_env['resource_gain'],
            pity_state_init=self._sim_env['pity_state_init'],
            card_defs=self._sim_env['card_defs'],
            target_specs=self.target_specs,
            initial_resources=ir,
            num_simulations=self.num_simulations,
            max_workers=self.max_workers,
            seed=0,
            strategy_name=strategy_type_to_key(self.config_store.strategy_type),
            strategy_params=self.config_store.strategy_params,
            ssr_ids=self._sim_env['ssr_ids'],
        )
        from gacha_simulator.core.gdr import compute_success_probability
        return compute_success_probability(histories, self.target_specs, self.gdr_key, self.gdr_threshold,
                                           self.desire_weights, self.miss_cost_weights, self.card_value_weights)

    def run(self):
        try:
            self.progress.emit("正在构建模拟环境...", 0)
            self._build_simulation_env()

            actual_cost_per_draw = self._actual_cost_per_draw
            display_cost_per_draw = self._display_cost_per_draw
            epsilon = actual_cost_per_draw * self.precision_draws

            steps = []
            iteration = 0

            self.progress.emit("阶段一：搜索上界...", 5)
            r_hi = self.initial_resource_hint
            if r_hi <= 0:
                r_hi = actual_cost_per_draw * 100

            prob = self._simulate_with_resource(r_hi)
            iteration += 1
            steps.append(ResourceSearchStep(
                iteration=iteration, resource_value=r_hi,
                success_probability=prob, phase='搜索上界',
                lo_bound=float(self.resource_lo), hi_bound=r_hi,
            ))
            self.progress.emit(f"上界搜索: R={r_hi:.0f}, P={prob:.2%}", 10)

            doubling_count = 0
            while prob < self.success_threshold:
                if self._should_stop:
                    self.finished.emit(None)
                    return
                r_hi *= 2
                prob = self._simulate_with_resource(r_hi)
                iteration += 1
                doubling_count += 1
                steps.append(ResourceSearchStep(
                    iteration=iteration, resource_value=r_hi,
                    success_probability=prob, phase='搜索上界',
                    lo_bound=0, hi_bound=r_hi,
                ))
                pct = min(10 + doubling_count * 5, 30)
                self.progress.emit(f"上界搜索: R={r_hi:.0f}, P={prob:.2%}", pct)
                if doubling_count > 15:
                    self.progress.emit("上界搜索超过15次翻倍，终止", 100)
                    result = ResourceSearchResult(
                        steps=steps, min_resource=r_hi,
                        final_success_probability=prob,
                        cost_per_draw=display_cost_per_draw,
                        target_specs=self.target_specs,
                        total_iterations=iteration,
                    )
                    self.finished.emit(result)
                    return

            r_lo = float(self.resource_lo)
            if r_hi < r_lo:
                r_hi = r_lo + actual_cost_per_draw * 100
            self.progress.emit(f"阶段二：二分搜索 [{r_lo:.0f}, {r_hi:.0f}]", 35)

            binary_iter = 0
            max_binary = self.max_iterations
            while r_hi - r_lo > epsilon:
                if self._should_stop:
                    self.finished.emit(None)
                    return

                binary_iter += 1
                if binary_iter > max_binary:
                    break

                r_mid = (r_lo + r_hi) / 2.0
                prob = self._simulate_with_resource(r_mid)
                iteration += 1

                if prob >= self.success_threshold:
                    r_hi = r_mid
                    phase = '二分(满足)'
                else:
                    r_lo = r_mid
                    phase = '二分(不足)'

                steps.append(ResourceSearchStep(
                    iteration=iteration, resource_value=r_mid,
                    success_probability=prob, phase=phase,
                    lo_bound=r_lo, hi_bound=r_hi,
                ))

                pct = int(35 + 60 * binary_iter / max(max_binary, 1))
                pct = min(pct, 95)
                draws_hi = r_hi / display_cost_per_draw
                self.progress.emit(
                    f"二分 #{binary_iter}: R={r_mid:.0f} P={prob:.2%} → [{r_lo:.0f}, {r_hi:.0f}] ≈{draws_hi:.1f}抽",
                    pct
                )

            final_prob = self._simulate_with_resource(r_hi)
            iteration += 1
            steps.append(ResourceSearchStep(
                iteration=iteration, resource_value=r_hi,
                success_probability=final_prob, phase='最终验证',
                lo_bound=r_lo, hi_bound=r_hi,
            ))

            result = ResourceSearchResult(
                steps=steps,
                min_resource=r_hi,
                final_success_probability=final_prob,
                cost_per_draw=display_cost_per_draw,
                target_specs=self.target_specs,
                total_iterations=iteration,
            )
            self.progress.emit(
                f"搜索完成: 最少资源={r_hi:.0f} (≈{r_hi/display_cost_per_draw:.1f}抽), P={final_prob:.2%}",
                100
            )
            self.finished.emit(result)

        except Exception as e:
            import traceback as tb
            tb.print_exc()
            detailed = f"{type(e).__name__}: {e}\n\n{tb.format_exc()}"

            class DetailedError(Exception):
                def __init__(self, msg):
                    self.msg = msg

                def __str__(self):
                    return self.msg

            self.error.emit(DetailedError(detailed))


class ResourceSearchPanel(QWidget):
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self._store = None
        self._worker = None
        self._setup_ui()

    def set_store(self, store: ConfigStore):
        self._store = store
        self._refresh_target_display()
        self._update_cost_per_draw_default()

    def set_config_panel(self, config_panel):
        self._config_panel = config_panel

    def _update_cost_per_draw_default(self):
        if not self._store or not self._store.pools:
            return
        cost = ResourceSearchWorker._extract_cost_per_draw_from_entries(self._store.pools)
        if cost > 0:
            self.cost_per_draw_spin.setValue(int(cost))

    def _refresh_target_display(self):
        if not self._store or not self._store.target_cards:
            self.target_info_label.setText("未配置目标卡，请先在配置面板中添加")
            return
        cards = [f"{tc.card_id}×{getattr(tc, 'quantity', 1)}" for tc in self._store.target_cards]
        self.target_info_label.setText("当前目标卡: " + ", ".join(cards))

    def _on_gdr_changed(self, index):
        key = self.gdr_combo.currentData()
        default = get_default_threshold(key)
        self.gdr_threshold_spin.setValue(default)

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left_panel = QWidget()
        left_layout = QVBoxLayout(left_panel)

        target_group = QGroupBox("目标卡")
        target_layout = QVBoxLayout(target_group)
        self.target_info_label = QLabel("未配置目标卡")
        self.target_info_label.setWordWrap(True)
        self.target_info_label.setStyleSheet("padding: 6px; background: #f0f0f0; border-radius: 4px;")
        target_layout.addWidget(self.target_info_label)
        left_layout.addWidget(target_group)

        params_group = QGroupBox("搜索参数")
        params_layout = QFormLayout(params_group)

        self.gdr_combo = QComboBox()
        self.gdr_combo.setMaxVisibleItems(30)
        populate_gdr_combo(self.gdr_combo)
        self.gdr_combo.setCurrentIndex(0)
        self.gdr_combo.currentIndexChanged.connect(self._on_gdr_changed)
        params_layout.addRow("成功判定GDR:", self.gdr_combo)

        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(0.0, 9999999.0)
        self.gdr_threshold_spin.setSingleStep(0.1)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setDecimals(2)
        self.gdr_threshold_spin.setToolTip("GDR指标需达到此值才算成功")
        params_layout.addRow("GDR达标阈值:", self.gdr_threshold_spin)

        self.success_threshold_spin = QDoubleSpinBox()
        self.success_threshold_spin.setRange(0.01, 1.0)
        self.success_threshold_spin.setSingleStep(0.01)
        self.success_threshold_spin.setValue(0.95)
        self.success_threshold_spin.setDecimals(2)
        self.success_threshold_spin.setToolTip("模拟中GDR达标的比例需超过此阈值")
        params_layout.addRow("成功率阈值:", self.success_threshold_spin)

        self.simulations_spin = QSpinBox()
        self.simulations_spin.setRange(50, 10000)
        self.simulations_spin.setSingleStep(100)
        self.simulations_spin.setValue(1000)
        params_layout.addRow("每次搜索模拟次数:", self.simulations_spin)

        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, os.cpu_count() or 16)
        self.max_workers_spin.setValue(max(1, (os.cpu_count() or 8) - 2))
        params_layout.addRow("并行进程数:", self.max_workers_spin)

        self.resource_hint_spin = QSpinBox()
        self.resource_hint_spin.setRange(0, 9999999)
        self.resource_hint_spin.setSingleStep(5000)
        self.resource_hint_spin.setValue(55000)
        self.resource_hint_spin.setToolTip("二分搜索的起始资源值（上界），若该值已够则直接进入二分；0表示自动从100抽成本开始")
        params_layout.addRow("搜索起始资源:", self.resource_hint_spin)

        self.resource_lo_spin = QSpinBox()
        self.resource_lo_spin.setRange(0, 9999999)
        self.resource_lo_spin.setSingleStep(5000)
        self.resource_lo_spin.setValue(0)
        self.resource_lo_spin.setToolTip("二分搜索的下界，0表示从0开始搜索；设置更高可加速收敛")
        params_layout.addRow("搜索下界:", self.resource_lo_spin)

        self.max_iterations_spin = QSpinBox()
        self.max_iterations_spin.setRange(5, 100)
        self.max_iterations_spin.setSingleStep(5)
        self.max_iterations_spin.setValue(30)
        self.max_iterations_spin.setToolTip("二分搜索最大迭代次数")
        params_layout.addRow("最大二分迭代:", self.max_iterations_spin)

        self.precision_spin = QSpinBox()
        self.precision_spin.setRange(1, 20)
        self.precision_spin.setSingleStep(1)
        self.precision_spin.setValue(1)
        self.precision_spin.setToolTip("精度=几抽的成本，1表示精确到1抽")
        params_layout.addRow("精度(抽):", self.precision_spin)

        self.cost_per_draw_spin = QSpinBox()
        self.cost_per_draw_spin.setRange(1, 9999999)
        self.cost_per_draw_spin.setSingleStep(10)
        self.cost_per_draw_spin.setValue(160)
        self.cost_per_draw_spin.setToolTip("每抽消耗的资源数量，默认从卡池配置解析，可手动修改")
        params_layout.addRow("单抽成本:", self.cost_per_draw_spin)

        left_layout.addWidget(params_group)

        btn_layout = QHBoxLayout()
        self.run_btn = QPushButton("开始搜索")
        self.run_btn.clicked.connect(self._on_run_clicked)
        btn_layout.addWidget(self.run_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setEnabled(False)
        btn_layout.addWidget(self.stop_btn)
        left_layout.addLayout(btn_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        left_layout.addWidget(self.status_label)

        left_layout.addStretch()

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        result_group = QGroupBox("搜索结果")
        result_layout = QVBoxLayout(result_group)

        desc_label = QLabel(
            "<b>资源搜索</b>：给定目标卡和成功率阈值，二分搜索最少抽卡资源。"
            "先搜索上界（不够则翻倍），再二分缩小到精度范围内。"
        )
        desc_label.setWordWrap(True)
        result_layout.addWidget(desc_label)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        self.result_label.setStyleSheet("padding: 6px; background: #f5f5f5; border-radius: 4px; font-size: 13px; line-height: 1.4;")
        result_layout.addWidget(self.result_label)

        right_layout.addWidget(result_group)

        steps_group = QGroupBox("搜索过程")
        steps_layout = QVBoxLayout(steps_group)

        self.steps_table = QTableWidget()
        self.steps_table.setColumnCount(6)
        self.steps_table.setHorizontalHeaderLabels(
            ["迭代", "阶段", "资源值", "成功率", "下界", "上界"]
        )
        header = self.steps_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Fixed)
        header.setSectionResizeMode(4, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        self.steps_table.setColumnWidth(0, 50)
        self.steps_table.setColumnWidth(1, 90)
        self.steps_table.setColumnWidth(3, 80)
        self.steps_table.verticalHeader().setVisible(False)
        steps_layout.addWidget(self.steps_table)

        right_layout.addWidget(steps_group)

        self.chart_group = QGroupBox("成功率-资源趋势")
        chart_layout = QVBoxLayout(self.chart_group)
        self.chart_label = QLabel("运行搜索后显示图表")
        self.chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label.setMinimumHeight(300)
        chart_layout.addWidget(self.chart_label)
        right_layout.addWidget(self.chart_group)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 650])

    def _on_run_clicked(self):
        if not self._store:
            self.status_update.emit("请先加载配置")
            return

        target_cards = self._store.target_cards
        if not target_cards:
            self.status_update.emit("请先在配置中添加目标卡")
            return

        target_specs = {}
        for tc in target_cards:
            target_specs[tc.card_id] = getattr(tc, 'quantity', 1)

        gdr_key = self.gdr_combo.currentData() or 'target_achievement'

        desire_weights = None
        miss_cost_weights = None
        card_value_weights = None
        if hasattr(self, '_config_panel') and self._config_panel:
            desire_weights = self._config_panel.get_desire_weights()
            miss_cost_weights = self._config_panel.get_miss_cost_weights()
            card_value_weights = self._config_panel.get_card_value_weights()

        self._worker = ResourceSearchWorker(
            target_specs=target_specs,
            success_threshold=self.success_threshold_spin.value(),
            num_simulations=self.simulations_spin.value(),
            initial_resource_hint=self.resource_hint_spin.value(),
            resource_lo=self.resource_lo_spin.value(),
            max_iterations=self.max_iterations_spin.value(),
            precision_draws=self.precision_spin.value(),
            gdr_key=gdr_key,
            gdr_threshold=self.gdr_threshold_spin.value(),
            config_store=self._store,
            max_workers=self.max_workers_spin.value(),
            desire_weights=desire_weights,
            miss_cost_weights=miss_cost_weights,
            card_value_weights=card_value_weights,
            cost_per_draw_override=self.cost_per_draw_spin.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.result_label.setText("搜索中...")
        self.steps_table.setRowCount(0)
        self._worker.start()

    def _on_stop_clicked(self):
        if self._worker:
            self._worker.stop()
            self._worker.wait()

    def _on_progress(self, msg, pct):
        self.status_label.setText(msg)
        self.progress_bar.setValue(pct)
        self.status_update.emit(msg)

    def _on_finished(self, result):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)

        if result is None:
            self.status_update.emit("搜索已停止")
            return

        r = result.min_resource
        draws = r / result.cost_per_draw if result.cost_per_draw > 0 else 0
        precision_val = result.cost_per_draw * self.precision_spin.value()
        from gacha_simulator.core.strategy import STRATEGY_REGISTRY, strategy_type_to_key
        _skey = strategy_type_to_key(self._store.strategy_type) if self._store else 'smart'
        _sname = STRATEGY_REGISTRY.get(_skey, {}).get('display_name', _skey)
        self.result_label.setText(
            f"<b>使用策略:</b> {_sname}<br>"
            f"<b>最少所需资源:</b> {r:.0f} &nbsp;|&nbsp; "
            f"<b>约等于:</b> {draws:.1f} 抽 &nbsp;|&nbsp; "
            f"<b>对应成功率:</b> {result.final_success_probability:.2%}<br>"
            f"<b>单抽成本:</b> {result.cost_per_draw:.0f} &nbsp;|&nbsp; "
            f"<b>搜索精度:</b> ±{precision_val:.0f} 资源 &nbsp;|&nbsp; "
            f"<b>总迭代次数:</b> {result.total_iterations}<br>"
            f"<b>目标规格:</b> {result.target_specs}"
        )

        self.steps_table.setRowCount(len(result.steps))
        for i, step in enumerate(result.steps):
            self.steps_table.setItem(i, 0, QTableWidgetItem(str(step.iteration)))
            self.steps_table.setItem(i, 1, QTableWidgetItem(step.phase))
            self.steps_table.setItem(i, 2, QTableWidgetItem(f"{step.resource_value:.0f}"))
            self.steps_table.setItem(i, 3, QTableWidgetItem(f"{step.success_probability:.2%}"))
            self.steps_table.setItem(i, 4, QTableWidgetItem(f"{step.lo_bound:.0f}"))
            self.steps_table.setItem(i, 5, QTableWidgetItem(f"{step.hi_bound:.0f}"))

            if step.success_probability >= self.success_threshold_spin.value():
                for col in range(6):
                    item = self.steps_table.item(i, col)
                    if item:
                        item.setBackground(QColor(220, 255, 220))
            else:
                for col in range(6):
                    item = self.steps_table.item(i, col)
                    if item:
                        item.setBackground(QColor(255, 220, 220))

        self._draw_resource_chart(result)

        self.status_update.emit("资源搜索完成")

    def _draw_resource_chart(self, result):
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        import tempfile
        import os

        from gacha_simulator.visualization.font_config import configure_chinese_font
        configure_chinese_font()

        if not result or not result.steps:
            self.chart_label.setText("无数据")
            return

        steps = result.steps
        cost = result.cost_per_draw if result.cost_per_draw > 0 else 160

        resources = [s.resource_value / cost for s in steps]
        probs = [s.success_probability for s in steps]
        phases = [s.phase for s in steps]

        fig, ax = plt.subplots(figsize=(10, 6))

        search_mask = [p.startswith('搜索') for p in phases]
        binary_mask = [p.startswith('二分') for p in phases]
        final_mask = [p == '最终验证' for p in phases]

        sr = [r for r, m in zip(resources, search_mask) if m]
        sp = [p for p, m in zip(probs, search_mask) if m]
        br = [r for r, m in zip(resources, binary_mask) if m]
        bp = [p for p, m in zip(probs, binary_mask) if m]
        fr = [r for r, m in zip(resources, final_mask) if m]
        fp = [p for p, m in zip(probs, final_mask) if m]

        if sr:
            ax.plot(sr, sp, 's', color='#FF9800', markersize=9, label='搜索上界', zorder=3)
        if br:
            ax.plot(br, bp, 'o', color='#2196F3', markersize=7, label='二分搜索', zorder=3)
        if fr:
            ax.plot(fr, fp, 'D', color='#4CAF50', markersize=6, label='最终验证', zorder=4)

        threshold = self.success_threshold_spin.value()
        ax.axhline(y=threshold, color='#F44336', linestyle='--', linewidth=1.5,
                   label=f'阈值 {threshold:.0%}')

        min_r = result.min_resource / cost
        ax.axvline(x=min_r, color='#4CAF50', linestyle=':', linewidth=1.5,
                   label=f'最少资源 ≈{min_r:.1f}抽')

        if len(steps) > 1:
            last_step = steps[-1]
            ax.fill_betweenx([0, 1.05], last_step.lo_bound / cost, last_step.hi_bound / cost,
                             alpha=0.1, color='#2196F3', label='最终搜索区间')

        ax.set_xlabel('资源量（抽数）', fontsize=19)
        ax.set_ylabel('成功率', fontsize=19)
        ax.set_title('成功率随资源量变化趋势', fontsize=22, pad=40)
        ax.set_ylim(-0.05, 1.25)
        ax.legend(loc='best', fontsize=15)
        ax.grid(True, alpha=0.3)
        ax.tick_params(axis='both', labelsize=15)

        plt.tight_layout()
        tmp = tempfile.mktemp(suffix='.png')
        plt.savefig(tmp, dpi=400, bbox_inches='tight')
        plt.close()

        from PyQt6.QtGui import QPixmap
        pixmap = QPixmap(tmp)
        self.chart_label.setPixmap(pixmap.scaled(
            self.chart_label.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))
        os.unlink(tmp)

    def _on_error(self, e):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_update.emit(f"搜索失败: {e}")
        self.result_label.setText(f"<p style='color: red'>错误: {e}</p>")
