<!-- META: P29 | module:subsystems/GDR系统 | status:designing | last:2026-06-11 -->
# P29 GDR系统理论文档补充计划

> 日期：2026-05-29 | 版本：v1
> 来源：[全模块理论严谨性系统性审查](reports/全模块理论严谨性系统性审查.md) 缺陷 4/5
> 状态：**设计中，未实施**
> 涉及文件：`gdr.py`、`generalized_drop_rate.py`

---

## 一、问题概述

GDR（广义出率）系统的 17 个指标为项目独创设计，无外部文献或业界标准对照。对指标的「正确性」判断主要基于内部一致性，缺乏外部验证和公理化文档。主体审查发现 2 项与效用理论基础相关的中等缺陷。

### 1.1 缺陷总览

| # | 缺陷 | 严重度 | 核心问题 |
|---|------|--------|---------|
| 4 | weighted_satisfaction 缺乏公理化效用理论基础 | 🟡 中等 | 可加拟线性假设过强，无损失厌恶建模 |
| 5 | total_card_value 对非目标卡隐式赋值 1.0 | 🟡 中等 | 普通 SSR 价值 = 任意目标卡 1 个副本的价值——几乎不可能是用户意图 |

---

## 二、缺陷详解与改进方案

### 2.1 缺陷 4：weighted_satisfaction 缺乏公理化基础（中等）

**现状**：`weighted_satisfaction` 假设跨卡片的可加拟线性效用函数：

```
U = Σ (desire_i × got_i − miss_cost_i × (target_i − got_i)_+)
```

**理论问题**：
1. **可加性假设过强**：无交互项——卡 A 和卡 B 的效用被假定为独立。在实际抽卡游戏中，「卡 A + 卡 B 组队效果翻倍」的协同效应无法建模。
2. **desire 和 miss_cost 的独立性**：在期望效用理论（von Neumann-Morgenstern, 1944）中，desire 和 miss_cost 通过参考点关联。前景理论（Kahneman & Tversky, 1979）进一步表明损失厌恶系数 λ > 1——未获得的痛苦大于获得的快乐。当前设计将它们视为两个独立参数，无参考点校准。
3. **未归一化**：所有权重默认为 1.0 时退化为 `Σ(2×got − target)`——跨不同 `target_specs` 配置不可比较。用户无法判断「配置 A 得 3.5 分」和「配置 B 得 7.2 分」哪个更好，因为评分尺度取决于目标卡数量。

**推荐方案**：
1. **补充公理化文档**：为 `weighted_satisfaction` 编写独立的指标说明文档，明确列出——
   - **定义**：数学公式及每项含义
   - **值域**：理论最小值（−Σ miss_cost_i × target_i）到最大值（Σ desire_i × target_i）
   - **假设**：可加独立性、线性效用、desire/miss_cost 外生给定
   - **适用场景**：用户对不同目标卡有明确偏好强度差异时
   - **不适用场景**：卡间有协同效应、偏好不确定、需要跨配置比较
2. **归一化选项**：提供「归一化到 [0,1]」复选框——将加权满意度映射到 `[actual − min_possible] / [max_possible − min_possible]`，使跨配置比较成为可能。
3. **长期方向**：引入参考点依赖（前景理论风格）——`desire` 和 `miss_cost` 通过统一的「参考点」参数关联，允许用户只配置一个参数而另一个自动推导。但这涉及 UX 研究和行为经济学验证，远超出当前工程范围。

**文献**：von Neumann & Morgenstern (1944), *Theory of Games and Economic Behavior*; Kahneman & Tversky (1979), *Econometrica*; Keeney & Raiffa (1976/1993), *Decisions with Multiple Objectives*

---

### 2.2 缺陷 5：total_card_value 隐式赋值 1.0（中等）

**现状**：

```python
total_value += cnt * card_value_weights.get(card_id, 1.0)
```

对所有未配置 `card_value_weights` 的卡（包括所有非目标卡）隐式赋予权重 1.0。

**问题**：一张普通 SSR 被赋予与「任意目标卡的一个副本」相同的价值。在典型的抽卡游戏中：
- 目标限定 SSR 的价值 >> 常驻 SSR 的价值
- 非目标 SSR 对某些玩家可能价值为 0（已满破）
- 不同稀有度的卡价值跨数量级

**推荐方案**：
1. **短期**（低风险）：`card_value_weights.get(card_id, 0.0)`——将未配置卡的默认权重从 1.0 改为 0.0。只有用户明确配置的卡才贡献 `total_card_value`。这是一个**破坏性变更**，需在发布说明中标注。
2. **中期**：提供「自动权重推断」选项——基于稀有度推断默认权重：
   - SSR 限定：1.0
   - SSR 常驻：0.3
   - SR：0.1
   - R：0.0
   - 用户仍可手动覆盖任何卡的权重
3. **长期**：将 `card_value_weights` 提升为一级配置项（类似 `target_specs` 和 `desire/miss_cost`），而非隐藏在 GDR 高级选项中。

---

## 三、实施路线

### 阶段一：公理化文档 + 默认值修正（预计 1-2 天）

| 任务 | 涉及文件 | 内容 |
|------|---------|------|
| weighted_satisfaction 文档 | `gdr.py`（docstring） + 可选 `docs/` | 定义、值域、假设、适用/不适用场景 |
| total_card_value 文档 | `gdr.py`（docstring） | 同上 + 默认值变更说明 |
| 非目标卡默认权重修正 | `gdr.py` | 1.0 → 0.0（破坏性变更） |
| 归一化选项 | `gdr.py` + `analysis_panel.py` | `normalize` 参数 + UI 复选框 |

### 阶段二：权重推断 + 一级配置（后续评估）

| 任务 | 说明 |
|------|------|
| 稀有度自动权重 | 基于 SSR/SR/R 推断默认 card_value |
| card_value 一级配置 | 升级为与 target_specs 并列的配置项 |

---

## 四、与现有计划的关系

- **P22（多资源类型分布）**：P22 处理 GDR 的资源类型参数化（缺陷 6），本计划处理 GDR 的效用理论基础（缺陷 4/5）。两者互补但不重叠——P22 关注「哪个资源」，本计划关注「价值如何量化」。
- **P19（比较分析面板重构）**：比较分析面板可能使用 `weighted_satisfaction` 作为跨配置比较指标，归一化选项对此至关重要。

---

## 五、测试策略

| 测试 | 说明 |
|------|------|
| 非目标卡默认 0.0 | 验证未配置卡不贡献 total_card_value |
| 归一化边界 | min_possible / max_possible 计算 + [0,1] 映射 |
| 向后兼容 | 旧配置文件显式指定 card_value_weights 后行为不变 |

---

*本计划覆盖 2 项理论缺陷。建议优先实施阶段一的公理化文档——以最小代码改动获得最大理论透明度增益。*
