#!/usr/bin/env python3
"""GachaStat 启动脚本"""

import sys
import os

def main():
    this_dir = os.path.dirname(os.path.abspath(__file__))
    parent_dir = os.path.dirname(this_dir)
    if parent_dir not in sys.path:
        sys.path.insert(0, parent_dir)

    try:
        from PyQt6.QtWidgets import QApplication
        from PyQt6.QtGui import QIcon
        from gacha_simulator.gui import MainWindow

        icon_path = os.path.join(this_dir, 'resources', 'app_icon.png')
        app = QApplication(sys.argv)
        app.setStyle('Fusion')
        app.setApplicationName("GachaStat")
        app.setOrganizationName("GachaStat")
        app.setApplicationVersion("1.0")
        if os.path.exists(icon_path):
            app.setWindowIcon(QIcon(icon_path))
        window = MainWindow()
        window.show()
        sys.exit(app.exec())
        
    except ImportError as e:
        if 'PyQt6' in str(e):
            print("PyQt6 不可用，启动CLI模式...")
            print()
            
            sys.argv = ['gacha-simulator', '-n', '1000', '-w', '4']
            
            from gacha_simulator import cli
            sys.exit(cli.main())
        else:
            raise


if __name__ == '__main__':
    main()
