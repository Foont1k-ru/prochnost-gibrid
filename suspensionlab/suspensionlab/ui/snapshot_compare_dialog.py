"""Сравнение геометрии и параметров с сохранённым снимком."""
from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDialog,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import autosave_path
from ..core.snapshot_compare import (
    LinkComparison,
    PointComparison,
    SnapshotComparison,
    compare_projects,
    max_link_delta,
    max_point_displacement,
)
from ..core.snapshot_parameters import ParameterComparison, compare_parameters
from ..export.csv_report import CSVReport, write_csv_report
from ..i18n import tr
from ..model.point_csv import PointRecord
from ..model.snapshot_restore import prepare_snapshot
from .controller import AppController, Selection
from .table_export import make_report

STATUSES = ("all", "changed", "unchanged", "added", "removed", "incompatible", "invalid")
POINT_COLUMNS = ("axle", "code", "name", "status", "old_rep", "new_rep", "old_x", "old_y", "old_z",
                 "new_x", "new_y", "new_z", "dx", "dy", "dz", "distance")
LINK_COLUMNS = ("axle", "code", "name", "status", "old_length", "new_length", "length_delta")
PARAM_COLUMNS = ("axle", "component", "code", "name", "status", "unit", "old_value", "new_value", "value_delta")


def _number(value: float | None) -> str:
    if value is None:
        return "—"
    if not math.isfinite(value):
        return tr("snapshot_compare.nonfinite")
    return repr(value)


def _coordinates(point: PointRecord | None) -> tuple[str, str, str]:
    return tuple(_number(v) for v in point.xyz) if point else ("—", "—", "—")  # type: ignore[return-value]


def _representation(point: PointRecord | None) -> str:
    if point is None:
        return "—"
    key = {"mirrored": "mirror", "explicit_side": "explicit", "single": "single"}[point.representation]
    return tr("point_table." + key)


def _scalar(value: str | bool | int | float | None) -> str:
    if value is None:
        return tr("snapshot_compare.nonfinite")
    if isinstance(value, bool):
        return tr("export.yes") if value else tr("export.no")
    return str(value) if isinstance(value, str) else repr(value)


class SnapshotCompareDialog(QDialog):
    """Показывает сравнение только для чтения; при изменении модели блокируется."""

    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.selection: Selection | None = None
        self._stale = False
        self._result: SnapshotComparison | None = None
        self._snapshot_hash = ""
        self._point_rows: tuple[tuple[str, ...], ...] = ()
        self._link_rows: tuple[tuple[str, ...], ...] = ()
        self._param_rows: tuple[tuple[str, ...], ...] = ()
        self._parameters: tuple[ParameterComparison, ...] = ()
        self.setWindowTitle(tr("snapshot_compare.title"))
        self.resize(1100, 690)
        layout = QVBoxLayout(self)
        note = QLabel(tr("snapshot_compare.notice"))
        note.setWordWrap(True)
        layout.addWidget(note)
        self._snapshot = QComboBox(self)
        for index, snapshot in enumerate(controller.project.snapshots):
            self._snapshot.addItem(f"{index + 1}. {snapshot.name}", index)
        layout.addWidget(self._snapshot)
        self._context = QLabel(self)
        self._context.setWordWrap(True)
        layout.addWidget(self._context)
        filters = QHBoxLayout()
        self._role = QComboBox(self)
        for role in ("all", "front", "rear", "vehicle"):
            self._role.addItem(tr(f"snapshot_compare.role_{role}"), role)
        self._filter = QComboBox(self)
        for status in STATUSES:
            self._filter.addItem(tr(f"snapshot_compare.filter_{status}"), status)
        filters.addWidget(self._role)
        filters.addWidget(self._filter)
        filters.addStretch(1)
        self._maximum = QPushButton(self)
        self._maximum.clicked.connect(self._select_maximum)
        filters.addWidget(self._maximum)
        layout.addLayout(filters)
        self._detail = QLabel(self)
        self._detail.setWordWrap(True)
        layout.addWidget(self._detail)
        self._count = QLabel(self)
        layout.addWidget(self._count)
        self._tabs = QTabWidget(self)
        self._points = self._make_table(POINT_COLUMNS)
        self._links = self._make_table(LINK_COLUMNS)
        self._params = self._make_table(PARAM_COLUMNS)
        self._tabs.addTab(self._points, tr("snapshot_compare.points"))
        self._tabs.addTab(self._links, tr("snapshot_compare.links"))
        self._tabs.addTab(self._params, tr("snapshot_compare.parameters"))
        layout.addWidget(self._tabs, 1)
        self._state = QLabel(self)
        self._state.setWordWrap(True)
        layout.addWidget(self._state)
        buttons = QHBoxLayout()
        self._choose = QPushButton(tr("snapshot_compare.choose"))
        self._choose.clicked.connect(self._select)
        buttons.addWidget(self._choose)
        self._export = QPushButton(tr("snapshot_compare.export"))
        self._export.clicked.connect(self._export_current)
        buttons.addWidget(self._export)
        buttons.addStretch(1)
        close = QPushButton(tr("point_table.close"))
        close.clicked.connect(self.reject)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self._snapshot.currentIndexChanged.connect(self._load)
        self._role.currentIndexChanged.connect(self._apply_filter)
        self._filter.currentIndexChanged.connect(self._apply_filter)
        self._tabs.currentChanged.connect(self._apply_filter)
        self._points.currentCellChanged.connect(self._update_choose)
        self._links.currentCellChanged.connect(self._update_choose)
        self._params.currentCellChanged.connect(self._update_choose)
        controller.modelChanged.connect(self._invalidate)
        controller.projectReplaced.connect(self._invalidate)
        self._load()

    @staticmethod
    def _make_table(columns: tuple[str, ...]) -> QTableWidget:
        table = QTableWidget(0, len(columns))
        table.setHorizontalHeaderLabels([tr(f"snapshot_compare.column_{name}") for name in columns])
        table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        return table

    def _load(self) -> None:
        if self._stale:
            return
        self._result = None
        self._point_rows = ()
        self._link_rows = ()
        self._param_rows = ()
        self._parameters = ()
        self._params.setRowCount(0)
        self._points.setRowCount(0)
        self._links.setRowCount(0)
        index = self._snapshot.currentData()
        if not isinstance(index, int) or not 0 <= index < len(self.controller.project.snapshots):
            self._context.setText("")
            self._state.setText(tr("snapshot_compare.no_snapshot"))
            self._apply_filter()
            return
        snapshot = self.controller.project.snapshots[index]
        try:
            reference = prepare_snapshot(snapshot.data)
            selected = {key: snapshot.data[key] for key in ("schema_version", "meta", "vehicle", "front_axle", "rear_axle")}
            payload = json.dumps(selected, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False)
            self._snapshot_hash = hashlib.sha256(payload.encode("utf-8")).hexdigest()
            result = compare_projects(reference, self.controller.project)
            parameters = compare_parameters(reference, self.controller.project)
        except (ValueError, TypeError, KeyError, OverflowError, ArithmeticError, RecursionError):
            self._context.setText("")
            self._state.setText(tr("snapshot_compare.bad_snapshot"))
            self._apply_filter()
            return
        self._result = result
        self._parameters = parameters
        current = self.controller.project
        self._context.setText(tr("snapshot_compare.types", old_front=reference.front.type_code,
                                 new_front=current.front.type_code, old_rear=reference.rear.type_code,
                                 new_rear=current.rear.type_code))
        self._state.setText(tr("snapshot_compare.ready"))
        point_rows = []
        for row in result.points:
            point = row.new or row.old
            name = tr(point.name_key) if point and point.name_key else row.code
            delta = tuple(_number(v) for v in row.delta) if row.delta is not None else ("—", "—", "—")
            point_rows.append((tr(f"tree.{row.role}"), row.code, name, tr(f"snapshot_compare.status_{row.status}"),
                               _representation(row.old), _representation(row.new), *_coordinates(row.old),
                               *_coordinates(row.new), *delta, _number(row.distance)))
        link_rows = []
        for link_row in result.links:
            axle = current.axle(link_row.role) if link_row.new_exists else reference.axle(link_row.role)
            spec = axle.spec.link(link_row.code)
            link_rows.append((tr(f"tree.{link_row.role}"), link_row.code, tr(spec.name_key) if spec else link_row.code,
                              tr(f"snapshot_compare.status_{link_row.status}"), _number(link_row.old_length),
                              _number(link_row.new_length), _number(link_row.delta)))
        param_rows = []
        for param in parameters:
            param_rows.append((tr(f"tree.{param.role}"), tr(f"tree.{param.component}"), param.code,
                               tr(param.name_key), tr(f"snapshot_compare.status_{param.status}"), param.unit,
                               _scalar(param.old), _scalar(param.new), _number(param.delta)))
        self._point_rows, self._link_rows, self._param_rows = tuple(point_rows), tuple(link_rows), tuple(param_rows)
        self._fill(self._points, self._point_rows)
        self._fill(self._links, self._link_rows)
        self._fill(self._params, self._param_rows)
        self._apply_filter()

    @staticmethod
    def _fill(table: QTableWidget, rows: tuple[tuple[str, ...], ...]) -> None:
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for col, text in enumerate(row):
                item = QTableWidgetItem(text)
                item.setToolTip(text)
                table.setItem(r, col, item)

    def _active(self) -> tuple[QTableWidget, tuple[PointComparison | LinkComparison | ParameterComparison, ...]]:
        index = self._tabs.currentIndex()
        if index == 0:
            return self._points, self._result.points if self._result else ()
        if index == 1:
            return self._links, self._result.links if self._result else ()
        return self._params, self._parameters

    def _apply_filter(self, *_args: object) -> None:
        result = self._result
        self._detail.setText(tr("snapshot_compare.parameter_scope") if self._tabs.currentIndex() == 2 else "")
        self._detail.setVisible(self._tabs.currentIndex() == 2)
        if result:
            for i, point in enumerate(result.points):
                self._points.setRowHidden(i, self._is_hidden(point.role, point.status))
            for i, link in enumerate(result.links):
                self._links.setRowHidden(i, self._is_hidden(link.role, link.status))
            for i, param in enumerate(self._parameters):
                self._params.setRowHidden(i, self._is_hidden(param.role, param.status))
        table, rows = self._active()
        visible = sum(not table.isRowHidden(i) for i in range(len(rows)))
        self._count.setText(tr("snapshot_compare.count", visible=visible, total=len(rows)))
        index = (max_point_displacement(result.points) if self._tabs.currentIndex() == 0 else
                 max_link_delta(result.links) if self._tabs.currentIndex() == 1 else None) if result else None
        self._maximum.setEnabled(index is not None and not self._stale)
        if index is None or result is None:
            self._maximum.setText(tr("snapshot_compare.max_none"))
        elif self._tabs.currentIndex() == 0:
            point = result.points[index]
            self._maximum.setText(tr("snapshot_compare.max_point", role=tr(f"tree.{point.role}"), code=point.code, value=_number(point.distance)))
        else:
            link = result.links[index]
            self._maximum.setText(tr("snapshot_compare.max_link", role=tr(f"tree.{link.role}"), code=link.code, value=_number(abs(link.delta or 0.0))))
        self._export.setEnabled(result is not None and not self._stale)
        self._update_choose()

    def _is_hidden(self, role: str, status: str) -> bool:
        return self._role.currentData() not in ("all", role) or self._filter.currentData() not in ("all", status)

    def _select_maximum(self) -> None:
        if self._result is None or self._stale or self._tabs.currentIndex() == 2:
            return
        index = (max_point_displacement(self._result.points) if self._tabs.currentIndex() == 0 else
                 max_link_delta(self._result.links))
        if index is not None:
            table, _ = self._active()
            if table.isRowHidden(index):
                self._role.setCurrentIndex(0)
                self._filter.setCurrentIndex(0)
            table.setCurrentCell(index, 0)
            item = table.item(index, 0)
            if item is not None:
                table.scrollToItem(item)

    def _update_choose(self, *_args: object) -> None:
        table, rows = self._active()
        index = table.currentRow()
        enabled = not self._stale and 0 <= index < len(rows) and not table.isRowHidden(index)
        if enabled:
            row = rows[index]
            if isinstance(row, PointComparison):
                enabled = row.new is not None
            elif isinstance(row, LinkComparison):
                enabled = row.new_exists
            else:
                enabled = row.selectable
        self._choose.setEnabled(enabled)

    def _select(self) -> None:
        if not self._choose.isEnabled():
            return
        table, rows = self._active()
        row = rows[table.currentRow()]
        if isinstance(row, ParameterComparison):
            self.selection = Selection(row.component, "" if row.role == "vehicle" else row.role)
        else:
            self.selection = Selection("point" if isinstance(row, PointComparison) else "link", row.role, row.code)
        self.accept()

    def _invalidate(self) -> None:
        self._stale = True
        self._snapshot.setEnabled(False)
        self._state.setText(tr("snapshot_compare.stale"))
        self._apply_filter()

    def _report(self) -> CSVReport:
        if self._stale or self._result is None:
            raise ValueError(tr("export.no_results"))
        index = self._snapshot.currentData()
        snapshot = self.controller.project.snapshots[index]
        result = self._result
        tab = self._tabs.currentIndex()
        report_columns: tuple[str, ...]
        if tab == 0:
            display_rows = self._point_rows
            data: tuple[PointComparison | LinkComparison | ParameterComparison, ...] = result.points
            report_columns = POINT_COLUMNS
            title = "points"
        elif tab == 1:
            display_rows = self._link_rows
            data = result.links
            report_columns = LINK_COLUMNS
            title = "links"
        else:
            display_rows = self._param_rows
            data = self._parameters
            report_columns = PARAM_COLUMNS
            title = "parameters"
        columns = (tr("snapshot_compare.column_old_type"), tr("snapshot_compare.column_new_type"),
                   tr("snapshot_compare.column_status_code"),
                   *(tr(f"snapshot_compare.column_{name}") for name in report_columns))
        rows = tuple((row.old_type or "—", row.new_type or "—", row.status, *display)
                     for row, display in zip(data, display_rows, strict=True))
        parameters = [(tr("snapshot_compare.snapshot_name"), snapshot.name),
                      (tr("snapshot_compare.snapshot_index"), str(index + 1)),
                      (tr("snapshot_compare.snapshot_hash"), self._snapshot_hash),
                      (tr("snapshot_compare.scope_label"), tr("snapshot_compare.notice"))]
        if tab == 2:
            parameters.append((tr("snapshot_compare.parameter_scope_label"), tr("snapshot_compare.parameter_scope")))
        return make_report(self.controller, tr("snapshot_compare." + title), parameters, columns, rows,
                           precision_text=tr("snapshot_compare.parameter_precision" if tab == 2 else
                                             "snapshot_compare.precision"), allow_empty_rows=True)

    def _export_current(self) -> None:
        try:
            report = self._report()
        except (ValueError, UnicodeError, ArithmeticError, TypeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
            return
        selected, _ = QFileDialog.getSaveFileName(self, tr("export.title"), "", tr("export.filter"))
        if not selected:
            return
        path = Path(selected)
        if path.suffix.lower() != ".csv":
            path = path.with_name(path.name + ".csv")
        try:
            if self._stale:
                raise ValueError(tr("snapshot_compare.stale"))
            protected = [autosave_path()]
            if self.controller.project.path:
                protected.append(Path(self.controller.project.path))
            if any(path.resolve() == target.resolve() for target in protected):
                raise ValueError(tr("point_import.export_project"))
            write_csv_report(report, path)
        except (OSError, UnicodeError, ValueError, RuntimeError) as error:
            QMessageBox.warning(self, tr("export.error_title"), tr("export.error", reason=str(error)))
