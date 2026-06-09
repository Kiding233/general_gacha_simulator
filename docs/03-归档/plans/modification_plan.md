# 修改计划 - 丢失修改恢复

按依赖关系从底层到表层排序。每层的修改依赖前一层完成。

---

## 第1层：核心逻辑（无外部依赖）

### 1.1 strategy.py — create_strategy 内部策略保护 ✅

- **文件**: `core/strategy.py`
- **问题**: `create_strategy('draw_target', {})` 会崩溃，因为 `DrawTargetStrategy.__init__` 需要2个参数
- **修改**: 在 `create_strategy()` 中，`entry = STRATEGY_REGISTRY.get(strategy_name)` 之后、`cls = entry['class']` 之前，添加：
  ```python
  if entry.get('internal'):
      raise ValueError(f"Cannot create internal strategy '{strategy_name}' via create_strategy()")
  ```

### 1.2 vulnerability.py — 删除 _is_success() 包装函数 ✅

- **文件**: `core/vulnerability.py`
- **问题**: `_is_success()` 是多余包装，4处调用仍传大量参数
- **修改**:
  - 删除 `_is_success()` 函数定义（约13行）
  - 4处调用从 `_is_success(r, target_specs, gdr_key, gdr_threshold, desire_weights, miss_cost_weights, card_value_weights, _checker=checker)` 改为 `checker.is_success(r)`

### 1.3 streaming.py — extract_process() 使用 SuccessChecker ✅

- **文件**: `core/streaming.py`
- **问题**: 第136行 `'success': val >= gdr_threshold` 直接比较，未使用 SuccessChecker
- **修改**:
  - 在 `extract_process()` 中创建 `SuccessChecker` 实例：
    ```python
    from .gdr import SuccessChecker
    checker = SuccessChecker(
        target_specs, gdr_key, gdr_threshold,
        desire_weights, miss_cost_weights, card_value_weights,
        ssr_ids, weapon_character_map,
    )
    ```
  - 第136行改为 `'success': val >= checker.gdr_threshold`（等价于 `checker.is_success(compact)`，避免重复计算）

### 1.4 process_analysis.py — 变量重命名 ✅

- **文件**: `core/process_analysis.py`
- **问题**: `never_success` 实际含义是"全部失败"，`never_fail` 实际含义是"全部成功"，命名反直觉
- **修改**: 全局替换
  - `never_success` → `all_fail`
  - `never_fail` → `all_success`
  - `never_success_prob` → `all_fail_prob`
  - `never_fail_prob` → `all_success_prob`

---

## 第2层：核心逻辑面板适配（依赖第1层）

### 2.1 process_analysis_panel.py — 读取新键名 + 显示标签更新 ✅

- **文件**: `gui/process_analysis_panel.py`
- **依赖**: 1.4（process_analysis.py 输出新键名）
- **问题**: 仍读取 `never_success_prob`/`never_fail_prob`，显示为"整体失败/成功"
- **修改**:
  - 第467-468行：`never_success_prob` → `all_fail_prob`，`never_fail_prob` → `all_success_prob`
  - 第473行：`"整体失败概率"` → `"全部池失败概率"`
  - 第474行：`"整体成功概率"` → `"全部池成功概率"`

---

## 第3层：核心→服务层接口修正（依赖第1层）

### 3.1 retreat_search.py — 导入路径 + ssr_ids 参数 ✅

- **文件**: `core/retreat_search.py`
- **依赖**: 1.1（service/batch_simulator.py 已存在）
- **问题**: ① 仍从 `gui.batch_simulator` 导入；② `run_batch_parallel()` 缺少 `ssr_ids` 参数
- **修改**:
  - 第75行：`from gacha_simulator.gui.batch_simulator import SimulationEnvBuilder` → `from gacha_simulator.service.batch_simulator import SimulationEnvBuilder`
  - 第83行：`from gacha_simulator.gui.batch_simulator import run_batch_parallel` → `from gacha_simulator.service.batch_simulator import run_batch_parallel`
  - 第87-102行的 `run_batch_parallel()` 调用添加 `ssr_ids=env.ssr_ids`

---

## 第4层：GUI 基础设施重构（依赖第3层）

原 4.1 拆分为 4.1a / 4.1b / 4.1c 三个子阶段，按风险递增顺序执行。
5.1（四面板 set_config_panel）与 4.1a/4.1b/4.1c 完全独立，可在 4.1a 之后插入执行。

### 4.1a gacha_panel.py — 消除 _find_config_panel()，注入 config_panel 引用 ✅

- **文件**: `gui/gacha_panel.py`, `gui/main_window.py`
- **依赖**: 无额外依赖
- **风险**: 极低 — 纯引用方式替换，不改变任何数据流
- **问题**: `_find_config_panel()` 通过 QApplication 全局搜索获取 ConfigPanel，脆弱且隐式
- **修改**:
  - `GachaPanel` 新增 `self._config_panel = None` 和 `set_config_panel(config_panel)` 方法
  - `start_simulation()` 中 `self._find_config_panel()` → `self._config_panel`
  - 删除 `_find_config_panel()` 方法
  - `main_window.py` 的 `_setup_ui()` 中添加 `self.gacha_panel.set_config_panel(self.config_panel)`

### 4.1b gacha_panel.py — SimulationThread 直接接收 ConfigStore，删除 _build_config_store() ✅

- **文件**: `gui/gacha_panel.py`
- **依赖**: 4.1a（已有 _config_panel 引用）
- **风险**: 中 — 需确保 `config_panel.get_store()` 返回的 ConfigStore 与 `_build_config_store()` 构建的内容一致
- **问题**: `SimulationThread` 接收 dict 配置，内部 `_build_config_store()` 约 90 行将 dict→ConfigStore，是 `config_panel.get_config()` 的逆操作，存在数据丢失风险
- **关键差异**: `_build_config_store()` 构建的 ConfigStore 缺少以下字段：`strategy_type`, `strategy_params`, `auto_wait`, `card_weights`, `gain_rules`, `day_overrides`, `resource_defs`, `stop_condition_*`。改用 `config_panel.get_store()` 后这些字段会生效，可能导致模拟结果变化——但这是修正 bug 而非回归
- **修改**:
  - `SimulationThread.__init__` 改为接收 `config_store: ConfigStore` + 模拟参数（`simulation_count, max_workers, seed`），不再接收 dict config
  - `SimulationThread.run()` 中直接使用 `self.config_store`，删除 `config_store = self._build_config_store()`
  - 删除 `_build_config_store()` 方法（约90行）
  - `start_simulation()` 改为 `config_store = self._config_panel.get_store()`，传给 `SimulationThread`

### 4.1c gacha_panel.py — 消除 start_simulation() 双路径写入 ✅

- **文件**: `gui/gacha_panel.py`
- **依赖**: 4.1b（SimulationThread 已直接用 ConfigStore）
- **风险**: 低 — dict 路径在 4.1b 后完全无用
- **问题**: `start_simulation()` 同时操作 dict config 和 ConfigStore store，双路径写入冗余
- **修改**:
  - 删除 `config = config_panel.get_config()` 及对 dict 的操作
  - 删除 `store = config_panel.get_store()` 及对 store 的写入
  - 改为 `config_panel.apply_to_store()` 确保 UI→Store 同步，然后直接从 store 读取模拟参数

---

## 第5层：GUI 面板 set_config_panel 模式统一（与第4层独立）

### 5.1 所有面板 self.window() → self._config_panel 替换 ✅

- **文件**: 4个面板
- **依赖**: 无（与 4.1a/4.1b/4.1c 完全独立）
- **风险**: 极低 — 与 4.1a 同类型，纯引用替换
- **问题**: 4处 `self.window()` 仍存在，通过 QWidget.window() 获取 MainWindow 引用来访问 config_panel
- **修改**:

  **5.1a strategy_panel.py**:
  - 添加 `self._config_panel = None` 和 `set_config_panel(config_panel)` 方法
  - 第566行 `main_window = self.window()` → 使用 `self._config_panel`
  - 添加策略信息显示（正向/反向结果中加"使用策略"行）

  **5.1b resource_search_panel.py**:
  - 添加 `self._config_panel = None` 和 `set_config_panel(config_panel)` 方法
  - 第491行 `main_window = self.window()` → 使用 `self._config_panel`
  - 添加策略信息显示

  **5.1c retreat_panel.py**:
  - 添加 `self._config_panel = None` 和 `set_config_panel(config_panel)` 方法
  - 第236行 `main_window = self.window()` → 使用 `self._config_panel`

  **5.1d worst_impact_panel.py**:
  - 添加 `self._config_panel = None` 和 `set_config_panel(config_panel)` 方法
  - 第379行 `main_window = self.window()` → 使用 `self._config_panel`
  - 添加策略信息显示

---

## 第6层：主窗口连接（依赖第4、5层）

### 6.1 main_window.py — gacha_panel 连接 + 所有面板 set_config_panel 调用 ✅

- **文件**: `gui/main_window.py`
- **依赖**: 4.1a（gacha_panel 有 set_config_panel）、5.1（各面板有 set_config_panel）
- **问题**: 缺少 `gacha_panel.set_config_panel()` 调用；缺少各面板 `set_config_panel()` 调用
- **修改**:
  - 在 `_setup_ui()` 中添加：
    ```python
    self.gacha_panel.set_config_panel(self.config_panel)
    ```
  - 为 strategy_panel、resource_search_panel、retreat_panel、worst_impact_panel 调用 `set_config_panel(self.config_panel)`
  - 在 `_on_config_changed()` 中添加 `self.gacha_panel.set_store(self._store)`（如果 4.1b 添加了 set_store）

---

## 执行顺序总览

```
第1层 (核心)     1.1 strategy.py ✅
                  1.2 vulnerability.py ✅
                  1.3 streaming.py ✅
                  1.4 process_analysis.py ✅
                      │
第2层 (面板适配)  2.1 process_analysis_panel.py ✅ ← 1.4
                      │
第3层 (接口修正)  3.1 retreat_search.py ✅ ← 1.1
                      │
第4层 (GUI重构)   4.1a gacha_panel — 消除 _find_config_panel ← 3.1  [极低风险]
                      │
第5层 (面板统一)  5.1a strategy_panel.py ← 独立  [极低风险]
                  5.1b resource_search_panel.py ← 独立  [极低风险]
                  5.1c retreat_panel.py ← 独立  [极低风险]
                  5.1d worst_impact_panel.py ← 独立  [极低风险]
                      │
第4层续           4.1b gacha_panel — SimulationThread 直接用 ConfigStore ← 4.1a  [中风险]
                      │
                  4.1c gacha_panel — 消除双路径写入 ← 4.1b  [低风险]
                      │
第6层 (主窗口)    6.1 main_window.py ← 4.1a, 5.1
```

## 涉及文件汇总

| 文件 | 涉及修改项 |
|------|-----------|
| `core/strategy.py` | 1.1 ✅ |
| `core/vulnerability.py` | 1.2 ✅ |
| `core/streaming.py` | 1.3 ✅ |
| `core/process_analysis.py` | 1.4 ✅ |
| `gui/process_analysis_panel.py` | 2.1 ✅ |
| `core/retreat_search.py` | 3.1 ✅ |
| `gui/gacha_panel.py` | 4.1a ✅, 4.1b ✅, 4.1c ✅ |
| `gui/strategy_panel.py` | 5.1a ✅ |
| `gui/resource_search_panel.py` | 5.1b ✅ |
| `gui/retreat_panel.py` | 5.1c ✅ |
| `gui/worst_impact_panel.py` | 5.1d ✅ |
| `gui/main_window.py` | 6.1 ✅ |
