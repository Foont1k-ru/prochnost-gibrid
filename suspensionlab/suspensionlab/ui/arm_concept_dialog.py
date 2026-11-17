"""Немодальный эскиз: производная схема, не CAD-деталь и не расчёт прочности."""
from __future__ import annotations

from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..i18n import tr
from ..model.arm_concept import ArmConcept, ArmStyle, make_arm_concept
from ..model.kim_format import KimFormatError, make_lower_arm_tube_prototype, write_document
from ..model.welded_arm import make_welded_arm, weldment_centerlines
from .controller import AppController
from .weldment_3d import Weldment3D


class ArmConceptCanvas(QWidget):
    """Условная проекция XY; толщина трубы/листа не является CAD-геометрией."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.concept: ArmConcept | None = None
        self.paths: tuple[tuple[tuple[float, float, float], ...], ...] | None = None
        self.setMinimumSize(420, 250)

    def set_concept(self, concept: ArmConcept | None,
                    paths: tuple[tuple[tuple[float, float, float], ...], ...] | None = None) -> None:
        self.concept = concept
        self.paths = paths if concept is not None else None
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
        paths = self.paths if self.paths is not None and self.concept.style == "tube" else (
            (points[0], points[2]), (points[1], points[2]))
        extent = [*points, *(point for path in paths for point in path)]
        xs = [p[0] for p in extent]
        ys = [p[1] for p in extent]
        span_x, span_y = max(max(xs) - min(xs), 1.), max(max(ys) - min(ys), 1.)
        scale = min(max(self.width() - 110., 1.) / span_x, max(self.height() - 90., 1.) / span_y)
        cx, cy = (max(xs) + min(xs)) / 2, (max(ys) + min(ys)) / 2
        def project(point: tuple[float, float, float]) -> QPointF:
            return QPointF(self.width() / 2 + (point[0] - cx) * scale,
                           self.height() / 2 - (point[1] - cy) * scale)
        mapped = [project(p) for p in points]
        if self.concept.style == "sheet":
            painter.setPen(QPen(QColor("#387fa3"), 2))
            painter.setBrush(QColor(71, 150, 187, 90))
            painter.drawPolygon(QPolygonF(mapped))
        else:
            # Deliberately capped for readability: not a true projected tube.
            width = max(2., min(24., 2 * self.concept.radius_mm * scale))
            painter.setPen(QPen(QColor("#387fa3"), width, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            for path in paths:
                painter.drawPolyline(QPolygonF([project(point) for point in path]))
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
        self._candidate: dict[str, Any] | None = None
        self._revision = 0
        self.setWindowTitle(tr("arm_concept.title"))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(680, 760)
        root = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        root.addWidget(scroll)
        content = QWidget(scroll)
        scroll.setWidget(content)
        layout = QVBoxLayout(content)
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
        self._damper = QComboBox(self)
        self._damper.addItem(tr("arm_concept.damper_unknown"), "unknown")
        self._damper.addItem(tr("arm_concept.damper_required"), "required")
        self._damper.addItem(tr("arm_concept.damper_not_required"), "not_required")
        form.addRow(tr("arm_concept.damper_mount"), self._damper)
        self._bend_checks: dict[str, QCheckBox] = {}
        self._bend_fields: dict[str, list[QLineEdit]] = {}
        for leg in ("front", "rear"):
            row = QHBoxLayout()
            check = QCheckBox(tr(f"arm_concept.bend_{leg}"), self)
            row.addWidget(check)
            fields = []
            for key in ("x", "y", "z", "r"):
                field = QLineEdit(self)
                field.setPlaceholderText(tr(f"arm_concept.bend_{key}"))
                field.setAccessibleName(tr(f"arm_concept.bend_{leg}") + " " + tr(f"arm_concept.bend_{key}"))
                field.setMaxLength(24)
                row.addWidget(field)
                fields.append(field)
            self._bend_checks[leg] = check
            self._bend_fields[leg] = fields
            form.addRow(row)
        layout.addLayout(form)
        bend_note = QLabel(tr("arm_concept.bend_note"), self)
        bend_note.setWordWrap(True)
        layout.addWidget(bend_note)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        self._status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._status)
        self._tabs = QTabWidget(self)
        self._canvas = ArmConceptCanvas(self._tabs)
        self._tabs.addTab(self._canvas, tr("weldment_3d.tab_2d"))
        self._three_d = Weldment3D(self._tabs, is_current=self._candidate_is_current)
        self._tabs.addTab(self._three_d, tr("weldment_3d.tab_3d"))
        layout.addWidget(self._tabs, 1)
        self._snapshot_status = QLabel(self)
        self._snapshot_status.setWordWrap(True)
        layout.addWidget(self._snapshot_status)
        self._summary = QLabel(self)
        self._summary.setWordWrap(True)
        layout.addWidget(self._summary)
        self._save_assembly = QPushButton(tr("arm_concept.save_assembly"), self)
        self._save_assembly.clicked.connect(self._save_weldment_snapshot)
        layout.addWidget(self._save_assembly)
        self._save_tube = QPushButton(tr("arm_concept.save_tube"), self)
        self._save_tube.clicked.connect(self._save_tube_snapshot)
        layout.addWidget(self._save_tube)
        self._save_status = QLabel(self)
        self._save_status.setWordWrap(True)
        self._save_status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self._save_status)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._three_d.availabilityChanged.connect(self._update_save)
        self._style.currentIndexChanged.connect(self._refresh)
        self._damper.currentIndexChanged.connect(self._refresh)
        for spin in (self._radius, self._wall, self._sheet):
            spin.valueChanged.connect(self._refresh)
        for check in self._bend_checks.values():
            check.toggled.connect(self._refresh)
        for fields in self._bend_fields.values():
            for field in fields:
                field.textChanged.connect(self._refresh)
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
        self._candidate = None
        self._three_d.set_document(None)
        self._snapshot_status.clear()
        style = cast(ArmStyle, self._style.currentData())
        self._radius.setEnabled(style == "tube")
        self._wall.setEnabled(style == "tube")
        self._sheet.setEnabled(style == "sheet")
        self._damper.setEnabled(style == "tube")
        for leg, check in self._bend_checks.items():
            check.setEnabled(style == "tube")
            for field in self._bend_fields[leg]:
                field.setEnabled(style == "tube" and check.isChecked())
        has_bend = style == "tube" and any(check.isChecked() for check in self._bend_checks.values())
        try:
            concept = make_arm_concept(self.controller.project, style, self._radius.value(),
                                       self._wall.value(), self._sheet.value())
        except KimFormatError:
            self.concept = None
            self._canvas.set_concept(None)
            self._status.setText(tr("arm_concept.invalid"))
            self._summary.clear()
            self._save_tube.setEnabled(False)
            self._save_assembly.setEnabled(False)
            return
        self._save_tube.setEnabled(style == "tube" and not has_bend)
        self.concept = concept
        if style == "tube":
            try:
                self._candidate = make_welded_arm(self.controller.project, concept.radius_mm,
                                                  concept.wall_mm, str(self._damper.currentData()), bends=self._read_bends())
            except (KimFormatError, TypeError, ValueError, OverflowError):
                self._snapshot_status.setText(tr("arm_concept.bend_invalid" if has_bend else "arm_concept.snapshot_invalid"))
        self._three_d.set_document(self._candidate)
        self._update_save()
        paths = weldment_centerlines(self._candidate) if self._candidate is not None and style == "tube" else None
        # A requested but invalid bend must not fall back to the old straight lines.
        self._canvas.set_concept(None if has_bend and self._candidate is None else concept, paths)
        self._status.setText(tr("arm_concept.current", project=self.controller.project.meta.name or tr("arm_concept.unnamed")))
        self._summary.setText(tr("arm_concept.summary", a=f"{concept.lengths_mm[0]:.2f}",
                                 b=f"{concept.lengths_mm[1]:.2f}", area=f"{concept.triangle_area_mm2:.2f}"))

    def _read_bends(self) -> dict[str, dict[str, Any]]:
        result: dict[str, dict[str, Any]] = {}
        for leg, check in self._bend_checks.items():
            if not check.isChecked():
                continue
            try:
                numbers = [float(field.text().strip().replace(",", ".")) for field in self._bend_fields[leg]]
            except ValueError as error:
                raise KimFormatError("all bend inputs are required") from error
            result[leg] = {"vertex_mm": numbers[:3], "radius_mm": numbers[3]}
        return result

    def _candidate_is_current(self, candidate: dict[str, Any]) -> bool:
        if self._candidate is None or candidate != self._candidate or self._style.currentData() != "tube":
            return False
        try:
            concept = make_arm_concept(self.controller.project, "tube", self._radius.value(),
                                       self._wall.value(), self._sheet.value())
            current = make_welded_arm(self.controller.project, concept.radius_mm, concept.wall_mm,
                                      str(self._damper.currentData()), bends=self._read_bends())
            return current == candidate
        except (KimFormatError, TypeError, ValueError, OverflowError):
            return False

    def _update_save(self, *_args: object) -> None:
        self._save_assembly.setEnabled(self._candidate is not None and self._three_d.can_save())

    def shutdown(self) -> bool:
        return self._three_d.shutdown()

    def reject(self) -> None:
        if self.shutdown():
            super().reject()

    def closeEvent(self, event) -> None:  # noqa: N802
        if self.shutdown():
            super().closeEvent(event)
        else:
            event.ignore()

    def _save_tube_snapshot(self) -> None:
        """Старый эксперимент — две трубы в одном документе, не деталь."""
        self._save_snapshot("part")

    def _save_weldment_snapshot(self) -> None:
        """Сохранить неполный снимок структуры сварной сборки."""
        self._save_snapshot("assembly")

    def _save_snapshot(self, kind: str) -> None:
        if self.concept is None or self.concept.style != "tube":
            return
        if kind == "part" and any(check.isChecked() for check in self._bend_checks.values()):
            return  # old two-straight-tube format cannot represent bends
        is_assembly = kind == "assembly"
        candidate = self._candidate if is_assembly else None
        if is_assembly and (candidate is None or not self._three_d.can_save()):
            return
        revision = self._revision
        generation = self._three_d.generation
        # Capture the old experiment too, so even unsignalled edits cannot
        # silently produce a different file while the native dialog is open.
        try:
            part = (None if is_assembly else
                    make_lower_arm_tube_prototype("front_lower_left", tr("arm_concept.part_name"),
                                                  self.controller.project, self._radius.value(), self._wall.value()))
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, tr("arm_concept.save_title"), tr("arm_concept.save_failed"))
            return
        suffix = ".kima" if is_assembly else ".kim"
        filter_key = "arm_concept.assembly_filter" if is_assembly else "arm_concept.save_filter"
        selected, _ = QFileDialog.getSaveFileName(self, tr("arm_concept.save_title"), "", tr(filter_key))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != suffix:
            path = path.with_name(path.name + suffix)
        changed = (revision != self._revision or self.concept is None or self.concept.style != "tube" or
                   (is_assembly and (generation != self._three_d.generation or not self._three_d.can_save())))
        if changed:
            QMessageBox.warning(self, tr("arm_concept.save_title"), tr("arm_concept.save_changed"))
            return
        try:
            if is_assembly:
                if candidate is None or not self._candidate_is_current(candidate):
                    raise KimFormatError("project changed")
                document = candidate
            else:
                document = make_lower_arm_tube_prototype("front_lower_left", tr("arm_concept.part_name"),
                                                        self.controller.project, self._radius.value(), self._wall.value())
                if document != part:
                    raise KimFormatError("project changed")
            if self.controller.is_protected_export_target(path):
                raise KimFormatError("protected project or autosave")
            # A new path only: also closes the suffix-appending overwrite gap.
            write_document(path, kind, document, overwrite=False)
        except (KimFormatError, OSError, RuntimeError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, tr("arm_concept.save_title"), tr("arm_concept.save_failed"))
            self._refresh()
            return
        done = "arm_concept.assembly_done" if is_assembly else "arm_concept.save_done"
        self._save_status.setText(tr(done, path=str(path)))
