#!/usr/bin/env python3

import os
import tempfile
from collections import Counter
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGridLayout, QPushButton, QLabel,
    QGroupBox, QComboBox, QDoubleSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView, QSplitter,
    QTabWidget, QSizePolicy, QProgressBar, QSpinBox, QAbstractItemView,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap

from ..core.process_trace import PoolEvent, SampleTrace, infer_events, compute_pool_gdr_cumulative, compute_pool_gdr_single_pool
from ..core.process_analysis import (
    compute_aa, compute_bb, compute_ab, compute_ba,
    EVENT_MODE_MAP, SUCCESS_MODE_MAP,
    _get_event_label, get_event_type_order, _hashable,
)
from ..core.gdr import UNIFIED_GDR_REGISTRY, SuccessChecker, compute_gdr_from_compact

_gdr_key_to_display = {key: defn.display_name for key, defn in UNIFIED_GDR_REGISTRY.items()}


class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


class _NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()


class ProcessAnalysisPanel(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._aggregate_data = []
        self._target_ids = set()
        self._ssr_ids = set()
        self._target_specs = {}
        self._gdr_context = None
        self._pool_end_times = {}
        self._initial_resources = {}
        self._cumulative_snapshots = {}
        self._pool_types = {}
        self._traces = []
        self._ab_results = []
        self._selected_ab_row = None
        self._setup_ui()

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)

        config_widget = self._build_config_panel()
        self.result_tabs = QTabWidget()
        self.result_tabs.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.aa_table = QTableWidget()
        self.bb_table = QTableWidget()
        self.bb_detail_label = QLabel()
        self.ab_table = QTableWidget()
        self.ba_table = QTableWidget()

        self.result_tabs.addTab(self._wrap_table(self.aa_table), "事件统计")
        self.result_tabs.addTab(self._build_bb_tab(), "成败统计")
        self.result_tabs.addTab(self._build_ab_tab(), "事件→成败")
        self.result_tabs.addTab(self._wrap_table(self.ba_table), "成败→事件")
        self.result_tabs.addTab(self._build_trace_tab(), "轨迹详情")

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(config_widget)
        splitter.addWidget(self.result_tabs)
        splitter.setSizes([250, 750])
        main_layout.addWidget(splitter)

    def _build_config_panel(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        gdr_group = QGroupBox("GDR 配置")
        gdr_layout = QVBoxLayout(gdr_group)

        gdr_layout.addWidget(QLabel("GDR 指标"))
        self.gdr_combo = _NoWheelComboBox()
        for key, defn in UNIFIED_GDR_REGISTRY.items():
            display = defn.display_name
            self.gdr_combo.addItem(display, key)
        gdr_layout.addWidget(self.gdr_combo)

        gdr_layout.addWidget(QLabel("成功阈值"))
        self.threshold_spin = _NoWheelDoubleSpinBox()
        self.threshold_spin.setRange(-9999999.0, 9999999.0)
        self.threshold_spin.setSingleStep(0.05)
        self.threshold_spin.setValue(1.0)
        self.threshold_spin.setDecimals(2)
        gdr_layout.addWidget(self.threshold_spin)
        self.gdr_combo.currentIndexChanged.connect(self._on_gdr_changed)

        gdr_layout.addWidget(QLabel("池子GDR方式"))
        self.pool_gdr_mode = _NoWheelComboBox()
        self.pool_gdr_mode.addItem("截止到该池（累积）", "cumulative")
        self.pool_gdr_mode.addItem("仅该池（单池）", "single_pool")
        gdr_layout.addWidget(self.pool_gdr_mode)

        layout.addWidget(gdr_group)

        mode_group = QGroupBox("模式配置")
        mode_layout = QVBoxLayout(mode_group)

        mode_layout.addWidget(QLabel("事件组合模式"))
        self.event_mode_combo = _NoWheelComboBox()
        self.event_mode_combo.addItem("事件类型序列", "sequence")
        self.event_mode_combo.addItem("事件类型集合", "set")
        self.event_mode_combo.addItem("事件计数组合", "count_set")
        self.event_mode_combo.addItem("原始轨迹", "raw")
        self.event_mode_combo.addItem("自定义模式", "custom")
        mode_layout.addWidget(self.event_mode_combo)

        self.custom_threshold_widget = QWidget()
        self._custom_threshold_layout = QGridLayout(self.custom_threshold_widget)
        self._custom_threshold_layout.setContentsMargins(0, 4, 0, 0)

        self.constraint_ops = {}
        self.constraint_ns = {}
        self._op_labels = [('任意', 'any'), ('=', '='), ('≥', '>='), ('≤', '<='), ('>', '>'), ('<', '<')]

        self._custom_placeholder = QLabel("请先运行一次过程分析")
        self._custom_placeholder.setStyleSheet("color: #888; padding: 8px;")
        self._custom_threshold_layout.addWidget(self._custom_placeholder, 0, 0)

        self.custom_threshold_widget.setVisible(False)
        mode_layout.addWidget(self.custom_threshold_widget)

        self.event_mode_combo.currentIndexChanged.connect(self._on_event_mode_changed)

        mode_layout.addWidget(QLabel("成败组合模式"))
        self.success_mode_combo = _NoWheelComboBox()
        self.success_mode_combo.addItem("成败计数", "count")
        self.success_mode_combo.addItem("成败序列", "sequence")
        self.success_mode_combo.addItem("成败集合", "set")
        self.success_mode_combo.addItem("自定义模式", "custom")
        mode_layout.addWidget(self.success_mode_combo)

        self.success_custom_widget = QWidget()
        success_custom_layout = QHBoxLayout(self.success_custom_widget)
        success_custom_layout.setContentsMargins(0, 4, 0, 0)
        self.success_op_combo = _NoWheelComboBox()
        success_op_labels = [('=', '='), ('≥', '>='), ('≤', '<='), ('>', '>'), ('<', '<')]
        for display, data in success_op_labels:
            self.success_op_combo.addItem(display, data)
        self.success_op_combo.setMaximumWidth(70)
        success_custom_layout.addWidget(self.success_op_combo)
        self.success_n_spin = QSpinBox()
        self.success_n_spin.setMinimum(0)
        self.success_n_spin.setMaximum(99)
        self.success_n_spin.setValue(1)
        self.success_n_spin.setMaximumWidth(80)
        success_custom_layout.addWidget(self.success_n_spin)
        success_custom_layout.addStretch()
        self.success_custom_widget.setVisible(False)
        mode_layout.addWidget(self.success_custom_widget)

        self.success_mode_combo.currentIndexChanged.connect(self._on_success_mode_changed)

        layout.addWidget(mode_group)

        self.run_btn = QPushButton("分析")
        self.run_btn.clicked.connect(self._run_analysis)
        layout.addWidget(self.run_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setVisible(False)
        layout.addWidget(self.progress_bar)

        self.status_label = QLabel("等待模拟数据...")
        layout.addWidget(self.status_label)

        layout.addStretch()
        return widget

    def _build_bb_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(self.bb_detail_label)
        layout.addWidget(self.bb_table)
        return widget

    def _build_ab_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        self.ab_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.ab_table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.ab_table.clicked.connect(self._on_ab_row_clicked)
        layout.addWidget(self.ab_table)

        self.cond_dist_group = QGroupBox("条件GDR分布")
        self.cond_dist_group.setCheckable(True)
        self.cond_dist_group.setChecked(False)
        self.cond_dist_group.toggled.connect(self._on_cond_dist_toggled)
        cond_layout = QVBoxLayout(self.cond_dist_group)

        self.cond_event_label = QLabel("当前事件组合: (未选择)")
        self.cond_event_label.setStyleSheet("font-weight: bold; color: #336;")
        cond_layout.addWidget(self.cond_event_label)

        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("GDR指标"))
        self.cond_gdr_combo = _NoWheelComboBox()
        for key, defn in UNIFIED_GDR_REGISTRY.items():
            self.cond_gdr_combo.addItem(defn.display_name, key)
        self.cond_gdr_combo.currentIndexChanged.connect(self._on_cond_gdr_changed)
        ctrl_row.addWidget(self.cond_gdr_combo)

        ctrl_row.addWidget(QLabel("条件"))
        self.cond_filter_combo = _NoWheelComboBox()
        self.cond_filter_combo.addItem("全部", "all")
        self.cond_filter_combo.addItem("仅成功", "success")
        self.cond_filter_combo.addItem("仅失败", "failure")
        self.cond_filter_combo.currentIndexChanged.connect(self._on_cond_gdr_changed)
        ctrl_row.addWidget(self.cond_filter_combo)
        cond_layout.addLayout(ctrl_row)

        self.cond_update_label = QLabel("")
        self.cond_update_label.setStyleSheet("color: #888; font-size: 11px;")
        cond_layout.addWidget(self.cond_update_label)

        self.cond_sample_label = QLabel("样本数: -")
        cond_layout.addWidget(self.cond_sample_label)

        self.cond_chart_label = QLabel()
        self.cond_chart_label.setMinimumHeight(300)
        self.cond_chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        cond_layout.addWidget(self.cond_chart_label)

        layout.addWidget(self.cond_dist_group)
        return widget

    def _build_trace_tab(self):
        widget = QWidget()
        layout = QVBoxLayout(widget)

        nav_layout = QHBoxLayout()
        nav_layout.addWidget(QLabel("轨迹序号"))
        self.trace_nav_spin = QSpinBox()
        self.trace_nav_spin.setMinimum(1)
        self.trace_nav_spin.setValue(1)
        self.trace_nav_spin.valueChanged.connect(self._on_trace_nav_changed)
        nav_layout.addWidget(self.trace_nav_spin)
        nav_layout.addWidget(QLabel("/"))
        self.trace_total_label = QLabel("0")
        nav_layout.addWidget(self.trace_total_label)

        self.trace_filter_combo = _NoWheelComboBox()
        self.trace_filter_combo.addItem("全部", "all")
        self.trace_filter_combo.addItem("仅成功", "success")
        self.trace_filter_combo.addItem("仅失败", "failure")
        self.trace_filter_combo.currentIndexChanged.connect(self._on_trace_filter_changed)
        nav_layout.addWidget(self.trace_filter_combo)

        nav_layout.addStretch()
        layout.addLayout(nav_layout)

        self.trace_summary_label = QLabel()
        layout.addWidget(self.trace_summary_label)

        self.trace_detail_table = QTableWidget()
        layout.addWidget(self.trace_detail_table)

        return widget

    def _wrap_table(self, table):
        widget = QWidget()
        layout = QVBoxLayout(widget)
        layout.addWidget(table)
        return widget

    def update_results(self, aggregate_data, target_ids=None, ssr_ids=None,
                       gdr_context=None, target_specs=None, pool_end_times=None,
                       initial_resources=None, cumulative_snapshots=None,
                       pool_types=None):
        self._aggregate_data = aggregate_data or []
        self._target_ids = target_ids or set()
        self._ssr_ids = ssr_ids or set()
        self._gdr_context = gdr_context
        self._target_specs = target_specs or {}
        self._pool_end_times = pool_end_times or {}
        self._initial_resources = initial_resources or {}
        self._cumulative_snapshots = cumulative_snapshots or {}
        self._pool_types = pool_types or {}
        self.status_label.setText(f"已加载 {len(self._aggregate_data)} 条模拟数据")

    def _on_event_mode_changed(self, index):
        mode = self.event_mode_combo.itemData(index)
        self.custom_threshold_widget.setVisible(mode == 'custom')

    def _rebuild_custom_event_controls(self, event_type_labels):
        for key in list(self.constraint_ops.keys()):
            self.constraint_ops[key].deleteLater()
            self.constraint_ns[key].deleteLater()
        self.constraint_ops.clear()
        self.constraint_ns.clear()

        for i in reversed(range(self._custom_threshold_layout.count())):
            item = self._custom_threshold_layout.itemAt(i)
            if item and item.widget():
                item.widget().deleteLater()

        if hasattr(self, '_custom_placeholder'):
            self._custom_placeholder = None

        for i, (key, label_text) in enumerate(event_type_labels):
            label = QLabel(label_text)
            self._custom_threshold_layout.addWidget(label, i, 0)
            op_combo = _NoWheelComboBox()
            for display, data in self._op_labels:
                op_combo.addItem(display, data)
            op_combo.setCurrentIndex(0)
            op_combo.setMaximumWidth(70)
            self.constraint_ops[key] = op_combo
            self._custom_threshold_layout.addWidget(op_combo, i, 1)
            spin = QSpinBox()
            spin.setMinimum(0)
            spin.setMaximum(99)
            spin.setValue(1)
            spin.setMaximumWidth(80)
            self.constraint_ns[key] = spin
            self._custom_threshold_layout.addWidget(spin, i, 2)
            op_combo.currentIndexChanged.connect(
                lambda idx, s=spin, c=op_combo: s.setEnabled(c.currentData() != 'any')
            )

    def _on_success_mode_changed(self, index):
        mode = self.success_mode_combo.itemData(index)
        self.success_custom_widget.setVisible(mode == 'custom')

    def _get_custom_constraints(self):
        constraints = {}
        for key in self.constraint_ops:
            op = self.constraint_ops[key].currentData()
            n = self.constraint_ns[key].value()
            constraints[key] = (op, n)
        return constraints

    def _get_success_n(self):
        return self.success_n_spin.value()

    def _on_gdr_changed(self, index):
        from gacha_simulator.core.gdr import get_default_threshold
        key = self.gdr_combo.currentData()
        default = get_default_threshold(key)
        self.threshold_spin.setValue(default)

    def _run_analysis(self):
        if not self._aggregate_data:
            self.status_label.setText("无模拟数据，请先运行模拟")
            return

        self.run_btn.setEnabled(False)
        self.progress_bar.setVisible(True)
        self.progress_bar.setRange(0, 0)

        gdr_key = self.gdr_combo.currentData() or next(iter(UNIFIED_GDR_REGISTRY), 'target_achievement')
        threshold = self.threshold_spin.value()
        event_mode = self.event_mode_combo.currentData() or 'sequence'
        success_mode = self.success_mode_combo.currentData() or 'count'
        custom_constraints = self._get_custom_constraints() if event_mode == 'custom' else None
        success_n = self._get_success_n() if success_mode == 'custom' else None
        success_op = self.success_op_combo.currentData() if success_mode == 'custom' else None

        try:
            self._traces = self._build_traces(gdr_key, threshold)

            # 保存当前自定义约束状态
            saved_constraints = {}
            for key in self.constraint_ops:
                saved_constraints[key] = (
                    self.constraint_ops[key].currentData(),
                    self.constraint_ns[key].value(),
                )

            # 动态重建自定义事件控件（收集所有出现的事件类型）
            all_event_types = set()
            for t in self._traces:
                for ev in t.events:
                    et = ev.event_type
                    if et == 'pity_hit' and ev.pity_name:
                        et = f'pity_hit:{ev.pity_name}'
                    all_event_types.add(et)
            ordered_types = get_event_type_order(all_event_types)
            event_type_labels = []
            for et in ordered_types:
                label = _get_event_label(et)
                event_type_labels.append((et, label))
            self._rebuild_custom_event_controls(event_type_labels)

            # 恢复已保存的约束（新出现的事件类型保持默认「任意」）
            for key, (op, n) in saved_constraints.items():
                if key in self.constraint_ops:
                    idx = self.constraint_ops[key].findData(op)
                    if idx >= 0:
                        self.constraint_ops[key].setCurrentIndex(idx)
                    self.constraint_ns[key].setValue(n)

            # 重新读取约束（含恢复的旧值 + 新类型默认值）
            if event_mode == 'custom':
                custom_constraints = self._get_custom_constraints()
                if not any(op != 'any' for op, _ in custom_constraints.values()):
                    custom_constraints = None

            aa_results = compute_aa(self._traces, event_mode, custom_constraints)
            self._fill_aa_table(aa_results)

            bb_results = compute_bb(self._traces, success_mode, success_n, success_op)
            self._fill_bb_table(bb_results)

            ab_results = compute_ab(self._traces, event_mode, success_mode, custom_constraints, success_n, success_op)
            self._fill_ab_table(ab_results)

            ba_results = compute_ba(self._traces, event_mode, success_mode, custom_constraints, success_op)
            self._fill_ba_table(ba_results)

            self._update_trace_nav()
            self._show_trace_detail(0)

            self.status_label.setText(
                f"分析完成: {len(self._traces)} 条轨迹, "
                f"成功 {sum(1 for t in self._traces if t.is_success)} 条"
            )
        except Exception as e:
            self.status_label.setText(f"分析出错: {e}")
        finally:
            self.run_btn.setEnabled(True)
            self.progress_bar.setVisible(False)

    def _build_traces(self, gdr_key, threshold):
        traces = []
        target_ids = self._target_ids
        target_specs = self._target_specs
        pool_gdr_mode = self.pool_gdr_mode.currentData() or 'single_pool'
        ssr_ids = self._ssr_ids
        weapon_character_map = (
            getattr(self._gdr_context, 'weapon_character_map', None)
            if self._gdr_context else None
        )
        initial_resources = self._initial_resources

        checker = SuccessChecker(
            target_specs, gdr_key, gdr_threshold=threshold,
            ssr_ids=ssr_ids,
            weapon_character_map=weapon_character_map,
        )

        for sample_idx, agg in enumerate(self._aggregate_data):
            val = checker.compute_gdr(agg)

            pool_events = infer_events(agg, target_ids, pool_types=self._pool_types)
            pool_ids_sorted = sorted(pool_events.keys())

            events_list = [pool_events[pid] for pid in pool_ids_sorted]

            pool_success = {}
            pool_gdr_values = {}
            for pid in pool_ids_sorted:
                pool_gdr_val = self._compute_pool_gdr(
                    pool_gdr_mode, agg, pid, sample_idx,
                    target_specs, gdr_key, ssr_ids,
                    weapon_character_map, initial_resources,
                )
                pool_gdr_values[pid] = pool_gdr_val if pool_gdr_val is not None else 0.0
                pool_success[pid] = (pool_gdr_val is not None and pool_gdr_val >= checker.gdr_threshold)

            traces.append(SampleTrace(
                events=events_list,
                pool_success=pool_success,
                is_success=checker.is_success(agg),
                gdr_value=val,
                pool_gdr_values=pool_gdr_values,
            ))

        return traces

    def _compute_pool_gdr(self, mode, agg, pool_id, sample_idx,
                          target_specs, gdr_key, ssr_ids,
                          weapon_character_map, initial_resources):
        if mode == 'cumulative':
            pool_snaps = self._cumulative_snapshots.get(pool_id, [])
            if sample_idx < len(pool_snaps):
                return compute_pool_gdr_cumulative(
                    pool_snaps[sample_idx], pool_id, target_specs, gdr_key,
                    ssr_ids=ssr_ids,
                    weapon_character_map=weapon_character_map,
                    initial_resources=initial_resources,
                )
            return None
        else:
            return compute_pool_gdr_single_pool(
                agg, pool_id, target_specs, gdr_key,
                ssr_ids=ssr_ids,
                weapon_character_map=weapon_character_map,
            )

    def _format_event_pattern(self, pattern, event_mode):
        if isinstance(pattern, dict):
            if event_mode == 'custom':
                parts = [v for k, v in sorted(pattern.items()) if not v.endswith(':*')]
                return ', '.join(parts) if parts else '(全部任意)'
            return ', '.join(f'{k}:{v}' for k, v in sorted(pattern.items()))
        if isinstance(pattern, (list, tuple)):
            if not pattern:
                return '(空)'
            if event_mode == 'count_set':
                from ..core.process_analysis import _get_event_label
                parts = []
                for et, cnt in pattern:
                    if cnt > 0:
                        label = _get_event_label(et)
                        parts.append(f'{label}:{cnt}')
                return ', '.join(parts) if parts else '(无事件)'
            if event_mode == 'set':
                return ', '.join(str(x) for x in pattern)
            else:
                return ' → '.join(str(x) for x in pattern)
        return str(pattern)

    def _format_success_pattern(self, pattern, success_mode):
        if isinstance(pattern, (list, tuple)):
            if success_mode in ('sequence',):
                return ', '.join('✓' if x else '✗' for x in pattern)
            elif success_mode == 'set' and len(pattern) == 2:
                return f"{pattern[0]}成功, {pattern[1]}失败"
            else:
                return str(pattern)
        elif isinstance(pattern, int):
            return f"成功{pattern}个池"
        elif isinstance(pattern, str):
            if pattern.startswith('>='):
                n = int(pattern[2:])
                return f'≥{n}个成功'
            elif pattern.startswith('<='):
                n = int(pattern[2:])
                return f'≤{n}个成功'
            elif pattern.startswith('='):
                n = int(pattern[1:])
                return f'恰好{n}个成功'
            elif pattern.startswith('≠'):
                n = int(pattern[1:])
                return f'≠{n}个成功'
            elif pattern.startswith('>'):
                n = int(pattern[1:])
                return f'>{n}个成功'
            elif pattern.startswith('<'):
                n = int(pattern[1:])
                return f'<{n}个成功'
        return str(pattern)

    def _fill_aa_table(self, results):
        self.aa_table.clear()
        self.aa_table.setColumnCount(4)
        self.aa_table.setHorizontalHeaderLabels(['事件组合', '出现次数', '概率', '累计概率'])
        self.aa_table.setRowCount(len(results))
        self.aa_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        event_mode = self.event_mode_combo.currentData() or 'sequence'

        for i, row in enumerate(results):
            text = self._format_event_pattern(row['pattern'], event_mode)
            self.aa_table.setItem(i, 0, QTableWidgetItem(text))
            self.aa_table.setItem(i, 1, QTableWidgetItem(str(row['count'])))
            self.aa_table.setItem(i, 2, QTableWidgetItem(f"{row['probability']:.4f}"))
            self.aa_table.setItem(i, 3, QTableWidgetItem(f"{row['cumulative_probability']:.4f}"))

    def _fill_bb_table(self, results):
        self.bb_table.clear()

        if isinstance(results, dict):
            pattern_table = results.get('pattern_table', [])
            pool_rates = results.get('pool_success_rates', {})
            all_fail_prob = results.get('all_fail_prob', 0)
            all_success_prob = results.get('all_success_prob', 0)
            total = results.get('total', 0)

            detail_text = (
                f"总样本: {total}\n"
                f"全部池失败概率: {all_fail_prob:.4f}\n"
                f"全部池成功概率: {all_success_prob:.4f}\n\n"
                f"各池成功率:\n"
            )
            for pid, rate in sorted(pool_rates.items()):
                detail_text += f"  {pid}: {rate:.4f}\n"
            self.bb_detail_label.setText(detail_text)
        else:
            pattern_table = results
            self.bb_detail_label.setText("")

        self.bb_table.setColumnCount(4)
        self.bb_table.setHorizontalHeaderLabels(['成败模式', '出现次数', '概率', '累计概率'])
        self.bb_table.setRowCount(len(pattern_table))
        self.bb_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        success_mode = self.success_mode_combo.currentData() or 'count'

        for i, row in enumerate(pattern_table):
            text = self._format_success_pattern(row['pattern'], success_mode)
            self.bb_table.setItem(i, 0, QTableWidgetItem(text))
            self.bb_table.setItem(i, 1, QTableWidgetItem(str(row['count'])))
            self.bb_table.setItem(i, 2, QTableWidgetItem(f"{row['probability']:.4f}"))
            self.bb_table.setItem(i, 3, QTableWidgetItem(f"{row['cumulative_probability']:.4f}"))

    def _fill_ab_table(self, results):
        self._ab_results = results
        self._selected_ab_row = None
        self.ab_table.clear()
        self.ab_table.setColumnCount(6)
        self.ab_table.setHorizontalHeaderLabels([
            '事件组合', 'P(成功|组合)', 'P(失败|组合)', '出现次数', '成功数', '失败数'
        ])
        self.ab_table.setRowCount(len(results))
        self.ab_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        event_mode = self.event_mode_combo.currentData() or 'sequence'

        for i, row in enumerate(results):
            text = self._format_event_pattern(row['event_pattern'], event_mode)
            self.ab_table.setItem(i, 0, QTableWidgetItem(text))
            self.ab_table.setItem(i, 1, QTableWidgetItem(f"{row['overall_success_prob']:.4f}"))
            self.ab_table.setItem(i, 2, QTableWidgetItem(f"{1 - row['overall_success_prob']:.4f}"))
            self.ab_table.setItem(i, 3, QTableWidgetItem(str(row['count'])))
            self.ab_table.setItem(i, 4, QTableWidgetItem(str(row['success_count'])))
            self.ab_table.setItem(i, 5, QTableWidgetItem(str(row['failure_count'])))

    def _on_ab_row_clicked(self, index):
        row = index.row()
        if row < 0 or row >= len(self._ab_results):
            return
        self._selected_ab_row = row
        self._update_cond_dist()

    def _on_cond_gdr_changed(self):
        if self._selected_ab_row is not None:
            self._update_cond_dist()

    def _on_cond_dist_toggled(self, checked):
        if checked and self._selected_ab_row is not None:
            self._update_cond_dist()

    def _update_cond_dist(self):
        if not self.cond_dist_group.isChecked():
            return
        row = self._selected_ab_row
        if row is None or row >= len(self._ab_results):
            return

        result = self._ab_results[row]
        event_pattern = result['event_pattern']

        event_mode = self.event_mode_combo.currentData() or 'sequence'
        pattern_text = self._format_event_pattern(event_pattern, event_mode)
        self.cond_event_label.setText(f"当前事件组合: {pattern_text}")

        constraints = self._get_custom_constraints() if event_mode == 'custom' else None

        base_func = EVENT_MODE_MAP.get(event_mode, EVENT_MODE_MAP['sequence'])
        if event_mode == 'custom' and constraints:
            event_func = lambda ev: base_func(ev, constraints=constraints)
        else:
            event_func = base_func

        cond = self.cond_filter_combo.currentData() or 'all'
        cond_text = {'all': '全部', 'success': '仅成功', 'failure': '仅失败'}.get(cond, cond)

        gdr_key = self.cond_gdr_combo.currentData() or next(iter(UNIFIED_GDR_REGISTRY), 'target_achievement')
        gdr_def = UNIFIED_GDR_REGISTRY.get(gdr_key)
        gdr_name = gdr_def.display_name if gdr_def else gdr_key

        filtered = []
        for t in self._traces:
            if _hashable(event_func(t.events)) != _hashable(event_pattern):
                continue
            if cond == 'success' and not t.is_success:
                continue
            if cond == 'failure' and t.is_success:
                continue
            filtered.append(t)

        n = len(filtered)
        from datetime import datetime
        self.cond_update_label.setText(f"已更新: {datetime.now().strftime('%H:%M:%S')}  |  GDR: {gdr_name}  |  条件: {cond_text}")

        if n == 0:
            self.cond_sample_label.setText("样本数: 0")
            self.cond_chart_label.clear()
            self.cond_chart_label.setText("无匹配样本")
            return

        values = [t.gdr_value for t in filtered]
        self.cond_sample_label.setText(f"样本数: {n}")
        self._plot_cond_dist(values, gdr_key)

    def _plot_cond_dist(self, values, gdr_key):
        n = len(values)
        if n < 10:
            self.cond_chart_label.setText(f"样本量不足（n={n}），无法显示分布")
            return

        from gacha_simulator.core.distribution import freedman_diaconis_bins
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from gacha_simulator.visualization.font_config import configure_chinese_font
        configure_chinese_font()

        fig, ax = plt.subplots(figsize=(8, 5))

        gdr_def = UNIFIED_GDR_REGISTRY.get(gdr_key)
        display_name = gdr_def.display_name if gdr_def else gdr_key

        try:
            bins = freedman_diaconis_bins(values)
        except Exception:
            bins = 20

        ax.hist(values, bins=bins, density=False, edgecolor='black', alpha=0.7)

        mean_val = sum(values) / n
        sorted_vals = sorted(values)
        median_val = sorted_vals[n // 2]
        ax.axvline(mean_val, color='red', linestyle='--', linewidth=1, label=f'均值={mean_val:.3f}')
        ax.axvline(median_val, color='blue', linestyle=':', linewidth=1, label=f'中位数={median_val:.3f}')

        ax.set_xlabel(display_name)
        ax.set_ylabel('频次')
        ax.set_title('条件GDR分布')
        ax.legend(fontsize=8)
        ax.grid(True, alpha=0.3)

        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        try:
            fig.savefig(tmp.name, dpi=150, bbox_inches='tight')
            plt.close(fig)

            pixmap = QPixmap(tmp.name)
            self.cond_chart_label.setPixmap(pixmap.scaled(
                self.cond_chart_label.width(), self.cond_chart_label.height(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation
            ))
        finally:
            try:
                os.unlink(tmp.name)
            except OSError:
                pass

    def _fill_ba_table(self, results):
        self.ba_table.clear()
        self.ba_table.setColumnCount(5)
        self.ba_table.setHorizontalHeaderLabels([
            '事件组合', 'P(组合|成功)', 'P(组合|失败)', '比值', '出现次数'
        ])
        self.ba_table.setRowCount(len(results))
        self.ba_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        event_mode = self.event_mode_combo.currentData() or 'sequence'

        for i, row in enumerate(results):
            text = self._format_event_pattern(row['event_pattern'], event_mode)
            ratio = row['ratio']
            ratio_text = f"{ratio:.2f}" if ratio != float('inf') else "∞"
            self.ba_table.setItem(i, 0, QTableWidgetItem(text))
            self.ba_table.setItem(i, 1, QTableWidgetItem(f"{row['p_given_success']:.4f}"))
            self.ba_table.setItem(i, 2, QTableWidgetItem(f"{row['p_given_failure']:.4f}"))
            self.ba_table.setItem(i, 3, QTableWidgetItem(ratio_text))
            self.ba_table.setItem(i, 4, QTableWidgetItem(str(row['count'])))

    def _get_filtered_traces(self):
        filter_mode = self.trace_filter_combo.currentData() or 'all'
        if filter_mode == 'success':
            return [(i, t) for i, t in enumerate(self._traces) if t.is_success]
        elif filter_mode == 'failure':
            return [(i, t) for i, t in enumerate(self._traces) if not t.is_success]
        else:
            return list(enumerate(self._traces))

    def _update_trace_nav(self):
        filtered = self._get_filtered_traces()
        count = len(filtered)
        self.trace_nav_spin.setMaximum(max(count, 1))
        self.trace_total_label.setText(str(count))
        if count == 0:
            self.trace_nav_spin.setValue(1)

    def _on_trace_nav_changed(self, value):
        self._show_trace_detail(value - 1)

    def _on_trace_filter_changed(self):
        self._update_trace_nav()
        self._show_trace_detail(0)

    def _show_trace_detail(self, display_idx):
        filtered = self._get_filtered_traces()
        if not filtered or display_idx >= len(filtered):
            self.trace_summary_label.setText("无轨迹数据")
            self.trace_detail_table.clear()
            self.trace_detail_table.setRowCount(0)
            return

        orig_idx, trace = filtered[display_idx]

        gdr_display = _gdr_key_to_display.get(self.gdr_combo.currentData(), '')
        success_mark = "✓ 成功" if trace.is_success else "✗ 失败"
        self.trace_summary_label.setText(
            f"原始序号: {orig_idx}  |  整体GDR({gdr_display}): {trace.gdr_value:.4f}  |  {success_mark}"
        )

        self.trace_detail_table.clear()
        headers = ['池子ID', '事件类型', '保底名', '抽卡数', '计数器最大值', '池GDR值', '池成败']
        self.trace_detail_table.setColumnCount(len(headers))
        self.trace_detail_table.setHorizontalHeaderLabels(headers)
        self.trace_detail_table.setRowCount(len(trace.events))
        self.trace_detail_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.ResizeToContents
        )

        for i, ev in enumerate(trace.events):
            self.trace_detail_table.setItem(i, 0, QTableWidgetItem(ev.pool_id))
            self.trace_detail_table.setItem(i, 1, QTableWidgetItem(ev.event_type))
            self.trace_detail_table.setItem(i, 2, QTableWidgetItem(ev.pity_name or ""))
            self.trace_detail_table.setItem(i, 3, QTableWidgetItem(str(ev.draws)))
            self.trace_detail_table.setItem(i, 4, QTableWidgetItem(str(ev.counter_max)))
            gdr_val = trace.pool_gdr_values.get(ev.pool_id, 0.0)
            self.trace_detail_table.setItem(i, 5, QTableWidgetItem(f"{gdr_val:.4f}"))
            pool_ok = trace.pool_success.get(ev.pool_id, False)
            self.trace_detail_table.setItem(i, 6, QTableWidgetItem("✓" if pool_ok else "✗"))
