"""数据管理面板——数据集列表 + 可比性检查 + 工具栏"""
from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView,
    QSplitter, QFrame, QMessageBox, QFileDialog, QInputDialog,
)
from PyQt6.QtCore import Qt, pyqtSignal
from PyQt6.QtGui import QColor


class DataManagerPanel(QWidget):
    """数据管理 Tab——左侧可比性，右侧数据集表格"""

    load_requested = pyqtSignal(str)           # 加载数据集到分析面板
    compare_requested = pyqtSignal(list)        # 开始比较（数据集名列表）
    status_update = pyqtSignal(str)

    def __init__(self, result_store, parent=None):
        super().__init__(parent)
        self._store = result_store
        self._store.datasets_changed.connect(self._refresh_table)
        self._setup_ui()
        self._refresh_table()

    def _setup_ui(self):
        layout = QHBoxLayout(self)

        splitter = QSplitter(Qt.Orientation.Horizontal)

        # —— 左侧：可比性检查面板（固定宽度 300px） ——
        left_panel = QFrame()
        left_panel.setFrameShape(QFrame.Shape.StyledPanel)
        left_layout = QVBoxLayout(left_panel)

        left_layout.addWidget(QLabel("可比性检查", styleSheet="font-weight:bold;font-size:14px;"))

        self._selection_label = QLabel("已选 0 个数据集")
        self._selection_label.setStyleSheet("font-size:11px;color:#888;")
        left_layout.addWidget(self._selection_label)

        self._comparability_table = QTableWidget()
        self._comparability_table.setColumnCount(3)
        self._comparability_table.setHorizontalHeaderLabels(["维度", "状态", "详情"])
        self._comparability_table.horizontalHeader().setSectionResizeMode(
            0, QHeaderView.ResizeMode.ResizeToContents)
        self._comparability_table.horizontalHeader().setSectionResizeMode(
            1, QHeaderView.ResizeMode.ResizeToContents)
        self._comparability_table.horizontalHeader().setSectionResizeMode(
            2, QHeaderView.ResizeMode.Stretch)
        self._comparability_table.verticalHeader().setVisible(False)
        self._comparability_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        left_layout.addWidget(self._comparability_table)

        self._mode_hint = QLabel("")
        self._mode_hint.setWordWrap(True)
        self._mode_hint.setStyleSheet(
            "font-size:11px;background:#fff9f0;border-left:3px solid #f5a623;"
            "padding:6px 8px;border-radius:2px;line-height:1.5;"
        )
        left_layout.addWidget(self._mode_hint)

        self._compare_btn = QPushButton("开始比较")
        self._compare_btn.setStyleSheet(
            "background:#1976d2;color:#fff;padding:10px 16px;font-size:13px;"
        )
        self._compare_btn.setEnabled(False)
        self._compare_btn.clicked.connect(self._on_compare_clicked)
        left_layout.addWidget(self._compare_btn)

        # —— 右侧：数据集表格 + 工具栏 ——
        right_panel = QWidget()
        right_layout = QVBoxLayout(right_panel)
        right_layout.setContentsMargins(0, 0, 0, 0)

        # 工具栏
        toolbar = QHBoxLayout()
        self._load_btn = QPushButton("加载")
        self._load_btn.clicked.connect(self._on_load_clicked)
        toolbar.addWidget(self._load_btn)

        self._rename_btn = QPushButton("重命名")
        self._rename_btn.clicked.connect(self._on_rename_clicked)
        toolbar.addWidget(self._rename_btn)

        self._delete_btn = QPushButton("删除")
        self._delete_btn.clicked.connect(self._on_delete_clicked)
        toolbar.addWidget(self._delete_btn)

        toolbar.addSpacing(8)
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.VLine)
        toolbar.addWidget(sep)
        toolbar.addSpacing(8)

        self._import_btn = QPushButton("导入...")
        self._import_btn.clicked.connect(self._on_import_clicked)
        toolbar.addWidget(self._import_btn)

        self._export_btn = QPushButton("导出...")
        self._export_btn.clicked.connect(self._on_export_clicked)
        toolbar.addWidget(self._export_btn)

        toolbar.addStretch()
        self._current_label = QLabel("")
        self._current_label.setStyleSheet("font-size:12px;color:#888;")
        toolbar.addWidget(self._current_label)

        right_layout.addLayout(toolbar)

        self._table = QTableWidget()
        self._table.setColumnCount(8)
        self._table.setHorizontalHeaderLabels([
            "", "名称", "策略", "目标卡", "初始资源", "N", "时间", "备注"
        ])
        hdr = self._table.horizontalHeader()
        hdr.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self._table.setColumnWidth(0, 30)
        hdr.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        hdr.setSectionResizeMode(2, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(4, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(5, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)
        hdr.setSectionResizeMode(7, QHeaderView.ResizeMode.Stretch)
        self._table.verticalHeader().setVisible(False)
        self._table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self._table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self._table.cellDoubleClicked.connect(self._on_double_click)
        self._table.itemChanged.connect(self._on_checkbox_changed)
        right_layout.addWidget(self._table)

        splitter.addWidget(left_panel)
        splitter.addWidget(right_panel)
        splitter.setSizes([300, 700])

        layout.addWidget(splitter)

    # —— 表格刷新 ——
    def _refresh_table(self):
        datasets = self._store.list_datasets()
        current_name = self._store.current_name or ''

        self._table.setRowCount(len(datasets))
        for row, ds in enumerate(datasets):
            name = ds['name']
            # 复选框列
            cb_item = QTableWidgetItem()
            cb_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            cb_item.setCheckState(Qt.CheckState.Unchecked)
            cb_item.setData(Qt.ItemDataRole.UserRole, name)
            self._table.setItem(row, 0, cb_item)

            self._table.setItem(row, 1, QTableWidgetItem(name))
            self._table.setItem(row, 2, QTableWidgetItem(ds['strategy_name']))
            target_str = ','.join(ds['target_cards'].keys()) if ds['target_cards'] else '—'
            self._table.setItem(row, 3, QTableWidgetItem(target_str))
            # 初始资源从指纹获取
            fp = self._store.get(name)
            init_res = ''
            if fp and fp.fingerprint.initial_resources:
                init_res = ','.join(
                    f"{k}:{v}" for k, v in fp.fingerprint.initial_resources.items())
            self._table.setItem(row, 4, QTableWidgetItem(init_res))
            self._table.setItem(row, 5, QTableWidgetItem(str(ds['num_simulations'])))
            created = ds['created_at']
            # 截取时间部分
            if 'T' in created:
                created = created.split('T')[1][:5] if 'T' in created else created
            self._table.setItem(row, 6, QTableWidgetItem(created))
            self._table.setItem(row, 7, QTableWidgetItem(ds.get('notes', '')))

            if name == current_name:
                for col in range(8):
                    item = self._table.item(row, col)
                    if item:
                        item.setBackground(QColor(227, 242, 253))

        self._current_label.setText(
            f"当前：{current_name}" if current_name else "未加载数据集"
        )
        self._update_comparability()

    def _on_checkbox_changed(self, item):
        if item.column() == 0:
            self._update_comparability()

    def _get_checked_names(self) -> list:
        names = []
        for row in range(self._table.rowCount()):
            item = self._table.item(row, 0)
            if item and item.checkState() == Qt.CheckState.Checked:
                names.append(item.data(Qt.ItemDataRole.UserRole))
        return names

    def _update_comparability(self):
        names = self._get_checked_names()
        n = len(names)
        self._selection_label.setText(f"已选 {n} 个数据集")

        self._comparability_table.setRowCount(0)
        self._mode_hint.setText("")

        if n == 0:
            self._mode_hint.setText("选择数据集以查看可比性")
            self._compare_btn.setEnabled(False)
            return

        if n == 1:
            # 显示单个数据集的完整元信息
            ds = self._store.get(names[0])
            if ds is None:
                return
            fp = ds.fingerprint
            rows = [
                ('策略', fp.strategy_name),
                ('目标卡', str(fp.target_cards)),
                ('初始资源', str(fp.initial_resources)),
                ('停止条件', fp.stop_condition),
                ('种子', f'{fp.seed_start}–{fp.seed_end}'),
                ('模拟次数', str(fp.num_simulations)),
                ('池子', ', '.join(fp.pool_ids)),
                ('配置Hash', fp.config_hash),
            ]
            self._comparability_table.setRowCount(len(rows))
            for i, (dim, val) in enumerate(rows):
                self._comparability_table.setItem(i, 0, QTableWidgetItem(dim))
                self._comparability_table.setItem(i, 1, QTableWidgetItem(val))
            self._compare_btn.setEnabled(False)
            return

        # >=2: 可比性差异矩阵
        diff = self._store.compare_fingerprints(names)
        if diff is None:
            return

        dims = [
            ('strategy_name', '策略'),
            ('config_hash', '配置'),
            ('target_cards', '目标卡'),
            ('initial_resources', '初始资源'),
            ('stop_condition', '停止条件'),
            ('seed_start', '种子'),
            ('num_simulations', 'N'),
            ('pool_ids', '池子'),
        ]

        self._comparability_table.setRowCount(len(dims))
        for i, (key, label) in enumerate(dims):
            self._comparability_table.setItem(i, 0, QTableWidgetItem(label))
            status = diff.dimensions.get(key, 'same')
            if status == 'same':
                status_item = QTableWidgetItem('✓')
                status_item.setForeground(QColor('#4caf50'))
                detail = '相同'
            elif status == 'varies':
                status_item = QTableWidgetItem('⚠')
                status_item.setForeground(QColor('#f5a623'))
                detail = '各数据集不同'
            else:
                status_item = QTableWidgetItem('⚠')
                status_item.setForeground(QColor('#f5a623'))
                detail = status.replace('different: ', '')
            self._comparability_table.setItem(i, 1, status_item)
            self._comparability_table.setItem(i, 2, QTableWidgetItem(detail))

        self._mode_hint.setText(diff.mode_label())
        self._compare_btn.setEnabled(True)

    # —— 按钮事件 ——
    def _on_load_clicked(self):
        checked = self._get_checked_names()
        if len(checked) != 1:
            QMessageBox.information(self, "提示", "请勾选一个数据集后加载")
            return
        self.load_requested.emit(checked[0])

    def _on_double_click(self, row, col):
        if col == 0:
            return  # 跳过复选框列
        item = self._table.item(row, 1)
        if item:
            name = item.text()
            self._show_dataset_detail(name)

    def _show_dataset_detail(self, name: str):
        """弹出数据集详情窗口——结构化文本展示全部数据"""
        ds = self._store.get(name)
        if ds is None:
            return

        import json
        from PyQt6.QtWidgets import QDialog, QTextEdit, QVBoxLayout as VBox, QDialogButtonBox

        dlg = QDialog(self)
        dlg.setWindowTitle(f"数据集详情: {name}")
        dlg.resize(800, 650)

        layout = VBox(dlg)
        editor = QTextEdit()
        editor.setReadOnly(True)
        editor.setStyleSheet("font-family:Consolas,'Microsoft YaHei',monospace;font-size:13px;")
        layout.addWidget(editor)

        btns = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        btns.rejected.connect(dlg.reject)
        layout.addWidget(btns)

        # 构建文本
        lines = []
        fp = ds.fingerprint

        def kv(k, v):
            lines.append(f"{k}: {v}")

        def section(title):
            lines.append("")
            lines.append(f"{'='*60}")
            lines.append(f"  {title}")
            lines.append(f"{'='*60}")

        def kv_dict(k, d, indent="  "):
            if not d:
                kv(k, "{}")
                return
            lines.append(f"{k}:")
            for dk, dv in sorted(d.items()):
                lines.append(f"{indent}{dk}: {dv}")

        # ── 指纹 ──
        section("指纹 (ComparabilityFingerprint)")
        kv("策略名称", fp.strategy_name)
        kv("停止条件", fp.stop_condition)
        kv("种子范围", f"{fp.seed_start} – {fp.seed_end}")
        kv("模拟次数", fp.num_simulations)
        kv("池子列表", ", ".join(fp.pool_ids))
        kv("配置Hash", fp.config_hash)
        kv("创建时间", fp.created_at)
        kv_dict("目标卡", fp.target_cards)
        kv_dict("初始资源", fp.initial_resources)

        # ── 数据集摘要 ──
        section("数据集摘要")
        kv("名称", ds.name)
        kv("备注", ds.notes or "(无)")
        kv("创建时间", ds.created_at)
        kv("策略", ds.strategy_name)
        kv("模拟次数", ds.num_simulations)
        kv("不抽卡资源量", ds.no_draw_resource)

        # ── 聚合数据 ──
        section("聚合数据 (aggregate_data)")
        agg = ds.aggregate_data
        kv("条目数", len(agg) if isinstance(agg, list) else str(type(agg)))
        if isinstance(agg, list) and agg:
            # 提取所有顶层键
            sample = agg[0]
            if isinstance(sample, dict):
                keys = list(sample.keys())
                kv("字段", ", ".join(keys))
                # 每个字段的统计摘要
                for key in keys:
                    vals = [d.get(key) for d in agg if key in d]
                    if vals and isinstance(vals[0], (int, float)):
                        import numpy as np
                        arr = np.array(vals, dtype=float)
                        lines.append(f"  {key}: mean={arr.mean():.4f}, "
                                    f"std={arr.std():.4f}, "
                                    f"min={arr.min():.4f}, max={arr.max():.4f}")
                    elif vals and isinstance(vals[0], (list, dict)):
                        kv(f"  {key}", f"({len(vals)} 条, 类型={type(vals[0]).__name__})")
                    else:
                        unique = set(str(v) for v in vals[:20])
                        preview = ", ".join(sorted(unique)[:5])
                        kv(f"  {key}", f"{preview}" + ("..." if len(unique) > 5 else ""))

        # ── 原始 JSON（前 3 条聚合数据） ──
        section("原始数据 (前 3 条)")
        if isinstance(agg, list) and agg:
            preview = agg[:3]
            lines.append(json.dumps(preview, indent=2, ensure_ascii=False, default=str))
        else:
            lines.append(str(agg)[:2000])

        # ── 其他数据 ──
        section("其他数据")
        kv("目标卡 (target_specs)", json.dumps(ds.target_specs, ensure_ascii=False))
        kv("目标ID", ", ".join(ds.target_ids) if ds.target_ids else "(空)")
        kv("SSR ID", ", ".join(ds.ssr_ids) if ds.ssr_ids else "(空)")

        gdr = ds.gdr_context
        if gdr and isinstance(gdr, dict):
            kv_dict("GDR上下文", gdr)
        else:
            kv("GDR上下文", str(gdr))

        kv("池结束时间", json.dumps(ds.pool_end_times, ensure_ascii=False, default=str))
        kv("池类型", json.dumps(ds.pool_types, ensure_ascii=False))

        # 抽卡序列摘要
        seqs = ds.draw_sequences
        kv("抽卡序列", f"({len(seqs)} 条模拟)" if isinstance(seqs, list) else str(type(seqs)))

        # 热力图摘要
        hm = ds.heatmap_data
        if hm and isinstance(hm, dict):
            lines.append("热力图数据:")
            for hk in sorted(hm.keys()):
                hv = hm[hk]
                if isinstance(hv, dict):
                    lines.append(f"  {hk}: {len(hv)} 个条目")
                elif isinstance(hv, list):
                    lines.append(f"  {hk}: [{len(hv)} 条]")
                else:
                    lines.append(f"  {hk}: {hv}")

        # 累积快照
        cs = ds.cumulative_snapshots
        if cs and isinstance(cs, dict):
            kv("累积快照", ", ".join(sorted(cs.keys())))

        # 转变标记
        tf = ds.transition_flags
        kv("转变标记", f"({len(tf)} 条)" if isinstance(tf, list) else str(type(tf)))

        # 不抽卡池资源
        ndpr = ds.no_draw_pool_resources
        if ndpr:
            kv_dict("不抽卡池资源", ndpr)

        # 初始资源
        ir = ds.initial_resources
        if ir:
            kv_dict("初始资源", ir)

        # ── 分析缓存 ──
        cache = ds.cached_analysis
        if cache:
            section("分析缓存")
            for ck in sorted(cache.keys()):
                cv = cache[ck]
                if isinstance(cv, (dict, list)):
                    kv(ck, f"({type(cv).__name__}, {len(cv)} 元素)")
                else:
                    kv(ck, str(cv)[:200])

        # ── 完整 JSON dump（可选，放在最后） ──
        section("完整序列化 (to_dict)")
        try:
            full = ds.to_dict()
            # 移除过大的字段，避免窗口卡顿
            for huge_key in ['aggregate_data', 'draw_sequences', 'heatmap_data',
                              'cumulative_snapshots', 'transition_flags']:
                if huge_key in full:
                    val = full[huge_key]
                    if isinstance(val, list):
                        full[huge_key] = f"<{len(val)} items, omitted>"
                    elif isinstance(val, dict):
                        full[huge_key] = f"<{len(val)} keys, omitted>"
            lines.append(json.dumps(full, indent=2, ensure_ascii=False, default=str))
        except Exception as e:
            lines.append(f"序列化失败: {e}")

        editor.setPlainText("\n".join(lines))
        dlg.exec()

    def _on_compare_clicked(self):
        names = self._get_checked_names()
        if len(names) < 2:
            QMessageBox.information(self, "提示", "请勾选至少 2 个数据集进行比较")
            return
        self.compare_requested.emit(names)

    def _on_rename_clicked(self):
        checked = self._get_checked_names()
        if len(checked) != 1:
            QMessageBox.information(self, "提示", "请勾选一个数据集后重命名")
            return
        old_name = checked[0]
        new_name, ok = QInputDialog.getText(
            self, "重命名数据集", "新名称:", text=old_name)
        if ok and new_name and new_name != old_name:
            if not self._store.rename(old_name, new_name):
                QMessageBox.warning(self, "重命名失败", f"名称 '{new_name}' 已存在或无效")
            self._refresh_table()

    def _on_delete_clicked(self):
        checked = self._get_checked_names()
        if not checked:
            QMessageBox.information(self, "提示", "请勾选要删除的数据集")
            return
        reply = QMessageBox.question(
            self, "确认删除",
            f"确定要删除 {len(checked)} 个数据集吗？此操作不可撤销。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply == QMessageBox.StandardButton.Yes:
            for name in checked:
                self._store.remove(name)
            self._refresh_table()

    def _on_import_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "导入数据集", "", "JSON Files (*.json);;All Files (*)")
        if path:
            try:
                self._store.load_all(path)
                self._refresh_table()
                self.status_update.emit(f"已导入: {path}")
            except Exception as e:
                QMessageBox.warning(self, "导入失败", str(e))

    def _on_export_clicked(self):
        checked = self._get_checked_names()
        if not checked:
            # 导出全部
            path, _ = QFileDialog.getSaveFileName(
                self, "导出全部数据集", "", "JSON Files (*.json)")
            if path:
                try:
                    self._store.save_all(path)
                    self.status_update.emit(f"已导出全部数据集: {path}")
                except Exception as e:
                    QMessageBox.warning(self, "导出失败", str(e))
        else:
            # 导出选中
            path, _ = QFileDialog.getSaveFileName(
                self, "导出选中数据集", "", "JSON Files (*.json)")
            if path:
                try:
                    import json
                    data = {
                        'version': 1,
                        'datasets': {
                            name: self._store.get(name).to_dict()
                            for name in checked
                        },
                    }
                    with open(path, 'w', encoding='utf-8') as f:
                        json.dump(data, f, indent=2, ensure_ascii=False, default=str)
                    self.status_update.emit(f"已导出 {len(checked)} 个数据集: {path}")
                except Exception as e:
                    QMessageBox.warning(self, "导出失败", str(e))
