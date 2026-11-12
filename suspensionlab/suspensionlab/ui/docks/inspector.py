"""Инспектор: автоматически построенная панель параметров выбранного узла.

Виджеты создаются по декларативным описаниям :mod:`suspensionlab.model.param_specs`
и :mod:`suspensionlab.model.suspension_types`. Числовые параметры получают
строку «ползунок + независимое поле» (Р-1), перечисления — выпадающий
список, флаги — галочку.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QGroupBox,
    QLabel,
    QLineEdit,
    QMessageBox,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...i18n import tr
from ...model import param_specs as specs
from ...model.entities import Axle
from ...model.param_specs import GroupSpec, ParamSpec
from ...model.suspension_types import types_for_role
from ..controller import AppController, Selection
from ..widgets.slider_field import SliderField


@dataclass(slots=True)
class _Row:
    """Связка «описание параметра ↔ виджет» для обновления значений."""

    spec: ParamSpec
    widget: QWidget
    is_length: bool = False


class Inspector(QWidget):
    """Панель инспектора с прокруткой."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._rows: list[_Row] = []
        self._container = QWidget(self)
        self._layout = QVBoxLayout(self._container)
        self._layout.setContentsMargins(8, 8, 8, 8)
        self._layout.setSpacing(8)
        self._layout.addStretch(1)

        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(self._container)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(scroll)

        controller.selectionChanged.connect(self._on_selection_changed)
        controller.projectReplaced.connect(self.rebuild)
        controller.modelChanged.connect(self.refresh)
        controller.unitsChanged.connect(self.rebuild)
        self.rebuild()

    # ------------------------------------------------------------------ выбор
    def _on_selection_changed(self, selection: Selection | None) -> None:
        """Перестраивает панель при выборе другого элемента."""
        self.rebuild()

    # ------------------------------------------------------------------ построение
    def _clear(self) -> None:
        """Удаляет все элементы панели."""
        while self._layout.count():
            item = self._layout.takeAt(0)
            if item is None:
                continue
            widget = item.widget()
            if widget is not None:
                widget.hide()
                widget.setParent(None)
                widget.deleteLater()
        self._rows.clear()

    def rebuild(self) -> None:
        """Строит панель для текущего выбора."""
        self._clear()
        selection = self._controller.selection
        if selection is None:
            self._add_placeholder()
            self._layout.addStretch(1)
            return

        header = self._build_header(selection)
        if header is not None:
            self._layout.addWidget(header)

        for group in self._groups_for(selection):
            if not group.params:
                continue
            self._layout.addWidget(self._build_group(group))
        self._layout.addStretch(1)

    def _add_placeholder(self) -> None:
        """Заглушка пустого состояния — с подсказкой, а не «нет данных»."""
        title = QLabel(tr("insp.no_selection"))
        title.setWordWrap(True)
        hint = QLabel(tr("insp.no_selection_hint"))
        hint.setObjectName("Hint")
        hint.setWordWrap(True)
        self._layout.addWidget(title)
        self._layout.addWidget(hint)

    def _build_header(self, selection: Selection) -> QWidget | None:
        """Заголовок панели: название элемента и специальные переключатели."""
        project = self._controller.project
        if selection.kind == "point":
            return self._simple_header(self._point_title(project.axle(selection.role), selection.code))
        if selection.kind == "link":
            axle = project.axle(selection.role)
            spec = axle.spec.link(selection.code)
            return self._simple_header(tr(spec.name_key) if spec else selection.code)
        if selection.kind in ("axle", "front", "rear"):
            return self._axle_header(project.axle(selection.role))
        if selection.kind == "vehicle":
            return self._simple_header(tr("tree.vehicle"))
        if selection.kind == "project":
            return self._simple_header(tr("tree.project"))
        if selection.kind == "snapshots":
            return self._simple_header(tr("tree.snapshots"))
        return self._simple_header(tr(f"tree.{selection.kind}"))

    def _point_title(self, axle: Axle, code: str) -> str:
        """Название точки с указанием стороны (для моста точки заданы явно)."""
        spec = axle.spec.point(code)
        if spec is None:
            return code
        if spec.side == "center":
            return tr(spec.name_key)
        return f"{tr(spec.name_key)} ({tr(f'hp.side.{spec.side}')})"

    def _simple_header(self, text: str) -> QWidget:
        """Заголовок с названием выбранного элемента."""
        label = QLabel(text)
        label.setStyleSheet("font-size:15px; font-weight:700;")
        label.setWordWrap(True)
        return label

    def _axle_header(self, axle: Axle) -> QWidget:
        """Заголовок оси: тип подвески и вариант схемы (для моста)."""
        box = QGroupBox(tr("tree.front") if axle.role == "front" else tr("tree.rear"))
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)

        type_row = QWidget(box)
        type_layout = QVBoxLayout(type_row)
        type_layout.setContentsMargins(0, 0, 0, 0)
        type_layout.addWidget(QLabel(tr("menu.axle.front_type") if axle.role == "front" else tr("menu.axle.rear_type")))
        combo = QComboBox(type_row)
        for code in types_for_role(axle.role):
            combo.addItem(tr(f"type.{code}.name"), code)
        index = combo.findData(axle.type_code)
        if index >= 0:
            combo.setCurrentIndex(index)
        combo.currentIndexChanged.connect(lambda _index, c=combo, a=axle: self._on_type_changed(a, c))
        type_layout.addWidget(combo)
        layout.addWidget(type_row)

        if axle.spec.layouts:
            layout_combo = QComboBox(box)
            for layout_code in axle.spec.layouts:
                layout_combo.addItem(tr(f"layout.{layout_code}"), layout_code)
            current = layout_combo.findData(axle.layout)
            layout_combo.setCurrentIndex(max(0, current))
            layout_combo.currentIndexChanged.connect(
                lambda _index, c=layout_combo, a=axle: self._controller.set_value(
                    a, "layout", c.currentData(), "undo.value", f"layout:{a.role}"
                )
            )
            layout.addWidget(QLabel(tr("layout.title")))
            layout.addWidget(layout_combo)
        return box

    def _on_type_changed(self, axle: Axle, combo: QComboBox) -> None:
        """Смена типа подвески из заголовка."""
        self._controller.set_axle_type(axle.role, combo.currentData())

    def _groups_for(self, selection: Selection) -> list[GroupSpec]:
        """Список групп параметров для выбранного элемента."""
        project = self._controller.project
        if selection.kind == "project":
            return specs.project_specs(project)
        if selection.kind == "vehicle":
            return specs.vehicle_specs(project.vehicle)
        if selection.kind == "axle":
            return []
        axle = project.axle(selection.role) if selection.role else None
        if selection.kind == "point" and axle is not None:
            point = axle.hardpoints.get(selection.code)
            if point is None:
                return []
            return specs.point_specs(point, selection.code)
        if selection.kind == "link" and axle is not None:
            link = axle.links.get(selection.code)
            if link is None:
                return []
            return specs.link_specs(link, axle, selection.code)
        if axle is None:
            return []
        if selection.kind == "wheel":
            return specs.wheel_specs(axle.wheel)
        if selection.kind == "spring":
            return specs.spring_specs(axle)
        if selection.kind == "damper":
            return specs.damper_specs(axle)
        if selection.kind == "arb":
            return specs.arb_specs(axle)
        if selection.kind == "bump_stop":
            return specs.bump_stop_specs(axle)
        if selection.kind == "steering":
            return specs.steering_specs(axle)
        if selection.kind == "drivetrain":
            return specs.drivetrain_specs(axle)
        if selection.kind == "setup":
            return specs.setup_specs(axle)
        if selection.kind == "travel":
            return specs.travel_specs(axle)
        return []

    def _build_group(self, group: GroupSpec) -> QWidget:
        """Строит группу параметров."""
        box = QGroupBox(tr(group.title_key))
        layout = QVBoxLayout(box)
        layout.setContentsMargins(8, 8, 8, 8)
        layout.setSpacing(2)
        for spec in group.params:
            widget = self._build_row(spec)
            if widget is not None:
                layout.addWidget(widget)
        return box

    def _build_row(self, spec: ParamSpec) -> QWidget | None:
        """Строит строку одного параметра."""
        if spec.kind in ("float", "int"):
            return self._build_slider_row(spec)
        if spec.kind == "bool":
            checkbox = QCheckBox(tr(spec.title_key))
            checkbox.setChecked(bool(spec.value()))
            checkbox.toggled.connect(lambda checked, s=spec: self._on_bool(s, checked))
            self._rows.append(_Row(spec, checkbox))
            return checkbox
        if spec.kind == "text":
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.addWidget(QLabel(tr(spec.title_key)))
            edit = QLineEdit(str(spec.value()))
            edit.editingFinished.connect(lambda e=edit, s=spec: self._on_text(s, e))
            row_layout.addWidget(edit)
            self._rows.append(_Row(spec, edit))
            return row
        if spec.kind == "enum":
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.addWidget(QLabel(tr(spec.title_key)))
            combo = QComboBox()
            for value, label_key in spec.options:
                combo.addItem(tr(label_key), value)
            index = combo.findData(str(spec.value()))
            combo.setCurrentIndex(max(0, index))
            combo.currentIndexChanged.connect(lambda _i, c=combo, s=spec: self._on_enum(s, c))
            row_layout.addWidget(combo)
            self._rows.append(_Row(spec, combo))
            return row
        if spec.kind == "readonly":
            row = QWidget()
            row_layout = QVBoxLayout(row)
            row_layout.setContentsMargins(0, 2, 0, 2)
            row_layout.addWidget(QLabel(tr(spec.title_key)))
            value_label = QLabel("—")
            value_label.setObjectName("Hint")
            row_layout.addWidget(value_label)
            self._rows.append(_Row(spec, value_label))
            return row
        return None

    def _build_slider_row(self, spec: ParamSpec) -> QWidget:
        """Строит строку «ползунок + поле»."""
        is_length = spec.key.startswith("link.") and spec.key.endswith(".length")
        value = float(spec.value())
        selection = self._controller.selection
        lock_key = f"{selection.role}.{spec.key}" if selection and selection.role else spec.key
        widget = SliderField(
            spec,
            self._controller.units,
            default=value,
            auto_extend=self._controller.auto_extend_slider,
            locked=(not is_length) and self._controller.is_locked(lock_key),
        )
        widget.valueChanged.connect(lambda new_value, s=spec, w=widget: self._on_value(s, new_value, w))
        widget.lockChanged.connect(lambda checked, key=lock_key: self._controller.set_lock(key, checked))
        widget.helpRequested.connect(self._show_help)
        self._rows.append(_Row(spec, widget, is_length=is_length))
        return widget

    # ------------------------------------------------------------------ обработчики
    def _on_value(self, spec: ParamSpec, value: float, widget: SliderField) -> None:
        """Изменение числового параметра."""
        if spec.key.startswith("link.") and spec.key.endswith(".length"):
            selection = self._controller.selection
            if selection is not None and selection.role:
                axle = self._controller.project.axle(selection.role)
                self._controller.set_link_length(axle, spec.key.split(".")[1], value)
            return
        self._controller.set_value(spec.owner, spec.attr, value, merge_key=spec.merge_key or None)

    def _on_bool(self, spec: ParamSpec, checked: bool) -> None:
        """Изменение логического параметра."""
        self._controller.set_value(spec.owner, spec.attr, checked, merge_key=spec.merge_key or None)

    def _on_text(self, spec: ParamSpec, edit: QLineEdit) -> None:
        """Изменение текстового параметра."""
        self._controller.set_value(spec.owner, spec.attr, edit.text(), merge_key=None)

    def _on_enum(self, spec: ParamSpec, combo: QComboBox) -> None:
        """Изменение параметра-перечисления."""
        self._controller.set_value(spec.owner, spec.attr, combo.currentData(), merge_key=None)

    def _show_help(self, key: str) -> None:
        """Показывает пояснение параметра в отдельном окне."""
        title = tr(key.replace(".help", ".name")) if key.endswith(".help") else tr("insp.info")
        text = tr(key)
        box = QMessageBox(self)
        box.setWindowTitle(tr("insp.info"))
        box.setIcon(QMessageBox.Icon.Information)
        box.setTextFormat(Qt.TextFormat.RichText)
        box.setText(f"<b>{title}</b><br><br>{text}")
        box.setStandardButtons(QMessageBox.StandardButton.Ok)
        box.exec()

    # ------------------------------------------------------------------ обновление
    def refresh(self) -> None:
        """Подтягивает значения из модели (после правки, отмены, перетаскивания)."""
        for row in self._rows:
            spec = row.spec
            try:
                value: Any = spec.value()
            except (KeyError, AttributeError):
                continue
            widget = row.widget
            if isinstance(widget, SliderField):
                widget.set_value(float(value), emit=False)
            elif isinstance(widget, QCheckBox):
                widget.blockSignals(True)
                widget.setChecked(bool(value))
                widget.blockSignals(False)
            elif isinstance(widget, QLineEdit):
                if not widget.hasFocus():
                    widget.setText(str(value))
                widget.setEnabled(True)
            elif isinstance(widget, QComboBox):
                widget.blockSignals(True)
                index = widget.findData(str(value))
                if index >= 0:
                    widget.setCurrentIndex(index)
                widget.blockSignals(False)
            elif isinstance(widget, QLabel):
                units = self._controller.units
                if spec.unit.value != "plain":
                    widget.setText(f"{units.display(float(value), spec.unit)} {tr(units.suffix_key(spec.unit))}")
                else:
                    widget.setText(str(value))
