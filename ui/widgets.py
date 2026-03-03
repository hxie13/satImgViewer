from PyQt6.QtWidgets import QListWidget, QLineEdit
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag


class DraggableList(QListWidget):
    """Band list that supports drag and configurable density."""

    def __init__(self, parent=None, density: str = "comfortable"):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)
        self.set_density(density)

    def set_density(self, density: str) -> None:
        value = "compact" if density == "compact" else "comfortable"
        self.setProperty("density", value)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def startDrag(self, supportedActions):
        item = self.currentItem()
        if not item:
            return

        mime = QMimeData()
        mime.setText(item.text())

        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(supportedActions)


class BandDropZone(QLineEdit):
    STATE_NORMAL = "normal"
    STATE_HOVER = "hover"
    STATE_ACTIVE = "active"
    STATE_INVALID = "invalid"

    def __init__(self, placeholder: str, channel: str = ""):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setReadOnly(True)
        self.setAcceptDrops(True)
        self.setObjectName("BandDropZone")
        if channel:
            self.setProperty("channel", channel)
        self.set_state(self.STATE_NORMAL)

    def set_state(self, state: str) -> None:
        if state not in {
            self.STATE_NORMAL,
            self.STATE_HOVER,
            self.STATE_ACTIVE,
            self.STATE_INVALID,
        }:
            state = self.STATE_NORMAL
        self.setProperty("dropState", state)
        self.style().unpolish(self)
        self.style().polish(self)
        self.update()

    def enterEvent(self, event):
        super().enterEvent(event)
        if self.text().strip():
            self.set_state(self.STATE_ACTIVE)
        else:
            self.set_state(self.STATE_HOVER)

    def leaveEvent(self, event):
        super().leaveEvent(event)
        if self.text().strip():
            self.set_state(self.STATE_ACTIVE)
        else:
            self.set_state(self.STATE_NORMAL)

    def clear_band(self) -> None:
        self.clear()
        self.set_state(self.STATE_NORMAL)

    def dragEnterEvent(self, event):
        if event.mimeData().hasText():
            event.acceptProposedAction()
            self.set_state(self.STATE_HOVER)
        else:
            self.set_state(self.STATE_INVALID)
            event.ignore()

    def dropEvent(self, event):
        text = event.mimeData().text().strip()
        if not text:
            self.set_state(self.STATE_INVALID)
            event.ignore()
            return

        self.setText(text)
        self.set_state(self.STATE_ACTIVE)
        event.acceptProposedAction()

