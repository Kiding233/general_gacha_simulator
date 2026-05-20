#!/usr/bin/env python3
"""抽卡模拟器主窗口"""

import sys
import os
import traceback
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QTabWidget, QWidget, QVBoxLayout, QHBoxLayout,
    QMessageBox, QFileDialog, QStatusBar, QMenuBar, QMenu, QLabel
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QAction, QIcon

from .config_panel import ConfigPanel
from .gacha_panel import GachaPanel
from .analysis_panel import AnalysisPanel
from .strategy_panel import StrategyPanel
from .resource_search_panel import ResourceSearchPanel
from .retreat_panel import RetreatPanel
from .retreat_search_panel import RetreatSearchPanel
from .worst_impact_panel import WorstImpactPanel
from .process_analysis_panel import ProcessAnalysisPanel
from .strategy_comparison_panel import StrategyComparisonPanel
from ..core.config_store import ConfigStore
from ..core.config_io import load_store_from_directory, save_store_to_directory


_DEFAULT_CONFIG_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'config')
_ICON_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'resources', 'app_icon.png')


class MainWindow(QMainWindow):

    simulation_requested = pyqtSignal(dict)
    batch_simulation_requested = pyqtSignal(dict, int)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Gacha Simulator - 抽卡模拟器")
        self.setGeometry(100, 100, 1400, 900)
        if os.path.exists(_ICON_PATH):
            self.setWindowIcon(QIcon(_ICON_PATH))

        self.config_data = {}
        self.simulation_results = None
        self._store = ConfigStore()

        self._setup_ui()
        self._setup_menu()
        self._connect_signals()
        self._load_default_config()

    def _setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        layout = QVBoxLayout(central_widget)

        self.tabs = QTabWidget()
        self.tabs.currentChanged.connect(self._on_tab_changed)
        layout.addWidget(self.tabs)

        self.config_panel = ConfigPanel()
        self.gacha_panel = GachaPanel()
        self.analysis_panel = AnalysisPanel()
        self.strategy_panel = StrategyPanel()
        self.resource_search_panel = ResourceSearchPanel()

        self.retreat_panel = RetreatPanel()
        self.retreat_search_panel = RetreatSearchPanel()

        self.retreat_tab = QWidget()
        retreat_tab_layout = QVBoxLayout(self.retreat_tab)
        retreat_tab_layout.setContentsMargins(0, 0, 0, 0)
        self.retreat_sub_tabs = QTabWidget()
        self.retreat_sub_tabs.addTab(self.retreat_panel, "脆弱性分析")
        self.retreat_sub_tabs.addTab(self.retreat_search_panel, "方案搜索")
        retreat_tab_layout.addWidget(self.retreat_sub_tabs)

        self.worst_impact_panel = WorstImpactPanel()
        self.worst_impact_panel.set_store(self._store)

        self.process_analysis_panel = ProcessAnalysisPanel()

        self.strategy_comparison_panel = StrategyComparisonPanel()

        self.sensitivity_panel = QWidget()
        self.sensitivity_layout = QVBoxLayout(self.sensitivity_panel)
        self.sensitivity_layout.addWidget(QLabel("敏感度分析（功能开发中）"))
        self.sensitivity_layout.addStretch()

        self.config_panel.set_store(self._store)
        self.strategy_panel.set_store(self._store)
        self.resource_search_panel.set_store(self._store)
        self.retreat_panel.set_store(self._store)
        self.retreat_search_panel.set_store(self._store)
        self.strategy_comparison_panel.set_store(self._store)

        self.tabs.addTab(self.config_panel, "配置")
        self.tabs.addTab(self.gacha_panel, "批量模拟")
        self.tabs.addTab(self.analysis_panel, "统计分析")
        self.tabs.addTab(self.process_analysis_panel, "过程分析")
        self.tabs.addTab(self.strategy_panel, "最多目标卡")
        self.tabs.addTab(self.resource_search_panel, "最少资源")
        self.tabs.addTab(self.retreat_tab, "退路分析")
        self.tabs.addTab(self.worst_impact_panel, "最差影响")
        self.tabs.addTab(self.strategy_comparison_panel, "策略比较")
        self.tabs.addTab(self.sensitivity_panel, "敏感度分析")

        self.status_bar = QStatusBar()
        self.setStatusBar(self.status_bar)
        self.status_bar.showMessage("就绪")

    def _setup_menu(self):
        menubar = self.menuBar()

        file_menu = menubar.addMenu("文件")

        import_config_action = QAction("导入配置", self)
        import_config_action.setShortcut("Ctrl+O")
        import_config_action.triggered.connect(self.import_config)
        file_menu.addAction(import_config_action)

        export_config_action = QAction("导出配置", self)
        export_config_action.setShortcut("Ctrl+S")
        export_config_action.triggered.connect(self.export_config)
        file_menu.addAction(export_config_action)

        file_menu.addSeparator()

        reload_default_action = QAction("重置为默认配置", self)
        reload_default_action.triggered.connect(self._load_default_config)
        file_menu.addAction(reload_default_action)

        file_menu.addSeparator()

        export_results_action = QAction("导出结果", self)
        export_results_action.triggered.connect(self.export_results)
        file_menu.addAction(export_results_action)

        file_menu.addSeparator()

        exit_action = QAction("退出", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        help_menu = menubar.addMenu("帮助")

        about_action = QAction("关于", self)
        about_action.triggered.connect(self.show_about)
        help_menu.addAction(about_action)

    def _connect_signals(self):
        self.gacha_panel.simulation_finished.connect(self.on_simulation_finished)
        self.gacha_panel.status_update.connect(self.status_bar.showMessage)
        self.strategy_panel.status_update.connect(self.status_bar.showMessage)
        self.resource_search_panel.status_update.connect(self.status_bar.showMessage)
        self.retreat_panel.status_update.connect(self.status_bar.showMessage)
        self.retreat_search_panel.status_update.connect(self.status_bar.showMessage)
        self.worst_impact_panel.status_update.connect(self.status_bar.showMessage)
        self.strategy_comparison_panel.status_update.connect(self.status_bar.showMessage)
        self.config_panel.config_changed.connect(self._on_config_changed)
        self.retreat_panel.vulnerability_finished.connect(self.retreat_search_panel.set_vulnerability_result)

    def _on_config_changed(self, config):
        self.config_panel.apply_to_store()
        self.strategy_panel.set_store(self._store)
        self.resource_search_panel.set_store(self._store)
        self.retreat_panel.set_store(self._store)
        self.retreat_search_panel.set_store(self._store)
        self.strategy_comparison_panel.set_store(self._store)

    def _on_tab_changed(self, index):
        widget = self.tabs.widget(index)
        if widget is self.strategy_panel:
            self.strategy_panel.set_store(self._store)
        elif widget is self.resource_search_panel:
            self.resource_search_panel.set_store(self._store)
        elif widget is self.retreat_tab:
            self.retreat_panel.set_store(self._store)
            self.retreat_search_panel.set_store(self._store)
        elif widget is self.worst_impact_panel:
            self.worst_impact_panel.set_store(self._store)
        elif widget is self.strategy_comparison_panel:
            self.strategy_comparison_panel.set_store(self._store)

    def _load_default_config(self):
        try:
            load_store_from_directory(_DEFAULT_CONFIG_DIR, self._store)
            self.config_panel.refresh_from_store()
            self.strategy_panel.set_store(self._store)
            self.resource_search_panel.set_store(self._store)
            self.status_bar.showMessage(f"已加载默认配置: {_DEFAULT_CONFIG_DIR}")
        except Exception as e:
            traceback.print_exc()
            self.status_bar.showMessage(f"加载默认配置失败: {e}")

    def import_config(self):
        path = QFileDialog.getExistingDirectory(self, "选择配置目录")
        if path:
            try:
                self.config_panel.apply_to_store()
                load_store_from_directory(path, self._store)
                self.config_panel.refresh_from_store()
                self.strategy_panel.set_store(self._store)
                self.resource_search_panel.set_store(self._store)
                self.status_bar.showMessage(f"配置已导入: {path}")
            except Exception as e:
                traceback.print_exc()
                QMessageBox.warning(self, "导入失败", str(e))

    def export_config(self):
        path = QFileDialog.getExistingDirectory(self, "选择导出目录")
        if path:
            try:
                self.config_panel.apply_to_store()
                save_store_to_directory(path, self._store)
                self.status_bar.showMessage(f"配置已导出: {path}")
            except Exception as e:
                traceback.print_exc()
                QMessageBox.warning(self, "导出失败", str(e))

    def export_results(self):
        if self.simulation_results is None:
            QMessageBox.information(self, "提示", "请先运行模拟")
            return

        path, _ = QFileDialog.getSaveFileName(
            self, "导出结果", "", "JSON Files (*.json);;CSV Files (*.csv)"
        )
        if path:
            try:
                if path.endswith('.csv'):
                    self._export_csv(path)
                else:
                    self._export_json(path)
                self.status_bar.showMessage(f"结果已导出: {path}")
            except Exception as e:
                QMessageBox.warning(self, "导出失败", str(e))

    def _export_json(self, path):
        import json
        data = {
            'config': self.config_panel.get_config(),
            'results_summary': self.analysis_panel.get_summary() if self.analysis_panel else {},
        }
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2, ensure_ascii=False)

    def _export_csv(self, path):
        if not self.simulation_results:
            return
        import csv
        with open(path, 'w', newline='', encoding='utf-8') as f:
            writer = csv.writer(f)
            writer.writerow(['Sim_ID', 'Total_Draws', 'Pity_Triggers', 'Final_Resource', 'Card_Counts'])
            for sim_idx, sim_result in enumerate(self.simulation_results):
                if isinstance(sim_result, dict):
                    final_res = sim_result.get('final_resources', {}).get('draw_resource', 0)
                    card_counts = sim_result.get('card_counts', {})
                    writer.writerow([
                        f"Sim_{sim_idx}",
                        sim_result.get('total_draws', 0),
                        sim_result.get('pity_triggers', 0),
                        f"{final_res:.0f}",
                        str(card_counts),
                    ])

    def on_simulation_finished(self, result_bundle):
        if isinstance(result_bundle, dict):
            aggregate_data = result_bundle.get('aggregate_data', [])
            target_ids = result_bundle.get('target_ids', set())
            ssr_ids = result_bundle.get('ssr_ids', set())
            gdr_context = result_bundle.get('gdr_context', None)
            pool_end_times = result_bundle.get('pool_end_times', {})
            target_specs = result_bundle.get('target_specs', {})
            draw_sequences = result_bundle.get('draw_sequences', [])
            heatmap_data = result_bundle.get('heatmap_data', {})
            cumulative_snapshots = result_bundle.get('cumulative_snapshots', {})
            transition_flags = result_bundle.get('transition_flags', [])
        else:
            aggregate_data = result_bundle
            target_ids = getattr(self.gacha_panel, 'target_ids', set())
            ssr_ids = getattr(self.gacha_panel, 'ssr_ids', set())
            gdr_context = getattr(self.gacha_panel, 'gdr_context', None)
            pool_end_times = getattr(self.gacha_panel, 'pool_end_times', {})
            target_specs = {}
            draw_sequences = []
            heatmap_data = {}
            cumulative_snapshots = {}
            transition_flags = []

        self.simulation_results = aggregate_data

        self.analysis_panel.update_results(
            aggregate_data,
            draw_sequences=draw_sequences,
            heatmap_data=heatmap_data,
            cumulative_snapshots=cumulative_snapshots,
            transition_flags=transition_flags,
            target_ids=target_ids,
            ssr_ids=ssr_ids,
            gdr_context=gdr_context,
            pool_end_times=pool_end_times,
        )

        if not target_specs:
            target_specs = {}
            for tc in self._store.target_cards:
                target_specs[tc.card_id] = getattr(tc, 'quantity', 1)
        self.worst_impact_panel.set_simulation_results(aggregate_data, target_specs)
        self.worst_impact_panel._load_last_pool_config()
        self.retreat_panel.set_simulation_results(aggregate_data, target_specs)

        self.process_analysis_panel.update_results(
            aggregate_data,
            target_ids=target_ids,
            ssr_ids=ssr_ids,
            gdr_context=gdr_context,
            target_specs=target_specs,
            pool_end_times=pool_end_times,
            initial_resources=getattr(gdr_context, 'initial_resources', {}) if gdr_context else {},
            cumulative_snapshots=cumulative_snapshots,
        )

        self.tabs.setCurrentIndex(2)
        self.status_bar.showMessage(f"模拟完成，共 {len(aggregate_data)} 次模拟")

    def show_about(self):
        from .about_dialog import AboutDialog
        dialog = AboutDialog(self)
        dialog.exec()

    def closeEvent(self, event):
        reply = QMessageBox.question(
            self, "确认退出",
            "确定要退出吗？",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            event.accept()
        else:
            event.ignore()


def main():
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName("Gacha Simulator")
    app.setOrganizationName("Gacha Simulator")
    app.setApplicationVersion("1.0")
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
