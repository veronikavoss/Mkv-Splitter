import sys
import os
import ctypes
import cv2
import queue
import re
import time
import subprocess
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QSlider, QLabel, QFileDialog, QMessageBox, QStyle, QStyleOptionSlider, QListWidget, QListWidgetItem, QAbstractItemView,
                               QTableWidget, QTableWidgetItem, QHeaderView, QCheckBox, QComboBox, QFrame, QProgressDialog, QMenu)
import mpv
from PySide6.QtCore import Qt, QUrl, QTime, QPoint, Signal, QObject, QEvent, QSize, QTimer, QThread

import video_cutter

from PySide6.QtGui import QPainter, QColor, QPolygon, QPen, QBrush, QIcon, QShortcut, QKeySequence, QPixmap, QImage, QCursor

class ElidedLabel(QLabel):
    def __init__(self, text, parent=None):
        super().__init__(text, parent)
        self._text = text
        self.setToolTip(text)

    def setText(self, text):
        self._text = text
        self.setToolTip(text)
        super().setText(text)

    def paintEvent(self, event):
        if not self.isVisible() or self.width() <= 0 or self.height() <= 0:
            return
        painter = QPainter(self)
        if not painter.isActive():
            return
        metrics = painter.fontMetrics()
        elided = metrics.elidedText(self._text, Qt.TextElideMode.ElideMiddle, self.width())
        painter.drawText(self.rect(), self.alignment(), elided)
        painter.end()

import threading
class ThumbnailGrabberThread(QObject):
    thumbnail_ready = Signal(int, bytes)  # emits (msec, raw_jpeg_bytes)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("ThumbnailGrabberThread")
        self.request_queue = queue.Queue()
        self.running = True
        self.current_video_path = ""
        self.cap = None
        self.thread = threading.Thread(target=self.run, daemon=True)

    def start(self):
        self.thread.start()

    def request_thumbnail(self, video_path, time_msec):
        # Only keep the latest request to avoid lagging behind mouse movement
        while not self.request_queue.empty():
            try:
                self.request_queue.get_nowait()
            except queue.Empty:
                break
        self.request_queue.put((video_path, time_msec))

    def run(self):
        import subprocess
        import sys
        import time
        
        creation_flags = 0
        if sys.platform == "win32":
            creation_flags = subprocess.CREATE_NO_WINDOW
            
        current_proc = None
        
        while self.running:
            try:
                # Wait for a request
                item = self.request_queue.get(timeout=0.1)
                if not item: continue
                
                # Drain queue completely to get the absolutely most recent request
                # This naturally limits the extraction rate to FFmpeg's speed without lagging behind
                while not self.request_queue.empty():
                    try:
                        item = self.request_queue.get_nowait()
                    except queue.Empty:
                        break
                        
                if not item: continue
                video_path, time_msec = item
                self.current_video_path = video_path

                # Optimized thumbnail extraction
                cmd = [
                    "ffmpeg", "-y", "-hide_banner", "-loglevel", "quiet",
                    "-ss", f"{time_msec / 1000.0:.3f}", # Seeking before input is fastest
                    "-i", video_path,
                    "-vframes", "1",
                    "-an", "-sn", # Disable audio and subtitles for speed
                    "-q:v", "8", # Slightly lower quality for much faster encoding
                    "-vf", "scale=288:-2",
                    "-f", "image2pipe",
                    "-vcodec", "mjpeg",
                    "-"
                ]
                
                proc = subprocess.run(cmd, capture_output=True, creationflags=creation_flags, timeout=2) # Add timeout to prevent hanging
                
                if proc.returncode == 0 and proc.stdout:
                    # Emit raw bytes to GUI thread safely!
                    self.thumbnail_ready.emit(time_msec, proc.stdout)
            
            except queue.Empty:
                continue
            except Exception as e:
                pass # Silently drop thumbnailing errors so it doesn't crash user terminal

    def stop(self):
        self.running = False
        self.request_queue.put(None)  # Unblock the queue if it's waiting
        # PySide6 C++ thread warning bypassed via daemon python thread
        if self.cap:
            try: self.cap.release()
            except: pass

class ThumbnailTooltip(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent, Qt.WindowType.ToolTip | Qt.WindowType.FramelessWindowHint)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        
        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(2)
        
        # Frame for styling
        self.frame = QFrame(self)
        self.frame.setStyleSheet("""
            QFrame {
                background-color: rgba(30, 30, 30, 220);
                border: 1px solid #555;
                border-radius: 6px;
            }
        """)
        frame_layout = QVBoxLayout(self.frame)
        frame_layout.setContentsMargins(4, 4, 4, 4)
        frame_layout.setSpacing(2)
        
        # Image label
        self.img_label = QLabel()
        self.img_label.setFixedSize(288, 162)
        self.img_label.setStyleSheet("background-color: black;")
        self.img_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        # Time label
        self.time_label = QLabel("00:00:00")
        self.time_label.setStyleSheet("color: white; font-size: 11px; font-weight: bold;")
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        
        frame_layout.addWidget(self.img_label)
        frame_layout.addWidget(self.time_label)
        layout.addWidget(self.frame)
        
    def set_content(self, pixmap, time_str):
        self.img_label.setPixmap(pixmap)
        self.time_label.setText(time_str)

class MergeItemWidget(QWidget):
    def __init__(self, text, item, main_window):
        super().__init__()
        self.item = item
        self.main_window = main_window
        self._last_click_time = 0
        
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 3, 5, 3)
        
        self.label = ElidedLabel(text)
        self.label.setStyleSheet("background: transparent;")
        
        from PySide6.QtWidgets import QSizePolicy
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        layout.addWidget(self.label, 1) # Stretch factor 1
        
        import os
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
        
        up_style = f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/list_up.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/list_up_hover.svg); }} QPushButton:pressed {{ border-image: url({assets_dir}/list_up.svg); }} QPushButton:disabled {{ border-image: url({assets_dir}/list_up_disabled.svg); }}"
        down_style = f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/list_down.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/list_down_hover.svg); }} QPushButton:pressed {{ border-image: url({assets_dir}/list_down.svg); }} QPushButton:disabled {{ border-image: url({assets_dir}/list_down_disabled.svg); }}"
        delete_style = f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/list_delete.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/list_delete_hover.svg); }} QPushButton:pressed {{ border-image: url({assets_dir}/list_delete.svg); }}"
        
        self.btn_up = QPushButton("")
        self.btn_up.setFixedSize(20, 20)
        self.btn_up.setStyleSheet(up_style)
        self.btn_up.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_up.clicked.connect(self.move_up)
        
        self.btn_down = QPushButton("")
        self.btn_down.setFixedSize(20, 20)
        self.btn_down.setStyleSheet(down_style)
        self.btn_down.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_down.clicked.connect(self.move_down)
        
        self.btn_delete = QPushButton("")
        self.btn_delete.setFixedSize(20, 20)
        self.btn_delete.setStyleSheet(delete_style)
        self.btn_delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_delete.clicked.connect(self.delete_item)
        
        layout.addWidget(self.btn_up)
        layout.addWidget(self.btn_down)
        layout.addWidget(self.btn_delete)
        
        self.setLayout(layout)
        
    def move_up(self):
        self.main_window.move_queue_item_up(self.item)
        
    def move_down(self):
        self.main_window.move_queue_item_down(self.item)
        
    def delete_item(self):
        self.main_window.delete_queue_item_by_obj(self.item)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            current_time = time.time() * 1000
            interval = QApplication.doubleClickInterval()
            if current_time - self._last_click_time < interval:
                self._last_click_time = 0
                self.main_window.play_multi_merge_item(self.item)
            else:
                self._last_click_time = current_time
                event.ignore()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        event.ignore()

class SegmentItemWidget(QWidget):
    def __init__(self, text, item, main_window):
        super().__init__()
        self.item = item
        self.main_window = main_window
        self._last_click_time = 0
        
        layout = QHBoxLayout()
        layout.setContentsMargins(5, 3, 5, 3)
        
        self.label = ElidedLabel(text)
        self.label.setStyleSheet("background: transparent;")
        
        from PySide6.QtWidgets import QSizePolicy
        self.label.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Preferred)
        
        layout.addWidget(self.label, 1) # Stretch factor 1
        
        import os
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
        delete_style = f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/list_delete.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/list_delete_hover.svg); }} QPushButton:pressed {{ border-image: url({assets_dir}/list_delete.svg); }}"
        
        self.btn_delete = QPushButton("")
        self.btn_delete.setFixedSize(20, 20)
        self.btn_delete.setStyleSheet(delete_style)
        self.btn_delete.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.btn_delete.clicked.connect(self.delete_item)
            
        layout.addWidget(self.btn_delete)
        self.setLayout(layout)
        
    def delete_item(self):
        self.main_window.delete_segment_by_obj(self.item)
        
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            current_time = time.time() * 1000
            interval = QApplication.doubleClickInterval()
            if current_time - self._last_click_time < interval:
                self._last_click_time = 0
                self.main_window.seek_to_segment(self.item)
            else:
                self._last_click_time = current_time
                event.ignore()
            return
        super().mousePressEvent(event)

    def mouseDoubleClickEvent(self, event):
        event.ignore()

class ClickableVideoWidget(QWidget):
    """
    A custom QWidget that emits a clicked signal on mouse release after the double click interval, 
    or a doubleClicked signal manually calculated via timing mousePressEvents.
    """
    clicked = Signal()
    doubleClicked = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._last_click_time = 0
        self._click_timer = QTimer(self)
        self._click_timer.setSingleShot(True)
        self._click_timer.timeout.connect(self._on_click_timeout)

    def mousePressEvent(self, event):
        super().mousePressEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            self._click_timer.stop() # 이전 클릭 취소 방어
            
            current_time = time.time() * 1000
            interval = QApplication.doubleClickInterval()
            if current_time - self._last_click_time < interval:
                self._last_click_time = 0
                self.doubleClicked.emit()
            else:
                self._last_click_time = current_time

    def mouseReleaseEvent(self, event):
        super().mouseReleaseEvent(event)
        if event.button() == Qt.MouseButton.LeftButton:
            if self._last_click_time != 0:
                self._click_timer.start(250)

    def mouseDoubleClickEvent(self, event):
        # 방어벽
        super().mouseDoubleClickEvent(event)

    def _on_click_timeout(self):
        self.clicked.emit()
        self._last_click_time = 0

class SeekSlider(QSlider):
    """
    A custom QSlider that allows clicking to seek to a specific position.
    Also visualizes multiple selected cut ranges with distinct markers.
    Displays a thumbnail tooltip on hover.
    """
    hover_time_changed = Signal(int, QPoint) # emits (time_msec, global_pos)
    hover_left = Signal()

    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.segments = [] # List of tuples (start, end)
        self.current_start = -1
        self.current_end = -1
        self.setMouseTracking(True) # Ensure we get mouseMoveEvent without pressing buttons

    def set_current_selection(self, start, end):
        self.current_start = start
        self.current_end = end
        self.update()

    def set_segments(self, segments):
        self.segments = segments
        self.update()

    def mouseMoveEvent(self, event):
        val = self.pixelPosToRangeValue(event.position().x())
        if self.maximum() > 0:
            # Map value to an estimated milliseconds based on MainWindow state
            # This requires external connection to know the total duration, we emit the raw slider 'value'.
            # It's better to pass the value and let MainWindow handle conversion, or pass fraction.
            frac = val / self.maximum()
            pos = event.globalPosition().toPoint()
            # Convert to just passing the raw value or fraction, letting main window do math
            self.hover_time_changed.emit(val, pos)
        super().mouseMoveEvent(event)

    def leaveEvent(self, event):
        self.hover_left.emit()
        super().leaveEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            val = self.pixelPosToRangeValue(event.position().x())
            self.setValue(val)
            self.sliderMoved.emit(val)  # Emit signal to update playback
            event.accept()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        from PySide6.QtSvg import QSvgRenderer
        from PySide6.QtCore import QRectF, Qt
        from PySide6.QtGui import QPainter, QImage, QColor, QPen, QRegion
        import os
        
        # 1. First draw the default QSlider (Track and Handle)
        super().paintEvent(event)
        
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)

        val_range = self.maximum() - self.minimum()
        if val_range <= 0:
            return

        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        # Get the rect of the slider handle
        sr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)
        
        # Clip out the handle's exact box, so anything drawn under this painter will NOT overwrite the handle!
        clip_region = QRegion(self.rect()).subtracted(QRegion(sr))
        painter.setClipRegion(clip_region)

        # 2. Add Groove helper stats
        gr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        slider_length = gr.width()
        slider_min_pos = gr.x()
        rect_height = gr.height()
        rect_y = gr.y()

        def get_px(val):
            if val < 0: return -1
            ratio = (val - self.minimum()) / val_range
            return slider_min_pos + int(ratio * slider_length)

        # 3. Draw our custom selection segments
        bar_height = 4
        bar_y = rect_y + (rect_height - bar_height) // 2
        
        for start, end in self.segments:
            s_px = get_px(start)
            e_px = get_px(end)
            if s_px >= 0 and e_px > s_px:
                painter.setBrush(QColor("#ffd700"))
                painter.setPen(QPen(QColor("#777777"), 1))
                painter.drawRoundedRect(s_px, bar_y, e_px - s_px, bar_height, 2, 2)

        start_px = get_px(self.current_start)
        end_px = get_px(self.current_end)

        if start_px >= 0 and end_px > start_px:
            painter.setBrush(QColor(0, 120, 215, 255))
            painter.setPen(QPen(QColor("#777777"), 1))
            painter.drawRoundedRect(start_px, bar_y, end_px - start_px, bar_height, 2, 2)

        # 4. Draw SVGs (Recolored to White)
        base_dir = os.path.dirname(os.path.abspath(__file__))
        
        def draw_svg_icon(path, x_pos, align="start"):
            renderer = QSvgRenderer(path)
            if renderer.isValid():
                sz = renderer.defaultSize()
                target_w = sz.width()
                target_h = sz.height()
                
                # Render to an image using original exact size
                img = QImage(int(target_w), int(target_h), QImage.Format.Format_ARGB32_Premultiplied)
                img.fill(Qt.GlobalColor.transparent)
                
                p2 = QPainter(img)
                p2.setRenderHint(QPainter.RenderHint.Antialiasing)
                renderer.render(p2, QRectF(0, 0, target_w, target_h))
                
                # Composition mode to make it fully white
                p2.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                p2.fillRect(img.rect(), Qt.GlobalColor.white)
                p2.end()
                
                # Align left edge to x_pos if start, align right edge to x_pos if end
                target_x = x_pos if align == "start" else x_pos - target_w
                target_y = bar_y - (target_h / 2.0) + (bar_height / 2.0)

                target_rect = QRectF(target_x, target_y, target_w, target_h)
                painter.drawImage(target_rect, img)

        # Draw markers for saved segments
        for start, end in self.segments:
            s_px = get_px(start)
            e_px = get_px(end)
            if s_px >= 0:
                draw_svg_icon(os.path.join(base_dir, "assets", "start_check_point.svg"), s_px, align="start")
            if e_px >= 0:
                draw_svg_icon(os.path.join(base_dir, "assets", "end_check_point.svg"), e_px, align="end")

        # Draw markers for current selection
        if start_px >= 0:
            draw_svg_icon(os.path.join(base_dir, "assets", "start_check_point.svg"), start_px, align="start")

        if end_px >= 0:
            draw_svg_icon(os.path.join(base_dir, "assets", "end_check_point.svg"), end_px, align="end")

        painter.end()

    def pixelPosToRangeValue(self, pos):
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        gr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        sr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderHandle, self)

        if self.orientation() == Qt.Orientation.Horizontal:
            sliderLength = sr.width()
            sliderMin = gr.x()
            sliderMax = gr.right() - sliderLength + 1
        else:
            sliderLength = sr.height()
            sliderMin = gr.y()
            sliderMax = gr.bottom() - sliderLength + 1
        
        pr = pos - sliderLength / 2
        value = QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), int(pr),
                                               sliderMax - sliderMin, opt.upsideDown)
        return value

class ExportWorker(QThread):
    progress = Signal(int)
    log = Signal(str)
    finished = Signal(bool, list, str)

    def __init__(self, tasks, parent=None):
        super().__init__(parent)
        self.tasks = tasks
        self.running = True
        self.process = None

    def run(self):
        total_duration_ms = sum(t.get('duration_ms', 0) for t in self.tasks)
        completed_ms = 0
        success_count = 0
        generated_files = []
        fail_messages = []
        
        for task in self.tasks:
            if not self.running:
                break
                
            cmd = task['cmd']
            desc = task.get('desc', '작업 중...')
            self.log.emit(desc)
            task_duration = task.get('duration_ms', 0)
            
            try:
                self.process = subprocess.Popen(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    universal_newlines=True,
                    encoding='utf-8',
                    errors='replace',
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0
                )
            except Exception as e:
                fail_messages.append(f"{desc} 실행 실패: {e}")
                continue

            time_pattern = re.compile(r"time=(\d+):(\d+):(\d+\.\d+)")
            
            while True:
                if not self.running:
                    try:
                        self.process.kill()
                    except:
                        pass
                    break
                    
                try:
                    line = self.process.stderr.readline()
                except Exception as e:
                    fail_messages.append(f"{desc} 로그 읽기 오류: {e}")
                    break
                    
                if not line and self.process.poll() is not None:
                    break
                    
                match = time_pattern.search(line)
                if match and total_duration_ms > 0:
                    h, m, s = match.groups()
                    current_ms = int(h) * 3600000 + int(m) * 60000 + float(s) * 1000
                    overall_progress_ms = completed_ms + current_ms
                    percent = int((overall_progress_ms / total_duration_ms) * 100)
                    self.progress.emit(min(99, percent))
            
            self.process.wait()
            if 'cleanup_file' in task and os.path.exists(task['cleanup_file']):
                try: os.remove(task['cleanup_file'])
                except: pass
                
            if self.process.returncode == 0 and self.running:
                success_count += 1
                if 'output' in task:
                    generated_files.append(task['output'])
            elif self.running:
                fail_messages.append(f"{desc} 에러 발생")
            
            completed_ms += task_duration
        
        if not self.running:
            self.finished.emit(False, generated_files, "사용자에 의해 취소됨")
        elif fail_messages:
            self.finished.emit(False, generated_files, "\n".join(fail_messages))
        else:
            self.progress.emit(100)
            self.finished.emit(True, generated_files, "모든 작업 완료")

    def cancel(self):
        self.running = False
        if self.process:
            try:
                self.process.kill()
            except:
                pass


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MKV Lossless Editor")
        icon_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "icon.svg")
        self.setWindowIcon(QIcon(icon_path))
        
        # Apply Dark Mode to Windows Title Bar
        try:
            hwnd = self.winId()
            # 20 is DWMWA_USE_IMMERSIVE_DARK_MODE in Windows 11 (and newer Win 10)
            # 19 was used in older Win 10 versions. We try 20 first, then 19.
            DWMWA_USE_IMMERSIVE_DARK_MODE = 20
            set_window_attribute = ctypes.windll.dwmapi.DwmSetWindowAttribute
            rendering_policy = ctypes.c_int(1)
            result = set_window_attribute(int(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE, ctypes.byref(rendering_policy), ctypes.sizeof(rendering_policy))
            if result != 0:
                DWMWA_USE_IMMERSIVE_DARK_MODE_OLD = 19
                set_window_attribute(int(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE_OLD, ctypes.byref(rendering_policy), ctypes.sizeof(rendering_policy))
        except Exception:
            pass
        
        # Apply Modern Dark Theme
        self.setStyleSheet("""
            QMainWindow {
                background-color: #2b2b2b;
                color: #ffffff;
            }
            QWidget {
                background-color: #2b2b2b;
                color: #ffffff;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
            }
            QPushButton {
                background-color: #3d3d3d;
                border: 1px solid #555555;
                border-radius: 5px;
                padding: 8px 16px;
                color: #ffffff;
            }
            QPushButton:hover {
                background-color: #4d4d4d;
                border-color: #0078d7;
            }
            QPushButton:pressed {
                background-color: #252525;
            }
            QPushButton:disabled {
                background-color: #2b2b2b;
                border-color: #333333;
                color: #777777;
            }
            QLabel {
                color: #dddddd;
            }
            QSlider#playbackSlider::groove:horizontal {
                border: 1px solid #3d3d3d;
                height: 6px;
                background: #1e1e1e;
                margin: 2px 0;
                border-radius: 3px;
            }
            QSlider#playbackSlider::sub-page:horizontal {
                background: #6b6b6b;
                height: 2px;
                border-radius: 1px;
                margin: 4px 0;
            }
            QSlider#playbackSlider::handle:horizontal {
                background: white;
                border: 1px solid black;
                width: 12px;
                height: 12px;
                margin: -4px 0px;
                border-radius: 7px;
            }
            QSlider#playbackSlider::handle:horizontal:hover {
                background: skyblue;
            }
            QSlider#volumeSlider::groove:horizontal {
                height: 4px;
                background: #1e1e1e;
                margin: 0px 4px;
                border-radius: 2px;
            }
            QSlider#volumeSlider::sub-page:horizontal {
                background: gold;
                border-radius: 2px;
            }
            QSlider#volumeSlider::add-page:horizontal {
                background: transparent;
            }
            QSlider#volumeSlider::handle:horizontal {
                background: #ffffff;
                width: 12px;
                height: 12px;
                margin: -4px -4px;
                border-radius: 6px;
            }
            QSlider#volumeSlider::handle:horizontal:hover {
                background: skyblue;
            }
            QTableWidget {
                gridline-color: #777777;
                border: 1px solid #777777;
                margin-top: 4px;
                margin-bottom: 4px;
            }
            QTableWidget::item {
                border-right: 1px solid #777777;
                border-bottom: 1px solid #777777;
                padding: 2px;
            }
            QHeaderView::section {
                background-color: #3d3d3d;
                border: 1px solid #777777;
                font-weight: bold;
                padding-top: 2px;
                padding-bottom: 2px;
                padding-left: 4px;
                padding-right: 4px;
            }
            QListWidget {
                border: 1px solid #777777;
                background-color: #2b2b2b;
            }
            QListWidget::item {
                border-bottom: 1px solid #444444;
            }
            QListWidget::item:hover {
                background-color: #3d3d3d;
            }
            QListWidget::item:selected {
                background-color: #4f3b15;
                color: #ffffff;
                border-left: 4px solid #ffcc00;
                border-bottom: 1px solid #3c2d10;
            }
            QWidget#videoCanvas {
                background-color: black;
            }
        """)

        # MPV Player - initialized after video widget is ready
        self._mpv_prev_pause_state = True
        
        # UI Components
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Video Widget (MPV renders directly onto this native window)
        self.video_widget = ClickableVideoWidget(self.central_widget)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_DontCreateNativeAncestors)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NativeWindow)
        # Prevent Qt from painting background to avoid flickering or theme interference
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground)
        self.video_widget.setMinimumSize(1344, 756)
        self.video_widget.setObjectName("videoCanvas")
        self.video_widget.setStyleSheet("QWidget#videoCanvas { background-color: #000000; }")
        # Ensure the stylesheet and custom painting are respected
        self.video_widget.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.video_widget.clicked.connect(self.toggle_play)
        self.video_widget.doubleClicked.connect(self.handle_video_double_click)
        self.video_widget.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.video_widget.customContextMenuRequested.connect(self.show_context_menu)
        self.layout.addWidget(self.video_widget, stretch=1)

        # Initialize MPV with hardware-accelerated GPU rendering
        self.player = mpv.MPV(
            wid=str(int(self.video_widget.winId())),
            hwdec='auto',
            vo='gpu',
            keep_open='yes',
            osd_level=0,
            cursor_autohide='no',
            input_cursor='no',
            input_default_bindings='no',
            input_vo_keyboard='no',
        )
        self.player.volume = 100

        # Timer for polling MPV state (replaces Qt signal-based updates)
        self._mpv_timer = QTimer(self)
        self._mpv_timer.setInterval(50)
        self._mpv_timer.timeout.connect(self._mpv_poll)
        self._mpv_timer.start()

        # Bottom Panel Container
        self.bottom_panel = QWidget()
        self.bottom_panel_layout = QVBoxLayout(self.bottom_panel)
        self.bottom_panel_layout.setContentsMargins(0, 0, 0, 0)
        self.bottom_panel_layout.setSpacing(4)
        
        # Timeline Slider
        self.slider = SeekSlider(Qt.Orientation.Horizontal)
        self.slider.setObjectName("playbackSlider")
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.sliderPressed.connect(self.slider_pressed)
        self.slider.sliderReleased.connect(self.slider_released)
        self.bottom_panel_layout.addWidget(self.slider)

        # Thumbnail setup
        self.thumbnail_thread = ThumbnailGrabberThread(self)
        self.thumbnail_thread.thumbnail_ready.connect(self.on_thumbnail_ready)
        self.thumbnail_thread.start()
        
        self.thumbnail_tooltip = ThumbnailTooltip(self)

        self.slider.hover_time_changed.connect(self.on_slider_hovered)
        self.slider.hover_left.connect(self.on_slider_leave)

        # Time Labels and Controls Layout
        self.controls_layout = QHBoxLayout()
        self.bottom_panel_layout.addLayout(self.controls_layout)

        # Pre Frame Button (1 Frame Back)
        self.pre_frame_icon = QIcon("assets/pre_frame.svg")
        self.pre_frame_button = QPushButton()
        self.pre_frame_button.setIcon(self.pre_frame_icon)
        self.pre_frame_button.setIconSize(QSize(42, 36))
        self.pre_frame_button.setFixedSize(42, 36)
        self.pre_frame_button.setStyleSheet("background-color: transparent; border: none;")
        self.pre_frame_button.setToolTip("1프레임 뒤로")
        self.pre_frame_button.clicked.connect(self.step_backward)
        self.pre_frame_button.setEnabled(False)
        self.controls_layout.addWidget(self.pre_frame_button)

        # Rewind Button (5s Back)
        self.rewind_icon = QIcon("assets/rewind.svg")
        self.rewind_button = QPushButton()
        self.rewind_button.setIcon(self.rewind_icon)
        self.rewind_button.setIconSize(QSize(42, 36))
        self.rewind_button.setFixedSize(42, 36)
        self.rewind_button.setStyleSheet("background-color: transparent; border: none;")
        self.rewind_button.setToolTip("5초 뒤로")
        self.rewind_button.clicked.connect(self.skip_backward)
        self.rewind_button.setEnabled(False)
        self.controls_layout.addWidget(self.rewind_button)

        # Play/Pause Button
        self.play_icon = QIcon("assets/play.svg")
        self.pause_icon = QIcon("assets/pause.svg")
        self.play_button = QPushButton()
        self.play_button.setIcon(self.play_icon)
        self.play_button.setIconSize(QSize(42, 36))
        self.play_button.setFixedSize(42, 36)
        self.play_button.setStyleSheet("background-color: transparent; border: none;")
        self.play_button.setToolTip("재생 / 닫힌 상태에선 열기 창 띄우기")
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(True) # 빈 상태일 때 눌러서 파일 열 수 있게 활성화 유지
        self.controls_layout.addWidget(self.play_button)

        # Stop Button
        self.stop_icon = QIcon("assets/stop.svg")
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.stop_icon)
        self.stop_button.setIconSize(QSize(42, 36))
        self.stop_button.setFixedSize(42, 36)
        self.stop_button.setStyleSheet("background-color: transparent; border: none;")
        self.stop_button.setToolTip("정지 (초기화)")
        self.stop_button.clicked.connect(self.stop_and_clear)
        self.stop_button.setEnabled(False) # 비활성화 기본값
        self.controls_layout.addWidget(self.stop_button)

        # Fast Forward Button
        self.fast_forward_icon = QIcon("assets/fast_forward.svg")
        self.fast_forward_button = QPushButton()
        self.fast_forward_button.setIcon(self.fast_forward_icon)
        self.fast_forward_button.setIconSize(QSize(42, 36))
        self.fast_forward_button.setFixedSize(42, 36)
        self.fast_forward_button.setStyleSheet("background-color: transparent; border: none;")
        self.fast_forward_button.setToolTip("5초 앞으로")
        self.fast_forward_button.clicked.connect(self.skip_forward)
        self.fast_forward_button.setEnabled(False)
        self.controls_layout.addWidget(self.fast_forward_button)

        # Next Frame Button
        self.next_frame_icon = QIcon("assets/next_frame.svg")
        self.next_frame_button = QPushButton()
        self.next_frame_button.setIcon(self.next_frame_icon)
        self.next_frame_button.setIconSize(QSize(42, 36))
        self.next_frame_button.setFixedSize(42, 36)
        self.next_frame_button.setStyleSheet("background-color: transparent; border: none;")
        self.next_frame_button.setToolTip("1프레임 앞으로")
        self.next_frame_button.clicked.connect(self.step_forward)
        self.next_frame_button.setEnabled(False)
        self.controls_layout.addWidget(self.next_frame_button)

        # Open File Button
        self.open_icon = QIcon("assets/open.svg")
        self.open_button = QPushButton()
        self.open_button.setIcon(self.open_icon)
        self.open_button.setIconSize(QSize(42, 36))
        self.open_button.setFixedSize(42, 36)
        self.open_button.setStyleSheet("background-color: transparent; border: none;")
        self.open_button.setToolTip("파일 열기")
        self.open_button.clicked.connect(self.open_file)
        self.controls_layout.addWidget(self.open_button)

        # Time Label
        self.time_label = QLabel("00:00:00 / 00:00:00")
        self.controls_layout.addWidget(self.time_label)
        
        # Volume Button & Slider
        self.volume_icon = QIcon("assets/volume_max.svg")
        self.volume_mute_icon = QIcon("assets/volume_mute.svg")
        self.volume_button = QPushButton()
        self.volume_button.setIcon(self.volume_icon)
        self.volume_button.setIconSize(QSize(24, 24))
        self.volume_button.setFixedSize(30, 30)
        self.volume_button.setStyleSheet("background-color: transparent; border: none;")
        self.volume_button.setToolTip("음소거 토글")
        self.volume_button.setProperty("hover_color", "red")
        self.volume_button.clicked.connect(self.toggle_mute)
        self.controls_layout.addWidget(self.volume_button)
        
        self.volume_slider = QSlider(Qt.Orientation.Horizontal)
        self.volume_slider.setObjectName("volumeSlider")
        self.volume_slider.setRange(0, 100)
        self.volume_slider.setValue(100)
        self.volume_slider.setFixedWidth(80)
        self.volume_slider.valueChanged.connect(self.set_volume)
        self.controls_layout.addWidget(self.volume_slider)
        
        # Spacer
        self.controls_layout.addStretch()

        # Cut Controls
        self.start_time = 0
        self.end_time = 0
        self.segments = [] # List of (start, end)
        
        self.start_icon = QIcon("assets/start_point.svg")
        self.set_start_btn = QPushButton()
        self.set_start_btn.setIcon(self.start_icon)
        self.set_start_btn.setIconSize(QSize(42, 36))
        self.set_start_btn.setFixedSize(42, 36)
        self.set_start_btn.setStyleSheet("background-color: transparent; border: none;")
        self.set_start_btn.setToolTip("시작점 [I]")
        self.set_start_btn.setProperty("hover_color", "gold")
        self.set_start_btn.setEnabled(False)
        self.set_start_btn.clicked.connect(self.set_start_mark)
        self.controls_layout.addWidget(self.set_start_btn)
        
        self.end_icon = QIcon("assets/end_point.svg")
        self.set_end_btn = QPushButton()
        self.set_end_btn.setIcon(self.end_icon)
        self.set_end_btn.setIconSize(QSize(42, 36))
        self.set_end_btn.setFixedSize(42, 36)
        self.set_end_btn.setStyleSheet("background-color: transparent; border: none;")
        self.set_end_btn.setToolTip("끝점 [O]")
        self.set_end_btn.setProperty("hover_color", "gold")
        self.set_end_btn.setEnabled(False)
        self.set_end_btn.clicked.connect(self.set_end_mark)
        self.controls_layout.addWidget(self.set_end_btn)

        self.move_start_point_icon = QIcon("assets/move_start_point.svg")
        self.move_start_point_btn = QPushButton()
        self.move_start_point_btn.setIcon(self.move_start_point_icon)
        self.move_start_point_btn.setIconSize(QSize(42, 36))
        self.move_start_point_btn.setFixedSize(42, 36)
        self.move_start_point_btn.setStyleSheet("background-color: transparent; border: none;")
        self.move_start_point_btn.setToolTip("시작점으로 이동")
        self.move_start_point_btn.setProperty("hover_color", "gold")
        self.move_start_point_btn.clicked.connect(self.jump_to_start)
        self.move_start_point_btn.setEnabled(False)
        self.controls_layout.addWidget(self.move_start_point_btn)
        
        self.move_end_point_icon = QIcon("assets/move_end_point.svg")
        self.move_end_point_btn = QPushButton()
        self.move_end_point_btn.setIcon(self.move_end_point_icon)
        self.move_end_point_btn.setIconSize(QSize(42, 36))
        self.move_end_point_btn.setFixedSize(42, 36)
        self.move_end_point_btn.setStyleSheet("background-color: transparent; border: none;")
        self.move_end_point_btn.setToolTip("끝점으로 이동")
        self.move_end_point_btn.setProperty("hover_color", "gold")
        self.move_end_point_btn.clicked.connect(self.jump_to_end)
        self.move_end_point_btn.setEnabled(False)
        self.controls_layout.addWidget(self.move_end_point_btn)

        self.inverse_btn = QPushButton()
        self.inverse_btn.setIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "select_inverse.svg")))
        self.inverse_btn.setIconSize(QSize(42, 36))
        self.inverse_btn.setFixedSize(42, 36)
        self.inverse_btn.setStyleSheet("background-color: transparent; border: none;")
        self.inverse_btn.setToolTip("선택 영역 반전")
        self.inverse_btn.setProperty("hover_color", "gold")
        self.inverse_btn.setEnabled(False)
        self.inverse_btn.clicked.connect(self.inverse_segments)
        self.controls_layout.addWidget(self.inverse_btn)

        self.clear_btn = QPushButton()
        self.clear_btn.setIcon(QIcon(os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets", "deselect.svg")))
        self.clear_btn.setIconSize(QSize(42, 36))
        self.clear_btn.setFixedSize(42, 36)
        self.clear_btn.setStyleSheet("background-color: transparent; border: none;")
        self.clear_btn.setToolTip("선택 초기화")
        self.clear_btn.setProperty("hover_color", "gold")
        self.clear_btn.setEnabled(False)
        self.clear_btn.clicked.connect(self.clear_segments)
        self.controls_layout.addWidget(self.clear_btn)

        self.merge_checkbox = QCheckBox("다중 구간 병합 (Merge)")
        self.merge_checkbox.setStyleSheet("color: #cccccc;")
        self.merge_checkbox.setEnabled(False)
        self.controls_layout.addWidget(self.merge_checkbox)

        self.export_btn = QPushButton("내보내기")
        self.export_btn.clicked.connect(self.export_video)
        self.export_btn.setEnabled(False)
        self.controls_layout.addWidget(self.export_btn)

        # Add Horizontal Line Separator
        self.separator = QFrame()
        self.separator.setFrameShape(QFrame.Shape.HLine)
        self.separator.setFrameShadow(QFrame.Shadow.Sunken)
        self.separator.setStyleSheet("background-color: #3d3d3d;")
        self.bottom_panel_layout.addWidget(self.separator)

        # Tracks Table Widget Header
        self.tracks_header_layout = QHBoxLayout()
        self.tracks_header_layout.setContentsMargins(0, 0, 0, 0)
        
        self.tracks_label = QLabel("트랙, 챕터와 태그")
        self.tracks_label.setStyleSheet("color: gold; font-weight: bold; margin-top: 4px; margin-bottom: 4px;")
        self.tracks_header_layout.addWidget(self.tracks_label)
        
        self.tracks_header_layout.addStretch()
        
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
        
        self.btn_maximize = QPushButton()
        self.btn_maximize.setFixedSize(20, 20)
        self.btn_maximize.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_maximize.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/max_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/max_screen_hover.svg); }}")
        self.btn_maximize.setToolTip("창 최대화 / 복원 (비디오 더블클릭)")
        self.btn_maximize.clicked.connect(self.toggle_maximized)
        self.tracks_header_layout.addWidget(self.btn_maximize)
        
        self.btn_fullscreen = QPushButton()
        self.btn_fullscreen.setFixedSize(20, 20)
        self.btn_fullscreen.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_fullscreen.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/full_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/full_screen_hover.svg); }}")
        self.btn_fullscreen.setToolTip("순수 전체화면 모드 (Alt+Enter)")
        self.btn_fullscreen.clicked.connect(self.toggle_true_fullscreen)
        self.tracks_header_layout.addWidget(self.btn_fullscreen)
        
        self.bottom_panel_layout.addLayout(self.tracks_header_layout)
        
        self.tracks_table = QTableWidget(0, 9)
        self.tracks_table.setHorizontalHeaderLabels([
            "", "유형", "코덱", "항목 복사", "언어", "이름", "ID", "기본 트랙", "Forced display"
        ])
        
        # Header configuration
        header = self.tracks_table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setStretchLastSection(True)
        self.tracks_table.verticalHeader().setVisible(False)
        self.tracks_table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.tracks_table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.tracks_table.setShowGrid(True)
        self.tracks_table.setShowGrid(True)
        self.tracks_table.setColumnWidth(0, 24) # 체크박스 중앙 정렬용 적절한 폭
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Fixed)
        self.tracks_table.verticalHeader().setDefaultSectionSize(24) # 셀 높이 압축
        
        self._updating_all_tracks = False
        
        self.header_checkbox = QCheckBox(header.viewport())
        self.header_checkbox.setCursor(Qt.CursorShape.PointingHandCursor)
        self.header_checkbox.stateChanged.connect(self.toggle_all_tracks)
        
        header.setSectionsClickable(True)
        header.sectionClicked.connect(self.on_header_clicked)
        
        # Keep checkbox positioned correctly when resizing or scrolling
        header.sectionResized.connect(self.update_header_widgets_geometry)
        self.tracks_table.horizontalScrollBar().valueChanged.connect(self.update_header_widgets_geometry)
        
        # Schedule initial positioning
        QTimer.singleShot(50, self.update_header_widgets_geometry)
        
        self.tracks_table.itemChanged.connect(self.update_header_checkbox_state)
        self.tracks_table.itemChanged.connect(self.check_export_ready)
        
        self.tracks_table.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        
        # 동적 흰색 체크박스 SVG 아이콘 생성
        check_path = os.path.join(os.path.dirname(__file__), "assets/check_white.svg")
        with open(check_path, "w", encoding="utf-8") as f:
            f.write('<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg"><path d="M5 13L9 17L19 7" stroke="white" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"/></svg>')
            
        self.tracks_table.setStyleSheet(f"""
            QTableWidget {{ outline: none; }}
            QTableWidget::item {{ border: none; padding: 0px; }}
            QTableWidget::item:focus {{ outline: none; border: none; }}
            QTableWidget::indicator {{
                width: 13px; height: 13px;
                background-color: transparent;
                border: 1px solid white;
                border-radius: 2px;
                margin-left: 7px;
            }}
            QTableWidget::indicator:checked {{
                image: url("{check_path.replace(chr(92), '/')}");
            }}
            QTableWidget::indicator:hover {{
                border: 1px solid #aaa;
            }}
        """)
        
        self.header_checkbox.setStyleSheet(f"""
            QCheckBox {{
                background: transparent;
            }}
            QCheckBox::indicator {{
                width: 13px; height: 13px;
                background-color: transparent;
                border: 1px solid white;
                border-radius: 2px;
                margin-left: 10px;
            }}
            QCheckBox::indicator:checked {{
                image: url("{check_path.replace(chr(92), '/')}");
            }}
            QCheckBox::indicator:hover {{
                border: 1px solid #aaa;
            }}
        """)
        
        # Increase height to show more rows comfortably
        self.tracks_table.setFixedHeight(140)
        self.bottom_panel_layout.addWidget(self.tracks_table)

        # Add Horizontal Line Separator 2
        self.separator2 = QFrame()
        self.separator2.setFrameShape(QFrame.Shape.HLine)
        self.separator2.setFrameShadow(QFrame.Shadow.Sunken)
        self.separator2.setStyleSheet("background-color: #3d3d3d; margin-top: 4px; margin-bottom: 4px;")
        self.bottom_panel_layout.addWidget(self.separator2)

        # Bottom Lists Layout (Horizontal Split)
        self.bottom_lists_layout = QHBoxLayout()
        self.bottom_panel_layout.addLayout(self.bottom_lists_layout)

        # --- Left: Segments List Widget ---
        self.segments_layout = QVBoxLayout()
        self.segments_label = QLabel("선택된 자르기 구간 목록")
        self.segments_label.setStyleSheet("color: gold; font-weight: bold; margin-top: 4px; margin-bottom: 4px;")
        self.segments_layout.addWidget(self.segments_label)
        
        self.segments_list = QListWidget()
        self.segments_list.setFixedHeight(75)
        self.segments_list.itemDoubleClicked.connect(self.seek_to_segment)
        
        self.delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.segments_list)
        self.delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.delete_shortcut.activated.connect(self.delete_selected_segment)
        
        self.segments_layout.addWidget(self.segments_list)
        self.bottom_lists_layout.addLayout(self.segments_layout)

        # --- Right: Multi-Merge Queue Widget ---
        self.merge_queue_layout = QVBoxLayout()
        self.merge_queue_label = QLabel("다중 파일 병합 대기열")
        self.merge_queue_label.setStyleSheet("color: gold; font-weight: bold; margin-top: 4px; margin-bottom: 4px;")
        self.merge_queue_layout.addWidget(self.merge_queue_label)
        
        self.merge_queue_list = QListWidget()
        self.merge_queue_list.setFixedHeight(75)
        self.merge_queue_list.itemDoubleClicked.connect(self.play_multi_merge_item)
        self.merge_queue_list.setDragDropMode(QAbstractItemView.DragDropMode.InternalMove)
        self.merge_queue_list.model().rowsMoved.connect(self.sync_merge_queue)
        
        self.merge_delete_shortcut = QShortcut(QKeySequence(Qt.Key.Key_Delete), self.merge_queue_list)
        self.merge_delete_shortcut.setContext(Qt.ShortcutContext.WidgetShortcut)
        self.merge_delete_shortcut.activated.connect(self.delete_merge_queue_item)
        
        self.merge_queue_layout.addWidget(self.merge_queue_list)
        self.bottom_lists_layout.addLayout(self.merge_queue_layout)
        
        # Add the entire bottom panel to the main layout
        self.layout.addWidget(self.bottom_panel)
        
        
        self.setup_shortcuts()
        
        self._is_true_fullscreen = False
        QApplication.instance().installEventFilter(self)

        # Signals
        # MPV uses timer-based polling (_mpv_poll) instead of Qt signals

        # Status Bar
        self.statusBar().showMessage("준비 완료")
        self.statusBar().setStyleSheet("color: #cccccc;")

        self.file_path = ""
        self.is_slider_pressed = False
        self._was_playing_before_slider = False
        self.is_multi_merge_mode = False
        self.multi_merge_files = []
        self.multi_merge_play_idx = -1
        
        # Setup Hover Filter Class with QPixmap Colorization
        class IconColorizeHoverFilter(QObject):
            def eventFilter(self, obj, event):
                if event.type() == QEvent.Type.Enter:
                    current_icon = obj.icon()
                    if current_icon.isNull():
                        return super().eventFilter(obj, event)
                    
                    obj._icon_normal_backup = current_icon
                    
                    size = obj.iconSize()
                    if size.isEmpty(): size = QSize(42, 36)
                    
                    pm = current_icon.pixmap(size)
                    painter = QPainter(pm)
                    painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
                    
                    fill_color = obj.property("hover_color")
                    if not fill_color: fill_color = "skyblue"
                    
                    painter.fillRect(pm.rect(), QColor(fill_color))
                    painter.end()
                    
                    obj.setIcon(QIcon(pm))
                    
                elif event.type() == QEvent.Type.Leave:
                    if hasattr(obj, '_icon_normal_backup'):
                        obj.setIcon(obj._icon_normal_backup)
                
                return super().eventFilter(obj, event)
                
        self.icon_hover_filter = IconColorizeHoverFilter(self)
        
        for child in self.findChildren(QPushButton):
            if child.styleSheet() and "transparent" in child.styleSheet():
                child.installEventFilter(self.icon_hover_filter)
        
        # Enable Drag and Drop (Handled by Global Filter in main.py)
        self.setAcceptDrops(True)
        self._is_centered = False
        
        # Thumbnail Tooltip and Thread 
        self.thumbnail_thread = ThumbnailGrabberThread(self)
        self.thumbnail_thread.thumbnail_ready.connect(self.on_thumbnail_ready)
        self.thumbnail_thread.start()
        
        self.thumbnail_tooltip = ThumbnailTooltip(self)

        self.slider.hover_time_changed.connect(self.on_slider_hovered)
        self.slider.hover_left.connect(self.on_slider_leave)

    def on_slider_hovered(self, val, global_pos):
        if not hasattr(self, 'file_path') or not self.file_path or self._mpv_dur_ms() <= 0:
            return
            
        duration = self._mpv_dur_ms()
        val_range = self.slider.maximum() - self.slider.minimum()
        if val_range <= 0: return
        
        fraction = val / val_range
        time_msec = int(duration * fraction)
        
        time_str = QTime(0, 0, 0).addMSecs(max(0, time_msec)).toString("hh:mm:ss")
        
        tip_w = self.thumbnail_tooltip.width()
        tip_h = self.thumbnail_tooltip.height()
        
        x = global_pos.x() - tip_w // 2
        y_offset = 30
        y = global_pos.y() - tip_h - y_offset
        
        self.thumbnail_tooltip.time_label.setText(time_str)
        self.thumbnail_tooltip.move(x, y)
        if not self.thumbnail_tooltip.isVisible():
            self.thumbnail_tooltip.show()
            
        if self.file_path:
            self.thumbnail_thread.request_thumbnail(self.file_path, time_msec)

    def on_thumbnail_ready(self, time_msec, img_data):
        if not hasattr(self, 'thumbnail_tooltip') or not self.thumbnail_tooltip.isVisible():
            return
            
        qimg = QImage()
        loaded = qimg.loadFromData(img_data)
        
        if loaded and not qimg.isNull():
            pixmap = QPixmap.fromImage(qimg).scaled(288, 162, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation)
            self.thumbnail_tooltip.img_label.setPixmap(pixmap)

    def on_slider_leave(self):
        if hasattr(self, 'thumbnail_tooltip'):
            self.thumbnail_tooltip.hide()

    def setup_shortcuts(self):
        self.app_shortcuts = []
        def add_shortcut(key, func):
            shortcut = QShortcut(QKeySequence(key), self)
            shortcut.setContext(Qt.ShortcutContext.ApplicationShortcut)
            shortcut.activated.connect(func)
            self.app_shortcuts.append(shortcut)
            
        add_shortcut(Qt.Key.Key_Left, self.skip_backward)
        add_shortcut(Qt.Key.Key_Right, self.skip_forward)
        add_shortcut(Qt.Key.Key_Up, self.volume_up)
        add_shortcut(Qt.Key.Key_Down, self.volume_down)
        add_shortcut(Qt.Key.Key_M, self.toggle_mute)
        add_shortcut(Qt.Key.Key_F, self.step_forward)
        add_shortcut(Qt.Key.Key_D, self.step_backward)
        add_shortcut(Qt.Key.Key_BracketLeft, self.set_start_mark)
        add_shortcut(Qt.Key.Key_BracketRight, self.set_end_mark)
        add_shortcut(Qt.Key.Key_Comma, self.jump_to_start)
        add_shortcut(Qt.Key.Key_Period, self.jump_to_end)
        add_shortcut(Qt.Key.Key_Space, self.toggle_play)
        add_shortcut(Qt.Key.Key_Escape, self.stop_playback)
        
        alt_enter = QShortcut(QKeySequence("Alt+Return"), self)
        alt_enter.setContext(Qt.ShortcutContext.ApplicationShortcut)
        alt_enter.activated.connect(self.toggle_true_fullscreen)
        
        alt_enter2 = QShortcut(QKeySequence("Alt+Enter"), self)
        alt_enter2.setContext(Qt.ShortcutContext.ApplicationShortcut)
        alt_enter2.activated.connect(self.toggle_true_fullscreen)

    def eventFilter(self, obj, event):
        if self._is_true_fullscreen and event.type() == QEvent.Type.MouseMove:
            if hasattr(event, "globalPosition"):
                global_pos = event.globalPosition().toPoint()
            else:
                global_pos = event.globalPos() if hasattr(event, "globalPos") else QCursor.pos()
                
            y = global_pos.y()
            screen = QApplication.primaryScreen()
            if screen:
                screen_h = screen.geometry().height()
                if self.bottom_panel.isHidden() and self._is_true_fullscreen:
                    # 패널이 숨어있을 때는 바탕화면 하단 10% 이하로 내려가면 나타나게 트리거
                    if y > screen_h * 0.90:
                        self.bottom_panel.show()
                        
                elif not self.bottom_panel.isHidden() and self._is_true_fullscreen:
                    # 패널이 나타나있을 때는 마우스가 폼/패널 영역 안에 있는지 확인
                    top_left = self.bottom_panel.mapToGlobal(QPoint(0, 0))
                    from PySide6.QtCore import QRect
                    panel_rect = QRect(top_left, self.bottom_panel.size())
                    
                    if not panel_rect.contains(global_pos):
                        self.bottom_panel.hide()
                        
        return super().eventFilter(obj, event)

    def resizeEvent(self, event):
        super().resizeEvent(event)
    def changeEvent(self, event):
        if event.type() == QEvent.Type.WindowStateChange:
            assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
            if hasattr(self, 'btn_maximize'):
                if self.isMaximized():
                    self.btn_maximize.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/min_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/min_screen_hover.svg); }}")
                else:
                    self.btn_maximize.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/max_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/max_screen_hover.svg); }}")
        super().changeEvent(event)

    def showEvent(self, event):
        super().showEvent(event)
        if not self._is_centered:
            self.center_on_screen()
            self._is_centered = True

    def center_on_screen(self):
        screen = QApplication.primaryScreen()
        if screen:
            screen_geometry = screen.availableGeometry()
            window_geometry = self.frameGeometry()
            window_geometry.moveCenter(screen_geometry.center())
            self.move(window_geometry.topLeft())

    def handle_video_double_click(self):
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
        if self._is_true_fullscreen:
            self._is_true_fullscreen = False
            self.layout.setContentsMargins(9, 9, 9, 9)
            self.bottom_panel.show()
            self.showNormal()
            self.statusBar().show()
            if hasattr(self, 'menubar') and self.menubar: self.menubar.show()
            self.statusBar().showMessage("기본 화면으로 복귀")
            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/full_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/full_screen_hover.svg); }}")
        else:
            self.toggle_maximized()

    def toggle_maximized(self):
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
        
        if self._is_true_fullscreen:
            self._is_true_fullscreen = False
            self.layout.setContentsMargins(9, 9, 9, 9)
            self.bottom_panel.show()
            self.showMaximized()
            self.statusBar().show()
            if hasattr(self, 'menubar') and self.menubar: self.menubar.show()
            self.statusBar().showMessage("최대화 모드")
            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/full_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/full_screen_hover.svg); }}")
            return

        if self.isMaximized():
            self.showNormal()
            self.statusBar().showMessage("기본 화면으로 복귀")
            if hasattr(self, 'btn_maximize'):
                self.btn_maximize.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/max_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/max_screen_hover.svg); }}")
        else:
            self.showMaximized()
            self.statusBar().showMessage("최대화 모드")
            if hasattr(self, 'btn_maximize'):
                self.btn_maximize.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/min_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/min_screen_hover.svg); }}")

    def toggle_true_fullscreen(self):
        assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets").replace("\\", "/")
        if self.isFullScreen():
            self._is_true_fullscreen = False
            self.central_widget.setStyleSheet("")
            self.layout.setContentsMargins(9, 9, 9, 9)
            self.bottom_panel.show()
            self.showNormal()
            self.statusBar().show()
            if hasattr(self, 'menubar') and self.menubar: self.menubar.show()
            self.statusBar().showMessage("기본 화면으로 복귀")
            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/full_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/full_screen_hover.svg); }}")
        else:
            self._is_true_fullscreen = True
            self.central_widget.setObjectName("centralWidget")
            self.central_widget.setStyleSheet("QWidget#centralWidget { background-color: black; }")
            self.layout.setContentsMargins(0, 0, 0, 0)
            self.bottom_panel.hide()
            self.showFullScreen()
            self.statusBar().hide()
            if hasattr(self, 'menubar') and self.menubar: self.menubar.hide()
            if hasattr(self, 'btn_fullscreen'):
                self.btn_fullscreen.setStyleSheet(f"QPushButton {{ background: transparent; border: none; border-image: url({assets_dir}/defalt_screen.svg); }} QPushButton:hover {{ border-image: url({assets_dir}/defalt_screen_hover.svg); }}")

    def handle_dropped_files(self, file_paths):
        valid_extensions = ['.mkv', '.mp4', '.avi']
        valid_files = [f for f in file_paths if os.path.splitext(f)[1].lower() in valid_extensions]
        
        if not valid_files:
            QMessageBox.warning(self, "지원하지 않는 파일", "비디오 파일(.mkv, .mp4, .avi)만 열 수 있습니다.")
            return

        if len(valid_files) == 1:
            self.load_file(valid_files[0])
        else:
            self.load_multi_files(valid_files)

    def open_file(self):
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilters(["Video files (*.mkv *.mp4 *.avi)"])
        file_dialog.setFileMode(QFileDialog.FileMode.ExistingFiles)
        if file_dialog.exec():
            files = file_dialog.selectedFiles()
            if files:
                if len(files) == 1:
                    self.load_file(files[0])
                else:
                    self.load_multi_files(files)

    def load_multi_files(self, files):
        self.stop_and_clear()
        self.is_multi_merge_mode = True
        self.multi_merge_files = list(files)
        
        self._refresh_merge_queue_ui()
            
        self.setWindowTitle("MKV Lossless Cutter - 다중 파일 병합 모드")
        self.export_btn.setEnabled(True)
        self.export_btn.setText("병합 시작")
        self.statusBar().showMessage(f"{len(files)}개의 파일이 병합 대기열에 추가되었습니다.")

        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.rewind_button.setEnabled(True)
        self.pre_frame_button.setEnabled(True)
        self.fast_forward_button.setEnabled(True)
        self.next_frame_button.setEnabled(True)
        self.move_start_point_btn.setEnabled(False)
        self.move_end_point_btn.setEnabled(False)
        self.set_start_btn.setEnabled(False)
        self.set_end_btn.setEnabled(False)
        self.inverse_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.segments_label.setText('선택된 자르기 구간 목록 <span style="color: #ff6666;">(병합 모드 - 구간 설정 불가)</span>')
        self.slider.setEnabled(True)
        
        # 첫 번째 영상부터 재생 시작
        if files:
            self._play_queue_index(0)

    def _play_queue_index(self, index):
        if 0 <= index < len(self.multi_merge_files):
            self.multi_merge_play_idx = index
            file_path = self.multi_merge_files[index]
            self.file_path = file_path
            
            # Clear previous thumbnail
            if hasattr(self, 'thumbnail_tooltip') and self.thumbnail_tooltip:
                self.thumbnail_tooltip.img_label.clear()
                
            self.player.play(file_path)
            self.play_video()
            self.merge_queue_list.setCurrentRow(index)
            self.top_title_label.setText(os.path.basename(file_path))
            self.setWindowTitle(f"MKV Lossless Cutter - 다중 파일 미리보기 ({index+1}/{len(self.multi_merge_files)})")

    def play_multi_merge_item(self, item):
        if not self.is_multi_merge_mode: return
        row = self.merge_queue_list.row(item)
        self._play_queue_index(row)

    def load_file(self, file_path):
        self.file_path = file_path
        
        # Clear previous thumbnail
        if hasattr(self, 'thumbnail_tooltip') and self.thumbnail_tooltip:
            self.thumbnail_tooltip.img_label.clear()
            
        self.top_title_label.setText(os.path.basename(self.file_path))
        self.player.play(self.file_path)
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.rewind_button.setEnabled(True)
        self.pre_frame_button.setEnabled(True)
        self.fast_forward_button.setEnabled(True)
        self.next_frame_button.setEnabled(True)
        self.move_start_point_btn.setEnabled(True)
        self.move_end_point_btn.setEnabled(True)
        self.set_start_btn.setEnabled(True)
        self.set_end_btn.setEnabled(True)
        self.inverse_btn.setEnabled(True)
        self.clear_btn.setEnabled(True)
        self.segments_label.setText("선택된 자르기 구간 목록")
        self.play_video()
        self.setWindowTitle(f"MKV Lossless Cutter - {os.path.basename(self.file_path)}")
        
        # Reset selection
        self.start_time = 0
        self.end_time = 0
        self.segments = []
        self.slider.set_segments(self.segments)
        self.slider.set_current_selection(-1, -1)
        self.update_segments_list()
        
        # Load tracks into table
        self.load_tracks_to_table(self.file_path)
        
        self.check_export_ready()
        self.statusBar().showMessage(f"파일 불러옴: {os.path.basename(self.file_path)}")

    def stop_and_clear(self):
        self.is_multi_merge_mode = False
        self.multi_merge_files = []
        self._refresh_merge_queue_ui()
        self.file_path = None
        self.player.command('stop')
        
        self.slider.setEnabled(False)
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.rewind_button.setEnabled(False)
        self.pre_frame_button.setEnabled(False)
        self.fast_forward_button.setEnabled(False)
        self.next_frame_button.setEnabled(False)
        self.move_start_point_btn.setEnabled(False)
        self.move_end_point_btn.setEnabled(False)
        self.set_start_btn.setEnabled(False)
        self.set_end_btn.setEnabled(False)
        self.inverse_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.segments_label.setText("선택된 자르기 구간 목록")
        self.multi_merge_play_idx = -1
        self.merge_queue_list.clear()
        self.export_btn.setText("내보내기")
        self.slider.setEnabled(True)

        self.player.command('stop')
        self.file_path = None
        self.play_button.setEnabled(True) # 빈 상태일 때 누를 수 있게 유지
        self.play_button.setToolTip("재생 / 파일 새로 열기")
        self.stop_button.setEnabled(False)
        self.rewind_button.setEnabled(False)
        self.pre_frame_button.setEnabled(False)
        self.fast_forward_button.setEnabled(False)
        self.next_frame_button.setEnabled(False)
        self.move_start_point_btn.setEnabled(False)
        self.move_end_point_btn.setEnabled(False)
        self.set_start_btn.setEnabled(False)
        self.set_end_btn.setEnabled(False)
        self.inverse_btn.setEnabled(False)
        self.clear_btn.setEnabled(False)
        self.play_button.setIcon(self.play_icon)
        self.setWindowTitle("MKV Lossless Cutter")
        
        # UI 및 타임라인 초기화
        self.slider.setRange(0, 0)
        self.slider.setValue(0)
        self.time_label.setText("00:00:00 / 00:00:00")
        
        # 선택 구간 초기화
        self.start_time = 0
        self.end_time = 0
        self.segments = []
        self.slider.set_segments(self.segments)
        self.slider.set_current_selection(-1, -1)
        self.update_segments_list()
        self.tracks_table.setRowCount(0)
        self.check_export_ready()
        self.statusBar().showMessage("준비 완료")

    def set_button_icon(self, btn, icon, tooltip=None):
        btn._icon_normal_backup = icon
        if tooltip: btn.setToolTip(tooltip)
        if btn.underMouse():
            size = btn.iconSize()
            if size.isEmpty(): size = QSize(42, 36)
            pm = icon.pixmap(size)
            painter = QPainter(pm)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            fill_color = btn.property("hover_color") or "skyblue"
            painter.fillRect(pm.rect(), QColor(fill_color))
            painter.end()
            btn.setIcon(QIcon(pm))
        else:
            btn.setIcon(icon)

    def media_state_changed(self, is_playing):
        if is_playing:
            self.set_button_icon(self.play_button, self.pause_icon, "일시정지")
            self.statusBar().showMessage("재생")
        else:
            self.set_button_icon(self.play_button, self.play_icon, "재생")
            self.statusBar().showMessage("일시정지")

    def toggle_play(self):
        if not self.file_path and not self.is_multi_merge_mode:
            self.open_file()
            return
        try:
            self.player.pause = not self.player.pause
        except:
            pass

    def play_video(self):
        try:
            self.player.pause = False
        except:
            pass

    def pause_video(self):
        try:
            self.player.pause = True
        except:
            pass

    def toggle_subtitles(self):
        if not hasattr(self, 'player'): return
        try:
            current_vis = getattr(self.player, 'sub_visibility', True)
            self.player.sub_visibility = not current_vis
            state_str = "보이기" if not current_vis else "끄기"
            self.statusBar().showMessage(f"자막 {state_str}")
        except:
            pass

    def show_context_menu(self, pos):
        menu = QMenu(self)
        menu.setWindowFlags(menu.windowFlags() | Qt.WindowType.FramelessWindowHint | Qt.WindowType.NoDropShadowWindowHint)
        menu.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        menu.setStyleSheet("""
            QMenu {
                background-color: rgba(30, 30, 30, 240);
                color: #e0e0e0;
                border: 1px solid #555555;
                border-radius: 8px;
                padding: 8px 0px;
                font-family: 'Segoe UI', sans-serif;
                font-size: 14px;
            }
            QMenu::item {
                padding: 8px 36px 8px 24px;
                margin: 2px 8px;
                border-radius: 4px;
                background-color: transparent;
            }
            QMenu::item:selected {
                background-color: rgba(255, 255, 255, 25);
                color: #ffffff;
            }
            QMenu::separator {
                height: 1px;
                background-color: #444444;
                margin: 6px 16px;
            }
        """)

        act_open = menu.addAction("파일 열기... (Ctrl+O)")
        act_open.triggered.connect(self.open_file)
        menu.addSeparator()

        act_play = menu.addAction("재생 / 일시정지 (Space)")
        act_play.triggered.connect(self.toggle_play)

        act_stop = menu.addAction("정지 (S)")
        act_stop.triggered.connect(self.stop_playback)
        menu.addSeparator()

        act_mute = menu.addAction("음소거 토글 (M)")
        act_mute.triggered.connect(self.toggle_mute)

        act_sub = menu.addAction("자막 보이기 / 끄기")
        act_sub.triggered.connect(self.toggle_subtitles)
        menu.addSeparator()

        act_full = menu.addAction("전체 화면 (Alt+Enter)")
        act_full.triggered.connect(self.toggle_true_fullscreen)
        menu.addSeparator()

        act_exit = menu.addAction("종료 (Esc)")
        act_exit.triggered.connect(self.close)

        global_pos = self.video_widget.mapToGlobal(pos)
        menu.exec(global_pos)

    def toggle_mute(self):
        try:
            self.player.mute = not self.player.mute
            is_muted = self.player.mute
        except:
            is_muted = False
        
        if is_muted:
            size = QSize(24, 24)
            pm = self.volume_mute_icon.pixmap(size)
            painter = QPainter(pm)
            painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceIn)
            painter.fillRect(pm.rect(), QColor("red"))
            painter.end()
            red_mute_icon = QIcon(pm)
            
            self.volume_button.setIcon(red_mute_icon)
            self.volume_button.setProperty("hover_color", "skyblue")
            if hasattr(self.volume_button, "_icon_normal_backup"):
                self.volume_button._icon_normal_backup = red_mute_icon
                
            self.volume_button.setToolTip("음소거 해제")
            self.statusBar().showMessage("음소거 설정됨")
        else:
            self.volume_button.setIcon(self.volume_icon)
            self.volume_button.setProperty("hover_color", "red")
            if hasattr(self.volume_button, "_icon_normal_backup"):
                self.volume_button._icon_normal_backup = self.volume_icon
                
            self.volume_button.setToolTip("음소거 토글")
            self.statusBar().showMessage("음소거 해제됨")

    def volume_up(self):
        val = min(100, self.volume_slider.value() + 5)
        self.volume_slider.setValue(val)
        self.set_volume(val)
        
    def volume_down(self):
        val = max(0, self.volume_slider.value() - 5)
        self.volume_slider.setValue(val)
        self.set_volume(val)

    def stop_playback(self):
        if self.isFullScreen():
            self.toggle_fullscreen()
            return

        self.stop_and_clear()

    def set_volume(self, value):
        # value is 0-100, mpv uses 0-100 directly
        try:
            self.player.volume = value
        except:
            pass
        
        if value == 0:
            self.volume_button.setIcon(self.volume_mute_icon)
            try: self.player.mute = True
            except: pass
            self.statusBar().showMessage("음소거 설정됨")
        else:
            self.volume_button.setIcon(self.volume_icon)
            try: self.player.mute = False
            except: pass
            self.statusBar().showMessage(f"볼륨: {value}%")
            
    def set_position(self, position):
        try:
            self.player.seek(position / 1000.0, "absolute+exact")
        except:
            pass

    def step_backward(self):
        if self.file_path:
            try:
                self.player.frame_back_step()
            except:
                pass
            self.statusBar().showMessage("1프레임 뒤로")

    def skip_backward(self):
        if self.file_path:
            try:
                self.player.seek(-5, "relative")
            except:
                pass
            self.statusBar().showMessage("5초 뒤로")

    def skip_forward(self):
        if self.file_path:
            try:
                self.player.seek(5, "relative")
            except:
                pass
            self.statusBar().showMessage("5초 앞으로")

    def step_forward(self):
        if self.file_path:
            try:
                self.player.frame_step()
            except:
                pass
            self.statusBar().showMessage("1프레임 앞으로")

    def jump_to_start(self):
        if getattr(self, 'is_multi_merge_mode', False): return
        if not self.file_path: return
        starts = [s[0] for s in self.segments]
        # 현재 활성화된(저장 대기 중인) 설정 구간이 있다면 포함
        if self.start_time != 0 or self.end_time != 0:
            starts.append(self.start_time)
            
        if not starts:
            self.set_position(self.start_time)
            return
            
        starts = sorted(list(set(starts)))
        current_pos = self._mpv_pos_ms()
        
        # 현재 위치보다 큰(오른쪽에 있는) 첫 번째 시작점 찾기 (약간의 오차 무시 위해 50ms 추가)
        next_start = next((s for s in starts if s > current_pos + 50), None)
        
        if next_start is not None:
            self.set_position(next_start)
        else:
            # 더 이상 우측에 시작점이 없으면 가장 처음(리스트의 첫 번째) 시작점으로 루프
            self.set_position(starts[0])

    def jump_to_end(self):
        if getattr(self, 'is_multi_merge_mode', False): return
        if not self.file_path: return
        ends = [s[1] for s in self.segments]
        # 현재 활성화된 끝점이 있다면 포함
        if self.end_time > 0:
            ends.append(self.end_time)
            
        if not ends:
            if self.end_time > 0:
                self.set_position(self.end_time)
            return
            
        ends = sorted(list(set(ends)))
        current_pos = self._mpv_pos_ms()
        
        # 현재 위치보다 큰(오른쪽에 있는) 첫 번째 끝점 찾기
        next_end = next((e for e in ends if e > current_pos + 50), None)
        
        if next_end is not None:
            self.set_position(next_end)
        else:
            # 더 이상 우측에 끝점이 없으면 가장 처음 끝점으로 루프
            self.set_position(ends[0])

    def slider_pressed(self):
        self.is_slider_pressed = True
        self._was_playing_before_slider = not (self.player.pause if self.player.pause is not None else True)
        try:
            self.player.pause = True
        except:
            pass

    def slider_released(self):
        self.is_slider_pressed = False
        self.set_position(self.slider.value())
        
        if self._was_playing_before_slider:
            try:
                self.player.pause = False
            except:
                pass
            self.play_button.setIcon(self.pause_icon)
            self.play_button.setToolTip("일시정지")
        else:
            self.play_button.setIcon(self.play_icon)
            self.play_button.setToolTip("재생")

    def position_changed(self, position):
        if not self.is_slider_pressed:
            self.slider.setValue(position)
            
        # 다중 병합 미리보기 모드일 때, 영상 재생이 거의 끝나가면 다음 영상으로 전환
        if self.is_multi_merge_mode and self._mpv_dur_ms() > 0:
            if position >= self._mpv_dur_ms() - 100: # 100ms 오차 허용
                next_idx = self.multi_merge_play_idx + 1
                if next_idx < len(self.multi_merge_files):
                    self._play_queue_index(next_idx)
                else:
                    self.stop_playback() # 모두 재생 완료

        self.update_time_label()

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label()

    def update_time_label(self):
        current = self.format_time(self._mpv_pos_ms())
        total = self.format_time(self._mpv_dur_ms())
        self.time_label.setText(f"{current} / {total}")

    def format_time(self, ms):
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000) % 60
        hours = (ms // 3600000)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def _mpv_pos_ms(self):
        """Get current MPV position in milliseconds."""
        try:
            tp = self.player.time_pos
            return int(tp * 1000) if tp is not None else 0
        except:
            return 0

    def _mpv_dur_ms(self):
        """Get current MPV duration in milliseconds."""
        try:
            d = self.player.duration
            return int(d * 1000) if d is not None else 0
        except:
            return 0

    def _mpv_poll(self):
        """Timer-based polling to replace Qt media player signals."""
        if not hasattr(self, 'player') or self.player is None:
            return
        try:
            pos_ms = self._mpv_pos_ms()
            dur_ms = self._mpv_dur_ms()
            if dur_ms > 0 and self.slider.maximum() != dur_ms:
                self.duration_changed(dur_ms)
            self.position_changed(pos_ms)
            is_paused = True
            try:
                p = self.player.pause
                is_paused = p if p is not None else True
            except:
                pass
            if is_paused != self._mpv_prev_pause_state:
                self._mpv_prev_pause_state = is_paused
                self.media_state_changed(not is_paused)
        except:
            pass

    def update_segments_list(self):
        self.segments_list.clear()
        
        # 우선 현재 마킹 중인 (저장 대기) 구간 표시
        if self.start_time > 0 or self.end_time > 0:
            start_str = self.format_time(self.start_time) if self.start_time > 0 else "00:00:00"
            end_str = self.format_time(self.end_time) if self.end_time > 0 else "미지정"
            text = f"> 현재 활성화: {start_str} ~ {end_str}"
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 32))
            item.setData(Qt.ItemDataRole.UserRole, int(self.start_time))
            self.segments_list.addItem(item)
            widget = SegmentItemWidget(text, item, self)
            self.segments_list.setItemWidget(item, widget)
            
        # 저장된 전체 구간 리스트 표시
        for i, (s, e) in enumerate(self.segments):
            text = f"구간 {i+1}: {self.format_time(s)} ~ {self.format_time(e)}"
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 32))
            item.setData(Qt.ItemDataRole.UserRole, int(s))
            self.segments_list.addItem(item)
            widget = SegmentItemWidget(text, item, self)
            self.segments_list.setItemWidget(item, widget)

    def seek_to_segment(self, item):
        start_ms = item.data(Qt.ItemDataRole.UserRole)
        # Type casting to int to be safe
        try:
            start_ms = int(start_ms) if start_ms is not None else None
        except (ValueError, TypeError):
            start_ms = None
            
        # Fallback parsing directly from the item's text if UserRole failed to retrieve
        if start_ms is None:
            widget = self.segments_list.itemWidget(item)
            text = widget.label.text() if (widget and hasattr(widget, 'label')) else item.text()
            # 예: "구간 1: 00:00:10 ~ 00:00:20" 또는 "> 현재 활성화: 00:00:10 ~ 미지정"
            if ": " in text and " ~ " in text:
                try:
                    time_part = text.split(": ", 1)[1].split(" ~ ")[0]
                    parts = time_part.split(":")
                    if len(parts) == 3:
                        h, m, s = map(int, parts)
                        start_ms = (h * 3600 + m * 60 + s) * 1000
                except Exception:
                    pass
            
        if start_ms is not None and self.file_path:
            self.set_position(start_ms)
            self.slider.setValue(start_ms)
            self.statusBar().showMessage(f"구간 시작점으로 이동: {self.format_time(start_ms)}")

    def delete_selected_segment(self):
        selected_items = self.segments_list.selectedItems()
        if not selected_items: return
        self.delete_segment_by_obj(selected_items[0])

    def delete_segment_by_obj(self, item):
        row = self.segments_list.row(item)
        if row == -1: return
        widget = self.segments_list.itemWidget(item)
        text = widget.label.text() if (widget and hasattr(widget, 'label')) else item.text()
        
        if "> 현재 활성화" in text:
            # 현재 활성화된 마커 취소
            self.start_time = 0
            self.end_time = 0
            self.slider.set_current_selection(-1, -1)
            self.statusBar().showMessage("현재 임시 설정 구간이 취소/삭제 되었습니다.")
        else:
            # 저장된 구간 삭제. offset 확인 필요.
            list_idx = row
            if self.segments_list.count() > len(self.segments):
                # 활성화 마커가 맨 윗줄에 표시되는 경우
                list_idx -= 1
                
            if 0 <= list_idx < len(self.segments):
                self.segments.pop(list_idx)
                self.slider.set_segments(self.segments)
                self.statusBar().showMessage(f"구간 {list_idx+1} 항목이 삭제되었습니다.")

        self.update_segments_list()
        self.check_export_ready()

    def _refresh_merge_queue_ui(self):
        self.merge_queue_list.clear()
        for i, f in enumerate(self.multi_merge_files):
            item = QListWidgetItem()
            item.setSizeHint(QSize(0, 32))
            item.setData(Qt.ItemDataRole.UserRole, f)
            self.merge_queue_list.addItem(item)
            
            widget = MergeItemWidget(f"{i+1}. {os.path.basename(f)}", item, self)
            
            # Disable Up on the first item, Down on the last item
            if i == 0:
                widget.btn_up.setEnabled(False)
            if i == len(self.multi_merge_files) - 1:
                widget.btn_down.setEnabled(False)
                
            self.merge_queue_list.setItemWidget(item, widget)
            
            if self.multi_merge_play_idx == i:
                self.merge_queue_list.setCurrentItem(item)

    def sync_merge_queue(self, parent, start, end, destination, row):
        new_files = []
        for i in range(self.merge_queue_list.count()):
            item = self.merge_queue_list.item(i)
            file_path = item.data(Qt.ItemDataRole.UserRole)
            new_files.append(file_path)
            
        self.multi_merge_files = new_files
        
        if self.file_path in self.multi_merge_files:
            self.multi_merge_play_idx = self.multi_merge_files.index(self.file_path)
        else:
            self.multi_merge_play_idx = -1
            
        QTimer.singleShot(0, self._refresh_merge_queue_ui)

    def move_queue_item_up(self, item):
        row = self.merge_queue_list.row(item)
        if row > 0:
            self.multi_merge_files[row-1], self.multi_merge_files[row] = self.multi_merge_files[row], self.multi_merge_files[row-1]
            if self.multi_merge_play_idx == row:
                self.multi_merge_play_idx = row - 1
            elif self.multi_merge_play_idx == row - 1:
                self.multi_merge_play_idx = row
            self._refresh_merge_queue_ui()

    def move_queue_item_down(self, item):
        row = self.merge_queue_list.row(item)
        if row >= 0 and row < len(self.multi_merge_files) - 1:
            self.multi_merge_files[row], self.multi_merge_files[row+1] = self.multi_merge_files[row+1], self.multi_merge_files[row]
            if self.multi_merge_play_idx == row:
                self.multi_merge_play_idx = row + 1
            elif self.multi_merge_play_idx == row + 1:
                self.multi_merge_play_idx = row
            self._refresh_merge_queue_ui()

    def delete_queue_item_by_obj(self, item):
        row = self.merge_queue_list.row(item)
        if row >= 0:
            del self.multi_merge_files[row]
            if self.multi_merge_play_idx == row:
                self.stop_playback()
                self.multi_merge_play_idx = -1
                self.setWindowTitle("MKV Lossless Cutter - 다중 파일 병합 모드")
            elif self.multi_merge_play_idx > row:
                self.multi_merge_play_idx -= 1
            self._refresh_merge_queue_ui()
            self.check_export_ready()

    def delete_merge_queue_item(self):
        if not self.is_multi_merge_mode: return
        selected_items = self.merge_queue_list.selectedItems()
        if not selected_items: return
        item = selected_items[0]
        self.delete_queue_item_by_obj(item)
        
    def filter_by_type(self, text):
        self._updating_all_tracks = True
        
        target = text
        if text == "유형(전체)":
            target = "전체"
            
        for row in range(self.tracks_table.rowCount()):
            item = self.tracks_table.item(row, 0)
            type_item = self.tracks_table.item(row, 1)
            if item and type_item:
                if target == "전체":
                    item.setCheckState(Qt.CheckState.Checked)
                else:
                    if type_item.text() == target:
                        item.setCheckState(Qt.CheckState.Checked)
                    else:
                        item.setCheckState(Qt.CheckState.Unchecked)
                        
        self._updating_all_tracks = False
        self.update_header_checkbox_state()
        self.check_export_ready()

    def on_header_clicked(self, logicalIndex):
        if logicalIndex == 0:
            self.header_checkbox.toggle()
        elif logicalIndex == 1:
            from PySide6.QtWidgets import QMenu
            from PySide6.QtGui import QCursor
            menu = QMenu(self)
            menu.setStyleSheet("QMenu { background-color: #2b2b2b; color: white; border: 1px solid #444; } QMenu::item:selected { background-color: #555; }")
            
            act_all = menu.addAction("유형 전체 선택")
            menu.addSeparator()
            act_vid = menu.addAction("비디오만 선택")
            act_aud = menu.addAction("오디오만 선택")
            act_sub = menu.addAction("자막만 선택")
            
            action = menu.exec(QCursor.pos())
            if action == act_all:
                self.filter_by_type("전체")
            elif action == act_vid:
                self.filter_by_type("비디오")
            elif action == act_aud:
                self.filter_by_type("오디오")
            elif action == act_sub:
                self.filter_by_type("자막")

    def update_header_widgets_geometry(self, *args):
        header = self.tracks_table.horizontalHeader()
        h = header.height()
        
        if hasattr(self, 'header_checkbox'):
            x0 = header.sectionViewportPosition(0)
            w0 = header.sectionSize(0)
            self.header_checkbox.setGeometry(x0, 0, w0, h)
            self.header_checkbox.show()
            self.header_checkbox.raise_()

    def update_header_checkbox_state(self, item=None):
        if getattr(self, '_updating_all_tracks', False) or not hasattr(self, 'header_checkbox') or not self.tracks_table.rowCount(): return
        if item is not None and item.column() != 0: return
        
        all_checked = True
        for row in range(self.tracks_table.rowCount()):
            chk = self.tracks_table.item(row, 0)
            if chk and chk.checkState() != Qt.CheckState.Checked:
                all_checked = False
                break
        
        self.header_checkbox.blockSignals(True)
        self.header_checkbox.setChecked(all_checked)
        self.header_checkbox.blockSignals(False)

    def toggle_all_tracks(self, state):
        self._updating_all_tracks = True
        # state could be int (0/2) from QCheckBox, map to Qt.CheckState
        chk_state = Qt.CheckState.Checked if state == 2 else Qt.CheckState.Unchecked
        for row in range(self.tracks_table.rowCount()):
            item = self.tracks_table.item(row, 0)
            if item:
                item.setCheckState(chk_state)
        self._updating_all_tracks = False
        self.check_export_ready()

    def check_export_ready(self, item=None):
        if self.is_multi_merge_mode:
            self.export_btn.setEnabled(len(self.multi_merge_files) > 1)
            self.export_btn.setText("병합 시작")
            return
            
        if not self.file_path:
            self.export_btn.setEnabled(False)
            self.export_btn.setText("내보내기")
            return

        ready = False
        
        if len(self.segments) > 0:
            ready = True
            if len(self.segments) > 1:
                self.merge_checkbox.setEnabled(True)
            else:
                self.merge_checkbox.setEnabled(False)
                self.merge_checkbox.setChecked(False)
        else:
            self.merge_checkbox.setEnabled(False)
            self.merge_checkbox.setChecked(False)
            
            # 구간 자르기가 없을 경우, 트랙 선택창 변화(일부 해제) 감지
            all_checked = True
            any_checked = False
            for row in range(self.tracks_table.rowCount()):
                chk_item = self.tracks_table.item(row, 0)
                if chk_item:
                    is_checked = (chk_item.checkState() == Qt.CheckState.Checked)
                    if not is_checked:
                        all_checked = False
                    else:
                        any_checked = True
            
            # 모두 선택된 상태가 아니고(변경점 있음) 최소 하나라도 선택(추출)되었다면
            if not all_checked and any_checked:
                ready = True

        self.export_btn.setEnabled(ready)
        self.export_btn.setText("내보내기")

    def set_start_mark(self):
        if getattr(self, 'is_multi_merge_mode', False): return
        self.start_time = self._mpv_pos_ms()
        self.end_time = 0 # Reset end time for a new segment
        self.update_segments_list()
        self.slider.set_current_selection(self.start_time, self.end_time)
        self.check_export_ready()
        self.statusBar().showMessage(f"시작 지점 설정됨: {self.format_time(self.start_time)}")

    def set_end_mark(self):
        if getattr(self, 'is_multi_merge_mode', False): return
        current_pos = self._mpv_pos_ms()
        if current_pos <= self.start_time:
             QMessageBox.warning(self, "경고", "끝점은 시작점보다 뒤에 있어야 합니다.")
             return
        
        self.end_time = current_pos
        self.update_segments_list()
        
        # Save the segment
        self.segments.append((self.start_time, self.end_time))
        self.slider.set_segments(self.segments)
        self.slider.set_current_selection(-1, -1) # Clear current selection visual after saving
        
        # Reset current selection state so next 'start' can be made cleanly
        self.start_time = 0
        self.end_time = 0
        self.update_segments_list()
        
        self.check_export_ready()
        self.statusBar().showMessage(f"구간 임시 저장됨: {self.format_time(self.segments[-1][0])} ~ {self.format_time(self.segments[-1][1])}")
    def clear_segments(self):
        if getattr(self, 'is_multi_merge_mode', False): return
        self.segments = []
        self.start_time = 0
        self.end_time = 0
        self.slider.set_segments(self.segments)
        self.slider.set_current_selection(-1, -1)
        self.update_segments_list()
        self.check_export_ready()
        self.statusBar().showMessage("전체 자르기 구간이 초기화되었습니다.")

    def inverse_segments(self):
        if getattr(self, 'is_multi_merge_mode', False): return
        if not self.file_path: return
        total_duration = self._mpv_dur_ms()
        if total_duration <= 0: return

        if not self.segments:
            # 선택 영역이 없으면 전체를 선택
            self.segments = [(0, total_duration)]
        else:
            # 겹치는 구간 병합 후 역순 구간 계산
            sorted_segs = sorted(self.segments, key=lambda x: x[0])
            merged = []
            for s in sorted_segs:
                if not merged:
                    merged.append(s)
                else:
                    last = merged[-1]
                    if s[0] <= last[1]:
                        merged[-1] = (last[0], max(last[1], s[1]))
                    else:
                        merged.append(s)
            
            new_segments = []
            curr_time = 0
            for s, e in merged:
                if s > curr_time:
                    new_segments.append((curr_time, s))
                curr_time = max(curr_time, e)
            
            if curr_time < total_duration:
                new_segments.append((curr_time, total_duration))
                
            self.segments = new_segments
            
        self.slider.set_segments(self.segments)
        self.update_segments_list()
        self.check_export_ready()
        self.statusBar().showMessage("선택 영역이 반전되었습니다.")


    def load_tracks_to_table(self, file_path):
        self.tracks_table.setRowCount(0)
        tracks = video_cutter.get_media_tracks(file_path)
        self.tracks_table.setRowCount(len(tracks))
        
        for row, track in enumerate(tracks):
            # 0: 선택 (체크박스)
            chk_item = QTableWidgetItem()
            chk_item.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            chk_item.setCheckState(Qt.CheckState.Checked)
            self.tracks_table.setItem(row, 0, chk_item)
            
            # 1: 유형
            type_str = track.get('type', '')
            lbl = "비디오" if type_str == "video" else "오디오" if type_str == "audio" else "자막" if type_str == "subtitle" else type_str
            self.tracks_table.setItem(row, 1, QTableWidgetItem(lbl))
            
            # 2: 코덱
            self.tracks_table.setItem(row, 2, QTableWidgetItem(str(track.get('codec', ''))))
            
            # 3: 항목 복사
            self.tracks_table.setItem(row, 3, QTableWidgetItem("예"))
            
            # 4: 언어
            self.tracks_table.setItem(row, 4, QTableWidgetItem(str(track.get('language', 'und'))))
            
            # 5: 이름
            self.tracks_table.setItem(row, 5, QTableWidgetItem(str(track.get('title', ''))))
            
            # 6: ID
            track_id = track.get('id', '')
            id_item = QTableWidgetItem(str(track_id))
            id_item.setData(Qt.ItemDataRole.UserRole, track_id)
            self.tracks_table.setItem(row, 6, id_item)
            
            # 7: 기본 트랙
            is_default = "예" if track.get('default') else "아니오"
            self.tracks_table.setItem(row, 7, QTableWidgetItem(is_default))
            
            # 8: Forced display
            is_forced = "예" if track.get('forced') else "아니오"
            self.tracks_table.setItem(row, 8, QTableWidgetItem(is_forced))

    def export_video(self):
        if self.is_multi_merge_mode and len(self.multi_merge_files) > 1:
            extensions = {os.path.splitext(f)[1].lower() for f in self.multi_merge_files}
            if len(extensions) > 1:
                msg_box = QMessageBox(self)
                msg_box.setIcon(QMessageBox.Icon.Warning)
                msg_box.setWindowTitle("경고: 확장자 불일치")
                msg_box.setText("병합하려는 파일들의 확장자가 서로 다릅니다.\n이 경우 병합된 영상이 재생되지 않거나 파일이 손상될 수 있습니다.\n\n강제로 병합을 진행하시겠습니까?")
                
                btn_yes = msg_box.addButton("강제 병합", QMessageBox.ButtonRole.YesRole)
                btn_cancel = msg_box.addButton("병합 취소", QMessageBox.ButtonRole.RejectRole)
                msg_box.setDefaultButton(btn_cancel)
                
                msg_box.exec()
                if msg_box.clickedButton() == btn_cancel:
                    return

            first_file = self.multi_merge_files[0]
            dir_name = os.path.dirname(first_file)
            base_name, ext = os.path.splitext(os.path.basename(first_file))
            ext = ext.lower() if ext else ".mkv"
            default_output = os.path.join(dir_name, f"{base_name}_merged{ext}")
            
            desc = "Audio Files" if ext in ['.m4a', '.mp3', '.mka', '.aac', '.flac', '.wav', '.ogg'] else "Subtitle Files" if ext in ['.srt', '.mks', '.ass', '.vtt'] else "Video Files"
            output_path, _ = QFileDialog.getSaveFileName(self, "병합 파일 저장", default_output, f"{desc} (*{ext});;All Files (*)")
            if output_path:
                cmd, lst_file = video_cutter.build_merge_cmd(self.multi_merge_files, output_path)
                if not cmd:
                    QMessageBox.critical(self, "실패", lst_file)
                    return
                # Multi-merge specific progress
                tasks = [{'cmd': cmd, 'desc': "다중 파일 병합 중...", 'duration_ms': 0, 'cleanup_file': lst_file, 'output': output_path}]
                self.start_export_worker(tasks, [output_path])
            return
            
        has_segments = len(self.segments) > 0
        has_track_changes = False
        selected_track_ids = []
        selected_track_types = []
        selected_track_codecs = []
        any_checked = False
        
        if self.file_path:
            for row in range(self.tracks_table.rowCount()):
                chk_item = self.tracks_table.item(row, 0)
                id_item = self.tracks_table.item(row, 6)
                type_item = self.tracks_table.item(row, 1)
                codec_item = self.tracks_table.item(row, 2)
                
                if chk_item and id_item:
                    is_checked = (chk_item.checkState() == Qt.CheckState.Checked)
                    if not is_checked: has_track_changes = True
                    if is_checked:
                        any_checked = True
                        selected_track_ids.append(id_item.data(Qt.ItemDataRole.UserRole))
                        if type_item: selected_track_types.append(type_item.text())
                        if codec_item: selected_track_codecs.append(codec_item.text().lower())

        if not self.file_path or (not has_segments and not (has_track_changes and any_checked)):
            return

        dir_name = os.path.dirname(self.file_path)
        base_name, original_ext = os.path.splitext(os.path.basename(self.file_path))
        original_ext = original_ext.lower() if original_ext else ".mkv"
        
        ext = original_ext
        if "비디오" not in selected_track_types and len(selected_track_types) > 0:
            if all(t == "자막" for t in selected_track_types):
                if len(selected_track_types) == 1 and ("srt" in selected_track_codecs[0] or "subrip" in selected_track_codecs[0]):
                    ext = ".srt"
                else:
                    ext = ".mks"
            elif all(t == "오디오" for t in selected_track_types):
                if len(selected_track_types) == 1:
                    codec = selected_track_codecs[0]
                    if codec == "aac":
                        ext = ".m4a"
                    elif codec == "mp3":
                        ext = ".mp3"
                    else:
                        ext = ".mka"
                else:
                    ext = ".mka"
            else:
                ext = ".mka"
        
        if not has_segments:
            default_output = os.path.join(dir_name, f"{base_name}_extracted{ext}")
        else:
            default_output = os.path.join(dir_name, f"{base_name}_cut{ext}")

        desc = "Audio Files" if ext in ['.m4a', '.mp3', '.mka', '.aac', '.flac', '.wav', '.ogg'] else "Subtitle Files" if ext in ['.srt', '.mks', '.ass', '.vtt'] else "Video Files"
        output_path, _ = QFileDialog.getSaveFileName(self, "저장할 파일 선택", default_output, f"{desc} (*{ext});;All Files (*)")
        
        if output_path:
            output_dir = os.path.dirname(output_path)
            output_base, output_ext = os.path.splitext(os.path.basename(output_path))
            
            process_segments = self.segments if has_segments else [(0, self._mpv_dur_ms())]
            total = len(process_segments)
            do_merge = self.merge_checkbox.isChecked() and total > 1
            
            tasks = []
            generated_files = []
            
            for i, (start_idx, end_idx) in enumerate(process_segments):
                duration_ms = max(0, end_idx - start_idx)
                
                if do_merge:
                    current_output = os.path.join(output_dir, f"{output_base}_temp_part{i+1}{output_ext}")
                elif total > 1:
                    current_output = os.path.join(output_dir, f"{output_base}_{i+1}{output_ext}")
                else:
                    current_output = output_path
                    
                generated_files.append(current_output)
                cmd = video_cutter.build_cut_cmd(self.file_path, start_idx, end_idx, current_output, selected_track_ids)
                tasks.append({
                    'cmd': cmd,
                    'desc': f"구간 내보내기 중... ({i+1}/{total})",
                    'duration_ms': duration_ms,
                    'output': current_output
                })
                
            if do_merge:
                merged_output_path = output_path
                merge_cmd, lst_file = video_cutter.build_merge_cmd(generated_files, merged_output_path)
                tasks.append({
                    'cmd': merge_cmd,
                    'desc': "조각 파일 묶음 병합 중...",
                    'duration_ms': 100, # Small padding for merge time
                    'cleanup_file': lst_file,
                    'output': merged_output_path,
                    'generated_temp_files': generated_files # We need to delete these after
                })
            
            self.start_export_worker(tasks, generated_files if do_merge else [])

    def start_export_worker(self, tasks, temp_files_created):
        self.play_button.setEnabled(False)
        self.export_btn.setEnabled(False)
        self.temp_files_created_by_worker = temp_files_created # to clean up if cancelled/finished
        
        # Create Progress Dialog
        self.progress_dialog = QProgressDialog("작업을 준비 중...", "취소", 0, 100, self)
        self.progress_dialog.setWindowTitle("내보내기 진행 상황")
        self.progress_dialog.setWindowModality(Qt.WindowModality.WindowModal)
        self.progress_dialog.setMinimumDuration(0)
        self.progress_dialog.setValue(0)
        
        self.export_worker = ExportWorker(tasks, self)
        self.export_worker.progress.connect(self.progress_dialog.setValue)
        self.export_worker.log.connect(self.progress_dialog.setLabelText)
        self.export_worker.finished.connect(self.on_export_finished)
        self.progress_dialog.canceled.connect(self.export_worker.cancel)
        
        self.export_worker.start()

    def on_export_finished(self, success, outputs, msg):
        self.play_button.setEnabled(True)
        self.progress_dialog.close()
        
        # Clean up intermediate files from merge step
        if hasattr(self, 'temp_files_created_by_worker'):
            if success:
                # Need to manually clean chunks if everything succeeded but it was a merge
                if any('temp_part' in f for f in self.temp_files_created_by_worker):
                    for f in self.temp_files_created_by_worker:
                        if os.path.exists(f): 
                            try: os.remove(f)
                            except: pass
            else:
                # If cancelled, remove all partial files
                for f in outputs:
                    if os.path.exists(f): 
                        try: os.remove(f)
                        except: pass
                for f in self.temp_files_created_by_worker:
                    if os.path.exists(f): 
                        try: os.remove(f)
                        except: pass
        
        self.check_export_ready() # Sync the button state properly!
        
        if success:
            self.statusBar().showMessage("작업이 완료되었습니다.")
            QMessageBox.information(self, "완료", msg)
        else:
            self.statusBar().showMessage("작업 취소 또는 실패")
            QMessageBox.critical(self, "실패", msg)

    def handle_errors(self):
        self.play_button.setEnabled(False)
        self.time_label.setText("오류 발생")

    def closeEvent(self, event):
        if hasattr(self, '_mpv_timer'):
            self._mpv_timer.stop()
            
        if hasattr(self, 'player'):
            try:
                self.player.terminate()
            except:
                pass
            
        if hasattr(self, 'thumbnail_thread'):
            self.thumbnail_thread.stop()
            
        QApplication.processEvents() # Let Qt internal threads process the stop
        
        if hasattr(self, 'export_worker') and self.export_worker.isRunning():
            self.export_worker.cancel()
        super().closeEvent(event)
