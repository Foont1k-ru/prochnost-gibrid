"""Дерево проекта: навигация по автомобилю, осям, точкам и узлам.

Дерево строится по реестру типов подвески: набор групп и точек берётся
из описания типа, поэтому новый тип появляется в дереве автоматически.
"""

from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ...i18n import tr
from ...model.entities import Axle, Project
from ..controller import AppController, Selection

#: Роль данных для хранения выбора в элементе дерева.
_ROLE_SELECTION = Qt.ItemDataRole.UserRole + 1


class ProjectTree(QWidget):
    """Дерево проекта с выбором элемента."""

    selectionRequested = Signal(object)

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._controller = controller
        self._tree = QTreeWidget(self)
        self._tree.setHeaderHidden(True)
        self._tree.setAlternatingRowColors(False)
        self._tree.setUniformRowHeights(True)
        self._tree.itemSelectionChanged.connect(self._on_selection_changed)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._tree)

        controller.projectReplaced.connect(self.rebuild)
        controller.selectionChanged.connect(self._sync_selection)
        self.rebuild()

    # ------------------------------------------------------------------ построение
    def rebuild(self) -> None:
        """Перестраивает дерево по текущему проекту."""
        expanded = {item.text(0) for i in range(self._tree.topLevelItemCount())
                    if (item := self._tree.topLevelItem(i)) is not None}
        self._tree.blockSignals(True)
        self._tree.clear()
        project = self._controller.project

        root = QTreeWidgetItem([tr("tree.project")])
        root.setData(0, _ROLE_SELECTION, Selection("project"))
        self._tree.addTopLevelItem(root)

        vehicle = QTreeWidgetItem([tr("tree.vehicle")])
        vehicle.setData(0, _ROLE_SELECTION, Selection("vehicle"))
        root.addChild(vehicle)

        root.addChild(self._build_axle(project, "front", project.front))
        root.addChild(self._build_axle(project, "rear", project.rear))

        snapshots = QTreeWidgetItem([tr("tree.snapshots")])
        snapshots.setData(0, _ROLE_SELECTION, Selection("snapshots"))
        root.addChild(snapshots)

        root.setExpanded(True)
        vehicle.setExpanded(False)
        self._tree.blockSignals(False)
        if not expanded:
            self._expand_default(root)
        self._sync_selection(self._controller.selection)

    def _expand_default(self, root: QTreeWidgetItem) -> None:
        """Раскрывает узлы первого уровня (оси) при первом построении."""
        for index in range(root.childCount()):
            child = root.child(index)
            if child is not None and child.text(0) in (tr("tree.front"), tr("tree.rear")):
                child.setExpanded(True)

    def _build_axle(self, project: Project, role: str, axle: Axle) -> QTreeWidgetItem:
        """Строит ветку оси: точки, рычаги и узлы."""
        title = tr("tree.front") if role == "front" else tr("tree.rear")
        item = QTreeWidgetItem([title])
        item.setData(0, _ROLE_SELECTION, Selection("axle", role))
        item.setToolTip(0, tr(axle.spec.name_key))

        points_group = QTreeWidgetItem([tr("tree.points")])
        for code in axle.point_codes():
            if code not in axle.hardpoints:
                continue
            point_spec = axle.spec.point(code)
            label = tr(point_spec.name_key) if point_spec is not None else code
            if point_spec is not None and point_spec.side != "center":
                label = f"{label} ({tr(f'hp.side.{point_spec.side}')})"
            point_item = QTreeWidgetItem([label])
            point_item.setData(0, _ROLE_SELECTION, Selection("point", role, code))
            point_item.setToolTip(0, tr(point_spec.help_key) if point_spec is not None else code)
            points_group.addChild(point_item)
        item.addChild(points_group)

        links_group = QTreeWidgetItem([tr("tree.links")])
        for link_spec in axle.spec.links:
            child = QTreeWidgetItem([tr(link_spec.name_key)])
            child.setData(0, _ROLE_SELECTION, Selection("link", role, link_spec.code))
            child.setToolTip(0, tr(link_spec.help_key))
            links_group.addChild(child)
        item.addChild(links_group)

        for kind, key in (
            ("wheel", "tree.wheel"),
            ("spring", "tree.spring"),
            ("damper", "tree.damper"),
            ("arb", "tree.arb"),
            ("bump_stop", "tree.bump_stop"),
            ("steering", "tree.steering"),
            ("drivetrain", "tree.drivetrain"),
            ("setup", "tree.setup"),
            ("travel", "tree.travel"),
        ):
            if kind == "steering" and not axle.spec.supports_steering:
                continue
            child = QTreeWidgetItem([tr(key)])
            child.setData(0, _ROLE_SELECTION, Selection(kind, role))
            item.addChild(child)
        return item

    # ------------------------------------------------------------------ выбор
    def _on_selection_changed(self) -> None:
        """Пользователь выбрал элемент дерева."""
        items = self._tree.selectedItems()
        if not items:
            return
        selection = items[0].data(0, _ROLE_SELECTION)
        if isinstance(selection, Selection):
            self.selectionRequested.emit(selection)

    def _sync_selection(self, selection: Selection | None) -> None:
        """Подсвечивает элемент, выбранный извне (например, на схеме)."""
        self._tree.blockSignals(True)
        try:
            if selection is None:
                self._tree.clearSelection()
                return
            for item in self._iterate(self._tree.invisibleRootItem()):
                if item.data(0, _ROLE_SELECTION) == selection:
                    self._tree.setCurrentItem(item)
                    parent = item.parent()
                    while parent is not None:
                        parent.setExpanded(True)
                        parent = parent.parent()
                    break
        finally:
            self._tree.blockSignals(False)

    def _iterate(self, parent: QTreeWidgetItem):
        """Обход всех элементов дерева."""
        for index in range(parent.childCount()):
            child = parent.child(index)
            if child is not None:
                yield child
                yield from self._iterate(child)

    # ------------------------------------------------------------------ доступ
    def tree_widget(self) -> QTreeWidget:
        """Сам виджет дерева (для тестов и настройки вида)."""
        return self._tree

    def select_in_axle(self, role: str) -> None:
        """Выбирает ветку оси."""
        self._controller.select(Selection("axle", role))
