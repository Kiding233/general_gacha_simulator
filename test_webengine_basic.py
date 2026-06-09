#!/usr/bin/env python3
"""最简测试：QWebEngineView 能否正常显示内容"""
import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QVBoxLayout, QWidget, QLabel
from PyQt6.QtWebEngineWidgets import QWebEngineView

app = QApplication(sys.argv)
app.setStyle('Fusion')

window = QMainWindow()
window.setWindowTitle("WebEngine 基础测试")
window.setGeometry(100, 100, 800, 600)

central = QWidget()
layout = QVBoxLayout(central)

layout.addWidget(QLabel("下面应该显示一个网页："))
web = QWebEngineView()
web.setHtml("""
<html><body style="font-family: sans-serif; padding: 20px;">
<h1 style="color: #3498db;">WebEngine 工作正常</h1>
<p>如果你看到这段文字，说明 QWebEngineView 可以正常渲染 HTML。</p>
<hr>
<p>当前时间：<span id="time"></span></p>
<script>document.getElementById('time').textContent = new Date().toLocaleString('zh-CN');</script>
</body></html>
""")
layout.addWidget(web)

window.setCentralWidget(central)
window.show()
sys.exit(app.exec())
