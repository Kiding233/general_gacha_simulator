"""ChartWebView —— 封装 Plotly 图表的 QWebEngineView 容器。

每个面板的所有图表共用一个 HTML 文件 + 一个 WebView。
图表间切换用 JS display: block/none，瞬时无延迟。
支持增量更新单个图表（runJavaScript），无需重载完整 HTML。

防闪烁策略：
- __init__ 中预加载骨架页（含 plotly.js + rebuildAll 函数，空图表）
- set_charts() 首次及后续均通过 runJavaScript 原地重建，零重载
- 若预加载未完成时调用 set_charts()，写入 _pending_charts 等待 loadFinished 处理
"""
from __future__ import annotations

import atexit
import json
import logging
import os
import tempfile

import plotly

from PyQt6.QtCore import QUrl, pyqtSignal
from PyQt6.QtWebEngineCore import QWebEngineDownloadRequest, QWebEngineProfile, QWebEngineSettings
from PyQt6.QtWebEngineWidgets import QWebEngineView
from PyQt6.QtWidgets import QSizePolicy

from ..visualization.chart_spec import ChartSpec
from ..visualization.plotly_charts import PlotlyRenderer

logger = logging.getLogger(__name__)

logger.info("ChartWebView 初始化: plotly==%s", plotly.__version__)

# ── 骨架页模板（预加载用，无图表数据）────────────────────────────────────

_SKELETON_HTML = """\
<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<script src="{plotly_js_url}"></script>
<style>
  * {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{ font-family: "Microsoft YaHei", "PingFang SC", sans-serif; background: #f8f9fa; }}
  .tab-bar {{
    display: flex; flex-wrap: wrap; gap: 2px; padding: 8px 10px 0 10px;
    background: #f8f9fa; border-bottom: 1px solid #dee2e6; position: sticky; top: 0; z-index: 10;
  }}
  .tab-btn {{
    padding: 8px 16px; border: none; border-radius: 6px 6px 0 0;
    background: #ced4da; color: #495057; cursor: pointer; font-size: 13px; transition: background .15s;
  }}
  .tab-btn:hover {{ background: #adb5bd; }}
  .tab-btn.active {{ background: #fff; color: #212529; font-weight: 600; }}
  .chart-panel {{ display: none; padding: 10px; }}
  .chart-panel.active {{ display: block; }}
  .chart-container {{ width: 100%; }}
  .collapsible {{
    margin: 10px 10px 0 10px; border: 1px solid #dee2e6; border-radius: 6px; overflow: hidden;
  }}
  .collapsible-header {{
    padding: 10px 16px; background: #e9ecef; cursor: pointer; font-size: 14px; font-weight: 600;
    user-select: none; display: flex; justify-content: space-between; align-items: center;
  }}
  .collapsible-header:hover {{ background: #dee2e6; }}
  .collapsible-body {{ display: none; padding: 10px; }}
  .collapsible.open .collapsible-body {{ display: block; }}
</style>
</head>
<body>
<div class="tab-bar" id="tab-bar"></div>
<div id="charts-root"></div>
<script>
  // 抑制 Plotly 的 Canvas2D getImageData 性能警告
  (function() {{
    var _getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function(type, attrs) {{
      if (type === '2d') {{
        attrs = Object.assign({{}}, attrs, {{willReadFrequently: true}});
      }}
      return _getContext.call(this, type, attrs);
    }};
  }})();

  function renderChart(key, figureJson) {{
    var data = JSON.parse(figureJson);
    var el = document.getElementById('chart-' + key);
    if (el) {{
      Plotly.newPlot(el, data.data, data.layout, {{
        responsive: true,
        displaylogo: false,
        scrollZoom: false,
        displayModeBar: true,
        modeBarButtonsToRemove: ['sendDataToCloud', 'lasso2d', 'select2d'],
        toImageButtonOptions: {{
          format: 'png',
          scale: 3,
        }},
      }});
    }}
  }}

  function reportHeight() {{
    document.title = 'HT:' + document.body.scrollHeight;
  }}

  function rebuildAll(config, charts, useTabs) {{
    var keys = Object.keys(charts);
    var tabBar = document.getElementById('tab-bar');
    var root = document.getElementById('charts-root');

    tabBar.innerHTML = '';
    root.innerHTML = '';

    if (useTabs && keys.length > 1) {{
      tabBar.style.display = 'flex';
      keys.forEach(function(key, i) {{
        var btn = document.createElement('button');
        btn.className = 'tab-btn' + (i === 0 ? ' active' : '');
        btn.textContent = config[key] || key;
        btn.onclick = function() {{
          document.querySelectorAll('.tab-btn').forEach(function(b) {{ b.classList.remove('active'); }});
          document.querySelectorAll('.chart-panel').forEach(function(p) {{ p.classList.remove('active'); }});
          btn.classList.add('active');
          document.getElementById('panel-' + key).classList.add('active');
        }};
        tabBar.appendChild(btn);

        var panel = document.createElement('div');
        panel.className = 'chart-panel' + (i === 0 ? ' active' : '');
        panel.id = 'panel-' + key;
        var div = document.createElement('div');
        div.className = 'chart-container';
        div.id = 'chart-' + key;
        panel.appendChild(div);
        root.appendChild(panel);
      }});
    }} else {{
      tabBar.style.display = 'none';
      keys.forEach(function(key) {{
        var section = document.createElement('div');
        section.className = 'collapsible open';
        var header = document.createElement('div');
        header.className = 'collapsible-header';
        header.textContent = config[key] || key;
        header.onclick = function() {{ section.classList.toggle('open'); }};
        var body = document.createElement('div');
        body.className = 'collapsible-body';
        var div = document.createElement('div');
        div.className = 'chart-container';
        div.id = 'chart-' + key;
        body.appendChild(div);
        section.appendChild(header);
        section.appendChild(body);
        root.appendChild(section);
      }});
    }}

    keys.forEach(function(key) {{ renderChart(key, charts[key]); }});
    window.scrollTo(0, 0);
    setTimeout(reportHeight, 100);
  }}
</script>
</body>
</html>
"""

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


# ── 下载处理器（Plotly 模式栏「保存为 PNG」）─────────────────────────────

_download_handler_installed: bool = False


def _install_download_handler() -> None:
    """为 QWebEngineProfile 安装下载处理器。

    Plotly 模式栏的「保存为 PNG」通过浏览器下载机制触发，
    QWebEngineView 默认不处理下载请求，需手动弹出保存对话框。
    模块级单例，仅首次调用时安装。
    """
    global _download_handler_installed
    if _download_handler_installed:
        return
    _download_handler_installed = True

    from PyQt6.QtWidgets import QFileDialog

    def _on_download_requested(download: QWebEngineDownloadRequest):
        # 生成默认文件名
        default_name = download.downloadFileName() or "plot.png"
        if not default_name.endswith(".png"):
            default_name = "plot.png"

        path, _ = QFileDialog.getSaveFileName(
            None, "保存图片", default_name, "PNG 图片 (*.png);;所有文件 (*)"
        )
        if path:
            download.setDownloadDirectory(os.path.dirname(path))
            download.setDownloadFileName(os.path.basename(path))
            download.accept()
        else:
            download.cancel()

    QWebEngineProfile.defaultProfile().downloadRequested.connect(
        _on_download_requested
    )


# ── ChartWebView ────────────────────────────────────────────────────────

class ChartWebView(QWebEngineView):
    """封装 Plotly 图表的 WebEngineView。

    特性：
    - __init__ 预加载骨架页，后续所有图表切换均通过 runJavaScript（零闪烁）
    - plotly.js 本地引用（file://），完全离线
    - 增量更新 runJavaScript()，支持滚动位置保持
    - 加载竞态保护（_loaded 标志 + 待处理队列）
    - 临时文件统一管理，面板销毁时自动清理
    """

    loaded = pyqtSignal(bool)

    def __init__(self, parent=None, shrinkable: bool = False):
        super().__init__(parent)
        _install_download_handler()
        self._renderer = PlotlyRenderer()
        self._html_path: str | None = None
        self._chart_keys: set[str] = set()
        self._loaded: bool = False
        self._pending_updates: dict[str, ChartSpec] = {}
        self._pending_charts: tuple[dict[str, ChartSpec], bool] | None = None
        self._shrinkable = shrinkable

        settings = self.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, False)

        self.loadFinished.connect(self._on_load_finished)
        self.titleChanged.connect(self._on_title_changed)
        self.setMinimumHeight(100 if shrinkable else 300)

        if shrinkable:
            sp = self.sizePolicy()
            sp.setVerticalPolicy(QSizePolicy.Policy.Expanding)
            self.setSizePolicy(sp)

        # 预加载骨架页：加载完成后 _loaded=True，后续 set_charts 均走 JS 路径
        self._preload()

    # ── 公共接口 ──────────────────────────────────────────────────

    def show_message(self, text: str) -> None:
        """在图表区域显示文本提示（不破坏 JS 上下文，set_chart 后续可正常调用）。"""
        safe = text.replace("\\", "\\\\").replace("'", "\\'")
        self.page().runJavaScript(
            f"(function(){{"
            f"  var tb = document.getElementById('tab-bar');"
            f"  if(tb) tb.style.display = 'none';"
            f"  var root = document.getElementById('charts-root');"
            f"  if(root) root.innerHTML = '<p style=\\'text-align:center;color:#888;padding:40px;\\'>"
            f"{safe}</p>';"
            f"}})();"
        )

    def set_chart(self, spec: ChartSpec) -> None:
        """显示单张图表。"""
        self.set_charts({spec.title: spec})

    def set_charts(self, charts: dict[str, object], use_tabs: bool = True) -> None:
        """显示多张图表。值可以是 ChartSpec 或已构建的 go.Figure 对象。"""
        from plotly.graph_objects import Figure as GoFigure

        self._chart_keys = set(charts.keys())
        self._pending_updates.clear()

        figures_json = {}
        config_json = {}
        for key, value in charts.items():
            if isinstance(value, GoFigure):
                figures_json[key] = value.to_json()
                config_json[key] = value.layout.title.text or key
            else:
                spec = value
                figures_json[key] = self._renderer.to_figure(spec).to_json()
                config_json[key] = spec.title

        use_tabs_flag = "true" if (use_tabs and len(charts) > 1) else "false"

        if self._loaded:
            charts_js = json.dumps(figures_json)
            config_js = json.dumps(config_json, ensure_ascii=False)
            self.page().runJavaScript(
                f"rebuildAll({config_js}, {charts_js}, {use_tabs_flag});"
            )
        else:
            # 预加载尚未完成，暂存请求
            self._pending_charts = (charts, use_tabs)

    def update_chart(self, key: str, spec: ChartSpec) -> None:
        """增量更新单张图表。"""
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
        """移除单张图表。"""
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

    def _preload(self) -> None:
        """加载骨架页，确保 plotly.js 和 JS 函数就绪。"""
        skeleton = _SKELETON_HTML.format(
            plotly_js_url=self._get_plotly_js_url(),
        )
        self._write_and_load(skeleton)

    def _write_and_load(self, html: str) -> None:
        old_path = self._html_path
        tmp_path = os.path.join(_get_temp_dir(), f"chart_{os.getpid()}_{id(self)}.html")
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                f.write(html)
        except OSError as e:
            logger.error("无法写入临时 HTML 文件 %s: %s", tmp_path, e)
            return
        self._html_path = tmp_path
        self.load(QUrl.fromLocalFile(tmp_path))
        if old_path and os.path.isfile(old_path):
            try:
                os.remove(old_path)
            except OSError:
                pass

    def _on_load_finished(self, ok: bool) -> None:
        if not ok:
            logger.error("ChartWebView 加载失败，请检查临时文件或 plotly.js 路径")
        self._loaded = ok
        self.loaded.emit(ok)

        if not ok:
            return

        if self._shrinkable:
            self._setup_shrinkable()

        # 处理预加载期间积压的 set_charts 请求
        if self._pending_charts is not None:
            charts, use_tabs = self._pending_charts
            self._pending_charts = None
            self.set_charts(charts, use_tabs)
            return

        # 处理积压的单图更新
        if self._pending_updates:
            for key, spec in self._pending_updates.items():
                self.update_chart(key, spec)
            self._pending_updates.clear()

    def _setup_shrinkable(self) -> None:
        """注入自适应高度 CSS 和 ResizeObserver（shrinkable 模式）。"""
        self.page().runJavaScript("""
(function() {
  var style = document.createElement('style');
  style.textContent = 'html,body{height:100%;overflow:hidden} ' +
    '#charts-root{min-height:100%} ' +
    '.chart-panel.active{height:calc(100vh - 50px)} ' +
    '.chart-container{width:100%;height:100%} ' +
    '.collapsible-body .chart-container{height:400px}';
  document.head.appendChild(style);

  var ro = new ResizeObserver(function() {
    var panels = document.querySelectorAll('.chart-panel.active .chart-container[id], ' +
      '.collapsible.open .chart-container[id]');
    panels.forEach(function(el) {
      Plotly.Plots.resize(el);
    });
  });
  var root = document.getElementById('charts-root');
  if (root) ro.observe(root);
})();
""")

    def _on_title_changed(self, title: str) -> None:
        """从 JS reportHeight() 回调中解析内容高度并调整 widget 大小。"""
        if self._shrinkable:
            return  # shrinkable 模式下由外部布局控制高度
        if title.startswith('HT:'):
            try:
                h = int(title.split(':')[1])
                if h > 100:
                    self.setMinimumHeight(h + 20)
                    self.updateGeometry()
            except (ValueError, IndexError):
                pass

    def closeEvent(self, event):
        self._loaded = False
        super().closeEvent(event)
