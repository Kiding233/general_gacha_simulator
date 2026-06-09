# 策略比较面板与模拟和比较的实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现策略比较面板 UI，让用户勾选多种策略、配置各策略参数，一键运行对比，用表格和图表展示各策略在 GDR、资源消耗、成功率等维度的表现。

**Architecture:** 新建 `StrategyComparisonPanel` 作为主窗口同级 Tab。对每个选中的策略调用 `run_batch_parallel`（已在前置基础设施中支持策略选择），收集结果后用 QTableWidget 和 matplotlib 图表对比展示。

**Tech Stack:** Python 3, PyQt6, matplotlib

**前置依赖:** 必须先完成 `2026-05-13-strategy-comparison-infra.md` 中的基础设施改造。

---

## 策略注册表（由前置基础设施提供）

```python
STRATEGY_REGISTRY = {
    'smart': {
        'display_name': '按需追卡',
        'description': '优先兑换→按目标追卡→等待下一个池',
        'factory': _create_smart_strategy,
        'params': {},
    },
    'pool_quota': {
        'display_name': '指定池配额',
        'description': '在指定池子抽指定数量后切换',
        'factory': _create_pool_quota_strategy,
        'params': {
            'pool_quotas': {
                'type': 'pool_int_map',
                'display_name': '各池配额',
                'default': {},
            },
        },
    },
    'pity_reserve': {
        'display_name': '保底预留',
        'description': '只在大保底概率≥阈值时才抽卡',
        'factory': _create_pity_reserve_strategy,
        'params': {
            'pity_threshold_pct': {
                'type': 'float',
                'display_name': '保底概率阈值(%)',
                'default': 80.0,
                'min': 0.0,
                'max': 100.0,
            },
        },
    },
    'stop_on_target': {
        'display_name': '目标即停',
        'description': '抽到当期up/目标卡就停止',
        'factory': _create_stop_on_target_strategy,
        'params': {
            'stop_on_featured': {
                'type': 'bool',
                'display_name': '抽到up即停',
                'default': True,
            },
            'stop_on_any_target': {
                'type': 'bool',
                'display_name': '抽到任意目标即停',
                'default': False,
            },
        },
    },
}
```

---

## 比较面板 UI 设计

```
┌─ 策略选择 ──────────────────────────────┐
│ ☑ 按需追卡    ☑ 指定池配额  ☑ 保底预留   │
│ ☐ 目标即停                                │
│                                          │
│ [指定池配额 参数]                         │
│   池A配额: [10]  池B配额: [5]             │
├─ 模拟参数 ──────────────────────────────┤
│ 每策略模拟次数: [1000]                    │
│ 并行进程数: [4]                           │
│ GDR判定: [目标达成率 ▼]  阈值: [1.0]      │
├─ [开始比较]  [停止]                       │
│ ████████████████ 75%                      │
├─ 比较结果 ──────────────────────────────┤
│ ┌───────┬──────┬──────┬──────┬──────┐    │
│ │策略    │成功率│均值抽│SSR数 │GDR   │    │
│ ├───────┼──────┼──────┼──────┼──────┤    │
│ │按需追卡│95.2% │87.3  │3.1   │0.98  │    │
│ │指定配额│89.1% │92.7  │3.8   │0.91  │    │
│ │保底预留│78.3% │105.2 │2.7   │0.82  │    │
│ └───────┴──────┴──────┴──────┴──────┘    │
│                                          │
│ [GDR分布对比图] [资源消耗对比图]           │
└──────────────────────────────────────────┘
```

---

## File Structure

| 文件 | 操作 | 职责 |
|------|------|------|
| `gui/strategy_comparison_panel.py` | 新建 | 策略比较面板 UI 和 Worker |
| `gui/main_window.py` | 修改 | 添加策略比较 Tab |

---

### Task 1: 新建策略比较面板

**Files:**
- Create: `gacha_simulator/gui/strategy_comparison_panel.py`

- [ ] **Step 1: 创建 StrategyComparisonWorker**

```python
class StrategyComparisonWorker(QThread):
    progress = pyqtSignal(str, int)
    finished = pyqtSignal(dict)
    error = pyqtSignal(object)

    def __init__(self, strategies_config, num_simulations, max_workers,
                 gdr_key, gdr_threshold, config_store):
        super().__init__()
        self.strategies_config = strategies_config  # {name: params}
        self.num_simulations = num_simulations
        self.max_workers = max_workers
        self.gdr_key = gdr_key
        self.gdr_threshold = gdr_threshold
        self.config_store = config_store
        self._should_stop = False

    def stop(self):
        self._should_stop = True

    def run(self):
        try:
            from .batch_simulator import SimulationEnvBuilder, run_batch_parallel, STRATEGY_REGISTRY
            from gacha_simulator.core.gdr import compute_success_probability, compute_gdr_from_compact

            env = SimulationEnvBuilder.from_config_store(self.config_store)
            target_specs = {tc.card_id: getattr(tc, 'quantity', 1) for tc in getattr(self.config_store, 'target_cards', [])}

            results = {}
            total = len(self.strategies_config)
            for i, (strategy_name, strategy_params) in enumerate(self.strategies_config.items()):
                if self._should_stop:
                    self.finished.emit(None)
                    return

                display_name = STRATEGY_REGISTRY.get(strategy_name, {}).get('display_name', strategy_name)
                self.progress.emit(f"正在模拟策略: {display_name} ({i+1}/{total})", int((i / total) * 100))

                histories = run_batch_parallel(
                    pools=env.pools,
                    schedule_mgr=env.schedule_mgr,
                    end_time=env.end_time,
                    pity_engine=env.pity_engine,
                    resource_gain=env.resource_gain,
                    pity_state_init=env.pity_state_init,
                    card_defs=env.card_defs,
                    target_specs=target_specs,
                    initial_resources=env.initial_resources,
                    num_simulations=self.num_simulations,
                    max_workers=self.max_workers,
                    seed=0,
                    strategy_name=strategy_name,
                    strategy_params=strategy_params or {},
                )

                success_prob = compute_success_probability(histories, target_specs, self.gdr_key, self.gdr_threshold)

                valid = [h for h in histories if h is not None]
                avg_draws = sum(h.get('total_draws', 0) for h in valid) / max(len(valid), 1)
                avg_ssr = 0
                for h in valid:
                    cc = h.get('card_counts', {})
                    for cid, cnt in cc.items():
                        if 'ssr' in cid.lower():
                            avg_ssr += cnt
                avg_ssr /= max(len(valid), 1)

                avg_gdr = 0
                for h in valid:
                    avg_gdr += compute_gdr_from_compact(h, target_specs, self.gdr_key)
                avg_gdr /= max(len(valid), 1)

                results[strategy_name] = {
                    'display_name': display_name,
                    'success_probability': success_prob,
                    'avg_draws': avg_draws,
                    'avg_ssr': avg_ssr,
                    'avg_gdr': avg_gdr,
                    'histories': histories,
                }

            self.progress.emit("比较完成", 100)
            self.finished.emit(results)

        except Exception as e:
            import traceback as tb
            tb.print_exc()
            class DetailedError(Exception):
                def __init__(self, msg):
                    self.msg = msg
                def __str__(self):
                    return self.msg
            self.error.emit(DetailedError(f"{type(e).__name__}: {e}\n\n{tb.format_exc()}"))
```

- [ ] **Step 2: 创建 StrategyComparisonPanel**

面板包含：
- 策略勾选区（QCheckBox 列表，从 STRATEGY_REGISTRY 动态生成）
- 各策略的参数配置区（根据 params 定义动态生成控件）
- 模拟参数区（模拟次数、并行数、GDR选择、阈值）
- 结果对比表格
- 结果对比图表（matplotlib 嵌入）

详细 UI 代码见实现阶段。

---

### Task 2: 集成到主窗口

**Files:**
- Modify: `gacha_simulator/gui/main_window.py`

- [ ] **Step 1: 导入并添加 Tab**

在 main_window.py 中导入 `StrategyComparisonPanel`，在 `_setup_ui` 中添加：

```python
self.comparison_panel = StrategyComparisonPanel()
self.comparison_panel.set_store(self._store)
self.tabs.addTab(self.comparison_panel, "策略比较")
```

在 `_on_tab_changed` 中添加 store 同步。

---

### Task 3: 验证

- [ ] **Step 1: 编译检查**

```bash
cd /workspace && python -m py_compile gacha_simulator/gui/strategy_comparison_panel.py && \
python -m py_compile gacha_simulator/gui/main_window.py && \
echo "ALL OK"
```

- [ ] **Step 2: 搜索残留引用**

确认所有 `run_batch_parallel` 调用都传了 `strategy_name` 和 `strategy_params`。
