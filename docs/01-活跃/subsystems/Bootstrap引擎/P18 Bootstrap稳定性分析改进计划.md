<!-- META: P18 | module:subsystems/Bootstrap引擎 | status:in_progress | last:2026-06-11 -->
# P18 Bootstrap 稳定性分析改进计划

> 创建日期：2026-05-26
> 来源：合并以下两个文件（均已废弃，见末尾说明）——
> - `docs/superpowers/plans/2026-05-18-bootstrap-stability-analysis.md`（原始 Bootstrap 引擎 + UI 计划，v3）
> - `docs/拉普拉斯平滑与Bootstrap改进计划.md` §二（引擎已知问题修复）+ §三（UI MVP 方案）
> 关联：P3（Bootstrap 引擎）、P4（自适应模拟 + EVT）
> 状态：**阶段一核心完成，引擎修复 + UI 待做**

---

## 一、核心原理

Bootstrap 不是重新跑模拟，而是对已有的 N 条模拟结果做有放回抽样（纯数组操作），从 B 次重抽样中估计统计量的分布，从而得到置信区间。**零额外模拟成本，零额外内存。**

---

## 二、测试策略

| 阶段 | 测试方式 | 测试文件 |
|------|---------|---------|
| 阶段1 BootstrapEngine | **TDD**——每个方法先写失败测试 | `tests/core/test_bootstrap.py`（已新建） |
| 阶段2 引擎修复 | 更新现有测试 + 新增边界测试 | `tests/core/test_bootstrap.py` |
| 阶段3 UI 集成 | 手动目视 + 现有测试套件保持绿色 | 各面板的现有测试 |

**TDD 覆盖目标：**
- `bootstrap_probability()` — 二分类概率
- `bootstrap_distribution()` — 连续分布分位数（标准/BCa/m-out-of-n/parametric_gpd 四种方法）
- `bootstrap_aa/bb/ab/ba()` — 过程分析四种统计
- `bootstrap_conditional_quantile()` — 条件分位数
- `total_variation_distance()` — TVD 计算
- `_compute_bca_correction()` — BCa 校正因子
- `detect_heavy_tail()` — 厚尾检测（Hill 估计量）

---

## 三、可 Bootstrap 清单

### 3.1 可直接 Bootstrap 的面板（数据已存储）

| 面板 | 可 Bootstrap 的统计量 | 优先级 |
|------|---------------------|--------|
| **analysis_panel** | GDR 分布各分位数、各池成功率、资源消耗/收益分布 | 🔴 高 |
| **process_analysis_panel** | AA/BB/AB/BA 所有概率、条件概率、比值 | 🔴 高 |
| **retreat_panel** | 条件资源分布分位数、核密度回归曲线、资源不足概率 | 🟡 中 |
| **worst_impact_panel** | 条件资源分布的 α 分位数 | 🟡 中 |

### 3.2 需小改即可 Bootstrap 的面板

这些面板每步跑 N 次模拟，但只保存聚合结果。只需额外保存个体结果（N 个 bool），**零额外模拟**。

| 面板 | 当前保存 | 需额外保存 | 改动量 |
|------|---------|-----------|--------|
| **strategy_panel** | 每步 `success_probability: float` | 每步 `success_flags: List[bool]`（N×1 字节） | 小 |
| **resource_search_panel** | 每步 `success_probability: float` | 每步 `success_flags: List[bool]` | 小 |
| **worst_impact_panel（新池子分布）** | 聚合 `pool_distribution` | `pool_success_counts: List[int]` | 小 |

### 3.3 不做 Bootstrap 的面板

| 面板 | 原因 |
|------|------|
| **gacha_panel** | 模拟面板，负责跑模拟和展示原始结果，非分析面板 |

---

## 四、核心设计决策

1. **零额外模拟**：Bootstrap 是纯数组重抽样操作
2. **B=1000 次重抽样**，95% 置信区间，随机种子固定（可复现）
3. **默认 BCa 方法**（校正偏差和偏态，二阶精度 O(1/n)），同时提供百分位法作为对比
4. **厚尾检测**：连续量统计量自动检测厚尾（Hill 估计量），若 α < 2 则警告并建议 m-out-of-n
5. **尾部分位数使用参数 Bootstrap**（从拟合 GPD 抽样），标准 Bootstrap 对极端分位数不可靠
6. **对偶变量法兼容**：`paired=True` 时重抽样 N/2 对而非 N 个个体
7. **TVD 总变差**：衡量整个分布估计的稳定性

### 4.1 偏差校正：BCa 方法

简单百分位法存在偏差（尤其概率接近 0/1 时）。BCa 校正两个参数：

- **z₀（偏差校正）**：`Φ⁻¹(#(θ̂*_b < θ̂) / B)`
- **a（加速系数）**：通过 Jackknife 估计，校正偏态

校正后 CI：`[θ̂*_(α₁), θ̂*_(α₂)]` 其中 α₁, α₂ 经 z₀ 和 a 调整。

### 4.2 厚尾问题与对策

| 统计量 | 分布特征 | Bootstrap 可靠性 | 推荐方法 |
|--------|---------|-----------------|---------|
| 成功率（伯努利） | 有限方差 p(1-p) | ✅ 完全可靠 | 标准 Bootstrap + BCa |
| 事件/成败模式概率 | 有限方差 | ✅ 完全可靠 | 标准 Bootstrap + BCa |
| GDR 均值/中位数 | 通常有限方差 | ✅ 可靠 | 标准 Bootstrap + BCa |
| 资源消耗/剩余均值 | **可能厚尾** | ⚠️ 需检查 | 自动厚尾检测 → m-out-of-n |
| VaR/CVaR（尾部分位数） | 尾部数据稀疏 | ❌ 不可靠 | **参数 Bootstrap（GPD）** |

> 文献依据：Athreya (1987) 证明方差无限时 Bootstrap 不一致；Hall (1990) 给出充要条件。本项目概率估计（伯努利）不受影响。

### 4.3 总变差（TVD）

衡量两个离散概率分布的整体距离：`TVD(P, Q) = (1/2) Σ_x |P(x) - Q(x)|`

Bootstrap B 次后得到 B 个分布估计，TVD 均值衡量"分布估计的平均变异程度"——一个数字告诉你整个分布估计有多稳。

### 4.4 已知的引擎级问题（待修复）

以下问题在 P12-Phase1.5 后审查中发现，当前 BootstrapEngine 实现中存在：

#### 问题 1：Jackknife 上限 1000 截断

**现状**（`bootstrap.py` line 91）：`for i in range(min(n, 1000))`

当 n > 1000 时只用前 1000 个 leave-one-out 估计，加速因子 a 的精度被截断。Efron (1987) 的 BCa 理论要求完整 Jackknife，截断后 a 的收敛速度从 O(n⁻¹) 降为 O(1000⁻¹)。

**方案**：n > 1000 时随机抽样 1000 个 Jackknife 点（而非取前 1000），保持无偏性：

```python
max_jk = min(n, 1000)
jk_indices = np.random.default_rng(42).choice(n, size=max_jk, replace=False) if n > max_jk else range(n)
for idx, i in enumerate(jk_indices):
    mask[i] = False
    jk_vals[idx] = stat_fn(data[mask])
    mask[i] = True
```

#### 问题 2：厚尾检测未自动采纳

**现状**：`detect_heavy_tail()` 返回 `{alpha, heavy_tail, recommendation}`，但 `bootstrap_mean()` / `bootstrap_quantile()` 不自动调用它。面板需要主动检查——当前无面板集成，形同虚设。

**方案**：在 `bootstrap_mean()` 中增加 `auto_heavy_tail=True` 参数。开启时：
1. 自动调用 `hill_estimator()`
2. α < 2 时自动切换到 GPD-param Bootstrap（`_bootstrap_tail_gpd` 逻辑泛化为均值场景）
3. 在 `BootstrapResult.method` 中标注 `'GPD-param (auto: heavy tail detected α={:.2f})'`

实现细节：将 `_bootstrap_tail_gpd` 泛化为接受任意统计量函数，而非仅分位数。

#### 问题 3：BCa 在小 n 时不稳定

**现状**：BCa 在 `use_bca=True` 时无条件尝试，失败回退百分位法。但 Jackknife 加速因子 a 在 n < 30 时方差极大（分母 `sum(jk_dev²)^1.5` 极不稳定）。

**方案**：n < 50 时自动使用百分位法（不尝试 BCa），在 `BootstrapResult.method` 中标注 `'percentile (n<50, BCa unstable)'`。

#### 问题 4：m-out-of-n 的 m 选择策略缺失（理论审查发现）

m 选太小增加方差，选太大保留偏差，需数据驱动选择。当前实现未提供 m 选择策略。

#### 问题 5：Hill 估计量的 k 选择缺失（理论审查发现）

k 对顺序统计量个数极度敏感，无 k 选择策略则厚尾检测不可靠。

#### 问题 6：BCa 在离散 Bootstrap 分布下可能失效（理论审查发现）

罕见事件（p~0.1%）的 Bootstrap 分布高度离散，BCa 的连续分布假设可能不成立。

> 问题 4-6 来源：`docs/reports/全模块理论严谨性系统性审查.md`（2026-05-26）。这三个问题的修复优先级低于问题 1-3，可在引擎修复阶段一并处理或后续深化。

---

## 五、阶段1：BootstrapEngine 核心类（TDD）✅ 已完成

> **阶段1 分为 8 个子任务，已于 2026-05-26 全部完成。**

- [x] **1.1: BootstrapResult 数据类**

**新建：** `gacha_simulator/core/bootstrap.py`
**新建：** `tests/core/test_bootstrap.py`

```python
@dataclass
class BootstrapResult:
    point_estimate: float
    ci_lower: float
    ci_upper: float
    bootstrap_std: float
```

- [x] **1.2: _resample_indices() 静态方法**

测试：验证输出形状 (B, n)、每行是有效索引范围、有放回抽样特性。

- [x] **1.3: bootstrap_probability() — 二分类概率**

测试：已知成功/失败数组 → 验证 CI 包含点估计。

- [x] **1.4: _compute_bca_correction()**

测试：用已知偏态的 Bootstrap 样本验证 BCa CI 比百分位法更准确。

- [x] **1.5: bootstrap_distribution() — 连续分布分位数**

测试：正态分布样本 → 验证中位数 CI 包含真实值。

- [x] **1.6: detect_heavy_tail() — Hill 估计量**

测试：正态分布（α=∞）→ 非厚尾；Pareto(α=1.5) → 厚尾。

- [x] **1.7: total_variation_distance()**

- [x] **1.8: 运行阶段1全部测试并提交**

---

## 六、阶段2：引擎已知问题修复（待实施）

> 来源：§四 4.4 的六个问题。本节是 `docs/拉普拉斯平滑与Bootstrap改进计划.md` §二 的完整迁移。

### 改动范围

| 文件 | 改动 |
|------|------|
| `core/bootstrap.py` | Jackknife 随机抽样、auto_heavy_tail 参数、n<50 跳过 BCa、m 选择策略、Hill k 选择策略、离散 BCa 守卫、**EVT拟合路径统一（B2.8）**、**TIB 检验反演 Bootstrap（B2.9）** |
| `tests/core/test_bootstrap.py` | 新增边界测试：n>1000 Jackknife、auto_heavy_tail 集成、n<50 BCa 跳过、m 选择验证、**EVT 拟合统一路径测试**、**TIB 覆盖率测试** |

### 子任务

- [ ] **2.1: Jackknife 随机抽样**——n > 1000 时随机抽取 1000 个索引替代取前 1000
- [ ] **2.2: auto_heavy_tail 参数**——`bootstrap_mean()` / `bootstrap_quantile()` 新增参数，自动检测并切换 GPD
- [ ] **2.3: BCa n<50 守卫**——小样本自动回退百分位法，标注原因
- [ ] **2.4: m-out-of-n m 选择策略**——数据驱动的 m 选择（如 Sherman-Morrison 或 double bootstrap 简化版）
- [ ] **2.5: Hill k 选择策略**——基于 Hill 图的拐点检测或 Hall 的自适应方法
- [ ] **2.6: 离散 BCa 守卫**——检测 Bootstrap 分布离散度，过离散时回退百分位法
- [ ] **2.7: 更新测试 + 提交**

> 问题 2.4-2.6 优先级较低，可在 2.1-2.3 完成后单独评估是否纳入本轮。

- [ ] **2.8: EVT 拟合路径统一（NEW — 2026-05-28，来源：P25 §八）**——`_bootstrap_tail_gpd()` 当前直接调用 `genpareto.fit()` 自行拟合 GPD，与 `evt_tail.py` 中的 GPD 拟合逻辑重复且不一致。改为委托 `evt_tail.fit_gpd_lower()` + `evt_tail.evt_var_right()`，消除重复实现并统一：
  1. 替换直接 `genpareto.fit()` 为委托 `evt_tail.fit_gpd_lower()`
  2. 在 GPD-param bootstrap 循环前加入退化检测（通过临时 `EmpiricalDistribution` 的 `_count_distinct() < 20` 守卫）
  3. 每个 resample 的 GPD 拟合失败时优雅回退该 resample 的经验分位数
  4. 删除 `_bootstrap_tail_gpd()` 中的 `genpareto` 直接导入（统一通过 `evt_tail` 访问）
  5. 同步享受 `evt_tail._fit_gpd()` 的 MLE 正则性检查（Smith 1985: ξ < -1 回退）
- **测试**：验证退化 resample 回退 + 与 `evt_tail` 结果一致性 + 参数传递正确性
- **改动量**：`bootstrap.py` ~30 行，`test_bootstrap.py` ~15 行

- [ ] **2.9: GPD-param Bootstrap 百分位法 → TIB（检验反演 Bootstrap）（NEW — 2026-05-28，来源：Schendel & Thongwichian 2017 + P25 §三.5）**——当前 `_bootstrap_tail_gpd()` 使用百分位法 CI，但 Schendel & Thongwichian (2017, *Advances in Water Resources*, Vol. 99, pp. 53-59) 证明百分位法在 GPD POT 框架下**系统性低估**上下置信界（因未正确建模超额发生次数与超额幅度的双域结构）。TIB 通过反演 Bootstrap 假设检验构造 CI，覆盖率最优。**无现成的 Python/R 实现——需要从零编写。**
  - **TIB 算法概要**：
    1. 对候选 VaR 值 y*，定义 H₀: VaR(q) = y*
    2. 在 H₀ 约束下，GPD 参数被约束（σ 由 ξ 和 y* 通过 VaR 公式反解）
    3. 从受限模型生成 Bootstrap 样本
    4. 计算检验统计量（Bootstrap VaR 估计）
    5. 比较观测统计量与 Bootstrap 分布 → p-value
    6. 数值求根搜索 CI 端点（双层循环：外层求根 + 内层 Bootstrap）
  - **复杂度**：B² 次 MLE 拟合（外层求根 ~20 次 + 内层 Bootstrap B=1000 次），比当前 O(B) 增加约 20 倍计算成本
  - **优化策略**：外层可使用粗网格搜索替代精确求根（~10-15 个候选值）；内层 B 可降至 500（TIB 对 B 不敏感，Schendel & Thongwichian 2017 验证）
  - **改动量**：`bootstrap.py` ~120 行，`test_bootstrap.py` ~25 行
  - **风险**：计算成本较高（B=500 × 20=10,000 次 MLE 拟合/指标），对于 B 类边际 GDR（需要 MLE-IC 的 GDR）成本可能过高
  - **降级策略**：对 A 类 GDR 使用 B2.8 统一后的百分位法（标注覆盖率警告）；仅对 B 类边际 GDR 启用 TIB

> **B2.8 vs B2.9 的依赖**：B2.8（EVT 路径统一）是 B2.9（TIB）的前置——TIB 需要调用统一的 EVT 拟合接口。B2.8 可独立交付（当前百分位法 + 统一路径），B2.9 在此基础上替换 CI 构造方法。

---

## 七、阶段3：UI 集成

### 7.1 过程分析面板已有 Wilson CI，不需要 Bootstrap CI

**关键结论（2026-05-28 重新审视）：过程分析面板（AA/BB/AB/BA）的概率列已经显示了 Wilson 95% 得分区间，再加 Bootstrap CI 是冗余的。**

理由：

1. **Wilson 和 Bootstrap 在这里回答的是同一个问题**——「基于这 N 次模拟，这个概率估计有多精确？」。两者的输入完全一致（事件计数和总次数），不是两个独立维度的不确定性。
2. **对二项比例，Wilson 得分区间实际上优于 Bootstrap**——Wilson 是专门为二项比例设计的，边界覆盖率（p 接近 0/1 时）优于标准 Bootstrap；Wilson 是解析公式，确定性、零计算成本；Bootstrap 在罕见事件（p~0.01）时分布高度离散，BCa 的连续假设可能不成立（计划本身在问题 2.6 也承认了这点）。
3. **同时显示两套 CI 会让用户困惑**——两个数字回答同一问题、用不同方法，叠加无实际意义。

**Bootstrap CI 不可替代的场景是连续型统计量**（均值、中位数、资源消耗等），Wilson 公式不适用于这些。这才是 Bootstrap 真正发力的地方。

| 统计量类型 | Wilson 能用吗？ | Bootstrap 有用吗？ |
|-----------|----------------|-------------------|
| 二项比例（成功率、模式概率） | ✅ 更优 | ❌ 冗余 |
| GDR 均值/中位数 | ❌ | ✅ |
| 资源消耗均值 | ❌ | ✅ |
| 条件分位数（VaR/CVaR） | ❌ | ⚠️ 需 GPD-param bootstrap |

### 7.2 UI 方案重新审视

原始计划（`2026-05-18-bootstrap-stability-analysis.md` 阶段 2~7）和 MVP 方案（`拉普拉斯平滑与Bootstrap改进计划.md` §三）在 UI 实现上存在以下差异需统一：

| 议题 | 原始计划 | MVP 方案 | 本计划采纳 |
|------|---------|---------|-----------|
| 覆盖面板 | 6 个面板 | 2 个面板（process_analysis + analysis） | **先 analysis_panel，后扩展**（process_analysis 不需要 Bootstrap CI，见 §7.1） |
| CI 展示形式 | 表格 CI + 图表 CI（误差棒/阴影带） | 仅表格 CI | **分阶段：先表格后图表** |
| 触发方式 | 每面板「计算稳定性」按钮 | 未明确 | **自动计算**（Bootstrap 是纯数组操作，成本极低，无需手动触发） |
| 独立 Bootstrap 面板 | 无 | 无（暂不实施） | 暂不实施（工作量大，优先级低） |

**关键决策：取消手动「计算稳定性」按钮，改为模拟完成后自动计算 CI。**

理由：Bootstrap 对已有数据做纯数组重抽样，B=1000、N=10000 时单次计算 < 1 秒，无需用户手动触发。自动计算消除了"用户忘记点按钮看不到 CI"的 UX 问题。

### 7.3 分阶段实施

```
阶段 3A（MVP，<2h）——仅 analysis_panel
└── analysis_panel：GDR 统计表格——均值、中位数列嵌入 Bootstrap 95% CI
    └── process_analysis_panel 已有 Wilson CI，不需要 Bootstrap CI（见 §7.1）

阶段 3B（扩展，3-6h）
├── strategy_panel：成功率趋势图 CI 阴影带（需小改数据保存：+success_flags）
├── resource_search_panel：成功率-资源曲线 CI 阴影带（需小改数据保存）
├── retreat_panel：条件分布分位数 CI + 核密度回归 CI 阴影带
└── worst_impact_panel：保守资源 CI + 安全边际 CI

阶段 3C（可选，优先级低）
└── 独立 Bootstrap 面板（新 Tab，完整 UI）
```

### 7.4 阶段 3A 详细方案（MVP）——仅 analysis_panel

**目标**：在 `analysis_panel.py` 的 GDR 统计表格（Plotly `go.Table`，当前 5 列）中，对连续型统计量（均值、中位数、VaR）追加 Bootstrap 95% CI。

**为什么只做 analysis_panel**：见 §7.1——process_analysis_panel 的 AA/BB/AB/BA 四个表已经是二项比例，Wilson CI 更优，Bootstrap CI 冗余。

**具体改动**：

GDR 统计表格（键 `gdr_statistics`，当前 5 列）：

```
旧：指标 | 均值 | 中位数 | 标准差 | VaR(5%)
新：指标 | 均值 [95% CI] | 中位数 [95% CI] | 标准差 | VaR(5%) [95% CI]
```

CI 嵌入单元格内，格式为：

```
0.7234 [0.695, 0.751]
```

**列数不变（仍为 5 列），无需新增列**。单元格内文本因附加 CI 而变长（约增加 15 字符），Plotly 表格自动缩放列宽，在 QScrollArea 内可水平滚动。

**实现要点**：

1. `AnalysisWorker._run_impl()` 在构造 `gdr_statistics` 的 `TableData` 前，对每个 GDR 指标分别调用 `BootstrapEngine`：
   - 均值列：`bootstrap_mean(gdr_values)` → `"0.7234 [0.695, 0.751]"`
   - 中位数列：`bootstrap_distribution(gdr_values, stat_fn=np.median)` → 同上格式
   - VaR 列：尾部分位数检测——先调用 `detect_heavy_tail()`，若无厚尾则用标准 `bootstrap_distribution(stat_fn=lower_quantile)`，若有厚尾则自动切换 `parametric_gpd` 方法；当前 GPD-param bootstrap 尚无完整实现时，先预留格式框架，CI 值暂时显示「待实现」

2. 标准差列不做 Bootstrap——标准差的 Bootstrap 分布高度偏态，解释复杂，用户需求优先级低
3. N < 100 时显示「样本不足」，不显示 CI

**VaR CI 的分阶段处理**：

**理论修正（2026-05-28）**：原计划用厚尾检测（Hill α < 2）作为 VaR CI 是否可用的判断条件，这是错误的。极端分位数 Bootstrap 不可靠的根本原因是**尾部稀疏**（低分位数只有少量样本落在其下，重抽样的尾部排序统计量方差极大、覆盖率差），而非分布是否厚尾。即使正态分布，q=0.05 时标准 Bootstrap CI 也不可靠。正确判断条件是分位数水平本身。

| 项目 | 现在（3A） | 后续（P4 EVT 完成） |
|------|-----------|-------------------|
| 非极端分位数（q > 0.1） | 标准百分位法 Bootstrap | 不变 |
| 尾部分位数（q ≤ 0.1） | 显示「待实现」 | GPD 参数 Bootstrap（从拟合 GPD 抽样计算分位数 CI） |
| N < 100 | 显示「样本不足」 | 不变 |

### 改动范围（阶段 3A）

| 文件 | 改动 |
|------|------|
| `gui/analysis_panel.py` | `_compute_statistics_unit()` / `_build_gdr_table()` 中，均值+中位数+VaR 计算后追加调用 BootstrapEngine，格式化 CI 嵌入单元格文本 |

相比原方案节省的改动：
- ~~`gui/process_analysis_panel.py`~~ —— 不需要改（Wilson CI 已覆盖）
- ~~AB/BA 表列宽超限问题~~ —— 不存在

### 阶段 3B 详细方案（扩展）

#### strategy_panel（需小改数据保存）

- [ ] **ForwardStep/BackwardStep 添加 `success_flags: List[bool]` 字段**
- [ ] **修改前进法/后退法——每步保存个体成功/失败结果**
- [ ] **趋势图添加阴影带（Bootstrap CI）**——自动计算，无需按钮

#### resource_search_panel（需小改）

- [ ] **步骤数据类添加 `success_flags: List[bool]`**
- [ ] **修改 `_simulate_with_resource`——返回个体结果**
- [ ] **成功率-资源曲线添加阴影带**

#### retreat_panel

- [ ] **实现 `bootstrap_conditional_quantile()`**
- [ ] **核密度回归曲线添加阴影带**
- [ ] **资源不足概率显示 CI**

#### worst_impact_panel

- [ ] **保守资源（条件分位数）添加 CI**
- [ ] **大保底覆盖倍数 CI 从保守资源 CI 派生**
- [ ] **新池子数分布添加 Bootstrap（需小改保存 `pool_success_counts`）**

### 暂不实施

- 独立 Bootstrap 面板（需新 Tab + 完整 UI，工作量大，优先级低）
- 分位数 Bootstrap CI（VaR 参数 Bootstrap 依赖 P4 EVT 的 GPD 尾部拟合——3A 仅预留格式框架显示「待实现」，真正实施在 P4 完成后）
- 图表 CI（阶段 3A 仅表格 CI，图表 CI 在阶段 3B）

---

## 八、验收标准

- [x] BootstrapEngine 核心类所有方法通过 TDD 测试
- [ ] 引擎已知问题修复（6 项）通过测试
- [ ] process_analysis_panel AA/BB/AB/BA 概率列保持 Wilson CI（现有实现，无需改动；Bootstrap CI 冗余，见 §7.1）
- [ ] analysis_panel GDR 分布、各池成功率显示 CI
- [ ] strategy_panel 成功率趋势图显示阴影带（阶段 3B）
- [ ] resource_search_panel 成功率-资源曲线显示阴影带（阶段 3B）
- [ ] retreat_panel 条件分布、核密度回归、资源不足概率显示 CI（阶段 3B）
- [ ] worst_impact_panel 保守资源显示 CI（阶段 3B）
- [ ] 性能：N=10000、B=1000 时，单次 Bootstrap 计算 < 5 秒
- [ ] 全部已有测试保持绿色

---

## 九、与其他计划的兼容性

### 与 P4 Task 3（EVT 尾部拟合）的关系

Bootstrap 对极端分位数不可靠。P4 的 EVT 实现后，P3 的尾部分位数自动升级为 Bootstrap-EVT 混合方法：

```
对 N 条数据做 Bootstrap:
  for b = 1..B:
    重抽样 N 条 → data_b
    对 data_b 拟合 GPD → (ξ_b, β_b)
    从 GPD 解析计算 VaR_p(data_b)
  从 B 组 VaR 估计中取分位数 → CI
```

P3 的 `bootstrap_distribution` 预留 `resample_method: str = 'auto'` 参数（`'auto'`/`'standard'`/`'m_out_of_n'`/`'parametric_gpd'`）。

**2026-05-28 更新**：P24（EVT 尾部拟合）已完成，`evt_tail.py` 提供 `fit_gpd_lower()` / `fit_gpd_upper()` / `evt_var_right()` 等统一接口。P25（EVT 改进）审查发现 B2.8（EVT 拟合路径统一）和 B2.9（TIB 替代百分位法）两个新需求。详见 `docs/P25 EVT改进——离散型与退化分布处理.md` §八。

### 与 P4 Task 2（对偶变量法）的关系

对偶变量法将 N 次模拟配对。朴素 Bootstrap 打破配对 → CI 偏宽。P3 支持 `paired=True`——重抽样 N/2 对而非 N 个个体。

### 与小样本概率估计改进计划的关系

`docs/小样本概率估计改进计划.md` 处理概率点估计本身的不确定性（Wilson 得分区间），本计划处理**连续型**统计量的抽样不确定性（Bootstrap CI）。

两者在覆盖范围上互补而非重叠：
- **process_analysis_panel**（AA/BB/AB/BA）的概率列为二项比例，Wilson CI 更优——Bootstrap CI 不介入（见 §7.1）
- **analysis_panel** 的均值/中位数/VaR 为连续统计量，Wilson 公式不适用——由 Bootstrap CI 覆盖

两者独立实施，互不阻塞。

### 建议执行顺序

```
阶段2（引擎修复）→ 阶段3A（UI MVP）→ 阶段3B（UI 扩展）
    ↓                    ↓
P4（自适应+EVT）     小样本概率估计改进（独立并行）
```

---

## 附录：源文件废弃说明

本文件合并自以下两个文件，原文件已废弃：

1. **`docs/superpowers/plans/2026-05-18-bootstrap-stability-analysis.md`**（v3，2026-05-26）
   - 贡献内容：Bootstrap 引擎设计、BCa/GPD/Hill 理论、UI 阶段划分（原始 6 面板方案）、测试策略、验收标准
   - 废弃原因：与拉普拉斯文件中的 Bootstrap 改进存在内容重叠，合并避免维护两份文件

2. **`docs/拉普拉斯平滑与Bootstrap改进计划.md`**（2026-05-26）
   - 贡献内容：§二 引擎已知问题修复（Jackknife/厚尾/BCa）+ §三 UI MVP 方案
   - 废弃原因：Bootstrap 部分合并至本文件，小样本概率估计部分独立为 `docs/小样本概率估计改进计划.md`

原文件保留在仓库中（含废弃声明头），仅供历史回溯，不再作为实施依据。

---

## 更新记录

| 日期 | 变更 |
|------|------|
| 2026-05-26 | 合并两个 Bootstrap 相关计划文件，重新审视 UI 方案，统一为单一权威文件 |
| 2026-05-28 | **重大修订**：process_analysis_panel 已有 Wilson CI，二项比例的 Bootstrap CI 冗余，3A 聚焦 analysis_panel 连续统计量；VaR CI 预留位置 |
| 2026-05-28 | **新增 B2.8**（来源：P25）：EVT 拟合路径统一——`_bootstrap_tail_gpd()` 委托 `evt_tail.fit_gpd_lower()` 消除重复实现 + 退化检测 |
| 2026-05-28 | **新增 B2.9**（来源：Schendel & Thongwichian 2017 + P25）：GPD-param Bootstrap 百分位法 → TIB——百分位法在 POT 框架下系统性低估 CI 边界，TIB 覆盖率最优；无现成 Python 实现，需从零编写 ~120 行 |
