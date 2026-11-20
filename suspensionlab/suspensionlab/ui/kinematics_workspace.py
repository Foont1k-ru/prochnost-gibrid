"""Редактирование точек и экспериментальный дискретный расчёт в одной области."""
from __future__ import annotations

import logging
from dataclasses import replace

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMenu,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSlider,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from ..core.kinematics_workspace import (
    ElementMeasurement,
    WorkspaceResult,
    calculate,
    moved_link_end,
    static_scene,
    supported,
)
from ..core.scene3d import Segment3D
from ..core.vehicle_schematic_scene import SelectableLink
from ..i18n import tr
from ..model.kinematic_elements import ElementSetup, KinematicElements
from ..model.param_specs import point_specs
from .canvas.scene3d_preview import Scene3DPreview
from .controller import AppController, Selection
from .widgets.camera_views import CameraViews
from .widgets.slider_field import SliderField

LOG = logging.getLogger(__name__)


def _element_text(measurement: ElementMeasurement | None) -> str:
    if measurement is None:
        return 'не рассчитано'
    if measurement.length_mm is None:
        return f'не проверено: {measurement.detail}'
    incomplete = '; полностью не проверено: пределы заданы не полностью' if not measurement.limits_complete and measurement.status in ('below', 'above', 'limit') else ''
    return f'{measurement.length_mm:.2f} мм — {measurement.detail}{incomplete}'


def _summary_text(result: WorkspaceResult) -> str:
    total = len(result.samples)
    solved = [sample for sample in result.samples if sample.scene is not None]
    sections = [f'положения {len(solved)}/{total}, отказов {total - len(solved)}']
    first_failure = next((sample.error for sample in result.samples if sample.error), None)
    if first_failure:
        sections.append(f'пример отказа: {first_failure}')
    for name, label in (('spring', 'пружина'), ('damper', 'амортизатор')):
        measurements = [getattr(sample, name) for sample in solved]
        complete = sum(m is not None and m.limits_complete for m in measurements)
        conflicts = sum(m is not None and m.status in ('below', 'above') for m in measurements)
        boundary = sum(m is not None and m.status == 'limit' for m in measurements)
        invalid = sum(m is not None and m.status in ('invalid', 'error') for m in measurements)
        text = f'{label}: полные пределы {complete}/{total}, выходы {conflicts}, у границы {boundary}'
        if invalid:
            text += f', ошибок {invalid}'
        missing_mounts = sum(m is not None and m.status == 'unknown' for m in measurements)
        partial_limits = sum(m is not None and m.length_mm is not None and not m.limits_complete and
                             m.status != 'invalid' for m in measurements)
        if missing_mounts:
            text += f', крепления не заданы/не применимы: {missing_mounts}'
        if partial_limits:
            text += f', неполные пределы: {partial_limits}'
        if complete < total:
            text += ' (не полностью проверено)'
        sections.append(text)
    return '; '.join(sections)


class KinematicsWorkspace(QWidget):
    """Редактируется статическая схема; расчёт не меняет проект."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.result: WorkspaceResult | None = None
        self._rows: dict[tuple[str, str], SliderField] = {}
        self._menu: QMenu | None = None
        self._revision = 0
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(300)
        self._timer.timeout.connect(self._calculate)
        outer = QVBoxLayout(self)
        intro = QLabel('Рабочая схема: выберите ось и деталь, измените точки или длину. '
                       'Шаблоны — исходные примеры, не готовая конструкция.', self)
        intro.setWordWrap(True)
        outer.addWidget(intro)
        top = QHBoxLayout()
        top.addWidget(QLabel('Ось:', self))
        self.role = QComboBox(self)
        self.role.addItem('Передняя', 'front')
        self.role.addItem('Задняя', 'rear')
        top.addWidget(self.role)
        top.addWidget(QLabel('Деталь / группа:', self))
        self.part = QComboBox(self)
        top.addWidget(self.part, 1)
        outer.addLayout(top)
        splitter = QSplitter(self)
        splitter.setChildrenCollapsible(False)
        self.view_scroll = QScrollArea(splitter)
        self.view_scroll.setWidgetResizable(True)
        left = QWidget(self.view_scroll)
        self.view_scroll.setWidget(left)
        left_layout = QVBoxLayout(left)
        left_layout.setContentsMargins(0, 0, 0, 0)
        controls = QHBoxLayout()
        self.camera = CameraViews(self)
        self.reset = QPushButton('Сбросить вид', self)
        controls.addWidget(self.camera)
        controls.addWidget(self.reset)
        controls.addStretch(1)
        left_layout.addLayout(controls)
        self.preview = Scene3DPreview(self, schematic=True, title_override='3D-схема (не CAD)',
                                      legend_override='Мышь: вращение • колесо: масштаб')
        self.preview.volumetric = False
        # The surrounding window has several docks; the default 250px minimum
        # can force controls to overlap on a 700px-high screen.
        self.preview.setMinimumSize(240, 110)
        left_layout.addWidget(self.preview, 1)
        grid = QHBoxLayout()
        self.start = self._spin(-150, 0, -30, ' мм')
        self.end = self._spin(0, 150, 30, ' мм')
        self.spacing = self._spin(5, 30, 10, ' мм')
        for text, widget in (('От', self.start), ('До', self.end), ('Шаг ≤', self.spacing)):
            widget.setMaximumWidth(90)
            grid.addWidget(QLabel(text, self))
            grid.addWidget(widget)
        grid.addStretch(1)
        left_layout.addLayout(grid)
        self.status = QLabel(self)
        self.status.setWordWrap(True)
        self.status.setTextFormat(Qt.TextFormat.PlainText)
        left_layout.addWidget(self.status)
        self.travel = QSlider(Qt.Orientation.Horizontal, self)
        self.travel.setEnabled(False)
        left_layout.addWidget(self.travel)
        self.sample = QLabel(self)
        self.sample.setWordWrap(True)
        left_layout.addWidget(self.sample)
        self.elements_sample = QLabel(self)
        self.elements_sample.setWordWrap(True)
        left_layout.addWidget(self.elements_sample)
        self.summary = QLabel(self)
        self.summary.setWordWrap(True)
        self.summary.setTextFormat(Qt.TextFormat.PlainText)
        left_layout.addWidget(self.summary)
        warning = QLabel('Только дискретная кинематика и явно заданные пределы длин между креплениями. '
                         'Между точками, смыкание витков, упоры, столкновения, руление, нагрузки, '
                         'прочность и безопасность не проверены.', self)
        warning.setWordWrap(True)
        left_layout.addWidget(warning)
        splitter.addWidget(self.view_scroll)
        self.editor_scroll = QScrollArea(splitter)
        self.editor_scroll.setWidgetResizable(True)
        self.editor_scroll.setMinimumWidth(310)
        self.editor = QWidget(self.editor_scroll)
        self.editor_layout = QVBoxLayout(self.editor)
        self.editor_scroll.setWidget(self.editor)
        splitter.addWidget(self.editor_scroll)
        splitter.setStretchFactor(0, 3)
        splitter.setStretchFactor(1, 2)
        outer.addWidget(splitter, 1)
        self.camera.viewSelected.connect(self.preview.set_standard_view)
        self.reset.clicked.connect(self.preview.reset_camera)
        self.preview.linksClicked.connect(self._select_hits)
        self.role.currentIndexChanged.connect(self._role_changed)
        self.part.currentIndexChanged.connect(self._part_changed)
        self.travel.valueChanged.connect(self._show_sample)
        for field in (self.start, self.end, self.spacing):
            field.valueChanged.connect(self._invalidate)
        controller.modelChanged.connect(self._model_changed)
        controller.projectReplaced.connect(self._role_changed)
        controller.unitsChanged.connect(self._rebuild_editor)
        controller.selectionChanged.connect(self._external_selection)
        self._role_changed()

    def _spin(self, minimum: float, maximum: float, value: float, suffix: str) -> QDoubleSpinBox:
        box = QDoubleSpinBox(self)
        box.setRange(minimum, maximum)
        box.setDecimals(1)
        box.setValue(value)
        box.setSuffix(suffix)
        return box

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        self._invalidate()

    def _axle(self):
        return self.controller.project.axle(self.role.currentData())

    def _part_index(self, data: object) -> int:
        return next((i for i in range(self.part.count()) if self.part.itemData(i) == data), -1)

    def _role_changed(self, *_args) -> None:
        axle = self._axle()
        old = self.part.currentData()
        self.part.blockSignals(True)
        self.part.clear()
        self.part.addItem('Все точки', ('all', ''))
        for spec in axle.spec.links:
            self.part.addItem(tr(spec.name_key), ('link', spec.code))
        group_names = {'upper_arm': 'Верхний рычаг', 'lower_arm': 'Нижний рычаг',
                       'upper_links': 'Верхние тяги', 'lower_links': 'Нижние тяги', 'steering': 'Рулевое',
                       'spring': 'Пружина', 'damper': 'Амортизатор', 'arb': 'Стабилизатор',
                       'drivetrain': 'Привод', 'wheel': 'Колесо', 'trailing_links': 'Продольные тяги',
                       'axle': 'Мост', 'triangulated': 'Треугольные тяги', 'lateral': 'Поперечные тяги',
                       'torque_arm': 'Реактивная тяга', 'strut': 'Стойка'}
        for group in axle.spec.point_groups:
            self.part.addItem('Точки: ' + group_names.get(group, group), ('group', group))
        index = self._part_index(old) if old is not None else -1
        if index < 0:
            index = self._part_index(('link', 'lower_arm'))
        if index < 0 and axle.spec.links:
            index = self._part_index(('link', axle.spec.links[0].code))
        self.part.setCurrentIndex(max(0, index))
        self.part.blockSignals(False)
        self._rebuild_editor()
        self._invalidate()
        self._show_sample()

    def _point_codes(self) -> list[str]:
        axle = self._axle()
        kind, code = self.part.currentData() or ('all', '')
        if kind == 'link':
            spec = axle.spec.link(code)
            return [p for p in (*spec.pivot, spec.end) if p in axle.hardpoints] if spec else []
        return [spec.code for spec in axle.spec.points
                if spec.code in axle.hardpoints and (kind == 'all' or spec.group == code)]

    def _part_changed(self, *_args) -> None:
        kind, code = self.part.currentData() or ('all', '')
        if kind == 'link':
            self.controller.select(Selection('link', self.role.currentData(), code))
        else:
            self.controller.select(Selection('axle', self.role.currentData()))
        self._rebuild_editor()
        self._show_sample()

    def _external_selection(self, selection: Selection | None) -> None:
        if selection is None or selection.kind != 'link' or selection.role != self.role.currentData():
            return
        index = self._part_index(('link', selection.code))
        if index >= 0 and index != self.part.currentIndex():
            self.part.setCurrentIndex(index)

    def _rebuild_editor(self, *_args) -> None:
        while self.editor_layout.count():
            item = self.editor_layout.takeAt(0)
            widget = item.widget() if item else None
            if widget is not None:
                widget.hide()
                widget.deleteLater()
        self._rows.clear()
        self._element_controls: dict[str, QComboBox | QDoubleSpinBox] = {}
        axle = self._axle()
        role = self.role.currentData()
        kind, code = self.part.currentData() or ('all', '')
        hint = QLabel('Координаты исходной схемы: X — вдоль, Y — влево, Z — вверх. '
                      'Для симметричных осей редактируется левая сторона.', self.editor)
        hint.setWordWrap(True)
        self.editor_layout.addWidget(hint)
        self.length: QDoubleSpinBox | None = None
        if kind == 'link':
            group = QGroupBox('Длина детали', self.editor)
            form = QVBoxLayout(group)
            form.addWidget(QLabel('От оси до конца', group))
            self.length = self._spin(0.001, 1_000_000, max(0.001, axle.link_length(code)), ' мм')
            self.length.setDecimals(3)
            self.length.setKeyboardTracking(False)
            self.length.valueChanged.connect(lambda value: self._change_length(code, value))
            form.addWidget(self.length)
            note = QLabel('Меняется наружная точка, перпендикулярно оси. Общие точки меняют и соседние детали.')
            note.setWordWrap(True)
            form.addWidget(note)
            self.editor_layout.addWidget(group)
        if kind == 'group' and code in ('spring', 'damper'):
            self._add_element_editor(code)
        for point_code in self._point_codes():
            point = axle.hardpoints[point_code]
            ps = axle.spec.point(point_code)
            group = QGroupBox(self.editor)
            layout = QVBoxLayout(group)
            title = QLabel(tr(ps.name_key) if ps else point_code, group)
            title.setWordWrap(True)
            layout.addWidget(title)
            for original_spec in point_specs(point, point_code)[0].params[:3]:
                value = float(original_spec.value())
                spec = replace(original_spec, minimum=min(original_spec.minimum, value - 100),
                               maximum=max(original_spec.maximum, value + 100))
                key = f'{role}.{spec.key}'
                field = SliderField(spec, self.controller.units, value, group,
                                    auto_extend=self.controller.auto_extend_slider,
                                    locked=point.locked or self.controller.is_locked(key))
                field._title.setText(spec.attr.upper())
                field._title.setMinimumWidth(24)
                field._lock_button.setEnabled(not point.locked)
                field.valueChanged.connect(lambda value, p=point_code, a=spec.attr: self._change_point(p, a, value))
                field.lockChanged.connect(lambda locked, k=key: self.controller.set_lock(k, locked))
                field.helpRequested.connect(self._show_help)
                self._rows[(point_code, spec.attr)] = field
                layout.addWidget(field)
            self.editor_layout.addWidget(group)
        self.editor_layout.addStretch(1)

    def _active_setup(self, name: str) -> ElementSetup:
        axle = self._axle()
        config = axle.kinematic_elements
        return getattr(config, name) if config is not None and config.type_code == axle.type_code else ElementSetup()

    def _add_element_editor(self, name: str) -> None:
        axle = self._axle()
        title = 'Проверка пружины' if name == 'spring' else 'Проверка амортизатора'
        group = QGroupBox(title, self.editor)
        form = QFormLayout(group)
        hint = QLabel('Укажите, к чему жёстко прикреплён каждый центр. '
                      'Пределы — расстояния между центрами, не длина штока и не длина витков.', group)
        hint.setWordWrap(True)
        form.addRow(hint)
        if not supported(axle):
            text = QLabel('Для этой схемы движение креплений не рассчитывается.', group)
            text.setWordWrap(True)
            form.addRow(text)
            self.editor_layout.addWidget(group)
            return
        setup = self._active_setup(name)
        for attr, label in (('lower', 'Нижняя точка'), ('upper', 'Верхняя точка')):
            combo = QComboBox(group)
            combo.addItem('Не задано', None)
            combo.addItem('Кузов', 'body')
            combo.addItem('Кулак', 'upright')
            if axle.type_code == 'double_wishbone':
                combo.addItem('Нижний рычаг', 'lower_arm')
            value = getattr(setup, attr)
            index = next((i for i in range(combo.count()) if combo.itemData(i) == value), 0)
            combo.setCurrentIndex(index)
            combo.currentIndexChanged.connect(lambda _i, field=attr: self._change_element(name, field))
            self._element_controls[attr] = combo
            form.addRow(label, combo)
        for attr, label in (('minimum_mm', 'Минимум, мм'), ('maximum_mm', 'Максимум, мм')):
            box = QDoubleSpinBox(group)
            box.setRange(0, 1_000_000)
            box.setDecimals(3)
            box.setSpecialValueText('Не задано')
            box.setSuffix(' мм')
            box.setKeyboardTracking(False)
            box.setValue(getattr(setup, attr) or 0)
            box.valueChanged.connect(lambda _v, field=attr: self._change_element(name, field))
            self._element_controls[attr] = box
            form.addRow(label, box)
        self.editor_layout.addWidget(group)

    def _change_element(self, name: str, field: str) -> None:
        axle = self._axle()
        if not supported(axle) or len(self._element_controls) != 4:
            return
        lower, upper = self._element_controls['lower'], self._element_controls['upper']
        minimum, maximum = self._element_controls['minimum_mm'], self._element_controls['maximum_mm']
        assert isinstance(lower, QComboBox) and isinstance(upper, QComboBox)
        assert isinstance(minimum, QDoubleSpinBox) and isinstance(maximum, QDoubleSpinBox)
        setup = ElementSetup(lower.currentData(), upper.currentData(), minimum.value() or None, maximum.value() or None)
        config = axle.kinematic_elements
        if config is None or config.type_code != axle.type_code:
            config = KinematicElements(axle.type_code)
        updated = replace(config, **{name: setup})
        self.controller.set_value(axle, 'kinematic_elements', updated,
                                  merge_key=f'kinematic-elements:{id(axle)}:{name}:{field}:{self._revision}')

    def _refresh_element_controls(self) -> None:
        kind, name = self.part.currentData() or ('all', '')
        if kind != 'group' or name not in ('spring', 'damper') or not self._element_controls:
            return
        setup = self._active_setup(name)
        for attr, widget in self._element_controls.items():
            widget.blockSignals(True)
            if isinstance(widget, QComboBox):
                value = getattr(setup, attr)
                index = next((i for i in range(widget.count()) if widget.itemData(i) == value), 0)
                widget.setCurrentIndex(index)
            else:
                widget.setValue(getattr(setup, attr) or 0)
            widget.blockSignals(False)

    def _show_help(self, key: str) -> None:
        QMessageBox.information(self, tr('insp.info'), tr(key))

    def _change_point(self, code: str, axis: str, value: float) -> None:
        point = self._axle().hardpoints.get(code)
        if point is None:
            return
        values = list(point.as_tuple())
        values['xyz'.index(axis)] = value
        try:
            if abs(value) > 1_000_000:
                raise ValueError('Координата вне диапазона отображения')
            self.controller.move_points({(self.role.currentData(), code): tuple(values)})
        except (ValueError, KeyError):
            self._refresh_fields()
            self.sample.setText('Точка зафиксирована или координата вне диапазона отображения.')

    def _change_length(self, code: str, value: float) -> None:
        try:
            target, xyz = moved_link_end(self._axle(), code, value)
            self.controller.move_points({(self.role.currentData(), target): xyz})
        except (ValueError, KeyError):
            self._refresh_fields()
            self.sample.setText('Длину изменить не удалось: точка зафиксирована или направление не определено.')

    def _refresh_fields(self) -> None:
        axle = self._axle()
        role = self.role.currentData()
        for (code, axis), widget in self._rows.items():
            point = axle.hardpoints.get(code)
            if point is not None:
                value = getattr(point, axis)
                if value < widget._minimum or value > widget._maximum:
                    widget._minimum = min(widget._minimum, value - 100)
                    widget._maximum = max(widget._maximum, value + 100)
                    widget._update_slider_range()
                widget.set_value(value)
                widget.set_locked(point.locked or self.controller.is_locked(f'{role}.point.{code}.{axis}'))
                widget._lock_button.setEnabled(not point.locked)
        kind, code = self.part.currentData() or ('all', '')
        if kind == 'link' and self.length is not None:
            self.length.blockSignals(True)
            self.length.setValue(max(0.001, axle.link_length(code)))
            self.length.blockSignals(False)

    def _model_changed(self) -> None:
        self._refresh_fields()
        self._refresh_element_controls()
        self._invalidate()

    def _invalidate(self, *_args) -> None:
        self._revision += 1
        self.result = None
        self._timer.stop()
        self.travel.setEnabled(False)
        self.sample.setText('')
        self.elements_sample.setText('')
        self.summary.setText('Сводка обеих осей: ожидает пересчёта.')
        try:
            scene, links = static_scene(self._axle())
            self.preview.link_targets = links
            self.preview.configure([scene])
            self.preview.show_frame(scene)
        except (ValueError, KeyError, OverflowError):
            self.preview.clear('Не удалось показать статическую схему.')
        self.status.setText('Параметры изменены: расчёт ожидает обновления.')
        if self.isVisible():
            self._timer.start()

    def _calculate(self) -> None:
        axle = self._axle()
        results: dict[str, WorkspaceResult] = {}
        errors: dict[str, str] = {}
        summaries = []
        for role, label in (('front', 'Передняя'), ('rear', 'Задняя')):
            other = self.controller.project.axle(role)
            if not supported(other):
                errors[role] = 'Расчёт хода для этой схемы пока не реализован. Показана только статическая компоновка.'
                summaries.append(f'{label}: только статическая схема; не проверено')
                continue
            try:
                calculated = calculate(other, self.start.value(), self.end.value(), self.spacing.value())
                results[role] = calculated
                summaries.append(f'{label}: {_summary_text(calculated)}')
            except (ValueError, KeyError, OverflowError, ArithmeticError) as error:
                errors[role] = f'Расчёт не выполнен: {error}. Показана статическая схема.'
                summaries.append(f'{label}: расчёт не выполнен: {error}; не проверено')
            except Exception:
                LOG.exception('Неожиданная ошибка кинематического расчёта')
                errors[role] = 'Расчёт не выполнен из-за ошибки. Показана статическая схема.'
                summaries.append(f'{label}: ошибка расчёта; не проверено')
        self.summary.setText('Сводка (на заданной сетке хода):\n' + '\n'.join(summaries))
        result = results.get(axle.role)
        if result is None:
            self.status.setText(errors[axle.role])
            return
        self.result = result
        success = sum(sample.scene is not None for sample in result.samples)
        failures = [sample for sample in result.samples if sample.error]
        model_description = ('Левая сторона, неподвижная рейка' if axle.role == 'front' else
                             'Левая сторона, пять тяг, неподвижный кузов')
        text = (f'{model_description}. Решено положений: {success} из {len(result.samples)}; '
                f'последние достигнутые ходы {result.reached_droop_mm:.1f}…{result.reached_bump_mm:.1f} мм.')
        if failures:
            text += f' Пример отказа: {failures[0].error}'
        self.status.setText(text)
        frames = [sample.scene for sample in result.samples if sample.scene is not None]
        self.preview.configure(frames)
        self.travel.blockSignals(True)
        self.travel.setRange(0, len(result.samples) - 1)
        self.travel.setValue(min(range(len(result.samples)), key=lambda i: abs(result.samples[i].travel_mm)))
        self.travel.blockSignals(False)
        self.travel.setEnabled(True)
        self._show_sample()

    def _show_sample(self, *_args) -> None:
        kind, code = self.part.currentData() or ('all', '')
        self.preview.selected_link = (self.role.currentData(), code) if kind == 'link' else None
        if self.result is None:
            self.preview.update()
            return
        sample = self.result.samples[self.travel.value()]
        self.preview.show_frame(sample.scene, 'Нет решения для этого положения')
        self.preview.link_targets = ()
        if sample.scene is not None:
            targets = []
            for spec in self._axle().spec.links:
                end = sample.scene.point(spec.end)
                for pivot in spec.pivot:
                    start = sample.scene.point(pivot)
                    if start is not None and end is not None:
                        targets.append(SelectableLink(self.role.currentData(), spec.code, Segment3D(start, end, 'arm')))
            self.preview.link_targets = tuple(targets)
        self.elements_sample.setText(f'Пружина: {_element_text(sample.spring)}\n'
                                     f'Амортизатор: {_element_text(sample.damper)}')
        if sample.error:
            self.sample.setText(f'Ход {sample.travel_mm:+.1f} мм: нет решения. {sample.error}')
        elif sample.metrics is None:
            self.sample.setText(f'Ход {sample.travel_mm:+.1f} мм: положение найдено, углы не рассчитаны.')
        else:
            self.sample.setText(f'Ход {sample.travel_mm:+.1f} мм • развал {sample.metrics.camber_deg:+.2f}° '
                                f'• схождение одного колеса {sample.metrics.toe_deg:+.2f}°')

    def _select_hits(self, hits, position) -> None:
        if not hits:
            return
        if len(hits) == 1:
            self._apply_hit(hits[0].code, self._revision)
            return
        if self._menu is not None:
            self._menu.close()
        menu = QMenu(self)
        self._menu = menu
        revision = self._revision
        for hit in hits:
            spec = self._axle().spec.link(hit.code)
            if spec:
                action = menu.addAction(tr(spec.name_key))
                action.triggered.connect(lambda _checked=False, code=hit.code, rev=revision: self._apply_hit(code, rev))
        menu.aboutToHide.connect(menu.deleteLater)
        menu.popup(self.preview.mapToGlobal(position))

    def _apply_hit(self, code: str, revision: int) -> None:
        if revision != self._revision:
            return
        index = self._part_index(('link', code))
        if index >= 0:
            self.part.setCurrentIndex(index)
