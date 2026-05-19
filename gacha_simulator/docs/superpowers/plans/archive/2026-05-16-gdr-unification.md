# GDR 与成功率判断统一管理实施计划

## 前置依赖

- 设计文档：`/workspace/docs/superpowers/specs/2026-05-16-gdr-unification-design.md`
- 本计划应在流式重构之前完成
- 与流式重构计划的关系见设计文档 §7

## Task 1：创建 UNIFIED_GDR_REGISTRY + SuccessChecker + 修复数值不一致

**目标**：合并两套注册表为单一真相源，修复所有数值不一致，创建统一成功判断模块

**内容**：

1. 在 `core/gdr.py` 中新增：
   - `GDRDefinition` NamedTuple 类
   - 13 个 `_gdr_*` 函数（每个都与对应的 Registry 函数数值一致）
   - `UNIFIED_GDR_REGISTRY` 字典
   - `SuccessChecker` 类
   - `populate_gdr_combo` 和 `get_default_threshold` 工具函数

2. 重写 `compute_gdr_from_compact`，委托给 `UNIFIED_GDR_REGISTRY`

3. 从 `UNIFIED_GDR_REGISTRY` 动态生成 `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY`

4. 关键修复：
   - `target_achievement`：分子加 min 截断
   - `all_targets`：改为逐卡检查
   - `ssr_collection`：改为收集率语义 + 使用 ssr_ids 参数
   - `extra_target`：改为逐卡盈余
   - `resource_efficiency`：分子加 min 截断 + 分母改为资源消耗量

**验证**：
- 构造测试数据，验证每个 `_gdr_*` 函数与对应的 Registry 函数给出相同结果
- 验证 `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY` 的向后兼容视图正常
- 验证 `SuccessChecker.is_success` 与直接调用 `compute_gdr_from_compact` 结果一致
- 验证 `compute_success_probability` 正常工作

**产出文件**：修改 `core/gdr.py`

## Task 2：worst_impact.py 去重

**目标**：用 SuccessChecker 替换 _build_success_checker 的 70 行重复逻辑

**内容**：

1. 删除 `_build_success_checker` 方法（~70 行）
2. 删除 `_check_success_from_counts` 函数
3. 在类中创建 `SuccessChecker` 实例
4. 所有调用 `self._success_checker(result)` 改为 `self._checker.is_success(result)`

**验证**：
- worst_impact 分析功能正常
- target_achievement + threshold < 1.0 的场景现在能正确工作

**产出文件**：修改 `core/worst_impact.py`

## Task 3：analysis_panel.py 去硬编码

**目标**：消除 4 处硬编码

**内容**：

1. `_compute_statistics_unit`：改为遍历 `UNIFIED_GDR_REGISTRY`，使用 `compute_gdr_from_compact`
2. `_CUM_PRECOMPUTED`：删除，改为使用 `compute_gdr_from_compact` 直接计算
3. GDR 下拉列表：改为使用 `UNIFIED_GDR_REGISTRY` 的 `(key, display_name)` 对
4. `_on_preset_threshold`：改为使用 `compute_gdr_from_compact`

**验证**：
- 统计表指标数 = UNIFIED_GDR_REGISTRY 条目数
- 累积分析支持所有 GDR 指标
- 预设阈值功能正常

**产出文件**：修改 `gui/analysis_panel.py`

## Task 4：per_pool_analysis.py 去硬编码

**目标**：用 SuccessChecker 替换内联成功逻辑

**内容**：

1. `compute_transition_matrices` 的 `success_func` 默认值改为使用 `SuccessChecker`

**验证**：
- 转变分析结果与改造前一致

**产出文件**：修改 `core/per_pool_analysis.py`

## Task 5：其他面板适配

**目标**：确保所有面板使用 UNIFIED_GDR_REGISTRY 生成下拉列表

**内容**：

1. retreat_panel.py：改为使用 `populate_gdr_combo` 和 `get_default_threshold`
2. worst_impact_panel.py：同上
3. strategy_panel.py：同上
4. resource_search_panel.py：同上
5. retreat_search_panel.py：同上

**验证**：
- 所有面板的 GDR 下拉列表条目数 = UNIFIED_GDR_REGISTRY 条目数
- 默认阈值与改造前一致

**产出文件**：修改 5 个面板文件

## Task 6：向后兼容验证 + 清理

**目标**：确保所有现有功能正常，清理废弃代码

**内容**：

1. 验证 `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY` 的向后兼容视图正常
2. 验证 `compute_success_probability` 正常工作
3. 删除 `compute_gdr_from_compact` 中旧的 if-elif 链
4. 更新 `core/__init__.py` 的导出列表

**验证**：
- 全量回归测试
- 所有面板功能正常

**产出文件**：修改 `core/gdr.py`、`core/__init__.py`

## 执行顺序

```
Task 1 (UNIFIED_GDR_REGISTRY + SuccessChecker + 修复数值不一致)
    ↓
Task 2 (worst_impact 去重)    Task 3 (analysis_panel 去硬编码)    Task 4 (per_pool 去硬编码)
    ↓                               ↓                                  ↓
Task 5 (其他面板适配)
    ↓
Task 6 (向后兼容验证 + 清理)
```

Task 2/3/4 依赖 Task 1，可并行。Task 5 依赖 Task 1。Task 6 依赖所有前置任务。

## 预期收益

| 维度 | 改造前 | 改造后 |
|------|--------|--------|
| 注册表数量 | 2 套（手动同步） | 1 套（自动同步） |
| 成功判断实现 | 5 处（3 处重复/硬编码） | 1 处（SuccessChecker） |
| 数值一致性 | 5 个指标有 bug | 全部一致 |
| 新增 GDR 指标工作量 | 修改 5-6 个位置 | 修改 1 个位置（UNIFIED_GDR_REGISTRY） |
| 统计表指标覆盖 | 9/11（缺 2 个） | 13/13（全覆盖） |
