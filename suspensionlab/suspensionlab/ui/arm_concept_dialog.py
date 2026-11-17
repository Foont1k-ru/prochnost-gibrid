"""Немодальный эскиз: производная схема, не CAD-деталь и не расчёт прочности."""
from __future__ import annotations

from pathlib import Path
from typing import cast

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.arm_concept import ArmConcept, ArmStyle, make_arm_concept
from ..model.kim_format import KimFormatError, make_lower_arm_tube_prototype, write_document
from .controller import AppController


class ArmConceptCanvas(QWidget):
    """Условная проекция XY; толщина трубы/листа не является CAD-геометрией."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.concept: ArmConcept | None = None
        self.setMinimumSize(420, 250)

    def set_concept(self, concept: ArmConcept | None) -> None:
        self.concept = concept
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        if self.concept is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), tr("arm_concept.no_preview"))
            return
        points = self.concept.points
        xs = [p[0] for p in points]
        ys = [p[1] for p in points]
        span_x, span_y = max(max(xs) - min(xs), 1.), max(max(ys) - min(ys), 1.)
        scale = min(max(self.width() - 110., 1.) / span_x, max(self.height() - 90., 1.) / span_y)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        mapped = [QPointF(self.width() / 2 + (p[0] - cx) * scale,
                          self.height() / 2 - (p[1] - cy) * scale) for p in points]
        if self.concept.style == "sheet":
            painter.setPen(QPen(QColor("#387fa3"), 2))
            painter.setBrush(QColor(71, 150, 187, 90))
            painter.drawPolygon(QPolygonF(mapped))
        else:
            # Deliberately capped for readability: not a true projected tube.
            width = max(2., min(24., 2 * self.concept.radius_mm * scale))
            painter.setPen(QPen(QColor("#387fa3"), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            painter.drawLine(mapped[0], mapped[2])
            painter.drawLine(mapped[1], mapped[2])
        painter.setPen(self.palette().text().color())
        painter.setBrush(self.palette().text())
        for point, label in zip(mapped, (tr("arm_concept.front_point"), tr("arm_concept.rear_point"),
                                         tr("arm_concept.outer_point")), strict=True):
            painter.drawEllipse(point, 4., 4.)
            painter.drawText(point + QPointF(7., -7.), label)
        painter.end()


class ArmConceptDialog(QDialog):
    """Открыт одновременно со схемой; каждое изменение пересчитывает эскиз."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.concept: ArmConcept | None = None
        self._revision = 0
        self.setWindowTitle(tr("arm_concept.title"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(620, 620)
        layout = QVBoxLayout(self)
        warning = QLabel(tr("arm_concept.warning"), self)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self._style = QComboBox(self)
        self._style.addItem(tr("arm_concept.tube"), "tube")
        self._style.addItem(tr("arm_concept.sheet"), "sheet")
        form.addRow(tr("arm_concept.style"), self._style)
        self._radius = self._spin(12.)
        self._wall = self._spin(2.)
        self._sheet = self._spin(3.)
        form.addRow(tr("arm_concept.radius"), self._radius)
        form.addRow(tr("arm_concept.wall"), self._wall)
        form.addRow(tr("arm_concept.thickness"), self._sheet)
        layout.addLayout(form)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._canvas = ArmConceptCanvas(self)
        layout.addWidget(self._canvas, 1)
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._save_tube = QPushButton(tr("arm_concept.save_tube"), self)
        self._save_tube.clicked.connect(self._save_tube_snapshot)
        layout.addWidget(self._save_tube)
        self._save_status = QLabel(self)
        self._save_status.setWordWrap(True)
        layout.addWidget(self._save_status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._style.currentIndexChanged.connect(self._refresh)
        for spin in (self._radius, self._wall, self._sheet):
            spin.valueChanged.connect(self._refresh)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._refresh)
        self._refresh()

    def _spin(self, value: float) -> QDoubleSpinBox:
        spin = QDoubleSpinBox(self)
        spin.setRange(0.01, 10000.)
        spin.setDecimals(2)
        spin.setValue(value)
        spin.setSuffix(" mm")
        spin.setKeyboardTracking(False)
        return spin

    def _refresh(self, *_args: object) -> None:
        self._revision += 1
        self._save_status.clear()
        style = cast(ArmStyle, self._style.currentData())
        self._radius.setEnabled(style == "tube")
        self._wall.setEnabled(style == "tube")
        self._sheet.setEnabled(style == "sheet")
        try:
            concept = make_arm_concept(self.controller.project, style, self._radius.value(),
                                       self._wall.value(), self._sheet.value())
        except KimFormatError:
            self.concept = None
            self._canvas.set_concept(None)
            self._status.setText(tr("arm_concept.invalid"))
            self._summary.clear()
            self._save_tube.setEnabled(False)
            return
        self._save_tube.setEnabled(style == "tube")
        self.concept = concept
        self._canvas.set_concept(concept)
        self._status.setText(tr("arm_concept.current", project=self.controller.project.meta.name or tr("arm_concept.unnamed")))
        self._summary.setText(tr("arm_concept.summary", a=f"{concept.lengths_mm[0]:.2f}",
                                 b=f"{concept.lengths_mm[1]:.2f}", area=f"{concept.triangle_area_mm2:.2f}"))

    def _save_tube_snapshot(self) -> None:
        """Сохранить снимок параметров, не устанавливая живую связь с файлом."""
        if self.concept is None or self.concept.style != "tube":
            return
        revision = self._revision
        selected, _ = QFileDialog.getSaveFileName(self, tr("arm_concept.save_title"), "", tr("arm_concept.save_filter"))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".kim":
            path = path.with_name(path.name + ".kim")
        if revision != self._revision or self.concept is None or self.concept.style != "tube":
            QMessageBox.warning(self, tr("arm_concept.save_title"), tr("arm_concept.save_changed"))
            return
        try:
            if self.controller.is_protected_export_target(path):
                raise KimFormatError("protected project or autosave")
            part = make_lower_arm_tube_prototype("front_lower_left", tr("arm_concept.part_name"),
                                                 self.controller.project, self.concept.radius_mm, self.concept.wall_mm)
            write_document(path, "part", part)
        except (KimFormatError, OSError, RuntimeError, ValueError):
            QMessageBox.warning(self, tr("arm_concept.save_title"), tr("arm_concept.save_failed"))
            return
        self._save_status.setText(tr("arm_concept.save_done", path=str(path)))
