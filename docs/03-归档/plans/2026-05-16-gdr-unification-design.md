# GDR 与成功率判断统一管理计划书

## 1. 现状

### 1.1 两套注册表

项目存在两套独立的 GDR（广义出率）注册表，服务于两种不同的计算路径：

| 注册表 | Key 体系 | 条目数 | 值类型 | 计算路径 |
|--------|---------|--------|--------|---------|
| `GDR_REGISTRY` | 中文名 | 11 | `Callable[[List[InfoVector], GDRContext], float]` | 遍历 InfoVector 逐抽记录 |
| `COMPACT_GDR_REGISTRY` | 英文 key | 9 | `Tuple[str, float]`（显示名, 默认阈值） | `compute_gdr_from_compact` 从聚合数据计算 |

**GDR_REGISTRY（11 条）**：

| 中文名 | 函数 | 需要的上下文 |
|--------|------|------------|
| 简单目标达成率 | `simple_target_achievement_rate` | `target_specs` |
| 目标卡收集率 | `target_collection_rate` | `target_specs` |
| 抽出全部目标卡 | `all_targets_obtained` | `target_specs` |
| SSR收集率 | `ssr_collection_rate` | `ssr_ids` |
| 资源剩余 | `resource_remaining` | `initial_resources` |
| 额外目标卡 | `extra_target_cards` | `target_specs` |
| 非保底抽卡数 | `non_pity_draws` | — |
| 保底抽卡数 | `pity_draws` | — |
| 资源转化效率 | `resource_efficiency` | `target_specs` |
| 每池下池出卡率 | `per_pool_draw_rate` | `target_specs` |
| 专武角色比 | `weapon_character_ratio` | `weapon_character_map` |

**COMPACT_GDR_REGISTRY（9 条）**：

| 英文 key | 显示名 | 默认阈值 |
|---------|--------|---------|
| `target_achievement` | 简单目标达成率 | 1.0 |
| `target_collection` | 目标卡收集率 | 1.0 |
| `all_targets` | 抽出全部目标卡 | 1.0 |
| `ssr_collection` | SSR收集率 | 0.05 |
| `resource_remaining` | 资源剩余 | 0.0 |
| `extra_target` | 额外目标卡 | 0.0 |
| `resource_efficiency` | 资源效率 | 0.01 |
| `weighted_satisfaction` | 加权满意度 | 0.0 |
| `total_card_value` | 总出卡价值 | 0.0 |

**两套注册表的差异**：

| 指标 | GDR_REGISTRY | COMPACT_GDR_REGISTRY | 差异说明 |
|------|:---:|:---:|---------|
| 目标卡收集率 | ✅ | ✅ | 已同步 |
| 非保底抽卡数 | ✅ | ❌ | compact 路径用 `pity_triggers` 一个数字替代 |
| 保底抽卡数 | ✅ | ❌ | 同上 |
| 每池下池出卡率 | ✅ | ❌ | compact 路径用 `pool_draw_counts` 替代 |
| 专武角色比 | ✅ | ❌ | `weapon_character_map` 始终为空，未实现 |
| 加权满意度 | ❌（签名不同） | ✅ | GDR_REGISTRY 中有同名函数但需要函数参数 |
| 总出卡价值 | ❌（签名不同） | ✅ | 同上 |

**设计意图**：两套注册表并存是历史演进的结果。最初只有 `GDR_REGISTRY`（InfoVector 路径），后来为 compact 模式新增了 `COMPACT_GDR_REGISTRY` + `compute_gdr_from_compact`。两套服务于不同的数据格式，这是合理的分层。但问题在于**两条路径的计算逻辑存在数值不一致**。

### 1.2 四条计算路径

当前项目中有四条独立的 GDR 计算路径：

| 路径 | 位置 | 输入 | 使用者 |
|------|------|------|--------|
| A: Registry | `GDR_REGISTRY` 函数 | `List[InfoVector]` + `GDRContext` | analysis_panel |
| B: Compact | `compute_gdr_from_compact` | compact dict + 参数 | vulnerability, compute_success_probability |
| C: Checker | `worst_impact._build_success_checker` | compact dict + 参数 | worst_impact |
| D: Panel | `_compute_statistics_unit` | compact → `_compact_to_iv_list` → Registry 函数 | analysis_panel 统计表 |

### 1.3 数值不一致问题

经过逐指标对比，四条路径之间存在多处数值不一致：

#### 极严重（语义错误）

**ssr_collection**：三条路径给出三种不同结果

| 路径 | SSR 识别 | 分子 | 分母 | 语义 |
|------|---------|------|------|------|
| A (Registry) | `ctx.ssr_ids` | SSR 种类数（去重） | `len(ssr_ids)` | SSR 收集率 |
| B (Compact) | `'ssr' in k.lower()` | SSR 抽数（含重复） | `total_draws` | SSR 出卡率 |
| C (Checker) | `self._ssr_ids` | SSR 抽数（含重复） | `total_draws` | SSR 出卡率 |

指标名为"SSR收集率"，但路径 B/C 实际算的是"SSR出卡率"，且 B 的 SSR 识别方式不可靠（字符串匹配）。

**resource_efficiency**：三条路径给出三种不同结果

| 路径 | 分子 | 分母 | 备注 |
|------|------|------|------|
| A (Registry) | `min(count, qty)` 截断 | `_total_resource_consumed`（资源量） | 正确 |
| B (Compact) | 原始计数（无截断） | `total_draws`（抽数） | 分母错误 + 死代码 bug |
| C (Checker) | 原始计数（无截断） | `total_consumed`（资源量） | 分母正确但分子未截断 |

路径 B 中 `consumed_r = total_consumed.get('draw_resource', 0)` 被计算但从未使用，是死代码 bug。

#### 严重（计算逻辑差异）

**target_achievement**：Compact 路径分子未做 min 截断

| 路径 | 分子 | 结果范围 |
|------|------|---------|
| A/D (Registry) | `min(got, qty)` 逐卡截断 | [0, 1] |
| B (Compact) | `sum(card_counts.get(cid, 0))` 无截断 | [0, +∞) |

示例：`target_specs = {'A': 2}`，`card_counts = {'A': 3}` → Registry: 1.0, Compact: 1.5

**all_targets**：Compact 路径使用全局求和

| 路径 | 判定方式 |
|------|---------|
| A/C/D | 逐卡检查 `counts.get(card_id, 0) >= qty` |
| B (Compact) | 全局求和 `sum(counts) >= sum(qty)` |

示例：`target_specs = {'A': 2, 'B': 1}`，`card_counts = {'A': 3, 'B': 0}` → Registry/Checker: 0.0, Compact: 1.0

**extra_target**：Compact 路径使用全局盈余

| 路径 | 计算方式 |
|------|---------|
| A/C/D | 逐卡 `max(got - qty, 0)` 求和 |
| B (Compact) | `max(sum(got) - sum(qty), 0)` |

示例：同上 → Registry/Checker: 1, Compact: 0

#### 中等

**Checker 的 target_achievement 分支**：忽略 gdr_threshold

```python
if gdr_key in ('target_achievement', 'all_targets'):
    return _check_success_from_counts(card_counts, target_specs)
```

`_check_success_from_counts` 等价于 `all_targets_obtained`（全部达成才返回 True），忽略了 `gdr_threshold`。当 threshold=0.5 时，即使只达成了 50% 也会返回 False。

### 1.4 硬编码位置

| # | 文件 | 位置 | 硬编码内容 | 问题 |
|---|------|------|-----------|------|
| 1 | worst_impact.py:176-248 | `_build_success_checker` | 手动重写 9 种 GDR 判断逻辑（~70 行） | 与 compute_gdr_from_compact 不同步 |
| 2 | analysis_panel.py:1756-1779 | `_compute_statistics_unit` | 硬编码 9 个函数列表 | 不用注册表，缺 2 个指标 |
| 3 | analysis_panel.py:1061-1067 | `_CUM_PRECOMPUTED` | 硬编码 5 个累积指标映射 | 不用注册表 |
| 4 | per_pool_analysis.py:196-206 | `success_func` 默认 | 内联"全部达成"逻辑 | 不支持其他 GDR 指标 |
| 5 | analysis_panel.py:1324-1389 | GDR 下拉列表 | 使用 GDR_REGISTRY 中文名 | 与其他面板用的 COMPACT_GDR_REGISTRY 不同 |
| 6 | analysis_panel.py:1566-1594 | `_on_preset_threshold` | 使用 GDR_REGISTRY | 同上 |

### 1.5 成功判断逻辑的分布

| 位置 | 方式 | 是否统一 | 数值正确性 |
|------|------|---------|-----------|
| vulnerability.py:53 `_is_success` | 调用 `compute_gdr_from_compact` | ✅ | ⚠️ 继承 B 路径的 bug |
| worst_impact.py:176 `_build_success_checker` | 手动重写 | ❌ | ⚠️ 部分正确（比 B 好，但 target_achievement 忽略 threshold） |
| gdr.py:416 `compute_success_probability` | 调用 `compute_gdr_from_compact` | ✅ | ⚠️ 继承 B 路径的 bug |
| analysis_panel.py:1752 `_compute_statistics_unit` | 硬编码 9 个函数 | ❌ | ✅ 走 A 路径，正确 |
| per_pool_analysis.py:201 `success_func` 默认 | 内联逻辑 | ❌ | ⚠️ 只支持"全部达成" |

## 2. 目标

1. **消除所有硬编码**：所有 GDR 指标列表和成功判断逻辑都从注册表动态生成
2. **统一注册表**：合并为单一注册表，或至少使得同步变得简单且自动化
3. **统一成功判断模块**：所有"是否成功"的判断都通过一个可复用的模块完成
4. **修复数值不一致**：确保所有路径对同一指标给出相同结果

## 3. 设计方案

### 3.1 统一注册表：UNIFIED_GDR_REGISTRY

**核心思路**：将两套注册表合并为一张表，每条记录包含两种计算路径所需的所有信息。

```python
from typing import List, Dict, Set, Optional, Callable, Any, Tuple, NamedTuple

class GDRDefinition(NamedTuple):
    key: str
    display_name: str
    default_threshold: float
    compute_from_compact: Callable[..., float]
    compute_from_history: Optional[Callable[..., float]] = None
    needs_ssr_ids: bool = False
    needs_weights: str = ''
    category: str = 'basic'

UNIFIED_GDR_REGISTRY: Dict[str, GDRDefinition] = {
    'target_achievement': GDRDefinition(
        key='target_achievement',
        display_name='简单目标达成率',
        default_threshold=1.0,
        compute_from_compact=_gdr_target_achievement,
        compute_from_history=simple_target_achievement_rate,
        category='basic',
    ),
    'target_collection': GDRDefinition(
        key='target_collection',
        display_name='目标卡收集率',
        default_threshold=1.0,
        compute_from_compact=_gdr_target_collection,
        compute_from_history=target_collection_rate,
        category='basic',
    ),
    'all_targets': GDRDefinition(
        key='all_targets',
        display_name='抽出全部目标卡',
        default_threshold=1.0,
        compute_from_compact=_gdr_all_targets,
        compute_from_history=all_targets_obtained,
        category='basic',
    ),
    'ssr_collection': GDRDefinition(
        key='ssr_collection',
        display_name='SSR收集率',
        default_threshold=0.05,
        compute_from_compact=_gdr_ssr_collection,
        compute_from_history=ssr_collection_rate,
        needs_ssr_ids=True,
        category='basic',
    ),
    'resource_remaining': GDRDefinition(
        key='resource_remaining',
        display_name='资源剩余',
        default_threshold=0.0,
        compute_from_compact=_gdr_resource_remaining,
        compute_from_history=resource_remaining,
        category='basic',
    ),
    'extra_target': GDRDefinition(
        key='extra_target',
        display_name='额外目标卡',
        default_threshold=0.0,
        compute_from_compact=_gdr_extra_target,
        compute_from_history=extra_target_cards,
        category='basic',
    ),
    'non_pity_draws': GDRDefinition(
        key='non_pity_draws',
        display_name='非保底抽卡数',
        default_threshold=0.0,
        compute_from_compact=_gdr_non_pity_draws,
        compute_from_history=non_pity_draws,
        category='basic',
    ),
    'pity_draws': GDRDefinition(
        key='pity_draws',
        display_name='保底抽卡数',
        default_threshold=0.0,
        compute_from_compact=_gdr_pity_draws,
        compute_from_history=pity_draws,
        category='basic',
    ),
    'resource_efficiency': GDRDefinition(
        key='resource_efficiency',
        display_name='资源转化效率',
        default_threshold=0.01,
        compute_from_compact=_gdr_resource_efficiency,
        compute_from_history=resource_efficiency,
        category='basic',
    ),
    'per_pool_draw_rate': GDRDefinition(
        key='per_pool_draw_rate',
        display_name='每池下池出卡率',
        default_threshold=0.0,
        compute_from_compact=_gdr_per_pool_draw_rate,
        compute_from_history=per_pool_draw_rate,
        category='basic',
    ),
    'weapon_character_ratio': GDRDefinition(
        key='weapon_character_ratio',
        display_name='专武角色比',
        default_threshold=0.0,
        compute_from_compact=_gdr_weapon_character_ratio,
        compute_from_history=weapon_character_ratio,
        category='basic',
    ),
    'weighted_satisfaction': GDRDefinition(
        key='weighted_satisfaction',
        display_name='加权满意度',
        default_threshold=0.0,
        compute_from_compact=_gdr_weighted_satisfaction,
        compute_from_history=None,
        needs_weights='desire+miss_cost',
        category='weighted',
    ),
    'total_card_value': GDRDefinition(
        key='total_card_value',
        display_name='总出卡价值',
        default_threshold=0.0,
        compute_from_compact=_gdr_total_card_value,
        compute_from_history=None,
        needs_weights='card_value',
        category='weighted',
    ),
}
```

**设计要点**：

1. **统一 key 体系**：使用英文 key（与 COMPACT_GDR_REGISTRY 一致），因为 key 是程序内部使用的标识符，英文更稳定
2. **保留两种计算函数**：`compute_from_compact` 和 `compute_from_history`，分别服务于两种数据格式
3. **元数据集中管理**：`display_name`、`default_threshold`、`needs_ssr_ids`、`needs_weights`、`category` 等元数据只定义一次
4. **向后兼容**：保留 `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY` 作为视图（从 `UNIFIED_GDR_REGISTRY` 动态生成），不破坏现有代码

### 3.2 向后兼容视图

```python
def _build_legacy_registries():
    gdr_registry = {}
    compact_gdr_registry = {}
    for key, defn in UNIFIED_GDR_REGISTRY.items():
        compact_gdr_registry[key] = (defn.display_name, defn.default_threshold)
        if defn.compute_from_history is not None:
            gdr_registry[defn.display_name] = defn.compute_from_history
    return gdr_registry, compact_gdr_registry

GDR_REGISTRY, COMPACT_GDR_REGISTRY = _build_legacy_registries()
```

这样所有现有代码中 `from gacha_simulator.core.gdr import GDR_REGISTRY` 的引用仍然有效，且内容自动与 `UNIFIED_GDR_REGISTRY` 同步。

### 3.3 修复 compute_from_compact 函数

每个 `_gdr_*` 函数必须与对应的 `compute_from_history` 函数给出**完全一致**的数值结果。以下是修复方案：

#### _gdr_target_achievement（修复：分子 min 截断）

```python
def _gdr_target_achievement(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    total = sum(target_specs.values())
    if total == 0:
        return 0.0
    achieved = sum(min(card_counts.get(cid, 0), qty) for cid, qty in target_specs.items())
    return achieved / total
```

#### _gdr_all_targets（修复：逐卡检查）

```python
def _gdr_all_targets(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    for cid, qty in target_specs.items():
        if card_counts.get(cid, 0) < qty:
            return 0.0
    return 1.0
```

#### _gdr_ssr_collection（修复：改为收集率语义 + 使用 ssr_ids）

```python
def _gdr_ssr_collection(compact, target_specs, ssr_ids=None, **kwargs):
    card_counts = compact.get('card_counts', {})
    if not ssr_ids:
        return 0.0
    collected = sum(1 for cid in ssr_ids if card_counts.get(cid, 0) > 0)
    return collected / len(ssr_ids)
```

#### _gdr_extra_target（修复：逐卡盈余）

```python
def _gdr_extra_target(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    extra = 0
    for cid, qty in target_specs.items():
        got = card_counts.get(cid, 0)
        if got > qty:
            extra += got - qty
    return float(extra)
```

#### _gdr_resource_efficiency（修复：分子截断 + 分母用资源消耗量）

```python
def _gdr_resource_efficiency(compact, target_specs, **kwargs):
    card_counts = compact.get('card_counts', {})
    total_consumed = compact.get('total_consumed', {})
    achieved = sum(min(card_counts.get(cid, 0), qty) for cid, qty in target_specs.items())
    consumed = total_consumed.get('draw_resource', 0)
    return achieved / consumed if consumed > 0 else 0.0
```

#### _gdr_non_pity_draws / _gdr_pity_draws（新增）

```python
def _gdr_non_pity_draws(compact, **kwargs):
    return float(compact.get('total_draws', 0) - compact.get('pity_triggers', 0))

def _gdr_pity_draws(compact, **kwargs):
    return float(compact.get('pity_triggers', 0))
```

#### _gdr_per_pool_draw_rate（新增）

```python
def _gdr_per_pool_draw_rate(compact, target_specs, **kwargs):
    pool_draw_counts = compact.get('pool_draw_counts', {})
    pool_card_counts = compact.get('pool_card_counts', {})
    target_ids = set(target_specs.keys())
    pools_with_draws = sum(1 for c in pool_draw_counts.values() if c > 0)
    if pools_with_draws == 0:
        return 0.0
    total_target_draws = sum(
        sum(cnt for cid, cnt in pool_cards.items() if cid in target_ids)
        for pool_cards in pool_card_counts.values()
    )
    return total_target_draws / pools_with_draws
```

#### _gdr_weapon_character_ratio（新增）

```python
def _gdr_weapon_character_ratio(compact, weapon_character_map=None, **kwargs):
    if not weapon_character_map:
        return 0.0
    card_counts = compact.get('card_counts', {})
    char_ids = set(weapon_character_map.values())
    char_count = sum(card_counts.get(cid, 0) for cid in char_ids)
    if char_count == 0:
        return 0.0
    weapon_count = 0
    for weapon_id, char_id in weapon_character_map.items():
        if card_counts.get(char_id, 0) > 0:
            weapon_count += card_counts.get(weapon_id, 0)
    return weapon_count / char_count
```

#### _gdr_weighted_satisfaction / _gdr_total_card_value（保留，已正确）

这两个函数的逻辑与 Registry 版本一致，无需修改。

### 3.4 统一成功判断模块：SuccessChecker

```python
class SuccessChecker:
    """统一的成功判断器。封装 GDR 计算 + 阈值比较。"""

    def __init__(self, target_specs, gdr_key='target_achievement',
                 gdr_threshold=None,
                 desire_weights=None, miss_cost_weights=None,
                 card_value_weights=None, ssr_ids=None,
                 weapon_character_map=None):
        self.target_specs = target_specs
        self.gdr_key = gdr_key
        self.desire_weights = desire_weights
        self.miss_cost_weights = miss_cost_weights
        self.card_value_weights = card_value_weights
        self.ssr_ids = ssr_ids
        self.weapon_character_map = weapon_character_map

        if gdr_threshold is None:
            defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
            self.gdr_threshold = defn.default_threshold if defn else 1.0
        else:
            self.gdr_threshold = gdr_threshold

    def compute_gdr(self, compact_or_aggregate):
        """计算单个结果的 GDR 值。兼容 compact dict 和 aggregate 数据。"""
        defn = UNIFIED_GDR_REGISTRY.get(self.gdr_key)
        if defn is None:
            return 0.0
        return defn.compute_from_compact(
            compact_or_aggregate,
            target_specs=self.target_specs,
            desire_weights=self.desire_weights,
            miss_cost_weights=self.miss_cost_weights,
            card_value_weights=self.card_value_weights,
            ssr_ids=self.ssr_ids,
            weapon_character_map=self.weapon_character_map,
        )

    def is_success(self, compact_or_aggregate):
        """判断单个结果是否成功。"""
        return self.compute_gdr(compact_or_aggregate) >= self.gdr_threshold

    def check_batch(self, results):
        """批量判断，返回 (success_count, total_count, probability)。"""
        total = 0
        success = 0
        for r in results:
            if r is not None:
                total += 1
                if self.is_success(r):
                    success += 1
        prob = success / total if total > 0 else 0.0
        return success, total, prob

    @classmethod
    def from_registry(cls, gdr_key, target_specs, gdr_threshold=None, **kwargs):
        """从 UNIFIED_GDR_REGISTRY 创建，自动填充默认阈值。"""
        return cls(target_specs=target_specs, gdr_key=gdr_key,
                   gdr_threshold=gdr_threshold, **kwargs)
```

### 3.5 重写 compute_gdr_from_compact

```python
def compute_gdr_from_compact(compact, target_specs, gdr_key='target_achievement',
                              desire_weights=None, miss_cost_weights=None,
                              card_value_weights=None, ssr_ids=None,
                              weapon_character_map=None):
    """从 compact dict 或 aggregate 数据计算 GDR 值。

    所有计算逻辑委托给 UNIFIED_GDR_REGISTRY 中注册的 compute_from_compact 函数，
    确保与 compute_from_history 路径的数值一致性。
    """
    defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
    if defn is None:
        return 0.0
    return defn.compute_from_compact(
        compact, target_specs=target_specs,
        desire_weights=desire_weights, miss_cost_weights=miss_cost_weights,
        card_value_weights=card_value_weights, ssr_ids=ssr_ids,
        weapon_character_map=weapon_character_map,
    )
```

### 3.6 消除硬编码的具体方案

#### 硬编码 1：worst_impact._build_success_checker

**当前**：~70 行手动重写 9 种 GDR 判断逻辑

**替换为**：

```python
def _build_success_checker(self):
    self._checker = SuccessChecker(
        target_specs=self.target_specs,
        gdr_key=self.gdr_key,
        gdr_threshold=self.gdr_threshold,
        desire_weights=self.desire_weights,
        miss_cost_weights=self.miss_cost_weights,
        card_value_weights=self.card_value_weights,
        ssr_ids=self._ssr_ids,
    )
    return self._checker.is_success
```

#### 硬编码 2：analysis_panel._compute_statistics_unit

**当前**：硬编码 9 个函数列表

**替换为**：

```python
def _compute_statistics_unit(self):
    if not self.results or not self._gdr_context:
        return
    import numpy as np
    results = self.results
    if results and isinstance(results[0], dict):
        pass
    else:
        return

    target_specs = self._gdr_context.target_specs
    ssr_ids = self._gdr_context.ssr_ids

    headers = ["指标", "均值", "中位数", "标准差"]
    rows = []
    self._summary_data = {}

    for key, defn in UNIFIED_GDR_REGISTRY.items():
        try:
            vals = []
            for r in results:
                v = compute_gdr_from_compact(
                    r, target_specs, key,
                    ssr_ids=ssr_ids,
                    desire_weights=self._desire_weights,
                    miss_cost_weights=self._miss_cost_weights,
                    card_value_weights=self._card_value_weights,
                )
                vals.append(v)
            mean_val = np.mean(vals)
            median_val = np.median(vals)
            std_val = np.std(vals)
            rows.append([defn.display_name, f"{mean_val:.4f}", f"{median_val:.4f}", f"{std_val:.4f}"])
            self._summary_data[defn.display_name] = {'mean': f"{mean_val:.4f}"}
        except Exception:
            rows.append([defn.display_name, "-", "-", "-"])
            self._summary_data[defn.display_name] = {'mean': "-"}
```

#### 硬编码 3：analysis_panel._CUM_PRECOMPUTED

**当前**：硬编码 5 个累积指标映射

**替换为**：不再需要预计算映射。流式重构后，累积快照包含 `cumulative_card_counts` + `cumulative_consumed`，可以直接用 `compute_gdr_from_compact` 计算任意 GDR 指标。

```python
for metric_key in self.cumulative_by_pool_selections:
    defn = UNIFIED_GDR_REGISTRY.get(metric_key)
    if not defn:
        pool_dists.append([])
        continue
    pool_dists = []
    for pid in pool_ids:
        raw = []
        for snap in cumulative_snapshots.get(pid, []):
            v = defn.compute_from_compact(snap, target_specs=target_specs, ...)
            raw.append(v)
        pool_dists.append(raw)
```

#### 硬编码 4：per_pool_analysis.success_func 默认

**当前**：内联"全部达成"逻辑

**替换为**：

```python
if success_func is None:
    checker = SuccessChecker(target_specs=ctx.target_specs, gdr_key='all_targets')
    def success_func(history_or_compact, end_time):
        return checker.is_success(history_or_compact)
```

#### 硬编码 5-6：analysis_panel GDR 下拉列表和预设阈值

**当前**：使用 `GDR_REGISTRY` 中文名

**替换为**：使用 `UNIFIED_GDR_REGISTRY` 的 `display_name`

```python
_gdr_items = [(defn.key, defn.display_name) for defn in UNIFIED_GDR_REGISTRY.values()]
_gdr_names = [name for _, name in _gdr_items]
# 用于 primary_gdr_combo, cond_gdr_combo, target_gdr_combo 等
```

预设阈值改为使用 `compute_gdr_from_compact`：

```python
def _on_preset_threshold(self, preset_type):
    if not self.results:
        return
    gdr_key = self.cond_gdr_combo.currentData()
    defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
    if not defn:
        return
    vals = [compute_gdr_from_compact(h, target_specs, gdr_key, ...) for h in self.results]
    dist = EmpiricalDistribution(vals)
    ...
```

### 3.7 UI 下拉列表统一

当前 5 个面板使用 `COMPACT_GDR_REGISTRY` 生成下拉列表，1 个面板（analysis_panel）使用 `GDR_REGISTRY`。统一后所有面板都使用 `UNIFIED_GDR_REGISTRY`：

```python
# 统一的 GDR 下拉列表生成方式
def populate_gdr_combo(combo: QComboBox):
    combo.clear()
    for key, defn in UNIFIED_GDR_REGISTRY.items():
        combo.addItem(defn.display_name, key)

# 统一的默认阈值获取方式
def get_default_threshold(gdr_key: str) -> float:
    defn = UNIFIED_GDR_REGISTRY.get(gdr_key)
    return defn.default_threshold if defn else 1.0
```

## 4. 实施步骤

### Task 1：创建 UNIFIED_GDR_REGISTRY + 修复 compute_from_compact

**目标**：合并两套注册表，修复所有数值不一致

**内容**：

1. 在 `core/gdr.py` 中新增 `GDRDefinition` 类和 `UNIFIED_GDR_REGISTRY`
2. 新增 13 个 `_gdr_*` 函数，每个都与对应的 `compute_from_history` 函数数值一致
3. 重写 `compute_gdr_from_compact`，委托给 `UNIFIED_GDR_REGISTRY`
4. 从 `UNIFIED_GDR_REGISTRY` 动态生成 `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY`（向后兼容）
5. 新增 `SuccessChecker` 类

**关键修复**：
- `target_achievement`：分子加 min 截断
- `all_targets`：改为逐卡检查
- `ssr_collection`：改为收集率语义 + 使用 ssr_ids 参数
- `extra_target`：改为逐卡盈余
- `resource_efficiency`：分子加 min 截断 + 分母改为资源消耗量

**验证**：
- 对每个指标，构造测试数据，验证 `compute_from_compact` 与 `compute_from_history` 给出相同结果
- 验证 `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY` 的内容与改造前一致（除 bug 修复外）
- 验证 `SuccessChecker.is_success` 与直接调用 `compute_gdr_from_compact` 结果一致

**产出文件**：修改 `core/gdr.py`

### Task 2：worst_impact.py 去重

**目标**：用 `SuccessChecker` 替换 `_build_success_checker` 的 70 行重复逻辑

**内容**：

1. 删除 `_build_success_checker` 方法
2. 删除 `_check_success_from_counts` 函数
3. 在 `__init__` 中创建 `SuccessChecker` 实例
4. 所有调用 `self._success_checker(result)` 的地方改为 `self._checker.is_success(result)`

**验证**：
- worst_impact 分析结果与改造前一致（除 bug 修复导致的预期变化外）
- 特别是 `target_achievement` + threshold < 1.0 的场景现在能正确工作

**产出文件**：修改 `core/worst_impact.py`

### Task 3：analysis_panel.py 去硬编码

**目标**：消除 4 处硬编码

**内容**：

1. `_compute_statistics_unit`：改为遍历 `UNIFIED_GDR_REGISTRY`，使用 `compute_gdr_from_compact`
2. `_CUM_PRECOMPUTED`：删除，改为使用 `compute_gdr_from_compact` 直接计算
3. GDR 下拉列表：改为使用 `UNIFIED_GDR_REGISTRY` 的 `(key, display_name)` 对
4. `_on_preset_threshold`：改为使用 `compute_gdr_from_compact`

**验证**：
- 统计表指标数 = `UNIFIED_GDR_REGISTRY` 条目数（13 条）
- 累积分析支持所有 GDR 指标
- 预设阈值功能正常

**产出文件**：修改 `gui/analysis_panel.py`

### Task 4：per_pool_analysis.py 去硬编码

**目标**：用 `SuccessChecker` 替换内联成功逻辑

**内容**：

1. `compute_transition_matrices` 的 `success_func` 默认值改为使用 `SuccessChecker`

**验证**：
- 转变分析结果与改造前一致

**产出文件**：修改 `core/per_pool_analysis.py`

### Task 5：其他面板适配

**目标**：确保所有面板使用 `UNIFIED_GDR_REGISTRY` 生成下拉列表

**内容**：

1. retreat_panel.py：改为使用 `populate_gdr_combo` 和 `get_default_threshold`
2. worst_impact_panel.py：同上
3. strategy_panel.py：同上
4. resource_search_panel.py：同上
5. retreat_search_panel.py：同上

**验证**：
- 所有面板的 GDR 下拉列表条目数 = `UNIFIED_GDR_REGISTRY` 条目数
- 默认阈值与改造前一致

**产出文件**：修改 5 个面板文件

### Task 6：向后兼容验证 + 清理

**目标**：确保所有现有功能正常，清理废弃代码

**内容**：

1. 验证 `GDR_REGISTRY` 和 `COMPACT_GDR_REGISTRY` 的向后兼容视图正常
2. 验证 `compute_success_probability` 正常工作
3. 删除 `compute_gdr_from_compact` 中旧的 if-elif 链（已被 `UNIFIED_GDR_REGISTRY` 委托替代）
4. 更新 `core/__init__.py` 的导出列表

**验证**：
- 全量回归测试
- 所有面板功能正常

**产出文件**：修改 `core/gdr.py`、`core/__init__.py`

## 5. 执行顺序

```
Task 1 (UNIFIED_GDR_REGISTRY + SuccessChecker + 修复数值不一致)
    ↓
Task 2 (worst_impact 去重)    Task 3 (analysis_panel 去硬编码)    Task 4 (per_pool 去硬编码)
    ↓                               ↓                                  ↓
Task 5 (其他面板适配)
    ↓
Task 6 (向后兼容验证 + 清理)
```

Task 2/3/4 依赖 Task 1，可并行。Task 5 依赖 Task 1。Task 6 依赖所有前置任务。

## 6. 风险与注意事项

### 6.1 数值修复导致的预期变化

以下修复会导致分析结果发生变化（但变化是正确的）：

| 修复 | 影响范围 | 变化方向 |
|------|---------|---------|
| target_achievement min 截断 | 所有使用该指标的分析 | 部分样本的值从 >1.0 降为 1.0 |
| all_targets 逐卡检查 | worst_impact, vulnerability | 某些样本从"成功"变为"失败" |
| ssr_collection 语义修正 | 所有使用该指标的分析 | 数值从"出卡率"量级变为"收集率"量级 |
| extra_target 逐卡盈余 | 所有使用该指标的分析 | 某些样本的值增大（不再被亏损抵消） |
| resource_efficiency 分母修正 | 所有使用该指标的分析 | 数值从"抽数"量级变为"资源量"量级 |

**建议**：在实施前向用户说明这些变化，确认接受后再执行。

### 6.2 ssr_ids 传递

当前 `compute_gdr_from_compact` 不接受 `ssr_ids` 参数。修复后需要所有调用方传递 `ssr_ids`。受影响的位置：

- `vulnerability.py:_is_success` — 需要新增 `ssr_ids` 参数
- `gdr.py:compute_success_probability` — 需要新增 `ssr_ids` 参数
- `worst_impact.py` — 已有 `self._ssr_ids`
- `analysis_panel.py` — 可从 `self._gdr_context.ssr_ids` 获取

### 6.3 weapon_character_map 传递

当前 `weapon_character_map` 始终为空字典。统一后需要所有调用方传递此参数。受影响的位置同上。

### 6.4 compact dict 新增字段

`_gdr_per_pool_draw_rate` 需要 `pool_card_counts` 字段，该字段目前不存在于 compact dict 中。需要与流式重构计划中的 Task 2（compact 新增字段）协调。

## 7. 与流式重构计划的关系

本计划与流式重构计划（`specs/2026-05-16-streaming-refactor-design.md`）高度相关：

| 本计划 | 流式重构 | 关系 |
|--------|---------|------|
| Task 1: UNIFIED_GDR_REGISTRY | Task 3: GDR 注册表修补 | 合并，本计划更全面 |
| Task 2: worst_impact 去重 | Task 3: worst_impact 去重 | 相同 |
| Task 3: analysis_panel 去硬编码 | Task 5: analysis_panel 改造 | 本计划是前置条件 |
| SuccessChecker | StreamingSuccessCounter | SuccessChecker 是 StreamingSuccessCounter 的核心组件 |

**建议执行顺序**：先执行本计划（Task 1-6），再执行流式重构。因为：
1. 流式重构需要 `compute_gdr_from_compact` 的数值正确性作为基础
2. `SuccessChecker` 是 `StreamingSuccessCounter` 的核心组件
3. 统一注册表后，流式重构的提取函数设计更简单
