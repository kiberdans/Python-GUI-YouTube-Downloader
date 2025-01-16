import yt_dlp
import time
import sys
import requests
from io import BytesIO
from PIL import Image
from PyQt5.QtWidgets import (
    QApplication, QWidget, QVBoxLayout, QLabel, QLineEdit, QPushButton, QMessageBox, QTextEdit, QHBoxLayout,
    QSizePolicy, QScrollArea, QProgressBar)
from PyQt5.QtCore import Qt, QThread, pyqtSignal
from PyQt5.QtGui import QPixmap, QImage
import qtawesome as qta


class ClearableLineEdit(QLineEdit):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # Создаем кнопку очистки
        self.clear_button = QPushButton(self)
        self.clear_button.setIcon(qta.icon('fa.times', color='white'))
        self.clear_button.setCursor(Qt.PointingHandCursor)
        self.clear_button.setStyleSheet("QPushButton { border: none; padding: 0px; background: transparent; }")
        self.clear_button.clicked.connect(self.clear)
        self.clear_button.hide()

        # Обновляем позицию кнопки при изменении размера
        self.textChanged.connect(self.update_clear_button)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self.update_clear_button_position()

    def update_clear_button_position(self):
        size = self.clear_button.sizeHint()
        frame_width = self.style().pixelMetric(self.style().PM_DefaultFrameWidth)
        self.clear_button.move(
            self.rect().right() - frame_width - size.width(),
            (self.rect().bottom() + 1 - size.height()) // 2
        )

    def update_clear_button(self, text):
        self.clear_button.setVisible(bool(text))


class FetchPreviewThread(QThread):
    preview_ready = pyqtSignal(QPixmap, str)  # Добавлен сигнал для названия видео
    error = pyqtSignal(str)

    def __init__(self, link):
        super().__init__()
        self.link = link

    def run(self):
        try:
            ydl_opts = {'skip_download': True, 'quiet': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(self.link, download=False)
                thumbnail_url = info.get('thumbnail', '')
                title = info.get('title', 'Название не найдено')  # Получение названия видео

                if thumbnail_url:
                    response = requests.get(thumbnail_url)
                    image = Image.open(BytesIO(response.content))
                    image = image.convert("RGBA")
                    data = image.tobytes("raw", "RGBA")

                    qim = QImage(data, image.width, image.height, QImage.Format_ARGB32)
                    pixmap = QPixmap.fromImage(qim)
                    self.preview_ready.emit(pixmap, title)  # Передаем превью и название
                else:
                    self.error.emit("Не удалось найти превью.")
        except Exception as e:
            self.error.emit(f"Не удалось загрузить превью: {e}")

class DownloadThread(QThread):
    progress = pyqtSignal(str)
    progress_bar_update = pyqtSignal(int, str, str)
    finished = pyqtSignal()

    def __init__(self, link):
        super().__init__()
        self.link = link

    def run(self):
        ydl_opts = {
            'format': 'bestvideo+bestaudio/best',
            'outtmpl': '%(title)s.%(ext)s',
            'merge_output_format': 'mp4',
            'progress_hooks': [self.hook],
        }
        try:
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                ydl.download([self.link])
        except Exception as e:
            self.progress.emit(f"Ошибка: {e}")
        finally:
            self.finished.emit()

    def hook(self, d):
        if d['status'] == 'downloading':
            progress = d.get('_percent_str', '0.0%').strip()
            speed_bytes = d.get('speed', 0)
            eta = d.get('eta', 0)

            # Конвертируем скорость в Mb/s
            speed_mb = speed_bytes / 1024 / 1024 if speed_bytes else 0
            speed_str = f"{speed_mb:.1f} Mb/s"

            percent = float(progress.strip('%'))
            eta_formatted = self.format_time(eta)

            self.progress.emit(f"{progress}, {speed_str}, {eta_formatted}")
            self.progress_bar_update.emit(int(percent), speed_str, eta_formatted)
        elif d['status'] == 'finished':
            self.progress.emit("Загрузка завершена")

    @staticmethod
    def format_time(seconds):
        if not seconds:
            return "0 сек"

        if seconds < 60:
            return f"{seconds} сек"
        else:
            minutes = seconds // 60
            remaining_seconds = seconds % 60
            if remaining_seconds == 0:
                return f"{minutes} мин"
            else:
                return f"{minutes} мин {remaining_seconds} сек"


class YouTubeDownloader(QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("YouTube Downloader")
        self.setFixedSize(400, 600)
        self.setStyleSheet("background-color: #2e2e2e; color: white; font-family: Arial; font-size: 14px;")

        self.download_thread = None
        self.preview_thread = None

        layout = QVBoxLayout()

        self.label = QLabel("Введите ссылку на видео:")
        self.label.setStyleSheet("font-size: 16px; color: #cccccc;")
        layout.addWidget(self.label)

        self.url_input = ClearableLineEdit()
        self.url_input.setPlaceholderText("Введите URL видео")
        self.url_input.setStyleSheet("background-color: #444444; color: white; padding: 5px; padding-right: 25px;")
        self.url_input.textChanged.connect(self.on_url_changed)
        layout.addWidget(self.url_input)

        self.preview_label = QLabel()
        self.preview_label.setAlignment(Qt.AlignCenter)
        self.preview_label.setStyleSheet(
            "background-color: #444444; color: #888888; padding: 10px; border: 1px solid #555555;")
        self.preview_label.setFixedHeight(200)
        layout.addWidget(self.preview_label)  # Превью ниже названия

        self.title_label = QLabel()  # Элемент для отображения названия
        self.title_label.setAlignment(Qt.AlignCenter)
        self.title_label.setStyleSheet("font-size: 14px; color: #cccccc; padding: 5px;")
        layout.addWidget(self.title_label)  # Название выше превью

        self.loading_icon = QLabel()
        self.loading_icon.setAlignment(Qt.AlignCenter)
        self.loading_icon.setVisible(False)
        loading_spinner = qta.icon('fa.spinner', color='white', animation=qta.Spin(self.loading_icon))
        self.loading_icon.setPixmap(loading_spinner.pixmap(24, 24))
        layout.addWidget(self.loading_icon)

        self.info_layout = QHBoxLayout()

        self.percent_label = QLabel("")
        self.percent_label.setStyleSheet("color: white;")
        self.info_layout.addWidget(self.percent_label)

        self.speed_label = QLabel("")
        self.speed_label.setStyleSheet("color: white;")
        self.info_layout.addWidget(self.speed_label)

        self.eta_label = QLabel("")
        self.eta_label.setStyleSheet("color: white;")
        self.info_layout.addWidget(self.eta_label)

        layout.addLayout(self.info_layout)

        self.progress_bar = QProgressBar()
        self.progress_bar.setStyleSheet(
            "QProgressBar { background-color: #444; color: white; border: 1px solid #555; } QProgressBar::chunk { background-color: #4CAF50; }")
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(False)
        layout.addWidget(self.progress_bar)

        button_layout = QHBoxLayout()

        self.paste_button = QPushButton("Вставить")
        self.paste_button.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 10px; border: none; border-radius: 5px; font-size: 14px;")
        self.paste_button.clicked.connect(self.paste_from_clipboard)
        button_layout.addWidget(self.paste_button)

        self.download_button = QPushButton("Скачать")
        self.download_button.setStyleSheet(
            "background-color: #4CAF50; color: white; padding: 10px; border: none; border-radius: 5px; font-size: 14px;")
        self.download_button.clicked.connect(self.start_download)
        button_layout.addWidget(self.download_button)

        layout.addLayout(button_layout)

        self.console_widget = QTextEdit()
        self.console_widget.setReadOnly(True)
        self.console_widget.setStyleSheet(
            "background-color: #1e1e1e; color: #cccccc; padding: 5px; font-family: monospace;")
        layout.addWidget(self.console_widget)

        self.progress_bar.setVisible(False)
        self.setLayout(layout)

    def paste_from_clipboard(self):
        clipboard = QApplication.clipboard()
        self.url_input.setText(clipboard.text())

    def on_url_changed(self):
        link = self.url_input.text()
        if self.validate_url(link):
            if self.preview_thread and self.preview_thread.isRunning():
                self.preview_thread.terminate()

            self.loading_icon.setVisible(True)
            self.preview_label.clear()
            self.title_label.clear()  # Очищаем название

            self.preview_thread = FetchPreviewThread(link)
            self.preview_thread.preview_ready.connect(self.update_preview)
            self.preview_thread.error.connect(self.log_message)
            self.preview_thread.start()

    def update_preview(self, pixmap, title):
        self.loading_icon.setVisible(False)
        self.preview_label.setPixmap(pixmap.scaled(300, 200, Qt.KeepAspectRatio))
        self.title_label.setText(title)  # Отображаем название видео

    def log_message(self, message):
        self.console_widget.append(message)

    def start_download(self):
        link = self.url_input.text()
        if self.validate_url(link):
            self.console_widget.clear()
            self.progress_bar.setVisible(True)
            self.percent_label.setText("%: 0")
            self.speed_label.setText("0 Mb/s")
            self.eta_label.setText("0 сек")
            self.progress_bar.setValue(0)

            self.download_thread = DownloadThread(link)
            self.download_thread.progress.connect(self.log_message)
            self.download_thread.progress_bar_update.connect(self.update_progress_bar)
            self.download_thread.finished.connect(self.download_finished)
            self.download_thread.start()
        else:
            QMessageBox.warning(self, "Ошибка", "Введите корректную ссылку на видео!")

    def update_progress_bar(self, percent, speed, eta):
        self.progress_bar.setValue(percent)
        self.percent_label.setText(f"%: {percent}")
        self.speed_label.setText(f"Скорость: {speed}")
        self.eta_label.setText(f"Осталось: {eta}")

    def download_finished(self):
        QMessageBox.information(self, "Загрузка завершена", "Видео успешно скачано!")
        self.progress_bar.setVisible(False)
        self.console_widget.append("Скачивание завершено.")
        self.download_thread = None

    @staticmethod
    def validate_url(link):
        return link.startswith("http://") or link.startswith("https://")


if __name__ == "__main__":
    app = QApplication(sys.argv)
    downloader = YouTubeDownloader()
    downloader.show()
    sys.exit(app.exec_())