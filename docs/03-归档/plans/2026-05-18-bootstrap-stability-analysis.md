# ⛔ 已废弃 —— Bootstrap 稳定性分析实施计划

> **此文件已于 2026-05-26 废弃。** 内容已合并至：
> - `docs/Bootstrap稳定性分析改进计划.md` —— 合并了本文件的全部内容 + `docs/拉普拉斯平滑与Bootstrap改进计划.md` 的 Bootstrap 相关部分，并重新审视了 UI 方案
>
> 本文件仅保留用于历史回溯，**不再作为实施依据**。请以迁移后的新文件为准。

> 日期：2026-05-18 | 修订：v3（阶段一核心完成，2026-05-26）| **v4（废弃，2026-05-26）**
> 状态：❌ 废弃——内容已合并至 `docs/Bootstrap稳定性分析改进计划.md`

---

## 一、核心原理

Bootstrap 不是重新跑模拟，而是对已有的 N 条模拟结果做有放回抽样（纯数组操作），从 B 次重抽样中估计统计量的分布，从而得到置信区间。**零额外模拟成本，零额外内存。**

---

## 二、测试策略

| 阶段 | 测试方式 | 测试文件 |
|------|---------|---------|
| 阶段1 BootstrapEngine | **TDD**——每个方法先写失败测试 | `tests/core/test_bootstrap.py`（新建） |
| 阶段2-7 面板集成 | 手动目视 + 现有测试套件保持绿色 | 各面板的现有测试 |

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

---

## 五、阶段1：BootstrapEngine 核心类（TDD）

> **阶段1 分为 8 个子任务，每个遵循 TDD：写失败测试 → 最小实现 → 通过。**

- [x] **1.1: BootstrapResult 数据类**

**新建：** `gacha_simulator/core/bootstrap.py`
**新建：** `tests/core/test_bootstrap.py`

```python
# 测试
def test_bootstrap_result_creation():
    result = BootstrapResult(point_estimate=0.95, ci_lower=0.92, ci_upper=0.97, bootstrap_std=0.012)
    assert result.point_estimate == 0.95
    assert result.ci_lower == 0.92

def test_bootstrap_result_format_string():
    result = BootstrapResult(0.95, 0.92, 0.97, 0.012)
    formatted = f"{result.point_estimate:.2f} [{result.ci_lower:.2f}, {result.ci_upper:.2f}]"
    assert formatted == "0.95 [0.92, 0.97]"
```

实现：

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

```python
def test_resample_indices_shape():
    indices = BootstrapEngine._resample_indices(n=100, B=1000, rng=np.random.default_rng(42))
    assert indices.shape == (1000, 100)

def test_resample_indices_values_in_range():
    indices = BootstrapEngine._resample_indices(n=50, B=100, rng=np.random.default_rng(42))
    assert indices.min() >= 0
    assert indices.max() < 50
```

- [x] **1.3: bootstrap_probability() — 二分类概率**

测试：已知成功/失败数组 → 验证 CI 包含点估计。

```python
def test_bootstrap_probability_balanced():
    engine = BootstrapEngine(B=200, ci_level=0.95, random_seed=42)
    data = [True] * 50 + [False] * 50  # p=0.5
    result = engine.bootstrap_probability(data)
    assert result.point_estimate == pytest.approx(0.5)
    assert 0 < result.ci_lower < result.ci_upper < 1

def test_bootstrap_probability_all_success():
    engine = BootstrapEngine(B=200, random_seed=42)
    data = [True] * 100  # p=1.0
    result = engine.bootstrap_probability(data)
    assert result.point_estimate == 1.0
```

- [x] **1.4: _compute_bca_correction()**

测试：用已知偏态的 Bootstrap 样本验证 BCa CI 比百分位法更准确。

```python
def test_bca_more_accurate_than_percentile():
    """对偏态分布，BCa CI 应比百分位法更窄且覆盖真实值"""
    # 构造有偏的 bootstrap 样本
    rng = np.random.default_rng(42)
    n, B = 100, 1000
    data = np.random.exponential(scale=1.0, size=n)
    point_est = np.mean(data)
    
    # Bootstrap
    bootstrap_means = np.array([np.mean(rng.choice(data, size=n, replace=True)) for _ in range(B)])
    
    # 百分位法
    ci_percentile = np.percentile(bootstrap_means, [2.5, 97.5])
    
    # BCa（如果实现正确，应对偏态有校正）
    # 验证 BCa 校正系数被正确计算
    ...
```

- [x] **1.5: bootstrap_distribution() — 连续分布分位数**

测试：正态分布样本 → 验证中位数 CI 包含真实值。

```python
def test_bootstrap_distribution_median():
    engine = BootstrapEngine(B=200, random_seed=42)
    rng = np.random.default_rng(42)
    data = rng.normal(loc=10, scale=2, size=500)
    results = engine.bootstrap_distribution(data, quantiles=[0.5])
    assert 9 < results[0.5].point_estimate < 11
    assert results[0.5].ci_lower < results[0.5].point_estimate < results[0.5].ci_upper
```

- [x] **1.6: detect_heavy_tail() — Hill 估计量**

测试：正态分布（α=∞）→ 非厚尾；Pareto(α=1.5) → 厚尾。

```python
def test_detect_heavy_tail_normal():
    rng = np.random.default_rng(42)
    data = rng.normal(size=1000)
    is_heavy, alpha = BootstrapEngine.detect_heavy_tail(data)
    assert not is_heavy

def test_detect_heavy_tail_pareto():
    rng = np.random.default_rng(42)
    data = (rng.pareto(a=1.5, size=1000) + 1) * 100
    is_heavy, alpha = BootstrapEngine.detect_heavy_tail(data)
    assert is_heavy or alpha < 3
```

- [x] **1.7: total_variation_distance()**

```python
def test_tvd_identical_distributions():
    p = {'a': 0.5, 'b': 0.3, 'c': 0.2}
    assert BootstrapEngine.total_variation_distance(p, p) == pytest.approx(0.0)

def test_tvd_completely_different():
    p = {'a': 1.0, 'b': 0.0}
    q = {'a': 0.0, 'b': 1.0}
    assert BootstrapEngine.total_variation_distance(p, q) == pytest.approx(1.0)

def test_tvd_partial_overlap():
    p = {'a': 0.6, 'b': 0.4}
    q = {'a': 0.4, 'b': 0.6}
    assert BootstrapEngine.total_variation_distance(p, q) == pytest.approx(0.2)
```

- [x] **1.8: 运行阶段1全部测试并提交**

```bash
pytest tests/core/test_bootstrap.py -v
# 预期: 全部 PASS
```

```bash
git add gacha_simulator/core/bootstrap.py tests/core/test_bootstrap.py
git commit -m "feat: BootstrapEngine 核心类——概率/分布/TVD Bootstrap + BCa校正 + 厚尾检测"
```

---

> **⚠ 2026-05-26 更新**：阶段 2~7 的 UI 集成已拆分为独立 MVP 计划 [`docs/拉普拉斯平滑与Bootstrap改进计划.md`](../../拉普拉斯平滑与Bootstrap改进计划.md) §三。MVP 仅覆盖阶段 2（process_analysis_panel）和阶段 3（analysis_panel）的**表格 CI 部分**，其余面板和图表 CI 作为后续扩展。**UI 集成的当前执行标准以该 MVP 计划为准。**

## 六、阶段2：process_analysis_panel 添加 Bootstrap（优先）

**文件：** `gacha_simulator/gui/process_analysis_panel.py`

- [ ] **2.1: 在 BootstrapEngine 中实现 bootstrap_aa()**

测试：构造最小 `process_data`（3条轨迹），验证 AA 概率的 CI 覆盖点估计。

- [ ] **2.2: 实现 bootstrap_bb()**

- [ ] **2.3: 实现 bootstrap_ab()**

- [ ] **2.4: 实现 bootstrap_ba()**

- [ ] **2.5: 四个 Tab 各添加「计算稳定性」按钮**

按钮调用对应 Bootstrap 方法 → 修改表格显示格式为 `0.95 [0.92, 0.98]`。

- [ ] **2.6: 目视验证 + 提交**

启动 GUI → 过程分析 Tab → 执行分析 → 点击「计算稳定性」→ 确认 CI 显示合理。

---

## 七、阶段3：analysis_panel 添加 Bootstrap

**文件：** `gacha_simulator/gui/analysis_panel.py`

- [ ] **3.1: 添加「计算稳定性」按钮**
- [ ] **3.2: GDR 分布分位数添加 CI**
- [ ] **3.3: 各池成功率添加 CI**
- [ ] **3.4: 图表添加误差棒（柱状图）/ 阴影带（趋势图）**
- [ ] **3.5: 目视验证 + 提交**

---

## 八、阶段4：strategy_panel 添加 Bootstrap（需小改数据保存）

**文件：** `gacha_simulator/gui/strategy_panel.py`

- [ ] **4.1: ForwardStep/BackwardStep 添加 `success_flags: List[bool]` 字段**
- [ ] **4.2: 修改前进法/后退法——每步保存个体成功/失败结果**
- [ ] **4.3: 添加「计算稳定性」按钮**
- [ ] **4.4: 趋势图添加阴影带（Bootstrap CI）**
- [ ] **4.5: 目视验证 + 提交**

---

## 九、阶段5：resource_search_panel 添加 Bootstrap（需小改）

**文件：** `gacha_simulator/gui/resource_search_panel.py`

- [ ] **5.1: 步骤数据类添加 `success_flags: List[bool]`**
- [ ] **5.2: 修改 `_simulate_with_resource`——返回个体结果**
- [ ] **5.3: 添加「计算稳定性」按钮**
- [ ] **5.4: 成功率-资源曲线添加阴影带**
- [ ] **5.5: 目视验证 + 提交**

---

## 十、阶段6：retreat_panel 添加 Bootstrap

**文件：** `gacha_simulator/gui/retreat_panel.py`

- [ ] **6.1: 实现 `bootstrap_conditional_quantile()`**
- [ ] **6.2: 添加「计算稳定性」按钮**
- [ ] **6.3: 核密度回归曲线添加阴影带**
- [ ] **6.4: 资源不足概率显示 CI**
- [ ] **6.5: 目视验证 + 提交**

---

## 十一、阶段7：worst_impact_panel 添加 Bootstrap

**文件：** `gacha_simulator/gui/worst_impact_panel.py`

- [ ] **7.1: 保守资源（条件分位数）添加 CI**
- [ ] **7.2: 大保底覆盖倍数 CI 从保守资源 CI 派生**
- [ ] **7.3: 新池子数分布添加 Bootstrap（需小改保存 `pool_success_counts`）**
- [ ] **7.4: 目视验证 + 提交**

---

## 十二、验收标准

- [ ] BootstrapEngine 核心类所有方法通过 TDD 测试
- [ ] process_analysis_panel AA/BB/AB/BA 所有表格显示 CI（`0.95 [0.92, 0.98]` 格式）
- [ ] analysis_panel GDR 分布、各池成功率显示 CI
- [ ] strategy_panel 成功率趋势图显示阴影带
- [ ] resource_search_panel 成功率-资源曲线显示阴影带
- [ ] retreat_panel 条件分布、核密度回归、资源不足概率显示 CI
- [ ] worst_impact_panel 保守资源显示 CI
- [ ] 性能：N=10000、B=1000 时，单次 Bootstrap 计算 < 5 秒
- [ ] 全部已有测试保持绿色

---

## 十三、与其他计划的兼容性

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

### 与 P4 Task 2（对偶变量法）的关系

对偶变量法将 N 次模拟配对。朴素 Bootstrap 打破配对 → CI 偏宽。P3 支持 `paired=True`——重抽样 N/2 对而非 N 个个体。

### 建议执行顺序

```
P2 (过程分析续) → P3 (Bootstrap) → P4 (自适应+EVT)
```
