# 自适应模拟次数与方差缩减实施计划

## 前置依赖

- 设计文档：`/workspace/docs/superpowers/specs/2026-05-16-adaptive-simulation-design.md`
- 依赖流式重构完成（`on_result` 回调 + `SharedResultCollector`）

## Task 1：自适应停止机制

**目标**：实现自适应精度模式，模拟过程中实时评估精度，达到目标后自动停止

**内容**：

1. 新建 `core/adaptive.py`：
   - `AdaptiveSimController` 类
   - 多指标联合收敛检测
   - 精度状态查询接口

2. 修改 `gui/batch_simulator.py`：
   - `run_batch_parallel` 新增 `stop_condition: Optional[Callable[[], bool]]` 参数
   - 多线程模式下，每消费一批结果后检查 stop_condition
   - 单线程模式下，每完成一个模拟后检查

3. 修改 `gui/gacha_panel.py`：
   - 新增"自适应精度"模式 UI（单选按钮 + 精度参数控件）
   - 自适应模式时创建 `AdaptiveSimController` 并注册到 `SharedResultCollector`
   - 模拟过程中实时显示精度状态

**验证**：
- 自适应模式在典型配置下自动收敛到目标 RSE
- 固定模式行为不变
- 自适应模式实际模拟次数 ≤ max_samples

**产出文件**：新建 `core/adaptive.py`，修改 `gui/batch_simulator.py`、`gui/gacha_panel.py`

## Task 2：对偶变量法

**目标**：实现配对模拟，降低 GDR 均值估计方差

**内容**：

1. 修改 `gui/batch_simulator.py`：
   - 新增 `antithetic: bool = False` 参数
   - 当 antithetic=True 时，将 N 次模拟配对为 N/2 对
   - 每对中第二次模拟的随机种子取补（seed' = max_seed - seed）
   - 返回结果仍然是 N 个独立估计

2. 修改 `gui/gacha_panel.py`：
   - 新增"对偶变量"复选框
   - 传递参数到 `run_batch_parallel`

**验证**：
- 对偶变量模式的 GDR 均值估计方差低于普通模式（至少 20% 降低）
- 估计值无偏（均值与普通模式一致）

**产出文件**：修改 `gui/batch_simulator.py`、`gui/gacha_panel.py`

## Task 3：EVT 尾部拟合

**目标**：用 GPD 拟合尾部数据，改善 VaR/CVaR 的估计精度

**内容**：

1. 新建 `core/evt_tail.py`：
   - `fit_gpd_tail(data, threshold_method='mean_excess')` — GPD 拟合
   - `evt_var(data, p, threshold)` — EVT VaR 计算
   - `evt_cvar(data, p, threshold)` — EVT CVaR 计算
   - `auto_threshold(data)` — 自动阈值选择（平均超额图法）
   - `gpd_mle_fit(exceedances)` — GPD 参数 MLE 估计

2. 修改 `gui/analysis_panel.py`：
   - VaR/CVaR 计算优先使用 EVT 拟合
   - 当尾部数据不足时回退到经验分位数
   - 显示 EVT 拟合质量指标（QQ 图、参数置信区间）

**验证**：
- EVT 拟合的 VaR 5% 与大样本经验分位数一致（误差 <5%）
- 5000 样本 + EVT 的 VaR 精度接近 50000 样本的经验分位数
- 当尾部数据不足时优雅回退

**产出文件**：新建 `core/evt_tail.py`，修改 `gui/analysis_panel.py`

## 执行顺序

```
Task 1 (自适应停止) — 优先级最高，独立
Task 2 (对偶变量) — 优先级低，独立
Task 3 (EVT尾部) — 优先级中，独立
```

三个 Task 完全独立，可以并行实现。
