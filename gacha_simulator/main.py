import sys
import os

this_dir = os.path.dirname(os.path.abspath(__file__))
parent_dir = os.path.dirname(this_dir)
if parent_dir not in sys.path:
    sys.path.insert(0, parent_dir)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from gacha_simulator.gui import MainWindow

_ICON_PATH = os.path.join(this_dir, 'gacha_simulator', 'resources', 'app_icon.png')


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Gacha Simulator")
    app.setOrganizationName("Gacha Simulator")
    app.setApplicationVersion("1.0")
    if os.path.exists(_ICON_PATH):
        app.setWindowIcon(QIcon(_ICON_PATH))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
