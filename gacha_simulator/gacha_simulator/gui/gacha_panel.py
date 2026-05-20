#!/usr/bin/env python3
"""抽卡面板 - 批量模拟"""

import traceback
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QProgressBar, QTextEdit, QGroupBox, QFormLayout, QSpinBox,
    QComboBox, QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal, QTimer
from PyQt6.QtGui import QFont

import sys
import os
_parent = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _parent not in sys.path:
    sys.path.insert(0, _parent)




class SimulationThread(QThread):
    progress = pyqtSignal(int, int)
    finished = pyqtSignal(object)
    error = pyqtSignal(str)

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config

    def run(self):
        try:
            from .._version import __version__
            print(f"[VERSION] {__version__}")

            from .batch_simulator import SimulationEnvBuilder, SimulationEnv

            config_store = self._build_config_store()
            env = SimulationEnvBuilder.from_config_store(config_store)

            target_ids = env.target_ids
            ssr_ids = env.ssr_ids
            self._target_ids = target_ids
            self._ssr_ids = ssr_ids
            self._pool_end_times = env.pool_end_times
            self._gdr_context = env.gdr_context

            N = self.config['simulation_count']
            max_workers = self.config['max_workers']
            seed = self.config['seed']

            from .batch_simulator import run_batch_parallel
            from ..core.streaming import SharedResultCollector, extract_aggregate, DrawSequenceExtractor

            target_specs = {tc.card_id: tc.quantity for tc in config_store.target_cards}
            card_defs_list = env.card_defs

            collector = SharedResultCollector()
            collector.add_extractor('aggregate', extract_aggregate)

            seq_extractor = DrawSequenceExtractor(
                max_keep=200,
                pool_end_times=env.pool_end_times,
                target_ids=target_ids,
                ssr_ids=ssr_ids,
                target_specs=target_specs,
                initial_resources=env.initial_resources,
            )
            collector.add_extractor('draw_sequence', seq_extractor)

            from ..core.strategy import strategy_type_to_key

            strategy_key = strategy_type_to_key(config_store.strategy_type)

            run_batch_parallel(
                pools=env.pools,
                schedule_mgr=env.schedule_mgr,
                end_time=env.end_time,
                pity_engine=env.pity_engine,
                resource_gain=env.resource_gain,
                pity_state_init=env.pity_state_init,
                card_defs=card_defs_list,
                target_specs=target_specs,
                initial_resources=env.initial_resources,
                num_simulations=N,
                max_workers=max_workers,
                seed=seed,
                progress_callback=lambda done, total: self.progress.emit(done, total),
                strategy_name=strategy_key,
                strategy_params=config_store.strategy_params,
                on_result=collector.on_result,
            )

            result_bundle = {
                'aggregate_data': collector.get_extracted('aggregate'),
                'draw_sequences': seq_extractor.get_kept_sequences(),
                'heatmap_data': seq_extractor.get_heatmap_data(),
                'cumulative_snapshots': seq_extractor.get_cumulative_snapshots(),
                'transition_flags': seq_extractor.get_transition_flags(),
                'target_ids': target_ids,
                'ssr_ids': ssr_ids,
                'gdr_context': env.gdr_context,
                'pool_end_times': env.pool_end_times,
                'target_specs': target_specs,
                'n_results': collector.n_results,
                'n_requested': N,
            }

            self.finished.emit(result_bundle)

        except Exception as e:
            self.error.emit(traceback.format_exc())

    def _build_config_store(self):
        from gacha_simulator.core.config_store import (
            ConfigStore, PoolEntry, PityConfig, PityDef, PoolDistEntry,
            CardDefEntry, TargetCardEntry,
        )
        config = self.config
        pools = []
        for p in config.get('pools', []):
            distribution = []
            for item in p.get('distribution', []):
                rg_text = item.get('resources_gained', '')
                rg = {}
                if rg_text and isinstance(rg_text, str):
                    for part in rg_text.split(','):
                        part = part.strip()
                        if ':' in part:
                            rk, rv = part.split(':', 1)
                            rg[rk.strip()] = float(rv.strip())
                elif isinstance(rg_text, dict):
                    rg = rg_text
                distribution.append(PoolDistEntry(
                    card_id=item['card_id'],
                    probability=item.get('probability', 0),
                    featured=item.get('featured', False),
                    rarity=item.get('rarity', 'R'),
                    resources_gained=rg,
                ))
            start_day = p.get('start_day', 0)
            pools.append(PoolEntry(
                pool_id=p['id'],
                name=p.get('name', p['id']),
                start_day=start_day,
                end_day=start_day + p.get('duration', 21),
                cost=p.get('cost', 'draw_resource:160'),
                distribution=distribution,
                exchange_card_id=p.get('exchange_card_id'),
            ))

        pity_cfg = config.get('pity', {})
        pities = []
        for pd in pity_cfg.get('pities', []):
            pities.append(PityDef(
                name=pd.get('name', 'pity'),
                btype=pd.get('type', 'soft'),
                params=pd.get('params', {}),
                target_distribution=pd.get('target_distribution', {}),
                reset_condition=pd.get('reset', 'any_ssr'),
                pools=pd.get('pools', '*'),
            ))
        pity = PityConfig(
            enabled=pity_cfg.get('enabled', True),
            pities=pities,
            counter_init=pity_cfg.get('counter_init', 0),
        )

        card_defs = []
        for cd in config.get('card_defs', []):
            card_defs.append(CardDefEntry(
                card_id=cd['card_id'],
                name=cd.get('name', ''),
                rarity=cd.get('rarity', 'R'),
                pools=cd.get('pools', []),
            ))

        target_cards = []
        for tc in config.get('target_cards', []):
            target_cards.append(TargetCardEntry(
                card_id=tc['card_id'],
                quantity=tc.get('quantity', 1),
            ))

        initial_resources = config.get('initial_resources', [])

        ir_dict = {}
        if isinstance(initial_resources, list):
            for ir in initial_resources:
                if isinstance(ir, dict):
                    rid = ir.get('resource_id', 'draw_resource')
                    amt = ir.get('amount', 0)
                    if amt > 0:
                        ir_dict[rid] = ir_dict.get(rid, 0) + float(amt)
        elif isinstance(initial_resources, dict):
            ir_dict = dict(initial_resources)

        return ConfigStore(
            pools=pools,
            pity=pity,
            card_defs=card_defs,
            target_cards=target_cards,
            initial_resources=ir_dict,
        )


class GachaPanel(QWidget):

    simulation_finished = pyqtSignal(object)
    status_update = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.simulation_thread = None
        self.result_bundle = None
        self.target_ids = set()
        self.ssr_ids = set()
        self.gdr_context = None
        self.pool_end_times = {}
        self._setup_ui()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        param_group = QGroupBox("模拟参数")
        param_layout = QFormLayout(param_group)

        self.sim_count = QSpinBox()
        self.sim_count.setRange(100, 100000)
        self.sim_count.setValue(1000)
        self.sim_count.setSingleStep(100)
        param_layout.addRow("模拟次数:", self.sim_count)

        self.max_workers = QSpinBox()
        self.max_workers.setRange(1, os.cpu_count() or 16)
        self.max_workers.setValue(max(1, (os.cpu_count() or 8) - 2))
        cpu_count = os.cpu_count() or 16
        param_layout.addRow("并行进程数:", self.max_workers)
        cpu_label = QLabel(f"(本机 {cpu_count} 核心)")
        cpu_label.setStyleSheet("color: #888; font-size: 11px;")
        param_layout.addRow("", cpu_label)

        self.seed = QSpinBox()
        self.seed.setRange(-1, 999999)
        self.seed.setValue(42)
        param_layout.addRow("随机种子(-1=随机):", self.seed)

        layout.addWidget(param_group)

        info_group = QGroupBox("模拟信息")
        info_layout = QFormLayout(info_group)

        self.status_label = QLabel("就绪")
        info_layout.addRow("状态:", self.status_label)

        self.progress_bar = QProgressBar()
        self.progress_bar.setTextVisible(True)
        self.progress_bar.setFormat('%p%')
        self.progress_bar.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.progress_bar.setValue(0)
        self.progress_bar.setRange(0, 100)
        info_layout.addRow("进度:", self.progress_bar)

        layout.addWidget(info_group)

        self.run_btn = QPushButton("开始批量模拟")
        self.run_btn.clicked.connect(self.start_simulation)
        layout.addWidget(self.run_btn)

        log_group = QGroupBox("模拟日志")
        log_layout = QVBoxLayout(log_group)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(150)
        self.log_text.setFont(QFont("Monospace", 9))
        log_layout.addWidget(self.log_text)

        layout.addWidget(log_group)

        results_group = QGroupBox("快速结果预览")
        results_layout = QVBoxLayout(results_group)

        self.results_table = QTableWidget()
        self.results_table.setColumnCount(3)
        self.results_table.setHorizontalHeaderLabels(["指标", "均值", "中位数"])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.results_table.setRowCount(5)

        for i, label in enumerate(["总抽卡数", "SSR数量", "目标达成率(%)", "保底触发次数", "模拟时长(天)"]):
            self.results_table.setItem(i, 0, QTableWidgetItem(label))
            self.results_table.setItem(i, 1, QTableWidgetItem("-"))
            self.results_table.setItem(i, 2, QTableWidgetItem("-"))

        results_layout.addWidget(self.results_table)
        layout.addWidget(results_group)

        layout.addStretch()

    def start_simulation(self):
        from .config_panel import ConfigPanel
        config_panel = self._find_config_panel()
        if not config_panel:
            self._log("错误: 无法获取配置面板")
            return

        config = config_panel.get_config()
        config['simulation_count'] = self.sim_count.value()
        config['max_workers'] = self.max_workers.value()
        config['seed'] = self.seed.value()
        self.status_label.setText("运行中...")
        self.run_btn.setEnabled(False)
        self.progress_bar.setValue(0)

        self._log(f"开始模拟: {config['simulation_count']} 次")
        pity_type = config.get('pity', {}).get('type', 'unknown')
        self._log(f"保底类型: {pity_type}")
        self._log(f"并行进程: {config['max_workers']}")

        self.simulation_thread = SimulationThread(config)
        self.simulation_thread.finished.connect(self.on_simulation_finished)
        self.simulation_thread.error.connect(self.on_simulation_error)
        self.simulation_thread.progress.connect(self.on_simulation_progress)
        self.simulation_thread.start()

    def on_simulation_finished(self, result_bundle):
        self.result_bundle = result_bundle
        if isinstance(result_bundle, dict):
            self.target_ids = result_bundle.get('target_ids', set())
            self.ssr_ids = result_bundle.get('ssr_ids', set())
            self.gdr_context = result_bundle.get('gdr_context', None)
            self.pool_end_times = result_bundle.get('pool_end_times', {})
            aggregate_data = result_bundle.get('aggregate_data', [])
            n_results = len(aggregate_data)
        else:
            self.target_ids = getattr(self.simulation_thread, '_target_ids', set())
            self.ssr_ids = getattr(self.simulation_thread, '_ssr_ids', set())
            self.gdr_context = getattr(self.simulation_thread, '_gdr_context', None)
            self.pool_end_times = getattr(self.simulation_thread, '_pool_end_times', {})
            aggregate_data = result_bundle
            n_results = len(result_bundle)

        self.status_label.setText("完成")
        self.run_btn.setEnabled(True)
        self.progress_bar.setValue(100)

        self._log(f"模拟完成，共 {n_results} 次")

        if isinstance(result_bundle, dict):
            n_requested = result_bundle.get('n_requested', 0)
            if n_requested > 0 and n_results < n_requested:
                self._log(f"警告: {n_requested - n_results}/{n_requested} 次模拟失败（可能是配置错误或资源不足）")

        self._calculate_quick_stats(aggregate_data)

        self.simulation_finished.emit(result_bundle)
        self.status_update.emit(f"模拟完成，共 {n_results} 次")

    def on_simulation_error(self, error_msg):
        self.status_label.setText("错误")
        self.run_btn.setEnabled(True)
        self._log(f"错误: {error_msg}")

    def on_simulation_progress(self, done, total):
        pct = int(done / total * 100) if total > 0 else 0
        self.progress_bar.setValue(pct)
        self.status_label.setText(f"运行中... {done}/{total} ({pct}%)")

    def _calculate_quick_stats(self, results):
        import numpy as np

        total_draws = []
        ssr_counts = []
        target_rates = []
        pity_counts = []
        sim_durations = []

        target_ids = self.target_ids
        ssr_ids = self.ssr_ids
        target_count = len(target_ids) if target_ids else 1

        for h in results:
            if isinstance(h, dict):
                total_draws.append(h.get('total_draws', 0))
                cc = h.get('card_counts', {})
                ssr_count = sum(cc.get(sid, 0) for sid in ssr_ids)
                target_obtained = sum(cc.get(tid, 0) for tid in target_ids)
                ssr_counts.append(ssr_count)
                target_rates.append((target_obtained / target_count) * 100 if target_ids else 0)
                pity_counts.append(h.get('pity_triggers', 0))
                final_time = h.get('final_time', 0)
                sim_durations.append(final_time / 86400.0)
            else:
                draws = [iv for iv in h if iv.action_type == 'draw']
                total_draws.append(len(draws))
                ssr_count = sum(1 for iv in draws if iv.card_id in ssr_ids)
                target_obtained = sum(1 for iv in draws if iv.card_id in target_ids)
                ssr_counts.append(ssr_count)
                target_rates.append((target_obtained / target_count) * 100 if target_ids else 0)
                pity_counts.append(0)
                sim_durations.append(0)

        if not total_draws:
            for row in range(5):
                for col in [1, 2]:
                    self.results_table.setItem(row, col, QTableWidgetItem("-"))
            return

        self.results_table.setItem(0, 1, QTableWidgetItem(f"{np.mean(total_draws):.1f}"))
        self.results_table.setItem(0, 2, QTableWidgetItem(f"{np.median(total_draws):.1f}"))

        self.results_table.setItem(1, 1, QTableWidgetItem(f"{np.mean(ssr_counts):.2f}"))
        self.results_table.setItem(1, 2, QTableWidgetItem(f"{np.median(ssr_counts):.1f}"))

        self.results_table.setItem(2, 1, QTableWidgetItem(f"{np.mean(target_rates):.2f}"))
        self.results_table.setItem(2, 2, QTableWidgetItem(f"{np.median(target_rates):.2f}"))

        self.results_table.setItem(3, 1, QTableWidgetItem(f"{np.mean(pity_counts):.2f}"))
        self.results_table.setItem(3, 2, QTableWidgetItem(f"{np.median(pity_counts):.1f}"))

        self.results_table.setItem(4, 1, QTableWidgetItem(f"{np.mean(sim_durations):.1f}"))
        self.results_table.setItem(4, 2, QTableWidgetItem(f"{np.median(sim_durations):.1f}"))

    def _find_config_panel(self):
        from PyQt6.QtWidgets import QApplication
        for widget in QApplication.topLevelWidgets():
            from .main_window import MainWindow
            if isinstance(widget, MainWindow):
                return widget.config_panel
        return None

    def _log(self, message):
        self.log_text.append(message)

    def get_results(self):
        return self.result_bundle
