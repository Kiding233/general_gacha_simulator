import sys
import os

this_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(this_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

# 关键修复：PyQt6 和 GUI 导入必须放在 __main__ 护卫内。
# Windows 上 multiprocessing 使用 spawn 模式，每个 worker 子进程都会
# 重新执行此模块的顶层代码。若 PyQt6 在顶层导入，18 个 worker 各自加载
# 整个 GUI 栈（PyQt6 C 扩展 + 所有面板 + matplotlib），浪费 3-8 秒。
# 移入 __main__ 护卫后，worker 进程 __name__ 为 'gacha_simulator.main'，
# 不会触发这些导入，仅加载轻量的 sys/os 路径配置。

if __name__ == '__main__':
    # Windows spawn 模式 + PyInstaller 打包的必要调用
    from multiprocessing import freeze_support
    freeze_support()

    from PyQt6.QtCore import Qt
    from PyQt6.QtWidgets import QApplication
    from PyQt6.QtGui import QIcon
    from gacha_simulator.gui import MainWindow
    from gacha_simulator._version import __version__

    from gacha_simulator.paths import get_resource
    _ICON_PATH = get_resource('app_icon.png')

    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv)
    app.setApplicationName("GachaStat")
    app.setOrganizationName("GachaStat")
    app.setApplicationVersion(__version__)
    app.setStyleSheet("""
        QTableWidget::item:hover:!selected {
            background-color: #d6e8f5;
        }
        QTableWidget::item:selected {
            background-color: #308cc6;
            color: white;
        }
    """)
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())
