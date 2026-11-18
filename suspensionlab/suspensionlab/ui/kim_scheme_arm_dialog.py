"""Открытие самодостаточного снимка схемы и труб и условных корпусов в .kim 0.3/0.4."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtGui import QCloseEvent
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..model.arm_concept import make_arm_concept
from ..model.entities import Project
from ..model.kim_format import (
    SCHEME_ARM_BUSHING_VERSION,
    SCHEME_ARM_PART_VERSIONS,
    KimFormatError,
    _part,
    _validate_scheme_arm_bushings,
    compare_lower_arm_source,
    rebuild_scheme_arm_part,
    set_scheme_arm_bushings,
    write_document,
)
from ..model.welded_arm import make_welded_arm
from .arm_concept_dialog import ArmConceptCanvas
from .controller import AppController
from .weldment_3d import Weldment3D


class BushingParametersDialog(QDialog):
    """Явные размеры двух одинаковых условных корпусов, без автоматической оценки."""
    def __init__(self, values: dict[str, Any] | None, parent: QWidget) -> None:
        super().__init__(parent)
        self.setWindowTitle("Условные корпуса втулок")
        layout = QVBoxLayout(self)
        notice = QLabel("Два одинаковых полых корпуса в центрах внутренних опор. "
                        "Размеры ниже — только пример; задайте свои. Ось относительно кузова, не трубы. "
                        "Корпуса и трубы не подрезаются и не соединяются.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        data = values or {"axis": "x", "outer_radius_mm": 14., "bore_radius_mm": 7., "length_mm": 24.}
        form = QFormLayout()
        self.axis = QComboBox(self)
        for key, label in (("x", "X — продольная"), ("y", "Y — поперечная"), ("z", "Z — вертикальная")):
            self.axis.addItem(label, key)
        self.axis.setCurrentIndex(self.axis.findData(data["axis"]))
        form.addRow("Общая ось, ISO", self.axis)
        self.fields: dict[str, QLineEdit] = {}
        for key, label in (("outer_radius_mm", "Наружный радиус, мм"),
                           ("bore_radius_mm", "Радиус отверстия, мм"), ("length_mm", "Длина корпуса, мм")):
            field = QLineEdit(str(data[key]), self)
            field.setMaxLength(64)
            field.setAccessibleName(label)
            self.fields[key] = field
            form.addRow(label, field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def accept(self) -> None:
        try:
            _validate_scheme_arm_bushings(self.values())
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, "Корпуса втулок", "Проверьте размеры: радиусы и длина от 0,1 до 500 мм; "
                                "наружный радиус должен превышать радиус отверстия минимум на 0,1 мм.")
            return
        super().accept()

    def values(self) -> dict[str, Any]:
        return {"axis": str(self.axis.currentData()),
                **{key: float(field.text().strip().replace(",", ".")) for key, field in self.fields.items()}}


class KimSchemeArmDialog(QDialog):
    def __init__(self, controller: AppController, document: dict[str, Any], path: Path,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        _part(document)
        if document["version"] not in SCHEME_ARM_PART_VERSIONS:
            raise KimFormatError("not a scheme-driven part")
        self.controller, self.path = controller, path
        self.document = deepcopy(document)
        self._saved = deepcopy(document)
        self._preview_doc: dict[str, Any] | None = None
        self.setWindowTitle("Экспериментальная деталь .kim — схема и 3D-заготовка")
        self.resize(780, 750)
        layout = QVBoxLayout(self)
        notice = QLabel("Снимок схемы и две прямые трубы; можно добавить два условных полых корпуса втулок. "
                        "Это отдельные пересекающиеся тела без подрезки и соединения. Покупных сайлентблоков, "
                        "шаровой, сварки, чертежа, истории 3D и проверки прочности нет. Это не готовая деталь.")
        notice.setWordWrap(True)
        layout.addWidget(notice)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.tabs = QTabWidget(self)
        self.canvas = ArmConceptCanvas(self.tabs)
        self.tabs.addTab(self.canvas, "Схема заготовки XY")
        self.three_d = Weldment3D(self.tabs, is_current=lambda candidate: candidate == self._preview_doc, scheme_part=True)
        self.tabs.addTab(self.three_d, "3D: предварительные тела")
        layout.addWidget(self.tabs, 1)
        self.source_status = QLabel()
        self.source_status.setWordWrap(True)
        layout.addWidget(self.source_status)
        self.apply_scheme = QPushButton("Перестроить по текущей схеме…")
        self.apply_scheme.clicked.connect(self._apply_current_scheme)
        layout.addWidget(self.apply_scheme)
        self.edit_bushings = QPushButton("Добавить или изменить корпуса втулок…")
        self.edit_bushings.clicked.connect(self._edit_bushings)
        layout.addWidget(self.edit_bushings)
        self.remove_bushings = QPushButton("Удалить условные корпуса втулок…")
        self.remove_bushings.clicked.connect(self._remove_bushings)
        layout.addWidget(self.remove_bushings)
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
        candidate = (deepcopy(self.document) if self.document["version"] == SCHEME_ARM_BUSHING_VERSION else
                     make_welded_arm(project, geometry["radius_mm"], geometry["wall_mm"], "unknown"))
        if candidate != self._preview_doc:
            self._preview_doc = candidate
            self.three_d.set_document(candidate)
        marker = " • изменён, не сохранён" if self.document != self._saved else ""
        self.status.setText(f"{self.path}{marker}\nРадиус: {geometry['radius_mm']:g} мм; стенка: {geometry['wall_mm']:g} мм. "
                            "Схема и заготовка открыты из файла, не из текущего проекта.")
        self.remove_bushings.setEnabled(self.document["version"] == SCHEME_ARM_BUSHING_VERSION)
        if self.document["version"] == SCHEME_ARM_BUSHING_VERSION:
            b = self.document["bushings"]
            self.status.setText(self.status.text() + f"\nДва условных корпуса: ось {b['axis'].upper()}, "
                                f"R={b['outer_radius_mm']:g}, r={b['bore_radius_mm']:g}, L={b['length_mm']:g} мм.")
        self._update_source_status()
        self._update_save()

    def _edit_bushings(self) -> None:
        original = deepcopy(self.document)
        dialog = BushingParametersDialog(original.get("bushings"), self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if self.document != original:
                raise KimFormatError("document changed during input")
            updated = set_scheme_arm_bushings(original, dialog.values())
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, "Корпуса втулок", "Некорректные размеры или документ изменился. "
                                "Корпуса не изменены: радиусы и длина 0,1–500 мм, "
                                "наружный радиус больше отверстия минимум на 0,1 мм.")
            return
        self.document = updated
        self._show_document()

    def _remove_bushings(self) -> None:
        original = deepcopy(self.document)
        if original["version"] != SCHEME_ARM_BUSHING_VERSION:
            return
        answer = QMessageBox.question(self, "Удаление корпусов", "Удалить оба условных корпуса из черновика? "
                                      "Исходный файл не изменится; сохранение — только в новую копию.",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes or self.document != original:
            return
        self.document = set_scheme_arm_bushings(original, None)
        self._show_document()

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
                                      "перестроены трубы и условные корпуса по текущим точкам; размеры и ось сохранятся. "
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
        original = deepcopy(self.document)
        result = QMessageBox.question(self, "Несохранённая заготовка", "Закрыть без сохранения новой копии?",
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return result == QMessageBox.StandardButton.Yes and self.document == original

    def reject(self) -> None:
        if self._confirm_close() and self.three_d.shutdown():
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_close() and self.three_d.shutdown():
            super().reject()
            event.accept()
        else:
            event.ignore()
