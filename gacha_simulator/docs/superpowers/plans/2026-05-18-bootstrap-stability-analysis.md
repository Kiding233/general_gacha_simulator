
# Bootstrap 稳定性分析实现计划

## 一、概述

为所有统计估计添加 Bootstrap 置信区间计算，并在图表上可视化展示。

**核心原理**：Bootstrap 不是重新跑模拟，而是对已有的 N 条模拟结果做有放回抽样（纯数组操作），从 B 次重抽样中估计统计量的分布，从而得到置信区间。**零额外模拟成本，零额外内存**。

---

## 二、完整的可 Bootstrap 清单

### 2.1 可直接 Bootstrap 的面板（数据已存储）

| 面板 | 可 Bootstrap 的统计量 | 数据来源 | 优先级 |
|------|---------------------|---------|--------|
| **analysis_panel** | GDR 分布各分位数、各池成功率、资源消耗/收益分布 | `aggregate_data` | 🔴 高 |
| **process_analysis_panel** | AA 每个事件模式概率、BB 每个成败模式概率及各池成功率、AB 每个条件概率、BA 每个条件概率和比值 | `process_data` | 🔴 高 |
| **retreat_panel** | 条件资源分布分位数、核密度回归曲线、资源不足概率 | `aggregate_data` | 🟡 中 |
| **worst_impact_panel** | 条件资源分布的 α 分位数（保守资源） | `aggregate_data` | 🟡 中 |

### 2.2 需小改即可 Bootstrap 的面板（每步已跑 N 次模拟，但只保存了聚合结果）

这些面板每一步都会跑 N 次模拟，但当前只保存了聚合结果，没有保存每次模拟的个体结果。**只需额外保存个体结果，即可 Bootstrap。不存在"需要重新模拟"的情况。**

| 面板 | 当前保存 | 需额外保存 | 改动量 |
|------|---------|-----------|--------|
| **strategy_panel** | 每步一个 `success_probability: float` | 每步一个 `success_flags: List[bool]` | 小：修改 `ForwardStep`/`BackwardStep` 数据类 |
| **resource_search_panel** | 每步一个 `success_probability: float` | 每步一个 `success_flags: List[bool]` | 小：修改 `ResourceSearchStep` 数据类 |
| **worst_impact_panel（新池子分布）** | 聚合 `pool_distribution: Dict[int,float]` | `pool_success_counts: List[int]`（每次模拟的通关数） | 小：修改 `_compute_pool_distribution` |
| **retreat_search_panel** | 聚合结果 | 每步个体结果 | 中：取决于内部引擎结构 |

### 2.3 不做 Bootstrap 的面板

| 面板 | 原因 |
|------|------|
| **gacha_panel** | 是模拟面板不是分析面板，负责跑模拟和展示原始结果 |

### 2.4 worst_impact_panel 的详细分析

| 步骤 | 内容 | 数据来源 | 可 Bootstrap？ |
|------|------|---------|--------------|
| 条件资源分布 | 从 N 条 `aggregate_data` 中筛选成功/失败，计算资源分布的 α 分位数 | `aggregate_data` | ✅ 直接可以 |
| 新池子数分布 | 用保守资源跑 M 次模拟，每次得到通关数 | M 次模拟的个体结果 | ✅ 小改即可（保存 `pool_success_counts: List[int]`） |

### 2.5 各面板详细的可 Bootstrap 统计量

#### analysis_panel

| 统计量 | 数据字段 | Bootstrap 方法 |
|--------|---------|---------------|
| GDR 分布各分位数（5%/25%/50%/75%/95%） | `gdr_value` | `bootstrap_distribution` |
| 各池成功率 | `success` 按池分组 | `bootstrap_probability` |
| 资源消耗分布 | `total_consumed` | `bootstrap_distribution` |
| 资源收益分布 | `total_gained` | `bootstrap_distribution` |
| 卡获得分布 | `card_counts` | `bootstrap_distribution_dict` |
| 抽卡数分布 | `total_draws` | `bootstrap_distribution` |

#### process_analysis_panel

| 统计量 | 数据字段 | Bootstrap 方法 |
|--------|---------|---------------|
| AA：每个事件模式的概率 | `pool_events` | `bootstrap_aa` |
| BB：每个成败模式的概率 | `success` + `pool_events` | `bootstrap_bb` |
| BB：各池独立成功率 | `pool_success` | `bootstrap_probability` |
| BB：永不失败/永不成功概率 | `pool_success` | `bootstrap_probability` |
| AB：每个事件模式下的成功概率 | `pool_events` + `success` | `bootstrap_ab` |
| AB：整体成功概率 | `success` | `bootstrap_probability` |
| BA：成功/失败下的事件模式概率 | `pool_events` + `success` | `bootstrap_ba` |
| BA：概率比值 | 上述条件概率 | 从 Bootstrap 样本计算 |

#### retreat_panel

| 统计量 | 数据字段 | Bootstrap 方法 |
|--------|---------|---------------|
| 条件资源分布分位数 | `final_resources` + `success` | `bootstrap_distribution`（条件筛选后） |
| 核密度回归曲线 | `final_resources` + `success` | `bootstrap_retreat` |
| 资源不足概率 | `final_resources` + `success` | `bootstrap_probability` |

#### worst_impact_panel

| 统计量 | 数据字段 | Bootstrap 方法 |
|--------|---------|---------------|
| 保守资源（α 分位数） | `final_resources` + `success` | `bootstrap_distribution`（条件筛选后） |
| 大保底覆盖倍数 | 保守资源 / 保底成本 | 从保守资源 CI 派生 |

#### strategy_panel（需小改）

| 统计量 | 需保存的数据 | Bootstrap 方法 |
|--------|------------|---------------|
| 每步成功率 | 每步 `success_flags: List[bool]` | `bootstrap_probability` |

#### resource_search_panel（需小改）

| 统计量 | 需保存的数据 | Bootstrap 方法 |
|--------|------------|---------------|
| 每步成功率 | 每步 `success_flags: List[bool]` | `bootstrap_probability` |

---

## 三、核心设计决策

1. **零额外模拟**：Bootstrap 是纯数组重抽样操作，不涉及任何新模拟
2. **零额外内存**（直接可 Bootstrap 的面板）：完全基于已存储的 `aggregate_data` 和 `process_data`
3. **极小额外内存**（strategy/resource 面板）：每步额外保存 N 个 bool（N=1000 时仅 1KB/步）
4. **BootstrapEngine**：统一处理所有 Bootstrap 计算
5. **可视化统一**：趋势图用阴影带，柱状图用误差棒，表格用 `0.95 [0.92, 0.98]` 格式
6. **默认配置**：B=1000 次重抽样，95% 置信区间
7. **默认使用 BCa 方法**：校正偏差和偏态，二阶精度 O(1/n)
8. **新增总变差（TVD）计算**：衡量两个概率分布的整体距离

---

## 三-B、Bootstrap 偏差问题与 BCa 校正

### 问题

简单的百分位法（取 Bootstrap 分布的 2.5% 和 97.5% 分位数）存在偏差：

| 偏差来源 | 说明 |
|---------|------|
| 估计量本身有偏 | Bootstrap 分布围绕样本统计量，而非真实参数 |
| 分布偏态 | 统计量抽样分布不对称时（如概率接近 0 或 1），百分位法 CI 不准确 |
| 边界效应 | 概率估计在 0 和 1 附近有自然边界，CI 不对称 |

### 校正方法对比

| 方法 | 精度 | 说明 |
|------|------|------|
| 百分位法 | 一阶 O(1/√n) | 最简单，不校正偏差 |
| BC 法（偏差校正） | 二阶 O(1/n) | 校正中位数偏差 z₀，不校正偏态 |
| **BCa 法**（加速偏差校正） | **二阶 O(1/n)** | **推荐**。同时校正偏差 z₀ 和偏态 a |

### BCa 方法

需要估计两个参数：

1. **z₀（偏差校正系数）**：`z₀ = Φ⁻¹(#(θ̂*_b < θ̂) / B)`，即 Bootstrap 估计中小于原始估计的比例对应的标准正态分位数
2. **a（加速系数）**：通过 Jackknife 估计。对每个数据点 i，计算去掉第 i 个数据后的统计量 θ̂_(-i)，然后：
   ```
   a = Σ(θ̂̄_(-i) - θ̂_(-i))³ / (6 · (Σ(θ̂̄_(-i) - θ̂_(-i))²)^(3/2))
   ```

校正后的分位数：
```
α₁ = Φ(z₀ + (z₀ + z^(α/2)) / (1 - a·(z₀ + z^(α/2))))
α₂ = Φ(z₀ + (z₀ + z^(1-α/2)) / (1 - a·(z₀ + z^(1-α/2))))
CI = [θ̂*_(α₁), θ̂*_(α₂)]
```

### 对本项目的影响

| 统计量 | 偏差风险 | 原因 |
|--------|---------|------|
| 成功率（接近 0 或 1） | 高 | 边界效应 |
| 条件概率（AB/BA，小样本组） | 高 | 小样本偏态 |
| 分位数（极端 α） | 中 | 分位数天然有偏 |
| 比值（BA ratio） | 高 | Jensen 不等式 |

**结论：默认使用 BCa 方法，同时提供百分位法作为对比选项。**

---

## 三-D、厚尾分布下 Bootstrap 的理论问题

### 文献证据

**Athreya (1987)**：当总体方差无限（E[X²] = ∞）时，即分布属于稳定律吸引域（1 < α < 2），朴素 Bootstrap 均值的极限分布是**随机的**，不收敛到真实抽样分布。Bootstrap 失败。

> "The bootstrap is not successful here. The limiting distributions of the sample mean and its bootstrap version are quite different, the latter one being a random probability distribution."
> — Athreya, K.B. (1987). Bootstrap of the Mean in the Infinite Variance Case. *Annals of Statistics*, 15(2), 724-731.

**Hall (1990)**：进一步证明 Bootstrap 均值分布收敛的充要条件是——要么总体在正态吸引域内（有限方差），要么尾部极重（慢变尾部）。中间情况（如稳定律吸引域）Bootstrap 不一致。

> "The bootstrap distribution function of the mean, suitably normalized, converges in probability to some fixed nondegenerate distribution function if and only if either (a) the sampling distribution is from the domain of attraction of the normal law or (b) the sampling distribution has slowly varying tails."
> — Hall, P. (1990). Asymptotic Properties of the Bootstrap for Heavy-Tailed Distributions. *Annals of Probability*, 18(3), 1342-1360.

### 对本项目的实际影响

| 统计量 | 分布特征 | Bootstrap 可靠性 | 推荐方法 |
|--------|---------|-----------------|---------|
| 成功率（伯努利） | 有限方差 p(1-p) | ✅ 完全可靠 | 标准 Bootstrap + BCa |
| 事件模式概率 | 有限方差 | ✅ 完全可靠 | 标准 Bootstrap + BCa |
| 条件概率（AB/BA） | 有限方差 | ✅ 完全可靠 | 标准 Bootstrap + BCa |
| GDR 均值/中位数 | 通常有限方差 | ✅ 可靠 | 标准 Bootstrap + BCa |
| 资源消耗/剩余均值 | **可能厚尾** | ⚠️ 需检查方差 | 若有限方差 → 标准 Bootstrap；若厚尾 → m-out-of-n |
| VaR/CVaR（尾部分位数） | 尾部数据稀疏 | ❌ 标准 Bootstrap 不可靠 | **参数 Bootstrap（从 GPD 抽样）** |

### 解决方案

#### 方案A：m-out-of-n Bootstrap（通用补救）

当标准 n-out-of-n Bootstrap 失败时，从 n 条数据中抽取 m 条（m < n, m → ∞, m/n → 0）。

> Politis & Romano (1994) 证明 m-out-of-n Bootstrap 在比标准 Bootstrap 更弱的条件下一致。
> — Politis, D.N. & Romano, J.P. (1994). Large Sample Confidence Regions Based on Subsamples. *Annals of Statistics*, 22(4), 2031-2050.

**缺点**：CI 偏宽，m 的选择困难。

#### 方案B：参数 Bootstrap（从拟合的 GPD 中抽样）——推荐用于尾部

先对尾部数据拟合 GPD，再从拟合的 GPD 中生成 Bootstrap 样本。

> Cornea-Madeira & Davidson (2015) 证明参数 Bootstrap 在厚尾情况下优于 m-out-of-n Bootstrap 和子抽样。
> — Cornea-Madeira, A. & Davidson, R. (2015). A Parametric Bootstrap for Heavy-Tailed Distributions. *Econometric Theory*, 31(3), 449-470.

> He, Peng, Zhang & Zhao (2021) 证明对 GPD 拟合的 VaR 估计，朴素 Bootstrap 和随机加权 Bootstrap 都是渐近正确的。
> — He, Y. et al. (2021). Risk Analysis via Generalized Pareto Distributions. *J. Business & Economic Statistics*, 40(2), 852-867.

**流程**：
```
1. 从 N 条数据中提取尾部数据（超过阈值 u 的部分）
2. 拟合 GPD → 参数 (ξ̂, β̂)
3. for b = 1..B:
     从 GPD(ξ̂, β̂) 中生成尾部 Bootstrap 样本
     从非尾部经验分布中生成非尾部 Bootstrap 样本
     合并 → 计算统计量 → θ̂*_b
4. 从 B 组估计中取分位数 → CI
```

#### 方案C：混合策略（本项目推荐）

| 统计量类型 | 方法 | 原因 |
|-----------|------|------|
| 离散概率（成功率、AA/BB/AB/BA） | 标准 Bootstrap + BCa | 伯努利试验，方差有限，Bootstrap 天然适用 |
| 连续量非尾部（均值、中位数、25-75%分位数） | 标准 Bootstrap + BCa | 通常有限方差 |
| 连续量尾部（5% VaR、1% VaR、CVaR） | **参数 Bootstrap（GPD）** | 尾部稀疏，标准 Bootstrap 不可靠 |
| 资源消耗均值（若检测到厚尾） | m-out-of-n Bootstrap | 厚尾补救 |

### 设计要求

1. `BootstrapEngine` 应支持 `method='standard'`（默认）、`method='parametric_gpd'`（参数 Bootstrap）、`method='m_out_of_n'`（m-out-of-n）
2. 对连续量统计量，自动检测厚尾（如 Hill 估计量估计尾部指数 α，若 α < 2 则警告）
3. 对尾部分位数（如 5% VaR），默认使用参数 Bootstrap（GPD）
4. 对偶变量法开关：gacha_panel 添加"对偶变量法"复选框，`BootstrapEngine` 支持 `paired=True`

---

## 三-C、总变差（Total Variation Distance）——衡量分布估计的变异

### 定义

对于离散概率分布 P 和 Q：

```
TVD(P, Q) = (1/2) Σ_x |P(x) - Q(x)|
```

取值范围 [0, 1]：0 表示两个分布完全相同，1 表示完全不同。

### 用途：衡量分布估计的稳定性

Bootstrap B 次后得到 B 个分布估计 P̂*₁, ..., P̂*B，用 TVD 衡量这些分布与点估计 P̂ 之间的变异：

```
TVD(P̂, P̂*₁), ..., TVD(P̂, P̂*B) → TVD 的分布
↓
TVD 的均值 = 分布估计的平均变异程度
TVD 的 95% 分位数 = 分布估计的最大变异程度
```

**一个数字告诉你整个分布估计有多稳**，比逐个概率做 CI 更紧凑。

### 在本项目中的应用

| 分析 | TVD 衡量什么 |
|------|------------|
| AA | 事件分布估计的稳定性（TVD between P̂_AA 和 Bootstrap P̂*_AA） |
| BB | 成败分布估计的稳定性 |
| AB | 条件概率分布估计的稳定性 |
| BA | 成功/失败下事件分布估计的稳定性 |
| worst_impact 新池子分布 | P(k pools) 分布估计的稳定性 |

### 额外用途：两个分布之间的 TVD

TVD 也可以衡量两个不同分布之间的距离，例如 BA 分析中"成功时的事件分布"和"失败时的事件分布"的整体差异。

---

## 四、详细实现步骤

### 阶段1：创建 BootstrapEngine 核心类

**新文件**：`/workspace/gacha_simulator/core/bootstrap.py`

**任务**：
- 定义 `BootstrapResult` 数据类：
  ```python
  @dataclass
  class BootstrapResult:
      point_estimate: float        # 点估计
      ci_lower: float              # 95% CI 下界
      ci_upper: float              # 95% CI 上界
      bootstrap_std: float         # 标准误
  ```
- 定义 `BootstrapEngine` 类，包含：
  - `bootstrap_probability(data: List[bool])`：二分类概率 Bootstrap
  - `bootstrap_distribution(data: List[float], quantiles)`：数值分布分位数 Bootstrap
  - `bootstrap_aa(process_data, event_mode, constraints)`：AA 分析 Bootstrap
  - `bootstrap_bb(process_data, success_mode, ...)`：BB 分析 Bootstrap
  - `bootstrap_ab(process_data, event_mode, success_mode, ...)`：AB 分析 Bootstrap
  - `bootstrap_ba(process_data, event_mode, ...)`：BA 分析 Bootstrap
  - `bootstrap_conditional_quantile(aggregate_data, condition, alpha, ...)`：条件分位数 Bootstrap（用于 retreat 和 worst_impact）
  - `bootstrap_conditional_gdr(process_data, aggregate_data, event_pattern, gdr_key, ...)`：以事件为条件的 GDR 分布 Bootstrap

### 阶段2：process_analysis_panel 添加 Bootstrap（优先）

**文件**：[`/workspace/gacha_simulator/gui/process_analysis_panel.py`](file:///workspace/gacha_simulator/gui/process_analysis_panel.py)

**任务**：
- 在 AA/BB/AB/BA 四个 Tab 上各添加 `📊 计算稳定性` 按钮
- 调用 `BootstrapEngine.bootstrap_aa/bb/ab/ba()` 计算 CI
- 修改表格显示：每个概率单元格显示为 `0.95 [0.92, 0.98]`

### 阶段2-B：process_analysis_panel 添加条件 GDR 分布

**文件**：[`/workspace/gacha_simulator/gui/process_analysis_panel.py`](file:///workspace/gacha_simulator/gui/process_analysis_panel.py)

**任务**：
- 在 AB Tab 中添加可折叠的"条件分布视图"
- 点击 AB 表格某行 → 展示该事件模式下的 GDR 分布
- GDR 指标通过下拉框选择（复用 GDR 下拉框），支持所有 13 种指标
- UI 设计详见第九节

### 阶段3：analysis_panel 添加 Bootstrap

**文件**：[`/workspace/gacha_simulator/gui/analysis_panel.py`](file:///workspace/gacha_simulator/gui/analysis_panel.py)

**任务**：
- 添加按钮：`📊 计算稳定性`
- 调用 `BootstrapEngine.bootstrap_distribution()` 计算 GDR 分布 CI
- 调用 `BootstrapEngine.bootstrap_probability()` 计算各池成功率 CI
- 修改图表，添加误差棒

### 阶段4：strategy_panel 添加 Bootstrap

**文件**：[`/workspace/gacha_simulator/gui/strategy_panel.py`](file:///workspace/gacha_simulator/gui/strategy_panel.py)

**任务**：
- 修改 `ForwardStep`/`BackwardStep` 数据类，添加 `success_flags: List[bool]` 字段
- 修改 `_forward_method`/`_backward_method`，在每步保存个体成功/失败结果
- 添加 `📊 计算稳定性` 按钮
- 调用 `BootstrapEngine.bootstrap_probability()` 计算每步成功率 CI
- 修改 `_draw_strategy_chart()` 绘制阴影带

### 阶段5：resource_search_panel 添加 Bootstrap

**文件**：[`/workspace/gacha_simulator/gui/resource_search_panel.py`](file:///workspace/gacha_simulator/gui/resource_search_panel.py)

**任务**：
- 修改 `ResourceSearchStep` 数据类，添加 `success_flags: List[bool]` 字段
- 修改 `_simulate_with_resource`，返回个体成功/失败结果
- 添加 `📊 计算稳定性` 按钮
- 调用 `BootstrapEngine.bootstrap_probability()` 计算每步成功率 CI
- 修改 `_draw_resource_chart()` 绘制阴影带

### 阶段6：retreat_panel 添加 Bootstrap

**文件**：[`/workspace/gacha_simulator/gui/retreat_panel.py`](file:///workspace/gacha_simulator/gui/retreat_panel.py)

**任务**：
- 添加按钮：`📊 计算稳定性`
- 调用 `BootstrapEngine.bootstrap_conditional_quantile()`
- 修改核密度回归曲线，添加阴影带
- 修改资源不足概率，显示 CI

### 阶段7：worst_impact_panel 添加 Bootstrap

**文件**：[`/workspace/gacha_simulator/gui/worst_impact_panel.py`](file:///workspace/gacha_simulator/gui/worst_impact_panel.py)

**任务**：
- 添加按钮：`📊 计算稳定性`
- 调用 `BootstrapEngine.bootstrap_conditional_quantile()`
- 修改保守资源显示，附带 CI
- 大保底覆盖倍数的 CI 从保守资源 CI 派生

---

## 五、数据结构定义

### BootstrapResult

```python
@dataclass
class BootstrapResult:
    point_estimate: float        # 点估计（原始数据的结果）
    ci_lower: float              # 95% CI 下界 (2.5% 分位数)
    ci_upper: float              # 95% CI 上界 (97.5% 分位数)
    bootstrap_std: float         # Bootstrap 标准误
```

### BootstrapEngine 签名

```python
class BootstrapEngine:
    def __init__(self, B: int = 1000, ci_level: float = 0.95, random_seed: int = 42, method: str = 'bca', paired: bool = False):
        """
        method: 'bca'（默认，加速偏差校正）或 'percentile'（简单百分位法）
        paired: True 时使用配对 Bootstrap（对偶变量法场景，重抽样 N/2 对而非 N 个个体）
        """

    @staticmethod
    def _resample_indices(n: int, B: int, rng, m: Optional[int] = None) -> np.ndarray:
        """生成 B×m 的有放回抽样索引矩阵。m=None 时 m=n（标准 Bootstrap），m<n 时 m-out-of-n"""
        ...

    @staticmethod
    def _compute_bca_correction(bootstrap_samples, point_estimate, jackknife_samples, ci_level) -> Tuple[float, float]:
        """计算 BCa 校正后的 CI 下界和上界"""
        ...

    @staticmethod
    def detect_heavy_tail(data: List[float]) -> Tuple[bool, float]:
        """用 Hill 估计量检测厚尾。返回 (is_heavy_tail, alpha_estimate)"""
        ...

    def bootstrap_probability(self, data: List[bool]) -> BootstrapResult:
        """二分类概率 Bootstrap（标准方法，伯努利方差有限）"""
        ...

    def bootstrap_distribution(self, data: List[float], quantiles: List[float] = [0.05, 0.25, 0.5, 0.75, 0.95], resample_method: str = 'auto') -> Dict[float, BootstrapResult]:
        """
        数值分布分位数 Bootstrap
        resample_method: 'auto'（自动检测厚尾）、'standard'、'm_out_of_n'、'parametric_gpd'
        """
        ...

    def bootstrap_aa(self, process_data, event_mode, constraints) -> Dict[str, BootstrapResult]: ...
    def bootstrap_bb(self, process_data, success_mode, ...) -> Dict[str, BootstrapResult]: ...
    def bootstrap_ab(self, process_data, event_mode, success_mode, ...) -> Dict[str, BootstrapResult]: ...
    def bootstrap_ba(self, process_data, event_mode, ...) -> Dict[str, BootstrapResult]: ...
    def bootstrap_conditional_quantile(self, aggregate_data, condition, alpha, ...) -> BootstrapResult: ...

    @staticmethod
    def total_variation_distance(p: Dict[str, float], q: Dict[str, float]) -> float: ...
    def bootstrap_tvd(self, process_data, event_mode, ...) -> BootstrapResult: ...

---

## 六、验收标准

- [ ] **BootstrapEngine 核心类**：实现所有主要方法
- [ ] **process_analysis_panel**：AA/BB/AB/BA 所有表格可以显示 CI
- [ ] **analysis_panel**：GDR 分布、各池成功率可以显示 CI
- [ ] **strategy_panel**：成功率趋势图可以显示阴影带
- [ ] **resource_search_panel**：成功率-资源曲线可以显示阴影带
- [ ] **retreat_panel**：条件分布、核密度回归、资源不足概率可以显示 CI
- [ ] **worst_impact_panel**：保守资源（条件分位数）可以显示 CI
- [ ] **process_analysis_panel 条件 GDR 分布**：AB Tab 中可以查看每个事件模式下任意 GDR 指标的分布
- [ ] **性能**：N=1万、B=1000 时，单次 Bootstrap 计算 < 5 秒

---

## 七、不做 Bootstrap

| 面板 | 原因 |
|----------|------|
| gacha_panel | 是模拟面板不是分析面板 |

---

## 八、与其他计划的依赖和兼容性

### 8.1 与 P2（过程分析续）的关系

P2 新增兑换池/资源池事件类型会改变 `process_data` 的 `pool_events` 格式。

**影响**：P3 的 `bootstrap_aa/bb/ab/ba` 需要适配新事件类型。

**建议**：P2 先行，P3 在 P2 完成后实现，避免重复适配。

### 8.2 与 P4 Task 3（EVT 尾部拟合）的关系——最关键的兼容性

**核心问题**：Bootstrap 对极端分位数（如 1%/5% VaR）不可靠。

| 统计量 | 推荐方法 | 原因 |
|--------|---------|------|
| 概率（成功率等） | Bootstrap | 离散统计量，Bootstrap 天然适用 |
| 中位数/均值 | Bootstrap | 非尾部，Bootstrap 可靠 |
| 5% VaR | **Bootstrap-EVT 混合** | 纯 Bootstrap 对极端分位数不稳定 |
| 1% VaR | **Bootstrap-EVT 混合** | 同上 |
| CVaR | **Bootstrap-EVT 混合** | 同上 |

**Bootstrap-EVT 混合方法**：

```
对 N 条数据做 Bootstrap:
  for b = 1..B:
    重抽样 N 条 → data_b
    ↓
    对 data_b 拟合 GPD（EVT）→ 参数 (ξ_b, β_b)
    ↓
    从 GPD 解析计算 VaR_p(data_b) 和 CVaR_p(data_b)
    ↓
    记录 VaR_p^(b), CVaR_p^(b)
  ↓
  从 B 组 VaR/CVaR 估计中取分位数 → CI
```

**设计要求**：
1. P3 的 `bootstrap_distribution` 应支持 `method='empirical'`（默认）和 `method='evt'`（委托 EVT）
2. P4 的 EVT 拟合应设计为接受任意数据（包括重抽样数据），返回 GPD 参数 + VaR/CVaR
3. P4 实现后，P3 的尾部分位数 Bootstrap 自动升级为 Bootstrap-EVT 混合方法

### 8.3 与 P4 Task 1（自适应停止）的关系

**互补关系**：

| | 自适应停止 | Bootstrap |
|---|---------|-----------|
| 时机 | 模拟过程中（实时） | 模拟完成后（事后） |
| 目的 | 决定何时停止模拟 | 量化结果的不确定性 |
| 输出 | "RSE < 5%，可以停止" | "成功率 = 0.95 [0.93, 0.97]" |

**无硬依赖**：两者独立工作，但概念相关。自适应停止保证"模拟量足够"，Bootstrap 回答"结果有多稳"。

### 8.4 与 P4 Task 2（对偶变量）的关系

**兼容，但需配对 Bootstrap。**

对偶变量法将 N 次模拟配对为 N/2 对，每对中两个结果负相关。朴素 Bootstrap（独立重抽样 N 个个体）会打破配对结构，导致 CI 偏保守（偏宽）。

| 方法 | 做法 | 结果 |
|------|------|------|
| 朴素 Bootstrap | 独立重抽样 N 个个体 | 打破配对，CI 偏宽（保守） |
| **配对 Bootstrap** | 重抽样 N/2 对（每对两个一起抽） | 保持配对，CI 更精确 |

**设计要求**：P3 的 `BootstrapEngine` 应支持 `paired: bool = False` 参数。当 `paired=True` 时，将数据视为 N/2 对，重抽样时成对抽取。

### 8.5 与 P5（策略比较）的关系

**无硬依赖**：P5 独立可实现。但 P3 完成后，策略比较的结果也可以附带 CI，增强对比的说服力。

### 8.6 建议执行顺序

```
P2 (过程分析续) → P3 (Bootstrap) → P4 (自适应+EVT) → P5 (策略比较)
```

- P2 先行：新增事件类型影响 process_data 格式
- P3 在 P4 之前：Bootstrap 先实现通用框架，EVT 作为尾部优化集成
- P4 Task 3 (EVT)：在 Bootstrap 框架上扩展 Bootstrap-EVT 混合方法
- P5 独立：可随时执行，P3 完成后获得 CI 加持

---

## 九、条件 GDR 分布的 Bootstrap 支持

条件 GDR 分布是过程分析面板的功能（详见过程分析计划 Task 9），Bootstrap 为其提供 CI 支持。

### BootstrapEngine 方法

```python
def bootstrap_conditional_gdr(
    self,
    process_data: List[Dict],
    aggregate_data: List[Dict],
    event_pattern: str,
    gdr_key: str = 'resource_remaining',
    target_specs: Optional[Dict] = None,
    desire_weights: Optional[Dict] = None,
    miss_cost_weights: Optional[Dict] = None,
    card_value_weights: Optional[Dict] = None,
    ssr_ids: Optional[Set[str]] = None,
    weapon_character_map: Optional[Dict] = None,
    success_filter: str = 'all',
    quantiles: List[float] = [0.05, 0.25, 0.5, 0.75, 0.95],
) -> Dict[str, BootstrapResult]:
    """
    以事件模式为条件的 GDR 分布 Bootstrap
    event_pattern: 事件模式键（来自 AA 分析结果）
    gdr_key: GDR 指标键名
    success_filter: 是否按成功/失败筛选
    """
    ...
```
