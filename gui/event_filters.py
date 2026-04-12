"""App-level Qt event filters for keyboard shortcuts.

These are installed on QApplication so they fire before any widget's own
keyPressEvent, making them suitable for global keys that must work regardless
of which widget has focus.
"""

from PySide6 import QtCore, QtWidgets


class _ZoomKeyFilter(QtCore.QObject):
    """App-level filter for zoom-in/out via bare '+' and '-'.

    QShortcut key sequences are unreliable for shifted keys like '+' (reported
    as Key_Plus | ShiftModifier on most platforms). Checking event.text() is
    layout-independent and works regardless of which child widget has focus.
    """

    _INPUT_TYPES = (
        QtWidgets.QLineEdit,
        QtWidgets.QTextEdit,
        QtWidgets.QPlainTextEdit,
        QtWidgets.QComboBox,
    )

    def __init__(self, zoom_in, zoom_out, parent=None):
        super().__init__(parent)
        self._zoom_in = zoom_in
        self._zoom_out = zoom_out

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QtCore.QEvent.Type.KeyPress:
            text = event.text()
            focused = QtWidgets.QApplication.focusWidget()
            if not isinstance(focused, self._INPUT_TYPES):
                if text == "+":
                    self._zoom_in()
                    return True
                if text == "-":
                    self._zoom_out()
                    return True
        return False


class _QuestionKeyFilter(QtCore.QObject):
    """App-level event filter that triggers the shortcut overlay on '?'.

    Installed on QApplication so it fires before any widget's own
    keyPressEvent — including QTableWidget / QTreeWidget which would
    otherwise swallow the key for their own navigation.

    Skips the callback when the focused widget is an editable input
    (QLineEdit, QTextEdit, QPlainTextEdit, QComboBox) so that typing
    '?' in a search box still works normally.
    """

    _INPUT_TYPES = (
        QtWidgets.QLineEdit,
        QtWidgets.QTextEdit,
        QtWidgets.QPlainTextEdit,
        QtWidgets.QComboBox,
    )

    def __init__(self, callback, parent=None):
        super().__init__(parent)
        self._callback = callback

    def eventFilter(self, obj, event):  # noqa: N802
        if event.type() == QtCore.QEvent.Type.KeyPress:
            key = event.key()
            # Key_Question covers '?' on all layouts; Key_Slash + Shift
            # is the US-keyboard way to produce '?', caught as a fallback.
            is_question = key == QtCore.Qt.Key.Key_Question or (
                key == QtCore.Qt.Key.Key_Slash
                and event.modifiers() & QtCore.Qt.KeyboardModifier.ShiftModifier
            )
            if is_question:
                focused = QtWidgets.QApplication.focusWidget()
                if not isinstance(focused, self._INPUT_TYPES):
                    self._callback()
                    return True  # consume — don't pass to the widget
        return False
