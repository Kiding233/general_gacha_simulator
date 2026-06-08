# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

GachaStat — 一个灵活的抽卡（gacha）概率模拟与统计分析系统，支持多池子、保底机制、资源管理、多种抽卡策略，以及丰富的后验分析（GDR/脆弱性/最差影响/过程分析/策略比较）。当前版本 v1.10.0。

## 技术栈

- Python 3.10+，GUI 使用 PyQt6，数值计算使用 numpy，绑图使用 matplotlib
- 并行模拟使用 `multiprocessing.Pool` + worker initializer 模式
- 测试框架：pytest + pytest-cov

## 常用命令

```bash
# 安装依赖
pip install -e ".[dev]"           # 含 pytest/pytest-cov

# 启动 GUI
python -m gacha_simulator.main    # 直接 GUI
python -m gacha_simulator.run     # 自动选择 GUI/CLI（PyQt6 不可用时回退 CLI）

# CLI 模拟
python -m gacha_simulator.cli -n 1000 -w 4 -s 42

# 运行测试
pytest                            # 全部测试
pytest tests/core/test_pool.py    # 单个测试文件
pytest -k "test_draw"             # 按名称过滤
pytest --cov=gacha_simulator      # 含覆盖率
```

## 架构分层

```
gacha_simulator/
├── core/       # 核心引擎：池子、状态、策略、保底、GDR、各类分析算法（无 GUI 依赖）
├── service/    # 业务层：GachaService（单次模拟循环）、batch_simulator（并行批量桥梁）
├── gui/        # PyQt6 面板（配置/批量模拟/统计分析/过程分析/策略优化/退路分析/最差影响/策略比较）
├── generator/  # 排期/目标生成器
├── config/     # 默认配置文件（| 分隔的文本格式）
└── visualization/  # matplotlib 中文字体配置
```

## 核心数据流

```
用户配置 → ConfigStore → SimulationEnvBuilder.from_config_store() → SimulationEnv
                                                                       ↓
GachaService(pools, strategy, stop_cond, ...) ← _wk_init() 注入子进程全局变量
                                                                       ↓
GachaService.run_simulation(initial_state, collector=CompactCollector()) → CompactResult
                                                                       ↓
SharedResultCollector.on_result(compact) → 边提取边丢弃 → 各面板读取聚合数据
```

### 两种模拟模式

| 模式 | 方法 | 输出 | 用途 |
|------|------|------|------|
| 紧凑模式 | `run_simulation_compact()` 或 `run_simulation(collector=CompactCollector())` | `CompactResult` | 主流路径，内存高效 |
| 完整模式 | `run_simulation(collector=InfoVectorCollector())` | `List[InfoVector]` | 需逐抽详细记录时使用 |

`CompactResult`（`core/result_types.py`）是 dataclass，包含逐抽序列（`draw_card_ids`、`draw_pool_ids`、`draw_pity` 等）、汇总统计（`total_draws`、`card_counts`、`total_consumed`）、各池结束快照（`pool_end_resources`）。提供 `to_dict()` / `from_dict()` 序列化，以及 `get()` / `__getitem__` / `__contains__` 向后兼容接口。元数据字段：`strategy_name`、`result_version`、`generated_at`。

## 关键子系统

### 策略系统（`core/strategy.py`）

`STRATEGY_REGISTRY` 注册 7 种策略，统一实现 `select_action(self, ctx: StrategyContext) -> Action` 接口：

| key | 显示名 | 决策逻辑 |
|-----|--------|---------|
| `smart` | 按需追卡 | 优先兑换 → 按目标追卡 → 等待 |
| `pool_quota` | 指定池配额 | 每池指定抽卡上限后切换 |
| `pity_reserve` | 保底预留 | 只在保底概率 ≥ 阈值时抽卡 |
| `stop_on_target` | 目标即停 | 抽到 up/目标卡后停止 |
| `target_hunting` | 指定池追卡 | 只在指定池子抽卡 |
| `fixed_count` | 固定次数 | 抽满固定次数后等待 |
| `draw_target` | 指定目标抽卡 | 从指定池抽卡直到获得目标（内部策略，不在 GUI 策略列表显示） |

`StrategyContext` dataclass 封装策略所需的全部信息：`state`、`current_pools`、`all_pools`、`future_schedules`、`target_cards`、`stop_condition`、`_pity_engine`/`_pity_state`（下划线前缀保护）、`acquired`（仅有效卡，不含 `_no_card`）、`pool_draw_counts`、`total_draws`、`last_draw_pity_triggered`、`ssr_ids`、`_pity_cache`（保底概率缓存）。`get_pity_probabilities(pool_id)` 惰性计算保底概率，只有 `PityReserveStrategy` 调用。

工厂函数：`create_strategy(name, params)` / `strategy_type_to_key(display_name)` / `strategy_key_to_type(key)`

### 停止条件（`core/stop_condition.py`）

`STOP_CONDITION_REGISTRY` 注册 6 种条件：`all_pools_end`、`fixed_action_count`、`resource_threshold`、`target_acquired`、`last_draw_card`、`time_limit`。工厂函数：`create_stop_condition(name, params)`。

### 保底系统（`core/pity.py`）

`PityEngine` 管理多池多保底机制：
- **软保底（soft pity）**：计数器从 `start_at` 开始生效，概率线性/指数/阶梯上升至 `end_at` 时 100%，目标概率按 `target_distribution` 权重分配
- **硬保底（hard pity）**：计数器达到 `threshold` 时 100% 触发
- **重置条件**：`any_ssr`（任何 SSR 重置）、`featured`（仅限定 SSR 重置）、`never`
- **多保底叠加**：一个池可适用多个保底机制，按顺序叠加调整概率

### GDR 系统（`core/gdr.py` + `core/generalized_drop_rate.py`）

`UNIFIED_GDR_REGISTRY` 定义 13 种广义出率指标，分为三类：

**目标达成类**（值域 [0,1]）：`target_achievement`（加权目标达成率）、`target_collection`（种类收集率）、`all_targets`（全部达成 0/1）、`ssr_collection`（SSR 全收集率）

**资源效率类**：`resource_remaining`、`resource_efficiency`、`extra_target`、`non_pity_draws`、`pity_draws`

**加权综合类**（需用户配置权重）：`weighted_satisfaction`（desire + miss_cost 权重）、`total_card_value`（card_value 权重）、`per_pool_draw_rate`、`weapon_character_ratio`（需角色-武器对应表，当前无配置入口，始终返回 0.0）

每种 GDR 有两种计算路径：`compute_from_compact`（主流，O(1)）和 `compute_from_history`（兼容旧代码，O(T)）。`SuccessChecker` 统一判断单次模拟是否成功（GDR 值 ≥ 阈值）。

### 过程分析（`core/process_trace.py` + `core/process_analysis.py`）

对每次模拟的每个池推断事件类型（A 维度），共 7 种：`pity_hit`、`early_hit`、`miss`、`skip`、`ignore`、`exchange`、`no_exchange`。其中 `exchange`/`no_exchange` 用于兑换池（2026-05-17 已实现），资源池事件当前跳过（`continue`）不产生轨迹条目。池子成败（B 维度）由池子级 GDR 阈值独立判定。四种交叉统计：AA（事件模式分布）、BB（成败模式分布）、AB（事件→成败条件概率）、BA（成败→事件条件概率）。支持 5 种事件组合模式（raw/sequence/set/count_set/custom）+ 4 种成败组合模式。

### 流式分析（`core/streaming.py`）

`SharedResultCollector` + `StreamingAnalyzer` 实现边模拟边提取边丢弃，内存占用与模拟次数 N 无关（从 O(N) 降为 O(1)）。注册多个 extractor，每次模拟完成后立即提取并丢弃 compact 数据。

## 并行模拟架构

`run_batch_parallel()`（`service/batch_simulator.py`）使用 `multiprocessing.Pool(initializer=_wk_init, initargs=(...))` 模式：
- 11 个模块级全局变量（`_wk_pools`、`_wk_schedule_mgr`、`_wk_end_time` 等）通过 initializer 注入子进程
- 策略类已不再直接依赖 `_wk_*` 全局变量（通过 `StrategyContext` 传入信息），但 worker 机制仍使用全局变量
- 消除方案（`docs/Worker全局变量消除方案.md`）：将 11 个全局变量合并为 1 个 `_wk_env: SimulationEnv`
- 单进程路径（`max_workers <= 1`）直接在主进程调用，全局变量可能被意外修改

`SimulationEnvBuilder.from_config_store()` 是 GUI 层和核心层之间的桥梁，将 `ConfigStore` 转换为所有运行时对象。

## GUI 架构

`MainWindow` 包含 10 个 Tab：配置 → 批量模拟 → 统计分析 → 过程分析 → 最多目标卡 → 最少资源 → 退路分析 → 最差影响 → 策略比较 → 敏感度分析（开发中）。

所有面板使用 **QThread + Worker** 模式执行模拟，通过 `progress`/`finished`/`error` 信号通信。图表使用 Plotly 通过 `ChartWebView` (PyQt6-WebEngine) 渲染，旧 matplotlib 路径仅保留中文字体配置。

面板通过 `set_store(ConfigStore)` 和 `set_config_panel()` 接收配置，通过 `status_update` 信号报告状态栏消息。

## 配置文件格式

所有配置文件位于 `config/`，使用 `|` 分隔的文本格式，通过 `core/config_io.py` 的 `load_store_from_directory()` / `save_store_to_directory()` 读写。

- `schedule.txt`：池ID | 名称 | 开始天 | 结束天 | 成本 | 分布文件 | [绑定参数] | [目标卡]
- `pools/*.txt`：卡ID | 稀有度 | 概率(%) | 是否限定 | [资源奖励]
- `pity.txt`：保底名 | 类型(soft/hard) | 参数 | 目标分布 | 重置条件 | 适用的池
- `targets.txt`：卡ID:数量（每行一个）
- `gains.txt`：资源类型 | 每日数量 | 开始天 | 结束天
- `cards.txt`：卡ID | 名称 | 稀有度 | 所属池列表
- `resources.txt`：资源ID | 显示名
- `initial_resources.txt`：资源ID:数量

## 关键约定

- PR 代码变更限制在 `gacha_simulator/` 目录，不得修改 `tests/`、`output/`、`pyproject.toml`、`README.md`
- 版本号在 `gacha_simulator/_version.py`，遵循 Pride Versioning（PATCH=SHAME, MINOR=DEFAULT, MAJOR=PROUD）
- 所有分析面板从 `CompactResult` 列表提取数据，不再使用旧的 `InfoVector` 路径
- 策略不维护可变运行时状态（`acquired`、`pool_draw_counts` 等由 `StrategyContext` 传入）

### 文档与计划约定

项目文档按面板/子系统聚合在 `docs/01-活跃/` 下。每个模块文件夹内含六文件：
`00-档案`（设计意图）→ `01-理论`（假设/局限）→ `02-实施`（代码位置）→ `03-审计`（对齐检查）
→ `04-问题`（P0/P1/P2动态待办）→ `05-笔记`（临时捕获）。

完整改进计划作为主题计划文件放在模块文件夹内，不被拆散。

- **单一入口**：`docs/01-活跃/00-本周聚焦.md`——每周只聚焦一个模块
- **全局索引**：`docs/00-meta/模块状态矩阵.md`——P编号+一句话+文件位置
- **新计划归入对应模块文件夹**，不新建独立文件在顶层；计划文件中文命名；**在模块状态矩阵注册编号后，将编号置于文件名最前面**（如 `P30 策略文档补充计划.md`）
- **搁置条目**在 `docs/00-meta/搁置计划记录.md` 中登记，标注归属模块
- **模块完成后整包移入** `docs/03-归档/`
- **不维护全局计划汇总**——模块状态矩阵为精简索引
- 计划文件**增量修改**：标注/替换/更正/补充，不整段删除
- 归档前搁置条目需先补充到搁置记录

### 文档维护工作流

- **每次会话结束时**：将关键结论写入当前模块的 `05-笔记.md`（带日期）；如有代码变更则更新 `02-实施.md`
- **新建模块时**：创建六文件骨架 → 读实际代码填写 `02-实施.md` → 从审查报告拆入 `01-理论.md`
- **计划完成时**：主题计划 → `99-历史/`；更新 `02-实施.md` + `04-问题.md` + `模块状态矩阵.md`
- **每周清理时**：清理 `05-笔记.md` + `04-收件箱/`；更新 `00-本周聚焦.md` + `模块状态矩阵.md`

## 已知问题

1. **weapon_character_ratio 始终为 0**：`GDRContext.weapon_character_map` 无配置入口，需在配置系统新增角色-武器对应表
2. **多面板 CPU 争抢**：各面板 Worker 线程无全局协调
3. **`_extract_cost_per_draw` 只取第一个池**：`resource_search_panel.py`（line 80-91）和 `retreat_search.py`（line 107+）的实现均遍历池列表但只返回第一个有效成本值，多池成本不同时可能不准确

## 未完成计划

见 `docs/00-meta/模块状态矩阵.md` 和各模块 `04-问题.md`。

## 扩展指南

**添加新 GDR 指标**：在 `core/gdr.py` 实现 `_gdr_xxx(compact, ...)` → 在 `UNIFIED_GDR_REGISTRY` 添加 `GDRDefinition` → 所有面板下拉列表通过 `populate_gdr_combo()` 自动更新

**添加新策略**：在 `core/strategy.py` 实现策略类（继承 `Strategy`，实现 `select_action(ctx)`）→ 在 `STRATEGY_REGISTRY` 注册 → 策略下拉列表自动包含

**添加新停止条件**：在 `core/stop_condition.py` 实现条件类（继承 `StopCondition`，实现 `check()` 和 `description()`）→ 在 `STOP_CONDITION_REGISTRY` 注册

**添加新分析面板**：在 `gui/` 创建新面板（QWidget + Worker QThread）→ 在 `MainWindow._setup_ui()` 添加 Tab → 通过 `set_store()` 接收配置

**添加新配置项**：在 `ConfigStore` 添加字段 → 在 `config_io.py` 添加读写逻辑 → 在 `config_panel.py` 添加 UI → 在 `SimulationEnvBuilder` 中使用
