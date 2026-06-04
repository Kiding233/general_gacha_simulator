"""比较分析面板——多数据集 L1-L4 递进比较"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QComboBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QScrollArea, QGroupBox, QGridLayout, QSplitter, QFrame,
    QAbstractItemView, QDoubleSpinBox, QTabWidget,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor
import numpy as np

from gacha_simulator.core.comparison_analyzer import (
    DescriptiveStats, compute_gdr_values_for_datasets,
    compute_dominance_matrix, compute_pvalue_matrix,
    ParetoFrontier,
)
from gacha_simulator.core.gdr import UNIFIED_GDR_REGISTRY


class ComparisonAnalysisPanel(QWidget):
    """比较分析面板——L1-L4 递进分析"""

    status_update = pyqtSignal(str)

    def __init__(self, result_store, parent=None):
        super().__init__(parent)
        self._store = result_store
        self._dataset_names: list = []
        self._current_gdr_key = 'target_achievement'
        self._current_threshold = 1.0
        self._current_correction = 'BH'
        self._current_test_method = 'MWU'
        self._analysis_cache: dict = {}

        self._setup_ui()

    def _setup_ui(self):
        main_layout = QVBoxLayout(self)

        # —— 顶部控制栏 ——
        control_bar = QHBoxLayout()

        control_bar.addWidget(QLabel("GDR 指标"))
        self._gdr_combo = QComboBox()
        for key, defn in UNIFIED_GDR_REGISTRY.items():
            display = ('(-)' + defn.display_name) if defn.lower_is_better else defn.display_name
            self._gdr_combo.addItem(display, key)
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
        self._desc_table.setColumnCount(9)
        self._desc_table.setHorizontalHeaderLabels([
            "数据集", "均值", "中位数", "标准差", "偏度", "CVaR₀.₀₅", "成功率", "min", "max"
        ])
        self._desc_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self._desc_table.verticalHeader().setVisible(False)
        self._desc_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        l1_layout.addWidget(self._desc_table)

        self._l1_chart_tabs = QTabWidget()
        self._ecdf_placeholder = QLabel("ECDF 叠加图（Plotly 渲染待实现）")
        self._ecdf_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ecdf_placeholder.setMinimumHeight(200)
        self._pmf_placeholder = QLabel("PMF 叠加直方图（Plotly 渲染待实现）")
        self._pmf_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._pmf_placeholder.setMinimumHeight(200)
        self._l1_chart_tabs.addTab(self._ecdf_placeholder, "ECDF 叠加")
        self._l1_chart_tabs.addTab(self._pmf_placeholder, "PMF 叠加")
        l1_layout.addWidget(self._l1_chart_tabs)

        scroll_layout.addWidget(l1_group)

        # L2 随机占优
        l2_group = QGroupBox("L2 随机占优 (DD Bootstrap)")
        l2_layout = QHBoxLayout(l2_group)
        self._fsd_table = QLabel("FSD (j=1)\n待运行")
        self._fsd_table.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._fsd_table.setMinimumHeight(150)
        self._ssd_table = QLabel("SSD (j=2)\n待运行")
        self._ssd_table.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._ssd_table.setMinimumHeight(150)
        self._tsd_table = QLabel("TSD (j=3)\n待运行")
        self._tsd_table.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._tsd_table.setMinimumHeight(150)
        l2_layout.addWidget(self._fsd_table)
        l2_layout.addWidget(self._ssd_table)
        l2_layout.addWidget(self._tsd_table)
        scroll_layout.addWidget(l2_group)

        # L3 假设检验
        l3_group = QGroupBox("L3 假设检验")
        l3_layout = QVBoxLayout(l3_group)
        self._pvalue_table = QTableWidget()
        self._pvalue_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        l3_layout.addWidget(self._pvalue_table)
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

        self._l4_placeholder = QLabel("选择两个 GDR 指标后点击「计算前沿」")
        self._l4_placeholder.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._l4_placeholder.setMinimumHeight(200)
        l4_layout.addWidget(self._l4_placeholder)
        scroll_layout.addWidget(l4_group)

        # 填充 L4 combo
        for key, defn in UNIFIED_GDR_REGISTRY.items():
            display = defn.display_name
            self._l4_x_combo.addItem(display, key)
            self._l4_y_combo.addItem(display, key)
        # 默认 Y=target_achievement, X=resource_efficiency
        self._l4_x_combo.setCurrentIndex(0)
        idx_y = self._l4_y_combo.findData('resource_efficiency')
        if idx_y >= 0:
            self._l4_y_combo.setCurrentIndex(idx_y)

        scroll_layout.addStretch()
        scroll.setWidget(scroll_content)
        main_layout.addWidget(scroll)

    # —— 公共接口 ——
    def set_datasets(self, names: list):
        """设置要比较的数据集列表"""
        self._dataset_names = names
        self._analysis_cache.clear()
        ds_list = ', '.join(names)
        self.status_update.emit(f"已加载 {len(names)} 个数据集: {ds_list}")
        self._run_analysis()

    def _get_datasets(self):
        return [self._store.get(name) for name in self._dataset_names]

    # —— 参数变化 ——
    def _on_gdr_changed(self, idx):
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

        self._run_btn.setEnabled(False)
        self._run_btn.setText("计算中...")

        try:
            # 提取 GDR 值
            target_specs_list = [ds.target_specs for ds in datasets]
            values_list, names, lower_is_better = compute_gdr_values_for_datasets(
                datasets, self._current_gdr_key, target_specs_list, self._current_threshold
            )
            if not values_list:
                self.status_update.emit("无法计算 GDR 值")
                return

            self._update_l1(values_list, names, lower_is_better)
            self._update_l2(values_list, names)
            self._update_l3(values_list, names, lower_is_better)

            self.status_update.emit(f"分析完成: {len(names)} 个数据集, GDR={self._current_gdr_key}")
        finally:
            self._run_btn.setEnabled(True)
            self._run_btn.setText("运行分析")

    def _update_l1(self, values_list, names, lower_is_better):
        stats_list = [
            DescriptiveStats.compute(name, self._current_gdr_key, vals,
                                     self._current_threshold, lower_is_better)
            for name, vals in zip(names, values_list)
        ]

        self._desc_table.setRowCount(len(stats_list))
        for row, s in enumerate(stats_list):
            items = [
                s.name, f"{s.mean:.4f}", f"{s.median:.4f}", f"{s.std:.4f}",
                f"{s.skewness:.3f}", f"{s.cvar_05:.4f}", f"{s.success_rate:.1%}",
                f"{s.min_val:.4f}", f"{s.max_val:.4f}",
            ]
            for col, text in enumerate(items):
                self._desc_table.setItem(row, col, QTableWidgetItem(text))

    def _update_l2(self, values_list, names):
        results = []
        for order in [1, 2, 3]:
            dom = compute_dominance_matrix(values_list, names, order=order,
                                           n_bootstrap=2000)
            results.append((order, dom))

        labels = [self._fsd_table, self._ssd_table, self._tsd_table]
        for (order, dom), label in zip(results, labels):
            n = len(names)
            lines = [f"<b>{['FSD','SSD','TSD'][order-1]} (j={order})</b>", '<table>']
            lines.append('<tr><th></th>' + ''.join(f'<th>{name}</th>' for name in names) + '</tr>')
            for i in range(n):
                line = f'<tr><th>{names[i]}</th>'
                for j in range(n):
                    if i == j:
                        line += '<td>—</td>'
                    elif j > i:
                        p = dom['matrix'][i][j]
                        if p is not None:
                            color = '#4caf50' if p < 0.05 else '#999'
                            line += f'<td style="color:{color}">{p:.3f}</td>'
                        else:
                            line += '<td></td>'
                    else:
                        line += '<td></td>'
                line += '</tr>'
                lines.append(line)
            lines.append('</table>')
            label.setText(''.join(lines))

    def _update_l3(self, values_list, names, lower_is_better):
        pmat = compute_pvalue_matrix(
            values_list, names,
            method=self._current_test_method,
            lower_is_better=lower_is_better,
        )

        # 选择显示的矩阵
        if self._current_correction == 'BH':
            matrix = pmat['bh_matrix']
            title = 'BH 校正'
        elif self._current_correction == 'Holm':
            matrix = pmat['holm_matrix']
            title = 'Holm 校正'
        else:
            matrix = pmat['raw_matrix']
            title = '原始 p 值'

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
                            item.setBackground(QColor('#fce4ec'))
                            item.setForeground(QColor('#c62828'))
                        elif p < 0.05:
                            item.setBackground(QColor('#fff3e0'))
                            item.setForeground(QColor('#e65100'))
                    else:
                        item = QTableWidgetItem('—')
                else:
                    item = QTableWidgetItem('')
                self._pvalue_table.setItem(i, j + 1, item)
        self._pvalue_table.horizontalHeader().setSectionResizeMode(
            QHeaderView.ResizeMode.Stretch)

    def _run_l4(self):
        datasets = self._get_datasets()
        if len(datasets) < 2:
            return

        x_key = self._l4_x_combo.currentData()
        y_key = self._l4_y_combo.currentData()
        target_specs_list = [ds.target_specs for ds in datasets]

        x_vals, x_names, x_lib = compute_gdr_values_for_datasets(
            datasets, x_key, target_specs_list, self._current_threshold)
        y_vals, y_names, y_lib = compute_gdr_values_for_datasets(
            datasets, y_key, target_specs_list, self._current_threshold)

        if not x_vals or not y_vals:
            return

        pf = ParetoFrontier.compute(x_vals, y_vals, x_names, x_key, y_key, x_lib, y_lib)

        lines = [f"<b>帕累托前沿: {x_key} × {y_key}</b><br>"]
        lines.append("<b>前沿策略（非支配）:</b><br>")
        for idx in pf.frontier_indices:
            p = pf.points[idx]
            lines.append(f"• <b>{p['name']}</b>: x={p['x_raw']:.4f}, y={p['y_raw']:.4f}<br>")
        if pf.dominated_indices:
            lines.append("<br><b>被支配策略:</b><br>")
            for idx in pf.dominated_indices:
                p = pf.points[idx]
                lines.append(f"• <span style='color:#999;'>{p['name']}</span>: "
                             f"x={p['x_raw']:.4f}, y={p['y_raw']:.4f}<br>")
        self._l4_placeholder.setText(''.join(lines))
