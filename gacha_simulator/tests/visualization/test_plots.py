"""旧 matplotlib 绑图测试已迁移至 test_chart_spec.py 和 test_plotly_charts.py。
此文件保留为占位，确保 test_plots 模块可被 pytest 发现。"""
import numpy as np


def test_chart_spec_histogram_roundtrip():
    """验证 ChartSpec hist 数据可正确构造。"""
    from gacha_simulator.visualization.chart_spec import histogram, HistogramData
    samples = np.array([1, 1, 2, 2, 2, 3])
    spec = histogram(samples, title="测试分布")
    assert spec.chart_type == "histogram"
    assert isinstance(spec.data, HistogramData)
    assert len(spec.data.samples) == 6


def test_chart_spec_cdf_roundtrip():
    """验证 ChartSpec cdf 数据可正确构造。"""
    from gacha_simulator.visualization.chart_spec import cdf, CDFData
    samples = np.array([1, 2, 3, 4, 5])
    spec = cdf(samples, title="测试CDF")
    assert spec.chart_type == "cdf"
    assert isinstance(spec.data, CDFData)
    assert len(spec.data.samples) == 5


def test_chart_spec_scatter_roundtrip():
    """验证 ChartSpec scatter 数据可正确构造。"""
    from gacha_simulator.visualization.chart_spec import scatter, ScatterData
    x = np.arange(10)
    y = x * 2
    spec = scatter(x, y, title="测试散点", mode="lines+markers")
    assert spec.chart_type == "scatter"
    assert isinstance(spec.data, ScatterData)
    assert len(spec.data.x) == 10


def test_plotly_histogram_figure():
    """验证 PlotlyRenderer 可从 ChartSpec 生成 go.Figure。"""
    from gacha_simulator.visualization.chart_spec import histogram
    from gacha_simulator.visualization.plotly_charts import PlotlyRenderer
    samples = np.random.randn(100)
    spec = histogram(samples, title="正态分布")
    renderer = PlotlyRenderer()
    fig = renderer.to_figure(spec)
    assert fig is not None
    assert len(fig.data) >= 1


def test_plotly_scatter_figure():
    """验证 PlotlyRenderer 可生成散点图。"""
    from gacha_simulator.visualization.chart_spec import scatter
    from gacha_simulator.visualization.plotly_charts import PlotlyRenderer
    x = np.linspace(0, 10, 50)
    y = np.sin(x)
    spec = scatter(x, y, title="正弦波", mode="lines")
    renderer = PlotlyRenderer()
    fig = renderer.to_figure(spec)
    assert fig is not None
    assert len(fig.data) >= 1
