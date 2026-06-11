<!-- META: P28 | module:panels/统计分析 | status:in_progress | last:2026-06-11 -->
# P28 每池GDR分析统计严谨性改进计划

> 日期：2026-05-29 | 版本：v1
> 来源：[全模块理论严谨性系统性审查](reports/全模块理论严谨性系统性审查.md) 缺陷 17（部分）+ [补充模块理论严谨性审查](reports/补充模块理论严谨性审查.md) 缺陷 P1-P7
> 状态：**设计中，未实施**
> 涉及文件：`process_trace.py`、`process_analysis.py`、`per_pool_analysis.py`、`gdr.py`

---

## 一、问题概述

每池GDR分析将全局 GDR 分解到每个卡池级别，计算每池事件类型、GDR 值、成功判定，并进行 AA/BB/AB/BA 交叉分析。补充审查发现 7 项缺陷，其中 2 项严重、3 项中等、2 项低等（含 1 项已在主体审查中记录）。

### 1.1 缺陷总览

| # | 缺陷 | 严重度 | 核心问题 |
|---|------|--------|---------|
| P1 | K 个池 × N 次模拟的多重比较无校正 | 🔴 严重 | K=8 时 FWER ≈ 34%，用户误判池间差异 |
| P2 | 全局 GDR 掩盖池间异质性（Simpson 悖论风险） | 🔴 严重 | 高成功率池驱动全局指标，掩盖低成功率池失败 |
| P3 | Laplace 加一平滑过度收缩（Beta(1,1) 先验对所有事件类型等权收缩） | 🟡 中等 | 出现 1 次的 pity_hit 和 skip 得到相同平滑处理 |
| P4 | BA 似然比分母为零时返回 inf（已知，主体审查缺陷 17） | 🟡 中等 | inf 破坏下游聚合 |
| P5 | 单池 GDR 的 pseudo_compact 构造不完整 | 🟡 中等 | 未来新增 GDR 指标可能静默失败 |
| P6 | pool_target_map 回退路径有已知缺陷（已知，主体审查缺陷 16） | 🟢 低等 | 已在 P2 中修复，需确认回退路径覆盖 |
| P7 | 资源池/兑换池在成败分析中的特殊处理不一致 | 🟢 低等 | 不影响核心分析，未来扩展时需统一 |

### 1.2 涉及文件

| 文件 | 角色 |
|------|------|
| `core/process_trace.py` | PoolEvent/SampleTrace/infer_events/compute_pool_gdr |
| `core/process_analysis.py` | compute_aa/bb/ab/ba 交叉分析 |
| `core/per_pool_analysis.py` | PoolSnapshot/CumulativeSnapshot/汇总函数 |
| `core/gdr.py` | per_pool_draw_rate/target_card_draws/GDRContext |

---

## 二、缺陷详解与改进方案

### 2.1 缺陷 P1：K 个池的多重比较无校正（严重）

**现状**：对 K 个池各自计算 GDR 值 → 与全局阈值比较 → K 个布尔成功判定 → 用户观察「哪个池最难」。检验了 K 个假设（每个池的「真实成功率是否等于全局平均」），FWER 在 α=0.05 时为 1−(1−0.05)^K。对于 K=8，FWER ≈ 34%。

各池成功与否并非独立——早期池高消耗损害后续池成功率，产生负相关。Bonferroni 在此场景下过于保守，FDR 方法需检验独立性假设。

**推荐方案**：
1. **在每池分析面板标注**：「此为探索性分析——各池成功率来自同一模拟批次的相互依赖观测，不做假设检验校正」
2. **提供可选的 Benjamini-Hochberg FDR 校正**：控制错误发现率，在正相关条件下仍有效（Benjamini & Yekutieli, 2001）
3. **使用 Bootstrap 同时置信域**：对各池成功率构建联合置信区间，保留池间相关结构——这是处理非独立多重比较的金标准方法（Westfall & Young, 1993）

**文献**：Benjamini & Hochberg (1995, *JRSS-B*); Benjamini & Yekutieli (2001, *Annals of Statistics*); Westfall & Young (1993), *Resampling-Based Multiple Testing*

**依赖**：P3（Bootstrap 引擎）的重抽样基础设施。

---

### 2.2 缺陷 P2：全局 GDR 掩盖池间异质性——Simpson 悖论风险（严重）

**现状**：
- 池 A（角色池）：成功率 95%，消耗 60% 资源——容易
- 池 B（武器池）：成功率 40%，消耗 40% 资源——高难度
- 全局成功率：85%

用户看全局 GDR → 85%，满意。看每池 GDR → 池 B 仅 40%。这两者不矛盾——但系统没有提醒用户全局成功可能由容易的池子驱动，掩盖了高难度池子的低成功率。

这一模式与医学文献中「聚集 AUC 高于各亚组 AUC 的 Simpson 悖论」在结构上完全类似。

**推荐方案**：
1. **异质性诊断**：在每池分析面板增加自动诊断——
   - 各池成功率的变异系数 CV = std/mean
   - 若 CV > 0.3 → 标注「各池表现高度异质，全局指标可能掩盖池间差异」
   - 若 max(池成功率) − min(池成功率) > 0.3 → 标注「池间成功率跨度大（X% − Y%），请分别检查各池」
2. **UI 补充**：在全局 GDR 结果旁显示「池间异质性：高/中/低」指示器
3. **参考**：Simpson (1951, *JRSS-B*); Lerman (2018), *J. Computational Social Science*

---

### 2.3 缺陷 P3：Laplace 加一平滑过度收缩（中等）

**现状**：`compute_ab` 使用 `(success+1)/(total+2)` 作为 P(成功|事件) 的估计——Beta(1,1) 先验下的后验均值，等价于假设在观察数据前每种事件各成功和失败了一次。

问题：
- n=100 时，+1 先验贡献约 1%——可忽略
- n=3 时，+1 先验贡献约 40%——影响极大
- 所有事件类型施加**相同收缩强度**，忽略基础率差异

**推荐方案**：
1. **短期**（低风险）：将 Laplace 平滑改为 **Beta(0.5, 0.5) (Jeffreys 先验)**——P2 已实施。但从审查角度看，Jeffreys 先验仍未解决「不同事件类型基础率不同却同等收缩」的问题。
2. **中期**（推荐）：引入**经验贝叶斯收缩**（Efron & Morris, 1975）——使用层次先验，基础率高的事件类型收缩较少、基础率低的收缩较多。具体做法：
   - 对所有事件类型拟合 Beta 分布的 MLE 作为先验
   - 每个事件类型的后验均值 = (success + α_hat) / (total + α_hat + β_hat)
   - 这等价于 James-Stein 估计量在二项比例上的推广
3. **长期**：层次贝叶斯模型（Gelman et al., 2013, *Bayesian Data Analysis*, 第 5 章）——完全建模事件类型间的协方差结构

**文献**：Efron & Morris (1975), *JASA*; Gelman et al. (2013), *Bayesian Data Analysis*

---

### 2.4 缺陷 P4：BA 似然比分母为零返回 inf（中等，已知）

已在主体审查中记录为缺陷 17。P2 已实施 Laplace 平滑缓解此问题，但未根本解决——分母为 0 时 `ratio = P(事件|成功) / P(事件|失败)` 仍返回 inf。

**推荐方案**：
1. 分母为 0 时返回 `NaN` + `low_sample=True` 标记，而非 inf
2. UI 中对 NaN 显示「数据不足」、inf 显示「仅在成功路径上出现」
3. 提供可选的伪计数（pseudocount）参数：`ratio = (a + ε) / (b + ε)`，默认 ε=0.5

---

### 2.5 缺陷 P5：单池 GDR 的 pseudo_compact 构造不完整（中等）

**现状**：`compute_pool_gdr_single_pool` 构造伪 `compact` 字典传给 `compute_gdr_from_compact`，但缺少多个字段：`no_draw_resources`、`strategy_name`、`result_version`、各池资源的完整初始值和增益。

当前所有 GDR 指标不使用缺失字段——但未来新增 GDR 若依赖它们，单池模式会静默失败。

**推荐方案**：
1. 补全 `pseudo_compact` 中所有可获取的字段
2. 在 `GDRContext` 中添加 `available_fields` 元数据——GDR 计算函数声明所需字段
3. 若 `pseudo_compact` 缺少某 GDR 所需的字段，跳过该 GDR 并记录警告日志（而非返回 None/错误值）

---

### 2.6 缺陷 P6：pool_target_map 回退路径（低等，已知）

已在 P2 中修复主路径，但回退路径仍可能触发旧缺陷。需确认 `_infer_from_draw_sequence` 和 `_infer_from_aggregate` 两路径在 `pool_target_map=None` 时的行为，确保 skip/ignore 判定修正覆盖所有路径。

---

### 2.7 缺陷 P7：资源池/兑换池的特殊处理不一致（低等）

资源池和兑换池被赋予特殊事件类型，但在 AB/BA/BB 交叉分析中始终被排除。当前不影响核心分析——兑换池和资源池通常不被视为影响策略成功的主要因素。若未来需纳入兑换/资源池的经济影响，需统一处理。

**推荐方案**：在代码注释中明确标注此设计决策和未来扩展路径，避免后人误用。

---

## 三、实施路线

### 阶段一：Simpson 诊断 + inf 修复（预计 1-2 天）

| 任务 | 涉及文件 | 修复内容 |
|------|---------|---------|
| 异质性诊断 | `per_pool_analysis.py` | CV 计算 + 自动标注逻辑 |
| UI 异质性指示器 | `analysis_panel.py`, `process_analysis_panel.py` | 全局 GDR 旁显示异质性等级 |
| BA 分母 NaN 替代 inf | `process_analysis.py` | ratio 计算 NaN + low_sample |
| UI NaN/inf 处理 | `process_analysis_panel.py` | NaN→「数据不足」、inf→「仅在成功路径上出现」 |

### 阶段二：多重比较校正 + 经验贝叶斯（预计 3-5 天）

| 任务 | 涉及文件 | 修复内容 |
|------|---------|---------|
| FDR 校正 | `per_pool_analysis.py` | Benjamini-Hochberg 程序 |
| Bootstrap 同时置信域 | `per_pool_analysis.py`（依赖 P3） | 池间相关结构保留的联合 CI |
| 经验贝叶斯收缩 | `process_analysis.py` | Beta MLE 先验 + James-Stein 收缩 |
| pseudo_compact 补全 | `process_trace.py` | 补全可获取字段 + GDR 依赖声明 |

### 阶段三：可选深化（后续评估）

| 任务 | 说明 |
|------|------|
| 层次贝叶斯模型 | 完整的事件类型协方差建模（Gelman et al., 2013） |
| 资源池/兑换池统一 | 在 AB/BA/BB 中纳入兑换/资源池的经济影响 |

---

## 四、与现有计划的关系

- **P2（过程分析续）**：P2 已实现 Laplace→Jeffreys 平滑 + low_sample 标记 + skip/ignore 修正。本计划在此基础上进一步改进平滑策略和多重比较。
- **P3/P18（Bootstrap）**：阶段二的多重比较校正和同时置信域依赖 Bootstrap 引擎。
- **P22（多资源类型分布）**：P22 的资源类型参数化可能改善资源相关的每池 GDR 计算。

---

## 五、测试策略

| 测试 | 说明 |
|------|------|
| CV 诊断测试 | 同质/异质场景的 CV 计算和阈值触发 |
| FDR 校正测试 | K=5/10 池的校正前后对比 |
| 经验贝叶斯测试 | Beta MLE 先验拟合 + 不同 n 下的收缩行为 |
| pseudo_compact 补全测试 | 新 GDR 指标依赖声明 + 缺失字段警告 |
| BA inf→NaN 测试 | 分母为 0/非零的返回值验证 |

---

*本计划覆盖 7 项理论缺陷（2 项严重、3 项中等、2 项低等），引用 8 篇学术文献。建议优先实施阶段一（低风险，Simpson 诊断立即提升用户对分析结果的正确解读）。*
