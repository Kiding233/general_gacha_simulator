# Gacha Simulator 项目交接文档

> 当前版本：v1.9.0 | 最后更新：2026-05-20

---

## 1. 项目概述

Gacha Simulator 是一个**抽卡模拟器**，用于蒙特卡洛模拟手游抽卡系统的各种统计量。核心能力：

- 给定卡池配置、保底机制、资源获取规则和目标卡集合，运行 N 次独立模拟
- 计算成功率、资源消耗、GDR（广义出率）分布等统计量
- 支持策略比较、退路搜索、资源搜索、脆弱性分析、过程分析等高级功能
- PyQt6 GUI + CLI 双入口

技术栈：Python 3.14, PyQt6, multiprocessing, matplotlib（图表）

---

## 2. 文件结构

```
gacha_simulator/
├── main.py                    # 入口1：直接启动 GUI
├── run.py                     # 入口2：GUI/CLI 自动选择
├── cli.py                     # CLI 模式入口
├── _version.py                # 版本号（Pride Versioning）
│
├── config/                    # 默认配置文件（文本格式）
│   ├── schedule.txt           #   卡池时间表
│   ├── cards.txt              #   卡牌定义
│   ├── targets.txt            #   目标卡
│   ├── pity.txt               #   保底机制
│   ├── resources.txt          #   资源类型
│   ├── gains.txt              #   资源获取规则
│   ├── initial_resources.txt  #   初始资源
│   └── pools/                 #   各池出率分布
│       ├── character_pool.txt
│       ├── standard_pool.txt
│       └── weapon_pool.txt
│
├── core/                      # 核心模拟引擎（无 GUI 依赖）
│   ├── __init__.py            #   统一导出
│   ├── state.py               #   GachaState：模拟状态（资源、时间、计数器）
│   ├── action.py              #   Action/DrawAction/WaitAction：操作类型
│   ├── info_vector.py         #   InfoVector：每步操作记录
│   ├── result_types.py        #   CompactResult：紧凑结果 dataclass（替代裸 dict）
│   ├── collector.py           #   SimulationCollector/InfoVectorCollector/CompactCollector
│   ├── pool.py                #   Pool/Reward：卡池定义与抽选
│   ├── schedule.py            #   PoolSchedule/PoolScheduleManager：时间调度
│   ├── strategy.py            #   Strategy 抽象基类 + 6种策略 + STRATEGY_REGISTRY + StrategyContext
│   ├── stop_condition.py      #   StopCondition 抽象基类 + 6种条件 + STOP_CONDITION_REGISTRY
│   ├── pity.py                #   PityEngine/PityState：保底机制引擎
│   ├── resource_gain.py       #   ResourceGain：资源获取计算
│   ├── target_card.py         #   TargetCard/TargetCardSet：目标卡管理
│   ├── config_store.py        #   ConfigStore：配置数据容器（dataclass）
│   ├── config_io.py           #   配置文件读写
│   ├── pool_config.py         #   PoolConfig/CardDef/CardCatalog：配置解析
│   ├── distribution.py        #   概率分布工具
│   ├── gdr.py                 #   UNIFIED_GDR_REGISTRY：13种广义出率定义 + SuccessChecker
│   ├── streaming.py           #   StreamingAnalyzer/SharedResultCollector：流式结果收集
│   ├── forward_backward.py    #   前进法/后退法/资源搜索数据结构
│   ├── gdr_analysis.py        #   GDR 分布分析
│   ├── per_pool_analysis.py   #   逐池分析
│   ├── process_trace.py       #   PoolEvent/SampleTrace/infer_events：事件推断
│   ├── process_analysis.py    #   AA/BB/AB/BA 交叉统计 + 事件模式分类
│   ├── risk_analysis.py       #   风险分析
│   ├── vulnerability.py       #   脆弱性分析（条件分布、核密度回归）
│   ├── worst_impact.py        #   最差影响分析（条件分布下尾分位数）
│   ├── retreat_config.py      #   退路搜索配置
│   └── retreat_search.py      #   RetreatSearchEngine：退路搜索 + Pareto 前沿
│
├── gui/                       # GUI 层（PyQt6）
│   ├── __init__.py            #   导出 MainWindow
│   ├── main_window.py         #   MainWindow：主窗口 + Tab 管理
│   ├── batch_simulator.py     #   SimulationEnv + run_batch_parallel：并行模拟桥梁
│   ├── config_panel.py        #   ConfigPanel：配置编辑（7个Tab）
│   ├── gacha_panel.py         #   GachaPanel：单次/批量模拟
│   ├── analysis_panel.py      #   AnalysisPanel：综合分析（15+种图表）
│   ├── strategy_panel.py      #   StrategyPanel：策略比较（成功率趋势图）
│   ├── resource_search_panel.py # ResourceSearchPanel：二分搜索最少资源
│   ├── retreat_panel.py       #   RetreatPanel：退路分析
│   ├── retreat_search_panel.py # RetreatSearchPanel：退路搜索
│   ├── worst_impact_panel.py  #   WorstImpactPanel：最差影响分析
│   ├── process_analysis_panel.py # ProcessAnalysisPanel：过程分析（5个Tab）
│   ├── strategy_comparison_panel.py # StrategyComparisonPanel：策略比较
│   └── about_dialog.py        #   关于对话框
│
├── service/                   # 业务逻辑层
│   ├── gacha_service.py       #   GachaService：模拟执行引擎（run_simulation / run_simulation_compact）
│   ├── analysis_service.py    #   AnalysisService：分析服务
│   └── config_service.py      #   ConfigService：配置服务
│
├── generator/                 # 生成器（辅助工具）
│   ├── schedule_generator.py  #   时间表生成
│   └── target_generator.py    #   目标卡生成
│
├── visualization/             # 可视化工具
│   └── font_config.py         #   中文字体配置
│
└── resources/                 # 资源文件
    └── app_icon.png           #   应用图标（256×256）

docs/
└── superpowers/
    ├── PLAN_SUMMARY.md        #   项目计划汇总
    ├── plans/                 #   实施计划
    │   ├── archive/           #     已完成（10个）
    │   ├── 2026-05-13-strategy-comparison*.md
    │   ├── 2026-05-15-process-analysis.md
    │   ├── 2026-05-16-adaptive-simulation.md
    │   └── 2026-05-18-bootstrap-stability-analysis.md
    └── specs/                 #   设计文档
        ├── archive/           #     已完成（6个）
        ├── 2026-05-15-process-analysis-design.md
        └── 2026-05-16-adaptive-simulation-design.md
```

---

## 3. 核心架构与信息流

### 3.1 模拟执行全流程

```
用户配置 → ConfigStore → SimulationEnvBuilder.from_config_store() → SimulationEnv
                                                                    ↓
GachaService(pools, strategy, stop_cond, ...) ← _wk_init() 注入子进程全局变量
                                                                    ↓
GachaService.run_simulation(initial_state, collector=CompactCollector()) → CompactResult
                                                                    ↓
SharedResultCollector.on_result(compact) → 提取聚合数据
                                                                    ↓
各面板读取聚合数据 → 计算 GDR / 统计量 / 图表
```

详细步骤：

1. **配置加载**：`config_io.load_store_from_directory()` 读取 `config/` 下的文本文件，填充 `ConfigStore` dataclass
2. **环境构建**：`SimulationEnvBuilder.from_config_store(config_store)` 将 `ConfigStore` 转换为 `SimulationEnv`（Pool 对象、PityEngine、ScheduleManager 等）
3. **并行模拟**：`run_batch_parallel()` 使用 `multiprocessing.Pool`，通过 `_wk_init` 将静态环境注入每个子进程的全局变量，每个子任务调用 `_wk_run_single(seed, target_specs, initial_resources)`
4. **单次模拟**：`GachaService.run_simulation_compact()` 执行主循环——策略选择动作 → 执行抽卡/等待 → 更新状态 → 收集 compact 数据
5. **结果收集**：`SharedResultCollector.on_result(compact)` 边模拟边提取，内存与 N 无关

### 3.2 两种模拟模式

| 模式 | 方法 | 输出 | 用途 |
|------|------|------|------|
| **完整模式** | `run_simulation(collector=InfoVectorCollector())` | `List[InfoVector]` | 需要逐抽详细记录时使用（如过程分析） |
| **紧凑模式** | `run_simulation(collector=CompactCollector())` 或 `run_simulation_compact()` | `CompactResult` | 绝大多数场景使用，内存高效 |

`CompactResult` 是 dataclass，替代了原来的裸 `Dict[str, Any]`，提供 `.get()` / `__getitem__` / `__contains__` 向后兼容接口，以及 `.to_dict()` / `.from_dict()` 序列化方法。

新增元数据字段：
- `strategy_name: str` — 使用的策略类名
- `result_version: int` — 结果格式版本号（当前为 1）
- `generated_at: float` — 结果生成时间戳

### 3.3 GDR（广义出率）系统

`UNIFIED_GDR_REGISTRY` 定义了 13 种 GDR 指标，每种都有两种计算路径：

| key | 显示名 | 默认阈值 | 值域 | 需要权重 |
|-----|--------|----------|------|----------|
| `target_achievement` | 简单目标达成率 | 1.0 | [0,1] | 否 |
| `target_collection` | 目标卡收集率 | 1.0 | [0,1] | 否 |
| `all_targets` | 抽出全部目标卡 | 1.0 | {0,1} | 否 |
| `ssr_collection` | SSR收集率 | 0.05 | [0,1] | 否（需ssr_ids） |
| `resource_remaining` | 资源剩余 | 0.0 | (-∞,+∞) | 否 |
| `extra_target` | 额外目标卡 | 0.0 | [0,+∞) | 否 |
| `non_pity_draws` | 非保底抽卡数 | 0.0 | [0,+∞) | 否 |
| `pity_draws` | 保底抽卡数 | 0.0 | [0,+∞) | 否 |
| `resource_efficiency` | 资源转化效率 | 0.01 | [0,+∞) | 否 |
| `per_pool_draw_rate` | 每池下池出卡率 | 0.0 | [0,+∞) | 否 |
| `weapon_character_ratio` | 专武角色比 | 0.0 | [0,+∞) | 否（需weapon_map） |
| `weighted_satisfaction` | 加权满意度 | 0.0 | (-∞,+∞) | desire+miss_cost |
| `total_card_value` | 总出卡价值 | 0.0 | [0,+∞) | card_value |

- `compute_from_compact(compact_dict, ...)` → 从 compact dict 计算（高效，主流路径）
- `compute_from_history(history_list, ctx)` → 从 InfoVector 列表计算（兼容旧代码）
- `SuccessChecker` 统一了"某次模拟是否成功"的判断逻辑（GDR值 ≥ 阈值）

### 3.4 策略系统

`STRATEGY_REGISTRY`（在 `core/strategy.py` 中）注册了 6 种策略：

| key | 显示名 | 逻辑 |
|-----|--------|------|
| `smart` | 按需追卡 | 优先兑换→按目标追卡→等待 |
| `pool_quota` | 指定池配额 | 每池指定抽卡上限 |
| `pity_reserve` | 保底预留 | 只在保底概率≥阈值时抽 |
| `stop_on_target` | 目标即停 | 抽到up/目标卡就停止 |
| `target_hunting` | 指定池追卡 | 在指定池中追目标卡 |
| `fixed_count` | 固定次数 | 固定抽卡次数后等待 |

所有策略统一实现 `select_action(self, ctx: StrategyContext) -> Action` 接口。

`StrategyContext` dataclass 包含：
- `state` / `current_pools` / `all_pools` / `future_schedules` / `target_cards` / `stop_condition`
- `_pity_engine` / `_pity_state`：保底引擎和状态（用于 `get_pity_probabilities()`）
- `acquired` / `pool_draw_counts` / `total_draws` / `last_draw_pity_triggered`：模拟统计
- `ssr_ids: Set[str]`：SSR 卡 ID 集合
- `_pity_cache: Dict[str, Dict[str, float]]`：保底概率缓存

工厂函数：`create_strategy(name, params)` / `strategy_type_to_key(display_name)` / `strategy_key_to_type(key)`

### 3.5 停止条件系统

`STOP_CONDITION_REGISTRY`（在 `core/stop_condition.py` 中）注册了 6 种停止条件：

| key | 显示名 | 逻辑 |
|-----|--------|------|
| `all_pools_end` | 所有池结束 | 所有池子到期后停止 |
| `fixed_action_count` | 固定次数 | 抽满指定次数后停止 |
| `resource_threshold` | 资源阈值 | 资源达到阈值时停止 |
| `target_acquired` | 目标获得 | 获得指定目标卡后停止 |
| `last_draw_card` | 抽到即停 | 最后一次抽到指定卡时停止 |
| `time_limit` | 时间限制 | 模拟时间达到限制后停止 |

工厂函数：`create_stop_condition(name, params)` / `stop_condition_type_to_key(display_name)` / `stop_condition_key_to_type(key)`

### 3.6 保底机制

`PityEngine` 管理多种保底机制，支持：
- **软保底**（soft pity）：从 `start_at` 抽开始概率线性/指数上升，到 `end_at` 抽达到 100%
- **硬保底**（hard pity）：达到 `threshold` 抽时 100% 触发
- 每种保底可指定 `target_distribution`（如限定SSR 50%/常驻SSR 50%）
- `reset_condition`：`any_ssr`（任何SSR重置）或 `featured`（仅限定SSR重置）
- `pools` 字段支持通配符匹配（如 `character_*`）

### 3.7 过程分析系统

**事件推断**（`process_trace.py`）：从 compact dict 的逐抽记录推断每个池的事件类型：
- `pity_hit`：保底出（目标卡 + 保底触发）
- `early_hit`：提前出（目标卡 + 无保底触发）
- `miss`：没出（无目标卡 + 有抽卡）
- `skip`：跳过（有目标卡在池中但未抽）
- `ignore`：忽略（池中无目标卡且未抽）

**交叉统计**（`process_analysis.py`）：
- AA：事件模式分布（5种模式 + 自定义模式）
- BB：成败模式分布（池子级/整体级）
- AB：事件模式 × 成败模式交叉分布
- BA：成败模式 × 事件模式交叉分布

### 3.8 流式架构

`SharedResultCollector` 实现了边模拟边提取边丢弃：
- 注册多个 `extractor`（如 `aggregate`、`process_data`）
- 每次模拟完成调用 `on_result(compact)`，各 extractor 提取所需字段
- 最终通过 `get_extracted(name)` 获取聚合结果
- 内存与 N 无关（不保存 N 条完整 compact dict）

---

## 4. GUI 层架构

### 4.1 主窗口

`MainWindow` 是 `QMainWindow`，包含一个 `QTabWidget`，各面板以 Tab 形式组织：

| Tab序 | 面板 | 功能 |
|-------|------|------|
| 0 | ConfigPanel | 配置编辑（7个子Tab：卡牌、资源、卡池、保底、获取、初始资源、目标卡） |
| 1 | GachaPanel | 单次/批量模拟 |
| 2 | AnalysisPanel | 综合分析（15+种图表） |
| 3 | StrategyPanel | 策略比较（成功率趋势图） |
| 4 | ResourceSearchPanel | 二分搜索最少资源 |
| 5 | RetreatPanel | 退路分析 |
| 6 | RetreatSearchPanel | 退路搜索 |
| 7 | WorstImpactPanel | 最差影响分析 |
| 8 | ProcessAnalysisPanel | 过程分析（5个子Tab） |
| 9 | StrategyComparisonPanel | 策略比较 |

### 4.2 Worker 线程模式

所有面板的模拟都使用 **QThread + Worker** 模式：

```python
class XxxWorker(QThread):
    progress = pyqtSignal(str, int)   # 进度消息 + 百分比
    finished = pyqtSignal(object)     # 结果对象
    error = pyqtSignal(object)        # 错误对象

    def run(self):
        # 构建模拟环境 → 运行模拟 → 发射 finished 信号
```

面板类持有 `self._worker`，在 `_on_run_clicked()` 中创建并启动，在 `_on_finished()` 中处理结果。

**重要**：多个面板可以同时运行 Worker，它们共享 CPU 资源但没有全局协调，可能造成 CPU 争抢。

### 4.3 batch_simulator.py 的角色

这是 GUI 层和核心层之间的**桥梁**：

1. `SimulationEnv`：将 `ConfigStore` 转换为模拟所需的所有对象
2. `SimulationEnvBuilder.from_config_store()`：环境构建工厂
3. `run_batch_parallel()`：并行模拟入口，支持 `on_result` 回调（流式）和批量返回
4. `_wk_init()` / `_wk_run_single()`：multiprocessing Worker 的初始化和执行函数

注意：`STRATEGY_REGISTRY` 已迁移到 `core/strategy.py`，策略不再定义在 `batch_simulator.py` 中。

### 4.4 图表渲染

所有面板使用 matplotlib 渲染图表，流程：
1. 创建 `fig, ax = plt.subplots(figsize=..., dpi=400)`
2. 绑定数据、设置样式
3. 保存到临时 PNG 文件
4. 通过 `QLabel.setPixmap()` 显示

中文字体通过 `visualization/font_config.py` 的 `configure_chinese_font()` 配置。

---

## 5. 配置文件格式

所有配置文件位于 `config/` 目录，使用 `|` 分隔的文本格式：

### schedule.txt
```
池ID | 名称 | 开始天 | 结束天 | 成本 | 分布文件 | [绑定参数] | [目标卡]
character_1 | 角色池1 | 0 | 21 | draw_resource:160 | character_pool.txt | ssr=char1,char2 | char1:1
```

### pools/*.txt（出率分布）
```
卡ID | 稀有度 | 概率(%) | 是否限定 | [资源奖励]
char1 | SSR | 0.6 | 1 | draw_resource:0
sr1 | SR | 5.1 | 0 |
r1 | R | 94.3 | 0 |
```

### pity.txt
```
保底名 | 类型(soft/hard) | 参数 | 目标分布 | 重置条件 | 适用的池
角色保底 | soft | start=74;end=90 | limited_ssr:50;standard_ssr:50 | any_ssr | *
```

### targets.txt
```
卡ID:数量
char1:1
```

### gains.txt
```
资源类型 | 每日数量 | 开始天 | 结束天
draw_resource | 100 | 0 | 21
```

---

## 6. 开发历史

### 版本时间线

| 版本 | 日期 | 类型 | 内容 |
|------|------|------|------|
| 1.0.0 | 05-07 | PROUD | 初始版本：核心模拟引擎、GUI、配置系统 |
| 1.1.0 | 05-08 | DEFAULT | 分析面板、风险分析、经验分布 |
| 1.1.1~1.1.4 | 05-09~10 | SHAME | 4个 bug 修复 |
| 1.2.0 | 05-13 | DEFAULT | 代码重构：统一模拟环境构建、GDR 成功率计算 |
| 1.3.0 | 05-13 | DEFAULT | 退路分析：脆弱性分析、退路搜索、Pareto 前沿 |
| 1.4.0 | 05-14 | DEFAULT | 最差影响分析、退路搜索二期 |
| 1.5.0 | 05-16 | DEFAULT | 权重配置统一、策略注册表 |
| 1.5.1~1.5.6 | 05-16 | SHAME | 6个遗留代码清理 |
| 1.5.7 | 05-16 | DEFAULT | 关于页面、版本号系统 |
| 1.6.0 | 05-16 | DEFAULT | GDR 注册表统一、SuccessChecker、修复5个数值不一致bug |
| 1.7.0 | 05-17 | DEFAULT | 流式模拟架构重构：SharedResultCollector，内存与N无关 |
| 1.8.0 | 05-17 | DEFAULT | 过程分析功能：事件推断、交叉统计、ProcessAnalysisPanel |
| 1.9.0 | 05-20 | DEFAULT | 策略代码重构：CompactResult + Collector模式 + StrategyContext + 6种策略统一 + 停止条件注册表 + 策略比较面板 + 保底概率缓存 + compact元数据 |

### 重大架构变更

1. **v1.2.0 代码重构**：消除 GUI 层重复的模拟环境构建代码，统一到 `SimulationEnvBuilder`
2. **v1.6.0 GDR 统一**：合并两套注册表为 `UNIFIED_GDR_REGISTRY`，创建 `SuccessChecker`
3. **v1.7.0 流式重构**：`SharedResultCollector` 替代保存全部 compact dict 的方式，内存从 O(N) 降为 O(1)
4. **v1.9.0 策略重构**：`CompactResult` 替代裸 dict；`SimulationCollector` 统一两种模拟模式；`StrategyContext` + `STRATEGY_REGISTRY` 统一 6 种策略；`STOP_CONDITION_REGISTRY` 统一 6 种停止条件；策略比较面板

---

## 7. 未完成计划

### P2：过程分析功能（续）

状态：核心已完成，4项待实现

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 兑换池/资源池事件 | 🔴高 | 需新增 `pool_types` 字段 + 4种新事件类型 |
| 保底名区分 | 🟡中 | 当前仅 raw 模式区分保底机制名 |
| success_distribution UI | 🟡中 | AB 分析中已计算但未展示 |
| 条件 GDR 分布 | 🟡中 | Task 9：以事件组合为条件查看任意 GDR 分布 |
| BB 可视化增强 | 🟢低 | 柱状图、热力图 |

### P3：Bootstrap 稳定性分析

状态：计划已完成，未开始实现

核心设计：
- `BootstrapEngine`：支持概率 CI、分布分位数 CI、AA/BB/AB/BA CI
- 默认 BCa 校正（修正偏度和偏度）
- 厚尾问题：标准 Bootstrap 在方差无限时不一致（Athreya 1987），需参数 Bootstrap（从 GPD 抽样）或 m-out-of-n
- 对偶变量法兼容：配对 Bootstrap（重抽样 N/2 对）
- TVD（总变差距离）衡量分布估计稳定性

### P4：自适应模拟次数与方差缩减

状态：设计已完成，未开始实现

- `AdaptiveSimController`：实时 RSE 监控，达到精度自动停止
- 对偶变量法：配对模拟降低方差
- EVT 尾部拟合：GPD 拟合改善 VaR/CVaR 精度

### P5：策略比较面板

状态：✅ 已完成（v1.9.0）

### P6：策略代码重构遗留项

状态：6项未实施

| 步骤 | 内容 | 优先级 |
|------|------|--------|
| 0.1 | 删除根目录 `worst_impact.py` | 🟢低 |
| 3.1 | `vulnerability.py` 的 `_is_success()` 替换为 `SuccessChecker` | 🟡中 |
| 3.3 | `analysis_panel.py` 的 GDR 调用统一为 `SuccessChecker` | 🟡中 |
| 3.4 | `UNIFIED_GDR_REGISTRY` 增加 `register_gdr()` 函数 | 🟡中 |
| 4.4 | 策略参数动态控件 | 🟡中 |
| 4.6 | GUI 面板权重获取改为 `set_store()` / 信号 | 🟢低 |

### 建议执行顺序

```
P2 (过程分析续) → P6 (重构遗留) → P3 (Bootstrap) → P4 (自适应+EVT)
```

依赖关系：
- P2 先行：新增事件类型影响 `process_data` 格式
- P6 独立：可随时执行
- P3 在 P4 之前：Bootstrap 先实现通用框架，EVT 作为尾部优化集成

---

## 8. 已知问题

1. **weapon_character_ratio 始终为 0**：`GDRContext.weapon_character_map` 无配置入口，需要在配置系统中新增角色-武器对应表
2. **per_pool_analysis.py 的 success_func**：仍使用内联逻辑（InfoVector 路径），未改用 SuccessChecker
3. **多面板 CPU 争抢**：各面板 Worker 线程无全局协调，同时运行会争抢 CPU
4. **_extract_cost_per_draw 只取第一个池**：如果多池成本不同可能不准确（已添加手动设置入口）

---

## 9. 关键设计决策

### 9.1 为什么 compact dict 而非 InfoVector 列表？

`run_simulation_compact()` 不构建 `List[InfoVector]`，而是直接收集聚合数据到 dict。原因：
- 内存：N=10000 时 InfoVector 列表可能占数百 MB，compact dict 每次模拟仅几 KB
- 速度：避免大量小对象创建和 GC
- 逐抽记录仍保留在 compact dict 的 `draw_card_ids` 等列表字段中，供过程分析使用

### 9.2 为什么策略定义从 batch_simulator.py 迁移到 core/strategy.py？

v1.9.0 重构后，6 种策略统一定义在 `core/strategy.py` 中，使用 `StrategyContext` 替代了 6 参数签名 + `observe()` 模式：
- `StrategyContext` dataclass 封装了策略需要的所有信息（状态、池、保底、统计等）
- `select_action(ctx)` 统一接口，消除了 `observe()` 和 `self.acquired` 自维护
- `STRATEGY_REGISTRY` + `create_strategy()` 工厂函数，GUI 层通过 ConfigStore 选择策略
- `worst_impact.py` 使用统一接口但固定选择特制策略 `_DrawTargetStrategy`

### 9.3 为什么 GDR 有两套计算路径？

- `compute_from_compact`：从 compact dict 计算，是主流路径（高效）
- `compute_from_history`：从 InfoVector 列表计算，兼容旧代码（如 analysis_panel 的某些图表）
- `UNIFIED_GDR_REGISTRY` 统一管理两种路径，`GDRDefinition` 的 `compute_from_history` 可为 None

### 9.4 multiprocessing 的 initializer 模式

`run_batch_parallel()` 使用 `Pool(initializer=_wk_init, initargs=(...))` 将模拟环境注入每个子进程的全局变量。原因：
- Pool 对象（Pool, PityEngine 等）包含不可 pickle 的内容
- 全局变量避免了每个任务序列化/反序列化的开销
- 代价是子进程内的策略必须是全局可访问的

---

## 10. 扩展指南

### 添加新的 GDR 指标

1. 在 `core/gdr.py` 中实现 `_gdr_xxx(compact, ...)` 函数
2. 在 `UNIFIED_GDR_REGISTRY` 中添加 `GDRDefinition` 条目
3. 所有面板的 GDR 下拉列表通过 `populate_gdr_combo()` 自动更新

### 添加新的策略

1. 在 `core/strategy.py` 中实现策略类（继承 `Strategy`，实现 `select_action(ctx: StrategyContext)`）
2. 在 `STRATEGY_REGISTRY` 中注册（key、display_name、description、class、params）
3. 策略面板的下拉列表会自动包含

### 添加新的停止条件

1. 在 `core/stop_condition.py` 中实现停止条件类（继承 `StopCondition`，实现 `check()` 和 `description()`）
2. 在 `STOP_CONDITION_REGISTRY` 中注册
3. 配置面板的停止条件下拉列表会自动包含

### 添加新的分析面板

1. 在 `gui/` 下创建新面板文件，继承 `QWidget`
2. 实现 Worker（QThread）+ 面板类
3. 在 `MainWindow._setup_ui()` 中添加 Tab
4. 通过 `set_store()` 接收 ConfigStore

### 添加新的配置项

1. 在 `core/config_store.py` 的 `ConfigStore` 中添加字段
2. 在 `core/config_io.py` 中添加读写逻辑
3. 在 `gui/config_panel.py` 中添加 UI 控件
4. 在 `gui/batch_simulator.py` 的 `SimulationEnvBuilder` 中使用新配置

---

## 11. 运行方式

```bash
# GUI 模式
python -m gacha_simulator.main
python -m gacha_simulator.run

# CLI 模式（PyQt6 不可用时自动回退）
python -m gacha_simulator.cli -n 1000 -w 4

# 直接运行
python gacha_simulator/main.py
python gacha_simulator/run.py
```

---

## 12. 文档索引

| 文档 | 路径 | 内容 |
|------|------|------|
| 项目计划汇总 | `docs/superpowers/PLAN_SUMMARY.md` | 所有计划的状态、依赖、兼容性 |
| 策略重构计划 | `docs/strategy_code_investigation_and_refactoring_plan.md` | v8，5阶段重构（含6项遗留） |
| 过程分析计划 | `docs/superpowers/plans/2026-05-15-process-analysis.md` | v8，含 Task 9 条件 GDR 分布 |
| 过程分析设计 | `docs/superpowers/specs/2026-05-15-process-analysis-design.md` | v6 |
| Bootstrap 计划 | `docs/superpowers/plans/2026-05-18-bootstrap-stability-analysis.md` | 完整设计 |
| 自适应模拟设计 | `docs/superpowers/specs/2026-05-16-adaptive-simulation-design.md` | 含 Bootstrap 兼容性 |
| 自适应模拟计划 | `docs/superpowers/plans/2026-05-16-adaptive-simulation.md` | |
| 策略比较计划 | `docs/superpowers/plans/2026-05-13-strategy-comparison*.md` | 2个文件 |
| 已归档计划 | `docs/superpowers/plans/archive/` | 10个已完成计划 |
| 已归档设计 | `docs/superpowers/specs/archive/` | 6个已完成设计 |
