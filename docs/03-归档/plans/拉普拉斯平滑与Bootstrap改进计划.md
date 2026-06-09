# ⛔ 已废弃 —— 拉普拉斯平滑与 Bootstrap 改进计划

> **此文件已于 2026-05-26 废弃。** 内容已拆分迁移至：
> - `docs/小样本概率估计改进计划.md` —— §一 小样本概率估计改进（Wilson 得分区间）
> - `docs/Bootstrap稳定性分析改进计划.md` —— §二 Bootstrap 引擎修复 + §三 Bootstrap UI 集成
>
> 本文件仅保留用于历史回溯，**不再作为实施依据**。请以迁移后的两个新文件为准。

> 创建日期：2026-05-26（已废弃）
> 来源：P12-Phase1.5 大任务收尾讨论中发现的理论短板
> 状态：❌ 废弃——内容已迁移

---

## 背景

第三轮 P12-Phase1.5 完成后，审查发现两项已有实现存在理论缺陷，需单独修复：

1. **拉普拉斯平滑偏高**：过程分析（P2）中 `compute_ab()` / `compute_ba()` 使用 Beta(1,1) 先验，小样本 + 低概率场景下严重偏高
2. **Bootstrap 引擎（P3）已知问题**：Jackknife 截断、厚尾检测未自动采纳、无 UI 集成

---

## 一、小样本概率估计改进 → `process_analysis.py`

### 问题

当前 Laplace-Bayes 估计 `(count + 1) / (total + 2)` 基于 Beta(1,1) 先验（均匀分布）。在 `total_in_pattern = 5`、真实概率 0.001 时：

| 方法 | 公式 | N=5, 0成功 | 误差（真值 0.001） |
|------|------|-----------|-------------------|
| MLE | count / total | 0.000 | ~0 |
| Beta(1,1)（当前） | (c+1)/(t+2) | 0.143 | **143x** |
| Beta(0.5,0.5)（Jeffreys） | (c+0.5)/(t+1) | 0.083 | **83x** |
| Beta(0.1,0.1) | (c+0.1)/(t+0.2) | 0.019 | 19x |

核心结论：**小样本 + 极端概率 = 信息本身不足，任何平滑方法都不可靠。** Jeffreys prior 只是把偏差从 143x 降到 83x，没有解决问题。正确的做法不是换先验，而是诚实地展示不确定性。

### 方案：Wilson 得分区间 + 小样本计数回退

**不修正点估计，而是用 Wilson score interval 替代它**。Wilson 区间在极端概率和小样本下的覆盖率远优于其他方法（Brown, Cai & DasGupta 2001）：

$$\text{CI} = \frac{\hat{p} + \frac{z^2}{2n} \pm z\sqrt{\frac{\hat{p}(1-\hat{p})}{n} + \frac{z^2}{4n^2}}}{1 + \frac{z^2}{n}}$$

其中 z = 1.96（95% CI）。

| 方法 | N=5, 0成功 | N=5, 5成功 | N=100, 50成功 |
|------|-----------|-----------|--------------|
| MLE | 0.000 | 1.000 | 0.500 |
| Beta(0.5,0.5) | 0.083 | 0.917 | 0.500 |
| **Wilson 95% CI** | **[0.000, 0.434]** | **[0.566, 1.000]** | **[0.404, 0.596]** |

Wilson 区间的优势：
- 不需要选先验参数——不存在"偏还是不偏"的争论
- 小 N 时自动变宽——诚实地反映不确定性
- 大 N 时自动收敛到很窄的区间——不影响正常使用
- 即使在 N=0 也有效（返回 [0, 1]）

### 小样本阈值

| N | 处理方式 |
|---|---------|
| **< 5** | `low_sample=True`：不显示概率，直接显示原始计数 `"0/5"`，行灰显 + tooltip `"样本不足（N<5），不显示概率估计"` |
| **≥ 5** | 正常显示 Wilson 95% CI：`0.00 [0.00, 0.43]` |

选择 N=5 的理由：N<5 时 Wilson 区间虽数学上有效但过宽（N=1 时始终 [0, 1]），展示出来无信息量，不如直接展示原始计数。

### 改动范围

| 文件 | 改动 |
|------|------|
| `core/process_analysis.py` | 删除 `laplace_success_prob` / `p_laplace_s` / `p_laplace_f`（三个字段全部移除）；新增 `wilson_ci_lower` / `wilson_ci_upper` |
| `gui/process_analysis_panel.py` | `low_sample=True` 行灰显 + 显示原始计数替代概率；正常行显示 `"0.50 [0.40, 0.60]"` 格式 |

### 风险

- 删除 `laplace_success_prob` 等字段是**破坏性变更**——需确认无其他模块引用（当前仅 GUI 面板读取，无外部依赖）
- Wilson CI 公式涉及浮点平方根，对极大 N 数值稳定（`z²/(4n²)` 不会下溢）
- 所有现有测试预期值需更新（概率字段变更）

---

## 二、Bootstrap 引擎已知问题修复 → `bootstrap.py`

### 问题 1：Jackknife 上限 1000 截断

**现状**（line 91）：`for i in range(min(n, 1000))`

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

### 问题 2：厚尾检测未自动采纳

**现状**：`detect_heavy_tail()` 返回 `{alpha, heavy_tail, recommendation}`，但 `bootstrap_mean()` / `bootstrap_quantile()` 不自动调用它。面板需要主动检查——当前无面板集成，形同虚设。

**方案**：在 `bootstrap_mean()` 中增加 `auto_heavy_tail=True` 参数。开启时：
1. 自动调用 `hill_estimator()`
2. α < 2 时自动切换到 GPD-param Bootstrap（`_bootstrap_tail_gpd` 逻辑泛化为均值场景）
3. 在 `BootstrapResult.method` 中标注 `'GPD-param (auto: heavy tail detected α={:.2f})'`

实现细节：将 `_bootstrap_tail_gpd` 泛化为接受任意统计量函数，而非仅分位数。

### 问题 3：BCa 在小 n 时不稳定

**现状**：BCa 在 `use_bca=True` 时无条件尝试，失败回退百分位法。但 Jackknife 加速因子 a 在 n < 30 时方差极大（分母 `sum(jk_dev²)^1.5` 极不稳定）。

**方案**：n < 50 时自动使用百分位法（不尝试 BCa），在 `BootstrapResult.method` 中标注 `'percentile (n<50, BCa unstable)'`。

### 改动范围

| 文件 | 改动 |
|------|------|
| `core/bootstrap.py` | Jackknife 随机抽样、auto_heavy_tail 参数、n<50 跳过 BCa |

---

## 三、Bootstrap UI 集成 → `gui/`

### 与原始 Bootstrap 计划的关系

本方案是 [Bootstrap 稳定性分析实施计划](superpowers/plans/2026-05-18-bootstrap-stability-analysis.md) 中阶段 2~7（6 个面板 UI 集成）的 **MVP 子集**。原始计划覆盖 6 个面板的表格 CI + 图表 CI（阴影带/误差棒），本方案仅取其阶段 2（process_analysis_panel）和阶段 3（analysis_panel）的**表格 CI 部分**，作为快速交付的起步方案。

**以本方案为准执行**，原始计划中未被本方案覆盖的其余面板（strategy/resource_search/retreat/worst_impact）和图表 CI（误差棒/阴影带）作为后续扩展，优先级低，暂不实施。

### 现状

`BootstrapEngine` 是纯核心模块，零 GUI 集成。面板中的均值/中位数/分位数展示均无置信区间。

### 方案（MVP）

在 `analysis_panel.py` 的统计汇总表格中，对关键指标（成功率、均值、中位数）追加 Bootstrap 95% CI 列：

```
指标            | 点估计    | 95% CI
成功率          | 0.723    | [0.695, 0.751]
平均抽数        | 311.2    | [309.1, 313.5]
```

实现：
1. 面板 Worker 在模拟完成后调用 `BootstrapEngine` 计算 CI
2. `BootstrapResult.format_ci()` 已就绪，直接格式化输出
3. CI 列仅在有 ≥100 个有效样本时显示（<100 时显示"样本不足"）

### 改动范围

| 文件 | 改动 |
|------|------|
| `gui/analysis_panel.py` | 表格新增 CI 列，调用 BootstrapEngine |
| `gui/process_analysis_panel.py` | low_sample 行灰显 + tooltip |

### 暂不实施

- 独立 Bootstrap 面板（需新 Tab + 完整 UI，工作量大，优先级低）
- 分位数 Bootstrap CI（仅在需要 VaR 时有用，当前无需求）

---

## 实施顺序

```
1. Wilson 得分区间替换 Laplace 平滑（<2h）→ 删除旧字段 + 新增 CI 字段 → 更新测试
    ↓
2. Bootstrap 已知问题修复（<2h）→ 更新测试
    ↓
3. Bootstrap UI 集成（<3h）
```

三项独立可并行，但建议按序推进以逐步验证。

---

## 更新记录

| 日期 | 变更 |
|------|------|
| 2026-05-26 | 初版 |
