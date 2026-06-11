"""统一分箱模块 —— 所有 GDR 绘图的分箱策略入口。

唯一职责：给定 GDR key + 样本数据，返回正确的分箱策略 (BinningResult)。
纯数据驱动——不做"按 GDR 类型预设分箱策略"。数据长什么样，就怎么画。

使用方式:
    from gacha_simulator.core.gdr_binning import compute_bins

    bin_result = compute_bins(gdr_key, samples, cost_per_draw=160, ...)
    spec = histogram(
        samples=samples, ...,
        density=bin_result.density,
        **bin_result.to_layout_hints(),
    )

参考: docs/01-活跃/subsystems/GDR系统/统一分箱模块重构方案.md
"""

import numpy as np
from dataclasses import dataclass, field
from typing import Optional


# ============================================================
# 数据结构
# ============================================================

@dataclass(frozen=True)
class BinningResult:
    """不可变分箱结果——由 compute_bins() 返回。

    面板永远传 chart_type="histogram" + HistogramData。
    渲染层看 layout_hints["bar_mode"] 决定用 go.Bar 还是 go.Histogram。
    """

    # ── 分箱参数 ──
    bin_edges: Optional[np.ndarray] = None   # None = 委托渲染器默认
    bar_mode: bool = False                   # True → 柱状图 (go.Bar)
    density: bool = True                     # True → 概率密度; False → 频数

    # ── 柱状图专用（bar_mode=True 时） ──
    bar_x: Optional[np.ndarray] = None       # 柱的 x 坐标（= 格点值）
    bar_y: Optional[np.ndarray] = None       # 柱的高度（= 计数）

    # ── 内部使用 ──
    _extra: dict = field(default_factory=dict)  # 额外 layout_hints（nbins 等）

    # ── 元数据 ──
    inf_fraction: Optional[float] = None     # resource_per_card 的 inf 占比
    inf_label: Optional[str] = None          # 图表标注文本，调用方自主决定渲染方式

    def to_layout_hints(self) -> dict:
        """转为可直接合并到 ChartSpec.layout_hints 的字典。"""
        hints = dict(self._extra)
        if self.bin_edges is not None:
            hints["bin_edges"] = self.bin_edges
        if self.bar_mode:
            hints["bar_mode"] = True
            if self.bar_x is not None:
                hints["bar_x"] = self.bar_x
            if self.bar_y is not None:
                hints["bar_y"] = self.bar_y
        hints["density"] = self.density
        return hints


# ============================================================
# 公共函数：步长检测 & 对齐分箱（从 vulnerability.py 迁出）
# ============================================================

def detect_step_size(values: np.ndarray) -> Optional[float]:
    """检测数据的自然步长（格点间距），用于 B₁ 类离散分箱。

    对排序后的相邻差值取众数作为候选步长，同时尝试常见抽卡成本值。
    选择使 std(values % step) / step 最小的步长，且该比值需 < 0.3。
    若无法检测到有效步长，返回 None（调用方回退连续分箱）。
    """
    arr = np.asarray(values, dtype=np.float64)
    if len(arr) < 10:
        return None

    candidates: set[float] = set()

    # 1. 从相邻差值的众数推断
    sorted_vals = np.sort(arr)
    diffs = np.diff(sorted_vals)
    diffs = diffs[diffs > 1e-6]
    if len(diffs) >= 3:
        rounded = np.round(diffs).astype(int)
        uniq, counts = np.unique(rounded, return_counts=True)
        top_indices = np.argsort(counts)[-5:][::-1]
        for idx in top_indices:
            if counts[idx] >= 3:
                candidates.add(float(uniq[idx]))

    # 2. 常见抽卡成本（主候选集）
    common_costs = [160, 280, 300, 100, 200, 60, 120, 150, 180, 80, 140, 220, 240, 260, 320]
    candidates.update(common_costs)
    max_cost = max(common_costs)  # 320——差分候选不应超过此值，避免随机游走伪影

    # 1.5 差分候选限制在 [1, max_cost] 范围，滤除随机游走组合伪影
    candidates = {c for c in candidates if c <= max_cost}

    if not candidates:
        return None

    # 3. 从大到小遍历候选步长，选最大的通过者。
    #    使用「到最近格点距离」替代 arr % step——避免负噪声值的取模包裹
    #    （如 -5 % 160 = 155，严重放大 std）。距离度量为：
    #    dist = |arr/step - round(arr/step)| * step ∈ [0, step/2]
    for step in sorted(candidates, reverse=True):
        dists = np.abs(arr / step - np.round(arr / step)) * step
        ratio = float(np.std(dists)) / step
        if ratio < 0.3:
            return step

    return None


def compute_aligned_bins(values: np.ndarray, step: float) -> np.ndarray:
    """按检测到的步长创建对齐的分箱边界。

    bin 边界对齐到 R₀ + k·step，其中 R₀ = median(values % step)。
    floor((r − R₀) / step) 天然容受日收入等多偏移——偏移不改变 bin 归属。
    """
    r0 = float(np.median(values % step))
    vmin = float(np.min(values))
    vmax = float(np.max(values))

    start = np.floor((vmin - r0) / step) * step + r0
    if start > vmin:
        start -= step
    end = np.ceil((vmax - r0) / step) * step + r0
    if end < vmax:
        end += step
    end += step * 0.5  # 余量确保边界值不落在最后一个 bin 外

    n_edges = int(np.ceil((end - start) / step)) + 1
    return start + np.arange(n_edges, dtype=np.float64) * step


# ============================================================
# 内部函数：各层分箱策略
# ============================================================

def _bins_finite_grid(vals: np.ndarray) -> BinningResult:
    """第一层：有限格点柱状图——每个实际取值一根柱子。

    边界取相邻值的中点，确保间隔不均一也能正确计数。"""
    uniq = np.sort(np.unique(vals))
    n = len(uniq)

    if n == 1:
        edges = np.array([uniq[0] - 0.5, uniq[0] + 0.5], dtype=np.float64)
    else:
        edges = np.empty(n + 1, dtype=np.float64)
        edges[0] = uniq[0] - (uniq[1] - uniq[0]) / 2.0
        for i in range(1, n):
            edges[i] = (uniq[i - 1] + uniq[i]) / 2.0
        edges[n] = uniq[-1] + (uniq[-1] - uniq[-2]) / 2.0

    counts, _ = np.histogram(vals, bins=edges)
    return BinningResult(
        bin_edges=edges,
        bar_mode=True,
        density=False,
        bar_x=uniq.astype(np.float64),
        bar_y=counts.astype(np.int64),
    )


def _bins_continuous(vals: np.ndarray) -> BinningResult:
    """第三层：连续分布分箱（FD 规则 + IQR 集中分布保护）。"""
    n = len(vals)
    if n < 5:
        return BinningResult(bin_edges=None, density=True)

    q1, q3 = np.percentile(vals, [25, 75])
    iqr = max(q3 - q1, 1e-9)
    span = float(np.max(vals)) - float(np.min(vals))

    if span > 0 and iqr / span < 0.05:
        # 高度集中但有离群值——FD 会因 IQR≈0 产生过少 bin
        nbins = max(50, min(200, int(n / 20)))
    else:
        from gacha_simulator.core.distribution import freedman_diaconis_bins
        nbins = freedman_diaconis_bins(vals, min_bins=10, max_bins=200)

    return BinningResult(bin_edges=None, density=True, _extra={'nbins': nbins})


def _bins_stepped(vals: np.ndarray, cost_per_draw: Optional[float],
                  use_draw_units: bool) -> BinningResult:
    """第二层：B₁ 类步长分箱。命中则对齐分箱，未命中回退连续。"""
    if use_draw_units and cost_per_draw and cost_per_draw > 0:
        # 转为抽数单位 → round 取整 → 退化为 Δ=1 整数分箱
        scaled = np.round(vals / cost_per_draw).astype(int)
        lo, hi = int(np.min(scaled)), int(np.max(scaled))
        edges = np.arange(lo - 0.5, hi + 1.5, 1.0, dtype=np.float64)
        return BinningResult(bin_edges=edges, density=False)

    # 有 cost_per_draw 时优先用它作为步长——cost_per_draw 是消费的
    # 基本单位，选它而非更大的倍数可保证每 bin 对应≈1 抽的分辨率。
    # 只在 cost_per_draw 不通过时尝试 2×（数据跨度极大时可能需要）。
    if cost_per_draw and cost_per_draw > 0:
        for multiplier in [1, 2]:  # 优先基本单位，仅在跨度极大时放宽到 2×
            candidate = cost_per_draw * multiplier
            dists = np.abs(vals / candidate - np.round(vals / candidate)) * candidate
            ratio = float(np.std(dists)) / candidate
            if ratio < 0.3:
                edges = compute_aligned_bins(vals, candidate)
                return BinningResult(bin_edges=edges, density=False)

    step = detect_step_size(vals)
    if step is None:
        return _bins_continuous(vals)  # 回退连续

    edges = compute_aligned_bins(vals, step)
    return BinningResult(bin_edges=edges, density=False)


def _bins_with_inf(vals: np.ndarray) -> BinningResult:
    """特殊处理：resource_per_card 的 inf 值分离。"""
    is_inf = ~np.isfinite(vals)
    inf_count = int(np.sum(is_inf))
    inf_frac = inf_count / len(vals)

    finite = vals[~is_inf]
    if len(finite) < 5:
        return BinningResult(
            density=False, bar_mode=False,
            inf_fraction=inf_frac,
            inf_label=f"非有限值: {inf_frac:.1%} ({inf_count}/{len(vals)})",
        )

    base = _bins_continuous(finite)
    return BinningResult(
        bin_edges=base.bin_edges,
        density=base.density,
        _extra=base._extra,
        inf_fraction=inf_frac,
        inf_label=f"inf占比: {inf_frac:.1%} ({inf_count}/{len(vals)})"
                  if inf_frac > 0 else None,
    )


# ============================================================
# 唯一入口
# ============================================================

def compute_bins(
    gdr_key: str,
    samples: np.ndarray,
    *,
    target_specs: Optional[dict] = None,
    cost_per_draw: Optional[float] = None,
    use_draw_units: bool = False,
    fixed_edges: Optional[np.ndarray] = None,
) -> BinningResult:
    """为指定的 GDR 指标计算正确的分箱策略。

    自动检测值域类别，返回包含 bin_edges / density / bar_mode 等信息的 BinningResult。
    所有面板的 GDR 直方图绑图都应调用此函数。

    参数：
        gdr_key: GDR 指标 key（UNIFIED_GDR_REGISTRY 中的键）
        samples: 样本值数组
        target_specs: 目标卡规格 {card_id: quantity}（当前未使用，保留以备未来扩展）
        cost_per_draw: 单抽成本（用于 resource_consumed/remaining 步长检测）
        use_draw_units: 是否将资源值转为抽数单位
        fixed_edges: 外部预计算的统一分箱边界。非 None 时跳过检测，直接使用。
                    用于脆弱性分析保证多个池子使用相同 bin 边界。

    多数据集比较场景：调用方将各组样本合并后传入，bar_mode 时各组共享
    bar_x（合并后格点并集），各自用 bin_edges 计数得到 bar_y。合并后唯一值
    >20 则自然进入连续路径，无需调用方显式指定。
    """
    # 0. 外部预计算边界 → 直接使用，跳过全部检测
    if fixed_edges is not None:
        return BinningResult(
            bin_edges=np.asarray(fixed_edges, dtype=np.float64),
            density=False,
        )

    vals = np.asarray(samples, dtype=np.float64)

    # 0.5 resource_per_card 的 inf 处理
    from .gdr import parse_gdr_key
    if parse_gdr_key(gdr_key)[0] == "resource_per_card" and np.any(~np.isfinite(vals)):
        return _bins_with_inf(vals)

    # 1. 第一层：有限格点检测（全量样本）
    uniq = np.unique(vals)
    if len(uniq) <= 20:
        return _bins_finite_grid(vals)

    # 2. 第二层：步长检测（仅对 B₁ 类有意义，但不预设类型——
    #    对任意 >20 唯一值的数据尝试步长检测，命中则对齐分箱）
    if cost_per_draw is not None or use_draw_units:
        stepped = _bins_stepped(vals, cost_per_draw, use_draw_units)
        if stepped.bin_edges is not None:   # 步长命中
            return stepped

    # 3. 第三层：连续分箱
    return _bins_continuous(vals)
