# EVT 尾部拟合独立计划

> 创建日期：2026-05-28 | 状态：设计中
> 提取自：`docs/自适应模拟与方差缩减计划.md` §五 Task 3 + §5.5 外部库替代方案
> 依赖：P23 scipy 正式依赖（已完成）、P3 Bootstrap 引擎（核心已完成，`_bootstrap_tail_gpd` 已使用 `scipy.stats.genpareto`）

## 背景

P4（自适应模拟与方差缩减）的 Task 3 原本是 EVT 尾部拟合，与 Task 1（自适应停止）和 Task 2（对偶变量法）耦合在同一计划文件中。但 EVT 尾部拟合是一个**独立的技术改进**——它不依赖自适应停止、也不依赖对偶变量法，且影响范围远超 `analysis_panel.py` 一处。本计划将其提取为独立计划，并解决原方案的两个设计缺陷：

1. **覆盖范围过窄**：原方案仅在 `analysis_panel.py` 添加 `_compute_var_robust()` 辅助函数，但 VaR/CVaR 的实际入口是 `EmpiricalDistribution.var()/cvar()`——所有面板都通过它计算。应在核心层集成 EVT，自动惠及所有界面。
2. **外部库评估不充分**：原方案将 QuantLite 列为「未来可选升级路径」，但其 `tail_risk_summary()` 可能直接覆盖 GPD 拟合 + VaR/CVaR 计算 + 阈值选择全套需求。

---

## 一、VaR/CVaR 使用现状

### 1.1 调用链

```
所有 GUI 面板
    ↓
EmpiricalDistribution.var(alpha)   ← 当前：纯经验分位数（线性插值）
EmpiricalDistribution.cvar(alpha)  ← 当前：底部 α 尾部均值
    ↓
gui/analysis_panel.py              ← 最大消费方（6 处调用）
    ├── risk_var_cvar 图表          ← dist.var() / dist.cvar()
    ├── worst_case 图表             ← dist.var() / dist.cvar()
    ├── best_case 图表              ← dist.var()
    ├── conditional_analysis 表格   ← dist.var()
    └── GDR 统计表格                ← EmpiricalDistribution(vals).var(alpha)
```

### 1.2 关键发现

**所有 VaR/CVaR 计算都经过 `EmpiricalDistribution.var()` 和 `.cvar()` 两个方法**。如果在核心层集成 EVT，无需修改任何 GUI 代码即可自动覆盖所有面板。

当前经验分位数的问题（理论审查已指出）：
- 极端分位数（α ≤ 0.1）的标准误是中位数的 ~28 倍
- 5000 样本下 5% VaR 的实际精度远低于直观感受
- 尾部数据稀疏时线性插值引入额外误差

---

## 二、技术方案

### 2.1 核心思路：在 `EmpiricalDistribution` 层集成 EVT

**关键洞察**：`var()` 是 `quantile()` 的别名（`distribution.py:112`），且最差影响面板（`worst_impact.py:53`）和 analysis_panel 的 VaR 预设按钮（`analysis_panel.py:1736`）直接调用 `quantile()` 而非 `var()`。因此 EVT 逻辑应放在 `quantile()` 中，一次性覆盖所有调用方。

```python
class EmpiricalDistribution:
    def quantile(self, p: float, use_evt: bool = True) -> float:
        """分位数 —— 极端分位数自动使用 EVT GPD 外推。"""
        if use_evt and (p <= 0.1 or p >= 0.9) and self._n >= 100:
            evt_result = self._evt_quantile(p)
            if evt_result is not None:
                return evt_result
        return self._empirical_quantile(p)  # 当前逻辑（线性插值）

    def var(self, alpha: float = 0.05, use_evt: bool = True) -> float:
        return self.quantile(alpha, use_evt=use_evt)  # 保持别名关系

    def cvar(self, alpha: float = 0.05, use_evt: bool = True) -> float:
        """CVaR —— 极端分位数自动使用 EVT GPD 外推。"""
        if use_evt and alpha <= 0.1 and self._n >= 100:
            evt_result = self._evt_cvar(alpha)
            if evt_result is not None:
                return evt_result
        return self._empirical_cvar(alpha)
```

**设计要点**：
- `use_evt=True` 默认启用，所有现有调用方零改动自动获得 EVT 精度提升
- `alpha <= 0.1` 或 `alpha >= 0.9` 才触发 EVT（非极端分位数经验估计已足够精确）
- `n < 100` 回退经验方法（样本不足时 GPD 拟合不可靠）
- **自适应阈值**：`target_exc = min(max(n × 0.05, 100), 500)`，保证超额样本数在 100–500 之间。n=1000 → 90% 阈值（100 超额）；n=2000–5000 → 95% 阈值（100–250 超额）；n=20000+ → 97.5%+ 阈值（500 超额）。大样本用更高阈值让 GPD 近似更精确（Coles 2001「阈值尽可能高」原则），而非关掉 EVT
- GPD 拟合结果**分上下尾独立缓存**（同一 Distribution 实例多次调用不重复拟合）
- 覆盖范围：`analysis_panel.py`（6+ 处 VaR/CVaR 调用 + VaR 预设按钮 + 条件分布分位数）、`worst_impact.py`（条件资源分布分位数）、`risk_analysis.py` 等全部走 `EmpiricalDistribution` 的调用方

### 2.1.1 截断分布处理（方案 B：语义检测）

**问题**：最差影响面板的 `ConditionalResourceDistribution` 按 GDR 成败分组后取资源分位数。当 GDR key 为资源类指标（`resource_remaining`/`resource_efficiency`/`resource_consumed`）且 `condition='success'` 时，成功组的资源值被**下界截断**——低尾分位数紧贴截断边界，EVT 外推可能将分位数推到截断边界以下。

GDR key 为 `all_targets`（默认）时，条件变量与被分位数化的变量不在同一维度，不存在截断问题，EVT 完全适用。

**方案**：保持 `use_evt=True` 默认启用。仅当调用方通过语义判断确认存在同变量截断时，显式传 `use_evt=False`。

- 判断逻辑放入 `WorstImpactAnalyzer.analyze()`（~5 行）——它同时持有 `gdr_key` 和 `_resource_name`
- 检测条件：`gdr_key in ('resource_remaining', 'resource_efficiency', 'resource_consumed') and condition == 'success'`
- 其余所有调用方不受影响，无需任何改动

**备选方案对比**（见 2026-05-28 讨论）：

| 方案 | 思路 | 结论 |
|------|------|------|
| A：场景检测 | `ConditionalResourceDistribution` 分组后检测两组是否完全分离 | 不选——假阴性（重叠时漏检），且该类不持有 GDR key 语义 |
| B：语义检测（**选定**） | 调用方根据 GDR key + resource 名称判断 | 实现最简单，判断逻辑明确，~5 行 |
| C：仅靠 scipy 回退 | 信赖 `genpareto.fit()` 拟合失败自动回退 | 不选——scipy 可能在截断数据上返回偏差参数而非报错，无法做确定性测试 |

### 2.2 GPD 拟合方案

#### 统一取负法（推荐实现策略）

**核心思路**：始终对右尾（上尾）拟合标准 GPD，通过数据取负统一处理下尾。这样只需维护一套 VaR/CVaR 公式，消除上下尾公式歧义。

```
# 上尾（p ≥ 0.9）：直接右尾 POT
exc = X[X > u_upper] - u_upper        # 标准超额值

# 下尾（p ≤ 0.1）：取负后右尾 POT
Y = -X
exc = Y[Y > u_Y] - u_Y                # Y 的右尾 = X 的左尾
```

**统一公式**（对任意右尾超额样本拟合 GPD(ξ, β)）：

```
φ = Nu / n                            # 超阈值概率
VaR(q) = u + β × ln(φ/(1-q))          (|ξ| < 1e-6，指数极限)
       = u + (β/ξ) × [(φ/(1-q))^ξ - 1]  (|ξ| ≥ 1e-6)
CVaR(q) = VaR(q) + (β + ξ×(VaR(q) - u)) / (1-ξ)  (ξ < 1)
```

其中 q 是目标分位数水平（右尾 q 接近 1，如 0.95）。

**回原尺度**：
- 上尾（p ≥ 0.9）：q = p，直接使用 VaR(q)
- 下尾（p ≤ 0.1）：q = 1-p，VaR_X(p) = -VaR_Y(1-p)，CVaR_X(p) = -CVaR_Y(1-p)

#### 方案 A：scipy + 自写 VaR/CVaR 公式（当前推荐）

- **GPD 拟合**：`scipy.stats.genpareto.fit(exceedances, floc=0)` — 久经检验的 MLE 实现；**必须 try/except** 捕获 `RuntimeError`（收敛失败）和 `ValueError`（无效数据），失败时返回 None 触发回退
- **MLE 正则性检查**（§7.3）：拟合后检查 ξ；ξ < -0.5 记录警告（标准误不可靠）；ξ < -1 强制回退（MLE 不存在）
- **有界支撑约束**（§7.5）：ξ < 0 时 GPD 有有限端点 `x_F = u - β/ξ`；外推分位数不应超过端点，越界则返回 None 回退
- **VaR/CVaR 公式**：~25 行统一公式 + 上下尾取负/回原尺度逻辑（§7.2），直接可验证
- **阈值选择**：自适应分位数（见 §2.1）作为工程默认；参数稳定性检测（Coles 2001, §4.3.4）作为可选诊断工具
- **新增代码量**：~120 行（`core/evt_tail.py`）+ ~40 行（`EmpiricalDistribution` 改动）

#### 方案 B：QuantLite（待评估后决定）

```
QuantLite.risk.evt.tail_risk_summary(data, alpha)
    ↓
直接返回 VaR, CVaR, threshold, ξ, β
```

- **优势**：GPD 拟合 + 阈值选择 + VaR/CVaR 一站式解决，代码量更少
- **风险**：2025 年新包，API 稳定性未知，GitHub stars/维护者活跃度待验证
- **预估代码量**：~30 行（仅需包装 QuantLite 调用）

### 2.3 方案对比

| 维度 | scipy + 自写公式 | QuantLite |
|------|-----------------|-----------|
| 新增依赖 | 无（scipy 已是正式依赖） | 1 个新依赖 |
| GPD 拟合成熟度 | scipy 久经检验 | 待验证 |
| VaR/CVaR 计算 | 自写 15 行解析公式（无 Bug 空间） | 内置 `tail_risk_summary()` |
| 阈值选择 | 自写 30 行稳定性检测 | 内置 |
| 总代码量 | ~130 行 | ~30 行 |
| 长期维护成本 | 低（公式简单，不会变） | 依赖 QuantLite 上游 |
| 可替换性 | 高（API 清晰，随时可切 QuantLite） | 中（切换需改 API 调用） |

### 2.4 建议：先方案 A，保留方案 B 入口

实施策略：
1. **Phase 1**（本计划）：用 scipy + 自写公式实现，API 设计预留 QuantLite 切换空间
2. **Phase 2**（可选）：评估 QuantLite 成熟度后，若其 `tail_risk_summary()` 确实更优，仅需替换 `evt_tail.py` 内部实现，`EmpiricalDistribution` 不感知

这样既不会因为等 QuantLite 评估而阻塞实施，也不会在未来想切换时被锁定。

---

## 三、实施步骤

### Step 1：新建 `core/evt_tail.py`

- [ ] `fit_gpd_tail(data)` → `(ξ, β, threshold, phi) | None`
  - **自适应阈值**：`target_exc = min(max(n × 0.05, 100), 500)` → 阈值分位点 = `1 - target_exc / n`
  - 例：n=1000 → 90% 阈值（100 超额）；n=5000 → 95%（250 超额）；n=20000+ → 97.5%+（500 超额）
  - 委托 `scipy.stats.genpareto.fit(exceedances, floc=0)`
  - **try/except** 捕获 `RuntimeError`（收敛失败）和 `ValueError`（无效数据）→ 返回 None
  - **MLE 正则性检查**（§7.3）：ξ < -0.5 记录警告（渐近性质不成立，点估计仍可用）；ξ < -1 强制返回 None（MLE 不存在）
  - 超阈值样本 < 10 时回退返回 None
- [ ] `fit_gpd_upper(data)` — 对 X > u 拟合标准 POT（上尾场景）。委托 `fit_gpd_tail`
- [ ] `fit_gpd_lower(data)` — 对 Y = -X 取负后拟合标准 POT（下尾统一取负法，§7.2.1）。委托 `fit_gpd_tail`
- [ ] `gpd_threshold_stability` 保留为备选：自适应阈值已足够稳健，稳定性检测作为可选诊断工具
- [ ] `evt_var_right(q, xi, beta, u, phi)` → `float | None` — 右尾 VaR 统一公式（q 接近 1）
  - `|ξ| < 1e-6` 时用指数极限 `u + β × ln(φ/(1-q))` 避免除以近零值
  - **有界支撑约束**（§7.5）：ξ < 0 时检查 VaR 是否超过端点 `u - β/ξ`，越界返回 None
  - q 在阈值覆盖范围内返回 None（调用方使用经验分位数）
- [ ] `evt_cvar_right(q, xi, beta, u, phi)` → `float | None` — 右尾 CVaR 统一公式（q 接近 1）
  - ξ ≥ 1 返回 inf（一阶矩不存在）

### Step 2：在 `EmpiricalDistribution` 集成 EVT

- [ ] 新增 `_evt_quantile(p)` 私有方法
  - 首次调用拟合 GPD，**分别缓存**下尾 `_evt_lower` 和上尾 `_evt_upper`——阈值、ξ、β 均不同，不能共用一套参数
  - `p ≤ 0.1` → 下尾 GPD 外推：对 Y = -X 取负，拟合标准右尾 GPD（Y 的超额 = Y > u_Y 的部分），VaR_X(p) = -VaR_Y(1-p)，CVaR_X(p) = -CVaR_Y(1-p)
  - `p ≥ 0.9` → 上尾 GPD 外推：直接对 X - u_upper | X > u_upper 拟合标准右尾 GPD
  - 外推失败 → 返回 None
- [ ] 修改 `quantile(p, use_evt=True)`——EVT 逻辑放在此方法，因为 `var()` 是其别名且最差影响面板直接调 `quantile()`
  - `use_evt=True` 且 `p` 极端 → 调 `_evt_quantile`
  - 回退 → 调现有经验分位数逻辑（线性插值）
- [ ] 修改 `var(alpha, use_evt=True)`——委托 `self.quantile(alpha, use_evt=use_evt)`，保持别名关系
- [ ] 修改 `cvar(alpha, use_evt=True)`——独立 EVT 路径（CVaR 不委托 quantile）

### Step 3：截断场景处理 + Bootstrap CI 适配

- [ ] `WorstImpactAnalyzer.analyze()`：检测资源类 GDR + `condition='success'` → 传 `use_evt=False`（~5 行）
- [ ] P18c 中 VaR CI 的「待实现」（α ≤ 0.1）—— EVT 点估计就位后，参数 Bootstrap CI 可利用同一 GPD 拟合结果
- [ ] `bootstrap.py::_bootstrap_tail_gpd` 已使用 `scipy.stats.genpareto`，与 `evt_tail.py` 共享底层

### Step 4：测试

- [ ] `tests/core/test_evt_tail.py`（新建）—— 7 个测试（见原 P4 计划 §5.2）
- [ ] `tests/core/test_distribution.py`（扩展现有或新建）—— EVT 路径 + 回退路径

### Step 5：GUI 验证

- [ ] 统计分析面板 → VaR/CVaR 分析 → 确认 EVT 和经验分位数基本一致（N ≥ 5000）
- [ ] 最差情形分析 → 确认 VaR/CVaR 列自动使用 EVT
- [ ] GDR 统计表格 → 确认 VaR 列自动使用 EVT
- [ ] 条件分析 → 确认子分布同样享受 EVT

### Step 6：更新「关于→算法说明」界面

- [ ] `gui/about_dialog.py` `_create_algorithms_tab()` 更新以下小节：
  - **风险分析**（line 279-284）：VaR/CVaR 描述从「经验分布的 α 分位数」改为区分 EVT 外推（极端分位数 p≤0.1 或 p≥0.9）与经验分位数（非极端分位数）；CVaR 同样说明 EVT 路径
  - **经验分布**（line 287）：分位数计算描述从「线性插值法」改为「非极端分位数用线性插值，极端分位数（p≤0.1 或 p≥0.9）用广义 Pareto 分布（GPD）外推（Pickands-Balkema-de Haan 定理）」
  - 可新增一小节 **EVT 尾部拟合**：简介 POT 方法、GPD 拟合、自适应阈值选择、上下尾统一处理

---

## 四、与已有代码的关系

### 4.1 与 `bootstrap.py` 的分工

| 模块 | 提供 | 用途 |
|------|------|------|
| `evt_tail.py`（新建） | EVT VaR/CVaR **点估计**（GPD 解析公式） | 替换经验分位数，改善尾部精度 |
| `bootstrap.py::_bootstrap_tail_gpd`（已有） | 尾部分位数的 **Bootstrap 置信区间**（参数 Bootstrap） | 为 EVT 点估计提供 CI |

两者不重复——`evt_tail` 给点估计，`bootstrap` 给 CI。共享 `scipy.stats.genpareto` 底层。

### 4.2 与 `EmpiricalDistribution` 的关系

- 当前 `var()` = `quantile(alpha)` —— 纯经验分位数，线性插值
- 改造后 `var()` = EVT 外推（极端分位数）或经验分位数（非极端分位数）
- **所有现有调用方零改动自动生效**

### 4.3 与 P4 Task 1（自适应停止）的关系

两者互补但独立：
- EVT 改善尾部分位数的**准确度**（系统性偏差）
- 自适应停止改善所有估计量的**精度**（随机误差）
- 可以独立实施、独立测试、独立生效

---

## 五、外部库替代方案（参考）

> 以下内容提取自 P4 计划 §5.5，保留作为未来升级路径参考。

| 计划手写 | 当前方案 | 更专用替代 |
|---------|-------------|-----------|
| GPD 分布拟合 (MLE) | `scipy.stats.genpareto.fit()` | `pyextremes`（MCMC+L-moments）或 `QuantLite` |
| VaR / CVaR 解析公式 | 自实现（~15 行解析公式） | `QuantLite.risk.metrics`（历史/Para/Cornish-Fisher 三种 VaR + CVaR） |
| Hill 尾部指数 | 已有（`bootstrap.py`） | `QuantLite.risk.evt` 也内置 |
| 阈值选择 | 自实现稳定性检测（~30 行） | `QuantLite` 内置 |

**pyextremes vs QuantLite**：

| 维度 | pyextremes | QuantLite |
|------|-----------|-----------|
| 成熟度 | 252 stars，经典教材（Coles 2001）实现 | 2025 年新包，较新 |
| 拟合方法 | MLE + MCMC(Emcee) + 矩法 + L-moments | MLE |
| VaR/CVaR | 不直接提供（需手动从拟合分布计算） | 内置 `tail_risk_summary()` |
| Hill 估计量 | 无 | 有 |
| 推荐场景 | 经典平稳极值分析，学术严谨性优先 | EVT+风险度量一体化，工程便利性优先 |

---

## 六、验收标准

- [ ] `EmpiricalDistribution.quantile(p)` 在 p≤0.1 时自动使用 EVT 外推（`var()` 作为别名同样生效）
- [ ] `EmpiricalDistribution.cvar(0.05)` 在 N≥5000 时自动使用 EVT 外推
- [ ] EVT VaR 5% 与 50000 样本经验分位数误差 < 5%
- [ ] 5000 样本 + EVT 的 VaR 精度 ≥ 50000 样本经验分位数精度
- [ ] 非极端分位数（p=0.5）不受 EVT 影响，仍走经验分位数
- [ ] N<100 时自动回退经验分位数
- [ ] N=1000 时使用 90% 阈值（100 超额），N=20000 时使用 ≥97.5% 阈值（500 超额，自适应推高）
- [ ] 统计分析面板 VaR/CVaR 分析自动使用 EVT（无需修改 GUI 代码）
- [ ] 最差情形分析自动使用 EVT（无需修改 GUI 代码）
- [ ] GDR 统计表格 VaR 列自动使用 EVT（无需修改 GUI 代码）
- [ ] `WorstImpactAnalyzer` 资源类 GDR + `condition='success'` 时跳过 EVT（`use_evt=False`）
- [ ] `use_evt=False` 显式传入时走纯经验分位数，不触发 EVT
- [ ] 全部已有测试保持绿色

---

## 七、理论严谨性审查（2026-05-28）

> 审查范围：计划 §一~§三 全部技术决策。文献依据标注于各条目末尾。

### 7.1 理论基础：Pickands-Balkema-de Haan 定理 ✅ 无误

**定理（Balkema & de Haan 1974; Pickands 1975）**：对任何属于极值分布吸引域的分布 F，当阈值 u → x_F（右端点）时，超额分布收敛到广义 Pareto 分布（GPD）：

\[
F_u(y) = P(X - u \leq y \mid X > u) \to G(y; \sigma, \xi) = 1 - (1 + \xi y/\sigma)_{+}^{-1/\xi}
\]

**审查结论**：计划引用此定理作为 GPD 尾部拟合的理论基础是正确的。定理不要求原分布是连续的——离散分布的极值吸引域条件同样满足（Hitz et al. 2024 已扩展到离散 GPD）。抽卡模拟中资源值通常是连续或近似连续的（模拟次数足够多时），定理完全适用。

**边界条件**：
- 分布必须在某个极值吸引域中（Fréchet/Gumbel/Weibull）。几乎所有实际分布都满足，但不包括超重尾（super-heavy-tailed）分布——其 γ = +∞，不属于经典吸引域。抽卡资源值有界（不能低于 0），属于 Weibull 域（ξ < 0）或 Gumbel 域（ξ ≈ 0），**不存在超重尾问题**。
- 定理是渐近的——实践中需要足够高的阈值（§7.4 单独审查）。

*参考文献：Balkema & de Haan (1974) Ann. Probab.; Pickands (1975) Ann. Statist.; Coles (2001) Springer.*

### 7.2 VaR/CVaR 公式：存在下尾公式遗漏 🔴

#### 7.2.1 上尾（右尾）公式 ✅

计划 §2.2 给出的公式是标准的上尾 GPD 分位数公式：

\[
\text{VaR}_p = u + \frac{\beta}{\xi}\left[\left(\frac{n}{N_u}(1-p)\right)^{-\xi} - 1\right] \quad (|\xi| \geq 10^{-6})
\]
\[
\text{CVaR}_p = \text{VaR}_p + \frac{\beta + \xi(\text{VaR}_p - u)}{1-\xi} \quad (\xi < 1)
\]

其中 φ = N_u/n 是超阈值概率，p 接近 1（上分位数）。推导正确。ξ→0 指数极限 `u + β × ln(n/N_u × (1-p))` 也正确。

#### 7.2.2 下尾（左尾）公式 🔴 遗漏

计划在 §2.1 规定 p ≤ 0.1 触发 EVT，但 §2.2 只给出了上尾公式。**直接将 p = 0.05 代入上尾公式会得到错误结果**——上尾公式计算的是超过阈值的值（VaR > u），而下尾需要的是低于阈值的值（VaR < u_low）。

**正确的下尾公式**（拟合到 `u_low - X | X < u_low`，其中 u_low 是低分位数，φ = P(X < u_low)）：

\[
\text{VaR}_p = u_{\text{low}} - \frac{\beta}{\xi}\left[\left(\frac{p}{\phi}\right)^{-\xi} - 1\right]
\]
\[
\text{CVaR}_p = \text{VaR}_p - \frac{\beta + \xi(u_{\text{low}} - \text{VaR}_p)}{1-\xi}
\]

或者**使用统一的「取负」方法**（更推荐）：令 Y = -X，对 Y 的上尾拟合标准 GPD，然后：

\[
\text{VaR}_X(p) = -\text{VaR}_Y(1-p)
\]
\[
\text{CVaR}_X(p) = -\text{ES}_Y(1-p)
\]

**两种方法等价，但上尾公式不能直接用于下尾**。推荐在实现中使用统一取负法：始终对右尾拟合标准 GPD，下尾通过 Y = -X 转换后再用同一套 VaR/CVaR 公式。

#### 7.2.3 Step 2 "取负"描述纠正 🔴

计划 Step 2 原文：

> p ≤ 0.1 → 用下尾 GPD 外推（对 data ≤ 阈值的超额值拟合）
> p ≥ 0.9 → 用上尾 GPD 外推（data ≥ 阈值的超额值**取负**后拟合）

**上尾取负是错误的**。标准上尾拟合直接对 `X - u | X > u` 拟合 GPD，不需要取负。取负后得到负值，GPD 定义域为 [0, ∞)，无法拟合。

**正确的统一描述**应为：
- **上尾（p ≥ 0.9）**：对 `X - u_upper | X > u_upper` 直接拟合 GPD（标准 POT）
- **下尾（p ≤ 0.1）**：对 `Y = -X` 取负，然后对 `Y - u_Y | Y > u_Y` 拟合标准 GPD，结果取负回原尺度。等价于对 `u_low - X | X < u_low` 拟合 GPD

*参考文献：McNeil (1999) Extremes; McNeil & Frey (2000) J. Empir. Finance; Embrechts, Klüppelberg & Mikosch (1997) Springer.*

### 7.3 MLE 拟合的正则性条件 🟡

#### 7.3.1 ξ > -0.5 条件

**Smith (1985)** 证明 GPD 的 MLE 在 ξ > -0.5 时满足标准正则性条件（一致性、渐近正态性）；在 ξ ∈ [-1, -0.5) 时 MLE 存在但不满足标准渐近理论；在 ξ < -1 时 MLE 不存在。

计划使用 `scipy.stats.genpareto.fit()`（MLE），但对 ξ < -0.5 的情况没有检查。在抽卡模拟中，资源值通常有下界（0）和上界（初始资源量），ξ 很可能为负（Weibull 域）。如果 ξ 落在 [-1, -0.5) 区间，scipy 可能返回「成功」拟合但渐近性质不成立。

**建议**：拟合后检查 ξ，若 ξ < -0.5 记录警告日志（不阻塞，因为点估计仍可能有用，但标准误不可靠）；若 ξ < -1 强制回退经验分位数。

#### 7.3.2 超额样本数下限

Hosking & Wallis (1987) 推荐 MLE 拟合至少 20-30 个超额样本。McNeil & Frey (2000) 推荐 80-100 个超额样本以获得稳定 MSE。

计划的自适应阈值确保 100-500 个超额样本，**远超最低建议**，且计划规定 < 10 回退。下限 10 偏保守（文献建议 20-30），但 N<100 时触发总体回退经验分位数，下尾实际不会被触及，**实际上不会有问题**。

*参考文献：Smith (1985) Biometrika 72(1):67-90; Hosking & Wallis (1987) Technometrics 29(3):339-349.*

### 7.4 阈值选择方法 🟢

#### 7.4.1 自适应分位数阈值

计划使用 `target_exc = min(max(n × 0.05, 100), 500)` 确定阈值分位点（5% 基线 + 100–500 约束）。这在文献中是**常见且合理的实用方法**：

| 样本量 n | 阈值分位点 | 超额数 | 文献对照 |
|----------|-----------|--------|---------|
| 1,000 | 90% | 100 | McNeil & Frey (2000): 90% 阈值常见；100 下限兜底 |
| 5,000 | 95% | 250 | Coles (2001): 阈值尽可能高；Scarrott & MacDonald (2012) 综述确认 |
| 20,000+ | 97.5%+ | 500（上限） | Benito et al. (2023): 98-99% 用于市场风险 |

#### 7.4.2 与诊断方法的差距

理论上更优的阈值选择方法是**诊断图法**（Coles 2001, §4.3.4）：
- **均值剩余寿命图（MRL Plot）**：寻找均值超额函数开始线性的最低阈值
- **参数稳定性图（Stability Plot）**：寻找 ξ 和修正尺度参数 σ* 开始稳定的最低阈值

计划将 `gpd_threshold_stability` 降级为「可选诊断工具」是合理的——诊断图法需要人工判断，不适合自动化。自适应分位数阈值在工程上足够，但应在文档中注明这是**工程近似**而非理论最优。

**建议**：保留自适应分位数作为默认，将稳定性检测作为可选诊断函数，供有经验的用户在交互式环境（如 Jupyter）中手动检查。

*参考文献：Coles (2001) §4.3.4; Scarrott & MacDonald (2012) J. Stat. Softw. 53(6).*

### 7.5 GPD 有界支撑（ξ < 0）的上端点约束 🟡

当 ξ < 0 时，GPD 有有限上端点 `x_F = u - β/ξ`（在原始数据尺度上 `x_F = u + (-β/ξ)` 因为是右尾拟合，但下尾取负后要变换）。外推到超过端点的分位数在物理上不可能。

计划没有提及此约束。在抽卡场景中，如果拟合出 ξ < 0（有界分布），外推的 VaR 不应超过 GPD 的隐含上/下界。**对于 VaR（而非超样本极值外推），只要阈值选择和拟合正常，VaR 通常不会超过端点**——但如果 p 非常极端且 ξ 接近 0，可能出现边界问题。

**建议**：在 `evt_var` 中检查外推结果是否超过端点，若超过则返回 None 触发回退。

*参考文献：Coles (2001) p.75-77.*

### 7.6 条件分布上使用 EVT 的正当性 ✅

计划在条件分布（如 GDR 成功/失败分组后的资源分布）上使用 EVT。理论审查确认：

**正当**：Pickands-Balkema-de Haan 定理对任何属于极值吸引域的分布 F 都成立，不关心 F 是如何得到的（无条件、条件、混合……）。只要条件分布足够光滑（属于某个极值吸引域），EVT 就适用。

**前提条件**：
- 分组后每组样本数足够（满足超额样本下限）。计划 n ≥ 100 才触发 EVT，在最差分组（~50 个样本）时自动回退。
- 条件是外生变量（GDR 指标）而非被分位数化的变量本身。§2.1.1 的方案 B 正确排除了同变量截断场景。

**与已有文献的对齐**：条件 EVT 是成熟领域——McNeil & Frey (2000) 在 GARCH 残差上用 EVT、Chavez-Demoulin et al. (2005) 使用时变参数 GPD，均证明了条件分布上 EVT 的有效性。

*参考文献：McNeil & Frey (2000); Chavez-Demoulin et al. (2005) J. Econometrics.*

### 7.7 Bootstrap CI 用于 GPD 分位数的覆盖率不足 🟡

计划 §三 Step 3 提到「参数 Bootstrap CI 可利用同一 GPD 拟合结果」。但文献审查发现：

**Tajvidi (2003)** 通过模拟研究证明参数 Bootstrap 对 GPD 分位数的置信区间**系统性覆盖率不足**，尤其在小样本和 ξ < 0 时。问题根源在于：
- Bootstrap 重抽样可能产生物理上不可能的 GPD 参数（例如隐含上端点小于观测最大值）
- 约 10% 的 Bootstrap 样本产生不可行估计值（Cross Validated 社区验证）

**文献推荐的替代方案**：
1. **Profile likelihood CI**（Tajvidi 2003）：覆盖率优于 Bootstrap，自然避开边界问题
2. **Bartlett-corrected profile likelihood**（Tajvidi 2003）：进一步改善小样本覆盖率
3. **GPD safeprofile 混合法**（Pasche & Engelke 2024）：profile likelihood 失败时回退 Bootstrap

**对计划的影响**：
- P24 的 EVT 点估计本身不受此问题影响（仅影响 CI）
- P18c 的 VaR CI（当前显示「待实现，等 P4 EVT」）在接入 GPD 参数 Bootstrap 前，应评估是否改用 profile likelihood 或至少对 Bootstrap 结果做可行性过滤

**建议**：P24 的 VaR/CVaR 点估计照常实施（不受影响）。VaR CI 方案单独评审——若使用参数 Bootstrap，需加可行性过滤（丢弃不可行样本+警告）；若覆盖率要求严格，考虑后续实施 profile likelihood。

*参考文献：Tajvidi (2003) Extremes 6(2):111-123; Pasche & Engelke (2024) arXiv:2505.08578.*

### 7.8 审查总结

| # | 问题 | 严重度 | 应修复阶段 | 修复方式 |
|---|------|--------|-----------|---------|
| 1 | §2.2 仅含上尾 VaR/CVaR 公式，下尾公式遗漏 | 🔴 关键 | **实施前** | 采用统一取负法：下尾 Y=-X → 标准上尾公式 → 结果取负；或补全下尾独立公式 |
| 2 | Step 2 "上尾取负"描述错误——上尾不需取负 | 🔴 关键 | **实施前** | 修正描述：上尾直接拟合 X-u\|X>u，下尾取负 Y=-X 后标准拟合 |
| 3 | MLE 正则性 ξ > -0.5 未检查 | 🟡 重要 | 实施中 | 拟合后检查 ξ；ξ < -0.5 警告；ξ < -1 强制回退 |
| 4 | 参数 Bootstrap CI 对 GPD 分位数覆盖不足 | 🟡 重要 | 后续（P18c） | P24 点估计不受影响；VaR CI 方案单独评审 |
| 5 | ξ < 0 有界支撑端点约束 | 🟡 重要 | 实施中 | `evt_var` 中检查外推是否越界，越界则返回 None |
| 6 | 阈值选择缺少诊断方法 | 🟢 次要 | 后续增强 | 保留自适应分位数默认，诊断函数作为可选工具 |
| 7 | Pickands-Balkema-de Haan 定理基础 | ✅ 正确 | — | 无需修改 |
| 8 | 条件分布 EVT 正当性 | ✅ 正确 | — | 无需修改 |
| 9 | 自适应阈值范围 | ✅ 正确 | — | 100-500 超额远超文献建议下限 |
| 10 | ξ→0 极限处理 | ✅ 正确 | — | 无需修改 |
| 11 | ξ ≥ 1 → CVaR=inf | ✅ 正确 | — | 无需修改 |

---

## 更新记录

| 日期 | 变更 |
|------|------|
| 2026-05-28 | 从 `docs/自适应模拟与方差缩减计划.md` 提取，新增 `EmpiricalDistribution` 集成设计 + QuantLite 重新评估 |
| 2026-05-28 | v3：补全三处技术细节——ξ→0 指数极限、`genpareto.fit()` 异常处理、上尾/下尾独立缓存；自适应阈值替代固定 90% 分位数（n 越大阈值越高，保证超额样本 100–500）；撤回大样本自动退出（理论依据不足——应推高阈值而非关 EVT） |
| 2026-05-28 | v4：理论严谨性审查——新增 §七。发现 2 个关键问题（下尾公式遗漏、上尾取负描述错误）、3 个重要问题（MLE 正则性、Bootstrap CI 覆盖率、有界支撑端点）、2 个次要建议（阈值诊断方法）。计划其余部分（定理基础、条件 EVT、自适应阈值、ξ→0 极限、ξ≥1 处理）均正确无误 |
