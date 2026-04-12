"""Base class for all dockable panels in the profiler.

Provides a common ``set_unit`` / ``refresh_theme`` contract so
ProfilerWindow can call these methods on any dock without caring
about the specific subclass.
"""

from PySide6 import QtWidgets


class DockBase(QtWidgets.QDockWidget):
    """QDockWidget subclass with a common unit / theme API.

    Subclasses that need custom logic should override these methods and
    call ``super()`` first so the base fields stay in sync.  Subclasses
    that have no display to update can leave both methods unoverridden.
    """

    def __init__(self, title: str, parent=None):
        super().__init__(title, parent)
        self._unit_label: str = "us"
        self._unit_scale: float = 1.0

    def set_unit(self, unit_label: str, unit_scale: float) -> None:
        """Switch display unit (e.g. 'us' → 'ms').  Override to update UI."""
        self._unit_label = unit_label
        self._unit_scale = unit_scale

    def refresh_theme(self) -> None:
        """Called after a theme change.  Override to repaint custom widgets."""
