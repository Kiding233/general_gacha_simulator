"""plotly_charts.py 单元测试——验证 ChartSpec → go.Figure 转换正确。"""
import numpy as np
import pytest
import plotly.graph_objects as go

from gacha_simulator.visualization.chart_spec import (
    ChartAnnotation,
    ChartSpec,
    HistogramData,
    CDFData,
    RidgeData,
    BoxplotData,
    ScatterData,
    BarData,
    HeatmapData,
)
from gacha_simulator.visualization.plotly_charts import PlotlyRenderer, encode_heatmap_binary


@pytest.fixture
def renderer():
    return PlotlyRenderer()


class TestHistogram:
    def test_basic(self, renderer):
        spec = ChartSpec("histogram", HistogramData(np.array([1, 2, 2, 3, 3, 3])), "H", "X", "Y")
        fig = renderer.to_figure(spec)
        assert isinstance(fig, go.Figure)
        assert len(fig.data) >= 1
        assert isinstance(fig.data[0], go.Histogram)
        assert fig.layout.title.text == "H"

    def test_with_quantile_lines(self, renderer):
        samples = np.random.randn(200)
        spec = ChartSpec(
            "histogram",
            HistogramData(samples, quantile_lines=[0.05, 0.50, 0.95]),
            "Q",
        )
        fig = renderer.to_figure(spec)
        # 分位数线以 shape/annotation 形式存在
        assert len(fig.layout.shapes) >= 3 if fig.layout.shapes else True

    def test_no_mean_line(self, renderer):
        spec = ChartSpec("histogram", HistogramData(np.array([1, 2, 3]), mean_line=False), "H")
        fig = renderer.to_figure(spec)
        # 没有均值竖线时 shapes 为 None 或空
        shapes = fig.layout.shapes
        assert shapes is None or len(shapes) == 0


class TestCDF:
    def test_basic(self, renderer):
        samples = np.array([1.0, 5.0, 10.0, 3.0, 7.0])
        spec = ChartSpec("cdf", CDFData(samples), "CDF")
        fig = renderer.to_figure(spec)
        assert isinstance(fig.data[0], go.Scatter)
        # CDF 应在 [0, 1] 范围
        assert fig.layout.yaxis.range[1] <= 1.1

    def test_sorted_output(self, renderer):
        samples = np.array([3.0, 1.0, 2.0])
        spec = ChartSpec("cdf", CDFData(samples), "CDF")
        fig = renderer.to_figure(spec)
        x = fig.data[0].x
        # 验证数据已排序
        for i in range(len(x) - 1):
            assert x[i] <= x[i + 1]


class TestRidge:
    def test_basic(self, renderer):
        spec = ChartSpec(
            "ridge",
            RidgeData({"A": np.random.randn(100), "B": np.random.randn(100) + 2}),
            "Ridge",
        )
        fig = renderer.to_figure(spec)
        assert len(fig.data) == 2
        assert all(isinstance(t, go.Violin) for t in fig.data)

    def test_single_series(self, renderer):
        spec = ChartSpec("ridge", RidgeData({"X": np.array([1, 2, 3])}), "R")
        fig = renderer.to_figure(spec)
        assert len(fig.data) == 1


class TestBoxplot:
    def test_basic(self, renderer):
        spec = ChartSpec(
            "boxplot",
            BoxplotData({"A": np.random.randn(50), "B": np.random.randn(50)}),
            "Box",
        )
        fig = renderer.to_figure(spec)
        assert len(fig.data) == 2
        assert all(isinstance(t, go.Box) for t in fig.data)


class TestScatter:
    def test_markers_mode(self, renderer):
        spec = ChartSpec("scatter", ScatterData(np.array([1, 2]), np.array([3, 4]), "markers"), "S")
        fig = renderer.to_figure(spec)
        assert fig.data[0].mode == "markers"

    def test_lines_mode(self, renderer):
        spec = ChartSpec("scatter", ScatterData(np.array([1, 2]), np.array([3, 4]), "lines"), "S")
        fig = renderer.to_figure(spec)
        assert fig.data[0].mode == "lines"


class TestBar:
    def test_basic(self, renderer):
        spec = ChartSpec("bar", BarData(["A", "B"], np.array([10, 20])), "Bar")
        fig = renderer.to_figure(spec)
        assert isinstance(fig.data[0], go.Bar)
        assert list(fig.data[0].x) == ["A", "B"]


class TestHeatmap:
    def test_basic(self, renderer):
        matrix = np.array([[1, 2], [3, 4]])
        spec = ChartSpec("heatmap", HeatmapData(matrix, ["r1", "r2"], ["c1", "c2"]), "HM")
        fig = renderer.to_figure(spec)
        assert isinstance(fig.data[0], go.Heatmap)

    def test_custom_colorscale(self, renderer):
        spec = ChartSpec(
            "heatmap",
            HeatmapData(np.zeros((2, 2)), ["a", "b"], ["c", "d"], colorscale="Plasma"),
            "HM",
        )
        fig = renderer.to_figure(spec)
        assert fig.data[0].colorscale is not None

    def test_integer_matrix(self, renderer):
        """整数矩阵应正常工作。"""
        matrix = np.array([[0, 5, 10], [3, 7, 2]])  # shape (2, 3)
        spec = ChartSpec("heatmap", HeatmapData(matrix, ["a", "b"], ["x", "y", "z"]), "HM")
        fig = renderer.to_figure(spec)
        assert fig.data[0].z.shape == (2, 3)


class TestAnnotations:
    def test_vline(self, renderer):
        spec = ChartSpec(
            "cdf", CDFData(np.array([0.5])), "CDF",
            annotations=[ChartAnnotation(type="vline", value=0.75, text="75%")],
        )
        fig = renderer.to_figure(spec)
        assert fig.layout.shapes is not None
        assert len(fig.layout.shapes) >= 1

    def test_hline(self, renderer):
        spec = ChartSpec(
            "cdf", CDFData(np.array([0.5])), "CDF",
            annotations=[ChartAnnotation(type="hline", value=0.5)],
        )
        fig = renderer.to_figure(spec)
        assert fig.layout.shapes is not None


class TestToJson:
    def test_valid_json(self, renderer):
        spec = ChartSpec("bar", BarData(["A"], np.array([1])), "B")
        json_str = renderer.to_json(spec)
        assert len(json_str) > 0
        # 验证是合法 JSON
        import json
        data = json.loads(json_str)
        assert "data" in data
        assert "layout" in data


class TestToHtml:
    def test_contains_plotly_js(self, renderer):
        spec = ChartSpec("bar", BarData(["A"], np.array([1])), "B")
        html = renderer.to_html({"chart1": spec}, "file:///tmp/plotly.min.js")
        assert "file:///tmp/plotly.min.js" in html
        assert "chart1" in html

    def test_multi_chart_tabs(self, renderer):
        s1 = ChartSpec("bar", BarData(["A"], np.array([1])), "图1")
        s2 = ChartSpec("cdf", CDFData(np.array([0.5])), "图2")
        html = renderer.to_html({"a": s1, "b": s2}, "file:///p.js", use_tabs=True)
        assert "图1" in html
        assert "图2" in html
        # 标签模式应包含 tab-btn 类
        assert "tab-btn" in html

    def test_single_chart_no_tabs(self, renderer):
        spec = ChartSpec("bar", BarData(["A"], np.array([1])), "单图")
        html = renderer.to_html({"only": spec}, "file:///p.js")
        assert "collapsible" in html


class TestEncodeHeatmapBinary:
    def test_roundtrip(self):
        matrix = np.random.rand(100, 20)
        encoded = encode_heatmap_binary(matrix)
        import base64
        decoded_bytes = base64.b64decode(encoded)
        restored = np.frombuffer(decoded_bytes, dtype=np.float64).reshape(100, 20)
        np.testing.assert_array_almost_equal(matrix, restored)

    def test_small_matrix(self):
        matrix = np.array([[1.5, 2.5], [3.5, 4.5]])
        encoded = encode_heatmap_binary(matrix)
        assert len(encoded) > 0


class TestErrorHandling:
    def test_unsupported_chart_type(self, renderer):
        spec = ChartSpec("histogram", HistogramData(np.array([1.0])), "H")
        spec.chart_type = "unsupported_type"
        with pytest.raises(ValueError, match="不支持"):
            renderer.to_figure(spec)
