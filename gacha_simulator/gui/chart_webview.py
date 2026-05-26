"""ChartWebView —— 封装 Plotly 图表的 QWebEngineView 容器。

每个面板的所有图表共用一个 HTML 文件 + 一个 WebView。
图表间切换用 JS display: block/none，瞬时无延迟。
支持增量更新单个图表（runJavaScript），无需重载完整 HTML。
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import tempfile
from pathlib import Path

import plotly

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView

from ..visualization.chart_spec import ChartSpec
from ..visualization.plotly_charts import PlotlyRenderer

logger = logging.getLogger(__name__)

# 首次 import 时输出版本号，方便排查 plotly 升级导致的渲染异常
logger.info("ChartWebView 初始化: plotly==%s", plotly.__version__)

# ── HTML 模板路径 ───────────────────────────────────────────────────────

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_PATH = _TEMPLATE_DIR / "chart_container.html"

# 开发时热重载模板内容；打包后 _TEMPLATE_PATH 可能不存在，回退到内置模板
if _TEMPLATE_PATH.exists():
    with open(_TEMPLATE_PATH, encoding="utf-8") as _f:
        _HTML_TEMPLATE = _f.read()
else:
    from ..visualization.plotly_charts import _HTML_TEMPLATE  # noqa: F811


# ── 临时目录管理 ────────────────────────────────────────────────────────

_temp_dir: str | None = None


def _get_temp_dir() -> str:
    global _temp_dir
    if _temp_dir is None:
        _temp_dir = tempfile.mkdtemp(prefix="gachastat_charts_")
        atexit.register(_cleanup_temp_dir)
    return _temp_dir


def _cleanup_temp_dir() -> None:
    global _temp_dir
    if _temp_dir and os.path.isdir(_temp_dir):
        import shutil
        shutil.rmtree(_temp_dir, ignore_errors=True)
    _temp_dir = None


# ── ChartWebView ────────────────────────────────────────────────────────

class ChartWebView(QWebEngineView):
    """封装 Plotly 图表的 WebEngineView。

    特性：
    - 单 HTML 多图表，JS 标签切换（瞬时）
    - plotly.js 本地引用（file://），完全离线
    - 增量更新 runJavaScript()，支持滚动位置保持
    - 加载竞态保护（_loaded 标志 + 待处理队列）
    - 临时文件统一管理，面板销毁时自动清理
    """

    loaded = pyqtSignal(bool)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._renderer = PlotlyRenderer()
        self._html_path: str | None = None
        self._chart_keys: set[str] = set()
        self._loaded: bool = False
        self._pending_updates: dict[str, ChartSpec] = {}

        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

        self.loadFinished.connect(self._on_load_finished)
        self.setMinimumHeight(300)

    # ── 公共接口 ──────────────────────────────────────────────────

    def set_chart(self, spec: ChartSpec) -> None:
        """显示单张图表。"""
        self.set_charts({spec.title: spec})

    def set_charts(self, charts: dict[str, ChartSpec], use_tabs: bool = True) -> None:
        """显示多张图表，dict key 为标签名。整批替换，用于首次加载或数据集切换。"""
        self._chart_keys = set(charts.keys())
        self._loaded = False
        self._pending_updates.clear()

        figures_json = {}
        config_json = {}
        for key, spec in charts.items():
            figures_json[key] = self._renderer.to_figure(spec).to_json()
            config_json[key] = spec.title

        html = _HTML_TEMPLATE.format(
            plotly_js_url=self._get_plotly_js_url(),
            charts_json=json.dumps(figures_json),
            config_json=json.dumps(config_json, ensure_ascii=False),
            use_tabs="true" if (use_tabs and len(charts) > 1) else "false",
        )
        self._write_and_load(html)

    def update_chart(self, key: str, spec: ChartSpec) -> None:
        """增量更新单张图表，通过 runJavaScript() 更新指定 div。

        用于增量分析场景：参数不变的图表跳过，仅更新变化的。
        首次加载必须用 set_charts() 初始化 plotly.js。
        """
        if not self._loaded:
            self._pending_updates[key] = spec
            return

        self._chart_keys.add(key)
        fig_json = self._renderer.to_figure(spec).to_json()
        safe_json = fig_json.replace("\\", "\\\\").replace("'", "\\'")
        js_code = (
            "(function() {"
            "  var scrollY = window.scrollY;"
            "  try {"
            f"    var plotData = JSON.parse('{safe_json}');"
            f"    var el = document.getElementById('chart-{key}');"
            "    if (el) { Plotly.react(el, plotData.data, plotData.layout); }"
            "    else { console.warn('Chart div not found: chart-" + key + "'); }"
            "  } catch(e) { console.error('update_chart error:', e); }"
            "  window.scrollTo(0, scrollY);"
            "})();"
        )
        self.page().runJavaScript(js_code)

    def remove_chart(self, key: str) -> None:
        """移除单张图表（通过 JS 删除对应 DOM 元素）。"""
        self._chart_keys.discard(key)
        if self._loaded:
            self.page().runJavaScript(
                f"(function(){{ var el = document.getElementById('chart-{key}');"
                f" var panel = document.getElementById('panel-{key}');"
                f" if(el) el.remove(); if(panel) panel.remove(); }})();"
            )

    def has_chart(self, key: str) -> bool:
        return key in self._chart_keys

    # ── 内部方法 ──────────────────────────────────────────────────

    def _get_plotly_js_url(self) -> str:
        path = os.path.join(os.path.dirname(plotly.__file__), "package_data", "plotly.min.js")
        return QUrl.fromLocalFile(path).toString()

    def _write_and_load(self, html: str) -> None:
        old_path = self._html_path
        tmp_path = os.path.join(_get_temp_dir(), f"chart_{os.getpid()}_{id(self)}.html")
        with open(tmp_path, "w", encoding="utf-8") as f:
            f.write(html)
        self._html_path = tmp_path
        self.load(QUrl.fromLocalFile(tmp_path))
        if old_path and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    def _on_load_finished(self, ok: bool) -> None:
        self._loaded = ok
        self.loaded.emit(ok)
        if ok and self._pending_updates:
            for key, spec in self._pending_updates.items():
                self.update_chart(key, spec)
            self._pending_updates.clear()

    def closeEvent(self, event):
        self._loaded = False
        super().closeEvent(event)
