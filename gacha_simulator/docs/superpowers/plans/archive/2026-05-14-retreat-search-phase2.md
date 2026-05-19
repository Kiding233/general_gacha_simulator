# 退路方案搜索 — 第二阶段实现计划

## 未实现功能清单

| # | 功能 | 优先级 | 状态 |
|---|------|--------|------|
| 1 | Pareto 前沿图可视化 | 高 | ❌ 未实现 |
| 2 | 权重优先级真正读取 WeightConfig 并在页面配置权重 | 高 | ❌ 未实现 |
| 3 | 脆弱性分析和退路方案搜索合并为退路分析的子 Tab | 中 | ❌ 未实现 |
| 4 | RetreatSearchResult 类型精确化 (resource_only_result/target_only_result) | 低 | ⚠️ 类型不匹配但不影响使用 |
| 5 | 核心 __init__.py 导出 retreat 类 | 低 | ⚠️ 不影响使用 |
| 6 | 未运行脆弱性分析的明显提示 | 低 | ⚠️ 有基础提示 |
| 7 | 详细结果表"详情"按钮 | 低 | ❌ 未实现 |
| 8 | 搜索算法实际运行测试 | 低 | ⚠️ 仅基础测试 |

---

## Task A: Pareto 前沿图可视化

**目标**: 在退路方案搜索面板右栏结果区，添加 Pareto 前沿散点图（X轴=额外资源，Y轴=目标卡数量），搜索完成后自动绘制。

**实现方案**:
- 在 `retreat_search_panel.py` 的 `_on_finished` 中，使用 matplotlib 生成 Pareto 前沿图
- 保存为临时 PNG，用 QLabel + QPixmap 显示
- 图表嵌入在结果摘要和详细表格之间

**修改文件**: `gacha_simulator/gui/retreat_search_panel.py`

---

## Task B: 权重优先级读取 + 页面配置权重

**目标**: 
1. 后退法/Pareto搜索移除目标卡时按权重从小到大排序（权重小=不重要=先移除）
2. 在退路方案搜索面板添加权重配置表格（参考最多目标卡页面，但只有"错失代价"一列，没有"抽取意愿"）

**设计决策**:
- 退路方案搜索只有后退法（没有前进法），所以只需要"错失代价"权重（决定移除顺序）
- 权重表格列：卡ID | 错失代价权重
- 权重传入 RetreatSearchEngine，由 `_get_sorted_card_ids` 使用

**修改文件**: 
- `gacha_simulator/core/retreat_search.py` — 添加 miss_cost_weights 参数
- `gacha_simulator/gui/retreat_search_panel.py` — 添加权重配置表格 UI

---

## Task C: 合并为退路分析子 Tab

**目标**: 将"退路分析"（脆弱性分析）和"退路方案搜索"合并为同一个 Tab 页下的两个子 Tab。

**实现方案**:
- 在 MainWindow 中，将原来的两个独立 Tab 合并为一个
- 新 Tab 名"退路分析"，内含 QTabWidget，子 Tab 为"脆弱性分析"和"方案搜索"
- 信号连接不变，只是容器层级变化

**修改文件**: `gacha_simulator/gui/main_window.py`
