#!/usr/bin/env python3
"""
策略比较面板 - 并行运行多个策略并比较结果
"""

import sys
import os
import traceback
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QGroupBox, QFormLayout, QSpinBox,
    QTableWidget, QTableWidgetItem, QHeaderView,
    QSplitter, QCheckBox, QScrollArea, QAbstractItemView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor

_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)

from gacha_simulator.core.config_store import ConfigStore
from gacha_simulator.core.strategy import STRATEGY_REGISTRY


class ComparisonWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(Exception)

    def __init__(
        self,
        strategy_keys: list,
        num_simulations: int,
        config_store: ConfigStore,
        max_workers: int = 4,
    ):
        super().__init__()
        self.strategy_keys = strategy_keys
        self.num_simulations = num_simulations
        self.config_store = config_store
        self.max_workers = max_workers
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def run(self):
        try:
            from .batch_simulator import SimulationEnvBuilder, run_batch_parallel

            env = SimulationEnvBuilder.from_config_store(self.config_store)
            sim_env = {
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

            target_specs = {}
            for tc in self.config_store.target_cards:
                target_specs[tc.card_id] = getattr(tc, 'quantity', 1)

            current_strategy_key = self.config_store.strategy_name
            current_strategy_params = dict(self.config_store.strategy_params) if self.config_store.strategy_params else {}

            results = {}
            total = len(self.strategy_keys)
            for i, skey in enumerate(self.strategy_keys):
                if self._should_stop:
                    break
                entry = STRATEGY_REGISTRY.get(skey)
                display_name = entry['display_name'] if entry else skey
                self.progress.emit(f"运行策略: {display_name}", int((i / max(total, 1)) * 95) + 2)

                if skey == current_strategy_key:
                    sparams = current_strategy_params
                else:
                    sparams = {}

                histories = run_batch_parallel(
                    pools=sim_env['pools'],
                    schedule_mgr=sim_env['schedule_mgr'],
                    end_time=sim_env['end_time'],
                    pity_engine=sim_env['pity_engine'],
                    resource_gain=sim_env['resource_gain'],
                    pity_state_init=sim_env['pity_state_init'],
                    card_defs=sim_env['card_defs'],
                    target_specs=target_specs,
                    initial_resources=sim_env['initial_resources'],
                    num_simulations=self.num_simulations,
                    max_workers=self.max_workers,
                    seed=0,
                    strategy_name=skey,
                    strategy_params=sparams,
                    ssr_ids=sim_env['ssr_ids'],
                )

                results[skey] = self._compute_summary(histories, display_name)

            self.progress.emit("比较完成", 100)
            self.finished.emit(results)
        except Exception as e:
            traceback.print_exc()
            self.error.emit(e)

    def _compute_summary(self, histories, display_name):
        if not histories:
            return {'display_name': display_name, 'count': 0}

        total_draws_list = []
        pity_triggers_list = []
        target_acquired_list = []
        final_resource_list = []

        target_ids = set()
        for tc in self.config_store.target_cards:
            target_ids.add(tc.card_id)

        for h in histories:
            if isinstance(h, dict):
                total_draws_list.append(h.get('total_draws', 0))
                pity_triggers_list.append(h.get('pity_triggers', 0))
                fr = h.get('final_resources', {})
                final_resource_list.append(fr.get('draw_resource', 0) if fr else 0)
                cc = h.get('card_counts', {})
                acquired = sum(cc.get(tid, 0) for tid in target_ids)
                target_acquired_list.append(acquired)
            else:
                total_draws_list.append(getattr(h, 'total_draws', 0))
                pity_triggers_list.append(getattr(h, 'pity_triggers', 0))
                fr = getattr(h, 'final_resources', {})
                final_resource_list.append(fr.get('draw_resource', 0) if fr else 0)
                cc = getattr(h, 'card_counts', {})
                acquired = sum(cc.get(tid, 0) for tid in target_ids)
                target_acquired_list.append(acquired)

        n = len(total_draws_list)
        avg_draws = sum(total_draws_list) / n if n else 0
        avg_pity = sum(pity_triggers_list) / n if n else 0
        avg_target = sum(target_acquired_list) / n if n else 0
        avg_resource = sum(final_resource_list) / n if n else 0
        success_count = sum(1 for a in target_acquired_list if a > 0)
        success_rate = success_count / n if n else 0

        return {
            'display_name': display_name,
            'count': n,
            'avg_draws': avg_draws,
            'avg_pity_triggers': avg_pity,
            'avg_target_acquired': avg_target,
            'avg_final_resource': avg_resource,
            'success_rate': success_rate,
        }


class StrategyComparisonPanel(QWidget):
    status_update = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._store = ConfigStore()
        self._worker = None
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        layout.addWidget(splitter)

        left_scroll = QScrollArea()
        left_scroll.setWidgetResizable(True)
        left_widget = QWidget()
        left_layout = QVBoxLayout(left_widget)

        params_group = QGroupBox("比较参数")
        params_layout = QFormLayout(params_group)

        self.simulations_spin = QSpinBox()
        self.simulations_spin.setRange(100, 10000)
        self.simulations_spin.setSingleStep(100)
        self.simulations_spin.setValue(500)
        params_layout.addRow("每策略模拟次数:", self.simulations_spin)

        self.max_workers_spin = QSpinBox()
        self.max_workers_spin.setRange(1, os.cpu_count() or 16)
        self.max_workers_spin.setValue(max(1, (os.cpu_count() or 8) - 2))
        params_layout.addRow("并行进程数:", self.max_workers_spin)

        left_layout.addWidget(params_group)

        strategies_group = QGroupBox("选择策略")
        strategies_layout = QVBoxLayout(strategies_group)

        self._strategy_checks = {}
        for key, entry in STRATEGY_REGISTRY.items():
            if entry.get('internal'):
                continue
            cb = QCheckBox(f"{entry['display_name']} - {entry['description']}")
            cb.setChecked(key in ('smart', 'pool_quota'))
            self._strategy_checks[key] = cb
            strategies_layout.addWidget(cb)

        select_all_btn = QPushButton("全选")
        deselect_all_btn = QPushButton("全不选")

        def _select_all():
            for cb in self._strategy_checks.values():
                cb.setChecked(True)

        def _deselect_all():
            for cb in self._strategy_checks.values():
                cb.setChecked(False)

        select_all_btn.clicked.connect(_select_all)
        deselect_all_btn.clicked.connect(_deselect_all)

        btn_row = QHBoxLayout()
        btn_row.addWidget(select_all_btn)
        btn_row.addWidget(deselect_all_btn)
        strategies_layout.addLayout(btn_row)

        left_layout.addWidget(strategies_group)

        run_row = QHBoxLayout()
        self.run_btn = QPushButton("开始比较")
        self.run_btn.clicked.connect(self._on_run_clicked)
        run_row.addWidget(self.run_btn)

        self.stop_btn = QPushButton("停止")
        self.stop_btn.clicked.connect(self._on_stop_clicked)
        self.stop_btn.setEnabled(False)
        run_row.addWidget(self.stop_btn)
        left_layout.addLayout(run_row)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        left_layout.addWidget(self.progress_bar)

        self.status_label = QLabel("就绪")
        left_layout.addWidget(self.status_label)
        left_layout.addStretch()

        left_scroll.setWidget(left_widget)

        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)

        result_group = QGroupBox("比较结果")
        result_layout = QVBoxLayout(result_group)

        self.result_table = QTableWidget()
        self.result_table.setColumnCount(7)
        self.result_table.setHorizontalHeaderLabels([
            "策略", "模拟次数", "平均抽卡数", "平均保底触发",
            "平均目标获得", "成功率", "平均剩余资源"
        ])
        header = self.result_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.result_table.verticalHeader().setVisible(False)
        self.result_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        result_layout.addWidget(self.result_table)

        right_layout.addWidget(result_group)

        splitter.addWidget(left_scroll)
        splitter.addWidget(right_panel)
        splitter.setSizes([350, 650])

    def set_store(self, store: ConfigStore):
        self._store = store

    def _on_run_clicked(self):
        selected_keys = [k for k, cb in self._strategy_checks.items() if cb.isChecked()]
        if not selected_keys:
            self.status_label.setText("请至少选择一个策略")
            return

        self.run_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.progress_bar.setValue(0)
        self.result_table.setRowCount(0)

        self._worker = ComparisonWorker(
            strategy_keys=selected_keys,
            num_simulations=self.simulations_spin.value(),
            config_store=self._store,
            max_workers=self.max_workers_spin.value(),
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.finished.connect(self._on_finished)
        self._worker.error.connect(self._on_error)
        self._worker.start()

    def _on_stop_clicked(self):
        if self._worker:
            self._worker.stop()
            self.status_label.setText("正在停止...")

    def _on_progress(self, msg, pct):
        self.progress_bar.setValue(pct)
        self.status_label.setText(msg)
        self.status_update.emit(msg)

    def _on_finished(self, results):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.progress_bar.setValue(100)

        if not results:
            self.status_label.setText("无结果")
            return

        sorted_results = sorted(results.values(), key=lambda r: r.get('success_rate', 0), reverse=True)

        self.result_table.setRowCount(len(sorted_results))
        for row, r in enumerate(sorted_results):
            self.result_table.setItem(row, 0, QTableWidgetItem(r.get('display_name', '')))
            self.result_table.setItem(row, 1, QTableWidgetItem(str(r.get('count', 0))))
            self.result_table.setItem(row, 2, QTableWidgetItem(f"{r.get('avg_draws', 0):.1f}"))
            self.result_table.setItem(row, 3, QTableWidgetItem(f"{r.get('avg_pity_triggers', 0):.2f}"))
            self.result_table.setItem(row, 4, QTableWidgetItem(f"{r.get('avg_target_acquired', 0):.2f}"))
            self.result_table.setItem(row, 5, QTableWidgetItem(f"{r.get('success_rate', 0):.1%}"))
            self.result_table.setItem(row, 6, QTableWidgetItem(f"{r.get('avg_final_resource', 0):.0f}"))

            if row == 0:
                for col in range(7):
                    item = self.result_table.item(row, col)
                    if item:
                        item.setBackground(QColor(220, 255, 220))

        self.status_label.setText(f"比较完成，共 {len(sorted_results)} 个策略")
        self.status_update.emit(f"策略比较完成，共 {len(sorted_results)} 个策略")

    def _on_error(self, exc):
        self.run_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.status_label.setText(f"错误: {exc}")
        self.status_update.emit(f"策略比较错误: {exc}")
