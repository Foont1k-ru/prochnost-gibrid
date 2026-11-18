"""Предварительная сборка из отдельных KIM-деталей и снимка схемы."""
from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any, cast

from PySide6.QtCore import QSignalBlocker, Qt
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
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..model.arm_concept import make_arm_concept
from ..model.assembly_snapshot_fingerprint import assembly_snapshot_fingerprint
from ..model.autosave_guard import same_project_file
from ..model.entities import Project
from ..model.kim_format import KimFormatError, _number, compare_lower_arm_source, read_document, write_document
from ..model.scheme_arm_assembly import (
    PARTS,
    PLATE_PARTS,
    PLATE_VERSION,
    edit_assembly_part,
    make_plate,
    rebuild_scheme_arm_assembly,
    replace_assembly_part,
    set_assembly_axis,
    set_assembly_plate,
    set_plate_placement,
    validate_scheme_arm_assembly,
)
from .arm_concept_dialog import ArmConceptCanvas
from .assembly_material_estimate import AssemblyMaterialEstimate
from .cad_assembly_projection import CadAssemblyProjectionView
from .controller import AppController
from .kim_scheme_arm_dialog import BushingParametersDialog
from .scheme_assembly_views import SchemeAssemblyViews
from .weldment_3d import Weldment3D


class NewAssemblyParametersDialog(BushingParametersDialog):
    """Начальные параметры, которые схема сама не задаёт."""
    def __init__(self, parent: QWidget) -> None:
        super().__init__(None, parent)
        self.setWindowTitle('Параметры передней левой сборки')
        side_note = QLabel('Создаётся предварительная сборка переднего нижнего ЛЕВОГО рычага '
                           'по трём точкам схемы. Подсветка в 3D может включать обе зеркальные стороны. '
                           'Размеры ниже — примеры: проверьте и задайте свои; это не данные CAD или рекомендация.')
        side_note.setWordWrap(True)
        cast(QVBoxLayout, self.layout()).insertWidget(0, side_note)
        form = QFormLayout()
        self.radius = QLineEdit('12', self)
        self.wall = QLineEdit('2', self)
        for field in (self.radius, self.wall):
            field.setMaxLength(64)
        form.addRow('Радиус обеих труб, мм', self.radius)
        form.addRow('Толщина стенки обеих труб, мм', self.wall)
        cast(QVBoxLayout, self.layout()).insertLayout(1, form)

    def tube_values(self) -> tuple[float, float]:
        radius = _number(float(self.radius.text().strip().replace(',', '.')), positive=True)
        wall = _number(float(self.wall.text().strip().replace(',', '.')), positive=True)
        if not (0.01 <= wall <= 10000 and 0.01 <= radius <= 10000 and radius - wall >= 0.01):
            raise KimFormatError('invalid tube dimensions')
        return radius, wall

    def accept(self) -> None:
        try:
            self.tube_values()
        except (KimFormatError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Параметры труб', 'Проверьте радиус и стенку: 0,01–10000 мм, '
                                'внутренний радиус не меньше 0,01 мм.')
            return
        super().accept()


class PartDimensionsDialog(QDialog):
    """Параметры одной встроенной детали; неизвестные операции не изменяются."""
    def __init__(self, document: dict[str, Any], identifier: str, parent: QWidget) -> None:
        super().__init__(parent)
        self.document = deepcopy(document)
        self.identifier = identifier
        self.setWindowTitle('Размеры выбранной детали')
        layout = QVBoxLayout(self)
        part = document['parts'][PLATE_PARTS.index(identifier)]
        info = QLabel(f"{part['name']}\nЭто предварительная форма без подрезки и проверок.")
        info.setWordWrap(True)
        info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(info)
        form = QFormLayout()
        self.fields: dict[str, QLineEdit] = {}
        labels = ((('radius_mm', 'Наружный радиус трубы, мм'), ('wall_mm', 'Толщина стенки, мм'))
                  if identifier in PARTS[:2] else
                  (('width_mm', 'Ширина по локальной X, мм'), ('height_mm', 'Высота по локальной Y, мм'),
                   ('thickness_mm', 'Толщина, мм'), ('hole_radius_mm', 'Радиус центрального отверстия, мм'))
                  if identifier == 'ball_plate' else
                  (('outer_radius_mm', 'Наружный радиус корпуса, мм'),
                   ('bore_radius_mm', 'Радиус отверстия, мм'), ('length_mm', 'Длина корпуса, мм')))
        for key, label in labels:
            field = QLineEdit(str(part['geometry'][key]), self)
            field.setMaxLength(64)
            field.setAccessibleName(label)
            self.fields[key] = field
            form.addRow(label, field)
        layout.addLayout(form)
        actions = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        actions.accepted.connect(self.accept)
        actions.rejected.connect(self.reject)
        layout.addWidget(actions)

    def values(self) -> dict[str, float]:
        return {key: float(field.text().strip().replace(',', '.')) for key, field in self.fields.items()}

    def accept(self) -> None:
        try:
            edit_assembly_part(self.document, self.identifier, self.values())
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Размеры детали', 'Некорректные размеры: проверьте радиусы, толщину и длину. '
                                'Численные пределы не являются инженерными допусками.')
            return
        super().accept()


class PlatePlacementDialog(QDialog):
    """Добавление условной пластины или изменение её привязки к точке шаровой."""
    def __init__(self, document: dict[str, Any], parent: QWidget) -> None:
        super().__init__(parent)
        self.document = deepcopy(document)
        self.has_plate = document['version'] == PLATE_VERSION
        self.setWindowTitle('Условная пластина у шаровой')
        layout = QVBoxLayout(self)
        note = QLabel('Условная прямоугольная пластина с одним центральным сквозным отверстием. '
                      'Размеры — пример, не измерения. Центр отверстия смещается от точки шаровой по осям кузова. '
                      'Нормаль задаёт только одно из трёх направлений; произвольного поворота в плоскости нет. '
                      'Реальная шаровая, контакт с трубами, крепление и прочность не проверяются.')
        note.setWordWrap(True)
        layout.addWidget(note)
        form = QFormLayout()
        self.fields: dict[str, QLineEdit] = {}
        if not self.has_plate:
            for key, label, value in (('width_mm', 'Ширина X в плоскости, мм', '60'),
                                      ('height_mm', 'Высота Y в плоскости, мм', '50'),
                                      ('thickness_mm', 'Толщина, мм', '5'),
                                      ('hole_radius_mm', 'Радиус отверстия, мм', '10')):
                field = QLineEdit(value, self)
                field.setMaxLength(64)
                field.setAccessibleName(label)
                self.fields[key] = field
                form.addRow(label, field)
        placement = document.get('plate_placement', {'normal': 'z', 'offset_mm': [0, 0, 0]})
        self.normal = QComboBox(self)
        for key, label in (('x', 'X — плоскость YZ'), ('y', 'Y — плоскость XZ'), ('z', 'Z — плоскость XY')):
            self.normal.addItem(label, key)
        self.normal.setCurrentIndex(self.normal.findData(placement['normal']))
        form.addRow('Нормаль пластины в кузове', self.normal)
        self.offset_fields: list[QLineEdit] = []
        for index, axis in enumerate(('X', 'Y', 'Z')):
            label = f'Смещение {axis} от точки шаровой, мм'
            field = QLineEdit(str(placement['offset_mm'][index]), self)
            field.setMaxLength(64)
            field.setAccessibleName(label)
            self.offset_fields.append(field)
            form.addRow(label, field)
        layout.addLayout(form)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def candidate(self) -> dict[str, Any]:
        placement = {'normal': str(self.normal.currentData()),
                     'offset_mm': [float(field.text().strip().replace(',', '.')) for field in self.offset_fields]}
        if self.has_plate:
            return set_plate_placement(self.document, placement)
        values = {key: float(field.text().strip().replace(',', '.')) for key, field in self.fields.items()}
        part = make_plate(values['width_mm'], values['height_mm'], values['thickness_mm'], values['hole_radius_mm'])
        return set_assembly_plate(self.document, part, placement)

    def accept(self) -> None:
        try:
            self.candidate()
        except (KimFormatError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, 'Условная пластина', 'Проверьте размеры и смещения. Отверстие должно оставлять '
                                'не менее 0,1 мм до краёв; смещение ограничено ±10000 мм. '
                                'Это геометрические ограничения, не инженерные допуски.')
            return
        super().accept()


class SchemeArmAssemblyDialog(QDialog):
    def __init__(self, controller: AppController, document: dict[str, Any], path: Path | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        validate_scheme_arm_assembly(document)
        self.controller, self.path = controller, path
        self._source_paths: list[Path] = []
        if path is not None:
            self._remember_source(path)
        self.document = deepcopy(document)
        self._saved = deepcopy(document) if path is not None else None
        self.setWindowTitle('Предварительная сборка рычага .kima')
        self.resize(800, 780)
        outer = QVBoxLayout(self)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        outer.addWidget(scroll)
        body = QWidget(scroll)
        scroll.setWidget(body)
        layout = QVBoxLayout(body)
        note = QLabel('Две трубы и два корпуса — отдельные встроенные детали .kim. '
                      'Трубы заданы в координатах кузова, корпуса — локально по оси Z и размещены в точках схемы. '
                      'Можно явно добавить условную пластину у шаровой: она не является готовым кронштейном. '
                      'Покупные изделия и сварка не спроектированы. Тела могут пересекаться; '
                      'подрезки, монтажа и проверки прочности нет.')
        note.setWordWrap(True)
        layout.addWidget(note)
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.status)
        self.tabs = QTabWidget(self)
        self.tabs.setMinimumHeight(360)
        self.canvas = ArmConceptCanvas(self.tabs)
        self.tabs.addTab(self.canvas, 'Схема XY — условно')
        self.three_d = Weldment3D(self.tabs, is_current=lambda candidate: candidate == self.document, scheme_part=True)
        self.tabs.addTab(self.three_d, '3D — предварительная сборка')
        self.views = SchemeAssemblyViews(self.tabs)
        self.tabs.addTab(self.views, 'Виды и размеры — условно')
        self.cad_views = CadAssemblyProjectionView(
            self.tabs, is_current=lambda candidate: candidate == self.document and
            assembly_snapshot_fingerprint(candidate) == assembly_snapshot_fingerprint(self.document))
        self.tabs.addTab(self.cad_views, 'CAD-проекции — предварительно')
        self.material_estimate = AssemblyMaterialEstimate(
            self.tabs, is_current=lambda candidate: candidate == self.document and
            assembly_snapshot_fingerprint(candidate) == assembly_snapshot_fingerprint(self.document))
        self.tabs.addTab(self.material_estimate, 'Объём и масса — справочно')
        layout.addWidget(self.tabs, 1)
        self.source_status = QLabel()
        self.source_status.setWordWrap(True)
        layout.addWidget(self.source_status)
        axis_form = QFormLayout()
        self.axis = QComboBox(self)
        for key, label in (('x', 'X — продольная'), ('y', 'Y — поперечная'), ('z', 'Z — вертикальная')):
            self.axis.addItem(label, key)
        self.axis.setCurrentIndex(self.axis.findData(document['axis']))
        self.axis.currentIndexChanged.connect(self._change_axis)
        axis_form.addRow('Общая ось корпусов относительно кузова', self.axis)
        layout.addLayout(axis_form)
        self.apply_scheme = QPushButton('Перестроить по текущей схеме…')
        self.apply_scheme.clicked.connect(self._apply_current_scheme)
        layout.addWidget(self.apply_scheme)
        self.plate_button = QPushButton('Добавить условную пластину…')
        self.plate_button.clicked.connect(self._edit_plate_placement)
        layout.addWidget(self.plate_button)
        self.remove_plate = QPushButton('Удалить условную пластину…')
        self.remove_plate.clicked.connect(self._remove_plate)
        layout.addWidget(self.remove_plate)
        self.save_copy = QPushButton('Сохранить новую сборку .kima…')
        self.save_copy.clicked.connect(self._save_copy)
        layout.addWidget(self.save_copy)
        export = QFormLayout()
        self.part_choice = QComboBox(self)
        for part in self.document['parts']:
            self.part_choice.addItem(part['name'], part['id'])
        export.addRow('Встроенная отдельная деталь', self.part_choice)
        layout.addLayout(export)
        self.part_info = QLabel()
        self.part_info.setWordWrap(True)
        self.part_info.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.part_info)
        self.part_choice.currentIndexChanged.connect(self._update_part_info)
        self.edit_part = QPushButton('Изменить размеры выбранной детали…')
        self.edit_part.clicked.connect(self._edit_selected_part)
        layout.addWidget(self.edit_part)
        self.import_part = QPushButton('Заменить выбранную деталь снимком из .kim…')
        self.import_part.clicked.connect(self._import_selected_part)
        layout.addWidget(self.import_part)
        self.export_part = QPushButton('Сохранить выбранную деталь отдельно .kim…')
        self.export_part.clicked.connect(self._export_part)
        layout.addWidget(self.export_part)
        self.feedback = QLabel()
        self.feedback.setWordWrap(True)
        self.feedback.setTextFormat(Qt.TextFormat.PlainText)
        layout.addWidget(self.feedback)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self.three_d.availabilityChanged.connect(self._update_save)
        self.controller.modelChanged.connect(self._update_source_status)
        self.controller.projectReplaced.connect(self._update_source_status)
        self._show_document()

    def _show_document(self) -> None:
        self.views.set_document(self.document)
        self.cad_views.set_document(self.document)
        self.material_estimate.set_document(self.document)
        project = Project.from_dict(self.document['scheme'])
        geometry = self.document['parts'][0]['geometry']
        self.canvas.set_concept(make_arm_concept(project, 'tube', geometry['radius_mm'], geometry['wall_mm'], 3.))
        if self.three_d._document != self.document:
            self.three_d.set_document(deepcopy(self.document))
        path = str(self.path) if self.path else 'Новая несохранённая сборка'
        marker = ' • изменена, не сохранена' if self.document != self._saved else ''
        plate = self.document['version'] == PLATE_VERSION
        self.status.setText(f'{path}{marker}\nОсь корпусов: {self.document["axis"].upper()}. '
                            f'Снимок схемы и {len(self.document["parts"])} деталей находятся внутри сборки.')
        self.plate_button.setText('Изменить положение пластины…' if plate else 'Добавить условную пластину…')
        self.remove_plate.setEnabled(plate)
        with QSignalBlocker(self.axis):
            self.axis.setCurrentIndex(self.axis.findData(self.document['axis']))
        with QSignalBlocker(self.part_choice):
            selected = self.part_choice.currentData()
            self.part_choice.clear()
            for part in self.document['parts']:
                self.part_choice.addItem(part['name'], part['id'])
            position = self.part_choice.findData(selected)
            self.part_choice.setCurrentIndex(position if position >= 0 else 0)
        self._update_part_info()
        self._update_source_status()
        self._update_save()

    def _update_part_info(self, *_args: object) -> None:
        identifier = self.part_choice.currentData()
        if identifier not in (PLATE_PARTS if self.document['version'] == PLATE_VERSION else PARTS):
            self.part_info.clear()
            return
        part = self.document['parts'][PLATE_PARTS.index(identifier)]
        g = part['geometry']
        if identifier in PARTS[:2]:
            detail = f"радиус {g['radius_mm']:g} мм; стенка {g['wall_mm']:g} мм"
        elif identifier == 'ball_plate':
            p = self.document['plate_placement']
            detail = (f"{g['width_mm']:g} × {g['height_mm']:g} × {g['thickness_mm']:g} мм; "
                      f"радиус отверстия {g['hole_radius_mm']:g} мм; нормаль {p['normal'].upper()}, "
                      f"смещение {p['offset_mm']} мм")
        else:
            detail = (f"наружный радиус {g['outer_radius_mm']:g} мм; отверстие {g['bore_radius_mm']:g} мм; "
                      f"длина {g['length_mm']:g} мм")
        self.part_info.setText(f"{part['name']}: {detail}. Редактируется только эта встроенная деталь.")

    def _change_axis(self, *_args: object) -> None:
        try:
            updated = set_assembly_axis(self.document, str(self.axis.currentData()))
        except (KimFormatError, ValueError, TypeError):
            with QSignalBlocker(self.axis):
                self.axis.setCurrentIndex(self.axis.findData(self.document['axis']))
            return
        self.document = updated
        self.feedback.clear()
        self._show_document()

    def _edit_selected_part(self) -> None:
        original, identifier = deepcopy(self.document), self.part_choice.currentData()
        if identifier not in (PLATE_PARTS if self.document['version'] == PLATE_VERSION else PARTS):
            return
        dialog = PartDimensionsDialog(original, identifier, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if self.document != original or self.part_choice.currentData() != identifier:
                raise KimFormatError('changed during input')
            updated = edit_assembly_part(original, identifier, dialog.values())
        except (KimFormatError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, 'Размеры детали', 'Размеры некорректны или сборка изменилась. Деталь не изменена.')
            return
        self.document = updated
        self.feedback.clear()
        self._show_document()

    def _import_selected_part(self) -> None:
        original, identifier = deepcopy(self.document), self.part_choice.currentData()
        if identifier not in (PLATE_PARTS if self.document['version'] == PLATE_VERSION else PARTS):
            return
        selected, _ = QFileDialog.getOpenFileName(self, 'Выбрать снимок детали', '', 'Деталь KIM (*.kim)')
        if not selected:
            return
        try:
            if self.document != original or self.part_choice.currentData() != identifier:
                raise KimFormatError('changed during selection')
            path = Path(selected).absolute()
            resolved = path.resolve()
            imported = read_document(path, 'part')
            updated = replace_assembly_part(original, identifier, imported)
        except (KimFormatError, OSError, ValueError, TypeError, OverflowError, RuntimeError):
            QMessageBox.warning(self, 'Замена детали', 'Файл не подходит для выбранной позиции или сборка изменилась. '
                                'Для трубы должны совпадать сторона и точки схемы. Сборка не изменена.')
            return
        if updated == original:
            self.feedback.setText('Выбранный снимок уже совпадает с встроенной деталью.')
            return
        answer = QMessageBox.question(self, 'Замена детали',
                                      'Заменить выбранную встроенную деталь снимком из файла? '
                                      'Несохранённые размеры этой детали будут заменены. '
                                      'Идентификатор позиции сохранится; внешней связи с файлом не будет.',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if (self.document != original or self.part_choice.currentData() != identifier or
                    path.resolve() != resolved or read_document(path, 'part') != imported):
                raise KimFormatError('changed during confirmation')
            updated = replace_assembly_part(original, identifier, imported)
        except (KimFormatError, OSError, ValueError, TypeError, OverflowError, RuntimeError):
            QMessageBox.warning(self, 'Замена детали', 'Деталь или сборка изменились во время подтверждения. Повторите выбор.')
            return
        self.document = updated
        self._remember_source(path)
        self.feedback.setText('Снимок заменён в памяти. Внешний файл не синхронизируется; сохраните новую сборку.')
        self._show_document()

    def _edit_plate_placement(self) -> None:
        original = deepcopy(self.document)
        dialog = PlatePlacementDialog(original, self)
        if dialog.exec() != QDialog.DialogCode.Accepted:
            return
        try:
            if self.document != original:
                raise KimFormatError('changed during input')
            updated = dialog.candidate()
        except (KimFormatError, ValueError, TypeError, OverflowError):
            QMessageBox.warning(self, 'Условная пластина', 'Параметры неверны или сборка изменилась. Данные не изменены.')
            return
        self.document = updated
        self.feedback.setText('Условная пластина не подтверждает крепление шаровой. Сохраните новую копию сборки.')
        self._show_document()

    def _remove_plate(self) -> None:
        original = deepcopy(self.document)
        if original['version'] != PLATE_VERSION:
            return
        answer = QMessageBox.question(self, 'Удаление пластины',
                                      'Удалить условную пластину из сборки? Исходные файлы не изменятся.',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes or self.document != original:
            return
        self.document = set_assembly_plate(original, None)
        self.feedback.setText('Пластина удалена из черновика; сохраните новую копию сборки.')
        self._show_document()

    def _update_source_status(self, *_args: object) -> None:
        matches = all(compare_lower_arm_source(part, self.controller.project) for part in self.document['parts'][:2])
        state = 'совпадают' if matches else 'различаются или недоступны'
        self.source_status.setText(f'Передний нижний ЛЕВЫЙ рычаг: тип подвески и три исходные точки '
                                   f'текущего проекта {state}. Сравнение выполняется по округлённому снимку; '
                                   'остальные данные не сравниваются. Совпадение не подтверждает принадлежность '
                                   'сборки проекту или её пригодность.')

    def _update_save(self, *_args: object) -> None:
        self.save_copy.setEnabled(self.three_d.can_save())

    def _apply_current_scheme(self) -> None:
        original = deepcopy(self.document)
        try:
            updated = rebuild_scheme_arm_assembly(original, self.controller.project)
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Перестроение', 'Схема несовместима или точки некорректны. Сборка не изменена.')
            return
        if updated == original:
            self.feedback.setText('Снимок схемы уже совпадает с текущим проектом.')
            return
        answer = QMessageBox.question(self, 'Перестроение по схеме',
                                      'Проверьте, что открыт нужный проект. Заменить снимок схемы и '
                                      'перестроить трубы и размещение корпусов и пластины? Размеры и ориентации сохранятся; '
                                      'исходный файл не изменится.',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        if answer != QMessageBox.StandardButton.Yes:
            return
        try:
            if self.document != original or updated != rebuild_scheme_arm_assembly(original, self.controller.project):
                raise KimFormatError('changed during confirmation')
        except (KimFormatError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Перестроение', 'Документ или схема изменились. Повторите действие.')
            return
        self.document = updated
        self.feedback.clear()
        self._show_document()

    def _remember_source(self, path: Path) -> None:
        absolute = path.absolute()
        for candidate in (absolute, absolute.resolve()):
            if candidate not in self._source_paths:
                self._source_paths.append(candidate)

    def _safe_path(self, path: Path) -> None:
        if (self.controller.is_protected_export_target(path) or
                any(same_project_file(path, source) for source in self._source_paths)):
            raise KimFormatError('protected source')

    def _save_copy(self) -> None:
        if not self.three_d.can_save():
            return
        original, generation = deepcopy(self.document), self.three_d.generation
        selected, _ = QFileDialog.getSaveFileName(self, 'Сохранить новую сборку', 'рычаг.kima', 'Сборка KIMA (*.kima)')
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kima':
            path = path.with_name(path.name + '.kima')
        try:
            if original != self.document or generation != self.three_d.generation or not self.three_d.can_save():
                raise KimFormatError('changed during save')
            self._safe_path(path)
            write_document(path, 'assembly', original, overwrite=False)
        except (KimFormatError, OSError, RuntimeError, TypeError, ValueError, OverflowError):
            QMessageBox.warning(self, 'Сохранение сборки', 'Не удалось сохранить новую сборку. Существующие файлы не изменены.')
            return
        self.path, self._saved = path, deepcopy(original)
        self._remember_source(path)
        self.feedback.setText(f'Сохранена новая сборка: {path}')
        self._show_document()

    def _export_part(self) -> None:
        original = deepcopy(self.document)
        identifier = self.part_choice.currentData()
        selected, _ = QFileDialog.getSaveFileName(self, 'Сохранить деталь отдельно', f'{identifier}.kim', 'Деталь KIM (*.kim)')
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != '.kim':
            path = path.with_name(path.name + '.kim')
        try:
            if original != self.document or identifier != self.part_choice.currentData():
                raise KimFormatError('changed during export')
            self._safe_path(path)
            part = next(part for part in original['parts'] if part['id'] == identifier)
            write_document(path, 'part', part, overwrite=False)
        except (KimFormatError, OSError, RuntimeError, TypeError, ValueError, OverflowError, StopIteration):
            QMessageBox.warning(self, 'Сохранение детали', 'Не удалось сохранить новую копию детали. Файлы не изменены.')
            return
        self.feedback.setText(f'Сохранена отдельная деталь: {path}. Внешний файл не синхронизируется со сборкой.')

    def _confirm_close(self) -> bool:
        if self.document == self._saved:
            return True
        original = deepcopy(self.document)
        answer = QMessageBox.question(self, 'Несохранённая сборка', 'Закрыть без сохранения новой сборки?',
                                      QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                                      QMessageBox.StandardButton.No)
        return answer == QMessageBox.StandardButton.Yes and self.document == original

    def reject(self) -> None:
        if self._confirm_close() and self.three_d.shutdown() and self.cad_views.shutdown():
            self.views.shutdown()
            super().reject()

    def closeEvent(self, event: QCloseEvent) -> None:
        if self._confirm_close() and self.three_d.shutdown() and self.cad_views.shutdown():
            self.views.shutdown()
            super().reject()
            event.accept()
        else:
            event.ignore()
