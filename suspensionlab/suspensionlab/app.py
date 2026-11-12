"""Точка входа приложения.

Запуск: ``python -m suspensionlab`` или ``python app.py``.

Приложение полностью офлайн: ни одного сетевого запроса, все ресурсы
(темы, локализация, шаблоны) лежат рядом с кодом.
"""

from __future__ import annotations

import logging
import sys
import traceback

from PySide6.QtCore import QSettings, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMessageBox

from . import APP_ID, APP_NAME, ORG_ID, __version__
from .config import log_file_path, settings_path
from .i18n import tr
from .logging_setup import setup_logging

LOG = logging.getLogger(__name__)


def make_app_icon() -> QIcon:
    """Рисует иконку приложения (собственный векторный знак)."""
    pixmap = QPixmap(64, 64)
    pixmap.fill(Qt.GlobalColor.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
    painter.setPen(QPen(QColor("#2f6fd0"), 5, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
    painter.drawLine(12, 46, 52, 46)
    painter.drawLine(20, 46, 32, 24)
    painter.drawLine(44, 46, 32, 24)
    painter.setBrush(QColor("#e6ebf1"))
    painter.setPen(QPen(QColor("#e6ebf1"), 2))
    painter.drawEllipse(32 - 11, 24 - 11, 22, 22)
    painter.setBrush(QColor("#2f6fd0"))
    painter.setPen(Qt.PenStyle.NoPen)
    painter.drawEllipse(32 - 4, 24 - 4, 8, 8)
    painter.end()
    return QIcon(pixmap)


def create_application(argv: list[str] | None = None) -> QApplication:
    """Создаёт QApplication с настройками HiDPI и системным шрифтом."""
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(argv if argv is not None else sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationDisplayName(APP_NAME)
    app.setOrganizationName(ORG_ID)
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(APP_ID)
    app.setStyle("Fusion")

    font = QFont()
    font.setPointSize(10)
    app.setFont(font)
    app.setWindowIcon(make_app_icon())
    return app


def install_exception_hook() -> None:
    """Перехватывает необработанные исключения: журнал + понятное сообщение."""

    def hook(exc_type, exc_value, exc_tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_tb)
            return
        LOG.critical(
            "Необработанное исключение: %s",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        app = QApplication.instance()
        if app is not None:
            box = QMessageBox()
            box.setIcon(QMessageBox.Icon.Critical)
            box.setWindowTitle(tr("error.internal.title"))
            box.setText(tr("error.internal.text", path=str(log_file_path())))
            box.setStandardButtons(QMessageBox.StandardButton.Ok)
            box.exec()

    sys.excepthook = hook


def main(argv: list[str] | None = None) -> int:
    """Запускает приложение и возвращает код завершения."""
    setup_logging()
    install_exception_hook()
    LOG.info("Запуск %s %s", APP_NAME, __version__)

    app = create_application(argv)
    # импорт окна — после создания QApplication: модули интерфейса
    # обращаются к шрифтовой базе при инициализации
    from .ui.main_window import MainWindow

    settings = QSettings(str(settings_path()), QSettings.Format.IniFormat)
    window = MainWindow(settings=settings)
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
