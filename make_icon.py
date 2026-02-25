import sys
from PySide6.QtGui import QImage, QPainter, QColor, QFont, QPen, QPainterPath
from PySide6.QtCore import Qt, QRect

def create_icon():
    img = QImage(256, 256, QImage.Format.Format_ARGB32)
    img.fill(Qt.GlobalColor.transparent)

    painter = QPainter(img)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing)

    # 1. Dark Rounded Background
    path = QPainterPath()
    path.addRoundedRect(QRect(16, 16, 224, 224), 50, 50)
    painter.fillPath(path, QColor("#2b2b2b"))

    # 2. Golden Border
    pen = QPen(QColor("gold"))
    pen.setWidth(8)
    painter.setPen(pen)
    painter.drawPath(path)
    
    # 3. Text "MKV" in Gold
    font = QFont("Segoe UI", 72, QFont.Weight.Bold)
    painter.setFont(font)
    painter.setPen(QColor("gold"))
    painter.drawText(QRect(0, 0, 256, 256), Qt.AlignmentFlag.AlignCenter, "MKV")

    painter.end()
    img.save("assets/app_icon.png")
    print("Icon generated successfully at assets/app_icon.png")

if __name__ == "__main__":
    from PySide6.QtWidgets import QApplication
    app = QApplication(sys.argv)
    create_icon()
