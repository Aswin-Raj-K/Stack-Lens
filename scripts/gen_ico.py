"""Run once from the repo root: python scripts/gen_ico.py"""
import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtGui import QPixmap

app = QApplication(sys.argv)
px = QPixmap("gui/icons/icon.svg").scaled(256, 256)
ok = px.save("gui/icons/icon.ico")
print("icon.ico written" if ok else "FAILED — check Qt ICO plugin")
sys.exit(0 if ok else 1)
