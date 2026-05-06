import sys
from pathlib import Path
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QIcon
from ui import MainWindow


def _base_path() -> Path:
    # PyInstaller extracts bundled files to sys._MEIPASS when frozen
    if hasattr(sys, '_MEIPASS'):
        return Path(sys._MEIPASS)
    return Path(__file__).parent


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')
    app.setApplicationName('SadForge')
    icon_path = _base_path() / 'sadforge_ico.png'
    if icon_path.exists():
        app.setWindowIcon(QIcon(str(icon_path)))
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
