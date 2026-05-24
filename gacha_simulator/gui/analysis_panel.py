#!/usr/bin/env python3

import os
from pathlib import Path
from collections import defaultdict

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QScrollArea, QCheckBox, QSplitter, QComboBox,
    QSpinBox, QDoubleSpinBox, QTableWidget, QTableWidgetItem,
    QHeaderView, QFileDialog, QGridLayout, QSizePolicy, QProgressBar,
    QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QFont


class _NoWheelSpinBox(QSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class _NoWheelDoubleSpinBox(QDoubleSpinBox):
    def wheelEvent(self, event):
        event.ignore()

class _NoWheelComboBox(QComboBox):
    def wheelEvent(self, event):
        event.ignore()


ANALYSIS_CATEGORIES = {
    '总体广义出率分析': [
        ('gdr_dist', 'GDR分布'),
        ('gdr_statistics', 'GDR指标统计'),
        ('correlation', 'GDR指标相关性'),
    ],
    '风险分析': [
        ('risk_var_cvar', 'VaR/CVaR分析'),
        ('risk_worst_case', '最差情形分析'),
        ('risk_best_case', '最好情形分析'),
        ('conditional_dist', '条件分布'),
    ],
    '时间演化': [
        ('time_series', 'GDR时间序列演化'),
        ('time_heatmap', '时间-GDR热力图'),
        ('draws_vs_gdr', '抽卡数-目标达成率散点图'),
        ('waterfall_3d', '3D瀑布图'),
        ('waterfall_2d', '2D压缩瀑布图'),
    ],
    '每池分析': [
        ('per_pool_draws', '每池抽卡数统计'),
        ('per_pool_target_rate', '每池目标卡数'),
        ('per_pool_pity_rate', '每池保底数'),
        ('cumulative_by_pool', '截止每池的GDR分布'),
        ('transition_analysis', '转变分析'),
    ],
}


_EXPANDABLE_KEYS = {'gdr_dist', 'risk_worst_case', 'risk_best_case', 'conditional_dist', 'transition_analysis', 'cumulative_by_pool'}

_KEY_TITLE_MAP = {}
for _cat, _items in ANALYSIS_CATEGORIES.items():
    for _key, _label in _items:
        _KEY_TITLE_MAP[_key] = _label
_KEY_TITLE_MAP.update({
    'risk_worst_case_chart': '最差情形分布图',
    'risk_best_case_chart': '最好情形分布图',
    'conditional_dist_chart': '条件分布图',
    'draws_vs_gdr': '抽卡数-目标达成率散点图',
})


class AnalysisItemWidget(QFrame):
    checked_changed = pyqtSignal(str, bool)

    def __init__(self, key, label, parent=None):
        super().__init__(parent)
        self.key = key
        self._expanded = False
        self._setup_ui(label)

    def _setup_ui(self, label):
        self.setFrameShape(QFrame.Shape.StyledPanel)

        self._main_layout = QVBoxLayout(self)
        self._main_layout.setContentsMargins(0, 0, 0, 0)
        self._main_layout.setSpacing(0)

        self._header = QWidget()
        header_layout = QHBoxLayout(self._header)
        header_layout.setContentsMargins(6, 4, 6, 4)
        header_layout.setSpacing(4)

        self._toggle_btn = QPushButton("▶")
        self._toggle_btn.setFixedSize(16, 16)
        self._toggle_btn.setStyleSheet("""
            QPushButton {
                border: none;
                background: transparent;
                font-size: 10px;
                padding: 0px;
            }
        """)
        self._toggle_btn.clicked.connect(self._toggle_expand)
        header_layout.addWidget(self._toggle_btn)

        self._checkbox = QCheckBox(label)
        self._checkbox.toggled.connect(self._on_checked)
        header_layout.addWidget(self._checkbox)
        header_layout.addStretch()

        self._main_layout.addWidget(self._header)

        self._config_widget = QWidget()
        self._config_layout = QVBoxLayout(self._config_widget)
        self._config_layout.setContentsMargins(28, 4, 8, 6)
        self._config_layout.setSpacing(3)
        self._config_widget.setVisible(False)
        self._main_layout.addWidget(self._config_widget)

    def _toggle_expand(self):
        self._expanded = not self._expanded
        self._config_widget.setVisible(self._expanded)
        self._toggle_btn.setText("▼" if self._expanded else "▶")

    def _on_checked(self, checked):
        self.checked_changed.emit(self.key, checked)
        if checked and not self._expanded:
            self._toggle_expand()
        if not checked and self._expanded:
            self._toggle_expand()

    def isChecked(self):
        return self._checkbox.isChecked()

    def setChecked(self, checked):
        self._checkbox.setChecked(checked)

    def config_layout(self):
        return self._config_layout

    def add_config_row(self, label_text, widget):
        row = QHBoxLayout()
        row.setSpacing(4)
        lbl = QLabel(label_text)
        lbl.setStyleSheet("font-size: 11px;")
        row.addWidget(lbl)
        row.addWidget(widget)
        self._config_layout.addLayout(row)
        return row

    def add_config_widget(self, widget):
        self._config_layout.addWidget(widget)
        return widget


class ResultUnit(QFrame):
    def __init__(self, key, title, parent=None):
        super().__init__(parent)
        self.key = key
        self._image_path = None
        self._setup_ui(title)

    def _setup_ui(self, title):
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet("""
            ResultUnit {
                border: 1px solid #d0d0d0;
                border-radius: 6px;
                background: #ffffff;
            }
        """)

        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        title_bar = QWidget()
        title_bar.setObjectName("ruTitleBar")
        title_bar.setStyleSheet("""
            QWidget#ruTitleBar {
                background: #f0f0f0;
                border-top-left-radius: 6px;
                border-top-right-radius: 6px;
                border-bottom: 1px solid #e0e0e0;
            }
        """)
        title_layout = QHBoxLayout(title_bar)
        title_layout.setContentsMargins(10, 6, 10, 6)

        title_label = QLabel(title)
        title_label.setStyleSheet("font-weight: bold; font-size: 13px; background: transparent; border: none;")
        title_layout.addWidget(title_label)
        title_layout.addStretch()

        self.export_btn = QPushButton("导出")
        self.export_btn.setFixedSize(56, 24)
        self.export_btn.setStyleSheet("""
            QPushButton {
                background: #e0e0e0;
                border: 1px solid #ccc;
                border-radius: 3px;
                font-size: 11px;
            }
            QPushButton:hover {
                background: #d0d0d0;
            }
        """)
        title_layout.addWidget(self.export_btn)

        main_layout.addWidget(title_bar)

        self.content_widget = QWidget()
        self.content_widget.setStyleSheet("background: #ffffff; border: none;")
        self.content_layout = QVBoxLayout(self.content_widget)
        self.content_layout.setContentsMargins(10, 10, 10, 10)
        main_layout.addWidget(self.content_widget)

    def set_chart(self, image_path):
        self._clear_content()
        self._image_path = image_path
        label = QLabel()
        pixmap = QPixmap(image_path)
        if not pixmap.isNull():
            scaled = pixmap.scaledToWidth(900, Qt.TransformationMode.SmoothTransformation)
            label.setPixmap(scaled)
        label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.content_layout.addWidget(label)

    def set_table(self, headers, rows):
        self._clear_content()
        self._image_path = None
        table = QTableWidget()
        table.setColumnCount(len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.setRowCount(len(rows))
        for i, row in enumerate(rows):
            for j, val in enumerate(row):
                item = QTableWidgetItem(str(val))
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                table.setItem(i, j, item)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table.verticalHeader().setDefaultSectionSize(26)
        h = table.horizontalHeader().height() + len(rows) * 26 + 4
        table.setMinimumHeight(h)
        self.content_layout.addWidget(table)

    def set_text(self, text):
        self._clear_content()
        self._image_path = None
        label = QLabel(text)
        label.setWordWrap(True)
        label.setStyleSheet("font-size: 12px; line-height: 1.5;")
        self.content_layout.addWidget(label)

    def _clear_content(self):
        while self.content_layout.count():
            item = self.content_layout.takeAt(0)
            w = item.widget()
            if w:
                w.deleteLater()
        self._image_path = None

    def get_image_path(self):
        return self._image_path


def _compute_transition_flags(draw_sequences, sorted_pools, criteria, ctx, ssr_ids, target_specs):
    target_ids_trans = set(ctx.target_specs.keys())
    total_needed = sum(target_specs.values()) or 1
    success_flags_per_sim = []

    for seq in draw_sequences:
        card_ids = seq.get('draw_card_ids', [])
        pool_ids_seq = seq.get('draw_pool_ids', [])
        times = seq.get('draw_times', [])
        flags = []
        for pool_id, end_time in sorted_pools:
            if criteria == 'any_ssr':
                success = False
                for i, cid in enumerate(card_ids):
                    if i < len(times) and times[i] > end_time:
                        break
                    if cid in ssr_ids:
                        success = True
                        break
                flags.append(success)
            elif criteria == 'per_pool_target':
                success = False
                for i, cid in enumerate(card_ids):
                    if i < len(times) and times[i] > end_time:
                        break
                    if i < len(pool_ids_seq) and pool_ids_seq[i] == pool_id and cid in target_ids_trans:
                        success = True
                        break
                flags.append(success)
            else:
                obtained = 0
                for i, cid in enumerate(card_ids):
                    if i < len(times) and times[i] > end_time:
                        break
                    if cid in target_ids_trans:
                        obtained += 1
                flags.append(obtained >= total_needed)
        success_flags_per_sim.append(flags)

    return success_flags_per_sim


class AnalysisWorker(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str, int)

    def __init__(self, results, ctx, pool_end_times, selected, alpha, output_dir, success_criteria='all_targets', cond_gdr='抽出全部目标卡', target_gdr='资源剩余', cond_threshold=0.5, primary_gdr='简单目标达成率', best_primary_gdr='简单目标达成率', gdr_dist_selections=None, cumulative_by_pool_selections=None, worst_case_cond_selections=None, best_case_cond_selections=None, draw_sequences=None, heatmap_data=None, cumulative_snapshots=None, transition_flags=None, use_draw_units=False, cost_per_draw=160, no_draw_resource=None, no_draw_pool_resources=None):
        super().__init__()
        self.results = results
        self.ctx = ctx
        self.pool_end_times = pool_end_times
        self.selected = selected
        self.alpha = alpha
        self.output_dir = Path(output_dir)
        self.success_criteria = success_criteria
        self.cond_gdr = cond_gdr
        self.target_gdr = target_gdr
        self.cond_threshold = cond_threshold
        self.primary_gdr = primary_gdr
        self.best_primary_gdr = best_primary_gdr
        self.gdr_dist_selections = gdr_dist_selections or {}
        self.cumulative_by_pool_selections = cumulative_by_pool_selections or set()
        self.worst_case_cond_selections = worst_case_cond_selections or set()
        self.best_case_cond_selections = best_case_cond_selections or set()
        self.draw_sequences = draw_sequences or []
        self.heatmap_data = heatmap_data or {}
        self.cumulative_snapshots = cumulative_snapshots or {}
        self.transition_flags = transition_flags or []
        self.use_draw_units = use_draw_units
        self.cost_per_draw = cost_per_draw
        self.no_draw_resource = no_draw_resource
        self.no_draw_pool_resources = no_draw_pool_resources or {}

    def _emit(self, msg, pct):
        self.progress.emit(msg, pct)

    def run(self):
        import numpy as np
        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt

        from gacha_simulator.visualization.font_config import configure_chinese_font
        configure_chinese_font()

        plt.rcParams.update({
            'font.size': 14,
            'axes.titlesize': 16,
            'axes.labelsize': 14,
            'xtick.labelsize': 12,
            'ytick.labelsize': 12,
            'legend.fontsize': 12,
        })

        charts = {}
        ctx = self.ctx
        aggregate_data = self.results
        alpha = self.alpha

        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY, compute_gdr_from_compact, compute_gdr_from_cumulative
        from gacha_simulator.core.distribution import EmpiricalDistribution, JointSamples
        from gacha_simulator.core.per_pool_analysis import (
            per_pool_summary_stats,
        )

        ANALYSIS_STEPS = [
            ('_prepare_gdr_dists', '计算GDR分布'),
            ('gdr_dist', 'GDR分布'),
            ('risk_var_cvar', 'VaR/CVaR分析'),
            ('risk_worst_case', '最差情形分析'),
            ('risk_best_case', '最好情形分析'),
            ('conditional_dist', '条件分布'),
            ('time_series', '时间序列'),
            ('draws_vs_gdr', '抽卡数-目标达成率'),
            ('waterfall_3d', '3D瀑布图'),
            ('waterfall_2d', '2D压缩瀑布图'),
            ('per_pool_draws', '每池分析'),
            ('cumulative_by_pool', '截止每池的GDR分布'),
            ('transition_analysis', '转变分析'),
            ('correlation', '相关性分析'),
        ]

        active_steps = []
        for key, label in ANALYSIS_STEPS:
            if key == '_prepare_gdr_dists':
                active_steps.append((key, label))
            elif key in ('per_pool_target_rate', 'per_pool_pity_rate'):
                if 'per_pool_draws' not in [s[0] for s in active_steps] and any(k in self.selected for k in ('per_pool_draws', 'per_pool_target_rate', 'per_pool_pity_rate')):
                    active_steps.append(('per_pool_draws', '每池分析'))
            elif key == 'per_pool_draws':
                if any(k in self.selected for k in ('per_pool_draws', 'per_pool_target_rate', 'per_pool_pity_rate')):
                    active_steps.append((key, label))
            elif key in self.selected:
                active_steps.append((key, label))

        total_steps = len(active_steps)
        completed = 0

        def step_done(label):
            nonlocal completed
            completed += 1
            pct = int(completed / total_steps * 100)
            self._emit(f'{label} ({completed}/{total_steps})', pct)

        target_specs = ctx.target_specs if ctx else {}
        ssr_ids = ctx.ssr_ids if ctx else set()
        _display_to_key = {defn.display_name: key for key, defn in UNIFIED_GDR_REGISTRY.items()}
        _key_to_display = {key: defn.display_name for key, defn in UNIFIED_GDR_REGISTRY.items()}

        gdr_dists = {}
        if any(s[0] == '_prepare_gdr_dists' for s in active_steps):
            self._emit('计算GDR分布 (0/1)...', 0)
            for gdr_def in UNIFIED_GDR_REGISTRY.values():
                name = gdr_def.key
                try:
                    values = []
                    for agg in aggregate_data:
                        v = compute_gdr_from_compact(agg, target_specs, name)
                        values.append(v)
                    gdr_dists[name] = EmpiricalDistribution(values)
                except Exception:
                    pass
            step_done('GDR分布计算完成')

        if self.use_draw_units and self.cost_per_draw > 0:
            _resource_gdr_keys = {'resource_remaining'}
            for _key in _resource_gdr_keys:
                if _key in gdr_dists:
                    _orig = gdr_dists[_key]
                    _converted = [v / self.cost_per_draw for v in _orig.samples]
                    gdr_dists[_key] = EmpiricalDistribution(_converted)

        self.output_dir.mkdir(parents=True, exist_ok=True)

        if 'gdr_dist' in self.selected and self.gdr_dist_selections:
            self._emit('生成GDR分布...', int(completed / total_steps * 100))
            for metric_name, chart_types in self.gdr_dist_selections.items():
                metric_key = _display_to_key.get(metric_name, metric_name)
                dist = gdr_dists.get(metric_key)
                if not dist or dist.n == 0:
                    continue
                n_subplots = len(chart_types)
                if n_subplots == 1:
                    fig, ax = plt.subplots(figsize=(10, 6))
                    axes = [ax]
                else:
                    fig, axes = plt.subplots(1, n_subplots, figsize=(7 * n_subplots, 6))
                ax_idx = 0
                no_draw_ref = None
                if metric_key == 'resource_remaining' and self.no_draw_resource is not None:
                    no_draw_ref = self.no_draw_resource
                    if self.use_draw_units and self.cost_per_draw > 0:
                        no_draw_ref = no_draw_ref / self.cost_per_draw

                _unit_suffix = ''
                if metric_key == 'resource_remaining' and self.use_draw_units:
                    _unit_suffix = ' (抽)'

                if 'hist' in chart_types:
                    ax = axes[ax_idx]
                    from gacha_simulator.core.distribution import freedman_diaconis_bins
                    ax.hist(dist.samples, bins=freedman_diaconis_bins(dist.samples), density=True, edgecolor='black', alpha=0.7)
                    ax.axvline(dist.mean(), color='red', linestyle='--', label=f'均值: {dist.mean():.3f}')
                    ax.axvline(dist.var(alpha), color='orange', linestyle=':', label=f'VaR({alpha}): {dist.var(alpha):.3f}')
                    if no_draw_ref is not None:
                        ax.axvline(no_draw_ref, color='green', linestyle='--', linewidth=1.5, label=f'不抽卡基线: {no_draw_ref:.1f}')
                    ax.set_xlabel(f'{metric_name}{_unit_suffix}')
                    ax.set_ylabel('概率密度')
                    ax.set_title(f'{metric_name}{_unit_suffix} 分布')
                    ax.legend(fontsize=10)
                    ax.grid(alpha=0.3)
                    ax_idx += 1
                if 'cdf' in chart_types:
                    ax = axes[ax_idx]
                    sorted_v = sorted(dist.samples)
                    cdf_y = [(i + 1) / len(sorted_v) for i in range(len(sorted_v))]
                    ax.plot(sorted_v, cdf_y, linewidth=2)
                    ax.axhline(alpha, color='orange', linestyle=':', alpha=0.5)
                    if no_draw_ref is not None:
                        ax.axvline(no_draw_ref, color='green', linestyle='--', linewidth=1.5, label=f'不抽卡基线: {no_draw_ref:.1f}')
                        ax.legend(fontsize=10)
                    ax.set_xlabel(f'{metric_name}{_unit_suffix}')
                    ax.set_ylabel('累积概率')
                    ax.set_title(f'{metric_name}{_unit_suffix} 累积分布')
                    ax.grid(alpha=0.3)
                    ax.set_ylim(0, 1.05)
                    ax_idx += 1
                plt.tight_layout()
                safe_name = metric_name.replace('/', '_').replace(' ', '_')
                p = str(self.output_dir / f'gdr_dist_{safe_name}.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts[f'gdr_dist_{metric_name}'] = p
            step_done('GDR分布')

        if 'risk_var_cvar' in self.selected:
            self._emit('生成VaR/CVaR分析...', int(completed / total_steps * 100))
            rows = []
            for name, dist in gdr_dists.items():
                if dist.n < 2:
                    continue
                _display_name = _key_to_display.get(name, name)
                if name == 'resource_remaining' and self.use_draw_units:
                    _display_name = f'{_display_name} (抽)'
                rows.append({
                    'name': _display_name,
                    'VaR': dist.var(alpha),
                    'CVaR': dist.cvar(alpha),
                    'VaR-均值差': dist.var_mean_diff(alpha),
                    'VaR-中位数差': dist.var_median_diff(alpha),
                    'mean': dist.mean(),
                    'median': dist.median(),
                    'std': dist.std(),
                })
            if rows:
                headers = ['GDR指标', '均值', '中位数', '标准差', f'VaR({alpha})', f'CVaR({alpha})', 'VaR-均值差', 'VaR-中位数差']
                table_rows = []
                for r in rows:
                    table_rows.append([
                        r['name'], f"{r['mean']:.4f}", f"{r['median']:.4f}",
                        f"{r['std']:.4f}", f"{r['VaR']:.4f}", f"{r['CVaR']:.4f}",
                        f"{r['VaR-均值差']:.4f}", f"{r['VaR-中位数差']:.4f}",
                    ])
                charts['risk_var_cvar'] = ('table', headers, table_rows)
            step_done('VaR/CVaR分析')

        if 'risk_worst_case' in self.selected:
            self._emit('生成最差情形分析...', int(completed / total_steps * 100))
            primary_name = self.primary_gdr
            primary_key = _display_to_key.get(primary_name, primary_name)
            primary_dist = gdr_dists.get(primary_key)
            if primary_dist and primary_dist.n > 0:
                from gacha_simulator.core.distribution import JointSamples
                var_val = primary_dist.quantile(alpha)
                is_in_tail = [v <= var_val for v in primary_dist.samples]
                tail_samples = [primary_dist.samples[i] for i in range(primary_dist.n) if is_in_tail[i]]
                tail_dist = EmpiricalDistribution(tail_samples) if tail_samples else EmpiricalDistribution([])

                table_rows = []
                for name, dist in gdr_dists.items():
                    if dist.n < 2:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    cond_dist = joint.conditional_second(lambda f: f <= var_val)
                    if cond_dist.n > 0:
                        g_mean = dist.mean()
                        g_var = dist.var(alpha)
                        _wc_display = _key_to_display.get(name, name)
                        if name == 'resource_remaining' and self.use_draw_units:
                            _wc_display = f'{_wc_display} (抽)'
                        table_rows.append([
                            _wc_display,
                            f"{cond_dist.n}",
                            f"{g_mean:.4f}",
                            f"{cond_dist.mean():.4f}",
                            f"{cond_dist.mean() - g_mean:.4f}",
                            f"{cond_dist.median():.4f}",
                            f"{cond_dist.std():.4f}",
                            f"{cond_dist.var(alpha):.4f}",
                            f"{g_var - g_mean:.4f}",
                            f"{g_var - dist.median():.4f}",
                            f"{cond_dist.min_val():.4f}",
                            f"{cond_dist.max_val():.4f}",
                        ])
                if table_rows:
                    headers = ['GDR指标', '样本数', '全局均值', '条件均值', '均值差', '中位数', '标准差', f'VaR({alpha})', 'VaR-均值差', 'VaR-中位数差', '最小值', '最大值']
                    charts['risk_worst_case'] = ('table', headers, table_rows)

                fig, ax = plt.subplots(figsize=(12, 7))
                hp1 = AnalysisPanel._hist_params(primary_dist.samples, 'black', 0.4, f'{primary_name}(全部)')
                ax.hist(primary_dist.samples, **hp1)
                if tail_dist.n > 0:
                    uc_tail = AnalysisPanel._unique_count(tail_dist.samples)
                    if uc_tail <= 1 and AnalysisPanel._unique_count(primary_dist.samples) > 1:
                        import numpy as np
                        tail_val = float(tail_dist.samples[0])
                        ax.axvline(tail_val, color='red', linewidth=3,
                                   label=f'≤VaR({alpha}), n={tail_dist.n} (值={tail_val:.2f})')
                    else:
                        hp2 = AnalysisPanel._hist_params(tail_dist.samples, 'red', 0.6, f'≤VaR({alpha}), n={tail_dist.n}')
                        ax.hist(tail_dist.samples, **hp2)
                ax.axvline(var_val, color='orange', linestyle='--', label=f'VaR({alpha})={var_val:.4f}')
                ax.set_xlabel(primary_name)
                ax.set_ylabel('频次' if AnalysisPanel._is_discrete(primary_dist.samples) else '密度')
                ax.set_title(f'最差情形分析: {primary_name} (α={alpha})')
                ax.legend(fontsize=11)
                ax.grid(alpha=0.3)
                plt.tight_layout()
                p = str(self.output_dir / 'risk_worst_case.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['risk_worst_case_chart'] = p

                for name, dist in gdr_dists.items():
                    if name == primary_key or dist.n < 2:
                        continue
                    display = _key_to_display.get(name, name)
                    if display not in self.worst_case_cond_selections:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    cond = joint.conditional_second(lambda f: f <= var_val)
                    if cond.n < 2:
                        continue
                    uc_all = AnalysisPanel._unique_count(dist.samples)
                    uc_cond = AnalysisPanel._unique_count(cond.samples)
                    fig2, ax2 = plt.subplots(figsize=(10, 6))
                    hpa = AnalysisPanel._hist_params(dist.samples, 'black', 0.3, f'{display}(全部)')
                    ax2.hist(dist.samples, **hpa)
                    if uc_cond <= 1 and uc_all > 1:
                        import numpy as np
                        cval = float(cond.samples[0])
                        ax2.axvline(cval, color='red', linewidth=3,
                                    label=f'{display}(最差条件, n={cond.n}, 值={cval:.2f})')
                    else:
                        hpb = AnalysisPanel._hist_params(cond.samples, 'red', 0.6, f'{display}(最差条件, n={cond.n})')
                        ax2.hist(cond.samples, **hpb)
                    _wc_xlabel = display
                    if name == 'resource_remaining' and self.use_draw_units:
                        _wc_xlabel = f'{display} (抽)'
                    ax2.set_xlabel(_wc_xlabel)
                    ax2.set_ylabel('频次' if AnalysisPanel._is_discrete(dist.samples) else '密度')
                    ax2.set_title(f'最差情形: {display} | {primary_name}≤VaR({alpha})')
                    ax2.legend(fontsize=11)
                    ax2.grid(alpha=0.3)
                    plt.tight_layout()
                    safe_name = name.replace('/', '_').replace(' ', '_')
                    p2 = str(self.output_dir / f'risk_worst_case_{safe_name}.png')
                    plt.savefig(p2, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts[f'risk_worst_case_{name}'] = p2
            step_done('最差情形分析')

        if 'risk_best_case' in self.selected:
            self._emit('生成最好情形分析...', int(completed / total_steps * 100))
            primary_name = self.best_primary_gdr
            primary_key = _display_to_key.get(primary_name, primary_name)
            primary_dist = gdr_dists.get(primary_key)
            if primary_dist and primary_dist.n > 0:
                from gacha_simulator.core.distribution import JointSamples
                upper_val = primary_dist.quantile(1 - alpha)
                is_in_top = [v >= upper_val for v in primary_dist.samples]
                top_samples = [primary_dist.samples[i] for i in range(primary_dist.n) if is_in_top[i]]
                top_dist = EmpiricalDistribution(top_samples) if top_samples else EmpiricalDistribution([])

                table_rows = []
                for name, dist in gdr_dists.items():
                    if dist.n < 2:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    cond_dist = joint.conditional_second(lambda f: f >= upper_val)
                    if cond_dist.n > 0:
                        g_mean = dist.mean()
                        display = _key_to_display.get(name, name)
                        if name == 'resource_remaining' and self.use_draw_units:
                            display = f'{display} (抽)'
                        g_var = dist.var(alpha)
                        table_rows.append([
                            display,
                            f"{cond_dist.n}",
                            f"{g_mean:.4f}",
                            f"{cond_dist.mean():.4f}",
                            f"{cond_dist.mean() - g_mean:.4f}",
                            f"{cond_dist.median():.4f}",
                            f"{cond_dist.std():.4f}",
                            f"{cond_dist.var(alpha):.4f}",
                            f"{g_var - g_mean:.4f}",
                            f"{g_var - dist.median():.4f}",
                            f"{cond_dist.min_val():.4f}",
                            f"{cond_dist.max_val():.4f}",
                        ])
                if table_rows:
                    headers = ['GDR指标', '样本数', '全局均值', '条件均值', '均值差', '中位数', '标准差', f'VaR({alpha})', 'VaR-均值差', 'VaR-中位数差', '最小值', '最大值']
                    charts['risk_best_case'] = ('table', headers, table_rows)

                fig, ax = plt.subplots(figsize=(12, 7))
                hp1 = AnalysisPanel._hist_params(primary_dist.samples, 'black', 0.4, f'{primary_name}(全部)')
                ax.hist(primary_dist.samples, **hp1)
                if top_dist.n > 0:
                    uc_top = AnalysisPanel._unique_count(top_dist.samples)
                    if uc_top <= 1 and AnalysisPanel._unique_count(primary_dist.samples) > 1:
                        import numpy as np
                        top_val = float(top_dist.samples[0])
                        ax.axvline(top_val, color='green', linewidth=3,
                                   label=f'≥上{1-alpha:.2f}分位, n={top_dist.n} (值={top_val:.2f})')
                    else:
                        hp2 = AnalysisPanel._hist_params(top_dist.samples, 'green', 0.6, f'≥上{1-alpha:.2f}分位, n={top_dist.n}')
                        ax.hist(top_dist.samples, **hp2)
                ax.axvline(upper_val, color='green', linestyle='--', label=f'上{1-alpha:.2f}分位={upper_val:.4f}')
                ax.set_xlabel(primary_name)
                ax.set_ylabel('频次' if AnalysisPanel._is_discrete(primary_dist.samples) else '密度')
                ax.set_title(f'最好情形分析: {primary_name} (α={alpha})')
                ax.legend(fontsize=11)
                ax.grid(alpha=0.3)
                plt.tight_layout()
                p = str(self.output_dir / 'risk_best_case.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['risk_best_case_chart'] = p

                for name, dist in gdr_dists.items():
                    if name == primary_key or dist.n < 2:
                        continue
                    display = _key_to_display.get(name, name)
                    if display not in self.best_case_cond_selections:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    cond = joint.conditional_second(lambda f: f >= upper_val)
                    if cond.n < 2:
                        continue
                    uc_all = AnalysisPanel._unique_count(dist.samples)
                    uc_cond = AnalysisPanel._unique_count(cond.samples)
                    fig2, ax2 = plt.subplots(figsize=(10, 6))
                    hpa = AnalysisPanel._hist_params(dist.samples, 'black', 0.3, f'{display}(全部)')
                    ax2.hist(dist.samples, **hpa)
                    if uc_cond <= 1 and uc_all > 1:
                        import numpy as np
                        cval = float(cond.samples[0])
                        ax2.axvline(cval, color='green', linewidth=3,
                                    label=f'{display}(最好条件, n={cond.n}, 值={cval:.2f})')
                    else:
                        hpb = AnalysisPanel._hist_params(cond.samples, 'green', 0.6, f'{display}(最好条件, n={cond.n})')
                        ax2.hist(cond.samples, **hpb)
                    _bc_xlabel = display
                    if name == 'resource_remaining' and self.use_draw_units:
                        _bc_xlabel = f'{display} (抽)'
                    ax2.set_xlabel(_bc_xlabel)
                    ax2.set_ylabel('频次' if AnalysisPanel._is_discrete(dist.samples) else '密度')
                    ax2.set_title(f'最好情形: {display} | {primary_name}≥上{1-alpha:.2f}分位')
                    ax2.legend(fontsize=11)
                    ax2.grid(alpha=0.3)
                    plt.tight_layout()
                    safe_name = name.replace('/', '_').replace(' ', '_')
                    p2 = str(self.output_dir / f'risk_best_case_{safe_name}.png')
                    plt.savefig(p2, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts[f'risk_best_case_{name}'] = p2
            step_done('最好情形分析')

        if 'conditional_dist' in self.selected:
            self._emit('生成条件分布...', int(completed / total_steps * 100))
            cond_name = self.cond_gdr
            target_name = self.target_gdr
            _gdr_key_by_name_cond = _display_to_key
            cond_key = _gdr_key_by_name_cond.get(cond_name)
            target_key = _gdr_key_by_name_cond.get(target_name)
            if cond_key and target_key:
                cond_values = [compute_gdr_from_compact(agg, target_specs, cond_key, ssr_ids=ssr_ids) for agg in aggregate_data]
                target_values = [compute_gdr_from_compact(agg, target_specs, target_key, ssr_ids=ssr_ids) for agg in aggregate_data]
                _target_unit_suffix = ''
                if target_key == 'resource_remaining' and self.use_draw_units and self.cost_per_draw > 0:
                    target_values = [v / self.cost_per_draw for v in target_values]
                    _target_unit_suffix = ' (抽)'
                joint = JointSamples(list(zip(cond_values, target_values)))
                cond_dist = joint.first_distribution()
                if cond_dist.n > 0:
                    success_threshold = self.cond_threshold
                    success_target = joint.conditional_second(lambda f, t=success_threshold: f >= t)
                    fail_target = joint.conditional_second(lambda f, t=success_threshold: f < t)
                    all_target = joint.second_distribution()

                    table_rows = []
                    for label, cd in [('全部', all_target), (f'{cond_name}≥{success_threshold:.4f}', success_target), (f'{cond_name}<{success_threshold:.4f}', fail_target)]:
                        if cd.n > 0:
                            table_rows.append([
                                label,
                                f"{cd.n}",
                                f"{cd.mean():.4f}",
                                f"{cd.median():.4f}",
                                f"{cd.std():.4f}",
                                f"{cd.var(alpha):.4f}",
                                f"{cd.quantile(0.25):.4f}",
                                f"{cd.quantile(0.75):.4f}",
                            ])
                    if table_rows:
                        headers = ['条件', '样本数', '均值', '中位数', '标准差', f'VaR({alpha})', 'Q25', 'Q75']
                        charts['conditional_dist'] = ('table', headers, table_rows)

                    fig, ax = plt.subplots(figsize=(12, 7))
                    from gacha_simulator.core.distribution import freedman_diaconis_bins
                    if all_target.n > 0:
                        ax.hist(all_target.samples, bins=freedman_diaconis_bins(all_target.samples), density=True, edgecolor='black', alpha=0.3, label='全部')
                    if success_target.n > 0:
                        ax.hist(success_target.samples, bins=freedman_diaconis_bins(success_target.samples), density=True, edgecolor='green', alpha=0.5, label=f'条件≥{success_threshold:.4f}(n={success_target.n})')
                    if fail_target.n > 0:
                        ax.hist(fail_target.samples, bins=freedman_diaconis_bins(fail_target.samples), density=True, edgecolor='red', alpha=0.5, label=f'条件<{success_threshold:.4f}(n={fail_target.n})')
                    if target_key == 'resource_remaining' and self.no_draw_resource is not None:
                        _ref = self.no_draw_resource
                        if self.use_draw_units and self.cost_per_draw > 0:
                            _ref = _ref / self.cost_per_draw
                        ax.axvline(_ref, color='green', linestyle='--', linewidth=1.5, label=f'不抽卡基线: {_ref:.1f}')
                    _cond_unit_suffix = ''
                    if target_key == 'resource_remaining' and self.use_draw_units:
                        _cond_unit_suffix = ' (抽)'
                    ax.set_xlabel(f'{target_name}{_cond_unit_suffix}')
                    ax.set_ylabel('密度')
                    ax.set_title(f'条件分布: {target_name}{_target_unit_suffix} | {cond_name} (阈值={success_threshold:.4f})')
                    ax.legend(fontsize=11)
                    ax.grid(alpha=0.3)
                    plt.tight_layout()
                    p = str(self.output_dir / 'conditional_dist.png')
                    plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts['conditional_dist_chart'] = p
            step_done('条件分布')

        if 'time_series' in self.selected:
            self._emit('生成时间序列...', int(completed / total_steps * 100))
            if self.draw_sequences:
                target_ids = set(ctx.target_specs.keys())
                target_count = sum(ctx.target_specs.values())
                fig, ax = plt.subplots(figsize=(12, 7))
                n_sample = min(20, len(self.draw_sequences))
                indices = np.random.choice(len(self.draw_sequences), n_sample, replace=False) if len(self.draw_sequences) > n_sample else range(len(self.draw_sequences))
                for idx in indices:
                    seq = self.draw_sequences[idx]
                    card_ids = seq.get('draw_card_ids', [])
                    gdr_series = []
                    obtained = 0
                    for cid in card_ids:
                        if cid in target_ids:
                            obtained += 1
                        gdr_series.append(obtained / target_count if target_count > 0 else 0)
                    ax.plot(range(len(gdr_series)), gdr_series, alpha=0.4, linewidth=0.8)
                ax.set_xlabel('抽卡序号')
                ax.set_ylabel('目标达成率')
                ax.set_title('GDR演化（样本路径）')
                ax.grid(alpha=0.3)
                plt.tight_layout()
                p = str(self.output_dir / 'time_series.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['time_series'] = p
            step_done('时间序列')

        if 'time_heatmap' in self.selected:
            self._emit('生成时间热力图...', int(completed / total_steps * 100))
            if self.heatmap_data or self.draw_sequences:
                target_ids = set(ctx.target_specs.keys())
                target_count = sum(ctx.target_specs.values()) or 1

                n_sims = len(aggregate_data)
                max_draw_steps = 40

                if isinstance(self.heatmap_data, dict) and 'data' in self.heatmap_data:
                    heatmap_raw = self.heatmap_data['data']
                    heatmap_bins = self.heatmap_data.get('bins', {})
                else:
                    heatmap_raw = self.heatmap_data
                    heatmap_bins = {}

                gdr_configs = [
                    ('目标达成率', 'achievement', 0, 1.05, 25),
                    ('资源剩余', 'resource', None, None, 25),
                    ('SSR出数', 'ssr_count', None, None, 25),
                ]

                fig, axes = plt.subplots(len(gdr_configs), 1, figsize=(12, 4 * len(gdr_configs)),
                                         squeeze=False)
                has_content = False

                for row_idx, (gdr_name, gdr_key, vmin_default, vmax_default, n_gdr_bins) in enumerate(gdr_configs):
                    ax = axes[row_idx, 0]
                    time_gdr_data = {}
                    is_prebinned = gdr_key in heatmap_bins

                    if gdr_key in ('achievement', 'resource') and heatmap_raw:
                        for step_idx, step_data in heatmap_raw.items():
                            if gdr_key in step_data:
                                time_gdr_data[step_idx] = step_data[gdr_key]
                    elif gdr_key == 'ssr_count' and self.draw_sequences:
                        for seq in self.draw_sequences:
                            card_ids = seq.get('draw_card_ids', [])
                            ssr_so_far = 0
                            for i, cid in enumerate(card_ids):
                                if cid in ssr_ids:
                                    ssr_so_far += 1
                                if i not in time_gdr_data:
                                    time_gdr_data[i] = []
                                time_gdr_data[i].append(ssr_so_far)

                    if not time_gdr_data:
                        continue

                    has_content = True
                    sorted_draws = sorted(time_gdr_data.keys())
                    if len(sorted_draws) > max_draw_steps:
                        step = len(sorted_draws) / max_draw_steps
                        sample_indices = sorted(set(int(i * step) for i in range(max_draw_steps)))
                        sample_indices.append(len(sorted_draws) - 1)
                        sampled_draws = [sorted_draws[i] for i in sample_indices]
                    else:
                        sampled_draws = sorted_draws

                    if is_prebinned:
                        gdr_bin_edges = heatmap_bins[gdr_key]
                        n_bins = len(gdr_bin_edges) - 1
                        density_matrix = np.zeros((n_bins, len(sampled_draws)))
                        for ci, d in enumerate(sampled_draws):
                            counts = np.array(time_gdr_data[d], dtype=np.float64)
                            total = max(counts.sum(), 1)
                            density_matrix[:, ci] = counts / total
                        y_lo = gdr_bin_edges[0]
                        y_hi = gdr_bin_edges[-1]
                    else:
                        y_all = []
                        for d in sampled_draws:
                            y_all.extend(time_gdr_data[d])
                        y_valid = [v for v in y_all if np.isfinite(v)]
                        if len(y_valid) == 0:
                            continue

                        y_lo = float(np.min(y_valid)) if vmin_default is None else vmin_default
                        y_hi = float(np.max(y_valid)) if vmax_default is None else vmax_default
                        if abs(y_hi - y_lo) < 1e-9:
                            y_hi = y_lo + 1.0

                        gdr_bin_edges = np.linspace(y_lo, y_hi, n_gdr_bins + 1)
                        density_matrix = np.zeros((n_gdr_bins, len(sampled_draws)))
                        for ci, d in enumerate(sampled_draws):
                            col_vals = np.array(time_gdr_data[d])
                            col_valid = col_vals[np.isfinite(col_vals)]
                            if len(col_valid) == 0:
                                continue
                            counts, _ = np.histogram(col_valid, bins=gdr_bin_edges)
                            density_matrix[:, ci] = counts / max(len(col_valid), 1)

                    n_yticks = min(7, len(gdr_bin_edges) - 1)
                    y_tick_pos = np.linspace(0, len(gdr_bin_edges) - 2, n_yticks).astype(int)
                    y_tick_vals = np.linspace(y_lo, y_hi, n_yticks)
                    if gdr_key == 'achievement':
                        y_tick_labels = [f'{v:.0%}' for v in y_tick_vals]
                    elif gdr_key == 'ssr_count':
                        y_tick_labels = [f'{v:.0f}' for v in y_tick_vals]
                    elif gdr_key == 'resource':
                        y_tick_labels = [f'{v:.0f}' for v in y_tick_vals]
                    else:
                        y_tick_labels = [f'{v:.2f}' for v in y_tick_vals]

                    im = ax.imshow(density_matrix, aspect='auto', origin='lower',
                                   cmap='YlOrRd', interpolation='nearest',
                                   vmin=0, vmax=np.max(density_matrix) if np.max(density_matrix) > 0 else 1)
                    x_tick_step = max(1, len(sampled_draws) // 10)
                    ax.set_xticks(range(0, len(sampled_draws), x_tick_step))
                    ax.set_xticklabels([f'{sampled_draws[i]}' for i in range(0, len(sampled_draws), x_tick_step)],
                                       rotation=45, ha='right', fontsize=8)
                    ax.set_yticks(y_tick_pos)
                    ax.set_yticklabels(y_tick_labels, fontsize=8)
                    ax.set_xlabel('抽卡次数')
                    ax.set_ylabel(gdr_name)
                    ax.set_title(f'{gdr_name} 分布随抽卡次数演化')
                    cbar = fig.colorbar(im, ax=ax, shrink=0.8, pad=0.02)
                    cbar.set_label('概率密度', fontsize=8)

                if has_content:
                    plt.suptitle(f'GDR 时间演化热力图 ({n_sims} 次模拟)', fontsize=14, y=1.01)
                    plt.tight_layout()
                    p = str(self.output_dir / 'time_heatmap.png')
                    plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts['time_heatmap'] = p
                else:
                    plt.close()
            step_done('时间热力图')

        if 'waterfall_3d' in self.selected and self.draw_sequences:
            self._emit('生成3D瀑布图...', int(completed / total_steps * 100))
            target_ids = set(ctx.target_specs.keys())
            target_count = sum(ctx.target_specs.values())
            time_gdr_data = {}
            for seq in self.draw_sequences:
                card_ids = seq.get('draw_card_ids', [])
                obtained = 0
                draw_idx = 0
                for cid in card_ids:
                    if cid in target_ids:
                        obtained += 1
                    if draw_idx not in time_gdr_data:
                        time_gdr_data[draw_idx] = []
                    time_gdr_data[draw_idx].append(obtained)
                    draw_idx += 1
            if time_gdr_data:
                from mpl_toolkits.mplot3d import Axes3D
                sorted_times = sorted(time_gdr_data.keys())
                t_sample = min(40, len(sorted_times))
                t_indices = np.linspace(0, len(sorted_times) - 1, t_sample, dtype=int)
                t_indices = sorted(set(t_indices))
                cmap = plt.cm.viridis
                norm_t = plt.Normalize(sorted_times[t_indices[0]], sorted_times[t_indices[-1]])
                fig = plt.figure(figsize=(16, 11))
                ax3d = fig.add_subplot(111, projection='3d')
                gdr_range = range(0, target_count + 1)
                for idx in t_indices:
                    t_val = sorted_times[idx]
                    data = time_gdr_data[t_val]
                    counts_per = {g: 0 for g in gdr_range}
                    for v in data:
                        if v in counts_per:
                            counts_per[v] += 1
                    total = len(data)
                    probs = [counts_per[g] / total for g in gdr_range]
                    ax3d.plot([t_val] * len(list(gdr_range)), list(gdr_range), probs, color=cmap(norm_t(t_val)), linewidth=1.2, alpha=0.8)
                sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm_t)
                sm.set_array([])
                fig.colorbar(sm, ax=ax3d, shrink=0.5, pad=0.1, label='时间步')
                ax3d.set_xlabel('时间步')
                ax3d.set_ylabel('目标卡数')
                ax3d.set_zlabel('概率')
                ax3d.set_title('3D瀑布图')
                ax3d.view_init(elev=25, azim=-60)
                p = str(self.output_dir / 'waterfall_3d.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['waterfall_3d'] = p
            step_done('3D瀑布图')

        if 'waterfall_2d' in self.selected and self.draw_sequences:
            self._emit('生成2D瀑布图...', int(completed / total_steps * 100))
            target_ids = set(ctx.target_specs.keys())
            target_count = sum(ctx.target_specs.values())
            time_gdr_data = {}
            for seq in self.draw_sequences:
                card_ids = seq.get('draw_card_ids', [])
                obtained = 0
                draw_idx = 0
                for cid in card_ids:
                    if cid in target_ids:
                        obtained += 1
                    if draw_idx not in time_gdr_data:
                        time_gdr_data[draw_idx] = []
                    time_gdr_data[draw_idx].append(obtained)
                    draw_idx += 1
            if time_gdr_data:
                sorted_times = sorted(time_gdr_data.keys())
                t_sample = min(25, len(sorted_times))
                t_indices = np.linspace(0, len(sorted_times) - 1, t_sample, dtype=int)
                t_indices = sorted(set(t_indices))
                cmap = plt.cm.viridis
                norm_t = plt.Normalize(sorted_times[t_indices[0]], sorted_times[t_indices[-1]])
                fig, ax = plt.subplots(figsize=(12, 8))
                gdr_range = range(0, target_count + 1)
                for idx in t_indices:
                    t_val = sorted_times[idx]
                    data = time_gdr_data[t_val]
                    counts_per = {g: 0 for g in gdr_range}
                    for v in data:
                        if v in counts_per:
                            counts_per[v] += 1
                    total = len(data)
                    probs = [counts_per[g] / total for g in gdr_range]
                    ax.plot(list(gdr_range), probs, color=cmap(norm_t(t_val)), linewidth=1.2, alpha=0.7)
                sm = plt.cm.ScalarMappable(cmap=cmap, norm=norm_t)
                sm.set_array([])
                plt.colorbar(sm, ax=ax, label='时间步')
                ax.set_xlabel('目标卡数量')
                ax.set_ylabel('概率')
                ax.set_title('2D瀑布图')
                ax.grid(alpha=0.3)
                p = str(self.output_dir / 'waterfall_2d.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['waterfall_2d'] = p
            step_done('2D瀑布图')

        if any(k in self.selected for k in ('per_pool_draws', 'per_pool_target_rate', 'per_pool_pity_rate')):
            self._emit('生成每池分析...', int(completed / total_steps * 100))
            from gacha_simulator.core.per_pool_analysis import PoolSnapshot
            target_ids_set = set(ctx.target_specs.keys())
            batch_snaps = {}
            for agg in aggregate_data:
                pool_draw_counts = agg.get('pool_draw_counts', {})
                pool_card_counts = agg.get('pool_card_counts', {})
                pool_pity_counts = agg.get('pool_pity_counts', {})
                pool_res_consumed = agg.get('pool_resources_consumed', {})
                all_pool_ids = set(pool_draw_counts.keys()) | set(pool_card_counts.keys()) | set(pool_pity_counts.keys())
                for pid in all_pool_ids:
                    snap = PoolSnapshot(
                        pool_id=pid,
                        draw_count=pool_draw_counts.get(pid, 0),
                        target_card_draws=sum(cnt for cid, cnt in pool_card_counts.get(pid, {}).items() if cid in target_ids_set),
                        pity_draws=pool_pity_counts.get(pid, 0),
                        resources_consumed=dict(pool_res_consumed.get(pid, {})),
                    )
                    if pid not in batch_snaps:
                        batch_snaps[pid] = []
                    batch_snaps[pid].append(snap)
            stats = per_pool_summary_stats(batch_snaps)
            if stats:
                pool_ids = sorted(stats.keys())
                short_ids = [pid.replace('pool_', 'p').replace('exchange_', 'e')[:12] for pid in pool_ids]

                if 'per_pool_draws' in self.selected:
                    fig, ax = plt.subplots(figsize=(10, max(5, len(pool_ids) * 0.6 + 1)))
                    vals = [stats[pid].get('mean_draws', 0) for pid in pool_ids]
                    ax.barh(short_ids, vals, color='#2196F3', alpha=0.7)
                    ax.set_title('每池平均抽卡数', fontsize=14)
                    ax.grid(alpha=0.3, axis='x')
                    plt.tight_layout()
                    p = str(self.output_dir / 'per_pool_draws.png')
                    plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts['per_pool_draws'] = p

                if 'per_pool_target_rate' in self.selected:
                    fig, ax = plt.subplots(figsize=(10, max(5, len(pool_ids) * 0.6 + 1)))
                    vals = [stats[pid].get('target_count', 0) for pid in pool_ids]
                    ax.barh(short_ids, vals, color='#4CAF50', alpha=0.7)
                    ax.set_title('每池目标卡数', fontsize=14)
                    ax.grid(alpha=0.3, axis='x')
                    plt.tight_layout()
                    p = str(self.output_dir / 'per_pool_target_rate.png')
                    plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts['per_pool_target_rate'] = p

                if 'per_pool_pity_rate' in self.selected:
                    fig, ax = plt.subplots(figsize=(10, max(5, len(pool_ids) * 0.6 + 1)))
                    vals = [stats[pid].get('pity_count', 0) for pid in pool_ids]
                    ax.barh(short_ids, vals, color='#FF9800', alpha=0.7)
                    ax.set_title('每池保底数', fontsize=14)
                    ax.grid(alpha=0.3, axis='x')
                    plt.tight_layout()
                    p = str(self.output_dir / 'per_pool_pity_rate.png')
                    plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts['per_pool_pity_rate'] = p

            step_done('每池分析')

        if 'cumulative_by_pool' in self.selected and self.cumulative_by_pool_selections and self.pool_end_times:
            self._emit('生成截止每池的GDR分布...', int(completed / total_steps * 100))
            cum_data = {}
            for pid, snaps in self.cumulative_snapshots.items():
                if not snaps:
                    continue
                target_achievement_rates = []
                ssr_collection_rates = []
                resource_remainings = []
                cumulative_draws_list = []
                cumulative_pity_list = []
                for snap in snaps:
                    cum_card_counts = snap.get('cumulative_card_counts', {})
                    total_target_qty = sum(target_specs.values()) if target_specs else 0
                    achieved = sum(min(cum_card_counts.get(cid, 0), qty) for cid, qty in target_specs.items())
                    target_achievement_rates.append(achieved / total_target_qty if total_target_qty > 0 else 0.0)
                    collected_ssr = sum(1 for cid in ssr_ids if cum_card_counts.get(cid, 0) > 0)
                    ssr_collection_rates.append(collected_ssr / len(ssr_ids) if ssr_ids else 0.0)
                    res_rem = snap.get('pool_end_resource', 0.0)
                    resource_remainings.append(res_rem)
                    cumulative_draws_list.append(float(snap.get('cumulative_draws', 0)))
                    cumulative_pity_list.append(float(snap.get('cumulative_pity_draws', 0)))
                cum_data[pid] = {
                    'target_achievement_rate': target_achievement_rates,
                    'ssr_collection_rate': ssr_collection_rates,
                    'resource_remaining': resource_remainings,
                    'cumulative_draws': cumulative_draws_list,
                    'cumulative_pity_draws': cumulative_pity_list,
                }
            if not cum_data:
                step_done('截止每池的GDR分布')
            else:
                pool_ids = sorted(cum_data.keys())
                short_ids = [pid.replace('pool_', 'p').replace('exchange_', 'e')[:12] for pid in pool_ids]
                _gdr_key_by_name = _display_to_key
                _cum_data_keys = {
                    '简单目标达成率': 'target_achievement_rate',
                    'SSR收集率': 'ssr_collection_rate',
                    '资源剩余': 'resource_remaining',
                    '累积抽卡数': 'cumulative_draws',
                    '累积保底抽卡': 'cumulative_pity_draws',
                }
                sorted_pools = sorted(self.pool_end_times.items(), key=lambda x: x[1])
                for metric_name in self.cumulative_by_pool_selections:
                    metric_key = _gdr_key_by_name.get(metric_name)
                    if metric_key is None:
                        continue

                    pool_dists = []
                    for pid in pool_ids:
                        if metric_name in _cum_data_keys:
                            data_key = _cum_data_keys[metric_name]
                            raw = cum_data[pid].get(data_key, [])
                        else:
                            raw = []
                            for snap in self.cumulative_snapshots.get(pid, []):
                                try:
                                    v = compute_gdr_from_cumulative(snap, target_specs, metric_key, ssr_ids=ssr_ids)
                                    raw.append(float(v))
                                except Exception:
                                    pass
                        pool_dists.append(raw)

                    if metric_key == 'resource_remaining' and self.use_draw_units and self.cost_per_draw > 0:
                        pool_dists = [[v / self.cost_per_draw for v in d] for d in pool_dists]

                    per_pool_baselines = {}
                    if metric_key == 'resource_remaining' and self.no_draw_pool_resources:
                        for pid in pool_ids:
                            pool_res = self.no_draw_pool_resources.get(pid, {})
                            if 'draw_resource' in pool_res:
                                baseline = float(pool_res['draw_resource'])
                                if self.use_draw_units and self.cost_per_draw > 0:
                                    baseline = baseline / self.cost_per_draw
                                per_pool_baselines[pid] = baseline

                    n_pools = len(pool_ids)
                    fig, axes = plt.subplots(n_pools, 1, figsize=(10, 1.8 * n_pools), sharex=True)
                    if n_pools == 1:
                        axes = [axes]

                    all_vals = [v for d in pool_dists for v in d]
                    if all_vals:
                        x_min, x_max = min(all_vals), max(all_vals)
                        margin = (x_max - x_min) * 0.02 if x_max > x_min else 0.5
                        x_min -= margin
                        x_max += margin
                    else:
                        x_min, x_max = 0, 1

                    from gacha_simulator.core.distribution import freedman_diaconis_bins
                    num_bins = freedman_diaconis_bins(all_vals)
                    bin_edges = np.linspace(x_min, x_max, num_bins + 1)
                    colors = plt.cm.viridis(np.linspace(0.2, 0.9, n_pools))

                    # 计算全局最大频次，避免每池独立归一化导致分布形状不可比
                    global_max_count = 0
                    for dist in pool_dists:
                        if dist:
                            counts, _ = np.histogram(dist, bins=bin_edges)
                            global_max_count = max(global_max_count, max(counts))
                    if global_max_count == 0:
                        global_max_count = 1

                    for idx, (ax, dist, sid) in enumerate(zip(axes, pool_dists, short_ids)):
                        if not dist:
                            ax.text(0.5, 0.5, '无数据', ha='center', va='center',
                                    transform=ax.transAxes, fontsize=9)
                            ax.set_yticks([])
                            ax.spines['top'].set_visible(False)
                            ax.spines['right'].set_visible(False)
                            ax.spines['left'].set_visible(False)
                            ax.set_ylabel(sid, rotation=0, ha='right', va='center',
                                          fontsize=10, fontweight='bold')
                            continue

                        counts, _ = np.histogram(dist, bins=bin_edges)
                        density = counts / global_max_count
                        y_pad = np.append(density, density[-1])

                        ax.step(bin_edges, y_pad, where='post',
                                color=colors[idx], linewidth=1.2)
                        ax.fill_between(bin_edges, y_pad, step='post',
                                        alpha=0.45, color=colors[idx])

                        mean_val = np.mean(dist)
                        ax.axvline(x=mean_val, color='red', linestyle='--',
                                   linewidth=1, alpha=0.7)

                        _pid = pool_ids[idx]
                        _pool_baseline = per_pool_baselines.get(_pid)
                        if _pool_baseline is not None:
                            ax.axvline(x=_pool_baseline, color='green', linestyle='--',
                                       linewidth=1.5, alpha=0.7)

                        ax.set_ylim(0, 1.25)
                        ax.set_yticks([])
                        ax.spines['top'].set_visible(False)
                        ax.spines['right'].set_visible(False)
                        ax.spines['left'].set_visible(False)
                        ax.set_ylabel(sid, rotation=0, ha='right', va='center',
                                      fontsize=10, fontweight='bold')

                        if idx < n_pools - 1:
                            ax.spines['bottom'].set_visible(False)
                            ax.tick_params(labelbottom=False)

                    _xlabel = metric_name
                    if metric_key == 'resource_remaining' and self.use_draw_units:
                        _xlabel = f'{metric_name} (抽)'
                    axes[-1].set_xlabel(_xlabel, fontsize=11)
                    _cum_title = f'{metric_name} (截止每池)'
                    if metric_key == 'resource_remaining' and self.use_draw_units:
                        _cum_title = f'{metric_name} (抽, 截止每池)'
                    fig.suptitle(_cum_title, fontsize=13, fontweight='bold', y=0.995)
                    plt.tight_layout()
                    safe_name = metric_name.replace('/', '_').replace(' ', '_')
                    p = str(self.output_dir / f'cumulative_by_pool_{safe_name}.png')
                    plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                    plt.close()
                    charts[f'cumulative_by_pool_{metric_name}'] = p
                step_done('截止每池的GDR分布')

        if 'draws_vs_gdr' in self.selected:
            self._emit('生成抽卡数-目标达成率散点图...', int(completed / total_steps * 100))
            dist = gdr_dists.get('target_achievement')
            if dist and dist.n > 0:
                draws_per = [agg.get('total_draws', 0) for agg in aggregate_data]
                fig, ax = plt.subplots(figsize=(10, 7))
                ax.scatter(draws_per, dist.samples, alpha=0.3, s=10)
                ax.set_xlabel('总抽卡数')
                ax.set_ylabel('简单目标达成率')
                ax.set_title('抽卡数 vs 简单目标达成率')
                ax.grid(alpha=0.3)
                plt.tight_layout()
                p = str(self.output_dir / 'draws_vs_gdr.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['draws_vs_gdr'] = p
            step_done('抽卡数-目标达成率散点图')

        if 'correlation' in self.selected:
            self._emit('生成相关性分析...', int(completed / total_steps * 100))
            names = [n for n in gdr_dists if gdr_dists[n].n > 1]
            if len(names) >= 2:
                data_matrix = np.array([gdr_dists[n].samples for n in names])
                corr = np.corrcoef(data_matrix)
                fig, ax = plt.subplots(figsize=(max(10, len(names)), max(8, len(names))))
                im = ax.imshow(corr, cmap='RdBu_r', vmin=-1, vmax=1)
                ax.set_xticks(range(len(names)))
                ax.set_yticks(range(len(names)))
                short = [_key_to_display.get(n, n)[:8] for n in names]
                ax.set_xticklabels(short, rotation=45, ha='right', fontsize=11)
                ax.set_yticklabels(short, fontsize=11)
                for i in range(len(names)):
                    for j in range(len(names)):
                        ax.text(j, i, f'{corr[i, j]:.2f}', ha='center', va='center', fontsize=10, color='white' if abs(corr[i, j]) > 0.5 else 'black')
                plt.colorbar(im, ax=ax, label='相关系数')
                ax.set_title('GDR指标相关性')
                plt.tight_layout()
                p = str(self.output_dir / 'correlation.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['correlation'] = p
            step_done('相关性分析')

        if 'transition_analysis' in self.selected and self.pool_end_times:
            self._emit('生成转变分析...', int(completed / total_steps * 100))
            from gacha_simulator.core.per_pool_analysis import TransitionMatrix

            sorted_pools = sorted(self.pool_end_times.items(), key=lambda x: x[1])
            pool_ids_ordered = [pid for pid, _ in sorted_pools]
            n_pools = len(pool_ids_ordered)
            criteria = self.success_criteria

            if criteria == 'all_targets' and self.transition_flags:
                success_flags_per_sim = self.transition_flags
                n_sims = len(success_flags_per_sim)
            else:
                success_flags_per_sim = _compute_transition_flags(
                    self.draw_sequences, sorted_pools, criteria,
                    ctx, ssr_ids, target_specs,
                )
                n_sims = len(success_flags_per_sim)

            trans = []
            if n_sims > 0 and n_pools > 0:
                for i in range(n_pools):
                    to_pid = pool_ids_ordered[i]
                    from_pid = pool_ids_ordered[i - 1] if i > 0 else '(初始)'

                    if i == 0:
                        before = [False] * n_sims
                    else:
                        before = [success_flags_per_sim[s][i - 1] for s in range(n_sims) if i - 1 < len(success_flags_per_sim[s])]
                    after = [success_flags_per_sim[s][i] for s in range(n_sims) if i < len(success_flags_per_sim[s])]

                    n_eff = min(len(before), len(after))
                    before = before[:n_eff]
                    after = after[:n_eff]

                    ss = sum(1 for b, a in zip(before, after) if b and a)
                    sf = sum(1 for b, a in zip(before, after) if b and not a)
                    fs = sum(1 for b, a in zip(before, after) if not b and a)
                    ff = sum(1 for b, a in zip(before, after) if not b and not a)

                    s_before = sum(1 for b in before if b)
                    s_after = sum(1 for a in after if a)

                    trans.append(TransitionMatrix(
                        from_pool_id=from_pid,
                        to_pool_id=to_pid,
                        success_to_success=ss / s_before if s_before > 0 else 0,
                        success_to_fail=sf / s_before if s_before > 0 else 0,
                        fail_to_success=fs / (n_eff - s_before) if (n_eff - s_before) > 0 else 0,
                        fail_to_fail=ff / (n_eff - s_before) if (n_eff - s_before) > 0 else 0,
                        success_rate_before=s_before / n_eff if n_eff > 0 else 0,
                        success_rate_after=s_after / n_eff if n_eff > 0 else 0,
                    ))
            if trans:
                n_trans = len(trans)
                fig = plt.figure(figsize=(20, 6 + 3 * n_trans))

                ax_rates = fig.add_subplot(2, 1, 1)
                transition_labels = [f'{t.from_pool_id[:8]}→{t.to_pool_id[:8]}' for t in trans]
                x = range(n_trans)
                ax_rates.plot(x, [t.success_rate_before for t in trans], 'o-', label='转移前成功率', color='#2196F3')
                ax_rates.plot(x, [t.success_rate_after for t in trans], 's-', label='转移后成功率', color='#4CAF50')
                ax_rates.set_xticks(x)
                ax_rates.set_xticklabels(transition_labels, rotation=45, ha='right', fontsize=11)
                ax_rates.set_ylabel('成功率')
                ax_rates.set_title('相邻池子间成功率变化')
                ax_rates.legend()
                ax_rates.grid(alpha=0.3)

                for i, t in enumerate(trans):
                    ax_mat = fig.add_subplot(2, n_trans, n_trans + i + 1)
                    mat = [[t.success_to_success, t.success_to_fail],
                           [t.fail_to_success, t.fail_to_fail]]
                    im = ax_mat.imshow(mat, cmap='Blues', vmin=0, vmax=1)
                    ax_mat.set_xticks([0, 1])
                    ax_mat.set_yticks([0, 1])
                    ax_mat.set_xticklabels(['成功', '失败'], fontsize=11)
                    ax_mat.set_yticklabels(['成功', '失败'], fontsize=11)
                    ax_mat.set_xlabel('转移后', fontsize=11)
                    ax_mat.set_ylabel('转移前', fontsize=11)
                    ax_mat.set_title(f'{t.from_pool_id[:6]}→{t.to_pool_id[:6]}', fontsize=11)
                    for r in range(2):
                        for c in range(2):
                            ax_mat.text(c, r, f'{mat[r][c]:.3f}', ha='center', va='center',
                                        fontsize=10, color='white' if mat[r][c] > 0.5 else 'black')

                plt.tight_layout()
                p = str(self.output_dir / 'transition_analysis.png')
                plt.savefig(p, dpi=400, bbox_inches='tight', pad_inches=0.15)
                plt.close()
                charts['transition_analysis'] = p
            step_done('转变分析')

        self._emit('完成', 100)
        self.finished.emit(charts)


class AnalysisPanel(QWidget):
    def __init__(self):
        super().__init__()
        self.results = None
        self._gdr_context = None
        self._pool_end_times = {}
        self._draw_sequences = []
        self._heatmap_data = {}
        self._cumulative_snapshots = {}
        self._transition_flags = []
        self._result_units = {}
        self._computed_conditions = {}
        self._summary_data = {}
        self._store = None
        self.output_dir = Path(os.getcwd()) / 'output' / 'analysis'
        self._worker = None
        self._setup_ui()

    def set_store(self, store):
        self._store = store
        self._update_cost_per_draw_default()

    def _extract_cost_per_draw(self):
        if self._store is None or not self._store.pools:
            return 160
        for pe in self._store.pools:
            cost_str = getattr(pe, 'cost', '')
            if not cost_str:
                continue
            try:
                parts = cost_str.split(':')
                if len(parts) == 2:
                    return int(float(parts[1]))
            except (ValueError, IndexError):
                continue
        return 160

    def _update_cost_per_draw_default(self):
        if hasattr(self, 'cost_per_draw_spin'):
            self.cost_per_draw_spin.setValue(self._extract_cost_per_draw())

    def _setup_ui(self):
        main_layout = QHBoxLayout(self)
        splitter = QSplitter(Qt.Orientation.Horizontal)
        main_layout.addWidget(splitter)

        left = self._build_options_panel()
        splitter.addWidget(left)

        right = self._build_results_panel()
        splitter.addWidget(right)

        splitter.setSizes([280, 920])

    def _build_options_panel(self):
        outer = QWidget()
        outer.setMinimumWidth(240)
        outer.setMaximumWidth(340)
        outer_layout = QVBoxLayout(outer)
        outer_layout.setContentsMargins(0, 0, 0, 0)
        outer_layout.setSpacing(4)

        scroll = QScrollArea()
        scroll.verticalScrollBar().setSingleStep(15)
        scroll.setWidgetResizable(True)

        container = QWidget()
        layout = QVBoxLayout(container)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        btn_layout = QHBoxLayout()
        self.select_all_btn = QPushButton("全选")
        self.select_all_btn.clicked.connect(self._select_all)
        btn_layout.addWidget(self.select_all_btn)
        self.deselect_all_btn = QPushButton("全不选")
        self.deselect_all_btn.clicked.connect(self._deselect_all)
        btn_layout.addWidget(self.deselect_all_btn)
        layout.addLayout(btn_layout)

        param_group = QGroupBox("全局参数")
        param_layout = QGridLayout(param_group)
        param_layout.addWidget(QLabel("风险α:"), 0, 0)
        self.alpha_spin = _NoWheelDoubleSpinBox()
        self.alpha_spin.setRange(0.01, 0.5)
        self.alpha_spin.setValue(0.05)
        self.alpha_spin.setSingleStep(0.01)
        self.alpha_spin.setDecimals(2)
        param_layout.addWidget(self.alpha_spin, 0, 1)
        layout.addWidget(param_group)

        unit_group = QGroupBox("图表单位")
        unit_layout = QGridLayout(unit_group)
        self.draw_unit_cb = QCheckBox("以抽数为单位")
        self.draw_unit_cb.setToolTip("将资源类指标（如资源剩余）除以单抽消耗，以抽数显示")
        unit_layout.addWidget(self.draw_unit_cb, 0, 0, 1, 2)
        unit_layout.addWidget(QLabel("单抽消耗:"), 1, 0)
        self.cost_per_draw_spin = QSpinBox()
        self.cost_per_draw_spin.setRange(1, 999999)
        self.cost_per_draw_spin.setValue(self._extract_cost_per_draw())
        self.cost_per_draw_spin.setSingleStep(10)
        unit_layout.addWidget(self.cost_per_draw_spin, 1, 1)
        layout.addWidget(unit_group)

        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY as _UNIFIED_GDR_REGISTRY
        _gdr_names = [defn.display_name for defn in _UNIFIED_GDR_REGISTRY.values()]

        self._items = {}
        self._gdr_dist_checks = {}
        self._cumulative_by_pool_checks = {}
        self._worst_case_cond_checks = {}
        self._best_case_cond_checks = {}

        for category, items in ANALYSIS_CATEGORIES.items():
            cat_label = QLabel(f"── {category} ──")
            cat_label.setStyleSheet("color: #888; font-size: 11px; padding: 4px 0 0 0;")
            layout.addWidget(cat_label)

            for key, label in items:
                if key in _EXPANDABLE_KEYS:
                    item_w = AnalysisItemWidget(key, label)
                    self._items[key] = item_w

                    if key == 'gdr_dist':
                        gdr_config_widget = QWidget()
                        gdr_config_layout = QVBoxLayout(gdr_config_widget)
                        gdr_config_layout.setContentsMargins(0, 0, 0, 0)
                        gdr_config_layout.setSpacing(2)
                        for gdr_name in _gdr_names:
                            row = QHBoxLayout()
                            row.setSpacing(4)
                            name_label = QLabel(gdr_name)
                            name_label.setStyleSheet("font-size: 11px;")
                            name_label.setMinimumWidth(90)
                            row.addWidget(name_label)
                            hist_cb = QCheckBox("分布")
                            hist_cb.setStyleSheet("font-size: 11px;")
                            row.addWidget(hist_cb)
                            cdf_cb = QCheckBox("累积分布")
                            cdf_cb.setStyleSheet("font-size: 11px;")
                            row.addWidget(cdf_cb)
                            row.addStretch()
                            gdr_config_layout.addLayout(row)
                            self._gdr_dist_checks[gdr_name] = {'hist': hist_cb, 'cdf': cdf_cb}
                        item_w.add_config_widget(gdr_config_widget)

                    if key == 'risk_worst_case':
                        self.primary_gdr_combo = _NoWheelComboBox()
                        self.primary_gdr_combo.setMaxVisibleItems(30)
                        self.primary_gdr_combo.addItems(_gdr_names)
                        _i_star = _gdr_names.index('简单目标达成率') if '简单目标达成率' in _gdr_names else 0
                        self.primary_gdr_combo.setCurrentIndex(_i_star)
                        item_w.add_config_row("主指标:", self.primary_gdr_combo)

                        wc_cond_widget = QWidget()
                        wc_cond_layout = QVBoxLayout(wc_cond_widget)
                        wc_cond_layout.setContentsMargins(0, 0, 0, 0)
                        wc_cond_layout.setSpacing(2)
                        for gdr_name in _gdr_names:
                            row = QHBoxLayout()
                            row.setSpacing(4)
                            name_lbl = QLabel(gdr_name)
                            name_lbl.setStyleSheet("font-size: 11px;")
                            name_lbl.setMinimumWidth(90)
                            row.addWidget(name_lbl)
                            cb = QCheckBox("条件分布")
                            cb.setChecked(False)
                            cb.setStyleSheet("font-size: 11px;")
                            row.addWidget(cb)
                            row.addStretch()
                            wc_cond_layout.addLayout(row)
                            self._worst_case_cond_checks[gdr_name] = cb
                        item_w.add_config_row("条件分布指标:", wc_cond_widget)

                    if key == 'risk_best_case':
                        self.best_primary_gdr_combo = _NoWheelComboBox()
                        self.best_primary_gdr_combo.setMaxVisibleItems(30)
                        self.best_primary_gdr_combo.addItems(_gdr_names)
                        _i_star2 = _gdr_names.index('简单目标达成率') if '简单目标达成率' in _gdr_names else 0
                        self.best_primary_gdr_combo.setCurrentIndex(_i_star2)
                        item_w.add_config_row("主指标:", self.best_primary_gdr_combo)

                        bc_cond_widget = QWidget()
                        bc_cond_layout = QVBoxLayout(bc_cond_widget)
                        bc_cond_layout.setContentsMargins(0, 0, 0, 0)
                        bc_cond_layout.setSpacing(2)
                        for gdr_name in _gdr_names:
                            row = QHBoxLayout()
                            row.setSpacing(4)
                            name_lbl = QLabel(gdr_name)
                            name_lbl.setStyleSheet("font-size: 11px;")
                            name_lbl.setMinimumWidth(90)
                            row.addWidget(name_lbl)
                            cb = QCheckBox("条件分布")
                            cb.setChecked(False)
                            cb.setStyleSheet("font-size: 11px;")
                            row.addWidget(cb)
                            row.addStretch()
                            bc_cond_layout.addLayout(row)
                            self._best_case_cond_checks[gdr_name] = cb
                        item_w.add_config_row("条件分布指标:", bc_cond_widget)

                    if key == 'conditional_dist':
                        self.cond_gdr_combo = _NoWheelComboBox()
                        self.cond_gdr_combo.setMaxVisibleItems(30)
                        self.cond_gdr_combo.addItems(_gdr_names)
                        _i_ato = _gdr_names.index('抽出全部目标卡') if '抽出全部目标卡' in _gdr_names else 0
                        self.cond_gdr_combo.setCurrentIndex(_i_ato)
                        item_w.add_config_row("条件指标:", self.cond_gdr_combo)

                        self.target_gdr_combo = _NoWheelComboBox()
                        self.target_gdr_combo.setMaxVisibleItems(30)
                        self.target_gdr_combo.addItems(_gdr_names)
                        _i_rr = _gdr_names.index('资源剩余') if '资源剩余' in _gdr_names else 0
                        self.target_gdr_combo.setCurrentIndex(_i_rr)
                        item_w.add_config_row("目标指标:", self.target_gdr_combo)

                        self.threshold_spin = _NoWheelDoubleSpinBox()
                        self.threshold_spin.setRange(-1e7, 1e7)
                        self.threshold_spin.setValue(0.5)
                        self.threshold_spin.setDecimals(4)
                        self.threshold_spin.setSingleStep(0.01)
                        item_w.add_config_row("条件阈值:", self.threshold_spin)

                        preset_row = QHBoxLayout()
                        preset_row.setSpacing(3)
                        preset_lbl = QLabel("预设:")
                        preset_lbl.setStyleSheet("font-size: 11px;")
                        preset_row.addWidget(preset_lbl)
                        self.preset_var_btn = QPushButton("VaR(α)")
                        self.preset_var_btn.setFixedHeight(22)
                        self.preset_var_btn.setStyleSheet("font-size: 10px;")
                        self.preset_var_btn.clicked.connect(lambda checked, t='var': self._on_preset_threshold(t))
                        preset_row.addWidget(self.preset_var_btn)
                        self.preset_upper_btn = QPushButton("上1-α")
                        self.preset_upper_btn.setFixedHeight(22)
                        self.preset_upper_btn.setStyleSheet("font-size: 10px;")
                        self.preset_upper_btn.clicked.connect(lambda checked, t='upper': self._on_preset_threshold(t))
                        preset_row.addWidget(self.preset_upper_btn)
                        self.preset_median_btn = QPushButton("中位数")
                        self.preset_median_btn.setFixedHeight(22)
                        self.preset_median_btn.setStyleSheet("font-size: 10px;")
                        self.preset_median_btn.clicked.connect(lambda checked, t='median': self._on_preset_threshold(t))
                        preset_row.addWidget(self.preset_median_btn)
                        item_w.config_layout().addLayout(preset_row)

                    if key == 'transition_analysis':
                        self.success_criteria_combo = _NoWheelComboBox()
                        self.success_criteria_combo.addItem("全部目标卡达成", "all_targets")
                        self.success_criteria_combo.addItem("至少一张SSR", "any_ssr")
                        self.success_criteria_combo.addItem("每池至少一张目标卡", "per_pool_target")
                        item_w.add_config_row("成功判据:", self.success_criteria_combo)

                    if key == 'cumulative_by_pool':
                        cum_widget = QWidget()
                        cum_layout = QVBoxLayout(cum_widget)
                        cum_layout.setContentsMargins(0, 0, 0, 0)
                        cum_layout.setSpacing(2)
                        for gdr_name in _gdr_names:
                            row = QHBoxLayout()
                            row.setSpacing(4)
                            name_lbl = QLabel(gdr_name)
                            name_lbl.setStyleSheet("font-size: 11px;")
                            name_lbl.setMinimumWidth(90)
                            row.addWidget(name_lbl)
                            cb = QCheckBox("分析")
                            cb.setStyleSheet("font-size: 11px;")
                            row.addWidget(cb)
                            row.addStretch()
                            cum_layout.addLayout(row)
                            self._cumulative_by_pool_checks[gdr_name] = cb
                        item_w.add_config_widget(cum_widget)

                    layout.addWidget(item_w)
                else:
                    cb = QCheckBox(label)
                    self._items[key] = cb
                    layout.addWidget(cb)

        layout.addStretch()
        scroll.setWidget(container)
        outer_layout.addWidget(scroll, stretch=1)

        bottom_bar = QWidget()
        sb_width = scroll.verticalScrollBar().sizeHint().width() + 2  # 滚动条宽度 + 边框余量
        bottom_layout = QVBoxLayout(bottom_bar)
        bottom_layout.setContentsMargins(0, 0, sb_width, 0)
        bottom_layout.setSpacing(4)

        action_layout = QHBoxLayout()
        self.run_btn = QPushButton("运行分析")
        self.run_btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; padding: 8px; }")
        self.run_btn.clicked.connect(self._run_analysis)
        action_layout.addWidget(self.run_btn)
        self.clear_btn = QPushButton("清除结果")
        self.clear_btn.setStyleSheet("QPushButton { background-color: #f44336; color: white; padding: 8px; }")
        self.clear_btn.clicked.connect(self._clear_results)
        action_layout.addWidget(self.clear_btn)
        bottom_layout.addLayout(action_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setRange(0, 100)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setMaximumHeight(20)
        bottom_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        self.status_label.setStyleSheet("color: #666;")
        bottom_layout.addWidget(self.status_label)

        outer_layout.addWidget(bottom_bar)
        return outer

    def _build_results_panel(self):
        self._results_scroll = QScrollArea()
        self._results_scroll.verticalScrollBar().setSingleStep(15)
        self._results_scroll.setWidgetResizable(True)
        self._results_scroll.setStyleSheet("QScrollArea { background: #f5f5f5; border: none; }")

        self._results_container = QWidget()
        self._results_container.setStyleSheet("background: #f5f5f5;")
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._results_layout.setSpacing(12)
        self._results_layout.setContentsMargins(8, 8, 8, 8)

        self._placeholder_label = QLabel("请选择分析项并点击\"运行分析\"")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_label.setStyleSheet("color: #999; font-size: 14px; padding: 40px;")
        self._results_layout.addWidget(self._placeholder_label)

        self._results_scroll.setWidget(self._results_container)
        return self._results_scroll

    def _select_all(self):
        for item in self._items.values():
            item.setChecked(True)

    def _deselect_all(self):
        for item in self._items.values():
            item.setChecked(False)

    @staticmethod
    def _is_discrete(samples):
        if not samples:
            return False
        return all(abs(v - round(v)) < 1e-9 for v in samples[:min(200, len(samples))])

    @staticmethod
    def _unique_count(samples):
        if not samples:
            return 0
        seen = set()
        for v in samples[:5000]:
            seen.add(v)
            if len(seen) > 2:
                break
        return len(seen)

    @staticmethod
    def _hist_params(samples, color, alpha_val, label):
        import numpy as np
        n = AnalysisPanel._unique_count(samples)
        if n <= 1:
            lo = float(samples[0]) if samples else 0.0
            return {
                'bins': [lo - 0.5, lo + 0.5], 'density': False,
                'align': 'mid', 'edgecolor': color, 'alpha': alpha_val,
                'label': label, 'rwidth': 0.8,
            }
        is_d = AnalysisPanel._is_discrete(samples)
        if is_d:
            lo = int(min(samples))
            hi = int(max(samples)) + 1
            bins = list(range(lo, hi + 1)) if hi > lo else [lo - 0.5, lo + 0.5]
            return {'bins': bins, 'density': False, 'align': 'left', 'edgecolor': color, 'alpha': alpha_val, 'label': label, 'rwidth': 0.8}
        vals = np.array(samples)
        q1, q3 = np.percentile(vals, [25, 75])
        iqr = max(q3 - q1, 1e-9)
        span = max(vals) - min(vals)
        if span > 0 and iqr / span < 0.05:
            nbins = max(50, min(200, int(len(samples) / 20)))
        else:
            from gacha_simulator.core.distribution import freedman_diaconis_bins
            nbins = freedman_diaconis_bins(samples)
        return {'bins': nbins, 'density': True, 'edgecolor': color, 'alpha': alpha_val, 'label': label}

    def _on_preset_threshold(self, preset_type):
        if not self.results:
            self.status_label.setText("无模拟结果，无法计算预设阈值")
            return
        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY, compute_gdr_from_compact
        from gacha_simulator.core.distribution import EmpiricalDistribution
        cond_name = self.cond_gdr_combo.currentText()
        _gdr_key_by_name = {defn.display_name: key for key, defn in UNIFIED_GDR_REGISTRY.items()}
        cond_key = _gdr_key_by_name.get(cond_name)
        if not cond_key:
            return
        target_specs = self._gdr_context.target_specs if self._gdr_context else {}
        ssr_ids = self._gdr_context.ssr_ids if self._gdr_context else set()
        vals = [compute_gdr_from_compact(h, target_specs, cond_key, ssr_ids=ssr_ids) for h in self.results]
        dist = EmpiricalDistribution(vals)
        if dist.n == 0:
            return
        alpha = self.alpha_spin.value()
        preset_labels = {'var': f'VaR({alpha})', 'upper': f'上{1-alpha}分位数', 'median': '中位数'}
        if preset_type == 'var':
            threshold = dist.quantile(alpha)
        elif preset_type == 'upper':
            threshold = dist.quantile(1 - alpha)
        elif preset_type == 'median':
            threshold = dist.median()
        else:
            return
        self.threshold_spin.setValue(threshold)
        self.status_label.setText(f"已设置{cond_name}的{preset_labels.get(preset_type, preset_type)}={threshold:.4f}")
        for btn, pt in [(self.preset_var_btn, 'var'), (self.preset_upper_btn, 'upper'), (self.preset_median_btn, 'median')]:
            if pt == preset_type:
                btn.setStyleSheet("QPushButton { background-color: #4CAF50; color: white; font-weight: bold; font-size: 10px; }")
            else:
                btn.setStyleSheet("font-size: 10px;")

    def _get_selected(self):
        return [key for key, item in self._items.items() if item.isChecked()]

    def _get_gdr_dist_selections(self):
        selections = {}
        for name, checks in self._gdr_dist_checks.items():
            selected = set()
            if checks['hist'].isChecked():
                selected.add('hist')
            if checks['cdf'].isChecked():
                selected.add('cdf')
            if selected:
                selections[name] = selected
        return selections

    def _get_cumulative_by_pool_selections(self):
        return {name for name, cb in self._cumulative_by_pool_checks.items() if cb.isChecked()}

    def _get_worst_case_cond_selections(self):
        return {name for name, cb in self._worst_case_cond_checks.items() if cb.isChecked()}

    def _get_best_case_cond_selections(self):
        return {name for name, cb in self._best_case_cond_checks.items() if cb.isChecked()}

    def _get_conditions_for_key(self, key):
        cond = {'alpha': self.alpha_spin.value()}
        if key == 'transition_analysis':
            cond['success_criteria'] = self.success_criteria_combo.currentData()
        if key in ('conditional_dist', 'conditional_dist_chart'):
            cond['cond_gdr'] = self.cond_gdr_combo.currentText()
            cond['target_gdr'] = self.target_gdr_combo.currentText()
            cond['cond_threshold'] = self.threshold_spin.value()
        if key in ('risk_worst_case', 'risk_worst_case_chart'):
            cond['primary_gdr'] = self.primary_gdr_combo.currentText()
            cond['worst_case_cond_selections'] = frozenset(self._get_worst_case_cond_selections())
        if key in ('risk_best_case', 'risk_best_case_chart'):
            cond['primary_gdr'] = self.best_primary_gdr_combo.currentText()
            cond['best_case_cond_selections'] = frozenset(self._get_best_case_cond_selections())
        if key.startswith('gdr_dist_') or key == 'gdr_dist':
            sel = self._get_gdr_dist_selections()
            cond['gdr_dist_selections'] = frozenset((k, frozenset(v)) for k, v in sel.items())
        if key.startswith('cumulative_by_pool_') or key == 'cumulative_by_pool':
            cond['cumulative_by_pool_selections'] = frozenset(self._get_cumulative_by_pool_selections())
        cond['use_draw_units'] = self.draw_unit_cb.isChecked()
        cond['cost_per_draw'] = self.cost_per_draw_spin.value()
        return cond

    def _needs_computation(self, key):
        if key not in self._computed_conditions:
            return True
        return self._get_conditions_for_key(key) != self._computed_conditions[key]

    def _run_analysis(self):
        selected = self._get_selected()
        if not selected:
            self.status_label.setText("请至少选择一项分析")
            return
        if not self.results:
            self.status_label.setText("无模拟结果，请先运行模拟")
            return

        to_compute = [k for k in selected if self._needs_computation(k)]
        if not to_compute:
            self.status_label.setText("所有选中项已有结果且条件未变")
            return

        chart_keys = [k for k in to_compute if k != 'gdr_statistics']
        need_statistics = 'gdr_statistics' in to_compute

        if chart_keys:
            self.run_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.status_label.setText("分析中...")

            self._pending_statistics = need_statistics

            self._worker = AnalysisWorker(
                self.results, self._gdr_context, self._pool_end_times,
                chart_keys, self.alpha_spin.value(), self.output_dir,
                self.success_criteria_combo.currentData(),
                cond_gdr=self.cond_gdr_combo.currentText(),
                target_gdr=self.target_gdr_combo.currentText(),
                cond_threshold=self.threshold_spin.value(),
                primary_gdr=self.primary_gdr_combo.currentText(),
                best_primary_gdr=self.best_primary_gdr_combo.currentText(),
                gdr_dist_selections=self._get_gdr_dist_selections(),
                cumulative_by_pool_selections=self._get_cumulative_by_pool_selections(),
                worst_case_cond_selections=self._get_worst_case_cond_selections(),
                best_case_cond_selections=self._get_best_case_cond_selections(),
                draw_sequences=self._draw_sequences,
                heatmap_data=self._heatmap_data,
                cumulative_snapshots=self._cumulative_snapshots,
                transition_flags=self._transition_flags,
                use_draw_units=self.draw_unit_cb.isChecked(),
                cost_per_draw=self.cost_per_draw_spin.value(),
                no_draw_resource=self._no_draw_resource,
                no_draw_pool_resources=self._no_draw_pool_resources,
            )
            self._worker.progress.connect(self._on_progress)
            self._worker.finished.connect(self._on_analysis_done)
            self._worker.start()
        else:
            if need_statistics:
                self._compute_statistics_unit()
            if self._placeholder_label:
                self._placeholder_label.setVisible(False)
            self.status_label.setText("完成")

    def _on_progress(self, msg, pct):
        self.status_label.setText(msg)
        self.progress_bar.setValue(pct)

    def _on_analysis_done(self, charts):
        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY
        key_to_display = {k: d.display_name for k, d in UNIFIED_GDR_REGISTRY.items()}
        for key, data in charts.items():
            title = _KEY_TITLE_MAP.get(key)
            if title is None and key.startswith('gdr_dist_'):
                metric_name = key[len('gdr_dist_'):]
                title = f'{metric_name} 分布'
            if title is None and key.startswith('cumulative_by_pool_'):
                metric_name = key[len('cumulative_by_pool_'):]
                title = f'{metric_name} (截止每池)'
            if title is None and key.startswith('risk_worst_case_') and not key.endswith('_chart'):
                metric_name = key[len('risk_worst_case_'):]
                metric_display = key_to_display.get(metric_name, metric_name)
                title = f'最差情形: {metric_display}'
            if title is None and key.startswith('risk_best_case_') and not key.endswith('_chart'):
                metric_name = key[len('risk_best_case_'):]
                metric_display = key_to_display.get(metric_name, metric_name)
                title = f'最好情形: {metric_display}'
            if title is None:
                title = key
            if key in self._result_units:
                unit = self._result_units[key]
            else:
                unit = ResultUnit(key, title)
                unit.export_btn.clicked.connect(lambda checked, k=key: self._export_unit(k))
                self._results_layout.addWidget(unit)
                self._result_units[key] = unit
            if isinstance(data, tuple) and len(data) == 3 and data[0] == 'table':
                _, headers, rows = data
                unit.set_table(headers, rows)
            else:
                unit.set_chart(data)
            self._computed_conditions[key] = self._get_conditions_for_key(key)

        if any(k.startswith('gdr_dist_') for k in charts):
            self._computed_conditions['gdr_dist'] = self._get_conditions_for_key('gdr_dist')
        if any(k.startswith('cumulative_by_pool_') for k in charts):
            self._computed_conditions['cumulative_by_pool'] = self._get_conditions_for_key('cumulative_by_pool')
        if any(k.startswith('risk_worst_case_') for k in charts):
            self._computed_conditions['risk_worst_case'] = self._get_conditions_for_key('risk_worst_case')
        if any(k.startswith('risk_best_case_') for k in charts):
            self._computed_conditions['risk_best_case'] = self._get_conditions_for_key('risk_best_case')

        if getattr(self, '_pending_statistics', False):
            self._compute_statistics_unit()
            self._pending_statistics = False

        selected = self._get_selected()
        if 'gdr_statistics' in selected and self._needs_computation('gdr_statistics'):
            self._compute_statistics_unit()

        if self._placeholder_label:
            self._placeholder_label.setVisible(False)

        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(100)
        self.status_label.setText(f"完成，共 {len(self._result_units)} 个结果单元")

        last_key = list(charts.keys())[-1] if charts else None
        if last_key and last_key in self._result_units:
            self._results_scroll.ensureWidgetVisible(self._result_units[last_key])

    def _compute_statistics_unit(self):
        if not self.results or not self._gdr_context:
            return

        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY, compute_gdr_from_compact
        import numpy as np

        target_specs = self._gdr_context.target_specs if self._gdr_context else {}
        ssr_ids = self._gdr_context.ssr_ids if self._gdr_context else set()

        headers = ["指标", "均值", "中位数", "标准差", f"VaR({self.alpha_spin.value():.0%})"]
        rows = []
        self._summary_data = {}

        use_draw_units = self.draw_unit_cb.isChecked()
        cost_per_draw = self.cost_per_draw_spin.value()

        from gacha_simulator.core.distribution import EmpiricalDistribution
        for key, defn in UNIFIED_GDR_REGISTRY.items():
            try:
                vals = []
                for r in self.results:
                    v = compute_gdr_from_compact(r, target_specs, key, ssr_ids=ssr_ids)
                    vals.append(v)
                if key == 'resource_remaining' and use_draw_units and cost_per_draw > 0:
                    vals = [v / cost_per_draw for v in vals]
                mean_val = np.mean(vals)
                median_val = np.median(vals)
                std_val = np.std(vals)
                var_val = EmpiricalDistribution(vals).var(self.alpha_spin.value())
                _display_name = defn.display_name
                if key == 'resource_remaining' and use_draw_units:
                    _display_name = f'{_display_name} (抽)'
                rows.append([_display_name, f"{mean_val:.4f}", f"{median_val:.4f}", f"{std_val:.4f}", f"{var_val:.4f}"])
                self._summary_data[_display_name] = {'mean': f"{mean_val:.4f}"}
            except Exception:
                _display_name = defn.display_name
                if key == 'resource_remaining' and use_draw_units:
                    _display_name = f'{_display_name} (抽)'
                rows.append([_display_name, "-", "-", "-"])
                self._summary_data[_display_name] = {'mean': "-"}

        key = 'gdr_statistics'
        title = _KEY_TITLE_MAP.get(key, 'GDR指标统计')

        if key in self._result_units:
            self._result_units[key].set_table(headers, rows)
        else:
            unit = ResultUnit(key, title)
            unit.set_table(headers, rows)
            unit.export_btn.clicked.connect(lambda checked, k=key: self._export_unit(k))
            self._results_layout.addWidget(unit)
            self._result_units[key] = unit

        self._computed_conditions[key] = self._get_conditions_for_key(key)

    def _export_unit(self, key):
        unit = self._result_units.get(key)
        if not unit:
            return
        image_path = unit.get_image_path()
        if image_path and os.path.exists(image_path):
            save_path, _ = QFileDialog.getSaveFileName(self, "导出图表", f"{key}.png", "PNG Files (*.png)")
            if save_path:
                from shutil import copy2
                copy2(image_path, save_path)
        else:
            table = unit.findChild(QTableWidget)
            if table:
                save_path, _ = QFileDialog.getSaveFileName(self, "导出数据", f"{key}.csv", "CSV Files (*.csv)")
                if save_path:
                    with open(save_path, 'w', encoding='utf-8-sig') as f:
                        headers = []
                        for c in range(table.columnCount()):
                            hi = table.horizontalHeaderItem(c)
                            headers.append(hi.text() if hi else '')
                        f.write(','.join(headers) + '\n')
                        for r in range(table.rowCount()):
                            row_data = []
                            for c in range(table.columnCount()):
                                item = table.item(r, c)
                                row_data.append(item.text() if item else '')
                            f.write(','.join(row_data) + '\n')

    def _clear_results(self):
        for key in list(self._result_units.keys()):
            unit = self._result_units.pop(key)
            self._results_layout.removeWidget(unit)
            unit.deleteLater()
        self._computed_conditions.clear()
        self._summary_data.clear()
        if self._placeholder_label:
            self._placeholder_label.setVisible(True)
        self.status_label.setText("已清除所有结果")
        self.progress_bar.setValue(0)

    def update_results(self, results, target_ids=None, ssr_ids=None, gdr_context=None, pool_end_times=None,
                       draw_sequences=None, heatmap_data=None, cumulative_snapshots=None, transition_flags=None,
                       no_draw_resource=None, no_draw_pool_resources=None):
        self.results = results
        self._gdr_context = gdr_context
        self._pool_end_times = pool_end_times or {}
        self._draw_sequences = draw_sequences or []
        self._heatmap_data = heatmap_data or {}
        self._cumulative_snapshots = cumulative_snapshots or {}
        self._transition_flags = transition_flags or []
        self._no_draw_resource = no_draw_resource
        self._no_draw_pool_resources = no_draw_pool_resources or {}
        self._clear_results()
        self.status_label.setText(f"已加载 {len(results)} 条模拟结果，请选择分析项并运行")

    def get_summary(self):
        return dict(self._summary_data)
