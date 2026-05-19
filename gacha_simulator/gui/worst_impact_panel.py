import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QRadioButton, QButtonGroup, QComboBox, QSizePolicy,
    QSplitter, QLineEdit, QCheckBox, QScrollArea,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
from gacha_simulator.core.gdr import populate_gdr_combo, get_default_threshold, UNIFIED_GDR_REGISTRY
from .config_panel import PoolDistributionDialog


class CoverageBar(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedHeight(22)
        self._pct = 0.0
        self._marker_pct = 0.0
        self._color = QColor("#27ae60")

    def set_values(self, pct, marker_pct, color_hex):
        self._pct = pct
        self._marker_pct = marker_pct
        self._color = QColor(color_hex)
        self.update()

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        w = self.width()
        h = self.height()

        painter.setPen(QPen(QColor("#ccc"), 1))
        painter.setBrush(QColor("#eee"))
        painter.drawRoundedRect(0, 0, w - 1, h - 1, 4, 4)

        fill_w = int((w - 2) * min(self._pct, 1.0))
        if fill_w > 0:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(self._color)
            painter.drawRoundedRect(1, 1, fill_w, h - 2, 3, 3)

        mx = 1 + int((w - 2) * min(self._marker_pct, 1.0))
        pen = QPen(QColor("#e74c3c"), 2)
        painter.setPen(pen)
        painter.drawLine(mx, 1, mx, h - 2)

        painter.setPen(QColor("#e74c3c"))
        font = painter.font()
        font.setPixelSize(10)
        painter.setFont(font)
        text_x = min(mx + 3, w - 30)
        painter.drawText(text_x, h - 5, "1x")
        painter.end()


class PityCoverageGauge(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(8, 4, 8, 4)
        layout.setSpacing(2)

        self.value_label = QLabel("--")
        self.value_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.value_label.setStyleSheet("font-size: 28px; font-weight: bold; color: #2c3e50;")
        layout.addWidget(self.value_label)

        self.desc_label = QLabel("大保底覆盖倍数")
        self.desc_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.desc_label.setStyleSheet("font-size: 11px; color: #888;")
        layout.addWidget(self.desc_label)

        self.bar = CoverageBar()
        layout.addWidget(self.bar)

        self.detail_label = QLabel("")
        self.detail_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.detail_label.setStyleSheet("font-size: 11px; color: #555;")
        layout.addWidget(self.detail_label)

        layout.addStretch()

    def set_value(self, coverage: float):
        self.value_label.setText(f"{coverage:.2f}x")

        max_display = max(coverage * 1.3, 2.0)
        pct = coverage / max_display
        marker_pct = 1.0 / max_display

        if coverage >= 1.0:
            color = "#27ae60"
            hint = "足够1次保底"
        elif coverage >= 0.5:
            color = "#f39c12"
            hint = "不足1次保底"
        else:
            color = "#e74c3c"
            hint = "远不足1次保底"

        self.bar.set_values(pct, marker_pct, color)

        self.detail_label.setText(
            f"覆盖 {coverage:.2f} 倍大保底  |  {hint}"
        )


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
        self._custom_distribution = None
        self._gdr_checkboxes = {}
        self._results = {}
        self._setup_ui()

    def set_store(self, store):
        self._store = store
        self._load_last_pool_config()

    def set_simulation_results(self, results, target_specs=None):
        self._simulation_results = results
        self._target_specs = target_specs
        if results:
            self.status_label.setText(f"已接收 {len(results)} 条模拟结果")

    def _load_last_pool_config(self):
        if not self._store:
            return
        pool_entries = [pe for pe in self._store.pools if pe.enabled]
        if not pool_entries:
            return
        pe = pool_entries[-1]
        self.pool_duration_spin.setValue(pe.end_day - pe.start_day or 21)
        self.pool_cost_edit.setText(getattr(pe, 'cost', 'draw_resource:160'))
        dist_data = []
        for de in pe.distribution:
            dist_data.append({
                'card_id': de.card_id,
                'probability': de.probability,
                'rarity': de.rarity,
                'featured': de.featured,
                'resources_gained': dict(de.resources_gained) if de.resources_gained else {},
            })
        self._custom_distribution = dist_data
        self._update_dist_summary()

    def _update_dist_summary(self):
        if not self._custom_distribution:
            self.dist_summary_label.setText("未配置")
            return
        n = len(self._custom_distribution)
        total = sum(d.get('probability', 0) for d in self._custom_distribution)
        ssr = sum(1 for d in self._custom_distribution if d.get('rarity', '').upper() == 'SSR')
        self.dist_summary_label.setText(f"{n}卡 | SSR {ssr} | 合计 {total:.1f}%")

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left = QWidget()
        left_layout = QVBoxLayout(left)

        config_group = QGroupBox("分析配置")
        config_form = QFormLayout(config_group)

        self.cond_all = QRadioButton("全部")
        self.cond_success = QRadioButton("成功")
        self.cond_failure = QRadioButton("失败")
        self.cond_btn_group = QButtonGroup(self)
        for btn in [self.cond_all, self.cond_success, self.cond_failure]:
            self.cond_btn_group.addButton(btn)
        self.cond_success.setChecked(True)
        cond_layout = QHBoxLayout()
        cond_layout.addWidget(self.cond_all)
        cond_layout.addWidget(self.cond_success)
        cond_layout.addWidget(self.cond_failure)
        config_form.addRow("条件:", cond_layout)

        # GDR多选区域
        gdr_select_group = QGroupBox("广义出率指标")
        gdr_select_layout = QVBoxLayout(gdr_select_group)
        gdr_select_layout.setSpacing(2)
        gdr_select_layout.setContentsMargins(4, 4, 4, 4)

        gdr_btn_layout = QHBoxLayout()
        select_all_btn = QPushButton("全选")
        select_all_btn.setFixedHeight(22)
        select_all_btn.setStyleSheet("font-size: 10px;")
        select_all_btn.clicked.connect(self._select_all_gdr)
        gdr_btn_layout.addWidget(select_all_btn)
        deselect_all_btn = QPushButton("全不选")
        deselect_all_btn.setFixedHeight(22)
        deselect_all_btn.setStyleSheet("font-size: 10px;")
        deselect_all_btn.clicked.connect(self._deselect_all_gdr)
        gdr_btn_layout.addWidget(deselect_all_btn)
        gdr_btn_layout.addStretch()
        gdr_select_layout.addLayout(gdr_btn_layout)

        self._gdr_checks_widget = QWidget()
        self._gdr_checks_layout = QVBoxLayout(self._gdr_checks_widget)
        self._gdr_checks_layout.setSpacing(2)
        self._gdr_checks_layout.setContentsMargins(0, 0, 0, 0)

        for key, defn in UNIFIED_GDR_REGISTRY.items():
            cb = QCheckBox(defn.display_name)
            cb.setStyleSheet("font-size: 11px;")
            self._gdr_checkboxes[key] = cb
            self._gdr_checks_layout.addWidget(cb)

        # 默认选中第一个
        first_key = list(UNIFIED_GDR_REGISTRY.keys())[0] if UNIFIED_GDR_REGISTRY else None
        if first_key and first_key in self._gdr_checkboxes:
            self._gdr_checkboxes[first_key].setChecked(True)

        gdr_select_layout.addWidget(self._gdr_checks_widget)
        config_form.addRow(gdr_select_group)

        self.gdr_threshold_spin = QDoubleSpinBox()
        self.gdr_threshold_spin.setRange(-9999999.0, 9999999.0)
        self.gdr_threshold_spin.setSingleStep(0.05)
        self.gdr_threshold_spin.setValue(1.0)
        self.gdr_threshold_spin.setDecimals(2)
        config_form.addRow("成功阈值:", self.gdr_threshold_spin)

        self.alpha_spin = QDoubleSpinBox()
        self.alpha_spin.setRange(0.01, 0.5)
        self.alpha_spin.setSingleStep(0.01)
        self.alpha_spin.setValue(0.05)
        self.alpha_spin.setDecimals(2)
        config_form.addRow("保守分位数 α:", self.alpha_spin)

        self.sim_spin = QSpinBox()
        self.sim_spin.setRange(50, 100000)
        self.sim_spin.setSingleStep(100)
        self.sim_spin.setValue(1000)
        config_form.addRow("模拟次数:", self.sim_spin)

        left_layout.addWidget(config_group)

        pool_group = QGroupBox("后续池子配置")
        pool_form = QFormLayout(pool_group)

        self.pool_duration_spin = QSpinBox()
        self.pool_duration_spin.setRange(1, 365)
        self.pool_duration_spin.setValue(21)
        pool_form.addRow("持续(天):", self.pool_duration_spin)

        self.pool_cost_edit = QLineEdit("draw_resource:160")
        pool_form.addRow("单抽消耗:", self.pool_cost_edit)

        dist_row = QHBoxLayout()
        self.dist_summary_label = QLabel("未配置")
        self.dist_summary_label.setStyleSheet("font-size: 11px; color: #555;")
        dist_row.addWidget(self.dist_summary_label, 1)
        edit_dist_btn = QPushButton("编辑分布")
        edit_dist_btn.clicked.connect(self._edit_distribution)
        dist_row.addWidget(edit_dist_btn)
        pool_form.addRow("卡牌分布:", dist_row)

        left_layout.addWidget(pool_group)

        self.run_btn = QPushButton("开始分析")
        self.run_btn.clicked.connect(self._on_run)
        left_layout.addWidget(self.run_btn)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("请先运行批量模拟")
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

        right = QScrollArea()
        right.setWidgetResizable(True)
        right.setStyleSheet("QScrollArea { background: #f5f5f5; border: none; }")

        self._results_container = QWidget()
        self._results_container.setStyleSheet("background: #f5f5f5;")
        self._results_layout = QVBoxLayout(self._results_container)
        self._results_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self._results_layout.setSpacing(12)
        self._results_layout.setContentsMargins(8, 8, 8, 8)

        self._placeholder_label = QLabel("请选择GDR指标并点击\"开始分析\"")
        self._placeholder_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._placeholder_label.setStyleSheet("color: #999; font-size: 14px; padding: 40px;")
        self._results_layout.addWidget(self._placeholder_label)

        right.setWidget(self._results_container)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 700])

    def _select_all_gdr(self):
        for cb in self._gdr_checkboxes.values():
            cb.setChecked(True)

    def _deselect_all_gdr(self):
        for cb in self._gdr_checkboxes.values():
            cb.setChecked(False)

    def _get_selected_gdr_keys(self):
        return [key for key, cb in self._gdr_checkboxes.items() if cb.isChecked()]

    def _edit_distribution(self):
        pool_id = '_worst_impact_pool'
        dist_data = self._custom_distribution or []
        dlg = PoolDistributionDialog(pool_id, dist_data, self)
        if dlg.exec() == PoolDistributionDialog.DialogCode.Accepted:
            self._custom_distribution = dlg.get_distribution()
            self._update_dist_summary()

    def _on_run(self):
        if not self._simulation_results:
            self.status_label.setText("请先运行批量模拟")
            return

        if not self._target_specs:
            self.status_label.setText("缺少目标卡规格，请重新运行批量模拟")
            return

        selected_gdrs = self._get_selected_gdr_keys()
        if not selected_gdrs:
            self.status_label.setText("请至少选择一个GDR指标")
            return

        if self.cond_success.isChecked():
            condition = 'success'
        elif self.cond_failure.isChecked():
            condition = 'failure'
        else:
            condition = 'all'

        gdr_threshold = self.gdr_threshold_spin.value()

        custom_pool = {
            'duration_days': self.pool_duration_spin.value(),
            'cost': self.pool_cost_edit.text().strip(),
            'distribution': self._custom_distribution or [],
        }

        from ..core.worst_impact import WorstImpactAnalyzer

        desire_weights = None
        miss_cost_weights = None
        card_value_weights = None
        main_window = self.window()
        if hasattr(main_window, 'config_panel'):
            desire_weights = main_window.config_panel.get_desire_weights()
            miss_cost_weights = main_window.config_panel.get_miss_cost_weights()
            card_value_weights = main_window.config_panel.get_card_value_weights()

        self._results = {}
        self._pending_gdrs = selected_gdrs.copy()
        self._condition = condition
        self._gdr_threshold = gdr_threshold
        self._custom_pool = custom_pool
        self._desire_weights = desire_weights
        self._miss_cost_weights = miss_cost_weights
        self._card_value_weights = card_value_weights

        self._clear_results()
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)
        self._run_next_gdr()

    def _run_next_gdr(self):
        if not self._pending_gdrs:
            self.run_btn.setEnabled(True)
            self.status_label.setText(f"完成，分析了 {len(self._results)} 个GDR指标")
            self.status_update.emit("最差后期影响分析完成")
            return

        gdr_key = self._pending_gdrs.pop(0)
        self._current_gdr = gdr_key

        from ..core.worst_impact import WorstImpactAnalyzer

        analyzer = WorstImpactAnalyzer(
            simulation_results=self._simulation_results,
            target_specs=self._target_specs,
            store=self._store,
            gdr_key=gdr_key,
            gdr_threshold=self._gdr_threshold,
            custom_pool_config=self._custom_pool,
            desire_weights=self._desire_weights,
            miss_cost_weights=self._miss_cost_weights,
            card_value_weights=self._card_value_weights,
        )

        self._worker = WorstImpactWorker(
            analyzer, self._condition,
            self.alpha_spin.value(),
            self.sim_spin.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(lambda result, key=gdr_key: self._on_gdr_finished(result, key))
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_progress(self, msg, pct):
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"[{self._current_gdr}] {msg}")
        self.status_update.emit(msg)

    def _on_gdr_finished(self, result, gdr_key):
        self._results[gdr_key] = result
        self._add_result_widget(gdr_key, result)
        self._run_next_gdr()

    def _on_finished(self, result):
        pass

    def _clear_results(self):
        while self._results_layout.count():
            item = self._results_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

    def _add_result_widget(self, gdr_key, result):
        defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
        gdr_name = defn.display_name if defn else gdr_key

        widget = QWidget()
        widget.setStyleSheet("background: white; border-radius: 6px; padding: 4px;")
        layout = QVBoxLayout(widget)
        layout.setSpacing(6)
        layout.setContentsMargins(8, 8, 8, 8)

        title = QLabel(f"<b>{gdr_name}</b>")
        title.setStyleSheet("font-size: 14px; color: #2c3e50;")
        layout.addWidget(title)

        summary = QLabel(
            f"保守资源: <b>{result.worst_resource:.0f}</b> | "
            f"大保底覆盖: <b>{result.pity_coverage:.2f}</b> 倍" +
            (f" | 期望新池子数: <b>{result.expected_pools:.2f}</b>" if result.pool_distribution else "")
        )
        summary.setWordWrap(True)
        summary.setStyleSheet("font-size: 12px; color: #555;")
        layout.addWidget(summary)

        if result.pool_distribution:
            chart_label = QLabel()
            chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
            chart_label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
            chart_label.setMinimumHeight(200)
            layout.addWidget(chart_label)

            pixmap = self._create_chart_pixmap(result, gdr_name)
            if pixmap and not pixmap.isNull():
                chart_label.setPixmap(pixmap)

            table = QTableWidget()
            table.setColumnCount(5)
            table.setHorizontalHeaderLabels(["k", "P(X=k)", "P(X>=k)", "累计概率", "说明"])
            table.setMaximumHeight(150)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
            table.verticalHeader().setVisible(False)

            table.setRowCount(len(result.pool_distribution))
            cumulative = 0.0
            for i, (k, prob) in enumerate(sorted(result.pool_distribution.items())):
                table.setItem(i, 0, QTableWidgetItem(str(k)))
                table.setItem(i, 1, QTableWidgetItem(f"{prob:.2%}"))
                p_ge = result.get_p_ge(k)
                table.setItem(i, 2, QTableWidgetItem(f"{p_ge:.2%}"))
                cumulative += prob
                table.setItem(i, 3, QTableWidgetItem(f"{cumulative:.2%}"))
                table.setItem(i, 4, QTableWidgetItem(f"成功{k}个新池子" if k > 0 else "未成功"))
            layout.addWidget(table)

        self._results_layout.addWidget(widget)

    def _create_chart_pixmap(self, result, gdr_name):
        if not result.pool_distribution:
            return None

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from ..visualization.font_config import configure_chinese_font
        configure_chinese_font()

        fig, ax = plt.subplots(figsize=(8, 5))
        ks = sorted(result.pool_distribution.keys())
        probs = [result.pool_distribution[k] for k in ks]
        bars = ax.bar(ks, probs, color='coral')
        ax.set_xlabel('成功抽取新池子数 k', fontsize=11)
        ax.set_ylabel('P(X = k)', fontsize=11)
        ax.set_title(f'{gdr_name} - 新池子数分布 (E[X] = {result.expected_pools:.2f})', fontsize=12)
        ax.set_xticks(ks)
        ax.axvline(x=result.expected_pools, color='red', linestyle='--',
                  label=f'期望 = {result.expected_pools:.2f}')
        ax.legend(fontsize=9)
        for bar, prob in zip(bars, probs):
            if prob > 0.01:
                ax.text(bar.get_x() + bar.get_width()/2,
                       bar.get_height() + 0.005,
                       f'{prob:.1%}', ha='center', va='bottom', fontsize=9)
        plt.tight_layout()

        tmp = tempfile.NamedTemporaryFile(suffix='.png', delete=False)
        fig.savefig(tmp.name, dpi=200, bbox_inches='tight')
        plt.close(fig)
        pixmap = QPixmap(tmp.name)
        return pixmap

    def _on_error(self, err):
        self.run_btn.setEnabled(True)
        self.status_label.setText(f"错误: {err}")
        import traceback
        traceback.print_exc()
