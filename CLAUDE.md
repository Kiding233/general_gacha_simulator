# CLAUDE.md

GachaStat 抽卡概率模拟与分析系统。版本号/Tab 列表由 C1 cron 自动同步。Harness 生态说明见第三层。

## 一、项目事实

**技术栈：** Python 3.10+ · PyQt6 · numpy · Plotly (WebEngine) · pytest+cov
并行模拟：`multiprocessing.Pool` + worker initializer 模式

```bash
pip install -e ".[dev]"                              # 安装依赖
python -m gacha_simulator.main                       # GUI
python -m gacha_simulator.cli -n 1000 -w 4 -s 42     # CLI
pytest --cov=gacha_simulator                         # 测试
```

**架构分层：**
```
gacha_simulator/
├── core/       # 引擎：池子、状态、策略、保底、GDR、分析算法（无 GUI 依赖）
├── service/    # GachaService + batch_simulator
├── gui/        # PyQt6 面板（Tab 列表见 main.py，C1 cron 自动同步）
├── config/     # 配置文件（| 分隔文本格式）
└── visualization/  # matplotlib 中文字体
```

**核心数据流：** `ConfigStore → SimulationEnvBuilder → SimulationEnv → GachaService(pools, strategy, stop_cond) → run_simulation(CompactCollector) → CompactResult → SharedResultCollector`。两种模式：紧凑 `CompactResult`（主流，O(1) 内存，`to_dict()`/`from_dict()` 序列化）/ 完整 `List[InfoVector]`（逐抽记录）。

**版本号：** 见 `gacha_simulator/_version.py`（Pride Versioning: MAJOR=PROUD / MINOR=DEFAULT / PATCH=SHAME）。C1 每日同步到 `技术栈.md`。

---

## 二、架构约束

### 策略 (`core/strategy.py`)

`STRATEGY_REGISTRY` 注册 7 种策略（`smart`/`pool_quota`/`pity_reserve`/`stop_on_target`/`target_hunting`/`fixed_count`/`draw_target`），统一接口 `select_action(self, ctx: StrategyContext) -> Action`。`StrategyContext` 封装 `state`/`current_pools`/`target_cards`/`acquired`/`pool_draw_counts`/`total_draws` 等，`get_pity_probabilities()` 惰性计算。工厂：`create_strategy(name, params)`。

### 保底 (`core/pity.py`)

`PityEngine`：软保底（`start_at`→`end_at` 概率爬升）、硬保底（`threshold` 100%）。重置条件：`any_ssr`/`featured`/`never`。多保底按顺序叠加。

### GDR (`core/gdr.py` + `core/generalized_drop_rate.py`)

`UNIFIED_GDR_REGISTRY` 定义 13 种广义出率指标。两路计算：`compute_from_compact`（O(1)）/ `compute_from_history`（O(T)）。

**调用规范（强制）：** 必须用 `make_gdr_calculator(store, target_specs, gdr_key)` 构造 `GDRCalculator`——权重从 `ConfigStore` 自动提取。**禁止绕过直接调** `compute_gdr_from_compact`/`compute_success_probability`（权重易漏传、静默退化 1.0）。例外：`process_trace.py`/`per_pool_analysis.py` 通过 `**kwargs` 透传权重。

### 过程分析 (`core/process_trace.py` + `core/process_analysis.py`)

每池推断 7 种事件类型 + 池子成败（B 维度），4 种交叉统计（AA/BB/AB/BA），5 种事件组合模式。

### 流式分析 (`core/streaming.py`)

`SharedResultCollector` + `StreamingAnalyzer` 边模拟边提取边丢弃，内存 O(1)。

### 停止条件 · 并行模拟 · GUI · 配置

`STOP_CONDITION_REGISTRY` 注册 6 种条件 → `create_stop_condition()`。并行模拟用 `Pool(initializer=_wk_init)`，11 个全局变量注入子进程。GUI 用 QThread+Worker 模式，Plotly 图表通过 `ChartWebView` 渲染。配置文件 `|` 分隔文本 → `config_io.py` 读写（`schedule.txt`/`pools/*.txt`/`pity.txt`/`targets.txt`/`gains.txt`/`cards.txt`/`resources.txt`/`initial_resources.txt`）。

### 扩展指南

| 扩展 | 入口 |
|------|------|
| 新 GDR | `core/gdr.py` + `UNIFIED_GDR_REGISTRY` 注册 `GDRDefinition` |
| 新策略 | `core/strategy.py` + `STRATEGY_REGISTRY` 注册 |
| 新停止条件 | `core/stop_condition.py` + `STOP_CONDITION_REGISTRY` 注册 |
| 新面板 | `gui/` + `MainWindow._setup_ui()` 注册 Tab |
| 新配置项 | `ConfigStore` → `config_io.py` → `config_panel.py` → `SimulationEnvBuilder` |

---

## 三、Harness 使用指南

### Hooks（9 个，自动触发）

| # | 触发 | 行为 | 阻塞 |
|---|------|------|------|
| H1 | SessionStart | 注入 git log + P0 + eval 报告 + checkpoint | 永不 |
| H2 | 每次 Bash | 拦截 `rm -rf /`/`git push --force main` | exit 2 |
| H3 | git commit | Conventional Commits 格式 (`feat:`/`fix:`) | exit 2 |
| H4 | Write/Edit 后 | 自动追加变更日志到 05-笔记 | 永不 |
| H5 | git commit | 版本号/Tab 一致性校验 | exit 2 |
| H6 | Stop | >7 天未更新文档提醒 | 永不 |
| H7 | git commit | `ruff check` + 目录边界（ms 级） | exit 2 |
| H8 | PreCompact | 保存 checkpoint（worktree 感知） | 永不 |
| H9 | git push | `pytest -q`（min 级） | exit 2 |

**被阻止时：** H3→修正 commit message · H5→更新技术栈.md · H7→`ruff check --fix` · H9→修复失败测试
**紧急绕过：** 创建 `HARNESS_BYPASS` 文件 → H7/H9 降级为 warn-only（C4 30min 内自动删除）

### Cron Agents（6 个） + Evaluator（1 个）

| Agent | 频率 | 产出 |
|-------|------|------|
| C1 doc-syncer | 5:07 | 版本/Tab 同步 + `[auto]` commit |
| C2 matrix-syncer | 5:37 | 矩阵偏差 → `04-收件箱/matrix-drift-*.md` |
| C3 weekly-writer | 9:07 | 周一：本周聚焦 + `[auto]` commit |
| C4 stale-detector | 6:07 | 腐烂检测 + 收件箱清理 + BYPASS 过期删除 |
| C5 quality-reviewer | 10:07 | 周一：代码质量 → `04-收件箱/quality-*.md` |
| C6 heartbeat-monitor | 8:07 | cron 静默失败警报 |
| **E1** deep-evaluator | 每 6h | 独立审查 → `04-收件箱/eval-*.md`（SessionStart 自动注入） |

### Planner

`/plan <种子>` → AI 搜索影响面 → 创建计划文件（含 META 头）→ 注册到模块状态矩阵

### 计划审查工作流 (P38)

`/workflow plan-review "{计划文件路径}"` → 五阶段对抗验证流水线：
阶段 0 分类 → 阶段 1 扇出影响面 → 阶段 2 对抗循环 (Finder→Fixer→Verifier → 收敛) → 阶段 3 可行性门控 (6 项检查) → 阶段 4 代码审计

产出 `04-收件箱/peer-review-{plan}-{date}.md`，H1 SessionStart 自动注入。E1 交叉验证 peer-review 发现与 eval 发现的一致性。

### 故障排查

commit 被 H7 阻止 → `ruff check` 修复 · push 被 H9 阻止 → `pytest -q` 修复 · cron 静默失败 → 检查 `heartbeat-alert-*.md`（CronCreate 7 天过期需重新注册） · worktree hooks 不触发 → 已知限制（合并回主分支时二次检查）

### 文档体系

三文件制：`模块.md` + `理论.md` + `05-笔记.md`（H4 自动维护）。计划文件含 META 头，全局约定见 `docs/00-meta/全局约定.md`，活跃计划见 `模块状态矩阵.md`。
