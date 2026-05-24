import pytest

pytest.skip("plot_pmf / plot_cdf / plot_time_series 尚未实现", allow_module_level=True)


def test_plot_pmf():
    fig = plot_pmf([1, 1, 2, 2, 2, 3], bins=3)
    assert fig is not None


def test_plot_cdf():
    fig = plot_cdf([1, 2, 3, 4, 5])
    assert fig is not None


def test_plot_time_series():
    data = [{'action_index': i, 'cumulative': i * 2} for i in range(10)]
    fig = plot_time_series(data)
    assert fig is not None
