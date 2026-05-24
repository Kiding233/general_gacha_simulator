# 自适应模拟次数与方差缩减实施计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现自适应精度模式（实时 RSE 监控→自动停止）+ 对偶变量法（配对模拟降低方差）+ EVT 尾部拟合（GPD 改善 VaR/CVaR 精度），三项技术互补且可独立实现。

**Architecture:** 新建 `core/adaptive.py`（`AdaptiveSimController`）和 `core/evt_tail.py`（GPD 拟合 + VaR/CVaR 解析计算），修改 `service/batch_simulator.py`（`stop_condition` 回调 + `antithetic` 配对）和 `gui/gacha_panel.py`（自适应 UI + 对偶变量复选框），修改 `gui/analysis_panel.py`（EVT VaR/CVaR 替换经验分位数）。

**Tech Stack:** Python 3.10+, numpy, pytest, PyQt6

> 日期：2026-05-16 | 修订：v2（TDD + bite-sized 重写，2026-05-24）
> 状态：未开始
> 依赖：流式重构（已完成）的 `on_result` 回调 + `SharedResultCollector`

---

## 一、测试策略

| 阶段 | 测试方式 | 测试文件 |
|------|---------|---------|
| Task 1 AdaptiveSimController | **TDD**——每个方法先写失败测试 | `tests/core/test_adaptive.py`（新建） |
| Task 2 对偶变量法 | 核心配对逻辑 TDD + GUI 手动目视 | `tests/service/test_batch_service.py`（扩展现有） |
| Task 3 EVT 尾部拟合 | **TDD**——每个函数先写失败测试 | `tests/core/test_evt_tail.py`（新建） |
| 全部 UI 集成 | 手动目视 + 现有测试套件保持绿色 | — |

**TDD 覆盖目标：**
- `AdaptiveSimController.on_result()` / `_check_convergence()` / `should_stop()` / `get_status()`
- `compute_paired_seed()` — 对偶种子计算
- `fit_gpd_tail()` / `gpd_mle_fit()` — GPD 拟合
- `evt_var()` / `evt_cvar()` — EVT 分位数
- `auto_threshold()` — 平均超额图法自动阈值

---

## 二、理论基础（保留自设计文档，指导实现决策）

### 2.1 蒙特卡洛精度定律

```
SE = σ / √N
RSE = SE / |θ̂| = σ / (|θ̂| × √N)
要达到目标 RSE < ε，所需样本量：N ≥ (σ / (ε × |θ̂|))²
```

### 2.2 不同估计量的精度特征

**概率估计（伯努利）**：`SE = √(p(1-p)/N)`，`RSE = √((1-p)/(N×p))`

| p | N=1,000 RSE | N=10,000 RSE | N=100,000 RSE |
|---|------------|-------------|--------------|
| 0.5 | 3.2% | 1.0% | 0.32% |
| 0.9 | 1.1% | 0.33% | 0.11% |
| 0.99 | 3.2% | 1.0% | 0.32% |

**分位数估计**：`SE(x_p) ≈ √(p(1-p)) / (f(x_p) × √N)`。5% VaR 的标准误是中位数的 ~28 倍。

**稀有事件**：概率 q 的事件，要观察到 ≥k 次需 `N ≥ k/q`。

### 2.3 方差缩减技术评估（5 种，实现 2 种）

| 技术 | 实现复杂度 | 适用场景 | 收益 | 决策 |
|------|----------|---------|------|------|
| 重要抽样（IS） | 高 | 极低成功率 <1% | 极高（10-1000x） | **暂不实现**，未来按需 |
| **对偶变量法** | 低 | GDR 均值估计 | 中（1.2-2x） | ✅ **Task 2 实现** |
| 控制变量法 | 中 | 需要理论期望 | 中 | **暂不实现**，理论推导成本高 |
| 分层抽样法 | 中 | 不适用 | — | **不实现** |
| **EVT 尾部拟合** | 中 | VaR/CVaR | 高（10x 尾部精度） | ✅ **Task 3 实现** |

---

## 三、Task 1：自适应停止机制（TDD + UI 集成）

> **核心类 `AdaptiveSimController` → TDD；GUI 集成 → 手动目视**

### 3.1 新建测试文件

**新建：** `tests/core/test_adaptive.py`

- [ ] **1.1: test_adaptive_controller_init()**

```python
def test_adaptive_controller_init():
    controller = AdaptiveSimController(
        target_rse=0.05, min_samples=1000, max_samples=100000,
        check_interval=500, gdr_keys=['target_achievement'],
        target_specs={'char_a': 1}
    )
    assert controller._target_rse == 0.05
    assert controller._min_samples == 1000
    assert controller._max_samples == 100000
    assert controller._converged is False
    assert controller._n_done == 0
```

- [ ] **1.2: test_on_result_appends_values()**

```python
def test_on_result_appends_values():
    controller = AdaptiveSimController(
        target_rse=0.05, min_samples=10, max_samples=1000,
        check_interval=5, gdr_keys=['target_achievement'],
        target_specs={'char_a': 1}
    )
    # 构造最小 compact（仅含 card_counts 字段，compute_gdr_from_compact 所需）
    compact = {'card_counts': {'char_a': 1}, 'total_consumed': {}}
    controller.on_result(compact)
    assert controller._n_done == 1
    assert len(controller._values['target_achievement']) == 1
```

- [ ] **1.3: test_check_convergence_not_enough_samples()**

```python
def test_check_convergence_not_enough_samples():
    controller = AdaptiveSimController(
        target_rse=0.05, min_samples=100, max_samples=1000,
        check_interval=10, gdr_keys=['target_achievement'],
        target_specs={'char_a': 1}
    )
    # 只加 50 个样本（< min_samples=100），不应触发收敛检查
    for _ in range(50):
        controller._values['target_achievement'].append(1.0)
    controller._n_done = 50
    controller._check_convergence()
    assert controller._converged is False
```

- [ ] **1.4: test_check_convergence_below_target()**

```python
def test_check_convergence_below_target():
    import numpy as np
    controller = AdaptiveSimController(
        target_rse=0.10, min_samples=30, max_samples=1000,
        check_interval=10, gdr_keys=['target_achievement'],
        target_specs={'char_a': 1}
    )
    rng = np.random.default_rng(42)
    # 生成低方差数据（均值≈0.95，σ≈0.02 → RSE≈0.02/0.95/√100≈0.002，远低于 10%）
    values = rng.normal(loc=0.95, scale=0.02, size=100).tolist()
    controller._values['target_achievement'] = values
    controller._n_done = 100
    controller._check_convergence()
    assert controller._converged is True
    assert controller._worst_rse < 0.10
```

- [ ] **1.5: test_should_stop_converged()**

```python
def test_should_stop_converged():
    controller = AdaptiveSimController(
        target_rse=0.05, min_samples=10, max_samples=1000,
        check_interval=5, gdr_keys=['target_achievement'],
        target_specs={'char_a': 1}
    )
    controller._converged = True
    assert controller.should_stop() is True
```

- [ ] **1.6: test_should_stop_max_samples()**

```python
def test_should_stop_max_samples():
    controller = AdaptiveSimController(
        target_rse=0.05, min_samples=10, max_samples=100,
        check_interval=5, gdr_keys=['target_achievement'],
        target_specs={'char_a': 1}
    )
    controller._n_done = 100
    assert controller.should_stop() is True
```

- [ ] **1.7: test_get_status()**

```python
def test_get_status():
    controller = AdaptiveSimController(
        target_rse=0.05, min_samples=100, max_samples=1000,
        check_interval=10, gdr_keys=['target_achievement'],
        target_specs={'char_a': 1}
    )
    controller._n_done = 500
    controller._worst_rse = 0.032
    controller._worst_key = 'target_achievement'
    status = controller.get_status()
    assert status['n_done'] == 500
    assert status['worst_rse'] == 0.032
    assert status['worst_key'] == 'target_achievement'
    assert status['target_rse'] == 0.05
```

- [ ] **1.8: 运行 Task 1 测试确认全部 RED**

```bash
pytest tests/core/test_adaptive.py -v
# 预期: 7 failed（类不存在）
```

### 3.2 实现 AdaptiveSimController

**新建：** `gacha_simulator/core/adaptive.py`

- [ ] **1.9: 实现 AdaptiveSimController 类**

```python
"""自适应模拟控制器——实时 RSE 监控，达到目标精度自动停止"""
from typing import List, Dict, Optional, Callable


class AdaptiveSimController:
    def __init__(self, target_rse=0.05, min_samples=1000,
                 max_samples=100000, check_interval=500,
                 gdr_keys=None, target_specs=None):
        from gacha_simulator.core.gdr import compute_gdr_from_compact
        self._compute_gdr = compute_gdr_from_compact
        self._target_rse = target_rse
        self._min_samples = min_samples
        self._max_samples = max_samples
        self._check_interval = check_interval
        self._gdr_keys = gdr_keys or ['target_achievement']
        self._target_specs = target_specs or {}
        self._values = {k: [] for k in self._gdr_keys}
        self._converged = False
        self._n_done = 0
        self._worst_rse = float('inf')
        self._worst_key = None

    def on_result(self, compact):
        for key in self._gdr_keys:
            val = self._compute_gdr(compact, self._target_specs, key)
            self._values[key].append(val)
        self._n_done += 1
        if self._n_done >= self._min_samples and \
           self._n_done % self._check_interval == 0:
            self._check_convergence()

    def _check_convergence(self):
        worst_rse = 0.0
        worst_key = None
        for key, values in self._values.items():
            n = len(values)
            if n < 100:
                continue
            mean = sum(values) / n
            if abs(mean) < 1e-10:
                continue
            variance = sum((v - mean) ** 2 for v in values) / (n - 1)
            se = variance ** 0.5 / n ** 0.5
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

- [ ] **1.10: 运行测试确认全部 GREEN**

```bash
pytest tests/core/test_adaptive.py -v
# 预期: 7 passed
```

### 3.3 修改 batch_simulator——新增 stop_condition 回调

**文件：** `gacha_simulator/service/batch_simulator.py`

- [ ] **1.11: `run_batch_parallel()` 签名新增 `stop_condition` 参数**

```python
def run_batch_parallel(
    n: int,
    target_specs: Dict[str, int],
    initial_resources: Optional[Dict[str, float]] = None,
    max_workers: int = 4,
    seed: int = 42,
    on_result: Optional[Callable[[Dict], None]] = None,
    stop_condition: Optional[Callable[[], bool]] = None,  # 新增
    strategy_name: str = 'smart',
    strategy_params: Optional[Dict] = None,
    stop_condition_name: str = 'all_pools_end',
    stop_condition_params: Optional[Dict] = None,
    antithetic: bool = False,  # Task 2 预留
) -> List[Optional[Dict[str, Any]]]:
```

- [ ] **1.12: 多进程路径——每批结果后检查 stop_condition**

在 `imap_unordered` 消费循环中，每消费一批结果后：

```python
for result in pool.imap_unordered(_wk_run_single, task_args, chunksize=chunk_size):
    results.append(result)
    if on_result and result is not None:
        on_result(result)
    # 新增
    if stop_condition and stop_condition():
        pool.terminate()
        break
```

- [ ] **1.13: 单进程路径——每次模拟后检查 stop_condition**

```python
for i, args in enumerate(task_args):
    result = _wk_run_single(args)
    results.append(result)
    if on_result and result is not None:
        on_result(result)
    # 新增
    if stop_condition and stop_condition():
        break
```

### 3.4 修改 gacha_panel——自适应精度 UI

**文件：** `gacha_simulator/gui/gacha_panel.py`

- [ ] **1.14: 新增「自适应精度」模式 UI 控件**

在模拟次数区域下方新增 group box：

```
模拟模式： ○ 固定次数  ○ 自适应精度
固定次数： [10000] ▲▼
目标精度： [5%] ▲▼        （自适应模式时显示）
最小次数： [1000] ▲▼       （自适应模式时显示）
最大次数： [100000] ▲▼     （自适应模式时显示）
监控指标： [☑目标达成率 ☑资源剩余 ☑SSR收集率]
```

- [ ] **1.15: SimulationThread 支持自适应模式**

`SimulationThread.__init__` 新增可选参数：

```python
def __init__(self, config_store, simulation_count=1000, max_workers=4, seed=42,
             adaptive_mode=False, target_rse=0.05, min_samples=1000,
             max_samples=100000, gdr_keys=None, parent=None):
```

`run()` 方法中，当 `adaptive_mode=True` 时：
1. 创建 `AdaptiveSimController`
2. 将 `controller.on_result` 作为 `on_result` 回调传入 `run_batch_parallel`
3. 将 `controller.should_stop` 作为 `stop_condition` 传入
4. 模拟完成后，将 `controller.get_status()` 附加到返回结果

- [ ] **1.16: 实时精度状态显示**

在进度条下方新增 `QLabel`，定时更新精度状态：

```
当前精度：目标达成率 RSE=3.2% ✓ | 资源剩余 RSE=4.8% ✓
最慢指标：资源剩余 RSE=4.8% (目标 5%)
```

使用 `QTimer` 每 500ms 从 `SimulationThread` 的 `adaptive_controller.get_status()` 读取并更新。

- [ ] **1.17: 目视验证 + 提交**

```bash
git add gacha_simulator/core/adaptive.py tests/core/test_adaptive.py \
        gacha_simulator/service/batch_simulator.py gacha_simulator/gui/gacha_panel.py
git commit -m "feat: 自适应模拟停止——AdaptiveSimController 实时 RSE 监控 + batch_simulator stop_condition 回调 + gacha_panel 自适应精度 UI"
```

---

## 四、Task 2：对偶变量法（TDD + GUI 集成）

> 原理：使用 `(u, 1-u)` 负相关配对样本抵消方差。`θ̂_AV = (1/N) × Σ (h(X_i) + h(X'_i)) / 2`

### 4.1 配对逻辑测试

**扩展现有：** `tests/service/test_batch_service.py`

- [ ] **2.1: test_antithetic_pairing_seed_complement()**

```python
def test_antithetic_pairing_seed_complement():
    """对偶变量法：每对中第二次模拟的随机种子取补"""
    MAX_UINT32 = 2**32 - 1
    base_seeds = [42, 100, 9999, 123456]
    for seed in base_seeds:
        complement = MAX_UINT32 - seed
        # 验证种子不同
        assert complement != seed
        # 验证在有效范围
        assert 0 <= complement <= MAX_UINT32
```

- [ ] **2.2: test_antithetic_pairing_produces_n_results()**

```python
def test_antithetic_pairing_produces_n_results():
    """对偶变量模式：输入 N 次请求，输出 N 个结果（非 N/2 对）"""
    # 接口约定：antithetic=True 时内部配对 N/2 对
    # 但返回仍然是 N 个独立结果（每对展开为 2 个）
    n_samples = 100
    n_pairs = n_samples // 2
    assert n_pairs == 50
    # 每对 2 次模拟 = 100 个结果
    assert n_pairs * 2 == n_samples
```

### 4.2 修改 batch_simulator——对偶配对

**文件：** `gacha_simulator/service/batch_simulator.py`

- [ ] **2.3: `run_batch_parallel()` 实现 antithetic 配对逻辑**

当 `antithetic=True` 时：

```python
MAX_UINT32 = 2**32 - 1

if antithetic:
    n_pairs = n // 2
    task_args = []
    for i in range(n_pairs):
        seed_a = seed + i * 2
        seed_b = MAX_UINT32 - seed_a
        task_args.append((seed_a, target_specs, initial_resources))
        task_args.append((seed_b, target_specs, initial_resources))
    # n_pairs * 2 个任务 → n 或 n-1 个结果（n 为奇数时最后一个不成对）
else:
    task_args = [(seed + i, target_specs, initial_resources) for i in range(n)]
```

- [ ] **2.4: 单进程路径也支持 antithetic**

单进程路径同样需要支持配对模式，保持与多进程路径行为一致。

### 4.3 修改 gacha_panel——对偶变量复选框

**文件：** `gacha_simulator/gui/gacha_panel.py`

- [ ] **2.5: 新增「对偶变量法」复选框**

放在模拟次数设置区下方：

```python
self.antithetic_checkbox = QCheckBox("对偶变量法（降低方差 20-50%）")
self.antithetic_checkbox.setToolTip(
    "使用配对随机数抵消方差。适用于 GDR 均值估计，\n"
    "对成功率估计效果较弱。不适用于分位数估计。"
)
```

- [ ] **2.6: SimulationThread 传递 antithetic 参数**

`SimulationThread.__init__` 新增 `antithetic=False` 参数，`run()` 中传递给 `run_batch_parallel`。

- [ ] **2.7: 目视验证**

启动 GUI → 批量模拟 → 勾选「对偶变量法」→ 执行 N=2000 次模拟 → 对比关闭/开启对偶变量的 GDR 均值标准误。

- [ ] **2.8: 提交**

```bash
git add gacha_simulator/service/batch_simulator.py gacha_simulator/gui/gacha_panel.py \
        tests/service/test_batch_service.py
git commit -m "feat: 对偶变量法——配对模拟降低 GDR 均值估计方差 20-50%"
```

---

## 五、Task 3：EVT 尾部拟合（TDD + UI 集成）

> 原理：用广义帕累托分布（GPD）拟合超过阈值的尾部数据，解析计算 VaR/CVaR。
> `VaR_p = u + (β/ξ) × [(n/Nu × (1-p))^(-ξ) - 1]`

### 5.1 新建测试文件

**新建：** `tests/core/test_evt_tail.py`

- [ ] **3.1: test_gpd_mle_fit_known_params()**

用已知参数的 GPD 生成数据，验证 MLE 恢复参数：

```python
def test_gpd_mle_fit_known_params():
    import numpy as np
    rng = np.random.default_rng(42)
    # GPD(ξ=0.3, β=2.0) → 用 scipy 或手动生成
    # 实际项目中不依赖 scipy，用 numpy 的逆变换法生成
    n = 1000
    xi_true, beta_true = 0.3, 2.0
    u = rng.random(n)
    exceedances = (beta_true / xi_true) * ((1 - u) ** (-xi_true) - 1)
    
    xi_hat, beta_hat = gpd_mle_fit(exceedances)
    # MLE 在大样本下应接近真实值
    assert abs(xi_hat - xi_true) < 0.15
    assert abs(beta_hat - beta_true) < 0.5
```

- [ ] **3.2: test_gpd_mle_fit_empty_raises()**

```python
def test_gpd_mle_fit_empty_raises():
    with pytest.raises(ValueError):
        gpd_mle_fit([])
```

- [ ] **3.3: test_fit_gpd_tail_returns_params()**

```python
def test_fit_gpd_tail_returns_params():
    import numpy as np
    rng = np.random.default_rng(42)
    data = rng.exponential(scale=100, size=2000)
    xi, beta, threshold = fit_gpd_tail(data, threshold_method='quantile_90')
    assert isinstance(xi, float)
    assert isinstance(beta, float)
    assert threshold > 0
```

- [ ] **3.4: test_evt_var_below_threshold_returns_none()**

```python
def test_evt_var_below_threshold_returns_none():
    """VaR 概率在阈值覆盖范围内时，直接返回经验分位数而非 EVT 外推"""
    data = [10, 20, 30, 40, 50]
    xi, beta, u = fit_gpd_tail(data, threshold_method='quantile_80')
    # p=0.5 在 80% 阈值覆盖内，应使用经验分位数
    var = evt_var(data, p=0.5, xi=xi, beta=beta, threshold=u)
    assert var is not None
```

- [ ] **3.5: test_evt_var_extreme_tail()**

```python
def test_evt_var_extreme_tail():
    import numpy as np
    rng = np.random.default_rng(42)
    data = rng.exponential(scale=100, size=5000)
    xi, beta, u = fit_gpd_tail(data, threshold_method='quantile_90')
    # EVT VaR 95%（在 90% 阈值外，需外推）
    var_95 = evt_var(data, p=0.95, xi=xi, beta=beta, threshold=u)
    # 应与经验分位数基本一致
    empirical_95 = np.percentile(data, 95)
    assert abs(var_95 - empirical_95) / empirical_95 < 0.20
```

- [ ] **3.6: test_evt_cvar_consistency()**

```python
def test_evt_cvar_consistency():
    """CVaR 必须 ≥ VaR（同概率下）"""
    import numpy as np
    rng = np.random.default_rng(42)
    data = rng.exponential(scale=100, size=5000)
    xi, beta, u = fit_gpd_tail(data, threshold_method='quantile_90')
    var_97 = evt_var(data, p=0.97, xi=xi, beta=beta, threshold=u)
    cvar_97 = evt_cvar(data, p=0.97, xi=xi, beta=beta, threshold=u)
    assert cvar_97 >= var_97
```

- [ ] **3.7: test_auto_threshold_mean_excess()**

```python
def test_auto_threshold_mean_excess():
    import numpy as np
    rng = np.random.default_rng(42)
    data = rng.exponential(scale=100, size=2000)
    threshold = auto_threshold(data, method='mean_excess')
    # 应返回数据范围内的分位数
    assert np.percentile(data, 80) <= threshold <= np.percentile(data, 98)
```

- [ ] **3.8: 运行 Task 3 测试确认全部 RED**

```bash
pytest tests/core/test_evt_tail.py -v
# 预期: 7 failed（函数不存在）
```

### 5.2 实现 EVT 核心模块

**新建：** `gacha_simulator/core/evt_tail.py`

- [ ] **3.9: 实现 `gpd_mle_fit(exceedances)`**

GPD 负对数似然最小化（仅依赖 numpy，不依赖 scipy）：

```python
def gpd_mle_fit(exceedances):
    """GPD 参数的 MLE 估计（Profile Likelihood 方法）
    
    GPD CDF: F(x) = 1 - (1 + ξ·x/β)^(-1/ξ)  for ξ≠0
             F(x) = 1 - exp(-x/β)             for ξ=0
    
    返回 (ξ, β)
    """
    import numpy as np
    if len(exceedances) < 10:
        raise ValueError("至少需要 10 个超阈值样本")
    
    x = np.array(exceedances, dtype=np.float64)
    n = len(x)
    
    def neg_log_lik(params):
        xi, beta = params[0], params[1]
        if beta <= 0:
            return 1e15
        if xi < -0.5:  # MLE 正则条件
            return 1e15
        if abs(xi) < 1e-8:
            return n * np.log(beta) + np.sum(x) / beta
        if xi > 0 and np.any(x >= beta / (-xi) if xi < 0 else float('inf')):
            return 1e15
        t = 1 + xi * x / beta
        if np.any(t <= 0):
            return 1e15
        return n * np.log(beta) + (1 + 1/xi) * np.sum(np.log(t))
    
    # 网格搜索初值 + 简易梯度下降
    best_params = None
    best_nll = float('inf')
    for xi0 in np.linspace(-0.4, 0.8, 13):
        beta0 = np.mean(x)
        try:
            # 简易优化：在网格点附近做数值搜索
            for scale in [0.5, 1.0, 2.0]:
                params = np.array([xi0, beta0 * scale])
                nll = neg_log_lik(params)
                if nll < best_nll:
                    best_nll = nll
                    best_params = params.copy()
        except Exception:
            continue
    
    if best_params is None:
        # 回退：矩估计
        m = np.mean(x)
        v = np.var(x, ddof=1)
        xi_mom = 0.5 * (m**2 / v - 1)
        beta_mom = 0.5 * m * (m**2 / v + 1)
        return float(xi_mom), float(beta_mom)
    
    # 简易坐标下降精化
    xi, beta = best_params[0], best_params[1]
    for _ in range(30):
        # 固定 β，优化 ξ（黄金分割搜索）
        for xi_cand in np.linspace(xi - 0.1, xi + 0.1, 21):
            nll = neg_log_lik(np.array([xi_cand, beta]))
            if nll < best_nll:
                best_nll = nll
                xi = xi_cand
        # 固定 ξ，优化 β
        for beta_cand in np.linspace(beta * 0.8, beta * 1.2, 21):
            nll = neg_log_lik(np.array([xi, beta_cand]))
            if nll < best_nll:
                best_nll = nll
                beta = beta_cand
    
    return float(xi), float(beta)
```

- [ ] **3.10: 实现 `fit_gpd_tail(data, threshold_method)`**

```python
def fit_gpd_tail(data, threshold_method='quantile_90'):
    """对数据尾部拟合 GPD
    
    threshold_method:
      - 'quantile_90': 90% 分位数作为阈值
      - 'quantile_95': 95% 分位数
      - 'mean_excess': 自动选择（平均超额图法）
    """
    import numpy as np
    x = np.array(data, dtype=np.float64)
    
    if threshold_method == 'quantile_90':
        threshold = np.percentile(x, 90)
    elif threshold_method == 'quantile_95':
        threshold = np.percentile(x, 95)
    elif threshold_method == 'mean_excess':
        threshold = auto_threshold(x)
    else:
        raise ValueError(f"未知阈值方法: {threshold_method}")
    
    exceedances = x[x > threshold] - threshold
    if len(exceedances) < 10:
        # 尾部数据不足，回退到经验分位数
        return 0.0, np.std(x), threshold
    
    xi, beta = gpd_mle_fit(exceedances)
    return xi, beta, threshold
```

- [ ] **3.11: 实现 `auto_threshold(data, method)`**

```python
def auto_threshold(data, method='mean_excess'):
    """自动选择 GPD 阈值
    
    method='mean_excess': 平均超额图法——选择平均超额函数开始线性的点
    """
    import numpy as np
    x = np.array(sorted(data), dtype=np.float64)
    n = len(x)
    
    if method == 'mean_excess':
        # 取 top 30% 作为候选阈值
        candidates = np.percentile(x, np.linspace(70, 98, 29))
        best_score = float('inf')
        best_u = np.percentile(x, 85)
        
        for u in candidates:
            exceed = x[x > u] - u
            k = len(exceed)
            if k < 30:
                continue
            mean_excess = np.mean(exceed)
            # 计算线性拟合 R²
            sorted_exceed = np.sort(exceed)
            theoretical = np.linspace(0, mean_excess * 2, k)
            ss_res = np.sum((sorted_exceed - theoretical) ** 2)
            ss_tot = np.sum((sorted_exceed - mean_excess) ** 2)
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0
            # 选择 R² 最高的阈值（线性最好）
            score = -r2
            if score < best_score:
                best_score = score
                best_u = u
        
        return float(best_u)
    
    # 默认：90% 分位数
    return float(np.percentile(x, 90))
```

- [ ] **3.12: 实现 `evt_var(data, p, xi, beta, threshold)`**

```python
def evt_var(data, p, xi, beta, threshold):
    """EVT VaR 计算
    
    VaR_p = u + (β/ξ) × [(n/Nu × (1-p))^(-ξ) - 1]  for ξ≠0
    VaR_p = u + β × log(Nu / (n × (1-p)))          for ξ=0
    """
    import numpy as np
    x = np.array(data, dtype=np.float64)
    n = len(x)
    nu = np.sum(x > threshold)
    
    if nu < 10:
        return float(np.percentile(x, p * 100))
    
    tail_prob = n / nu * (1 - p)
    
    if abs(xi) < 1e-8:
        var = threshold + beta * np.log(tail_prob)
    else:
        var = threshold + (beta / xi) * (tail_prob ** (-xi) - 1)
    
    return float(var)
```

- [ ] **3.13: 实现 `evt_cvar(data, p, xi, beta, threshold)`**

```python
def evt_cvar(data, p, xi, beta, threshold):
    """EVT CVaR（Expected Shortfall）计算
    
    CVaR_p = VaR_p + (β + ξ × (VaR_p - u)) / (1 - ξ)  for ξ < 1
    """
    import numpy as np
    var_p = evt_var(data, p, xi, beta, threshold)
    
    if xi >= 1.0:
        return float('inf')  # 一阶矩不存在
    
    if abs(xi) < 1e-8:
        cvar = var_p + beta
    else:
        cvar = var_p + (beta + xi * (var_p - threshold)) / (1 - xi)
    
    return float(cvar)
```

- [ ] **3.14: 运行测试确认全部 GREEN**

```bash
pytest tests/core/test_evt_tail.py -v
# 预期: 7 passed
```

### 5.3 修改 analysis_panel——使用 EVT VaR/CVaR

**文件：** `gacha_simulator/gui/analysis_panel.py`

- [ ] **3.15: VaR/CVaR 计算优先使用 EVT 拟合**

在计算 VaR/CVaR 的相关方法中：

```python
from gacha_simulator.core.evt_tail import fit_gpd_tail, evt_var, evt_cvar

def _compute_var_robust(self, data, p):
    """混合 VaR 估计：当尾部数据充足时用 EVT，否则用经验分位数"""
    xi, beta, u = fit_gpd_tail(data, threshold_method='quantile_90')
    if abs(xi) < 1e-6 and abs(beta - np.std(data)) < 1e-6:
        # GPD 拟合失败或退回到矩估计，使用经验分位数
        return float(np.percentile(data, p * 100))
    return evt_var(data, p, xi, beta, u)
```

- [ ] **3.16: 显示 EVT 拟合质量指标**

在 analysis_panel 中添加 EVT 拟合摘要（可选折叠面板）：
- QQ 图（超阈值数据 vs GPD 理论分位数）
- 拟合参数 `ξ` 和 `β` 及其标准误
- 阈值 `u` 和超阈值样本数 `Nu`

- [ ] **3.17: 目视验证 + 提交**

启动 GUI → 统计分析 → 执行模拟 → 查看 VaR/CVaR 估计 → 对比 EVT 和经验分位数的一致性。

```bash
git add gacha_simulator/core/evt_tail.py tests/core/test_evt_tail.py \
        gacha_simulator/gui/analysis_panel.py
git commit -m "feat: EVT 尾部拟合——GPD 参数 MLE + VaR/CVaR 解析计算，改善尾部分位数精度"
```

---

## 六、验收标准

- [ ] `AdaptiveSimController` 所有方法通过 TDD 测试（7 个测试）
- [ ] `gpd_mle_fit` / `fit_gpd_tail` / `evt_var` / `evt_cvar` / `auto_threshold` 通过 TDD 测试（7 个测试）
- [ ] 自适应模式在典型配置（p≈0.5, σ≈0.3）下自动收敛到目标 RSE 5% 以内
- [ ] 固定次数模式行为不变（向后兼容）
- [ ] 对偶变量模式的 GDR 均值估计方差 ≤ 普通模式的 80%
- [ ] 对偶变量模式的 GDR 均值估计无偏（与普通模式均值差异 < 1%）
- [ ] EVT VaR 5% 与 50000 样本经验分位数误差 < 5%
- [ ] 5000 样本 + EVT 的 VaR 精度 ≥ 50000 样本经验分位数精度
- [ ] 全部已有测试保持绿色

---

## 七、与 P3（Bootstrap）的兼容性

| 本 Task | 与 Bootstrap 的关系 | 设计要求 |
|---------|-------------------|---------|
| Task 1（自适应停止） | 互补：自适应停止保证"模拟量足够"，Bootstrap 回答"结果有多稳" | 无特殊要求（当前基于 RSE，无可选停止偏差） |
| Task 2（对偶变量） | 兼容，需配对 Bootstrap | `BootstrapEngine` 支持 `paired=True`，重抽样 N/2 对而非 N 个个体 |
| Task 3（EVT 尾部） | 互补：尾部分位数需参数 Bootstrap | EVT 函数应接受任意数据（含重抽样数据），返回 GPD 参数 + VaR/CVaR；Bootstrap 从 GPD 中抽样而非从经验分布重抽样 |

**建议执行顺序**：P3（Bootstrap）先于 P4 实现，EVT 在 Bootstrap 框架上扩展 Bootstrap-EVT 混合方法。

---

## 八、执行顺序

```
Task 1 (自适应停止) — 优先级最高，独立
Task 3 (EVT 尾部)  — 优先级中，独立
Task 2 (对偶变量)  — 优先级低，独立
```

三个 Task 完全独立，可以并行实现。Task 1 优先级最高（所有面板通用收益），Task 3 次之（VaR/CVaR 精度改善），Task 2 最低（收益中等但实现简单）。
