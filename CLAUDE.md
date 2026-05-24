# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

GachaStat — 一个灵活的抽卡（gacha）概率模拟与统计分析系统，支持多池子、保底机制、资源管理、多种抽卡策略，以及丰富的后验分析（GDR/脆弱性/最差影响/过程分析/策略比较）。当前版本 v1.9.0。

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

所有面板使用 **QThread + Worker** 模式执行模拟，通过 `progress`/`finished`/`error` 信号通信。图表使用 matplotlib 渲染到临时 PNG，通过 `QLabel.setPixmap()` 显示。中文字体通过 `visualization/font_config.py` 配置。

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

### 计划文件约定

- 当我要求做计划时，应在 `docs/` 文件夹内新建一个独立的 `.md` 文件作为计划文件（而非写入 Claude 内部 plans 目录），计划文件应使用中文命名，命名应能体现计划主题
- 所有大型计划文件均应在 `docs/计划汇总.md` 中登记，注明日期、状态（已完成/进行中/未执行）及简要说明
- 当我要求更新/更正/更改已有计划时，应**在原文件上增量修改**，尽可能**不整段删除或缩减概括**原有的内容，而只做：**标记**（标注状态、依赖、风险）、**替换**（更正错误的部分）、**更正**（修正描述或方案）和**补充**（追加新内容）。保留历史讨论痕迹有助于后续回溯决策上下文
- 将计划文件移入 `archive/` 前，如该计划中有**搁置**（shelved）或**放弃**（abandoned）的条目，应先将搁置条目的内容补充到 `docs/搁置计划记录.md` 中，再执行归档

## 已知问题

1. **weapon_character_ratio 始终为 0**：`GDRContext.weapon_character_map` 无配置入口，需在配置系统新增角色-武器对应表
2. **per_pool_analysis.py 的 success_func 默认值**：`compute_transition_matrices()` 的 `success_func` 参数默认为 `None` 时，使用内联逻辑遍历 `List[InfoVector]` 按 `action_type == 'draw'` 判断（line 196-206）。调用方可通过传入基于 `SuccessChecker` 的 lambda 覆盖，但当前调用方（`analysis_panel.py`）未传入自定义 `success_func`
3. **多面板 CPU 争抢**：各面板 Worker 线程无全局协调
4. **`_extract_cost_per_draw` 只取第一个池**：`resource_search_panel.py`（line 80-91）和 `retreat_search.py`（line 107+）的实现均遍历池列表但只返回第一个有效成本值，多池成本不同时可能不准确
5. **转变分析不显示结果图片**（2026-05-24 发现）：代码逻辑存在于 `analysis_panel.py:1265-1355`，但 `transition_flags` 可能因 `DrawSequenceExtractor._update_transition()` 首行的 `if not self._pool_end_times: return` 而未被填充，导致四层守卫条件中某层跳过、静默无输出。也缺少显式的错误提示——当所有守卫都失败时用户看不到任何原因说明。P11 实施时应一并修复（添加 else 分支输出警告、确保数据链路完整）

## 未完成计划

见 `docs/计划汇总.md`——计划状态动态变化，以该文件为准，此处不重复。

## 扩展指南

**添加新 GDR 指标**：在 `core/gdr.py` 实现 `_gdr_xxx(compact, ...)` → 在 `UNIFIED_GDR_REGISTRY` 添加 `GDRDefinition` → 所有面板下拉列表通过 `populate_gdr_combo()` 自动更新

**添加新策略**：在 `core/strategy.py` 实现策略类（继承 `Strategy`，实现 `select_action(ctx)`）→ 在 `STRATEGY_REGISTRY` 注册 → 策略下拉列表自动包含

**添加新停止条件**：在 `core/stop_condition.py` 实现条件类（继承 `StopCondition`，实现 `check()` 和 `description()`）→ 在 `STOP_CONDITION_REGISTRY` 注册

**添加新分析面板**：在 `gui/` 创建新面板（QWidget + Worker QThread）→ 在 `MainWindow._setup_ui()` 添加 Tab → 通过 `set_store()` 接收配置

**添加新配置项**：在 `ConfigStore` 添加字段 → 在 `config_io.py` 添加读写逻辑 → 在 `config_panel.py` 添加 UI → 在 `SimulationEnvBuilder` 中使用
