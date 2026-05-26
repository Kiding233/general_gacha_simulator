import sys
import os

this_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(this_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from gacha_simulator.gui import MainWindow
from gacha_simulator._version import __version__

_ICON_PATH = os.path.join(this_dir, 'gacha_simulator', 'resources', 'app_icon.png')


def main():
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


if __name__ == '__main__':
    main()
