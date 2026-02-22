import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QWidget, QVBoxLayout, 
                               QHBoxLayout, QPushButton, QSlider, QLabel, QFileDialog, QMessageBox, QStyle, QStyleOptionSlider, QListWidget, QAbstractItemView)
from PySide6.QtMultimedia import QMediaPlayer, QAudioOutput
from PySide6.QtMultimediaWidgets import QVideoWidget
from PySide6.QtCore import Qt, QUrl, QTime, QPoint, Signal, QObject, QEvent, QSize

import video_cutter

from PySide6.QtGui import QPainter, QColor, QPolygon, QPen, QBrush, QIcon

class ClickableVideoWidget(QVideoWidget):
    """
    A custom QVideoWidget that emits a clicked signal on mouse press.
    """
    clicked = Signal()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.clicked.emit()
            event.accept()
        super().mousePressEvent(event)

class SeekSlider(QSlider):
    """
    A custom QSlider that allows clicking to seek to a specific position.
    Also visualizes multiple selected cut ranges with distinct markers.
    """
    def __init__(self, orientation, parent=None):
        super().__init__(orientation, parent)
        self.segments = [] # List of tuples (start, end)
        self.current_start = -1
        self.current_end = -1

    def set_current_selection(self, start, end):
        self.current_start = start
        self.current_end = end
        self.update()

    def set_segments(self, segments):
        self.segments = segments
        self.update()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            val = self.pixelPosToRangeValue(event.position().x())
            self.setValue(val)
            self.sliderMoved.emit(val)  # Emit signal to update playback
            event.accept()
        super().mousePressEvent(event)

    def paintEvent(self, event):
        super().paintEvent(event)
        
        painter = QPainter(self)
        
        # Use style option to get groove geometry
        opt = QStyleOptionSlider()
        self.initStyleOption(opt)
        gr = self.style().subControlRect(QStyle.ComplexControl.CC_Slider, opt, QStyle.SubControl.SC_SliderGroove, self)
        
        val_range = self.maximum() - self.minimum()
        if val_range <= 0:
            return

        slider_length = gr.width()
        slider_min_pos = gr.x()
        rect_height = gr.height()
        rect_y = gr.y()

        # Helper to calculate pixel position
        def get_px(val):
            if val < 0: return -1
            ratio = (val - self.minimum()) / val_range
            return slider_min_pos + int(ratio * slider_length)

        # Draw Saved Segments (Gold)
        for start, end in self.segments:
            s_px = get_px(start)
            e_px = get_px(end)
            if s_px >= 0 and e_px > s_px:
                painter.setBrush(QColor(255, 215, 0, 180)) # Gold for saved segments
                painter.setPen(Qt.PenStyle.NoPen)
                painter.drawRect(s_px, rect_y, e_px - s_px, rect_height)

        # Draw Current Selection (Blue)
        start_px = get_px(self.current_start)
        end_px = get_px(self.current_end)

        if start_px >= 0 and end_px > start_px:
            painter.setBrush(QColor(0, 120, 215, 150)) # Active blue
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(start_px, rect_y, end_px - start_px, rect_height)

        # Draw Markers for Current Selection
        # Start Marker (Green Triangle)
        if start_px >= 0:
            painter.setPen(QPen(QColor(0, 200, 0), 2))
            painter.drawLine(start_px, rect_y - 2, start_px, rect_y + rect_height + 2)
            
            painter.setBrush(QBrush(QColor(0, 200, 0)))
            painter.setPen(Qt.PenStyle.NoPen)
            triangle = QPolygon([
                QPoint(start_px, rect_y - 4),
                QPoint(start_px + 6, rect_y - 4),
                QPoint(start_px, rect_y + 2)
            ])
            painter.drawPolygon(triangle)

        # End Marker (Red Triangle)
        if end_px >= 0:
            painter.setPen(QPen(QColor(200, 0, 0), 2))
            painter.drawLine(end_px, rect_y - 2, end_px, rect_y + rect_height + 2)
            
            painter.setBrush(QBrush(QColor(200, 0, 0)))
            painter.setPen(Qt.PenStyle.NoPen)
            triangle = QPolygon([
                QPoint(end_px, rect_y - 4),
                QPoint(end_px - 6, rect_y - 4),
                QPoint(end_px, rect_y + 2)
            ])
            painter.drawPolygon(triangle)

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

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("MKV Lossless Cutter (한글 지원)")
        self.resize(1000, 800) # Increased height for list

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
            QSlider::groove:horizontal {
                border: 1px solid #3d3d3d;
                height: 8px;
                background: #1e1e1e;
                margin: 2px 0;
                border-radius: 4px;
            }
            QSlider::handle:horizontal {
                background: #0078d7;
                border: 1px solid #0078d7;
                width: 16px;
                height: 16px;
                margin: -4px 0;
                border-radius: 8px;
            }
            QSlider::handle:horizontal:hover {
                background: #1e90ff;
            }
        """)

        # Media Player Setup
        self.media_player = QMediaPlayer()
        self.audio_output = QAudioOutput()
        self.media_player.setAudioOutput(self.audio_output)
        
        # UI Components
        self.central_widget = QWidget()
        self.setCentralWidget(self.central_widget)
        self.layout = QVBoxLayout(self.central_widget)

        # Video Widget
        self.video_widget = ClickableVideoWidget(self.central_widget)
        self.video_widget.clicked.connect(self.toggle_play)
        self.layout.addWidget(self.video_widget)
        self.media_player.setVideoOutput(self.video_widget)

        # Timeline Slider
        self.slider = SeekSlider(Qt.Orientation.Horizontal)
        self.slider.setRange(0, 0)
        self.slider.sliderMoved.connect(self.set_position)
        self.slider.sliderPressed.connect(self.slider_pressed)
        self.slider.sliderReleased.connect(self.slider_released)
        self.layout.addWidget(self.slider)

        # Time Labels and Controls Layout
        self.controls_layout = QHBoxLayout()
        self.layout.addLayout(self.controls_layout)

        # Frame Pre Button (1 Frame Back)
        self.frame_pre_icon = QIcon("assets/frame_pre.png")
        self.frame_pre_button = QPushButton()
        self.frame_pre_button.setIcon(self.frame_pre_icon)
        self.frame_pre_button.setIconSize(QSize(42, 36))
        self.frame_pre_button.setFixedSize(42, 36)
        self.frame_pre_button.setStyleSheet("background-color: transparent; border: none;")
        self.frame_pre_button.setToolTip("1프레임 뒤로")
        self.frame_pre_button.clicked.connect(self.step_backward)
        self.frame_pre_button.setEnabled(False)
        self.controls_layout.addWidget(self.frame_pre_button)

        # Pre Button (5s Back)
        self.pre_icon = QIcon("assets/pre.png")
        self.pre_button = QPushButton()
        self.pre_button.setIcon(self.pre_icon)
        self.pre_button.setIconSize(QSize(42, 36))
        self.pre_button.setFixedSize(42, 36)
        self.pre_button.setStyleSheet("background-color: transparent; border: none;")
        self.pre_button.setToolTip("5초 뒤로")
        self.pre_button.clicked.connect(self.skip_backward)
        self.pre_button.setEnabled(False)
        self.controls_layout.addWidget(self.pre_button)

        # Play/Pause Button
        self.play_icon = QIcon("assets/play.png")
        self.pause_icon = QIcon("assets/pause.png")
        self.play_button = QPushButton()
        self.play_button.setIcon(self.play_icon)
        self.play_button.setIconSize(QSize(42, 36))
        self.play_button.setFixedSize(42, 36)
        self.play_button.setStyleSheet("background-color: transparent; border: none;")
        self.play_button.setToolTip("재생")
        self.play_button.clicked.connect(self.toggle_play)
        self.play_button.setEnabled(False) # 비활성화 기본값
        self.controls_layout.addWidget(self.play_button)

        # Stop Button
        self.stop_icon = QIcon("assets/stop.png")
        self.stop_button = QPushButton()
        self.stop_button.setIcon(self.stop_icon)
        self.stop_button.setIconSize(QSize(42, 36))
        self.stop_button.setFixedSize(42, 36)
        self.stop_button.setStyleSheet("background-color: transparent; border: none;")
        self.stop_button.setToolTip("정지 (초기화)")
        self.stop_button.clicked.connect(self.stop_and_clear)
        self.stop_button.setEnabled(False) # 비활성화 기본값
        self.controls_layout.addWidget(self.stop_button)

        # Next Button
        self.next_icon = QIcon("assets/next.png")
        self.next_button = QPushButton()
        self.next_button.setIcon(self.next_icon)
        self.next_button.setIconSize(QSize(42, 36))
        self.next_button.setFixedSize(42, 36)
        self.next_button.setStyleSheet("background-color: transparent; border: none;")
        self.next_button.setToolTip("5초 앞으로")
        self.next_button.clicked.connect(self.skip_forward)
        self.next_button.setEnabled(False)
        self.controls_layout.addWidget(self.next_button)

        # Frame Next Button
        self.frame_next_icon = QIcon("assets/frame_next.png")
        self.frame_next_button = QPushButton()
        self.frame_next_button.setIcon(self.frame_next_icon)
        self.frame_next_button.setIconSize(QSize(42, 36))
        self.frame_next_button.setFixedSize(42, 36)
        self.frame_next_button.setStyleSheet("background-color: transparent; border: none;")
        self.frame_next_button.setToolTip("1프레임 앞으로")
        self.frame_next_button.clicked.connect(self.step_forward)
        self.frame_next_button.setEnabled(False)
        self.controls_layout.addWidget(self.frame_next_button)

        # Open File Button
        self.open_icon = QIcon("assets/open.png")
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
        
        # Spacer
        self.controls_layout.addStretch()

        # Cut Controls
        self.start_time = 0
        self.end_time = 0
        self.segments = [] # List of (start, end)
        
        self.start_icon = QIcon("assets/start_point.png")
        self.set_start_btn = QPushButton()
        self.set_start_btn.setIcon(self.start_icon)
        self.set_start_btn.setIconSize(QSize(42, 36))
        self.set_start_btn.setFixedSize(42, 36)
        self.set_start_btn.setStyleSheet("background-color: transparent; border: none;")
        self.set_start_btn.setToolTip("시작점 [I]")
        self.set_start_btn.clicked.connect(self.set_start_mark)
        self.controls_layout.addWidget(self.set_start_btn)
        
        self.end_icon = QIcon("assets/end_point.png")
        self.set_end_btn = QPushButton()
        self.set_end_btn.setIcon(self.end_icon)
        self.set_end_btn.setIconSize(QSize(42, 36))
        self.set_end_btn.setFixedSize(42, 36)
        self.set_end_btn.setStyleSheet("background-color: transparent; border: none;")
        self.set_end_btn.setToolTip("끝점 [O]")
        self.set_end_btn.clicked.connect(self.set_end_mark)
        self.controls_layout.addWidget(self.set_end_btn)

        self.clear_btn = QPushButton("선택 초기화")
        self.clear_btn.clicked.connect(self.clear_segments)
        self.controls_layout.addWidget(self.clear_btn)
        
        self.cut_label = QLabel("시작: - | 끝: -")
        self.controls_layout.addWidget(self.cut_label)

        self.export_btn = QPushButton("내보내기")
        self.export_btn.clicked.connect(self.export_video)
        self.export_btn.setEnabled(False)
        self.controls_layout.addWidget(self.export_btn)

        # Signals
        self.media_player.positionChanged.connect(self.position_changed)
        self.media_player.durationChanged.connect(self.duration_changed)
        self.media_player.errorOccurred.connect(self.handle_errors)

        self.file_path = ""
        self.is_slider_pressed = False
        
        # Enable Drag and Drop (Handled by Global Filter in main.py)
        self.setAcceptDrops(True)

    def handle_dropped_file(self, file_path):
        valid_extensions = ['.mkv', '.mp4', '.avi']
        if os.path.splitext(file_path)[1].lower() in valid_extensions:
            self.load_file(file_path)
        else:
            QMessageBox.warning(self, "지원하지 않는 파일", f"비디오 파일(.mkv, .mp4, .avi)만 열 수 있습니다.\n입력 파일: {file_path}")

    def open_file(self):
        file_dialog = QFileDialog(self)
        file_dialog.setNameFilters(["Video files (*.mkv *.mp4 *.avi)"])
        if file_dialog.exec():
            files = file_dialog.selectedFiles()
            if files:
                self.load_file(files[0])

    def load_file(self, file_path):
        self.file_path = file_path
        self.media_player.setSource(QUrl.fromLocalFile(self.file_path))
        self.play_button.setEnabled(True)
        self.stop_button.setEnabled(True)
        self.pre_button.setEnabled(True)
        self.frame_pre_button.setEnabled(True)
        self.next_button.setEnabled(True)
        self.frame_next_button.setEnabled(True)
        self.play_video()
        self.setWindowTitle(f"MKV Lossless Cutter - {os.path.basename(self.file_path)}")
        
        # Reset selection
        self.start_time = 0
        self.end_time = 0
        self.segments = []
        self.slider.set_segments(self.segments)
        self.slider.set_current_selection(-1, -1)
        self.update_cut_label()
        self.check_export_ready()

    def stop_and_clear(self):
        self.media_player.stop()
        self.media_player.setSource(QUrl())
        self.file_path = None
        self.play_button.setEnabled(False)
        self.stop_button.setEnabled(False)
        self.pre_button.setEnabled(False)
        self.frame_pre_button.setEnabled(False)
        self.next_button.setEnabled(False)
        self.frame_next_button.setEnabled(False)
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
        self.update_cut_label()
        self.check_export_ready()

    def toggle_play(self):
        if not self.file_path:
            self.open_file()
            return
            
        if self.media_player.playbackState() == QMediaPlayer.PlaybackState.PlayingState:
            self.media_player.pause()
            self.play_button.setIcon(self.play_icon)
            self.play_button.setToolTip("재생")
        else:
            self.media_player.play()
            self.play_button.setIcon(self.pause_icon)
            self.play_button.setToolTip("일시정지")

    def play_video(self):
        self.media_player.play()
        self.play_button.setIcon(self.pause_icon)
        self.play_button.setToolTip("일시정지")

    def pause_video(self):
        self.media_player.pause()
        self.play_button.setIcon(self.play_icon)
        self.play_button.setToolTip("재생")

    def set_position(self, position):
        self.media_player.setPosition(position)

    def step_backward(self):
        if self.file_path:
            # 1 프레임 이동 (대략 30fps 기준 ~33ms)
            new_pos = max(0, self.media_player.position() - 33)
            self.set_position(new_pos)

    def skip_backward(self):
        if self.file_path:
            new_pos = max(0, self.media_player.position() - 5000)
            self.set_position(new_pos)

    def skip_forward(self):
        if self.file_path:
            duration = self.media_player.duration()
            if duration > 0:
                new_pos = min(duration, self.media_player.position() + 5000)
            else:
                new_pos = self.media_player.position() + 5000
            self.set_position(new_pos)

    def step_forward(self):
        if self.file_path:
            duration = self.media_player.duration()
            # 1 프레임 이동 (대략 30fps 기준 ~33ms)
            if duration > 0:
                new_pos = min(duration, self.media_player.position() + 33)
            else:
                new_pos = self.media_player.position() + 33
            self.set_position(new_pos)

    def slider_pressed(self):
        self.is_slider_pressed = True
        self.media_player.pause()

    def slider_released(self):
        self.is_slider_pressed = False
        self.set_position(self.slider.value())
        self.media_player.play()
        self.play_button.setIcon(self.pause_icon)
        self.play_button.setToolTip("일시정지")

    def position_changed(self, position):
        # Update slider only if not currently being dragged by user
        if not self.is_slider_pressed:
            self.slider.setValue(position)
        self.update_time_label()

    def duration_changed(self, duration):
        self.slider.setRange(0, duration)
        self.update_time_label()

    def update_time_label(self):
        current = self.format_time(self.media_player.position())
        total = self.format_time(self.media_player.duration())
        self.time_label.setText(f"{current} / {total}")

    def format_time(self, ms):
        seconds = (ms // 1000) % 60
        minutes = (ms // 60000) % 60
        hours = (ms // 3600000)
        return f"{hours:02}:{minutes:02}:{seconds:02}"

    def update_cut_label(self):
        start_str = self.format_time(self.start_time) if self.start_time > 0 else "00:00:00"
        end_str = self.format_time(self.end_time) if self.end_time > 0 else "-"
        self.cut_label.setText(f"시작: {start_str} | 끝: {end_str}")

    def check_export_ready(self):
        if len(self.segments) > 0 and self.file_path:
            self.export_btn.setEnabled(True)
        else:
            self.export_btn.setEnabled(False)

    def set_start_mark(self):
        self.start_time = self.media_player.position()
        self.end_time = 0 # Reset end time for a new segment
        self.update_cut_label()
        self.slider.set_current_selection(self.start_time, self.end_time)
        self.check_export_ready()

    def set_end_mark(self):
        current_pos = self.media_player.position()
        if current_pos <= self.start_time:
             QMessageBox.warning(self, "경고", "끝점은 시작점보다 뒤에 있어야 합니다.")
             return
        
        self.end_time = current_pos
        self.update_cut_label()
        
        # Save the segment
        self.segments.append((self.start_time, self.end_time))
        self.slider.set_segments(self.segments)
        self.slider.set_current_selection(-1, -1) # Clear current selection visual after saving
        
        # Reset current selection state so next 'start' can be made cleanly
        self.start_time = 0
        self.end_time = 0
        self.update_cut_label()
        
        self.check_export_ready()
    def clear_segments(self):
        self.segments = []
        self.start_time = 0
        self.end_time = 0
        self.slider.set_segments(self.segments)
        self.slider.set_current_selection(-1, -1)
        self.update_cut_label()
        self.check_export_ready()

    def export_video(self):
        if not self.file_path or not self.segments:
            return

        # Generate default output filename base
        dir_name = os.path.dirname(self.file_path)
        base_name = os.path.splitext(os.path.basename(self.file_path))[0]
        default_output = os.path.join(dir_name, f"{base_name}_cut.mkv")

        output_path, _ = QFileDialog.getSaveFileName(self, "저장할 파일 선택 (기본 이름으로 _1, _2 ... 자동 생성됨)", default_output, "MKV Files (*.mkv);;All Files (*)")
        
        if output_path:
            self.play_button.setEnabled(False)
            self.export_btn.setEnabled(False)
            
            output_dir = os.path.dirname(output_path)
            output_base, output_ext = os.path.splitext(os.path.basename(output_path))
            
            total = len(self.segments)
            success_count = 0
            fail_messages = []
            
            for i, (start_idx, end_idx) in enumerate(self.segments):
                self.export_btn.setText(f"처리 중... ({i+1}/{total})")
                QApplication.processEvents() # Force UI update
                
                # Append number if there are multiple segments
                if total > 1:
                    current_output = os.path.join(output_dir, f"{output_base}_{i+1}{output_ext}")
                else:
                    current_output = output_path

                success, message = video_cutter.cut_video(self.file_path, start_idx, end_idx, current_output)
                if success:
                    success_count += 1
                else:
                    fail_messages.append(f"구간 {i+1}: {message}")
            
            self.play_button.setEnabled(True)
            self.export_btn.setEnabled(True)
            self.export_btn.setText("내보내기")

            if success_count == total:
                QMessageBox.information(self, "성공", f"총 {total}개의 구간이 성공적으로 저장되었습니다.")
            else:
                QMessageBox.critical(self, "완료", f"{success_count}/{total}개 성공.\n실패 내역:\n" + "\n".join(fail_messages))

    def handle_errors(self):
        self.play_button.setEnabled(False)
        self.time_label.setText("오류: " + self.media_player.errorString())
