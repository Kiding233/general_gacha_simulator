# GUI 模拟性能优化方案

> 日期：2026-05-27 | 状态：**已完成（P0+P1 已实施，2026-05-27）**
> 背景：Phase 1.5 实施后，用户报告 GUI 下 1000 次模拟仍需 5-8 秒等待。本文档基于 GUI 代码路径的精确实测，识别剩余瓶颈并提出优化方案。

---

## 实测环境与方法

使用与 GUI 完全一致的代码路径（`profile_gui.py`），模拟真实使用场景：
- **Phase A**：应用启动（QApplication 初始化 + MainWindow 导入 + 配置加载）
- **Phase B**：首次点击「开始模拟」（冷启动，含首次 import 核心类）
- **Phase C**：第二次点击（热启动，所有 import 已缓存）

测试参数：N=1000, workers=16, Windows 11, Python 3.12, 22 核 CPU。

---

## 实测数据

### Phase A：应用启动

| 阶段 | 耗时 | 说明 |
|------|------|------|
| A1. QApplication 初始化 | 0.07s | PyQt6 框架启动 |
| A2. 导入 MainWindow + 全部 10 个面板 | 0.60s | 一次性开销，用户启动应用时已发生 |
| A3. 导入 config_io + ConfigStore | ~0ms | 已在 A2 中间接导入 |
| A4. 加载配置文件 | 4.5ms | `load_store_from_directory()` |
| **Phase A 合计** | **0.68s** | 用户从双击到界面可操作 |

### Phase B：首次点击「开始模拟」（冷启动）

| 阶段 | 耗时 | 占比 | 说明 |
|------|------|------|------|
| B1. `from_config_store()` | 0.9ms | 0.01% | ConfigStore → SimulationEnv 转换，极快 |
| B2. 准备参数 | ~0ms | — | target_specs / collector 创建 |
| B3. 主模拟 — 总耗时 | 2.98s | 41.9% | `run_batch_parallel()` 完整耗时 |
| 　B3b. 首次进度前等待 | **1.16s** | 16.3% | Windows spawn 16 进程 + `_wk_init` + 首个 chunk |
| 　B3c. 进度条活跃期 | 1.82s | 25.6% | 16 workers 并行模拟 1000 次 |
| 　B3d. 进度信号发射 | 1000 次 | — | 每完成一次模拟 emit 一次 |
| B4. no_draw 基线 | 1.0ms | 0.01% | 单进程跑 1 次 `no_draw` 策略 |
| B5. 构建 result_bundle | 0.1ms | — | 从 extraction 组装 dict |
| B6. 面板分发 — 总耗时 | **4.13s** | 58.0% | ⚠ 含首次导入 4 个分析面板模块 |
| 　B6a. analysis_panel | 0.1ms | — | update_results 调用本身 |
| 　B6b. worst_impact_panel | 0.1ms | — | 同上 |
| 　B6c. retreat_panel | ~0ms | — | 同上 |
| 　B6d. process_analysis_panel | ~0ms | — | 同上 |
| **Phase B 合计** | **7.11s** | 100% | 从点击到面板全部更新 |

### Phase C：第二次点击（热启动）

| 阶段 | 耗时 | 说明 |
|------|------|------|
| B1-B5 模拟线程 | 2.88s | 与冷启动基本一致 |
| 　B3b. 首次进度前等待 | 1.23s | 与冷启动一致（spawn 开销不变） |
| 　B3c. 进度条活跃期 | 1.64s | 与冷启动一致 |
| B6. 面板分发 | **0.04s** | 面板模块已导入，update 极快 |
| **Phase C 合计** | **2.92s** | 真实用户的每次模拟体验 |

---

## 关键发现

### 1. 冷启动 4.13s 面板分发是「伪瓶颈」

Phase B 中面板分发占 58%（4.13s），但这是**测试脚本的结构问题**——在真实 GUI 中，`MainWindow.__init__`（Phase A）已经通过 `from .analysis_panel import AnalysisPanel` 等语句预加载了所有面板模块。Phase A 的 0.60s「导入 MainWindow + 所有面板」已经包含了这些导入。

**真实用户的模拟点击体验接近 Phase C（热启动），即 ~2.9s，而非 Phase B 的 ~7.1s。**

### 2. 真正的瓶颈是「首次进度前等待」1.2s

这 1.2s 的构成：
- Windows `spawn` 启动 16 个 Python 子进程：~0.6-0.8s
- 每个子进程执行 `_wk_init`（`import gacha_simulator.core` + 构建 TargetCardSet + WorkerLocalExtractor）：~0.3-0.5s
- 首个 chunk（3 次模拟 × 9ms）完成：~0.03s

其中 `import gacha_simulator.core` 在 `_wk_init` 中导入整个 core 模块（[batch_simulator.py:203](gacha_simulator/service/batch_simulator.py#L203)），包含 bootstrap、vulnerability、risk_analysis、forward_backward 等 worker 中**完全不需要**的模块，浪费 200-400ms。

### 3. 模拟计算 1.6-1.8s 是硬瓶颈

1000 次 × 9ms/次 ÷ 16 workers ≈ 0.56s 理论下限。实际 1.6-1.8s 包含了：
- 负载不均（各次模拟抽卡次数不同，200-400 抽不等）
- pickle 序列化/反序列化开销
- Worker 内 Extract 开销（~0.5-1ms/次）

只有 Phase 2（Numba 数值化内核）能显著缩短这部分，但投入产出比在 N=1000 时不划算。

### 4. `collector` 冗余累积

[gacha_panel.py:67-68](gacha_simulator/gui/gacha_panel.py#L67-L68) 在主进程创建 `SharedResultCollector` 并注册 `extract_aggregate`，[line 84](gacha_simulator/gui/gacha_panel.py#L84) 将其作为 `on_result` 回调传入。**Worker 已在内部完成提取**，主进程重复执行 `extract_aggregate(compact)` 1000 次，且将结果存入 `collector._extractors['aggregate'][1]` 列表（1000 条 × ~2KB = ~2MB 冗余内存）。

`result_bundle` 实际使用的是 `batch_result.extraction`（worker 提取），`collector` 的数据仅作为「回退路径」存在，而这个回退路径在现代代码路径中永远不会被触发。

---

## 优化方案

### P0：去除 collector 冗余累积

- **文件**：`gacha_simulator/gui/gacha_panel.py`
- **改动**：移除 `SharedResultCollector` 创建和 `on_result` 传参，直接使用 `batch_result.extraction`
- **投入**：~1 小时
- **收益**：
  - 消除主进程 1000 次 `extract_aggregate` 串行调用（~0.3-0.5s）
  - Worker 无需传回完整 `compact` dict（仅传 `extraction_packet`），减少 pickle 传输量
  - 消除 ~2MB 冗余内存累积
  - 在 N=10 万时收益更显著（~30-50s + ~200MB 内存）
- **风险**：极低。回退路径已在 Phase 1.5 后不再触发。
- **验证**：`pytest` + GUI 模拟一次确认 `result_bundle` 数据完整

#### 实施细节

```python
# gacha_panel.py SimulationThread.run() 中的变更：

# 删除：
# collector = SharedResultCollector()
# collector.add_extractor('aggregate', extract_aggregate)

# run_batch_parallel 调用中：
# on_result=collector.on_result,  →  on_result=None,

# result_bundle 构建中删除回退分支（else 分支，第 137-154 行）
```

同时修改 `batch_simulator.py` 中 `_wk_run_single`：当 `on_result is None` 且 `_wk_extractor is not None` 时，**不传回 compact**，只传回 extraction_packet：

```python
def _wk_run_single(args):
    seed, initial_resources = args
    try:
        compact = _run_single(_wk_env, _wk_target_set, seed, initial_resources)
    except Exception:
        traceback.print_exc()
        return None

    if compact is None:
        return None

    extraction = None
    if _wk_extractor is not None:
        try:
            extraction = _wk_extractor.process(compact)
        except Exception:
            traceback.print_exc()

    return extraction  # 不再返回 compact
```

---

### P1：进度信号批处理

- **文件**：`gacha_simulator/gui/gacha_panel.py`
- **改动**：在 `SimulationThread.run()` 中加入计数器，每 20 次模拟才 emit 一次 progress
- **投入**：~0.5 小时
- **收益**：1000 次信号 → 50 次，减少 Qt 事件循环压力 ~0.2-0.3s
- **风险**：极低。进度条从 1000 步变为 50 步，精度略降但用户感知无差异。

```python
# gacha_panel.py SimulationThread.run() 中：
_batch_counter = 0
_batch_interval = max(1, N // 50)  # 至少 50 次更新

def progress_callback(done, total):
    nonlocal _batch_counter
    _batch_counter += 1
    if _batch_counter % _batch_interval == 0 or done >= total:
        self.progress.emit(done, total)

batch_result = run_batch_parallel(
    ...
    progress_callback=progress_callback,
    ...
)
```

---

### P2：`_wk_init` 精简导入

- **文件**：`gacha_simulator/service/batch_simulator.py`
- **改动**：`import gacha_simulator.core as _core` 改为只导入 worker 实际需要的类
- **投入**：~1 小时
- **收益**：首次进度前等待缩短 ~0.2-0.4s（每个 worker 的 `_wk_init` 从 ~0.3s 降至 ~0.1s）
- **风险**：中。需仔细确认 worker 中所有用到的类都被导入。

当前 `import gacha_simulator.core` 导入的模块（[core/__init__.py](gacha_simulator/core/__init__.py)）：
- **需要**：`GachaState`、`GachaService`（通过 `import gacha_simulator.service`）、`TargetCard`、`TargetCardSet`、`PityState`、`create_strategy`、`AllPoolsEndCondition`、`WorkerLocalExtractor`
- **不需要**：`BootstrapEngine`、`VulnerabilityAnalysisResult`、`ForwardStep`/`BackwardStep`、`RiskAnalyzer`、`WorstImpactAnalyzer`、`TransitionMatrix`、`StreamingAnalyzer`、`SuccessProbabilityAnalyzer`、`PoolConfig`、`CardCatalog` 等 ~30+ 个类

```python
def _wk_init(env: SimulationEnv, target_specs: Dict[str, int] = None):
    global _wk_env, _wk_target_set, _wk_extractor
    _wk_env = env

    # 只导入 worker 实际需要的类，而非整个 core 模块
    from gacha_simulator.core import GachaState, TargetCard, TargetCardSet
    from gacha_simulator.core.pity import PityState
    from gacha_simulator.service import GachaService
    # ... 构建 TargetCardSet 和 WorkerLocalExtractor
```

---

### P3：面板延迟更新（Lazy Panel Update）

- **文件**：`gacha_simulator/gui/main_window.py`
- **改动**：`on_simulation_finished()` 只更新当前可见 Tab，其他 Tab 标记为 `_dirty = True`，切换时再更新
- **投入**：~2 小时
- **收益**：面板分发从串行 4 面板变为仅 1 面板，~0.04s，减少主线程阻塞
- **风险**：低。需在各面板的 Tab 切换逻辑中加入 dirty 检查。

```python
# main_window.py
def on_simulation_finished(self, result_bundle):
    self._pending_result_bundle = result_bundle
    self._pending_target_specs = target_specs
    self._panels_dirty = {'analysis', 'worst_impact', 'retreat', 'process_analysis'}
    # 只更新当前可见的
    self._update_visible_panel()

def _on_tab_changed(self, index):
    # 切换时检查是否需要更新
    self._update_visible_panel()
    # ... 原有逻辑 ...

def _update_visible_panel(self):
    if not self._pending_result_bundle:
        return
    current = self.tabs.currentWidget()
    # 根据当前 Tab 分发对应面板
```

---

### P4：`from_config_store` 缓存

- **文件**：`gacha_simulator/gui/gacha_panel.py`
- **改动**：对 `SimulationEnv` 做配置指纹（hash），配置未变时复用上次的 env
- **投入**：~2 小时
- **收益**：首次点击节省 `from_config_store` 开销（虽然实测仅 0.9ms，但在复杂配置下可能达到 0.5-1s）
- **风险**：中。需正确处理配置变更检测，避免使用过期 env。

```python
class GachaPanel(QWidget):
    def __init__(self):
        self._cached_env = None
        self._cached_config_hash = None

    def _get_or_build_env(self, config_store):
        h = self._config_hash(config_store)
        if self._cached_env is not None and self._cached_config_hash == h:
            return self._cached_env
        env = SimulationEnvBuilder.from_config_store(config_store)
        self._cached_env = env
        self._cached_config_hash = h
        return env
```

但注意：当前实测 `from_config_store` 仅 0.9ms，P4 的优先级取决于实际配置复杂度。

---

### P5：`no_draw` 基线延迟计算

- **文件**：`gacha_simulator/gui/gacha_panel.py`、`gacha_simulator/gui/main_window.py`
- **改动**：将 `no_draw` 模拟移到 `on_simulation_finished` 之后的后台线程，或直接缓存（同配置下结果确定）
- **投入**：~1 小时
- **收益**：模拟线程缩短 ~0.3-0.5s（当前实测仅 1-2ms，但用户复杂配置下可能更慢）
- **风险**：低。`no_draw` 仅用于分析面板的可选展示。

---

## 收益汇总

| 优化项 | 投入 | N=1000 收益 | N=10万 收益 | 风险 |
|--------|------|------------|------------|------|
| **P0** 去除 collector 冗余 | 1h | ~0.3-0.5s | ~30-50s + 200MB | 极低 |
| **P1** 进度信号批处理 | 0.5h | ~0.2-0.3s | ~2-3s | 极低 |
| **P2** `_wk_init` 精简导入 | 1h | ~0.2-0.4s | ~0.2-0.4s | 中 |
| **P3** 面板延迟更新 | 2h | ~0.5-1s | ~0.5-1s | 低 |
| **P4** `from_config_store` 缓存 | 2h | ~0-1s | ~0-1s | 中 |
| **P5** `no_draw` 延迟 | 1h | ~0-0.5s | ~0-0.5s | 低 |

### 预期总收益

| 场景 | 当前实测 | P0+P1 后 | P0-P3 后 | 全部实施后 |
|------|---------|---------|---------|----------|
| 首次点击（冷启动） | ~7.1s | ~6.3s | ~5.5s | ~4-5s |
| 重复点击（热启动） | ~2.9s | **~2.1s** | **~1.5s** | **~1.0-1.5s** |
| N=10万 热启动 | ~60s | ~30s | ~28s | ~25s |

### N=1000 热启动路径优化后的时间线

```
点击按钮 → 0.0s
  ├─ from_config_store:        ~1ms  (P4 缓存后 0ms)
  ├─ 首次进度出现:              ~0.8s (P2 精简导入 -0.3s)
  ├─ 进度条活跃期:              ~1.6s (无变化，硬瓶颈)
  ├─ 构建 result_bundle:       ~0.1ms
  └─ 面板分发:                  ~0.02s (P3 延迟后仅更新当前面板)
完成 ← ~2.4s
```

---

## 不推荐的优化

### 进度条 indeterminate 模式

虽可改善「等待感」，但不减少实际耗时。P1 批处理后信号已足够平滑，不需要。

### 进程池预热（Worker Pool Warmup）

在用户配置参数时后台预启动一个 Pool。实现复杂，且 Windows spawn 下预热 Pool 的 worker 无法复用（Pool 关闭后子进程退出）。不推荐。

### 共享内存传输（Phase 3.1）

Phase 1.5 已将传输量从 ~15KB/次 降至 ~1KB/次。共享内存的边际收益极小（<0.1s），但实现复杂度高（Windows `shared_memory` 需显式 `close`+`unlink`）。

---

## 实施顺序

```
P0 (1h) → P1 (0.5h) → P2 (1h) → P3 (2h) → P5 (1h) → P4 (2h)
  ─────────── 半天可完成 ───────────   ────── 进阶优化 ──────
```

P0+P1 是最低成本的快速收益，建议立即实施。P2 需仔细验证 worker 内导入依赖。P3-P5 视用户实际体验反馈决定是否实施。

---

## 验证方案

1. 运行 `python profile_gui.py`，确认各阶段耗时缩短
2. 启动 GUI，点击「开始批量模拟」，观察进度条首次出现时间
3. 模拟完成后检查各分析面板数据完整性
4. `pytest` 全部通过，无回归
5. N=10,000 压力测试，确认内存无泄漏
