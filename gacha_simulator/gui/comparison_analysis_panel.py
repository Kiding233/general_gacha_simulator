"""比较分析面板——多数据集 L1-L4 递进比较（后台线程 + Plotly 图表）"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QGroupBox, QAbstractItemView, QDoubleSpinBox,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
import numpy as np
import plotly.graph_objects as go

from gacha_simulator.core.comparison_analyzer import (
    DescriptiveStats, compute_gdr_values_for_datasets,
    compute_dominance_matrix, compute_pvalue_matrix,
    ParetoFrontier,
)
from gacha_simulator.core.gdr import get_expanded_gdr_entries
from gacha_simulator.gui.chart_webview import ChartWebView


class ComparisonWorker(QThread):
    """后台计算线程——L1 描述统计 + L2 随机占优 + L3 假设检验"""
    progress = pyqtSignal(str)
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, datasets, gdr_key, threshold, test_method, correction,
                 target_specs_list,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None, parent=None):
        super().__init__(parent)
        self._datasets = datasets
        self._gdr_key = gdr_key
        self._threshold = threshold
        self._test_method = test_method
        self._correction = correction
        self._target_specs_list = target_specs_list
        self._desire_weights = desire_weights
        self._miss_cost_weights = miss_cost_weights
        self._card_value_weights = card_value_weights

    def run(self):
        try:
            self.progress.emit("正在提取 GDR 值...")
            values_list, names, lower_is_better = compute_gdr_values_for_datasets(
                self._datasets, self._gdr_key, self._target_specs_list, self._threshold,
                desire_weights=self._desire_weights,
                miss_cost_weights=self._miss_cost_weights,
                card_value_weights=self._card_value_weights,
            )
            if not values_list or len(values_list) < 2:
                self.error.emit("无法计算 GDR 值或数据集不足")
                return

            self.progress.emit("L1 描述统计...")
            stats_list = [
                DescriptiveStats.compute(name, self._gdr_key, vals,
                                         self._threshold, lower_is_better)
                for name, vals in zip(names, values_list)
            ]

            self.progress.emit("L2 随机占优 (Bootstrap)...")
            dom_results = {}
            ordinal_label = {1: '一阶', 2: '二阶', 3: '三阶'}
            for order, label in [(1, 'FSD'), (2, 'SSD'), (3, 'TSD')]:
                self.progress.emit(f"L2 {label} ({ordinal_label[order]}) 计算中...")
                dom = compute_dominance_matrix(values_list, names, order=order,
                                               n_bootstrap=1000)
                dom_results[order] = dom

            self.progress.emit("L3 假设检验...")
            pmat = compute_pvalue_matrix(
                values_list, names,
                method=self._test_method,
                lower_is_better=lower_is_better,
            )

            self.progress.emit("分析完成")
            self.finished.emit({
                'values_list': values_list,
                'names': names,
                'lower_is_better': lower_is_better,
                'stats_list': stats_list,
                'dom_results': dom_results,
                'pmat': pmat,
                'correction': self._correction,
            })
        except Exception as e:
            import traceback
            traceback.print_exc()
            self.error.emit(str(e))


class ComparisonAnalysisPanel(QWidget):
    """比较分析面板——L1-L4 递进分析"""

    status_update = pyqtSignal(str)

    def __init__(self, result_store, parent=None):
        super().__init__(parent)
        self._store = result_store
        self._config_store = None
        self._dataset_names: list = []
        self._current_gdr_key = 'target_achievement'
        self._current_threshold = 1.0
        self._current_correction = 'BH'
        self._current_test_method = 'MWU'
        self._analysis_cache: dict = {}
        self._worker: ComparisonWorker | None = None
        self._last_results: dict | None = None

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # —— 顶部控制栏 ——
        control_bar = QHBoxLayout()

        control_bar.addWidget(QLabel("GDR 指标"))
        self._gdr_combo = QComboBox()
        _entries = get_expanded_gdr_entries(
            self._store.resource_defs if self._store and hasattr(self._store, 'resource_defs') else None
        )
        for key, display, lower_is_better, _thr in _entries:
            _d = ('(-)' + display) if lower_is_better else display
            self._gdr_combo.addItem(_d, key)
        self._gdr_combo.currentIndexChanged.connect(self._on_gdr_changed)
        control_bar.addWidget(self._gdr_combo)

        control_bar.addWidget(QLabel("阈值"))
        self._threshold_spin = QDoubleSpinBox()
        self._threshold_spin.setRange(0.0, 999999.0)
        self._threshold_spin.setValue(1.0)
        self._threshold_spin.setDecimals(3)
        self._threshold_spin.valueChanged.connect(self._on_params_changed)
        control_bar.addWidget(self._threshold_spin)

        control_bar.addWidget(QLabel("检验方法"))
        self._method_combo = QComboBox()
        self._method_combo.addItems(['MWU', 'KS', 'ttest'])
        self._method_combo.currentTextChanged.connect(self._on_params_changed)
        control_bar.addWidget(self._method_combo)

        control_bar.addWidget(QLabel("校正"))
        self._correction_combo = QComboBox()
        self._correction_combo.addItems(['BH (FDR)', 'Holm (FWER)', '原始 p 值'])
        self._correction_combo.currentTextChanged.connect(self._on_correction_changed)
        control_bar.addWidget(self._correction_combo)

        self._run_btn = QPushButton("运行分析")
        self._run_btn.setStyleSheet("background:#1976d2;color:#fff;padding:6px 16px;")
        self._run_btn.clicked.connect(self._run_analysis)
        control_bar.addWidget(self._run_btn)

        self._loading_label = QLabel("")
        self._loading_label.setStyleSheet("color:#1976d2;font-weight:bold;padding:4px 8px;")
        control_bar.addWidget(self._loading_label)

        control_bar.addStretch()
        main_layout.addLayout(control_bar)

        # —— 可滚动内容区 ——
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll_content = QWidget()
        scroll_layout = QVBoxLayout(scroll_content)

        # L1 描述统计
        l1_group = QGroupBox("L1 探索性分析")
        l1_layout = QVBoxLayout(l1_group)
        self._desc_table = QTableWidget()
        self._desc_table.setColumnCount(11)
        self._desc_table.setHorizontalHeaderLabels([
            "数据集", "均值", "中位数", "标准差", "偏度", "峰度", "VaR₀.₀₅", "CVaR₀.₀₅", "成功率", "min", "max"
        ])
        self._desc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._desc_table.verticalHeader().setVisible(False)
        self._desc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._desc_table.setMinimumHeight(180)
        self._desc_table.verticalHeader().setDefaultSectionSize(32)
        l1_layout.addWidget(self._desc_table)

        # Plotly 图表：ECDF + PMF 并排
        self._l1_chart_view = ChartWebView()
        self._l1_chart_view.setMinimumHeight(250)
        l1_layout.addWidget(self._l1_chart_view)

        scroll_layout.addWidget(l1_group)

        # L2 随机占优
        l2_group = QGroupBox("L2 随机占优 (DD Bootstrap)")
        l2_layout = QHBoxLayout(l2_group)
        self._fsd_label = QLabel("FSD (一阶)\n待运行")
        self._fsd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fsd_label.setMinimumHeight(100)
        self._fsd_label.setTextFormat(Qt.TextFormat.RichText)
        self._ssd_label = QLabel("SSD (二阶)\n待运行")
        self._ssd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ssd_label.setMinimumHeight(100)
        self._ssd_label.setTextFormat(Qt.TextFormat.RichText)
        self._tsd_label = QLabel("TSD (三阶)\n待运行")
        self._tsd_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tsd_label.setMinimumHeight(100)
        self._tsd_label.setTextFormat(Qt.TextFormat.RichText)
        l2_layout.addWidget(self._fsd_label)
        l2_layout.addWidget(self._ssd_label)
        l2_layout.addWidget(self._tsd_label)
        scroll_layout.addWidget(l2_group)

        # L3 假设检验
        l3_group = QGroupBox("L3 假设检验")
        l3_layout = QVBoxLayout(l3_group)
        self._pvalue_table = QTableWidget()
        self._pvalue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._pvalue_table.setMinimumHeight(250)
        self._pvalue_table.verticalHeader().setDefaultSectionSize(36)
        l3_layout.addWidget(self._pvalue_table)

        self._l3_legend = QLabel(
            '<span style="background:#c8e6c9;color:#1b5e20;padding:1px 6px;'
            'border-radius:2px;">p&lt;0.01</span> '
            '<span style="background:#e8f5e9;color:#2e7d32;padding:1px 6px;'
            'border-radius:2px;">p&lt;0.05</span> '
            '&nbsp; ↑ = 行优于列 &nbsp; ↓ = 行劣于列 &nbsp; — = 不显著'
        )
        self._l3_legend.setStyleSheet("font-size:11px;color:#888;margin-top:4px;")
        self._l3_legend.setWordWrap(True)
        l3_layout.addWidget(self._l3_legend)
        scroll_layout.addWidget(l3_group)

        # L4 帕累托前沿
        l4_group = QGroupBox("L4 帕累托前沿")
        l4_layout = QVBoxLayout(l4_group)
        l4_controls = QHBoxLayout()
        l4_controls.addWidget(QLabel("X轴 GDR:"))
        self._l4_x_combo = QComboBox()
        l4_controls.addWidget(self._l4_x_combo)
        l4_controls.addWidget(QLabel("Y轴 GDR:"))
        self._l4_y_combo = QComboBox()
        l4_controls.addWidget(self._l4_y_combo)
        self._l4_run_btn = QPushButton("计算前沿")
        self._l4_run_btn.clicked.connect(self._run_l4)
        l4_controls.addWidget(self._l4_run_btn)
        l4_controls.addStretch()
        l4_layout.addLayout(l4_controls)

        self._l4_chart_view = ChartWebView()
        self._l4_chart_view.setMinimumHeight(250)
        l4_layout.addWidget(self._l4_chart_view)
        scroll_layout.addWidget(l4_group)

        # 填充 L4 combo（支持多资源展开）
        _l4_entries = get_expanded_gdr_entries(
            self._store.resource_defs if self._store and hasattr(self._store, 'resource_defs') else None
        )
        for key, display, lower_is_better, _thr in _l4_entries:
            self._l4_x_combo.addItem(display, key)
            self._l4_y_combo.addItem(display, key)
        self._l4_x_combo.setCurrentIndex(0)
        # resource_efficiency:draw_resource 的 key 匹配
        idx_y = self._l4_y_combo.findData('resource_efficiency')
        if idx_y < 0:
            idx_y = self._l4_y_combo.findData('resource_efficiency:draw_resource')
        if idx_y >= 0:
            self._l4_y_combo.setCurrentIndex(idx_y)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

    # —— 公共接口 ——
    def set_config_store(self, config_store):
        """接收 ConfigStore —— 用于展开多资源类型 GDR 条目。

        _setup_ui 时仅有 ResultStore（无 resource_defs），
        此方法由 MainWindow 在 ConfigStore 就绪后调用。
        """
        self._config_store = config_store
        resource_defs = config_store.resource_defs if config_store else None
        if not resource_defs:
            return
        self._refresh_gdr_combo(resource_defs)
        self._refresh_l4_combos(resource_defs)

    def _refresh_gdr_combo(self, resource_defs):
        """用展开后的 GDR 条目重新填充主 GDR 下拉框。"""
        _entries = get_expanded_gdr_entries(resource_defs)
        old_key = self._gdr_combo.currentData()
        self._gdr_combo.blockSignals(True)
        self._gdr_combo.clear()
        for key, display, lower_is_better, _thr in _entries:
            _d = ('(-)' + display) if lower_is_better else display
            self._gdr_combo.addItem(_d, key)
        if old_key:
            idx = self._gdr_combo.findData(old_key)
            if idx >= 0:
                self._gdr_combo.setCurrentIndex(idx)
        self._gdr_combo.blockSignals(False)
        self._on_gdr_changed(self._gdr_combo.currentIndex())

    def _refresh_l4_combos(self, resource_defs):
        """用展开后的 GDR 条目重新填充 L4 散点图 X/Y 轴下拉框。"""
        _l4_entries = get_expanded_gdr_entries(resource_defs)
        self._l4_x_combo.blockSignals(True)
        self._l4_y_combo.blockSignals(True)
        self._l4_x_combo.clear()
        self._l4_y_combo.clear()
        for key, display, lower_is_better, _thr in _l4_entries:
            self._l4_x_combo.addItem(display, key)
            self._l4_y_combo.addItem(display, key)
        self._l4_x_combo.setCurrentIndex(0)
        idx_y = self._l4_y_combo.findData('resource_efficiency')
        if idx_y < 0:
            idx_y = self._l4_y_combo.findData('resource_efficiency:draw_resource')
        if idx_y >= 0:
            self._l4_y_combo.setCurrentIndex(idx_y)
        self._l4_x_combo.blockSignals(False)
        self._l4_y_combo.blockSignals(False)

    def set_datasets(self, names: list):
        """设置要比较的数据集列表"""
        self._dataset_names = names
        self._analysis_cache.clear()
        self._last_results = None
        ds_list = ', '.join(names)
        self.status_update.emit(f"已加载 {len(names)} 个数据集: {ds_list}")
        self._run_analysis()

    def _get_datasets(self):
        return [self._store.get(name) for name in self._dataset_names]

    # —— 参数变化 ——
    def _on_gdr_changed(self, idx):
        if idx < 0:
            return
        self._current_gdr_key = self._gdr_combo.itemData(idx)
        self._on_params_changed()

    def _on_params_changed(self, *_):
        self._current_threshold = self._threshold_spin.value()
        self._current_test_method = self._method_combo.currentText()
        self._analysis_cache.clear()

    def _on_correction_changed(self, text):
        if 'BH' in text:
            self._current_correction = 'BH'
        elif 'Holm' in text:
            self._current_correction = 'Holm'
        else:
            self._current_correction = 'raw'

    # —— 运行分析 ——
    def _run_analysis(self):
        datasets = self._get_datasets()
        if len(datasets) < 2:
            return

        target_specs_list = [ds.target_specs for ds in datasets]

        self._run_btn.setEnabled(False)
        self._run_btn.setText("计算中...")
        self._loading_label.setText("⏳ 正在后台计算...")

        self._worker = ComparisonWorker(
            datasets, self._current_gdr_key, self._current_threshold,
            self._current_test_method, self._current_correction,
            target_specs_list,
            desire_weights=self._config_store.desire_weights if self._config_store else None,
            miss_cost_weights=self._config_store.miss_cost_weights if self._config_store else None,
            card_value_weights=self._config_store.card_value_weights if self._config_store else None,
        )
        self._worker.progress.connect(self._on_worker_progress)
        self._worker.finished.connect(self._on_analysis_finished)
        self._worker.error.connect(self._on_worker_error)
        self._worker.start()

    def _on_worker_progress(self, msg: str):
        self._loading_label.setText(f"⏳ {msg}")
        self.status_update.emit(msg)

    def _on_analysis_finished(self, results: dict):
        self._run_btn.setEnabled(True)
        self._run_btn.setText("运行分析")
        try:
            self._last_results = results
            names = results['names']
            values_list = results['values_list']
            lower_is_better = results['lower_is_better']

            self._update_l1(results['stats_list'], values_list, names, lower_is_better)
            self._update_l2(results['dom_results'], names)
            self._update_l3(results['pmat'], names, results['correction'])

            self._loading_label.setText("✓ 完成")
            self.status_update.emit(f"分析完成: {len(names)} 个数据集, GDR={self._current_gdr_key}")
        except Exception:
            import traceback
            traceback.print_exc()
            self.status_label.setText("结果展示失败，请查看控制台")

    def _on_worker_error(self, msg: str):
        self._run_btn.setEnabled(True)
        self._run_btn.setText("运行分析")
        self._loading_label.setText(f"✗ 错误: {msg}")
        self.status_update.emit(f"分析失败: {msg}")

    # —— L1 更新 ——
    def _update_l1(self, stats_list, values_list, names, lower_is_better):
        self._desc_table.setRowCount(len(stats_list))
        for row, s in enumerate(stats_list):
            items = [
                s.name, f"{s.mean:.4f}", f"{s.median:.4f}", f"{s.std:.4f}",
                f"{s.skewness:.3f}", f"{s.kurtosis:.3f}", f"{s.var_05:.4f}",
                f"{s.cvar_05:.4f}", f"{s.success_rate:.1%}",
                f"{s.min_val:.4f}", f"{s.max_val:.4f}",
            ]
            for col, text in enumerate(items):
                self._desc_table.setItem(row, col, QTableWidgetItem(text))

        # —— Plotly ECDF + PMF 图表 ——
        self._render_l1_charts(values_list, names, lower_is_better)

    def _render_l1_charts(self, values_list, names, lower_is_better):
        """构建 PMF (左) + ECDF (右) 并排 Plotly 图表"""
        from plotly.subplots import make_subplots
        from gacha_simulator.core.gdr_binning import compute_bins

        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        fig = make_subplots(
            rows=1, cols=2,
            subplot_titles=("PMF 叠加 (概率密度)", "ECDF 叠加"),
            horizontal_spacing=0.08,
        )

        # 合并各组样本，统一判定分箱策略
        all_vals = np.concatenate(values_list)
        bin_result = compute_bins(self._current_gdr_key, all_vals,
                                  cost_per_draw=None)  # 比较分析面板无可用的 cost_per_draw

        if bin_result.bar_mode:
            # 柱状图模式：各组共享 bar_x，各自用 bin_edges 计数
            for i, (vals, name) in enumerate(zip(values_list, names)):
                color = colors[i % len(colors)]
                counts, _ = np.histogram(vals, bins=bin_result.bin_edges)
                fig.add_trace(go.Bar(
                    x=bin_result.bar_x, y=counts,
                    name=name, marker_color=color,
                    opacity=0.7,
                    hovertemplate=f"{name}<br>值: %{{x:.4f}}<br>频数: %{{y}}<extra></extra>",
                    legendgroup=name,
                ), row=1, col=1)
        else:
            # 连续模式：共享 bin_edges，各组 go.Histogram
            bin_edges = bin_result.bin_edges
            if bin_edges is not None:
                bin_size = bin_edges[1] - bin_edges[0]
                xbins = dict(start=bin_edges[0], end=bin_edges[-1], size=bin_size)
            else:
                xbins = None

            for i, (vals, name) in enumerate(zip(values_list, names)):
                color = colors[i % len(colors)]
                hist_kwargs = dict(
                    x=vals,
                    histnorm='probability density',
                    name=name, marker_color=color, opacity=0.55,
                    hovertemplate=f"{name}<br>值: %{{x:.4f}}<br>密度: %{{y:.4f}}<extra></extra>",
                    legendgroup=name,
                )
                if xbins is not None:
                    hist_kwargs["xbins"] = xbins
                elif bin_result._extra.get("nbins"):
                    hist_kwargs["nbinsx"] = bin_result._extra["nbins"]
                fig.add_trace(go.Histogram(**hist_kwargs), row=1, col=1)

        # ECDF 曲线（bar_mode 和连续模式均渲染）
        for i, (vals, name) in enumerate(zip(values_list, names)):
            color = colors[i % len(colors)]
            sorted_vals = np.sort(vals)
            n_ecdf = len(sorted_vals)
            y_ecdf = np.arange(1, n_ecdf + 1) / n_ecdf
            fig.add_trace(go.Scatter(
                x=sorted_vals, y=y_ecdf, mode='lines', name=name,
                line=dict(color=color, width=2),
                hovertemplate=f"{name}<br>x: %{{x:.4f}}<br>P: %{{y:.3f}}<extra></extra>",
                legendgroup=name,
            ), row=1, col=2)

        fig.update_layout(
            template="plotly_white",
            font_family="Microsoft YaHei, PingFang SC, sans-serif",
            margin=dict(l=50, r=20, t=50, b=40),
            hovermode="x unified",
            barmode='overlay',
            bargap=0.05,
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="center", x=0.5),
        )
        _ylabel = "频数" if bin_result.bar_mode else "密度"
        fig.update_yaxes(title_text=_ylabel, fixedrange=True, row=1, col=1)
        fig.update_yaxes(title_text="累积概率", range=[0, 1.02], fixedrange=True, row=1, col=2)
        fig.update_xaxes(title_text="GDR 值", row=1, col=1)
        fig.update_xaxes(title_text="GDR 值", row=1, col=2)

        self._l1_chart_view.set_charts({"分布对比": fig}, use_tabs=False)

    # —— L2 更新 ——
    def _update_l2(self, dom_results, names):
        ordinal = {1: '一', 2: '二', 3: '三'}
        labels_map = {1: (self._fsd_label, 'FSD'), 2: (self._ssd_label, 'SSD'), 3: (self._tsd_label, 'TSD')}
        for order, (label_widget, title) in labels_map.items():
            dom = dom_results[order]
            n = len(names)
            lines = [f"<b>{title} ({ordinal[order]}阶)</b>",
                     '<table style="border-collapse:collapse;width:100%;text-align:center;'
                     'font-size:12px;">']
            lines.append('<tr style="background:#e9ecef;">'
                        '<th style="border:1px solid #ccc;padding:4px 8px;"></th>'
                        + ''.join(f'<th style="border:1px solid #ccc;padding:4px 8px;">{name}</th>'
                                  for name in names) + '</tr>')
            for i in range(n):
                line = f'<tr><th style="border:1px solid #ccc;padding:4px 8px;background:#f8f9fa;">{names[i]}</th>'
                for j in range(n):
                    if i == j:
                        line += ('<td style="border:1px solid #ccc;padding:4px 8px;'
                                'color:#ccc;">—</td>')
                    else:
                        p = dom['matrix'][i][j]
                        if p is not None:
                            color = '#2e7d32' if p < 0.05 else '#666'
                            bg = '#e8f5e9' if p < 0.05 else '#fff'
                            line += (f'<td style="border:1px solid #ccc;padding:4px 8px;'
                                    f'color:{color};background:{bg}">{p:.3f}</td>')
                        else:
                            line += '<td style="border:1px solid #ccc;padding:4px 8px;"></td>'
                line += '</tr>'
                lines.append(line)
            lines.append('</table>')
            lines.append(
                '<p style="font-size:11px;color:#888;margin-top:6px;">'
                '<span style="background:#e8f5e9;color:#2e7d32;padding:1px 6px;'
                'border-radius:2px;">p&lt;0.05</span> = 行 ' + ordinal[order] + '阶随机占优列 '
                '| 灰色 = 不显著</p>'
            )
            label_widget.setText(''.join(lines))

    # —— L3 更新 ——
    def _update_l3(self, pmat, names, correction):
        if correction == 'BH':
            matrix = pmat['bh_matrix']
        elif correction == 'Holm':
            matrix = pmat['holm_matrix']
        else:
            matrix = pmat['raw_matrix']

        direction = pmat['direction_matrix']
        n = len(names)

        self._pvalue_table.setRowCount(n)
        self._pvalue_table.setColumnCount(n + 1)
        self._pvalue_table.setHorizontalHeaderLabels([''] + names)
        self._pvalue_table.verticalHeader().setVisible(False)

        for i in range(n):
            self._pvalue_table.setItem(i, 0, QTableWidgetItem(names[i]))
            for j in range(n):
                if i == j:
                    item = QTableWidgetItem('—')
                    item.setForeground(QColor('#ccc'))
                elif j > i:
                    p = matrix[i][j]
                    d = direction[i][j]
                    if p is not None:
                        display = f"{d} {p:.3f}"
                        item = QTableWidgetItem(display)
                        if p < 0.01:
                            item.setBackground(QColor('#c8e6c9'))
                            item.setForeground(QColor('#1b5e20'))
                        elif p < 0.05:
                            item.setBackground(QColor('#e8f5e9'))
                            item.setForeground(QColor('#2e7d32'))
                    else:
                        item = QTableWidgetItem('—')
                else:
                    item = QTableWidgetItem('')
                self._pvalue_table.setItem(i, j + 1, item)
        self._pvalue_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)

    # —— L4 帕累托前沿 ——
    def _run_l4(self):
        datasets = self._get_datasets()
        if len(datasets) < 2:
            return

        x_key = self._l4_x_combo.currentData()
        y_key = self._l4_y_combo.currentData()
        target_specs_list = [ds.target_specs for ds in datasets]

        x_vals, x_names, x_lib = compute_gdr_values_for_datasets(
            datasets, x_key, target_specs_list, self._current_threshold,
            desire_weights=self._config_store.desire_weights if self._config_store else None,
            miss_cost_weights=self._config_store.miss_cost_weights if self._config_store else None,
            card_value_weights=self._config_store.card_value_weights if self._config_store else None,
        )
        y_vals, y_names, y_lib = compute_gdr_values_for_datasets(
            datasets, y_key, target_specs_list, self._current_threshold,
            desire_weights=self._config_store.desire_weights if self._config_store else None,
            miss_cost_weights=self._config_store.miss_cost_weights if self._config_store else None,
            card_value_weights=self._config_store.card_value_weights if self._config_store else None,
        )

        if not x_vals or not y_vals:
            self._l4_chart_view.show_message("无法计算帕累托前沿：数据不足")
            return

        pf = ParetoFrontier.compute(x_vals, y_vals, x_names, x_key, y_key, x_lib, y_lib)

        # 构建 Plotly 散点图
        colors = ['#1f77b4', '#ff7f0e', '#2ca02c', '#d62728', '#9467bd',
                  '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf']

        fig = go.Figure()

        for i, pt in enumerate(pf.points):
            is_frontier = i in pf.frontier_indices
            color = colors[i % len(colors)]
            marker_size = 14 if is_frontier else 9
            marker_symbol = 'circle' if is_frontier else 'circle-open'
            opacity = 1.0 if is_frontier else 0.55

            fig.add_trace(go.Scatter(
                x=[pt['x_raw']], y=[pt['y_raw']],
                mode='markers+text',
                name=pt['name'],
                text=[pt['name']],
                textposition='top center',
                textfont=dict(size=10, color=color if is_frontier else '#999'),
                marker=dict(
                    size=marker_size, color=color,
                    symbol=marker_symbol,
                    line=dict(width=1.5 if is_frontier else 0.5, color=color),
                    opacity=opacity,
                ),
                error_x=dict(
                    type='data', array=[pt['x_std']], visible=True,
                    color=color, thickness=1, width=0,
                ),
                error_y=dict(
                    type='data', array=[pt['y_std']], visible=True,
                    color=color, thickness=1, width=0,
                ),
                hovertemplate=(
                    f"<b>{pt['name']}</b><br>"
                    f"{x_key}: %{{x:.4f}} ± %{{error_x.array:.4f}}<br>"
                    f"{y_key}: %{{y:.4f}} ± %{{error_y.array:.4f}}<br>"
                    f"{'<b>前沿</b>' if is_frontier else '被支配'}"
                    "<extra></extra>"
                ),
                showlegend=False,
            ))

        # 前沿连线
        frontier_pts = sorted(
            [pf.points[i] for i in pf.frontier_indices],
            key=lambda p: p['x_raw']
        )
        if len(frontier_pts) >= 2:
            fig.add_trace(go.Scatter(
                x=[p['x_raw'] for p in frontier_pts],
                y=[p['y_raw'] for p in frontier_pts],
                mode='lines',
                name='帕累托前沿',
                line=dict(color='#333', width=1.5, dash='dash'),
                hovertemplate='前沿连线<extra></extra>',
                showlegend=False,
            ))

        fig.update_layout(
            title=f"帕累托前沿: {x_key} × {y_key}",
            xaxis_title=x_key,
            yaxis_title=y_key,
            template="plotly_white",
            font_family="Microsoft YaHei, PingFang SC, sans-serif",
            margin=dict(l=60, r=20, t=50, b=50),
            hovermode="closest",
        )

        # 反转 lower_is_better 轴的显示
        if x_lib:
            fig.update_xaxes(autorange="reversed")
        if y_lib:
            fig.update_yaxes(autorange="reversed")

        self._l4_chart_view.set_charts({"帕累托前沿": fig}, use_tabs=False)
