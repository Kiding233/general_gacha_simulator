"""chart_spec.py 单元测试——验证各图表类型的 data schema 构造正确。"""
import numpy as np
import pytest

from gacha_simulator.visualization.chart_spec import (
    HistogramData,
    CDFData,
    RidgeData,
    BoxplotData,
    ScatterData,
    BarData,
    HeatmapData,
    Waterfall3DData,
    ChartAnnotation,
    ChartSpec,
    histogram,
    cdf,
    ridge,
    boxplot,
    scatter,
    bar,
    heatmap,
    waterfall_3d,
)


class TestDataClasses:
    """各 data 类的基本构造验证。"""

    def test_histogram_data(self):
        samples = np.array([1.0, 2.0, 3.0, 2.0, 1.0])
        d = HistogramData(samples)
        assert len(d.samples) == 5
        assert d.mean_line is True
        assert d.quantile_lines is None

    def test_histogram_data_with_quantiles(self):
        samples = np.random.randn(100)
        d = HistogramData(samples, quantile_lines=[0.05, 0.95])
        assert d.quantile_lines == [0.05, 0.95]

    def test_cdf_data(self):
        samples = np.array([0.1, 0.5, 0.9])
        d = CDFData(samples)
        assert len(d.samples) == 3

    def test_ridge_data(self):
        d = RidgeData({"A": np.array([1, 2, 3]), "B": np.array([4, 5, 6])})
        assert list(d.series.keys()) == ["A", "B"]

    def test_boxplot_data(self):
        d = BoxplotData({"组1": np.array([1, 2, 3])})
        assert "组1" in d.series

    def test_scatter_data(self):
        d = ScatterData(np.array([1, 2]), np.array([3, 4]), mode="lines+markers")
        assert d.mode == "lines+markers"

    def test_bar_data(self):
        d = BarData(labels=["A", "B"], values=np.array([10, 20]))
        assert d.labels == ["A", "B"]

    def test_heatmap_data(self):
        d = HeatmapData(
            matrix=np.array([[1, 2], [3, 4]]),
            row_labels=["池1", "池2"],
            col_labels=["成功", "失败"],
        )
        assert d.matrix.shape == (2, 2)
        assert d.colorscale == "Viridis"

    def test_heatmap_data_custom_colorscale(self):
        d = HeatmapData(
            matrix=np.zeros((3, 3)),
            row_labels=["a", "b", "c"],
            col_labels=["x", "y", "z"],
            colorscale="Plasma",
        )
        assert d.colorscale == "Plasma"


class TestChartSpec:
    """ChartSpec 构造与元数据验证。"""

    def test_chart_spec_basic(self):
        spec = ChartSpec(
            chart_type="histogram",
            data=HistogramData(np.array([1, 2, 3])),
            title="测试直方图",
            xlabel="值",
            ylabel="频数",
        )
        assert spec.chart_type == "histogram"
        assert isinstance(spec.data, HistogramData)
        assert spec.title == "测试直方图"
        assert spec.xlabel == "值"
        assert spec.annotations == []
        assert spec.layout_hints == {}

    def test_chart_spec_with_annotations(self):
        spec = ChartSpec(
            chart_type="cdf",
            data=CDFData(np.array([0.5])),
            title="CDF",
            annotations=[
                ChartAnnotation(type="vline", value=0.75, text="75%"),
                ChartAnnotation(type="hline", value=0.5, color="blue"),
            ],
        )
        assert len(spec.annotations) == 2
        assert spec.annotations[0].type == "vline"
        assert spec.annotations[0].value == 0.75
        assert spec.annotations[0].text == "75%"

    def test_chart_spec_all_types(self):
        """验证所有图表类型的 ChartSpec 都能正常构造。"""
        specs = [
            ChartSpec("histogram", HistogramData(np.array([1.0])), "h"),
            ChartSpec("cdf", CDFData(np.array([0.5])), "c"),
            ChartSpec("ridge", RidgeData({"a": np.array([1])}), "r"),
            ChartSpec("boxplot", BoxplotData({"a": np.array([1])}), "b"),
            ChartSpec("scatter", ScatterData(np.array([1]), np.array([2])), "s"),
            ChartSpec("bar", BarData(["x"], np.array([1])), "bar"),
            ChartSpec("heatmap", HeatmapData(np.zeros((2, 2)), ["a", "b"], ["c", "d"]), "hm"),
            ChartSpec("waterfall_3d", Waterfall3DData(np.array([1]), np.array([2]), np.array([3])), "w3"),
        ]
        for spec in specs:
            assert isinstance(spec.data, (
                HistogramData, CDFData, RidgeData, BoxplotData,
                ScatterData, BarData, HeatmapData, Waterfall3DData,
            ))


class TestConvenienceFunctions:
    """便捷构造函数测试。"""

    def test_histogram_fn(self):
        spec = histogram(np.array([1, 2, 3]), title="H", xlabel="X")
        assert spec.chart_type == "histogram"
        assert isinstance(spec.data, HistogramData)
        assert spec.title == "H"
        assert spec.xlabel == "X"
        assert spec.ylabel == "频数"

    def test_cdf_fn(self):
        spec = cdf(np.array([0.1, 0.5, 0.9]), title="CDF")
        assert spec.chart_type == "cdf"
        assert isinstance(spec.data, CDFData)

    def test_ridge_fn(self):
        spec = ridge({"A": np.array([1, 2]), "B": np.array([3, 4])}, title="R")
        assert spec.chart_type == "ridge"
        assert isinstance(spec.data, RidgeData)

    def test_boxplot_fn(self):
        spec = boxplot({"组1": np.array([1, 2])})
        assert spec.chart_type == "boxplot"

    def test_scatter_fn_default_mode(self):
        spec = scatter(np.array([1, 2]), np.array([3, 4]))
        assert spec.data.mode == "markers"

    def test_scatter_fn_lines_mode(self):
        spec = scatter(np.array([1, 2]), np.array([3, 4]), mode="lines")
        assert spec.data.mode == "lines"

    def test_bar_fn(self):
        spec = bar(["A", "B"], np.array([10, 20]), title="Bar")
        assert spec.chart_type == "bar"

    def test_heatmap_fn(self):
        spec = heatmap(np.zeros((2, 2)), ["a", "b"], ["c", "d"], colorscale="Plasma")
        assert spec.chart_type == "heatmap"
        assert spec.data.colorscale == "Plasma"

    def test_waterfall_3d_fn(self):
        spec = waterfall_3d(np.array([1]), np.array([2]), np.array([3]), zlabel="Z")
        assert spec.chart_type == "waterfall_3d"
        assert spec.layout_hints["zlabel"] == "Z"


class TestChartAnnotation:
    """ChartAnnotation 基本验证。"""

    def test_vline_annotation(self):
        ann = ChartAnnotation(type="vline", value=0.75, text="75%分位")
        assert ann.type == "vline"
        assert ann.value == 0.75
        assert ann.color == "#ff4444"
        assert ann.dash == "dash"

    def test_hline_annotation(self):
        ann = ChartAnnotation(type="hline", value=0.5, color="blue", dash="solid")
        assert ann.type == "hline"
        assert ann.value == 0.5


class TestEdgeCases:
    """边界情况。"""

    def test_empty_histogram_samples(self):
        d = HistogramData(np.array([]))
        assert len(d.samples) == 0

    def test_nan_in_samples(self):
        samples = np.array([1.0, np.nan, 3.0])
        d = HistogramData(samples)
        assert np.isnan(d.samples[1])

    def test_single_value_histogram(self):
        spec = histogram(np.array([5.0]), title="单值")
        assert len(spec.data.samples) == 1

    def test_large_heatmap(self):
        matrix = np.random.rand(100, 50)
        spec = heatmap(matrix, [f"r{i}" for i in range(100)], [f"c{j}" for j in range(50)])
        assert spec.data.matrix.shape == (100, 50)
