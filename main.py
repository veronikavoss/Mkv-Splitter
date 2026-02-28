import sys
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, QEvent
from gui import MainWindow

class GlobalDragDropFilter(QObject):
    def __init__(self, main_window):
        super().__init__()
        self.main_window = main_window

    def eventFilter(self, watched, event):
        if event.type() == QEvent.Type.DragEnter or event.type() == QEvent.Type.DragMove:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                return True
        elif event.type() == QEvent.Type.Drop:
            if event.mimeData().hasUrls():
                event.acceptProposedAction()
                urls = event.mimeData().urls()
                if urls:
                    file_paths = []
                    for url in urls:
                        path = url.toLocalFile()
                        if not path:
                            path = url.toString().replace('file:///', '')
                        file_paths.append(path)
                    if self.main_window and file_paths:
                        self.main_window.handle_dropped_files(file_paths)
                return True
        return super().eventFilter(watched, event)

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = MainWindow()
    
    # Install global filter
    drag_drop_filter = GlobalDragDropFilter(window)
    app.installEventFilter(drag_drop_filter)
    
    window.show()
    
    # Set global tooltip style
    app.setStyleSheet("""
        QToolTip {
            color: white;
            background-color: #2b2b2b;
            border: 1px solid #767676;
            padding: 4px;
        }
    """)
    
    sys.exit(app.exec())
