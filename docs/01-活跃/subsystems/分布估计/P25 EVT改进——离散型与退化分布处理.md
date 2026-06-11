<!-- META: P25 | module:subsystems/分布估计 | status:in_progress | last:2026-06-11 -->
# P25 EVT 改进——离散型与退化分布处理

> 创建日期：2026-05-28 | 状态：设计中（v4——新增 MLE-IC 极端分位数稳定性分析 + Bootstrap 兼容性 + TIB vs 百分位法）
> 前置：P24 EVT 尾部拟合（已实现）
> 依赖：无
> 关联：P3（Bootstrap 稳定性分析——Bootstrap-EVT 统一 GPD 拟合路径 + TIB 升级）
> 前置：P24 EVT 尾部拟合（已实现）
> 依赖：无
> 关联：P3（Bootstrap 稳定性分析——Bootstrap-EVT 统一 GPD 拟合路径）

## 背景

P24 在 `EmpiricalDistribution` 核心层集成了 EVT GPD 尾部外推，所有面板自动受益。但实施后的理论讨论揭示了两个未解决的问题：

1. **离散性问题**：Pickands-Balkema-de Haan 定理假设底层分布连续，但抽卡模拟输出（GDR 指标）多为离散或有限格点数据。连续 GPD 拟合到离散数据上存在理论不匹配。
2. **退化/近退化分布**：`all_targets`（二元 {0,1}）、`weapon_character_ratio`（当前恒为 0）等 GDR 仅有个位数个不同取值，GPD 拟合完全无意义。

本计划针对这两个问题进行系统分类和改进。

---

## 一、理论基础：离散分布与极值理论的根本矛盾

### 1.1 长尾条件是 EVT 的必要前提

极值理论的核心定理——Pickands-Balkema-de Haan 定理（Balkema & de Haan 1974; Pickands 1975）——要求底层分布属于某个极值分布的吸引域（Maximum Domain of Attraction, MDA）。而 MDA 的一个**必要条件**是分布为**长尾分布**（long-tailed）：

\[
\lim_{x \to \infty} \frac{\overline{F}(x + c)}{\overline{F}(x)} = 1, \quad \forall c > 0
\]

其中 \(\overline{F}(x) = 1 - F(x)\) 为生存函数。长尾性质意味着：在已处于极端区域的条件下，再多走一步的概率衰减为 0。对于**取值为整数的离散分布**，长尾性质等价于：

\[
\lim_{n \to \infty} \frac{\overline{F}(n+1)}{\overline{F}(n)} = 1
\]

即相邻整数格点的尾部概率比值趋于 1。

### 1.2 Anderson (1970)：离散化系统性破坏长尾性

Anderson (1970) 的经典论文 *"Extreme value theory for a class of discrete distributions with applications to some stochastic processes"*（*Journal of Applied Probability*, Vol. 7, No. 1, pp. 99–113）是这一领域的奠基工作。Anderson 研究了整数格点分布的极值渐近行为，识别出三种根本不同的体制：

| 尾部比值极限 | Anderson 分类 | 极值行为 | 代表性分布 |
|-------------|-------------|---------|-----------|
| r = 1 | 长尾 | 经典 MDA *可能*成立 | 亚指数分布（离散化后） |
| r ∈ (0, 1) | **Anderson 类 Dα** | 最大值**不收敛**到单一极值分布，而是在上下两个**偏移 Gumbel 分布**间振荡：<br>exp(-r^{-(x-1)}) ≤ liminf ≤ limsup ≤ exp(-r^{-x}) | **几何分布**、**负二项分布** |
| r = 0 | 远离任何吸引域 | 最大值几乎必然在两个连续整数间**振荡** | **Poisson 分布** |

**Anderson (1970) 的核心结论**：最常见的离散分布——Poisson、几何、负二项——**全都不属于任何经典极值吸引域**。连续分布的 MDA 成员资格在离散化过程中被破坏。

### 1.3 关键反例：几何分布与指数分布的关系

一个最能说明问题的例子：设 \(X \sim \text{Exp}(\lambda)\) 是连续指数分布，则 \(Y = \lfloor X \rfloor \sim \text{Geom}(p)\) 是几何分布（其中 \(p = 1 - e^{-\lambda}\)）。指数分布**属于** Gumbel 吸引域（ξ=0，超额分布精确为指数 = GPD(ξ=0)），而几何分布——仅仅是将其取整——就**丧失了** MDA 成员资格（Shimura 2012）：

\[
\frac{\overline{F}_{\text{Geom}}(n+1)}{\overline{F}_{\text{Geom}}(n)} = 1-p = e^{-\lambda} < 1
\]

离散化使得尾部比值从连续极限 1 变为常数 r < 1，长尾性质被破坏。Anderson 类 Dα 的最大值行为——在偏移 Gumbel 分布间振荡——意味着**不存在唯一的极值吸引域**。

### 1.4 抽卡模拟的缓解因素：独立加和的中心极限效应

以上分析针对的是**单一离散随机变量**（如单次抽卡的出货抽数）。但实际 GDR 指标（如 `resource_remaining`、`weighted_satisfaction`）是**大量独立随机变量的加和**。由中心极限定理（CLT），加和的分布趋近正态分布，而正态分布属于 Gumbel 吸引域（ξ = 0）。

具体来说：
- 单次出货等待抽数 ~ Geom(p)，尾部分类为 Anderson Dα，理论上有 MDA 振荡
- 5000 次模拟的 `resource_remaining` = Σ(单次资源消耗)，是 5000 个随机变量的加和
- 加和分布趋近正态，属于 Gumbel 吸引域，对 POT-GPD 的收敛速度 μ(n) 随 n 增大
- 5000 次模拟 + 5000 个不同取值 = 连续性近似优秀

这就是为什么**在实践中**，连续 GPD 对高模拟次数下的 GDR 分布工作良好——即使单个过程的离散性在理论上与 MDA 条件冲突，大量独立加和后的分布已足够连续。

---

## 二、离散 EVT 外推：三大方案的系统文献评估

针对离散数据的极值外推，文献中存在三种主要方案。本节从理论严谨性、数值性能、可实现性三个维度进行对比。

### 2.1 方案 A：连续 GPD + 数据驱动的退化回退（当前方案）

**核心思想**：对"足够连续"的数据使用标准连续 GPD（POT 方法），对"明显离散"的数据（不同取值数 < 阈值）跳过 EVT，回退经验分位数。

**理论严谨性**：

**有利因素——已有文献间接支持**：

1. **Hitz, Davis & Samorodnitsky (2024)**（*"Discrete Extremes"*, *Journal of Data Science*, Vol. 22, pp. 524–536, DOI: 10.6339/24-jds1120）直接比较了连续 GPD、D-GPD、GZD 三种方法在离散数据上的表现。关键发现：
   > *"Both methods [D-GPD and GZD] outperform the continuous GPD when there are many tied observations; **otherwise [when there are few ties] results are similar**."*

   即：当数据中结（ties）较少时——等价于不同取值数足够多——连续 GPD 与离散专用方法的结果**相似**。

2. **Deidda & Puliga (2009)**（*"Performances of some parameter estimators of the generalized Pareto distribution over rounded-off samples"*, *Physics and Chemistry of the Earth*, Vol. 34, pp. 626–634, DOI: 10.1016/j.pce.2008.12.002）通过 Monte Carlo 模拟（每种参数组合 10,000 次）评估了 MLE、PWM、MDPD 等 7 种 GPD 估计器在四舍五入样本上的表现。核心发现：
   - 当舍入幅度 δ 相对于尺度参数 σ 较小时（δ/σ ≲ 0.1），**所有估计器的偏差可忽略**
   - 当舍入幅度大时（δ/σ ≳ 0.5），所有估计器都**严重退化**（偏差 +50% 以上）

3. **Ma, Yan & Zhang (2024)** 的区间删失 MLE 方法（MLE-IC）将舍入数据视为区间删失观测。论文指出：
   - 当 δ/σ 小（精细分辨率 + 大尺度 = 近似连续），**naive 连续 MLE 与 MLE-IC 几乎一致**
   - 当 δ/σ 大（粗糙舍入 = 高度离散），必须使用区间删失似然

4. **CLT 的缓解效应**（§1.4）：对于 5000 次独立模拟的 GDR 加和，正态近似 + Gumbel 吸引域提供了额外的理论支撑。

**不利因素——理论严谨性的真实缺口**：

1. **根本假设不满足**：严格来说，连续 GPD 的 Pickands-Balkema-de Haan 定理要求底层分布属于某个 MDA。Anderson (1970) 证明几何分布不满足这一条件。但 CLT 加和效应（§1.4）在实践中很大程度上弥合了这一缺口。

2. **MLE 似然的系统性偏差**：连续 GPD 的似然函数 `f(x) = (1/σ)(1+ξx/σ)^(-1/ξ-1)` 假设数据来自连续分布。当数据实际是离散格点时，似然值在格点之间的密度被错误地集中到格点本身，导致参数估计的**系统偏差**。Deidda & Puliga (2009) 的模拟确认了这种偏差随 δ/σ 增大而恶化。

3. **回归到「实践上没问题」的论证**：方案的可靠性主要依赖于 Hitz et al. (2024) 的经验结论——"ties 少时连续 GPD 与 D-GPD 结果相似"——而非严格的理论证明。对 ξ < 0（有界支撑）的分布，离散化偏差可能比 ξ ≥ 0 更严重，因为有界端点对格点位置敏感。

### 2.2 方案 B：D-GPD（离散广义 Pareto 分布）

**核心思想**：对连续 GPD 的生存函数在整数格点处求差，直接得到离散版本的分布，然后对离散超额数据进行精确的 MLE。

**数学定义**（Hitz et al. 2024; Krishna & Pundir 2009）：

\[
P(Y = k) = \overline{F}_{\text{GPD}}(k) - \overline{F}_{\text{GPD}}(k+1), \quad k \in \{0, 1, 2, \ldots\}
\]

其中 \(\overline{F}_{\text{GPD}}(x) = (1 + \xi x/\sigma)_+^{-1/\xi}\) 是连续 GPD 的生存函数。

**文献支撑**：

| 文献 | 贡献 |
|------|------|
| **Krishna & Pundir (2009)** | 首先提出 DGPD，推导 MLE 估计 |
| **Prieto et al. (2014)** | 研究 DGPD 参数估计的抽样性质 |
| **Hitz, Davis & Samorodnitsky (2024)** | **最完整**的 DGPD 研究——同时提出 D-GPD 和 GZD（广义 Zipf 分布）两种方案，在模拟数据和四个真实数据集（词频、法语词长、美国龙卷风、多胞胎出生数）上与连续 GPD 对比 |

**Hitz et al. (2024) 的关键发现**：

1. D-GPD 和 GZD 在 ξ=0 时都**退化到几何分布**——一致的理论一致性
2. D-GPD 拥有**闭式生存函数和概率质量函数**，可进行精确的似然推断
3. 当数据的质量（mass）较大时（即存在大量结 / 重复值），D-GPD 和 GZD **显著优于**连续 GPD
4. 当质量较小时（近似连续），D-GPD 和连续 GPD 表现相近
5. 该论文未明确推荐 D-GPD 优于 GZD（或反之）——两者基于不同的理论假设（D-GPD 假设底层连续潜变量在 MDA，GZD 假设 PMF 自身满足尾部条件），在大多数应用中给出相似结果

**理论严谨性**：⭐⭐⭐⭐（4/5）—— 直接解决离散性问题，不再回避 Anderson (1970) 的理论挑战。

**数值性能**：⭐⭐⭐（3/5）—— MLE 比连续 GPD 更复杂（无解析梯度，Hessian 可能奇异），Hitz et al. (2024) 使用数值优化 + 分析梯度，但在边界 ξ 处仍有收敛问题。

**可实现性**：⭐⭐（2/5）—— Python 生态中无任何成熟库实现 DGPD。DGPD 的 CDF 求逆需要数值求根（无可直接使用的分位数函数），VaR/CVaR 计算需要额外代码。

**可靠性风险**：
1. MLE 在离散似然下更易陷入局部最优（似然曲面有"阶梯"状特征）
2. 没有社区维护的参考实现（与连续 GPD 有 scipy 维护形成对比）
3. 边界 ξ 处的 MLE 行为比连续情况更差（Smith 1985 的正则性条件不完全适用）

### 2.3 方案 C：MLE-IC（区间删失极大似然）

**核心思想**（Ma et al. 2024）：不重新定义分布，而是修正似然函数。将每个离散观测 x* 视为来自区间 [x* - δ/2, x* + δ/2] 的连续数据（区间删失），似然变为：

\[
L(\xi, \sigma; \text{data}) = \prod_{i=1}^{n} \left[F_{\text{GPD}}\left(x_i + \frac{\delta}{2}\right) - F_{\text{GPD}}\left(x_i - \frac{\delta}{2}\right)\right]
\]

其中 δ 为离散化间距（对于整数数据 δ=1）。

**理论严谨性**：⭐⭐⭐⭐⭐（5/5）—— 最严谨的方案。不对连续 GPD 做任何近似，而是将离散化过程明确建模为区间删失。MLE-IC 是渐近无偏且一致的。

**数值性能**（Ma et al. 2024 的 Monte Carlo 结果）：
- 当 δ/σ 大时：MLE-IC 远优于 naive MLE（偏差减少 70-90%）
- 当 δ/σ 小时：MLE-IC 与 naive MLE 几乎一致（正如预期的——连续和区间删失似然趋于等同）
- 置信区间宽度：MLE-IC 的 CI 比 naive MLE 窄 5-10 倍（在极端舍入情况下）

**可实现性**：⭐⭐⭐（3/5）—— 用 scipy 的 `genpareto.cdf()` + `scipy.optimize.minimize()` 可实现 MLE-IC。与 D-GPD 不同，MLE-IC 不改变分布族（仍用连续 GPD），只改变似然函数。代码量约 30-40 行。

**MLE-IC 与 D-GPD 的关键区别**：

| 维度 | MLE-IC | D-GPD |
|------|--------|-------|
| 分布族 | 连续 GPD（不变） | 离散 GPD（新建） |
| VaR 反演 | 直接用 GPD 分位数（scipy 已实现） | 需要数值求根（无解析逆） |
| 似然 | \(F(x+δ/2) - F(x-δ/2)\) | \(F(k+1) - F(k)\)（δ=1 时与 MLE-IC 一致） |
| 与当前代码的兼容性 | **高**——只改拟合，不改 VaR/CVaR 公式 | **低**——需要完整的新分布类 |
| 理论基础 | 测量误差 / 区间删失文献 | 离散极值理论 |
| 文献成熟度 | Ma et al. (2024) + 区间删失的百年统计传统 | Hitz et al. (2024) + Krishna & Pundir (2009) |

### 2.4 综合对比与推荐

```
                 理论严谨性    数值性能    可实现性    与现代码兼容
                 ─────────    ────────    ────────    ───────────
方案A（连续GPD）   ⭐⭐⭐       ⭐⭐⭐⭐     ⭐⭐⭐⭐⭐    ⭐⭐⭐⭐⭐
方案B（D-GPD）     ⭐⭐⭐⭐      ⭐⭐⭐       ⭐⭐        ⭐
方案C（MLE-IC）    ⭐⭐⭐⭐⭐    ⭐⭐⭐⭐⭐    ⭐⭐⭐      ⭐⭐⭐⭐
```

**严谨性与表现最优方案：方案 C（MLE-IC）**。它拥有最高的理论严谨性（区间删失的似然是正确指定的），在数值上优于 naive 连续 MLE（尤其在有界支持 ξ < 0 和粗离散化时），且与现有 EVT 基础设施的兼容性远高于 D-GPD（只改似然函数，不改分布族，VaR/CVaR 反演无需变动）。

**但方案 A（当前方案）对抽卡模拟场景几乎是等价的**，理由：

1. **5000 次模拟 → 连续近似优良**：δ/σ 比值极小。对于 `resource_remaining`（σ ~ 数百至数千），δ=1 的离散化间距相对于 σ 可以忽略不计。Ma et al. (2024) 和 Deidda & Puliga (2009) 均确认当 δ/σ 小时 naive MLE 与 MLE-IC 几乎一致。
2. **Hitz et al. (2024) 的经验结论**：ties 少时（不同取值数 ≥ 20）连续 GPD 与 D-GPD 结果相似。
3. **退化数据已有回退**：不同取值数 < 20 的数据（此时 δ/σ 大，MLE-IC 的优势最明显）已通过经验分位数回退——此时经验分位数本身就是精确的。

**推荐策略**：

| 场景 | δ/σ 估计 | 推荐方案 | 理由 |
|------|---------|---------|------|
| 不同取值数 < 20 | 大 | 经验分位数（当前方案） | 格点间距即分辨率上限，EVT 无额外收益 |
| 不同取值数 ≥ 20 | 中-小 | 连续 GPD（当前方案） | Hitz et al. (2024) + Deidda & Puliga (2009) 确认偏差可忽略 |
| 未来升级（可选） | 任意 | MLE-IC（方案 C） | 最高理论严谨性；仅当有明确证据显示连续 GPD 偏差显著时才值得实施 |

---

## 三、连续 GPD 应用于离散数据的可靠性评估

### 3.1 分层评估

基于以上文献，对连续 GPD 在抽卡模拟离散数据上的可靠性进行分层评估：

| GDR 类别 | 示例指标 | 不同取值数 | 离散化间距 δ | 典型尺度 σ | δ/σ | 连续 GPD 可靠性 |
|----------|---------|-----------|------------|-----------|-----|---------------|
| **A 类（大值域）** | `resource_remaining` | 数百~数千 | 1 | 500~3000 | <0.002 | ✅ **高**——Deidda & Puliga (2009) 确认此比值下所有估计器无显著偏差 |
| **A 类（连续值）** | `weighted_satisfaction` | 数百~数千 | ~0 | 10~100 | ~0 | ✅ **高**——浮点连续值，无离散化问题 |
| **B 类（中等格点）** | `target_achievement` (N=50) | 51 | 1/50=0.02 | 0.2~0.5 | 0.04~0.10 | ✅ **可接受**——δ/σ ≈ 0.05-0.10，在 Deidda & Puliga 的「可忽略」范围内 |
| **B 类（边际格点）** | `target_collection` (K=6) | 7 | 1/6≈0.167 | 0.2~0.5 | 0.3~0.8 | ⚠️ **边际**——δ/σ 接近 Deidda & Puliga 的「退化」区域；Hitz et al. 建议在此类存在大量 ties 的数据上使用 D-GPD |
| **C 类（退化）** | `all_targets` | 2 | 1 | 0.4~0.6 | 1.7~2.5 | ❌ **不可靠**——δ/σ > 1，所有估计器崩溃；应回退经验分位数 |

### 3.2 阈值 < 20 的理论验证

当前方案选择 distinct < 20 作为跳过 EVT 的阈值。从 δ/σ 角度看：

- 对于值域 [0, 1] 的有理数格点 GDR（如 `target_collection`），distinct=20 意味着格点间距 δ = 1/19 ≈ 0.053
- GDR 的典型标准差 σ ~ 0.15-0.30
- δ/σ ≈ 0.18-0.35 → 接近 Deidda & Puliga (2009) 的「显著偏差」区域
- 因此 distinct < 20 作为跳过阈值在文献上是**合理的**，甚至是保守的（已在 δ/σ 开始有影响的区域就回退了）

### 3.3 与 Hitz et al. (2024) 的一致性

当前方案的核心设计原则——「ties 多时回退经验分位数，ties 少时使用连续 GPD」——与 Hitz et al. (2024) 的最核心发现完全一致：

> *"Both methods outperform the continuous GPD when there are many tied observations; otherwise results are similar."*

当不同取值数 ≥ 20 时，数据中 ties 的比例通常 < 5%（5000 个样本分布在 20+ 个格点上），连续 GPD 的偏差可忽略。当不同取值数 < 20 时，ties 比例可能 > 25%，此时经验分位数本身就是精确的（格点间距就是分辨率上限）。

### 3.4 MLE-IC 对极端分位数估计稳定性的提升——机制与边界

**核心问题**：MLE-IC 修正了似然函数，但这是否转化为更稳定的极端分位数估计？

**提升机制（三重）**：

1. **形状参数 ξ 的偏差校正 → VaR 偏差的乘数级缩减**

   极端分位数对 ξ 极为敏感。VaR(q) ∝ (1-q)^{-ξ} 的关系意味着：即使 ξ 的偏差只有 0.05，当外推到 q=0.01 时，VaR 的相对偏差会被放大 10-50 倍。MLE-IC 通过消除离散化导致的似然函数系统偏差，直接校正 ξ 的估计偏差——这是 MLE-IC 对极端分位数稳定性最重要的贡献。

2. **更多超额样本被保留**

   Ma et al. (2024) 的实际数据应用发现：MLE-IC 能在 9/18 个站点成功选择阈值，而 naive MLE 仅在 2/18 个站点成功。较低的阈值意味着更多的超额样本（n_exc ↑），GPD 拟合的方差 ∝ 1/√(n_exc)，直接转化为更窄的置信区间。报告结果：MLE-IC 的置信区间宽度在某些站点仅为 naive MLE 的 **1/10**。

3. **正确的 Fisher 信息矩阵 → 校准的渐近方差**

   区间删失似然的二阶导数（Hessian）正确反映了离散观测的实际信息含量。如果观测被舍入到 δ，则观测中包含的关于底层连续参数的信息确实少于连续似然所假设的——MLE-IC 正确地「知道」这一点，而 naive MLE 过度自信。

**边界与限制**：

1. **He et al. (2014) 的基本限制**（*Statistics and Its Interface*, Vol. 7, pp. 389–404）：

   > *"Better parameter estimation does not necessarily lead to better extreme quantile estimation."*

   即使 ξ 和 σ 被完美估计，极端分位数本身的抽样变异性仍然很大——特别是对 ξ ≥ 0.5（非常重尾）或 ξ < -0.5（非常短尾，接近有界支撑）的情况。MLE-IC 改进参数估计，但不能消除极端分位数估计的固有统计困难。

2. **离散化间距的硬天花板**

   Deidda & Puliga (2009) 的 Monte Carlo 模拟表明：当 δ/σ ≳ 0.5 时，**所有估计器**——包括理论上无偏的估计器——都严重退化。MLE-IC 只是修正了离散化偏差，并没有增加数据的信息含量。如果 δ 太大，数据本身就没有足够的信息来区分不同的参数值，任何方法都无济于事。

3. **阈值选择的连锁效应**

   MLE-IC 倾向于选择更低的阈值（保留更多超额样本），这通常有利——但阈值过低会引入非尾部数据，违反 GPD 的渐近假设。Ma et al. (2024) 的框架包含了拟合优度检验以验证阈值选择，但实践中这一环节容易被忽略。

**对抽卡模拟的结论**：

| GDR 类别 | δ/σ | MLE-IC 稳定性提升 |
|----------|-----|------------------|
| A 类（resource_remaining 等） | < 0.002 | **可忽略**（naive MLE 已接近无偏） |
| B 类边际（target_collection, K=6） | 0.3~0.8 | **显著**——ξ 偏差校正 + 置信区间收窄 |
| C 类（all_targets） | 1.7~2.5 | **仍不可靠**——δ/σ 超过任何方法的可用上限 |

**关键结论**：MLE-IC 在 δ/σ 大时（粗离散化网格）对极端分位数估计稳定性有**显著提升**，但在抽卡模拟的主流场景（模拟次数多、δ/σ 极小）中，这种提升可以忽略。MLE-IC 最有价值的应用场景是 B 类边际 GDR（target_collection 等有限格点但 ≥ 20 不同取值的指标）。

### 3.5 MLE-IC 与 Bootstrap 的兼容性

**三种 Bootstrap 路径的逐项分析**：

#### A. 参数 Bootstrap + MLE-IC（完全兼容，推荐方案）

这是最自然的集成路径。数据生成模型为：连续潜变量 → 离散化 → 观测。Bootstrap 精确复制此过程：

```
Step 1: 对原始离散数据拟合 MLE-IC → (ξ̂, σ̂)
Step 2: for b = 1..B:
  (a) 从连续 GPD(ξ̂, σ̂) 抽样 n 个值
  (b) 按原始数据的精度离散化（取整 / 舍入到格点）  ← 关键步骤
  (c) 对离散化后的 resample 拟合 MLE-IC → (ξ̂_b, σ̂_b)
  (d) 从 (ξ̂_b, σ̂_b) 计算 VaR_b
Step 3: VaR_b 的经验分位数 → 置信区间
```

**兼容性分析**：
- MLE-IC 只改变**拟合步骤**（1 和 2c），不改变抽样模型
- Bootstrap 正确复现了完整的数据生成过程（连续 GPD → 离散化）
- 每个 Bootstrap 迭代的 MLE-IC 拟合是独立的，可并行化
- 与现有 `BootstrapEngine._bootstrap_tail_gpd()` 的结构完全一致（仅替换 naive MLE 为 MLE-IC，并加入离散化步骤）

#### B. 非参数 Bootstrap + MLE-IC（兼容但次优）

```
Step 1: for b = 1..B:
  (a) 对原始离散数据做有放回重抽样
  (b) 对重抽样数据拟合 MLE-IC → (ξ̂_b, σ̂_b)
  (c) 计算 VaR_b
Step 2: VaR_b 的经验分位数 → 置信区间
```

**兼容性分析**：
- 技术上完全可行——MLE-IC 只是一个似然函数，接受任何数据
- 但每个重抽样中 ties 的模式与原始数据不同，某些重抽样可能触发退化检测
- **更严重的问题**：Schendel & Thongwichian (2017)（*Advances in Water Resources*, Vol. 99, pp. 53–59）系统比较了三种 GPD POT 置信区间方法：

  | 方法 | 覆盖率 | 表现 |
  |------|--------|------|
  | 百分位 Bootstrap | **严重低估**上下界 | ❌ 不推荐 |
  | 剖面似然 | 类似但较温和的低估 | ⚠️ 边际 |
  | **检验反演 Bootstrap（TIB）** | **合理覆盖，即使在大回归期** | ✅ 最佳 |

  百分位 Bootstrap 低估的原因是：它未正确建模 POT 的**双域结构**——超额发生次数（Poisson 过程）和超额幅度（GPD）的变异性被混淆了。这一发现直接挑战了当前 `BootstrapEngine._bootstrap_tail_gpd()` 使用的百分位法。

#### C. 检验反演 Bootstrap（TIB）+ MLE-IC（最严谨，但实现复杂）

Schendel & Thongwichian (2017) 的 TIB 算法：

```
对候选 VaR 值 y*，定义 H₀: VaR(q) = y*
在 H₀ 约束下，GPD 参数被约束为 σ = σ(ξ, y*)（由 VaR 公式反解）
从受限模型生成 Bootstrap 样本
计算检验统计量（Bootstrap VaR 估计）
比较观测统计量与 Bootstrap 分布 → 接受/拒绝 H₀
数值求根搜索 CI 端点
```

**优势**：覆盖率最优（Schendel & Thongwichian 2017）
**劣势**：双层循环（外层求根 + 内层 Bootstrap），B² 次 MLE-IC 拟合，计算成本高

#### 对现有 Bootstrap 计划的影响

当前 `_bootstrap_tail_gpd()` 使用百分位法 CI，Schendel & Thongwichian (2017) 的发现表明这是一个**方法论级别的缺陷**——百分位法在 GPD POT 设定下系统性低估 CI 宽度：

1. **短期修复**：在文档中标注百分位法的已知限制（Schendel & Thongwichian 2017），用户应知悉 GPD-param Bootstrap 的 CI **实际覆盖率低于名义水平**
2. **中期改进**：实现 TIB（检验反演 Bootstrap）替代百分位法。这需要 ~100 行新代码 + 修改 Bootstrap 的 CI 提取逻辑
3. **MLE-IC 集成**：仅在 δ/σ 大的场景（B 类边际 GDR）中有价值——对 A 类（δ/σ < 0.002），MLE-IC ≈ naive MLE，集成收益为零

**推荐优先级**：
1. 🔴 **修复百分位法 → TIB**（影响所有 GPD-param Bootstrap CI 的覆盖率）
2. 🟡 **实施 MLE-IC**（仅显著改善 B 类边际 GDR，对 A 类无影响）
3. 🔴 **TIB + MLE-IC 联合**（两个改进正交，可独立实施后组合）

### 3.6 δ/σ 比值在何种池子配置下足够大——场景分析

上述分析的结论是：MLE-IC 仅在 δ/σ > 0.1 时提供有意义的改善。本节分析在何种池子配置下这一条件会被满足。

**关键概念澄清**：

- δ = 离散化间距（整数型 GDR 为 1，有理数比值型 GDR 为 1/分母）
- σ = GPD 尾部尺度参数 β（不是全分布的标准差）
- δ/β 决定离散化偏差的严重程度（Deidda & Puliga 2009）
- **反直觉效应**：模拟次数越多 → 分布越集中 → **δ/β 可能越大**（尾部更「紧」→ 格点间距相对更大）→ 离散化问题更显著

#### 整数型 GDR（A 类主流）

| GDR | δ | 典型 β（尾部尺度） | δ/β | 结论 |
|-----|---|-------------------|------|------|
| `resource_remaining` | 1 | 300~3000 | < 0.003 | **始终可忽略** |
| `resource_consumed` | 1 | 300~3000 | < 0.003 | **始终可忽略** |
| `non_pity_draws` | 1 | 200~2000 | < 0.005 | **始终可忽略** |
| `extra_target` | 1 | 1~5 | 0.2~1.0 | ⚠️ **大**——但 distinct 通常 < 20，EVT 已被跳过 |
| `target_card_draws` | 1 | 5~30 | 0.03~0.2 | **边际**——高值配置时 δ/β 可能 > 0.1 |

**结论**：主流 A 类整数型 GDR（`resource_remaining` 等）的 δ/β < 0.005，**MLE-IC 无实际收益**。唯一的例外是 `target_card_draws`（抽取目标卡的次数）——其尾部尺度较小，在高目标数配置中 δ/β 可能达到 ~0.2。

#### 有理数比值型 GDR（B 类 + C 类）

对于比率型 GDR，δ = 1/K（K = 类别/格点数），β 为尾部尺度。以 `target_achievement` 为例（值域 k/N，步长 1/N）：

| 目标总量 N | distinct = N+1 | δ = 1/N | 典型尾部 β | δ/β | EVT 状态 | MLE-IC 收益 |
|-----------|---------------|---------|-----------|------|---------|------------|
| N=5 | 6 | 0.200 | 0.08~0.15 | 1.3~2.5 | ❌ 跳过（distinct < 20） | N/A |
| N=10 | 11 | 0.100 | 0.06~0.12 | 0.8~1.7 | ❌ 跳过（distinct < 20） | N/A |
| N=15 | 16 | 0.067 | 0.05~0.10 | 0.7~1.3 | ❌ 跳过（distinct < 20） | N/A |
| **N=20** | **21** | **0.050** | 0.04~0.08 | **0.6~1.3** | ✅ **启用**（distinct ≥ 20） | **显著** |
| **N=30** | **31** | **0.033** | 0.03~0.07 | **0.5~1.1** | ✅ 启用 | **显著** |
| N=50 | 51 | 0.020 | 0.03~0.06 | 0.3~0.7 | ✅ 启用 | 中等 |
| N=100 | 101 | 0.010 | 0.02~0.05 | 0.2~0.5 | ✅ 启用 | 轻微-中等 |

**关键发现**：

1. **N < 20 时**：distinct < 20，EVT 被跳过，经验分位数已精确——**MLE-IC 不需要**
2. **N = 20-50 时**：distinct ≥ 20（EVT 启用）但 δ/β 仍然很大（0.3-1.3）——**MLE-IC 有显著收益**
3. **N > 50 时**：δ/β 下降至 0.2-0.5，MLE-IC 收益递减

对于其他比值型 GDR：

| GDR | 分母 | δ | 典型场景 | δ/β（distinct ≥ 20） | MLE-IC 收益 |
|-----|------|---|---------|---------------------|------------|
| `target_collection` | K（目标种类数） | 1/K | K=3~10 典型 | K≤10 → δ/β 大但 distinct < 20，EVT 跳过；K≥20 不常见 | 通常 N/A |
| `ssr_collection` | M（SSR 种类数） | 1/M | M=5~20 典型 | M≥20 → distinct=21，δ/β≈0.4-0.8 | **显著**（M≥20 时） |
| `target_achievement` | N（总需求数） | 1/N | N=20~50 常见 | δ/β≈0.3-1.3 | **显著**（N=20-50 时） |

#### 配置场景速查

| 池子配置 | target_achievement 的 N | δ/β 级别 | 建议 |
|---------|------------------------|---------|------|
| 5 目标 × 1 张 | N=5 | N/A（跳过 EVT） | 经验分位数 ✓ |
| 5 目标 × 4 张 | N=20 | **大**（δ/β≈0.6-1.3） | **MLE-IC 推荐** |
| 5 目标 × 7 张 | N=35 | 大（δ/β≈0.4-0.9） | MLE-IC 推荐 |
| 5 目标 × 10 张 | N=50 | 中等（δ/β≈0.3-0.7） | MLE-IC 可选 |
| 10 目标 × 2 张 | N=20 | **大**（δ/β≈0.6-1.3） | **MLE-IC 推荐** |
| 3 目标 × 5 张 | N=15 | N/A（跳过 EVT） | 经验分位数 ✓ |
| 20 SSR × 1 张 | M=20 (ssr_collection) | 大（δ/β≈0.4-0.8） | **MLE-IC 推荐** |

#### 总结

MLE-IC **仅在特定池子配置中有显著收益**——主要是 B 类边际 GDR（ratio 型，distinct 刚好 ≥ 20，即 N=20~50 的 `target_achievement` 或 M≥20 的 `ssr_collection`）。对于 A 类主流 GDR（`resource_remaining` 等整数大值域指标），δ/β < 0.005，MLE-IC 无实际价值。**大多数实际配置（5-10 目标类型 × 1-3 副本 = N=5-30）中，target_achievement 的 N 通常 < 20，EVT 已被跳过，所以 MLE-IC 在典型配置下的适用范围进一步缩小。**

---

### 3.1 分类维度

| 维度 | 说明 |
|------|------|
| **值域** | 取值区间 |
| **值类型** | 整数 / 有理数 / 实数值 |
| **不同取值数** | 5000 次模拟中预期的不同取值个数（决定 GPD 连续近似的质量） |
| **尾部特征** | 有界 / 指数衰减 / 正态尾 |

### 3.2 全量分类

#### A 类：EVT 完全适用（值域广、近似连续）

| # | GDR key | 值域 | 值类型 | 不同取值数 | 尾部特征 |
|---|---------|------|--------|-----------|---------|
| 1 | `resource_remaining` | [0, +∞) | 整数 | 数百~数千 | 有下界，上尾近似正态 |
| 2 | `resource_consumed` | [0, +∞) | 整数 | 数百~数千 | 有下界，上尾近似正态 |
| 3 | `non_pity_draws` | [0, +∞) | 整数 | 数百~数千 | 有下界，上尾近似正态 |
| 4 | `pity_draws` | [0, +∞) | 整数 | 数十~数百 | 混合分布，上尾有界（保底截断） |
| 5 | `resource_efficiency` | [0, 1/成本] | 连续值 | 数百~数千 | 有界 |
| 6 | `resource_per_card` | [0, +∞) | 连续值 | 数百~数千 | 右偏，上尾近似正态 |
| 7 | `weighted_satisfaction` | (-∞, +∞) | 连续值 | 数百~数千 | 近似正态 |
| 8 | `total_card_value` | [0, +∞) | 连续值 | 数百~数千 | 近似正态 |
| 9 | `draw_conversion_efficiency` | [0, +∞) | 连续值 | 数百~数千 | 右偏 |

**处置**：EVT 正常启用。

#### B 类：EVT 边际适用（有限格点，但仍有一定分辨率）

| # | GDR key | 值域 | 值类型 | 不同取值数 | 尾部特征 |
|---|---------|------|--------|-----------|---------|
| 10 | `target_achievement` | [0, 1] | 有理数 k/N | 11~101（取决于 N=Σtarget_qty） | 有界 [0,1] |
| 11 | `target_collection` | [0, 1] | 有理数 k/K | K+1（K=目标种类数，通常 3~10） | 有界 [0,1] |
| 12 | `ssr_collection` | [0, 1] | 有理数 k/M | M+1（M=SSR 种类数，通常 5~20） | 有界 [0,1] |
| 13 | `extra_target` | {0,1,2,...} | 整数 | 10~50 | 有下界，上尾衰减 |
| 14 | `target_card_draws` | {0,1,2,...} | 整数 | ~Σtarget_qty | 有下界，上尾衰减 |
| 15 | `per_pool_draw_rate` | [0, +∞) | 有理数 | 数十~数百 | 右偏 |

**处置**：取决于不同取值数。当不同取值数 ≥ 20 时 EVT 可用；< 20 时自动跳过。当前通过自动检测（§四）统一处理。

#### C 类：EVT 完全不适用（退化/近退化分布）

| # | GDR key | 值域 | 不同取值数 | 原因 |
|---|---------|------|-----------|------|
| 16 | `all_targets` | {0, 1} | 2 | 二元 Bernoulli，GPD 拟合无意义 |
| 17 | `weapon_character_ratio` | {0}（当前） | 1 | 配置缺失导致恒为 0，完全退化 |

**处置**：必须跳过 EVT。`weapon_character_ratio` 未来有配置入口后可能不再退化，届时自动检测会重新启用。

### 3.3 已知截断场景（已处理）

`WorstImpactAnalyzer` 资源类 GDR + `condition='success'` 时跳过 EVT（P24 §2.1.1 方案 B）。此逻辑不变。

---

## 五、改进方案：自动退化检测

### 4.1 思路

在 `EmpiricalDistribution` 中添加自动检测：如果数据的不同取值数过少，EVT 外推无意义，自动回退经验分位数。

这是比按 GDR key 逐个标记更稳健的方案——它不依赖调用方传递正确的 GDR key，而是从数据本身判断。

### 4.2 阈值选择

**不同取值数 < 20 → 跳过 EVT。**

理由：
- GPD MLE 至少需要 20-30 个超额样本（Hosking & Wallis 1987）
- 如果整个数据集只有不到 20 个不同取值，尾部（5%）只覆盖 1-2 个不同取值，GPD 拟合完全无意义
- 此时经验分位数本身就很精确（格点间距就是分辨率上限，插值没有帮助）

### 4.3 实现

```python
class EmpiricalDistribution:
    def __init__(self, samples):
        ...
        self._distinct_count = None  # 惰性计算 + 缓存

    def _count_distinct(self):
        if self._distinct_count is None:
            if self._n == 0:
                self._distinct_count = 0
            else:
                count = 1
                for i in range(1, self._n):
                    if self._sorted[i] != self._sorted[i-1]:
                        count += 1
                self._distinct_count = count
        return self._distinct_count

    def _evt_quantile(self, p):
        if self._count_distinct() < 20:
            return None  # 退化数据，回退经验分位数
        ...
```

### 4.4 影响范围

| 场景 | 不同取值数 | 自动检测结果 |
|------|-----------|-------------|
| `all_targets` 二元 | 2 | → 跳过 EVT |
| `weapon_character_ratio` 退化 | 1 | → 跳过 EVT |
| `target_collection` 5 种目标 | 6 | → 跳过 EVT |
| `target_achievement` Σ=10 | 11 | → 跳过 EVT |
| `target_achievement` Σ=50 | 51 | → EVT 正常启用 |
| `resource_remaining` | 数百~数千 | → EVT 正常启用 |

### 4.5 关于 target_achievement 的边界情况

`target_achievement` 的值域是 k/N，其中 N = Σ target_specs.values()。例如：
- 需要 1+1+1+1+1=5 张卡 → N=5，6 个不同取值 → 跳过 EVT
- 需要 3+3+3+3+3=15 张卡 → N=15，16 个不同取值 → 跳过 EVT
- 需要 7+7+7+7+7=35 张卡 → N=35，36 个不同取值 → EVT 启用

对于典型的配置（5-10 张目标卡 × 1-3 张需求 = 5-30 总需求），N ≤ 30 时不同取值数 ≤ 31，其中 N ≤ 19 的被自动跳过。边界场景（N=20~30）EVT 边际可用。

---

## 六、跳过/检测方法的实现细节补充

### 5.1 当前 EVT 跳过条件的完整清单

当前 `EmpiricalDistribution` 中 EVT 跳过条件分散在多处，以下是完整梳理：

| 检查位置 | 条件 | 跳过行为 |
|----------|------|---------|
| `quantile()` | `use_evt=False` | 直接走经验分位数 |
| `quantile()` | `n < 100` | 不触发 EVT，走经验分位数 |
| `quantile()` | `p ∈ (0.1, 0.9)` | 非极端分位数，走经验分位数 |
| `_evt_quantile()` | `distinct < 20` | 退化数据，回退经验分位数 |
| `_evt_cvar()` | `distinct < 20` | 退化数据，回退经验 CVaR |
| `fit_gpd_upper()` | `n < 100` | 样本不足，返回 None |
| `fit_gpd_upper()` | `n_exc < 10` | 超额样本不足，返回 None |
| `_fit_gpd()` | `n_exc < 10` | 超额样本不足，返回 None |
| `_fit_gpd()` | ξ < -1 | MLE 不存在（Smith 1985），返回 None |
| `_fit_gpd()` | ξ < -0.5 | MLE 渐近性质不成立，仅警告，点估计仍可用 |
| `evt_var_right()` | `tail_prob > φ` | q 在阈值覆盖范围内，无需外推，返回 None |
| `evt_var_right()` | `var ≥ endpoint`（ξ < 0 有界支撑） | 外推越界，返回 None |

### 5.2 建议：统一 EVT 适用性判定方法

当前跳过逻辑分散在 4 个方法中（`quantile` / `_evt_quantile` / `_evt_cvar` / `_fit_gpd`），不利于维护和 UI 查询。建议抽取统一的判定方法：

```python
class EmpiricalDistribution:
    # ── EVT 适用性判定 ──

    _EVT_MIN_SAMPLES = 100       # 触发 EVT 的最小样本数
    _EVT_MIN_DISTINCT = 20       # 触发 EVT 的最小不同取值数
    _EVT_EXTREME_LOW = 0.1       # 下尾极端分位数阈值
    _EVT_EXTREME_HIGH = 0.9      # 上尾极端分位数阈值

    def _evt_applicable(self, p: float) -> Tuple[bool, str]:
        """统一的 EVT 适用性判定。

        Returns:
            (applicable, reason) —— applicable=False 时 reason 说明跳过原因
        """
        if self._n < self._EVT_MIN_SAMPLES:
            return False, f"样本不足（n={self._n} < {self._EVT_MIN_SAMPLES}）"
        if not (p <= self._EVT_EXTREME_LOW or p >= self._EVT_EXTREME_HIGH):
            return False, f"非极端分位数（p={p}）"
        if self._count_distinct() < self._EVT_MIN_DISTINCT:
            return False, f"退化数据（distinct={self._distinct_count} < {self._EVT_MIN_DISTINCT}）"
        return True, "OK"

    @property
    def evt_status(self) -> dict:
        """EVT 状态快照——供 UI 查询。

        Returns:
            {'sample_size': int, 'distinct_count': int,
             'evt_available': bool, 'lower_fitted': bool, 'upper_fitted': bool}
        """
        return {
            'sample_size': self._n,
            'distinct_count': self._count_distinct(),
            'evt_available': self._n >= 100 and self._count_distinct() >= 20,
            'lower_fitted': self._evt_lower is not None,
            'upper_fitted': self._evt_upper is not None,
        }
```

然后在 `_evt_quantile()` 和 `_evt_cvar()` 中统一调用 `_evt_applicable(p)`，消除分散的重复检查。

### 5.3 退化检测阈值的理论依据补充

当前选择 `< 20` 不同取值作为跳过 EVT 的阈值，依据：

1. **GPD MLE 最小超额样本数**：Hosking & Wallis (1987) 建议至少 20-30 个超额样本。如果整个数据集只有不到 20 个不同取值，尾部 5% 只覆盖 1-2 个不同取值，GPD 拟合完全无意义。
2. **经验分位数的精确性**：当不同取值数 < 20 时，格点间距就是分辨率上限。线性插值在两个相邻格点之间内插，并不能提供比格点本身更多的信息——此时经验分位数本身就是精确的。
3. **scipy 默认行为**：`scipy.stats.genpareto.fit()` 在超额样本 < 10 时数值不稳定，我们的 `_fit_gpd()` 已设置此下限。不同取值数 < 20 意味着即使全部数据都作为"超额"也不够。

### 5.4 已排除的检测方法

以下方法曾被考虑但未采用：

| 方法 | 排除理由 |
|------|---------|
| 按 GDR key 逐个标记 | 不如数据驱动检测稳健——不依赖调用方传递正确的 key，新 GDR 自动受益 |
| 基于方差/熵的检测 | 二元数据（如 all_targets {0,1}）方差可能很大（p≈0.5 时），不能有效区分退化 |
| 基于唯一值比例的检测 | 与 `_count_distinct()` 等价但计算更复杂 |
| 直方图分箱数检测 | 依赖分箱参数选择，不稳定 |

---

## 七、EVT 使用状态的 UI 显示计划

### 6.1 目标

让用户能够直观了解：哪些 GDR 指标的 VaR/CVaR 使用了 EVT 外推，哪些因数据特征跳过了 EVT，以及跳过原因是什么。

### 6.2 三层显示方案

#### 第一层：关于对话框（`about_dialog.py`）

**改动**：在现有「EVT 尾部拟合」条目中追加一项说明。

```html
<li><b>退化分布自动跳过</b>：当数据不同取值数 &lt; 20 时（如二元指标 all_targets、
    有限格点指标 target_collection），自动跳过 GPD 拟合，使用经验分位数——
    此时经验分位数本身已精确，EVT 外推无额外收益</li>
```

**工作量**：~3 行 HTML，< 5 分钟。

#### 第二层：分析面板 GDR 统计表格（`analysis_panel.py`）

**改动**：在 GDR 统计表格的 VaR/CVaR 单元格中附加 EVT 状态标记。

**方案 A（推荐——轻量）**：VaR 单元格值后追加小标记：
- EVT 正常使用：无额外标记（默认行为，用户无需关心）
- EVT 被跳过：值后追加 `†` 符号，表尾注脚说明「† 该指标数据不足或取值过少，VaR/CVaR 使用经验分位数，未经 EVT 外推」

**方案 B（完整——后续实施）**：新增可选的「EVT 状态」列或 Tooltip：
- 鼠标悬停 VaR/CVaR 单元格时显示 Tooltip：
  - `"GPD 外推 (ξ=-0.12, n_exc=250)"` — EVT 正常
  - `"经验分位数 (distinct=6, 跳过 EVT)"` — 退化跳过
  - `"经验分位数 (n=50, 样本不足)"` — 样本不足跳过

**推荐采用方案 A 作为当前实施目标**（改动量极小，< 10 行），方案 B 留待后续根据用户反馈决定是否实施。

#### 第三层：独立 EVT 诊断面板（长期可选）

在「统计分析」Tab 或独立面板中展示：
- 各 GDR 的 EVT 拟合状态矩阵（指标 × 状态）
- GPD 拟合参数（ξ, β）及阈值稳定性图
- 超额样本数与阈值的关系

**优先级**：低。当前 EVT 是透明的底层优化，过度的诊断信息可能让用户困惑。仅在用户明确需要时才实施。

### 6.3 实施优先级

| 优先级 | 层级 | 改动量 | 建议时间 |
|--------|------|--------|---------|
| 🔴 立即 | 第一层：about_dialog 补充说明 | ~3 行 | 本次 |
| 🟡 短期 | 第二层方案A：VaR 单元格标记 | ~10 行 | 本次或下一轮 |
| 🟢 中期 | 第二层方案B：Tooltip + 详细诊断 | ~50 行 | 按需 |
| ⬜ 长期 | 第三层：独立诊断面板 | 新面板 | 暂不实施 |

---

## 八、Bootstrap 对 EVT 的依赖分析与计划修改

### 7.1 当前状态：两套独立的 GPD 拟合

Bootstrap 和 EVT 各自维护了独立的 GPD 拟合代码路径：

| 组件 | 文件 | GPD 拟合方式 | 退化检测 |
|------|------|-------------|---------|
| EVT 核心 | `evt_tail.py` | `scipy.stats.genpareto.fit()` + MLE 正则性检查 | 无（依赖调用方的 `_count_distinct()` 守卫） |
| Bootstrap GPD | `bootstrap.py:205-236` | 直接 `genpareto.fit(-excess, floc=0)` | 仅 `len(excess) < 20` 检查 |
| EmpiricalDistribution | `distribution.py` | 委托给 `evt_tail.py` | `_count_distinct() < 20` |

**问题**：

1. **重复实现**：`_bootstrap_tail_gpd()` 重新实现了 GPD 拟合逻辑（`genpareto.fit(-excess, floc=0)`），而不是复用 `evt_tail.fit_gpd_lower()`
2. **退化检测不一致**：Bootstrap 的 GPD 路径没有 `_count_distinct()` 检查，只检查了超额样本数。binary 数据的 Bootstrap 重抽样可能产生全是 0 或全是 1 的 resample，GPD 拟合在这些退化 resample 上会静默失败
3. **ξ<-1 正则性检查缺失**：Bootstrap 路径没有 `evt_tail._fit_gpd()` 中的 Smith (1985) MLE 正则性条件检查
4. **阈值策略不同**：EVT 核心使用自适应阈值（100-500 超额样本），Bootstrap 使用固定 q=0.2 阈值——不一致的阈值可能导致 VaR 点估计和 Bootstrap CI 的系统性偏差

### 7.2 建议：统一 GPD 拟合路径（含 MLE-IC 和 TIB）

`bootstrap.py` 的 `_bootstrap_tail_gpd()` 应改为委托 `evt_tail.fit_gpd_lower()` + `evt_tail.evt_var_right()`，而非自行拟合：

```python
# bootstrap.py 修改后
from .evt_tail import fit_gpd_lower, evt_var_right

def _bootstrap_tail_gpd(self, data: np.ndarray, q: float) -> BootstrapResult:
    """参数 Bootstrap：对每次重抽样拟合 GPD，计算分位数 CI。"""
    n = len(data)
    
    # 复用 EVT 核心的退化检测
    from .distribution import EmpiricalDistribution
    tmp_dist = EmpiricalDistribution(list(data))
    if tmp_dist._count_distinct() < 20:
        return self.bootstrap_quantile(data, q, use_gpd=False)
    
    point_est = float(np.quantile(data, q))
    boot_quants = np.zeros(self.B)
    
    for b in range(self.B):
        indices = self._rng.integers(0, n, size=n)
        resample = data[indices]
        
        # 统一使用 evt_tail 的 GPD 拟合
        gpd_fit = fit_gpd_lower(resample)
        if gpd_fit is None:
            # GPD 拟合失败 → 对该 resample 使用经验分位数
            boot_quants[b] = float(np.quantile(resample, q))
            continue
        
        xi, beta, u_Y, phi = gpd_fit
        q_y = 1.0 - q
        var_y = evt_var_right(q_y, xi, beta, u_Y, phi)
        if var_y is None:
            boot_quants[b] = float(np.quantile(resample, q))
        else:
            boot_quants[b] = -var_y
    
    _, ci_low, ci_high, std = self._percentile_ci(boot_quants, point_est)
    return BootstrapResult(point_est, ci_low, ci_high, std,
                           'GPD-param (unified EVT)', n, self.B)
```

### 7.3 Bootstrap 计划（`docs/P18 Bootstrap稳定性分析改进计划.md`）的修改建议

基于以上分析，Bootstrap 计划需新增/修改以下条目：

#### 新增条目：B2.8 — EVT 拟合路径统一

- **文件**：`core/bootstrap.py` 的 `_bootstrap_tail_gpd()`
- **改动**：
  1. 替换直接 `genpareto.fit()` 为委托 `evt_tail.fit_gpd_lower()` + `evt_tail.evt_var_right()`
  2. 在 GPD-param bootstrap 循环前加入退化检测（`_count_distinct() < 20`）
  3. 每个 resample 的 GPD 拟合失败时回退该 resample 的经验分位数（而非回退整个 Bootstrap）
  4. 删除 `_bootstrap_tail_gpd()` 中的 `genpareto` 直接导入（统一通过 `evt_tail` 访问）
- **测试**：新增测试验证退化 resample 的回退行为 + 与 `evt_tail` 结果一致性

#### 新增条目：B2.9 — 百分位法 CI → TIB（检验反演 Bootstrap）（NEW — 2026-05-28 文献审查发现）

- **来源**：Schendel & Thongwichian (2017) + §三.5 的详细分析
- **问题**：当前 `_bootstrap_tail_gpd()` 使用百分位法构造 GPD VaR 的置信区间，但 Schendel & Thongwichian (2017) 证明百分位法在 POT 框架下**系统性低估**上下置信界（未能正确建模超额发生次数和超额幅度的双域结构）
- **推荐替代**：检验反演 Bootstrap（TIB）——对候选 VaR 值反演假设检验，搜索 CI 端点
- **复杂度**：中高（双层循环：外层数值求根 + 内层 Bootstrap），~100 行新代码
- **优先级**：🔴 高于 MLE-IC 集成——影响所有 GPD-param Bootstrap CI 的实际覆盖率
- **与 MLE-IC 的关系**：TIB 和 MLE-IC 是两个正交改进——TIB 改进 CI 构造方法，MLE-IC 改进参数估计精度。可独立实施后组合。

#### 修改现有条目：问题 2（厚尾检测）→ 简化

当前 Bootstrap 计划的「问题 2：厚尾检测未自动采纳」建议在 `bootstrap_mean()` 中增加 `auto_heavy_tail` 参数。由于 EVT 核心（`evt_tail.py`）已经实现了可靠的 GPD 拟合，Bootstrap 的厚尾路径应统一委托给 EVT 核心，而非维护独立的 GPD 逻辑。

#### 新增条目：B3.0 — VaR CI 从「待实现」升级为可用（含 TIB 警告）

Bootstrap 计划 §7.4 中 VaR CI 标注为「待实现」（等待 P4 EVT 完成）。P24 已实现 EVT 核心，B2.8（EVT 路径统一）完成后 VaR 的参数 GPD Bootstrap CI 即可正式启用。

**⚠️ 2026-05-28 更新**：Schendel & Thongwichian (2017) 的发现表明，即使实现了 GPD-param Bootstrap CI，使用的百分位法 CI 构造也存在覆盖率缺陷（系统性低估置信界）。因此 B3.0 的交付物应包括：(1) 基本 GPD-param Bootstrap CI（百分位法，附已知限制警告），(2) 文档注明用户应知晓 CI 实际覆盖率低于名义水平，(3) B2.9（TIB 升级）为后续改进路径。

### 7.4 Bootstrap-EVT 统一后的数据流

```
BootstrapEngine._bootstrap_tail_gpd(data, q=0.05)
  │
  ├─ EmpiricalDistribution._count_distinct()  ← 退化检测（P25 新增）
  │   └─ distinct < 20 → 回退标准百分位法 Bootstrap
  │
  └─ for b in 1..B:
       ├─ resample = data[rng.choice(n, n)]
       │
       ├─ evt_tail.fit_gpd_lower(resample)    ← 统一 GPD 拟合（P24）
       │   ├─ _fit_gpd(exceedances)            ← MLE + 正则性检查
       │   └─ 失败 → 回退该 resample 的经验分位数
       │
       ├─ evt_tail.evt_var_right(q_Y, ξ, β, u_Y, φ)  ← 统一 VaR 公式（P24）
       └─ VaR_X = -VaR_Y
```

---

## 九、DGPD「几十行代码」可行性评估

### 8.1 背景

有人声称「使用 DGPD 只需要几十行代码」。本节评估这一声称的真实性，并调查是否有成熟库可用。

### 8.2 DGPD 的数学定义

离散广义 Pareto 分布（DGPD）通过离散化连续 GPD 构造：

\[
P(X = k) = F_{\text{GPD}}(k+1; \xi, \sigma) - F_{\text{GPD}}(k; \xi, \sigma)
\]

其中 \(F_{\text{GPD}}(x) = 1 - (1 + \xi x/\sigma)_{+}^{-1/\xi}\) 是连续 GPD 的 CDF。

### 8.3 最小可行实现（~20 行）

使用 `scipy.stats.genpareto.cdf()` + `scipy.optimize.minimize()` 确实可以在 ~20 行内实现 DGPD 的 MLE 拟合：

```python
import numpy as np
from scipy.stats import genpareto
from scipy.optimize import minimize

def _dgpd_nll(params, excesses):
    """DGPD 负对数似然。"""
    xi, sigma = params
    if sigma <= 0:
        return np.inf
    # GPD CDF: F(k+1) - F(k)
    cdf_hi = genpareto.cdf(excesses + 1, xi, scale=sigma)
    cdf_lo = genpareto.cdf(excesses, xi, scale=sigma)
    pmf = cdf_hi - cdf_lo
    # 数值安全：截断极小正数
    pmf = np.clip(pmf, 1e-300, None)
    return -np.sum(np.log(pmf))

def fit_dgpd(excesses):
    """拟合 DGPD(ξ, σ) 到整数超额值。"""
    # 初始值：连续 GPD MLE
    shape_init, _, scale_init = genpareto.fit(excesses, floc=0)
    res = minimize(
        _dgpd_nll,
        x0=[shape_init, scale_init],
        args=(excesses,),
        method='Nelder-Mead',
        bounds=[(-2.0, 5.0), (1e-6, None)],
    )
    if res.success:
        return res.x[0], res.x[1]  # (xi, sigma)
    return None
```

**行数**：~25 行（含空行和注释）。声称「几十行代码」在技术上是正确的。

### 8.4 成熟库调查

| 库/语言 | DGPD 支持 | 说明 |
|---------|----------|------|
| **scipy** (Python) | ❌ 无 | 仅有连续 `genpareto`，无离散版本 |
| **scipy.stats** 全部离散分布 | ❌ 无 | 含 Poisson/NB/ZIP 等 30+ 离散分布，无 DGPD |
| **statsmodels** (Python) | ❌ 无 | 含离散选择模型、计数回归，无 EVT 离散分布 |
| **R `mev` 包** | ⚠️ 边际 | 含 GPD 拟合工具，无独立 DGPD 函数 |
| **R `extRemes`** | ❌ 无 | 极值分析主流 R 包，无 DGPD |
| **R `VGAM`** (Vector GLM) | ⚠️ 可能 | 通过自定义族函数可能间接支持，但无现成 DGPD 族 |

**结论：Python 生态中**没有**任何成熟库提供 DGPD 的 MLE 拟合或分布函数。** R 生态中也没有独立、成熟的 DGPD 包。

### 8.5 隐藏的复杂性与风险

上述 25 行「最小可行实现」与生产级代码之间存在显著差距：

| 问题 | 最小实现 | 生产级需求 |
|------|---------|-----------|
| **数值稳定性** | `np.clip(pmf, 1e-300, None)` 粗暴截断 | 需 log-space 计算：`log(F(k+1) - F(k))` 通过 `log1p` / `logsumexp` 避免灾难性抵消 |
| **MLE 收敛** | 单起点 Nelder-Mead | 需多起点（~5 个不同初始值）+ BFGS/L-BFGS-B 梯度方法，避免局部最优 |
| **边界 ξ 的 MLE 行为** | 无处理 | ξ < -1 时 MLE 不存在（Smith 1985）——与连续 GPD 相同，DGPD 也不例外 |
| **标准误计算** | 无 | 需 Hessian 逆矩阵或 Bootstrap 计算参数不确定性 |
| **拟合优度检验** | 无 | 需 χ² 或离散 KS 检验判断 DGPD 是否适合数据 |
| **小样本行为** | 未知 | n < 30 时 MLE 偏差大，需偏差校正或贝叶斯方法 |
| **VaR/CVaR 反演** | 无 | 从 DGPD 参数反演 VaR 需要求根（DGPD 的 CDF 无解析逆函数） |

**保守估计**：一个可靠的 DGPD 实现（含数值安全 + 多起点优化 + 正则性检查 + 拟合优度 + VaR 反演）需要 **150-250 行**，且需要深入的 EVT 领域知识进行验证。

### 8.6 使用 scipy 的连续 GPD 替代方案：连续性校正

对于值域较大（≥20 不同取值）的离散数据，更实用的方案是在现有连续 GPD 框架上加**连续性校正**（continuity correction），而非实现完整的 DGPD：

```python
# 连续性校正：对整数离散数据，在 CDF 评估点加 0.5
# P(X ≤ k)_continuous ≈ P(X ≤ k + 0.5)_discrete
def _evt_var_discrete(q, xi, beta, u, phi):
    """带连续性校正的离散 EVT VaR。"""
    var_continuous = evt_var_right(q, xi, beta, u, phi)
    if var_continuous is None:
        return None
    # 向下取整 + 0.5 偏移（标准连续性校正）
    return np.floor(var_continuous + 0.5)
```

但即使是这个方案，**在当前场景下的收益也极微**——不同取值数 ≥ 20 时，连续 GPD 的近似误差已小于 Bootstrap CI 宽度；不同取值数 < 20 时，经验分位数本身就是精确的。

### 8.7 结论与建议

| 维度 | 评估 |
|------|------|
| 「几十行代码」声称 | **技术上正确**——~25 行可实现基本 DGPD MLE |
| 成熟 Python 库 | **不存在**——scipy/statsmodels 均无 DGPD 支持 |
| 生产级可靠性 | **不可行**——数值安全 + MLE 收敛 + 检验需要 150-250 行 + 深入领域知识 |
| 对当前项目的收益 | **极低**——不同取值数 <20 时经验分位数已精确，≥20 时连续 GPD 近似已足够 |
| 可维护性成本 | **高**——团队需维护一个无社区参考实现的非标准统计方法 |

**建议**：
1. **不引入 DGPD**——当前「distinct < 20 跳过 EVT + distinct ≥ 20 连续 GPD」策略在理论和工程上都足够稳健
2. **不引入连续性校正**——同理，收益不足以覆盖新增代码的维护成本
3. **如果未来有明确的用户反馈**（如某个 GDR 的 VaR EVT 估计与经验分位数偏差显著且无法用 Bootstrap 解释），再重新评估 DGPD

### 8.8 对计划 §一（原 DGPD 评估）的补充

本节的结论与 §一 完全一致——「不推荐采用 DGPD」——但补充了具体的代码可行性分析和成熟库调查结果。原 §一 的结论表和理由不变。

---

## 十、更新的实施清单

### 9.1 已实施

- [x] `_count_distinct()` 惰性计算 + 缓存
- [x] `_evt_quantile()` 和 `_evt_cvar()` 中 distinct < 20 守卫
- [x] 7 项退化数据测试

### 9.2 待实施（本计划）

- [ ] **5.2 统一 EVT 适用性判定方法**：抽取 `_evt_applicable(p)` + `evt_status` property（`distribution.py`，~40 行）
- [ ] **6.2 第一层**：更新 `about_dialog.py` 算法说明——注明退化分布自动跳过 EVT（~3 行）
- [ ] **6.2 第二层方案A**：GDR 统计表格 VaR 单元格追加退化标记（`analysis_panel.py`，~10 行）
- [ ] 更新测试覆盖新增的 `_evt_applicable()` 方法

### 9.3 待实施（需更新 Bootstrap 计划）

- [ ] **7.2 统一 GPD 拟合路径**：`_bootstrap_tail_gpd()` 委托 `evt_tail.fit_gpd_lower()`（`bootstrap.py`，~30 行）
- [ ] **7.3 B2.9 TIB 升级**：将 GPD-param Bootstrap 的 CI 构造从百分位法替换为检验反演 Bootstrap（`bootstrap.py`，~100 行，优先级高于 MLE-IC）
- [ ] **7.3 B3.0**：VaR CI 从「待实现」升级为可用，附带百分位法已知限制警告（`analysis_panel.py` + `bootstrap.py`）
- [ ] 更新 `docs/P18 Bootstrap稳定性分析改进计划.md`——新增 B2.8 + B2.9 条目 + 修改问题 2 + 更新 §7.4 VaR CI 状态
- [ ] **（可选——低优先级）** 对 B 类边际 GDR（δ/σ > 0.1）实施 MLE-IC 拟合路径（§三.4-§三.5）

### 9.4 中期（可选）

- [ ] GDR 分箱报告（P21）中标记 EVT 适用性
- [ ] 第二层方案B：VaR/CVaR 单元格 Tooltip 显示 EVT 详细诊断

### 9.5 不实施

- [ ] DGPD 实现（理由见 §八）
- [ ] 连续性校正（理由见 §8.6）
- [ ] 独立 EVT 诊断面板（优先级低，暂不实施）

---

## 十一、与 P24 的关系

| 维度 | P24（已实现） | 本计划 |
|------|-------------|--------|
| 目标 | EVT 尾部拟合基础集成 | 修正 EVT 对退化/离散分布的错误适用 + UI 显示 + Bootstrap 路径统一 |
| 改动范围 | `core/evt_tail.py`（新建）+ `distribution.py` + `worst_impact.py` | `distribution.py`（+40 行 `_evt_applicable`）+ `bootstrap.py`（~30 行重构）+ `gui/about_dialog.py`（~3 行）+ `gui/analysis_panel.py`（~10 行） |
| 测试 | 30 项（test_evt_tail + test_distribution） | 已有 7 项退化检测测试 + 新增 `_evt_applicable` 测试 + Bootstrap GPD 统一路径测试 |
| 风险 | 低（回退机制完善） | 低（仅增加回退条件 + 统一已有路径，不改变已启用 EVT 的核心逻辑） |

---

## 十二、验收标准

### 退化检测
- [ ] `all_targets`（二元）分布上调用 `quantile(0.05, use_evt=True)` → 走经验分位数，不走 EVT
- [ ] `weapon_character_ratio`（退化）分布 → 不走 EVT
- [ ] `target_collection`（< 20 不同取值）分布 → 不走 EVT
- [ ] `resource_remaining`（> 20 不同取值）分布 → 正常走 EVT
- [ ] 不同取值数检查惰性计算 + 缓存，不重复遍历

### EVT 适用性判定
- [ ] `_evt_applicable(p)` 统一返回 (bool, reason)
- [ ] `evt_status` property 提供完整 EVT 状态快照
- [ ] `_evt_quantile()` 和 `_evt_cvar()` 通过 `_evt_applicable()` 而非分散检查

### UI 显示
- [ ] `about_dialog.py` 中 EVT 说明包含退化分布自动跳过信息
- [ ] GDR 统计表格中退化指标的 VaR 值附带标记

### Bootstrap 统一
- [ ] `_bootstrap_tail_gpd()` 委托 `evt_tail.fit_gpd_lower()` 而非自行拟合
- [ ] Bootstrap GPD 路径包含退化检测（与 `EmpiricalDistribution` 一致）
- [ ] 每个 resample 的 GPD 拟合失败时优雅回退（不影响整体 CI 计算）
- [ ] GPD-param Bootstrap 文档注明百分位法 CI 的已知覆盖率缺陷（Schendel & Thongwichian 2017）

### MLE-IC 与 TIB（文献审查发现——当前阶段为文档记录，非实施要求）
- [ ] 计划文档中记录了 MLE-IC + TIB 的理论分析（§三.4-§三.5）
- [ ] TIB 升级列为 Bootstrap 计划 B2.9 条目
- [ ] MLE-IC 实施被判定为低优先级（仅在 B 类边际 GDR 中有显著收益）

### 回归
- [ ] 全部已有测试保持绿色

---

## 更新记录

| 日期 | 变更 |
|------|------|
| 2026-05-28 | 初版：DGPD 评估 + 几何分布分析 + 17 种 GDR 分类 + 自动退化检测方案 |
| 2026-05-28 | v2：补充跳过/检测实现方法（§六）、EVT UI 显示计划（§七）、Bootstrap 依赖分析与计划修改（§八）、DGPD 代码可行性评估（§九）、更新实施清单与验收标准 |
| 2026-05-28 | v3：**重大修订**——重写 §一、§二、§三为文献支撑的严谨调研：Anderson (1970) 离散化破坏 MDA + Hitz, Davis & Samorodnitsky (2024) D-GPD vs GZD vs 连续 GPD + Deidda & Puliga (2009) 舍入偏差 Monte Carlo 研究 + Ma et al. (2024) MLE-IC 区间删失方法；三层方案对比（A: 连续GPD+回退 / B: D-GPD / C: MLE-IC）；δ/σ 分层的连续GPD可靠性评估；阈值 <20 的理论验证 |
| 2026-05-28 | v2：补充跳过/检测实现方法（§五）、EVT UI 显示计划（§六）、Bootstrap 依赖分析与计划修改（§七）、DGPD 代码可行性评估（§八）、更新实施清单与验收标准 |
