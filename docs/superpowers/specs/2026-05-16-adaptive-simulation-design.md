# 自适应模拟次数与方差缩减设计

## 1. 目标

1. 为各分析功能提供科学的模拟次数推荐，避免"凭感觉设次数"
2. 实现自适应停止机制：模拟过程中实时评估精度，达到目标后自动停止
3. 评估方差缩减技术（重要抽样、EVT 尾部拟合等）在本项目中的适用性

## 2. 理论基础

### 2.1 蒙特卡洛精度定律

中心极限定理给出蒙特卡洛估计的标准误：

```
SE = σ / √N
```

相对标准误（RSE）：

```
RSE = SE / |θ̂| = σ / (|θ̂| × √N)
```

要达到目标 RSE < ε，所需样本量：

```
N ≥ (σ / (ε × |θ̂|))²
```

### 2.2 不同估计量的精度特征

#### 概率估计（伯努利试验）

估计成功率 p 时：`SE = √(p(1-p)/N)`

相对标准误：`RSE = √((1-p)/(N×p))`

**关键特性**：当 p 接近 0 或 1 时，RSE 变差。估计 99% 成功率的相对精度与估计 1% 成功率相同。

| p | N=1,000 RSE | N=10,000 RSE | N=100,000 RSE |
|---|------------|-------------|--------------|
| 0.5 | 3.2% | 1.0% | 0.32% |
| 0.9 | 1.1% | 0.33% | 0.11% |
| 0.99 | 3.2% | 1.0% | 0.32% |

#### 连续量均值

`SE = σ/√N`，σ 取决于具体指标：

| 指标 | 典型 σ | N=1,000 SE | N=10,000 SE |
|------|--------|-----------|------------|
| 目标达成率 | ~0.3 | 0.95% | 0.30% |
| 资源剩余 | ~5000 | 158 | 50 |
| SSR 收集率 | ~0.05 | 0.16% | 0.05% |

#### 分位数估计

`SE(x_p) ≈ √(p(1-p)) / (f(x_p) × √N)`

尾部分位数的 f(x_p) 很小，需要更多样本：

| 分位数 | 典型 f | N=10,000 SE | N=100,000 SE |
|--------|--------|-----------|------------|
| 中位数 | ~0.02 | ~8 | ~2.5 |
| 5% VaR | ~0.001 | ~218 | ~69 |

**5% VaR 的标准误是中位数的 ~28 倍。**

#### 稀有事件频率

概率为 q 的事件，要观察到 ≥k 次：`N ≥ k/q`

| 事件概率 | ≥10 次观察 | ≥100 次观察 |
|---------|----------|----------|
| 10% | 100 | 1,000 |
| 1% | 1,000 | 10,000 |
| 0.1% | 10,000 | 100,000 |
| 0.01% | 100,000 | 1,000,000 |

## 3. 各分析类型的推荐模拟量

| 分析类型 | 估计目标 | 推荐 N | 精度依据 |
|---------|---------|--------|---------|
| 成功率判定 | 概率 p | 1,000-5,000 | RSE(p) < 5% |
| GDR 分布（均值/直方图） | 连续分布 | 5,000-10,000 | SE(均值) < 0.5% |
| VaR/CVaR（5% 尾部） | 尾部分位数 | 10,000-50,000 | SE(VaR) 可接受 |
| 脆弱性分析 | 条件概率函数 | 10,000-50,000 | 每个直方图 bin ≥30 样本 |
| 过程分析（常见模式 q>1%） | 模式概率 | 10,000-50,000 | 每种模式 ≥100 次观察 |
| 过程分析（罕见模式 q~0.1%） | 罕见模式概率 | 100,000-500,000 | 每种模式 ≥100 次观察 |
| 最差影响分析 | 条件分布 | 5,000-10,000 | 与 GDR 分布相同 |

## 4. 自适应停止机制

### 4.1 设计

在 gacha_panel 中提供两种模拟模式：

- **固定模式**（当前）：用户手动设置模拟次数
- **自适应模式**（新增）：用户设置目标精度，系统自动决定模拟次数

### 4.2 自适应控制器

利用流式架构的 `on_result` 回调，实时计算精度指标：

```python
class AdaptiveSimController:
    def __init__(self, target_rse=0.05, min_samples=1000,
                 max_samples=100000, check_interval=500,
                 gdr_keys=None, target_specs=None):
        self._target_rse = target_rse
        self._min_samples = min_samples
        self._max_samples = max_samples
        self._check_interval = check_interval
        self._gdr_keys = gdr_keys or ['target_achievement']
        self._target_specs = target_specs
        self._values = {k: [] for k in self._gdr_keys}
        self._converged = False
        self._n_done = 0
        self._worst_rse = float('inf')
        self._worst_key = None

    def on_result(self, compact):
        for key in self._gdr_keys:
            val = compute_gdr_from_compact(compact, self._target_specs, key)
            self._values[key].append(val)
        self._n_done += 1

        if self._n_done >= self._min_samples and \
           self._n_done % self._check_interval == 0:
            self._check_convergence()

    def _check_convergence(self):
        worst_rse = 0
        worst_key = None
        for key, values in self._values.items():
            if len(values) < 100:
                continue
            mean = sum(values) / len(values)
            if abs(mean) < 1e-10:
                continue
            var = sum((v - mean) ** 2 for v in values) / (len(values) - 1)
            se = var ** 0.5 / len(values) ** 0.5
            rse = se / abs(mean)
            if rse > worst_rse:
                worst_rse = rse
                worst_key = key
        self._worst_rse = worst_rse
        self._worst_key = worst_key
        if worst_rse < self._target_rse:
            self._converged = True

    def should_stop(self):
        return self._converged or self._n_done >= self._max_samples

    def get_status(self):
        return {
            'n_done': self._n_done,
            'converged': self._converged,
            'worst_rse': self._worst_rse,
            'worst_key': self._worst_key,
            'target_rse': self._target_rse,
        }
```

### 4.3 与 run_batch_parallel 的集成

新增 `stop_condition` 回调参数：

```python
def run_batch_parallel(
    ...,
    on_result: Optional[Callable[[Dict], None]] = None,
    stop_condition: Optional[Callable[[], bool]] = None,
) -> List[Optional[Dict[str, Any]]]:
```

在多线程模式下，每消费一批结果后检查 `stop_condition()`，若返回 True 则终止剩余任务。

### 4.4 UI 设计

```
模拟模式： ○ 固定次数  ○ 自适应精度
固定次数： [10000] ▲▼
目标精度： [5%] ▲▼    （自适应模式时显示）
最小次数： [1000] ▲▼  （自适应模式时显示）
最大次数： [100000] ▲▼（自适应模式时显示）
监控指标： [☑目标达成率 ☑资源剩余 ☑SSR收集率]（自适应模式时显示）

模拟进度： 5,000 / ≤100,000
当前精度： 目标达成率 RSE=3.2% ✓ | 资源剩余 RSE=4.8% ✓ | SSR收集率 RSE=1.1% ✓
最慢指标： 资源剩余 RSE=4.8% (目标 5%)
预计还需： ~0 次（已收敛）
```

## 5. 方差缩减技术评估

### 5.1 重要抽样法（Importance Sampling）

**原理**：改变抽样分布，使稀有事件更频繁发生，然后用似然比修正估计。

**在本项目中的适用性分析**：

抽卡模拟的随机性来源是每次抽卡的结果（SSR/SR/R），由池子的分布表决定。要应用重要抽样，需要修改抽卡概率分布（如提高 SSR 概率），然后对每次抽卡乘以似然比 `w = P_original(card) / P_biased(card)`。

**可行性**：✅ 技术上可行

- 修改 `Pool.draw()` 方法，接受一个偏置分布参数
- 在 `GachaService.run_simulation_compact` 中，每次抽卡记录似然比
- 最终估计：`θ̂_IS = (1/N) × Σ w_i × h(X_i)`

**适用场景**：

| 场景 | 是否适用 | 原因 |
|------|---------|------|
| 估计极低成功率（<1%） | ✅ 高度适用 | 可将 SSR 概率提高 10-100 倍，方差降低 10-1000 倍 |
| 估计 50% 成功率 | ❌ 不适用 | 事件不稀有，IS 反而可能增加方差 |
| VaR 5% 尾部 | ⚠️ 部分适用 | 需要精心设计偏置分布，否则权重退化 |
| 过程分析罕见模式 | ⚠️ 部分适用 | 需要针对特定模式设计偏置，复杂度高 |

**风险**：权重退化（weight degeneracy）——如果偏置分布选得不好，少数样本的似然比极大，估计方差反而增大。

**推荐**：**仅在估计极低成功率（<1%）时实现 IS**。大多数抽卡场景的成功率在 10%-90%，IS 收益不大。

### 5.2 对偶变量法（Antithetic Variables）

**原理**：使用负相关的配对样本，抵消方差。

**在本项目中的适用性**：

抽卡模拟的随机数是均匀分布 U(0,1)。对偶变量法使用 `u` 和 `1-u` 作为一对随机数。

**可行性**：✅ 实现简单

- 在 `run_batch_parallel` 中，将 N 次模拟配对为 N/2 对
- 每对中第二次模拟使用 `1 - seed` 的随机序列
- 估计量：`θ̂_AV = (1/N) × Σ (h(X_i) + h(X'_i)) / 2`

**适用场景**：

| 场景 | 是否适用 | 原因 |
|------|---------|------|
| GDR 均值估计 | ✅ 适用 | h 是单调函数时，对偶变量负相关 |
| 成功率估计 | ⚠️ 弱效果 | h 是 0/1 指示函数，负相关不保证 |
| 分位数估计 | ❌ 不适用 | 分位数不是平滑函数 |

**推荐**：**实现成本低（~50 行代码），收益中等（方差降低 20-50%），值得做。**

### 5.3 控制变量法（Control Variates）

**原理**：利用与目标变量相关且期望已知的辅助变量修正估计。

`θ̂_CV = θ̂_MC - c × (Ẑ - E[Z])`

其中 c 是最优系数，Z 是控制变量。

**在本项目中的适用性**：

抽卡模拟中，一个天然的控制变量是**理论期望抽卡数**。在无保底的情况下，抽到 SSR 的期望次数是 1/0.006 ≈ 167 次。实际抽卡数与理论值的偏差可以作为控制变量。

**可行性**：⚠️ 需要推导理论期望

- 对于有保底的系统，理论期望不容易解析计算
- 需要针对每种保底配置推导 E[Z]
- 实现复杂度中等

**推荐**：**暂不实现。理论推导成本高，且自适应停止机制已经能解决精度问题。**

### 5.4 分层抽样法（Stratified Sampling）

**原理**：将总体划分为若干子层，每层独立抽样，降低层内方差。

**在本项目中的适用性**：

抽卡模拟可以按"首次 SSR 出现的抽卡次数"分层（1-73 抽 vs 74-90 抽 vs 91+ 抽），但保底机制已经隐式地做了这种分层。

**推荐**：**不适用。** 抽卡模拟的分层变量不明显，且保底机制已经处理了分层效果。

### 5.5 EVT 尾部拟合（Peaks Over Threshold）

**原理**：用广义帕累托分布（GPD）拟合超过阈值的尾部数据，外推极值分位数。

**VaR/CVaR 估计改进**：

当前 VaR/CVaR 用经验分位数估计，在 5% 尾部需要大量样本。EVT 可以用少量尾部数据拟合 GPD，然后解析计算极值分位数：

```
VaR_p = u + (β/ξ) × [(n/Nu × (1-p))^(-ξ) - 1]
```

其中 u 是阈值，ξ 和 β 是 GPD 参数，Nu 是超过阈值的样本数，n 是总样本数。

**可行性**：✅ 可行

- 从模拟结果中提取尾部数据（如最低 10% 的资源剩余值）
- 用 MLE 拟合 GPD 参数
- 解析计算 VaR/CVaR

**适用场景**：

| 场景 | 是否适用 | 效果 |
|------|---------|------|
| VaR 1%/5% 估计 | ✅ 高度适用 | 用 5000 样本达到 50000 样本的尾部精度 |
| CVaR 估计 | ✅ 高度适用 | 解析公式直接计算 |
| 脆弱性分析尾部分布 | ✅ 适用 | 改善尾部的核密度估计 |
| 过程分析 | ❌ 不适用 | 过程分析估计的是离散概率，不是连续分布尾部 |

**推荐**：**实现。** 对 VaR/CVaR 估计有显著改善，且实现复杂度中等。

### 5.6 方差缩减技术总结

| 技术 | 实现复杂度 | 适用场景 | 收益 | 推荐 |
|------|----------|---------|------|------|
| 重要抽样（IS） | 高 | 极低成功率 <1% | 极高（10-1000x） | 暂不实现，未来按需 |
| 对偶变量法 | 低 | GDR 均值估计 | 中（1.2-2x） | ✅ 实现 |
| 控制变量法 | 中 | 需要理论期望 | 中 | 暂不实现 |
| 分层抽样法 | 中 | 不适用 | — | 不实现 |
| EVT 尾部拟合 | 中 | VaR/CVaR | 高（10x 尾部精度） | ✅ 实现 |

## 6. 实施计划

### Task 1：自适应停止机制

**内容**：
1. 新建 `core/adaptive.py`：`AdaptiveSimController` 类
2. 修改 `gui/batch_simulator.py`：新增 `stop_condition` 参数
3. 修改 `gui/gacha_panel.py`：新增"自适应精度"模式 UI
4. 与 `SharedResultCollector` 集成

**验证**：
- 自适应模式在典型配置下自动收敛到目标 RSE
- 固定模式行为不变

### Task 2：对偶变量法

**内容**：
1. 修改 `gui/batch_simulator.py`：新增 `antithetic=True` 选项
2. 配对模拟：第 2k 次模拟使用 `1 - seed_2k` 的随机序列
3. 估计量取配对均值

**验证**：
- 对偶变量模式的 GDR 均值估计方差低于普通模式
- 估计值无偏

### Task 3：EVT 尾部拟合

**内容**：
1. 新建 `core/evt_tail.py`：GPD 拟合 + VaR/CVaR 解析计算
2. 修改 `gui/analysis_panel.py`：VaR/CVaR 计算使用 EVT 拟合
3. 阈值选择：使用平均超额图（Mean Excess Plot）自动选择

**验证**：
- EVT 拟合的 VaR 5% 与 50000 样本的经验分位数一致
- 5000 样本 + EVT 的精度接近 50000 样本的经验分位数

### 执行顺序

```
Task 1 (自适应停止) — 独立
Task 2 (对偶变量) — 独立
Task 3 (EVT尾部) — 独立
```

三个 Task 完全独立，可以并行实现。Task 1 优先级最高（通用收益），Task 3 次之（VaR 精度改善），Task 2 最低（收益中等但实现简单）。

### 与 Bootstrap（P3）的兼容性

| Task | 与 Bootstrap 的关系 | 设计要求 |
|------|-------------------|---------|
| Task 1（自适应停止） | 互补：自适应停止保证"模拟量足够"，Bootstrap 回答"结果有多稳" | 无特殊要求（当前基于 RSE，无可选停止偏差） |
| Task 2（对偶变量） | 兼容，需配对 Bootstrap | `BootstrapEngine` 支持 `paired=True`，重抽样 N/2 对而非 N 个个体；gacha_panel 添加"对偶变量法"开关 |
| Task 3（EVT 尾部） | 互补：尾部分位数需参数 Bootstrap | EVT 拟合应接受任意数据（含重抽样数据），返回 GPD 参数 + VaR/CVaR；Bootstrap 从 GPD 中抽样而非从经验分布重抽样 |

**建议执行顺序**：P3（Bootstrap）先于 P4 实现，EVT 在 Bootstrap 框架上扩展 Bootstrap-EVT 混合方法。
