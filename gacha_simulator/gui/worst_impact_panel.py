import tempfile
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QDoubleSpinBox,
    QSpinBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QRadioButton, QButtonGroup, QComboBox, QSizePolicy,
    QSplitter, QLineEdit,
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPixmap, QPainter, QColor, QPen
from gacha_simulator.core.gdr import populate_gdr_combo, get_default_threshold
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
        self._config_panel = None
        self._setup_ui()

    def set_store(self, store):
        self._store = store
        self._load_last_pool_config()

    def set_config_panel(self, config_panel):
        self._config_panel = config_panel

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

        self.gdr_combo = QComboBox()
        self.gdr_combo.setMaxVisibleItems(30)
        populate_gdr_combo(self.gdr_combo)
        self.gdr_combo.setCurrentIndex(1)
        self.gdr_combo.currentIndexChanged.connect(self._on_gdr_changed)
        config_form.addRow("广义出率:", self.gdr_combo)

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

        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setContentsMargins(4, 4, 4, 4)

        summary_group = QGroupBox("结果摘要")
        summary_layout = QVBoxLayout(summary_group)
        self.summary_label = QLabel("尚未运行分析")
        self.summary_label.setWordWrap(True)
        self.summary_label.setStyleSheet(
            "padding: 6px; background: #f5f5f5; border-radius: 4px; font-size: 13px;"
        )
        summary_layout.addWidget(self.summary_label)
        right_layout.addWidget(summary_group)

        cov_box = QGroupBox("大保底资源覆盖")
        cov_layout = QVBoxLayout(cov_box)
        cov_layout.setContentsMargins(4, 8, 4, 4)
        self.coverage_gauge = PityCoverageGauge()
        cov_layout.addWidget(self.coverage_gauge)
        right_layout.addWidget(cov_box, 1)

        dist_box = QGroupBox("新池子数分布")
        dist_layout = QVBoxLayout(dist_box)
        dist_layout.setContentsMargins(2, 6, 2, 2)
        self.chart_label_dist = QLabel()
        self.chart_label_dist.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label_dist.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self.chart_label_dist.setMinimumHeight(200)
        dist_layout.addWidget(self.chart_label_dist)
        right_layout.addWidget(dist_box, 2)

        table_group = QGroupBox("详细数据")
        table_layout = QVBoxLayout(table_group)
        table_layout.setContentsMargins(2, 6, 2, 2)
        self.detail_table = QTableWidget()
        self.detail_table.setColumnCount(5)
        self.detail_table.setHorizontalHeaderLabels(
            ["k", "P(X=k)", "P(X>=k)", "累计概率", "说明"]
        )
        self.detail_table.setMaximumHeight(200)
        header = self.detail_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.detail_table.verticalHeader().setVisible(False)
        table_layout.addWidget(self.detail_table)
        right_layout.addWidget(table_group, 1)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([300, 700])

    def _edit_distribution(self):
        pool_id = '_worst_impact_pool'
        dist_data = self._custom_distribution or []
        dlg = PoolDistributionDialog(pool_id, dist_data, self)
        if dlg.exec() == PoolDistributionDialog.DialogCode.Accepted:
            self._custom_distribution = dlg.get_distribution()
            self._update_dist_summary()

    def _on_gdr_changed(self, index):
        key = self.gdr_combo.currentData()
        default = get_default_threshold(key)
        self.gdr_threshold_spin.setValue(default)

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

        gdr_key = self.gdr_combo.currentData() or 'all_targets'
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
        if self._config_panel:
            desire_weights = self._config_panel.get_desire_weights()
            miss_cost_weights = self._config_panel.get_miss_cost_weights()
            card_value_weights = self._config_panel.get_card_value_weights()

        analyzer = WorstImpactAnalyzer(
            simulation_results=self._simulation_results,
            target_specs=self._target_specs,
            store=self._store,
            gdr_key=gdr_key,
            gdr_threshold=gdr_threshold,
            custom_pool_config=custom_pool,
            desire_weights=desire_weights,
            miss_cost_weights=miss_cost_weights,
            card_value_weights=card_value_weights,
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

        self.coverage_gauge.set_value(result.pity_coverage)

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

        self._plot_distribution(result)
        self.status_update.emit("最差后期影响分析完成")

    def _plot_distribution(self, result):
        if not result.pool_distribution:
            return

        import matplotlib
        matplotlib.use('Agg')
        import matplotlib.pyplot as plt
        from ..visualization.font_config import configure_chinese_font
        configure_chinese_font()

        dist_w = max(self.chart_label_dist.width(), 400) / 100
        dist_h = max(self.chart_label_dist.height(), 250) / 100
        fig, ax = plt.subplots(figsize=(dist_w, dist_h))
        ks = sorted(result.pool_distribution.keys())
        probs = [result.pool_distribution[k] for k in ks]
        bars = ax.bar(ks, probs, color='coral')
        ax.set_xlabel('成功抽取新池子数 k', fontsize=11)
        ax.set_ylabel('P(X = k)', fontsize=11)
        ax.set_title(f'新池子数分布 (E[X] = {result.expected_pools:.2f})', fontsize=12)
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
        fig.savefig(tmp.name, dpi=200, bbox_inches='tight', pad_inches=0.15)
        plt.close(fig)
        pixmap = QPixmap(tmp.name)
        if not pixmap.isNull():
            scaled = pixmap.scaled(
                self.chart_label_dist.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.chart_label_dist.setPixmap(scaled)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        pixmap = self.chart_label_dist.pixmap()
        if pixmap and not pixmap.isNull():
            scaled = pixmap.scaled(
                self.chart_label_dist.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self.chart_label_dist.setPixmap(scaled)

    def _on_error(self, err):
        self.run_btn.setEnabled(True)
        self.status_label.setText(f"错误: {err}")
        import traceback
        traceback.print_exc()
