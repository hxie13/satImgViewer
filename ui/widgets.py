from PyQt6.QtWidgets import QListWidget, QLineEdit
from PyQt6.QtCore import Qt, QMimeData
from PyQt6.QtGui import QDrag  # <--- 必须导入 QDrag

class DraggableList(QListWidget):
    """支持拖出的列表控件"""
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setSelectionMode(QListWidget.SelectionMode.SingleSelection)

    def startDrag(self, supportedActions):
        """
        重写拖拽开始事件：将选中的波段名称打包进 MimeData
        """
        item = self.currentItem()
        if not item:
            return

        # 1. 创建数据包
        mime = QMimeData()
        mime.setText(item.text()) # 将波段名 (e.g., "B13") 放入文本
        
        # 2. 创建拖拽对象
        drag = QDrag(self)
        drag.setMimeData(mime)
        
        # 3. (可选) 设置拖拽时的缩略图，这里省略，使用默认光标
        
        # 4. 执行拖拽 (阻塞式调用)
        drag.exec(supportedActions)

class BandDropZone(QLineEdit):
    def __init__(self, placeholder):
        super().__init__()
        self.setPlaceholderText(placeholder)
        self.setReadOnly(True)
        self.setAcceptDrops(True)
        
        # 这里只保留特殊的虚线边框样式，颜色留给 QSS 控制
        # 或者直接定义一种特殊的深色虚线风格
        self.setStyleSheet("""
            QLineEdit {
                border: 2px dashed #555; /* 深灰色虚线 */
                border-radius: 5px;
                padding: 5px;
                background: #252525; /* 比背景稍深，形成凹槽感 */
                color: #ddd;
            }
            QLineEdit:hover {
                border-color: #0078d7; /* 悬停变蓝 */
                background: #2a2a2a;
            }
        """)

    def dragEnterEvent(self, event):
        # 只接受文本格式
        if event.mimeData().hasText():
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        text = event.mimeData().text()
        self.setText(text)
        event.acceptProposedAction()