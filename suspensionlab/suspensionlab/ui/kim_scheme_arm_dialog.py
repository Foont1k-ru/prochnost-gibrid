"""Открытие самодостаточного снимка схемы и двух труб в .kim 0.3."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..model.arm_concept import make_arm_concept
from ..model.entities import Project
from ..model.kim_format import (
    SCHEME_ARM_PART_VERSION,
    KimFormatError,
    _part,
    compare_lower_arm_source,
    rebuild_scheme_arm_part,
    write_document,
)
from ..model.welded_arm import make_welded_arm
from .arm_concept_dialog import ArmConceptCanvas
from .controller import AppController
from .weldment_3d import Weldment3D


class KimSchemeArmDialog(QDialog):
    def __init__(self, controller: AppController, document: dict[str, Any], path: Path,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _part(document)
        if document["version"] != SCHEME_ARM_PART_VERSION:
            raise KimFormatError("not a scheme-driven part")
        self.controller, self.path = controller, path
        self.document = deepcopy(document)
        self._saved = deepcopy(document)
        self._preview_doc: dict[str, Any] | None = None
        self.setWindowTitle("Экспериментальная деталь .kim — схема и 3D-заготовка")
        self.resize(780, 750)
        layout = QVBoxLayout(self)
        notice = QLabel("В файле сохранены полный снимок схемы и параметры двух прямых труб. "
                        "Трубы пересекаются, не подрезаны и не объединены. Креплений, сварки, чертежа, "
                        "истории 3D-операций и проверки прочности пока нет. Это не готовая деталь.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.tabs = QTabWidget(self)
        self.canvas = ArmConceptCanvas(self.tabs)
        self.tabs.addTab(self.canvas, "Схема заготовки XY")
        self.three_d = Weldment3D(self.tabs, is_current=lambda candidate: candidate == self._preview_doc)
        self.tabs.addTab(self.three_d, "3D: только трубы")
        layout.addWidget(self.tabs, 1)
        self.source_status = QLabel()
        self.source_status.setWordWrap(True)
        layout.addWidget(self.source_status)
        self.apply_scheme = QPushButton("Перестроить по текущей схеме…")
        self.apply_scheme.clicked.connect(self._apply_current_scheme)
        layout.addWidget(self.apply_scheme)
        self.save_copy = QPushButton("Сохранить новую копию .kim…")
        self.save_copy.clicked.connect(self._save_copy)
        layout.addWidget(self.save_copy)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)
        self.three_d.availabilityChanged.connect(self._update_save)
        self.controller.modelChanged.connect(self._update_source_status)
        self.controller.projectReplaced.connect(self._update_source_status)
        self._show_document()

    def _show_document(self) -> None:
        project = Project.from_dict(self.document["scheme"])
        geometry = self.document["geometry"]
        concept = make_arm_concept(project, "tube", geometry["radius_mm"], geometry["wall_mm"], 3.)
        self.canvas.set_concept(concept)
        candidate = make_welded_arm(project, geometry["radius_mm"], geometry["wall_mm"], "unknown")
        if candidate != self._preview_doc:
            self._preview_doc = candidate
            self.three_d.set_document(candidate)
        marker = " • изменён, не сохранён" if self.document != self._saved else ""
        self.status.setText(f"{self.path}{marker}\nРадиус: {geometry['radius_mm']:g} мм; стенка: {geometry['wall_mm']:g} мм. "
                            "Схема и заготовка открыты из файла, не из текущего проекта.")
        self._update_source_status()
        self._update_save()

    def _update_source_status(self, *_args: object) -> None:
        matches = compare_lower_arm_source(self.document, self.controller.project)
        state = "совпадают" if matches else "различаются или недоступны"
        self.source_status.setText(f"Текущий проект: тип передней подвески и три точки {state}. "
                                   "Это не проверка идентичности проекта, других параметров или монтажа.")

    def _update_save(self, *_args: object) -> None:
        self.save_copy.setEnabled(self.three_d.can_save())

    def _apply_current_scheme(self) -> None:
        original = deepcopy(self.document)
        try:
            updated = rebuild_scheme_arm_part(original, self.controller.project)
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, "Перестроение", "Текущая схема несовместима или точки некорректны. "
                                "Тип подвески менять нельзя. Файл и заготовка не изменены.")
            return
        if updated == self.document:
            self.source_status.setText("Снимок схемы уже совпадает с текущим проектом; файл не изменён.")
            return
        answer = QMessageBox.question(self, "Перестроение по текущей схеме",
                                      "Вы уверены, что открыт нужный проект? Будет заменён снимок схемы и "
                                      "перестроены обе трубы по текущим точкам; радиус и стенка сохранятся. "
                                      "Сохранённый файл не изменится: потребуется новая копия. "
                                      "Сравнение трёх точек не подтверждает принадлежность проекту.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.document != original or updated != rebuild_scheme_arm_part(original, self.controller.project):
                raise KimFormatError("project changed during confirmation")
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, "Перестроение", "Схема изменилась во время подтверждения. Повторите действие.")
            return
        self.document = updated
        self._show_document()

    def _save_copy(self) -> None:
        if not self.three_d.can_save():
            return
        original, generation = deepcopy(self.document), self.three_d.generation
        name = self.path.with_name(self.path.stem + "-новый.kim")
        selected, _ = QFileDialog.getSaveFileName(self, "Сохранить новую копию", str(name), "Деталь KIM (*.kim)")
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".kim":
            path = path.with_name(path.name + ".kim")
        try:
            if self.document != original or self.three_d.generation != generation or not self.three_d.can_save():
                raise KimFormatError("document changed during save")
            if self.controller.is_protected_export_target(path):
                raise KimFormatError("protected path")
            write_document(path, "part", original, overwrite=False)
        except (KimFormatError, OSError, RuntimeError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, "Сохранение .kim", "Не удалось сохранить новую копию. Существующие файлы не перезаписываются.")
            return
        self.path, self._saved = path, deepcopy(original)
        self._show_document()

    def _confirm_close(self) -> bool:
        if self.document == self._saved:
            return True
        result = QMessageBox.question(self, "Несохранённая заготовка", "Закрыть без сохранения новой копии?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return result == QMessageBox.StandardButton.Yes

    def reject(self) -> None:
        if self._confirm_close() and self.three_d.shutdown():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_close() and self.three_d.shutdown():
            super().reject()
            event.accept()
        else:
            event.ignore()
