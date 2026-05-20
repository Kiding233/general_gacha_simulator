# 项目计划汇总

## 已完成的计划（12 个）

| # | 日期 | 计划 | 说明 |
|---|------|------|------|
| 1 | 05-07 | gacha-simulator-implementation-plan | 初始实现：核心模拟引擎、GUI、配置系统 |
| 2 | 05-13 | code-refactor | 消除 GUI 层重复模拟环境构建，统一 GDR 成功率计算 |
| 3 | 05-13 | retreat-search | 退路搜索：最小额外资源/最大目标卡/Pareto 前沿 |
| 4 | 05-13 | retreat-vulnerability-analysis | 脆弱性分析：条件资源分布、核密度回归 |
| 5 | 05-13 | strategy-comparison-infra | 策略注册表、4 种策略工厂、Worker 策略选择 |
| 6 | 05-14 | worst-impact | 最差影响分析：条件分布下尾分位数评估 |
| 7 | 05-14 | retreat-search-phase2 | 退路搜索二期（Pareto 可视化、权重配置、子标签合并）— 部分完成，4 项低优先级待办 |
| 8 | 05-16 | 遗留代码清理 + 权重统一 + 关于页面 | 删除 ConvertAction/旧版保底/archive/visualization 文件、权重 txt 导入导出统一、GDR_REGISTRY 补全 target_collection、关于页面完善、Pride Versioning 版本号系统 |
| 9 | 05-16 | GDR 与成功率判断统一管理 | 合并两套注册表为 UNIFIED_GDR_REGISTRY、创建 SuccessChecker 统一成功判断、修复 5 个数值不一致 bug、消除 6 处硬编码、5 个面板下拉列表统一 |
| 10 | 05-17 | 流式模拟架构重构 | SharedResultCollector 边模拟边提取边丢弃、内存与 N 无关；逐抽真实资源替代线性插值/均摊近似；修复 9 项 bug（total_gained 丢失、gdr_dists key 映射、空数据守卫、SSR 识别、per-pool 资源丢失等）；删除死代码 _compact_to_iv_list |
| 11 | 05-17 | 过程分析功能（核心） | infer_events 双路径轨迹推断（5种抽卡池事件）、compute_aa/bb/ab/ba 四种交叉统计分析、5种事件模式（含自定义模式+零样本枚举）+4种成败模式（含自定义模式）、ProcessAnalysisPanel UI 面板（5个Tab）、compact 新增 draw_pity_names/draw_pity_counter_max、修复10+个级联Bug |
| 12 | 05-20 | 策略代码重构（5阶段） | CompactResult + Collector 模式 + StrategyContext + 统一策略体系 + ConfigStore + 停止条件注册表 + 策略比较面板 + 保底概率缓存 + compact 元数据 + ssr_ids |

## 进行中的计划（1 个）

### P2：过程分析功能（续）

- **设计文档**：`specs/2026-05-15-process-analysis-design.md`（v5）
- **实施计划**：`plans/2026-05-15-process-analysis.md`（v7）
- **状态**：核心功能已完成，4项待实现
- **已完成**：
  - 抽卡池5种事件推断（pity_hit/early_hit/miss/skip/ignore）
  - 四种统计分析（AA/BB/AB/BA）
  - 5种事件模式 + 4种成败模式（含自定义模式）
  - 自定义模式：自由约束组合 + 零样本枚举
  - 过程分析面板 UI（5个Tab + 自定义约束控件）
  - 两种成败定义确认合理（池子级 vs 整体级各有用途）
- **未实现**：

| 功能 | 优先级 | 说明 |
|------|--------|------|
| 兑换池/资源池事件 | 🔴 高 | 需新增 `pool_types` 字段 + 4种事件推断（exchange/no_exchange/resource_draw/resource_ignore） |
| 保底名区分 | 🟡 中 | 当前仅 raw 模式区分保底机制名，其他模式不区分 |
| success_distribution UI展示 | 🟡 中 | AB 分析中已计算但未展示 |
| BB 可视化增强 | 🟢 低 | 柱状图、热力图、条件概率矩阵 |

## 未执行的待办计划（3 个）

### P3：Bootstrap 稳定性分析

- **实施计划**：`plans/2026-05-18-bootstrap-stability-analysis.md`
- **状态**：未开始
- **目标**：为所有统计估计添加 Bootstrap 置信区间，在图表上可视化展示稳定性
- **核心原理**：Bootstrap 不是重新跑模拟，而是对已有 N 条结果做有放回抽样（纯数组操作），零额外模拟成本、零额外内存
- **核心内容**：
  - BootstrapEngine 核心类：支持概率、分布分位数、AA/BB/AB/BA、条件分位数，默认 BCa 校正
  - 直接可 Bootstrap：analysis_panel、process_analysis_panel、retreat_panel、worst_impact_panel
  - 需小改即可 Bootstrap：strategy_panel、resource_search_panel、worst_impact_panel（新池子分布）、retreat_search_panel（保存个体结果即可）
  - 新增总变差（TVD）计算：衡量分布估计的稳定性
  - 可视化：阴影带（趋势图）、误差棒（柱状图）、表格显示 `0.95 [0.92, 0.98]`
- **不做 Bootstrap**：gacha_panel（模拟面板）

### P4：自适应模拟次数与方差缩减

- **设计文档**：`specs/2026-05-16-adaptive-simulation-design.md`
- **实施计划**：`plans/2026-05-16-adaptive-simulation.md`
- **状态**：未开始
- **目标**：自适应精度模式 + 对偶变量法 + EVT 尾部拟合
- **核心内容**：
  - `AdaptiveSimController`：实时 RSE 监控，达到目标精度自动停止
  - `stop_condition` 回调：`run_batch_parallel` 支持提前终止
  - 对偶变量法：配对模拟降低均值估计方差
  - EVT 尾部拟合：GPD 拟合改善 VaR/CVaR 精度
- **依赖**：流式重构（P1，已完成）的 `on_result` 回调

### P6：策略代码重构遗留项

- **设计文档**：`strategy_code_investigation_and_refactoring_plan.md`（v8）
- **状态**：未开始
- **目标**：完成策略重构中 6 项未实施步骤
- **未实现项**：

| 步骤 | 内容 | 优先级 | 说明 |
|------|------|--------|------|
| 0.1 | 删除根目录 `worst_impact.py` | 🟢 低 | 统一使用 `core/worst_impact.py` |
| 3.1 | `vulnerability.py` 的 `_is_success()` 替换为 `SuccessChecker` | 🟡 中 | GDR 统一判定 |
| 3.3 | `analysis_panel.py` 的 GDR 调用统一为 `SuccessChecker` | 🟡 中 | GDR 统一判定 |
| 3.4 | `UNIFIED_GDR_REGISTRY` 增加 `register_gdr()` 函数，带冲突检测 | 🟡 中 | GDR 统一管理 |
| 4.2 | 旧字段迁移逻辑（`strategy_type` → `strategy_name`） | 🟢 低 | 当前通过 `strategy_type_to_key()` 转换，功能等价 |
| 4.4 | 策略参数动态控件（int→QSpinBox, float→QDoubleSpinBox 等） | 🟡 中 | 当前 `strategy_params` 始终为 `{}`，策略使用默认参数 |
| 4.6 | GUI 面板权重获取改为 `set_store()` / 信号，而非 `self.window()` | 🟢 低 | 功能正常，仅代码风格优化 |

## 已知问题

- **专武角色比（weapon_character_ratio）**：`GDRContext.weapon_character_map` 当前始终为空字典，没有配置入口。该指标需要角色-武器对应关系（如 `{"weapon_a": "char_a"}`），但配置文件和 GUI 中均无定义方式，因此该指标始终返回 0.0。需要在配置系统中新增角色-武器对应表定义。
- **per_pool_analysis.py 的 success_func**：仍使用内联逻辑（InfoVector 路径），未改用 SuccessChecker。过程分析功能实施时一并修改。

## 建议执行顺序

```
P2 (过程分析续) → P6 (重构遗留) → P3 (Bootstrap) → P4 (自适应+EVT)
```

**依赖关系**：
- P2 先行：新增事件类型影响 `process_data` 格式，P3 需要适配
- P6 独立：可随时执行，与 P2 无依赖
- P3 在 P4 之前：Bootstrap 先实现通用框架，EVT 作为尾部优化集成
- P4 Task 3 (EVT)：在 Bootstrap 框架上扩展 Bootstrap-EVT 混合方法（对尾部分位数，Bootstrap 不可靠，需 EVT 参数化外推）

**关键兼容性**：Bootstrap 与 P4 的三个方法都兼容——
- 自适应停止：兼容（当前基于 RSE，无偏）
- 对偶变量法：兼容，需配对 Bootstrap（`paired=True`，重抽样 N/2 对而非 N 个个体，否则 CI 偏宽）；gacha_panel 添加开关
- EVT 尾部拟合：互补，需参数 Bootstrap（从拟合的 GPD 中抽样，非标准 Bootstrap 重抽样）
- P3 的 `bootstrap_distribution` 应预留 `resample_method='auto'/'standard'/'parametric_gpd'/'m_out_of_n'` 接口
- **厚尾问题**：Athreya(1987) 和 Hall(1990) 证明方差无限时标准 Bootstrap 不一致；本项目概率估计（伯努利）不受影响，但连续量尾部需参数 Bootstrap 或 m-out-of-n

## 已完成计划的归档

以下计划已完成，其设计文档和计划文件仅作参考，可归档：

- 2026-05-07-gacha-simulator-implementation-plan.md
- 2026-05-13-code-refactor.md
- 2026-05-13-retreat-search.md
- 2026-05-13-retreat-vulnerability-analysis.md
- 2026-05-13-strategy-comparison-infra.md
- 2026-05-14-worst-impact.md
- 2026-05-14-retreat-search-phase2.md（部分完成）
- 2026-05-16-gdr-unification.md
- 2026-05-16-streaming-refactor.md
- strategy_code_investigation_and_refactoring_plan.md（v8，6项遗留归入 P6）
