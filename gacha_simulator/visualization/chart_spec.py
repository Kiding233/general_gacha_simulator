"""图表中间表示——面板与渲染层之间的纯数据桥梁，零外部依赖。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal, Union

import numpy as np


# ── 各图表类型的类型化 data 载荷 ──────────────────────────────────────────

@dataclass
class HistogramData:
    """直方图数据。"""
    samples: np.ndarray          # 样本值数组
    mean_line: bool = True       # 是否绘制均值竖线
    quantile_lines: list[float] | None = None  # 分位数线列表，如 [0.05, 0.95]


@dataclass
class CDFData:
    """经验累积分布函数数据。"""
    samples: np.ndarray


@dataclass
class RidgeData:
    """山脊线图数据——多组样本按标签叠加。"""
    series: dict[str, np.ndarray]  # {标签: 样本数组}


@dataclass
class BoxplotData:
    """箱线图数据。"""
    series: dict[str, np.ndarray]  # {标签: 样本数组}


@dataclass
class ScatterTrace:
    """散点图单条轨迹。"""
    x: np.ndarray
    y: np.ndarray
    mode: str = "markers"
    name: str = ""
    marker_symbol: str = "circle"
    marker_size: int = 7
    marker_color: str | None = None
    line_color: str | None = None


@dataclass
class ScatterData:
    """散点/折线图数据。支持单轨迹（x/y）和多轨迹（traces）两种模式。"""
    x: np.ndarray | None = None
    y: np.ndarray | None = None
    mode: str = "markers"
    traces: list[ScatterTrace] | None = None     # 多轨迹模式
    color_values: np.ndarray | None = None       # 颜色映射值（散点着色用）
    colorscale: str = "RdYlGn"                    # 颜色映射名称
    colorbar_title: str = ""                      # 颜色条标题


@dataclass
class BarData:
    """条形图数据。"""
    labels: list[str]
    values: np.ndarray


@dataclass
class HeatmapData:
    """热力图数据。"""
    matrix: np.ndarray                       # 2D 数组 (rows × cols)
    row_labels: list[str]
    col_labels: list[str]
    colorscale: str = "Viridis"


@dataclass
class Waterfall3DData:
    """3D 瀑布图数据。"""
    x: np.ndarray          # 池子索引
    y: np.ndarray          # 资源值
    z: np.ndarray          # 模拟次数 / 计数


# ── Union 类型别名 ─────────────────────────────────────────────────────

ChartData = Union[
    HistogramData,
    CDFData,
    RidgeData,
    BoxplotData,
    ScatterData,
    BarData,
    HeatmapData,
    Waterfall3DData,
]

ChartType = Literal[
    "histogram", "cdf", "ridge", "boxplot",
    "scatter", "bar", "heatmap", "waterfall_3d",
]


# ── 注解类型 ───────────────────────────────────────────────────────────

@dataclass
class ChartAnnotation:
    """图表参考线/标注。"""
    type: Literal["vline", "hline"]
    value: float                    # x（vline）或 y（hline）坐标
    color: str = "#ff4444"
    dash: Literal["solid", "dash", "dot", "dashdot"] = "dash"
    text: str = ""


# ── ChartSpec ──────────────────────────────────────────────────────────

@dataclass
class ChartSpec:
    """面板与渲染层之间的中间表示，纯数据，不依赖任何绑图库。"""
    chart_type: ChartType
    data: ChartData
    title: str
    xlabel: str = ""
    ylabel: str = ""
    annotations: list[ChartAnnotation] = field(default_factory=list)
    layout_hints: dict = field(default_factory=dict)
    # layout_hints 可包含: figsize=(w, h), nbins=int, color=str, 等渲染提示


# ── 便捷构造函数 ───────────────────────────────────────────────────────


def histogram(
    samples: np.ndarray,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "频数",
    mean_line: bool = True,
    quantile_lines: list[float] | None = None,
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="histogram",
        data=HistogramData(samples, mean_line=mean_line, quantile_lines=quantile_lines),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def cdf(
    samples: np.ndarray,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "累积概率",
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="cdf",
        data=CDFData(samples),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def ridge(
    series: dict[str, np.ndarray],
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="ridge",
        data=RidgeData(series),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def boxplot(
    series: dict[str, np.ndarray],
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="boxplot",
        data=BoxplotData(series),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def scatter(
    x: np.ndarray,
    y: np.ndarray,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    mode: str = "markers",
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="scatter",
        data=ScatterData(x=x, y=y, mode=mode),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def scatter_multi(
    traces: list[ScatterTrace],
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    **layout_hints,
) -> ChartSpec:
    """多轨迹散点图，每个 ScatterTrace 为一条独立轨迹。"""
    return ChartSpec(
        chart_type="scatter",
        data=ScatterData(traces=traces),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def scatter_colored(
    x: np.ndarray,
    y: np.ndarray,
    color_values: np.ndarray,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    colorscale: str = "RdYlGn",
    colorbar_title: str = "",
    mode: str = "markers",
    **layout_hints,
) -> ChartSpec:
    """带颜色映射的散点图。"""
    return ChartSpec(
        chart_type="scatter",
        data=ScatterData(
            x=x, y=y, mode=mode,
            color_values=color_values, colorscale=colorscale,
            colorbar_title=colorbar_title,
        ),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def bar(
    labels: list[str],
    values: np.ndarray,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="bar",
        data=BarData(labels, values),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def heatmap(
    matrix: np.ndarray,
    row_labels: list[str],
    col_labels: list[str],
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    colorscale: str = "Viridis",
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="heatmap",
        data=HeatmapData(matrix, row_labels, col_labels, colorscale),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints=layout_hints,
    )


def waterfall_3d(
    x: np.ndarray,
    y: np.ndarray,
    z: np.ndarray,
    title: str = "",
    xlabel: str = "",
    ylabel: str = "",
    zlabel: str = "",
    **layout_hints,
) -> ChartSpec:
    return ChartSpec(
        chart_type="waterfall_3d",
        data=Waterfall3DData(x, y, z),
        title=title, xlabel=xlabel, ylabel=ylabel,
        layout_hints={"zlabel": zlabel, **layout_hints},
    )
