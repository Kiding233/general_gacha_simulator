#!/usr/bin/env python3

import os
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QGroupBox, QScrollArea, QCheckBox, QSplitter, QComboBox,
    QSpinBox, QDoubleSpinBox,
    QGridLayout, QProgressBar, QSizePolicy,
    QFrame,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal



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

# 渲染顺序：按 ANALYSIS_CATEGORIES 中定义的出现顺序排列图表
_CHART_DISPLAY_ORDER: dict[str, int] = {}
_order_idx = 0
for _cat, _items in ANALYSIS_CATEGORIES.items():
    for _key, _label in _items:
        _CHART_DISPLAY_ORDER[_key] = _order_idx
        _order_idx += 1


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


# 支持「以抽数为单位」换算的资源类 GDR（除以 cost_per_draw 转为抽数等价量）
_DRAW_UNIT_GDR_KEYS = {'resource_remaining', 'resource_consumed', 'resource_per_card'}

class AnalysisWorker(QThread):
    finished = pyqtSignal(dict)
    progress = pyqtSignal(str, int)
    error = pyqtSignal(str)

    def __init__(self, results, ctx, pool_end_times, selected, alpha, output_dir, success_criteria='all_targets', cond_gdr='抽出全部目标卡', target_gdr='资源剩余', cond_threshold=0.5, primary_gdr='简单目标达成率', best_primary_gdr='简单目标达成率', gdr_dist_selections=None, cumulative_by_pool_selections=None, worst_case_cond_selections=None, best_case_cond_selections=None, draw_sequences=None, heatmap_data=None, cumulative_snapshots=None, transition_flags=None, use_draw_units=False, cost_per_draw=160, no_draw_resource=None, no_draw_pool_resources=None, pool_names=None):
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
        self.pool_names = pool_names or {}

    def _emit(self, msg, pct):
        self.progress.emit(msg, pct)

    def run(self):
        try:
            self._run_impl()
        except Exception as e:
            import traceback
            self.error.emit(f"分析过程发生异常：{e}\n{traceback.format_exc()}")

    def _run_impl(self):
        import numpy as np
        from gacha_simulator.visualization.chart_spec import (
            ChartSpec, ChartAnnotation,
            HistogramData, HistogramOverlay, CDFData, RidgeData,
            ScatterData, ScatterTrace, BarData, HeatmapData, Waterfall3DData,
            histogram, cdf, ridge, scatter, scatter_multi, scatter_colored,
            bar, heatmap,
        )

        def _strip_pid(pid: str) -> str:
            """返回池子显示名：优先配置中文名，fallback 为原始 ID。"""
            return self.pool_names.get(pid, pid)

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
        _display_to_key = {
            (('(-)' + defn.display_name) if defn.lower_is_better else defn.display_name): key
            for key, defn in UNIFIED_GDR_REGISTRY.items()
        }
        _key_to_display = {
            key: (('(-)' + defn.display_name) if defn.lower_is_better else defn.display_name)
            for key, defn in UNIFIED_GDR_REGISTRY.items()
        }

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
            _resource_gdr_keys = _DRAW_UNIT_GDR_KEYS
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

                no_draw_ref = None
                if metric_key == 'resource_remaining' and self.no_draw_resource is not None:
                    no_draw_ref = self.no_draw_resource
                    if self.use_draw_units and self.cost_per_draw > 0:
                        no_draw_ref = no_draw_ref / self.cost_per_draw

                _unit_suffix = ' (抽)' if (metric_key in _DRAW_UNIT_GDR_KEYS and self.use_draw_units) else ''
                annotations = []
                if no_draw_ref is not None:
                    annotations.append(ChartAnnotation(
                        type="vline", value=no_draw_ref, color="green",
                        dash="dash", text=f'不抽卡基线: {no_draw_ref:.1f}',
                    ))

                if 'hist' in chart_types:
                    var_val = dist.var(alpha)
                    spec = ChartSpec(
                        chart_type="histogram",
                        data=HistogramData(
                            samples=np.array(dist.samples),
                            mean_line=True,
                            quantile_lines=[alpha],
                        ),
                        title=f'{metric_name}{_unit_suffix} 分布',
                        xlabel=f'{metric_name}{_unit_suffix}',
                        ylabel='概率密度',
                        annotations=list(annotations),
                    )
                    # 替换默认分位数线标签为 VaR 格式
                    if spec.annotations:
                        for a in spec.annotations:
                            if a.type == "vline" and a.color == "green":
                                a.text = f'不抽卡基线: {no_draw_ref:.1f}'
                    charts[f'gdr_dist_{metric_name}_hist'] = spec

                if 'cdf' in chart_types:
                    spec = ChartSpec(
                        chart_type="cdf",
                        data=CDFData(samples=np.array(dist.samples)),
                        title=f'{metric_name}{_unit_suffix} 累积分布',
                        xlabel=f'{metric_name}{_unit_suffix}',
                        ylabel='累积概率',
                        annotations=[
                            ChartAnnotation(type="hline", value=alpha, color="orange", dash="dot", text=f'α={alpha:.2f}'),
                        ] + list(annotations),
                    )
                    charts[f'gdr_dist_{metric_name}_cdf'] = spec
            step_done('GDR分布')

        if 'risk_var_cvar' in self.selected:
            self._emit('生成VaR/CVaR分析...', int(completed / total_steps * 100))
            rows = []
            for name, dist in gdr_dists.items():
                if dist.n < 2:
                    continue
                _display_name = _key_to_display.get(name, name)
                if name in _DRAW_UNIT_GDR_KEYS and self.use_draw_units:
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
                from gacha_simulator.visualization.chart_spec import TableData
                charts['risk_var_cvar'] = ChartSpec(
                    chart_type="table",
                    data=TableData(headers=headers, rows=table_rows),
                    title='GDR 风险指标 (VaR/CVaR)',
                )
            step_done('VaR/CVaR分析')

        if 'risk_worst_case' in self.selected:
            self._emit('生成最差情形分析...', int(completed / total_steps * 100))
            primary_name = self.primary_gdr
            primary_key = _display_to_key.get(primary_name, primary_name)
            primary_dist = gdr_dists.get(primary_key)
            primary_defn = UNIFIED_GDR_REGISTRY.get(primary_key)
            primary_lib = primary_defn.lower_is_better if primary_defn else False
            if primary_dist and primary_dist.n > 0:
                from gacha_simulator.core.distribution import JointSamples
                if primary_lib:
                    var_val = primary_dist.quantile(1 - alpha)
                    is_in_tail = [v >= var_val for v in primary_dist.samples]
                    tail_label = f'≥上{1-alpha}分位数'
                    tail_label_short = f'上{1-alpha}分位数'
                else:
                    var_val = primary_dist.quantile(alpha)
                    is_in_tail = [v <= var_val for v in primary_dist.samples]
                    tail_label = f'≤VaR({alpha})'
                    tail_label_short = f'VaR({alpha})'
                tail_samples = [primary_dist.samples[i] for i in range(primary_dist.n) if is_in_tail[i]]
                tail_dist = EmpiricalDistribution(tail_samples) if tail_samples else EmpiricalDistribution([])

                table_rows = []
                for name, dist in gdr_dists.items():
                    if dist.n < 2:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    cond_filter = (lambda f: f >= var_val) if primary_lib else (lambda f: f <= var_val)
                    cond_dist = joint.conditional_second(cond_filter)
                    if cond_dist.n > 0:
                        g_mean = dist.mean()
                        g_var = dist.var(alpha)
                        _wc_display = _key_to_display.get(name, name)
                        if name in _DRAW_UNIT_GDR_KEYS and self.use_draw_units:
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
                    var_label = f'上{1-alpha}分位数' if primary_lib else f'VaR({alpha})'
                    headers = ['GDR指标', '样本数', '全局均值', '条件均值', '均值差', '中位数', '标准差', var_label, 'VaR-均值差', 'VaR-中位数差', '最小值', '最大值']
                    from gacha_simulator.visualization.chart_spec import TableData
                    charts['risk_worst_case'] = ChartSpec(
                        chart_type="table",
                        data=TableData(headers=headers, rows=table_rows),
                        title=f'各GDR在 {primary_name} 条件分布下的统计量',
                    )

                # 主概览图: 直方图 + 尾部叠加
                is_disc = AnalysisPanel._is_discrete(primary_dist.samples)
                main_color = 'black'
                wc_overlays = []
                wc_anns = [
                    ChartAnnotation(type="vline", value=var_val, color="orange", dash="dash",
                                    text=f'{tail_label_short}={var_val:.4f}'),
                ]
                if tail_dist.n > 0:
                    uc_tail = AnalysisPanel._unique_count(tail_dist.samples)
                    if uc_tail <= 1 and AnalysisPanel._unique_count(primary_dist.samples) > 1:
                        wc_anns.append(ChartAnnotation(
                            type="vline", value=float(tail_dist.samples[0]), color="red", dash="solid",
                            text=f'{tail_label}, n={tail_dist.n} (值={float(tail_dist.samples[0]):.2f})',
                        ))
                    else:
                        wc_overlays.append(HistogramOverlay(
                            samples=np.array(tail_dist.samples),
                            color='red', opacity=0.6, label=f'{tail_label}, n={tail_dist.n}',
                        ))
                charts['risk_worst_case_chart'] = ChartSpec(
                    chart_type="histogram",
                    data=HistogramData(
                        samples=np.array(primary_dist.samples),
                        mean_line=False,
                        overlays=wc_overlays,
                        density=not is_disc,
                    ),
                    title=f'最差情形分析: {primary_name} (α={alpha})',
                    xlabel=primary_name,
                    ylabel='频次' if is_disc else '密度',
                    annotations=wc_anns,
                )

                # 各指标条件分布图
                for name, dist in gdr_dists.items():
                    if name == primary_key or dist.n < 2:
                        continue
                    display = _key_to_display.get(name, name)
                    if display not in self.worst_case_cond_selections:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    cond = joint.conditional_second(lambda f: f >= var_val) if primary_lib else joint.conditional_second(lambda f: f <= var_val)
                    if cond.n < 2:
                        continue
                    is_disc2 = AnalysisPanel._is_discrete(dist.samples)
                    _wc_xlabel = f'{display} (抽)' if (name in _DRAW_UNIT_GDR_KEYS and self.use_draw_units) else display
                    wc_cond_op = '≥' if primary_lib else '≤'
                    wc_cond_label = tail_label_short if primary_lib else f'VaR({alpha})'
                    ovs2 = [HistogramOverlay(
                        samples=np.array(cond.samples), color='red', opacity=0.6,
                        label=f'{display}(最差条件, n={cond.n})',
                    )]
                    charts[f'risk_worst_case_{name}'] = ChartSpec(
                        chart_type="histogram",
                        data=HistogramData(
                            samples=np.array(dist.samples),
                            mean_line=False,
                            overlays=ovs2,
                            density=not is_disc2,
                        ),
                        title=f'最差情形: {display} | {primary_name}{wc_cond_op}{wc_cond_label}',
                        xlabel=_wc_xlabel,
                        ylabel='频次' if is_disc2 else '密度',
                    )
            step_done('最差情形分析')

        if 'risk_best_case' in self.selected:
            self._emit('生成最好情形分析...', int(completed / total_steps * 100))
            primary_name = self.best_primary_gdr
            primary_key = _display_to_key.get(primary_name, primary_name)
            primary_dist = gdr_dists.get(primary_key)
            primary_defn_best = UNIFIED_GDR_REGISTRY.get(primary_key)
            primary_lib_best = primary_defn_best.lower_is_better if primary_defn_best else False
            if primary_dist and primary_dist.n > 0:
                from gacha_simulator.core.distribution import JointSamples
                if primary_lib_best:
                    upper_val = primary_dist.quantile(alpha)
                    is_in_top = [v <= upper_val for v in primary_dist.samples]
                    best_tail_label = f'≤VaR({alpha})'
                    best_tail_label_short = f'VaR({alpha})'
                else:
                    upper_val = primary_dist.quantile(1 - alpha)
                    is_in_top = [v >= upper_val for v in primary_dist.samples]
                    best_tail_label = f'≥上{1-alpha}分位数'
                    best_tail_label_short = f'上{1-alpha}分位数'
                top_samples = [primary_dist.samples[i] for i in range(primary_dist.n) if is_in_top[i]]
                top_dist = EmpiricalDistribution(top_samples) if top_samples else EmpiricalDistribution([])

                table_rows = []
                for name, dist in gdr_dists.items():
                    if dist.n < 2:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    bc_cond_filter = (lambda f: f <= upper_val) if primary_lib_best else (lambda f: f >= upper_val)
                    cond_dist = joint.conditional_second(bc_cond_filter)
                    if cond_dist.n > 0:
                        g_mean = dist.mean()
                        display = _key_to_display.get(name, name)
                        if name in _DRAW_UNIT_GDR_KEYS and self.use_draw_units:
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
                    bc_var_label = f'VaR({alpha})' if primary_lib_best else f'上{1-alpha}分位数'
                    headers = ['GDR指标', '样本数', '全局均值', '条件均值', '均值差', '中位数', '标准差', bc_var_label, 'VaR-均值差', 'VaR-中位数差', '最小值', '最大值']
                    from gacha_simulator.visualization.chart_spec import TableData
                    best_primary_name = self.best_primary_gdr
                    charts['risk_best_case'] = ChartSpec(
                        chart_type="table",
                        data=TableData(headers=headers, rows=table_rows),
                        title=f'各GDR在 {best_primary_name} 条件分布下的统计量',
                    )

                # 主概览图: 直方图 + 顶部叠加
                is_disc = AnalysisPanel._is_discrete(primary_dist.samples)
                bc_overlays = []
                bc_anns = [
                    ChartAnnotation(type="vline", value=upper_val, color="green", dash="dash",
                                    text=f'{best_tail_label_short}={upper_val:.4f}'),
                ]
                if top_dist.n > 0:
                    uc_top = AnalysisPanel._unique_count(top_dist.samples)
                    if uc_top <= 1 and AnalysisPanel._unique_count(primary_dist.samples) > 1:
                        bc_anns.append(ChartAnnotation(
                            type="vline", value=float(top_dist.samples[0]), color="green", dash="solid",
                            text=f'{best_tail_label}, n={top_dist.n} (值={float(top_dist.samples[0]):.2f})',
                        ))
                    else:
                        bc_overlays.append(HistogramOverlay(
                            samples=np.array(top_dist.samples),
                            color='green', opacity=0.6, label=f'{best_tail_label}, n={top_dist.n}',
                        ))
                charts['risk_best_case_chart'] = ChartSpec(
                    chart_type="histogram",
                    data=HistogramData(
                        samples=np.array(primary_dist.samples),
                        mean_line=False,
                        overlays=bc_overlays,
                        density=not is_disc,
                    ),
                    title=f'最好情形分析: {primary_name} (α={alpha})',
                    xlabel=primary_name,
                    ylabel='频次' if is_disc else '密度',
                    annotations=bc_anns,
                )

                # 各指标条件分布图
                for name, dist in gdr_dists.items():
                    if name == primary_key or dist.n < 2:
                        continue
                    display = _key_to_display.get(name, name)
                    if display not in self.best_case_cond_selections:
                        continue
                    joint = JointSamples([(primary_dist.samples[i], dist.samples[i]) for i in range(primary_dist.n) if i < dist.n])
                    bc_cond_filter2 = (lambda f: f <= upper_val) if primary_lib_best else (lambda f: f >= upper_val)
                    cond = joint.conditional_second(bc_cond_filter2)
                    if cond.n < 2:
                        continue
                    is_disc2 = AnalysisPanel._is_discrete(dist.samples)
                    _bc_xlabel = f'{display} (抽)' if (name in _DRAW_UNIT_GDR_KEYS and self.use_draw_units) else display
                    bc_cond_op = '≤' if primary_lib_best else '≥'
                    bc_cond_label2 = best_tail_label_short if primary_lib_best else f'上{1-alpha}分位数'
                    ovs2 = [HistogramOverlay(
                        samples=np.array(cond.samples), color='green', opacity=0.6,
                        label=f'{display}(最好条件, n={cond.n})',
                    )]
                    charts[f'risk_best_case_{name}'] = ChartSpec(
                        chart_type="histogram",
                        data=HistogramData(
                            samples=np.array(dist.samples),
                            mean_line=False,
                            overlays=ovs2,
                            density=not is_disc2,
                        ),
                        title=f'最好情形: {display} | {primary_name}{bc_cond_op}{bc_cond_label2}',
                        xlabel=_bc_xlabel,
                        ylabel='频次' if is_disc2 else '密度',
                    )
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
                if target_key in _DRAW_UNIT_GDR_KEYS and self.use_draw_units and self.cost_per_draw > 0:
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
                        from gacha_simulator.visualization.chart_spec import TableData
                        cond_gdr_name = self.cond_gdr
                        target_gdr_name = self.target_gdr
                        charts['conditional_dist'] = ChartSpec(
                            chart_type="table",
                            data=TableData(headers=headers, rows=table_rows),
                            title=f'{cond_gdr_name} 条件下 {target_gdr_name} 的分布统计量',
                        )

                    is_disc = AnalysisPanel._is_discrete(all_target.samples)
                    _cond_unit_suffix = ' (抽)' if (target_key in _DRAW_UNIT_GDR_KEYS and self.use_draw_units) else ''
                    overlays_cond = []
                    cond_anns = []
                    if success_target.n > 0:
                        overlays_cond.append(HistogramOverlay(
                            samples=np.array(success_target.samples), color='green', opacity=0.5,
                            label=f'条件≥{success_threshold:.4f}(n={success_target.n})',
                        ))
                    if fail_target.n > 0:
                        overlays_cond.append(HistogramOverlay(
                            samples=np.array(fail_target.samples), color='red', opacity=0.5,
                            label=f'条件<{success_threshold:.4f}(n={fail_target.n})',
                        ))
                    if target_key == 'resource_remaining' and self.no_draw_resource is not None:
                        _ref = self.no_draw_resource
                        if self.use_draw_units and self.cost_per_draw > 0:
                            _ref = _ref / self.cost_per_draw
                        cond_anns.append(ChartAnnotation(
                            type="vline", value=_ref, color="green", dash="dash",
                            text=f'不抽卡基线: {_ref:.1f}',
                        ))
                    charts['conditional_dist_chart'] = ChartSpec(
                        chart_type="histogram",
                        data=HistogramData(
                            samples=np.array(all_target.samples),
                            mean_line=False,
                            overlays=overlays_cond,
                            density=not is_disc,
                        ),
                        title=f'条件分布: {target_name}{_target_unit_suffix} | {cond_name} (阈值={success_threshold:.4f})',
                        xlabel=f'{target_name}{_cond_unit_suffix}',
                        ylabel='密度',
                        annotations=cond_anns,
                    )
            step_done('条件分布')

        if 'time_series' in self.selected:
            self._emit('生成时间序列...', int(completed / total_steps * 100))
            if self.draw_sequences:
                target_ids = set(ctx.target_specs.keys())
                target_count = sum(ctx.target_specs.values())
                n_sample = min(20, len(self.draw_sequences))
                indices = np.random.choice(len(self.draw_sequences), n_sample, replace=False) if len(self.draw_sequences) > n_sample else range(len(self.draw_sequences))
                ts_traces = []
                for idx in indices:
                    seq = self.draw_sequences[idx]
                    card_ids = seq.get('draw_card_ids', [])
                    gdr_series = []
                    obtained = 0
                    for cid in card_ids:
                        if cid in target_ids:
                            obtained += 1
                        gdr_series.append(obtained / target_count if target_count > 0 else 0)
                    ts_traces.append(ScatterTrace(
                        x=np.arange(len(gdr_series)), y=np.array(gdr_series),
                        mode="lines", name=f"样本{idx}",
                        marker_size=1, line_color=None,
                    ))
                charts['time_series'] = ChartSpec(
                    chart_type="scatter",
                    data=ScatterData(traces=ts_traces),
                    title='GDR演化（样本路径）',
                    xlabel='抽卡序号',
                    ylabel='目标达成率',
                )
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

                has_content = False

                for row_idx, (gdr_name, gdr_key, vmin_default, vmax_default, n_gdr_bins) in enumerate(gdr_configs):
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

                    if gdr_key == 'resource' and self.use_draw_units and self.cost_per_draw > 0:
                        time_gdr_data = {k: [v / self.cost_per_draw for v in vals] for k, vals in time_gdr_data.items()}
                        gdr_name = '资源剩余 (抽)'

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
                    y_tick_vals = np.linspace(y_lo, y_hi, n_yticks)
                    if gdr_key == 'achievement':
                        y_tick_labels = [f'{v:.0%}' for v in y_tick_vals]
                    elif gdr_key == 'ssr_count':
                        y_tick_labels = [f'{v:.0f}' for v in y_tick_vals]
                    elif gdr_key == 'resource':
                        y_tick_labels = [f'{v:.0f}' for v in y_tick_vals]
                    else:
                        y_tick_labels = [f'{v:.2f}' for v in y_tick_vals]

                    col_labels = [f'{sampled_draws[i]}' for i in range(0, len(sampled_draws))]
                    charts[f'time_heatmap_{gdr_key}'] = ChartSpec(
                        chart_type="heatmap",
                        data=HeatmapData(
                            matrix=density_matrix,
                            row_labels=y_tick_labels,
                            col_labels=col_labels,
                            colorscale="YlOrRd",
                        ),
                        title=f'{gdr_name} 分布随抽卡次数演化 ({n_sims} 次模拟)',
                        xlabel='抽卡次数',
                        ylabel=gdr_name,
                    )

                if has_content:
                    pass  # 各 heatmap 已添加到 charts
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
                sorted_times = sorted(time_gdr_data.keys())
                t_sample = min(40, len(sorted_times))
                t_indices = np.linspace(0, len(sorted_times) - 1, t_sample, dtype=int)
                t_indices = sorted(set(t_indices))
                gdr_range = range(0, target_count + 1)
                wf_x = []
                wf_y = []
                wf_z = []
                for idx in t_indices:
                    t_val = sorted_times[idx]
                    data = time_gdr_data[t_val]
                    counts_per = {g: 0 for g in gdr_range}
                    for v in data:
                        if v in counts_per:
                            counts_per[v] += 1
                    total = len(data)
                    for g in gdr_range:
                        wf_x.append(float(t_val))
                        wf_y.append(float(g))
                        wf_z.append(counts_per[g] / total)
                charts['waterfall_3d'] = ChartSpec(
                    chart_type="waterfall_3d",
                    data=Waterfall3DData(
                        x=np.array(wf_x),
                        y=np.array(wf_y),
                        z=np.array(wf_z),
                    ),
                    title='3D瀑布图',
                    xlabel='时间步',
                    ylabel='目标卡数',
                    layout_hints={'zlabel': '概率'},
                )
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
                t_min = sorted_times[t_indices[0]]
                t_max = sorted_times[t_indices[-1]]
                gdr_range = range(0, target_count + 1)
                wf2d_traces = []
                for idx in t_indices:
                    t_val = sorted_times[idx]
                    data = time_gdr_data[t_val]
                    counts_per = {g: 0 for g in gdr_range}
                    for v in data:
                        if v in counts_per:
                            counts_per[v] += 1
                    total = len(data)
                    probs = [counts_per[g] / total for g in gdr_range]
                    # 使用 viridis 色阶计算颜色
                    frac = (t_val - t_min) / max(t_max - t_min, 1)
                    r = int((0.267 + frac * (0.993 - 0.267)) * 255)
                    g2 = int((0.004 + frac * (0.906 - 0.004)) * 255)
                    b = int((0.329 + frac * (0.144 - 0.329)) * 255)
                    color_hex = f'#{r:02x}{g2:02x}{b:02x}'
                    wf2d_traces.append(ScatterTrace(
                        x=np.array(list(gdr_range)), y=np.array(probs),
                        mode="lines", name=f't={int(t_val)}',
                        marker_size=1, line_color=color_hex,
                    ))
                charts['waterfall_2d'] = ChartSpec(
                    chart_type="scatter",
                    data=ScatterData(traces=wf2d_traces),
                    title='2D瀑布图',
                    xlabel='目标卡数量',
                    ylabel='概率',
                )
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
                short_ids = [_strip_pid(pid) for pid in pool_ids]

                if 'per_pool_draws' in self.selected:
                    vals = [stats[pid].get('mean_draws', 0) for pid in pool_ids]
                    charts['per_pool_draws'] = ChartSpec(
                        chart_type="bar",
                        data=BarData(labels=short_ids, values=np.array(vals), orientation="h"),
                        title='每池平均抽卡数',
                        xlabel='抽卡数',
                        ylabel='池子',
                        layout_hints={'color': '#2196F3'},
                    )

                if 'per_pool_target_rate' in self.selected:
                    vals = [stats[pid].get('target_count', 0) for pid in pool_ids]
                    charts['per_pool_target_rate'] = ChartSpec(
                        chart_type="bar",
                        data=BarData(labels=short_ids, values=np.array(vals), orientation="h"),
                        title='每池目标卡数',
                        xlabel='目标卡数',
                        ylabel='池子',
                        layout_hints={'color': '#4CAF50'},
                    )

                if 'per_pool_pity_rate' in self.selected:
                    vals = [stats[pid].get('pity_count', 0) for pid in pool_ids]
                    charts['per_pool_pity_rate'] = ChartSpec(
                        chart_type="bar",
                        data=BarData(labels=short_ids, values=np.array(vals), orientation="h"),
                        title='每池保底数',
                        xlabel='保底数',
                        ylabel='池子',
                        layout_hints={'color': '#FF9800'},
                    )

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
                short_ids = [_strip_pid(pid) for pid in pool_ids]
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

                    if metric_key in _DRAW_UNIT_GDR_KEYS and self.use_draw_units and self.cost_per_draw > 0:
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
                    ridge_series = {}
                    for sid, dist in zip(short_ids, pool_dists):
                        if dist:
                            ridge_series[sid] = np.array(dist)
                    # 将基线 key 从完整 pool_id 映射为 short_id
                    ridge_baselines = {}
                    for pid, baseline in per_pool_baselines.items():
                        short_pid = _strip_pid(pid)
                        if short_pid in ridge_series:
                            ridge_baselines[short_pid] = baseline
                    _xlabel = metric_name
                    if metric_key in _DRAW_UNIT_GDR_KEYS and self.use_draw_units:
                        _xlabel = f'{metric_name} (抽)'
                    _cum_title = f'{metric_name} (截止每池)'
                    if metric_key in _DRAW_UNIT_GDR_KEYS and self.use_draw_units:
                        _cum_title = f'{metric_name} (抽, 截止每池)'
                    if ridge_series:
                        charts[f'cumulative_by_pool_{metric_name}'] = ChartSpec(
                            chart_type="ridge",
                            data=RidgeData(series=ridge_series, baselines=ridge_baselines),
                            title=_cum_title,
                            xlabel=_xlabel,
                            ylabel='池子',
                        )
                step_done('截止每池的GDR分布')

        if 'draws_vs_gdr' in self.selected:
            self._emit('生成抽卡数-目标达成率散点图...', int(completed / total_steps * 100))
            dist = gdr_dists.get('target_achievement')
            if dist and dist.n > 0:
                draws_per = [agg.get('total_draws', 0) for agg in aggregate_data]
                draws_per = [agg.get('total_draws', 0) for agg in aggregate_data]
                charts['draws_vs_gdr'] = ChartSpec(
                    chart_type="scatter",
                    data=ScatterData(x=np.array(draws_per), y=np.array(dist.samples), mode="markers"),
                    title='抽卡数 vs 简单目标达成率',
                    xlabel='总抽卡数',
                    ylabel='简单目标达成率',
                )
            step_done('抽卡数-目标达成率散点图')

        if 'correlation' in self.selected:
            self._emit('生成相关性分析...', int(completed / total_steps * 100))
            names = [n for n in gdr_dists if gdr_dists[n].n > 1]
            if len(names) >= 2:
                data_matrix = np.array([gdr_dists[n].samples for n in names])
                # 过滤零方差 GDR（如二元指标全部为 0 或全部为 1，导致 corrcoef 除零）
                stds = np.std(data_matrix, axis=1)
                valid_mask = stds > 1e-12
                if valid_mask.sum() >= 2:
                    data_matrix = data_matrix[valid_mask]
                    names = [n for n, v in zip(names, valid_mask) if v]
                    corr = np.corrcoef(data_matrix)
                else:
                    corr = np.zeros((len(names), len(names)))
                short = [_key_to_display.get(n, n)[:8] for n in names]
                charts['correlation'] = ChartSpec(
                    chart_type="heatmap",
                    data=HeatmapData(
                        matrix=corr,
                        row_labels=short,
                        col_labels=short,
                        colorscale="RdBu_r",
                    ),
                    title='GDR指标相关性',
                )
            step_done('相关性分析')

        if 'transition_analysis' in self.selected:
            trans = []
            if not self.pool_end_times:
                self._emit('警告: 转变分析需要池结束时间数据，但当前为空，已跳过',
                           int(completed / total_steps * 100))
            else:
                self._emit('生成转变分析...', int(completed / total_steps * 100))
                from gacha_simulator.core.per_pool_analysis import (
                    compute_transition_matrices_from_flags,
                    compute_transition_flags_from_gdr,
                )

                sorted_pools = sorted(self.pool_end_times.items(), key=lambda x: x[1])
                pool_ids_ordered = [pid for pid, _ in sorted_pools]

                # 优先使用 streaming 提取器预计算的 transition_flags（已修正计数逻辑）
                if self.transition_flags:
                    success_flags_per_sim = self.transition_flags
                elif self.cumulative_snapshots or self.draw_sequences:
                    criteria_map = {
                        'all_targets':      ('all_targets',       'cumulative',  1.0),
                        'any_ssr':          ('ssr_collection',    'cumulative',  0.01),
                        'per_pool_target':  ('target_card_draws', 'single_pool', 1.0),
                    }
                    gdr_key, scope, threshold = criteria_map.get(
                        self.success_criteria, ('all_targets', 'cumulative', 1.0)
                    )
                    success_flags_per_sim = compute_transition_flags_from_gdr(
                        self.cumulative_snapshots, pool_ids_ordered,
                        target_specs, gdr_key=gdr_key, threshold=threshold,
                        scope=scope, aggregates=self.results,
                        ssr_ids=ssr_ids,
                    )
                else:
                    self._emit('警告: 转变分析缺少数据——transition_flags 和 cumulative_snapshots 均为空',
                               int(completed / total_steps * 100))
                    success_flags_per_sim = []

                trans = compute_transition_matrices_from_flags(
                    success_flags_per_sim, pool_ids_ordered,
                )
                if not trans:
                    self._emit('警告: 转变分析无足够数据生成转移矩阵（池数={}，模拟数={}）'.format(
                        len(pool_ids_ordered), len(success_flags_per_sim)),
                        int(completed / total_steps * 100))
            if trans:
                n_trans = len(trans)
                # 使用池名替代池 ID
                def _pool_label(pid):
                    return self.pool_names.get(pid, pid)
                transition_labels = [f'{_pool_label(t.from_pool_id)}→{_pool_label(t.to_pool_id)}' for t in trans]

                # 成功率变化折线图
                ts_rates_traces = [
                    ScatterTrace(
                        x=np.arange(n_trans),
                        y=np.array([t.success_rate_before for t in trans]),
                        mode="lines+markers", name='转移前成功率',
                        marker_size=8, line_color='#2196F3',
                    ),
                    ScatterTrace(
                        x=np.arange(n_trans),
                        y=np.array([t.success_rate_after for t in trans]),
                        mode="lines+markers", name='转移后成功率',
                        marker_size=8, line_color='#4CAF50',
                        marker_symbol="square",
                    ),
                ]
                charts['transition_analysis_rates'] = ChartSpec(
                    chart_type="scatter",
                    data=ScatterData(traces=ts_rates_traces),
                    title='相邻池子间成功率变化',
                    xlabel='转移',
                    ylabel='成功率',
                )

                # 所有转移矩阵合并为一张子图网格
                matrices = []
                grid_titles = []
                for t in trans:
                    mat = np.array([
                        [t.success_to_success, t.success_to_fail],
                        [t.fail_to_success, t.fail_to_fail],
                    ])
                    matrices.append(mat)
                    grid_titles.append(f'{_pool_label(t.from_pool_id)}→{_pool_label(t.to_pool_id)}')
                from gacha_simulator.visualization.chart_spec import SubplotGridData
                charts['transition_analysis_matrices'] = ChartSpec(
                    chart_type="subplot_grid",
                    data=SubplotGridData(
                        matrices=matrices,
                        titles=grid_titles,
                        row_labels=['成功', '失败'],
                        col_labels=['成功', '失败'],
                        colorscale="Blues",
                        cols=4,
                    ),
                    title='转移概率矩阵',
                )
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
        self._computed_conditions = {}
        self._chart_specs_cache: dict[str, object] = {}
        self._chart_webview_initialized = False
        self._summary_data = {}
        self._store = None
        self.output_dir = Path(os.getcwd()) / 'output' / 'analysis'
        self._worker = None
        self._setup_ui()

    def set_store(self, store):
        self._store = store
        self._update_cost_per_draw_default()

    def _get_pool_names(self):
        """构建 {pool_id: pool_name} 映射。"""
        names = {}
        if self._store and hasattr(self._store, 'pools'):
            for pe in self._store.pools:
                names[pe.pool_id] = getattr(pe, 'name', pe.pool_id)
        return names

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
        param_layout.addWidget(QLabel("Bootstrap 置信水平:"), 1, 0)
        self.ci_level_spin = _NoWheelDoubleSpinBox()
        self.ci_level_spin.setRange(0.80, 0.99)
        self.ci_level_spin.setValue(0.95)
        self.ci_level_spin.setSingleStep(0.01)
        self.ci_level_spin.setDecimals(2)
        self.ci_level_spin.setToolTip("Bootstrap 置信区间的置信水平（80%~99%），影响均值/中位数/VaR 列的 CI 宽度")
        param_layout.addWidget(self.ci_level_spin, 1, 1)
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
        _gdr_names = [
            ('(-)' + defn.display_name) if defn.lower_is_better else defn.display_name
            for defn in _UNIFIED_GDR_REGISTRY.values()
        ]

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

        from gacha_simulator.gui.chart_webview import ChartWebView
        self.chart_webview = ChartWebView()
        self.chart_webview.setVisible(False)
        self.chart_webview.setMinimumHeight(800)
        self.chart_webview.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self._results_layout.addWidget(self.chart_webview)

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
        if key == 'gdr_statistics':
            cond['ci_level'] = self.ci_level_spin.value()
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

            pool_names = self._get_pool_names()
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
                pool_names=pool_names,
            )
            self._worker.progress.connect(self._on_progress)
            self._worker.finished.connect(self._on_analysis_done)
            self._worker.error.connect(self._on_analysis_error)
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

    def _on_analysis_error(self, err_msg):
        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.status_label.setText(f"分析失败：{err_msg[:100]}...")
        if self._placeholder_label:
            self._placeholder_label.setVisible(False)
        from PyQt6.QtWidgets import QMessageBox
        QMessageBox.critical(self, "分析异常", err_msg)

    def _on_analysis_done(self, charts):
        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY
        from gacha_simulator.visualization.chart_spec import ChartSpec
        key_to_display = {k: d.display_name for k, d in UNIFIED_GDR_REGISTRY.items()}

        # 收集所有 ChartSpec（表格已统一为 chart_type="table"）
        chart_specs = {}
        for key, data in charts.items():
            if isinstance(data, ChartSpec):
                chart_specs[key] = data

        # 图表型结果：使用 ChartWebView
        if chart_specs:
            self.chart_webview.setVisible(True)
            # 判断哪些 chart key 是全新的（HTML 中尚无对应 div）
            new_keys = {k for k in chart_specs if not self.chart_webview.has_chart(k)}
            if self._chart_webview_initialized and not new_keys:
                # 纯增量更新：所有 key 均已存在于 HTML 中，只更新数据
                for key, spec in chart_specs.items():
                    self.chart_webview.update_chart(key, spec)
                    self._computed_conditions[key] = self._get_conditions_for_key(key)
                self._chart_specs_cache.update(chart_specs)  # 同步缓存，避免后续全量重建时混入过期数据
            else:
                # 有新增图表或首次加载：合并到缓存后全量重建 HTML
                self._chart_specs_cache.update(chart_specs)
                self.chart_webview.set_charts(self._get_ordered_charts(), use_tabs=False)
                self._chart_webview_initialized = True
                for key in chart_specs:
                    self._computed_conditions[key] = self._get_conditions_for_key(key)

        if any(k.startswith('gdr_dist_') for k in charts):
            self._computed_conditions['gdr_dist'] = self._get_conditions_for_key('gdr_dist')
        if any(k.startswith('cumulative_by_pool_') for k in charts):
            self._computed_conditions['cumulative_by_pool'] = self._get_conditions_for_key('cumulative_by_pool')
        if any(k.startswith('risk_worst_case_') for k in charts):
            self._computed_conditions['risk_worst_case'] = self._get_conditions_for_key('risk_worst_case')
        if any(k.startswith('risk_best_case_') for k in charts):
            self._computed_conditions['risk_best_case'] = self._get_conditions_for_key('risk_best_case')
        if any(k.startswith('time_heatmap_') for k in charts):
            self._computed_conditions['time_heatmap'] = self._get_conditions_for_key('time_heatmap')
        if any(k.startswith('transition_analysis_') for k in charts):
            self._computed_conditions['transition_analysis'] = self._get_conditions_for_key('transition_analysis')

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
        chart_count = len(chart_specs)
        self.status_label.setText(f"完成，共 {chart_count} 个图表")

    def _compute_statistics_unit(self):
        if not self.results or not self._gdr_context:
            return

        from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY, compute_gdr_from_compact
        from gacha_simulator.core.bootstrap import BootstrapEngine
        import numpy as np

        target_specs = self._gdr_context.target_specs if self._gdr_context else {}
        ssr_ids = self._gdr_context.ssr_ids if self._gdr_context else set()

        alpha = self.alpha_spin.value()
        ci_level = self.ci_level_spin.value()
        ci_pct = f"{ci_level:.0%}"
        headers = [
            "指标",
            "均值", f"均值 {ci_pct} CI",
            "中位数", f"中位数 {ci_pct} CI",
            "标准差",
            f"VaR({alpha:.0%})", f"VaR {ci_pct} CI",
        ]
        rows = []
        self._summary_data = {}

        use_draw_units = self.draw_unit_cb.isChecked()
        cost_per_draw = self.cost_per_draw_spin.value()
        engine = BootstrapEngine(B=1000, ci_level=ci_level, random_seed=42)

        from gacha_simulator.core.distribution import EmpiricalDistribution
        for key, defn in UNIFIED_GDR_REGISTRY.items():
            try:
                vals = []
                for r in self.results:
                    v = compute_gdr_from_compact(r, target_specs, key, ssr_ids=ssr_ids)
                    vals.append(v)
                if key in _DRAW_UNIT_GDR_KEYS and use_draw_units and cost_per_draw > 0:
                    vals = [v / cost_per_draw for v in vals]
                n = len(vals)
                mean_val = np.mean(vals)
                median_val = np.median(vals)
                std_val = np.std(vals)
                var_val = EmpiricalDistribution(vals).var(alpha)
                _display_name = ('(-)' + defn.display_name) if defn.lower_is_better else defn.display_name
                if key in _DRAW_UNIT_GDR_KEYS and use_draw_units:
                    _display_name = f'{_display_name} (抽)'

                if n >= 100:
                    try:
                        mean_res = engine.bootstrap_mean(vals, use_bca=True)
                        mean_ci = f"[{mean_res.ci_lower:.4f}, {mean_res.ci_upper:.4f}]"
                    except Exception:
                        mean_ci = "—"

                    try:
                        median_res = engine.bootstrap_quantile(vals, q=0.5)
                        median_ci = f"[{median_res.ci_lower:.4f}, {median_res.ci_upper:.4f}]"
                    except Exception:
                        median_ci = "—"

                    try:
                        if alpha <= 0.1:
                            var_ci = "待实现"
                        else:
                            var_res = engine.bootstrap_quantile(vals, q=alpha, use_gpd=False)
                            var_ci = f"[{var_res.ci_lower:.4f}, {var_res.ci_upper:.4f}]"
                    except Exception:
                        var_ci = "—"
                else:
                    mean_ci = "样本不足"
                    median_ci = "样本不足"
                    var_ci = "样本不足"

                rows.append([
                    _display_name,
                    f"{mean_val:.4f}", mean_ci,
                    f"{median_val:.4f}", median_ci,
                    f"{std_val:.4f}",
                    f"{var_val:.4f}", var_ci,
                ])
                self._summary_data[_display_name] = {'mean': f"{mean_val:.4f}"}
            except Exception:
                _display_name = ('(-)' + defn.display_name) if defn.lower_is_better else defn.display_name
                if key in _DRAW_UNIT_GDR_KEYS and use_draw_units:
                    _display_name = f'{_display_name} (抽)'
                rows.append([_display_name, "-", "-", "-", "-", "-", "-", "-"])
                self._summary_data[_display_name] = {'mean': "-"}

        key = 'gdr_statistics'
        from gacha_simulator.visualization.chart_spec import TableData, ChartSpec
        spec = ChartSpec(
            chart_type="table",
            data=TableData(headers=headers, rows=rows),
            title='GDR 指标统计',
        )
        self._chart_specs_cache[key] = spec
        self.chart_webview.setVisible(True)
        if self._placeholder_label:
            self._placeholder_label.setVisible(False)
        self.chart_webview.set_charts(self._get_ordered_charts(), use_tabs=False)
        self._chart_webview_initialized = True
        self._computed_conditions[key] = self._get_conditions_for_key(key)

    def _get_ordered_charts(self) -> dict:
        """按 ANALYSIS_CATEGORIES 中定义的顺序排列图表缓存。

        扩展键（如 gdr_dist_xxx）排在父键（如 gdr_dist）附近。
        未在 CATEGORIES 中出现的键排在末尾。
        """
        cache = self._chart_specs_cache
        if not cache:
            return {}
        ordered: dict[str, object] = {}
        seen: set[str] = set()
        for base_key in _CHART_DISPLAY_ORDER:
            if base_key in cache:
                ordered[base_key] = cache[base_key]
                seen.add(base_key)
            prefix = base_key + '_'
            for k in sorted(cache):
                if k not in seen and k.startswith(prefix):
                    ordered[k] = cache[k]
                    seen.add(k)
        for k in cache:
            if k not in seen:
                ordered[k] = cache[k]
        return ordered

    def _clear_results(self):
        # 清除表格型结果帧（即除 placeholder_label 和 chart_webview 外的所有 widget）
        i = 0
        while i < self._results_layout.count():
            w = self._results_layout.itemAt(i).widget()
            if w is self._placeholder_label or w is self.chart_webview:
                i += 1
                continue
            self._results_layout.removeWidget(w)
            w.deleteLater()
            # 不递增 i，因为移除后下一个元素索引仍为 i
        # 隐藏并清理 chart_webview
        self.chart_webview.setVisible(False)
        self._chart_webview_initialized = False
        self._chart_specs_cache.clear()
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
