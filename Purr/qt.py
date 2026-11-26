# -*- coding: utf-8 -*-
"""Single import point for Qt in Purr.

PyQt4 had one flat ``PyQt4.Qt`` module; Qt5/Qt6 split it into QtCore, QtGui and
QtWidgets. qtpy picks whichever binding is installed (PyQt5 by default, PyQt6 also
works; set QT_API to choose).
"""
try:
    from qtpy.QtCore import (QCoreApplication, QEventLoop, QMimeData, QObject, QPoint, QSize,
                             Qt, QTimer, QUrl, Signal)
    from qtpy.QtGui import (QClipboard, QCursor, QDrag, QFont, QFontMetrics, QTextDocument)
    from qtpy.QtWidgets import (QAbstractItemView, QApplication, QButtonGroup, QComboBox, QDialog,
                                QFileDialog, QFrame, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                                QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox,
                                QPushButton, QRadioButton, QSizePolicy, QSplitter, QStackedWidget,
                                QTextBrowser, QTextEdit, QToolBar, QTreeWidget, QTreeWidgetItem,
                                QVBoxLayout, QWidget, QWidgetAction, QWizard, QWizardPage)
except ImportError as exc:
    raise ImportError("Purr needs Qt bindings: install PyQt5 (e.g. apt install python3-pyqt5, "
                      "or pip install 'purr[pyqt5]'). Original error: %s" % exc) from exc


def set_margin(layout, margin):
    """QLayout.setMargin() is gone in Qt6; this works everywhere."""
    layout.setContentsMargins(margin, margin, margin, margin)


def event_pos(ev):
    """Local position of a mouse/drop event as a QPoint (Qt5 .pos(), Qt6 .position())."""
    if hasattr(ev, "position"):
        return ev.position().toPoint()
    return ev.pos()


def event_global_pos(ev):
    """Global position of a mouse event as a QPoint (Qt5 .globalPos(), Qt6 .globalPosition())."""
    if hasattr(ev, "globalPosition"):
        return ev.globalPosition().toPoint()
    return ev.globalPos()


def text_width(fontmetrics, text):
    """QFontMetrics.width() was replaced by horizontalAdvance() in Qt 5.11."""
    if hasattr(fontmetrics, "horizontalAdvance"):
        return fontmetrics.horizontalAdvance(text)
    return fontmetrics.width(text)
