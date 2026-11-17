"""Просмотр условных рычагов схемы, без проектирования или записи CAD."""
from __future__ import annotations

import math

from PySide6.QtCore import QPointF, Qt
from PySide6.QtGui import QColor, QPainter, QPaintEvent, QPen, QPolygonF
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..core.niva_arm_mesh import schematic_mesh
from ..i18n import tr
from ..model.niva_arm_views import ARM_KEYS, ArmView, make_niva_arm_view
from .canvas.cad_preview import CadPreview
from .controller import AppController


class ArmPlan(QWidget):
    def __init__(self, axes: tuple[int, int], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.axes = axes
        self.view: ArmView | None = None
        self.path: tuple[tuple[float, float, float], ...] | None = None
        self.setMinimumSize(360, 300)

    def set_view(self, view: ArmView | None, path: tuple[tuple[float, float, float], ...] | None = None) -> None:
        self.view = view
        self.path = path if view is not None else None
        self.update()

    def paintEvent(self, event: QPaintEvent) -> None:  # noqa: N802
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), self.palette().base())
        if self.view is None:
            painter.setPen(self.palette().text().color())
            painter.drawText(self.rect(), int(Qt.AlignmentFlag.AlignCenter), tr('niva_arms.empty'))
            return
        a, b = self.axes
        points = self.view.points
        extent = (*points, *(self.path or ()))
        first, second = [p[a] for p in extent], [p[b] for p in extent]
        scale = min(max(self.width()-140, 1)/max(max(first)-min(first), 1.),
                    max(self.height()-100, 1)/max(max(second)-min(second), 1.))
        center_a, center_b = (max(first)+min(first))/2, (max(second)+min(second))/2
        def map_point(p: tuple[float, float, float]) -> QPointF:
            return QPointF(self.width()/2 + (p[a]-center_a)*scale,
                           self.height()/2 - (p[b]-center_b)*scale)
        painter.setPen(QPen(QColor('#387fa3'), 4))
        if self.path is not None:
            painter.drawPolyline(QPolygonF([map_point(point) for point in self.path]))
        else:
            for start, end in self.view.segments:
                painter.drawLine(map_point(start), map_point(end))
        painter.setPen(QPen(self.palette().text().color(), 1.5))
        for point, code, kind in zip(points, self.view.point_codes, self.view.joint_kinds, strict=True):
            pos = map_point(point)
            painter.setBrush(self.palette().base())
            painter.drawEllipse(pos, 6, 6)
            if kind == 'ball':
                painter.drawEllipse(pos, 3, 3)
            else:
                painter.drawLine(pos + QPointF(-9, 0), pos + QPointF(9, 0))
            painter.setBrush(self.palette().text())
            painter.drawText(pos + QPointF(8, -8), code)
        painter.drawText(10, 22, tr('niva_arms.axis', horizontal='XYZ'[a], vertical='XYZ'[b]))


class NivaArmsDialog(QDialog):
    def __init__(self, controller: AppController, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.controller = controller
        self.setWindowTitle(tr('niva_arms.title'))
        self.setWindowModality(Qt.WindowModality.NonModal)
        self.resize(780, 720)
        layout = QVBoxLayout(self)
        warning = QLabel(tr('niva_arms.warning'), self)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        form = QFormLayout()
        self._arm = QComboBox(self)
        for key in ARM_KEYS:
            self._arm.addItem(tr(f'niva_arms.{key}'), key)
        form.addRow(tr('niva_arms.choose'), self._arm)
        layout.addLayout(form)
        self._status = QLabel(self)
        self._status.setWordWrap(True)
        layout.addWidget(self._status)
        self._tabs = QTabWidget(self)
        self._plans = [ArmPlan(axes, self._tabs) for axes in ((0, 1), (0, 2), (1, 2))]
        for widget, label in zip(self._plans, ('XY', 'XZ', 'YZ'), strict=True):
            self._tabs.addTab(widget, label)
        self._three_d = CadPreview(self._tabs, empty_text_key='niva_arms.empty')
        self._tabs.addTab(self._three_d, tr('niva_arms.tab_3d'))
        layout.addWidget(self._tabs, 1)
        self._reset = QPushButton(tr('weldment_3d.reset'), self)
        self._reset.clicked.connect(self._three_d.reset_camera)
        layout.addWidget(self._reset)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._arm.currentIndexChanged.connect(self._refresh)
        controller.modelChanged.connect(self._refresh)
        controller.projectReplaced.connect(self._refresh)
        self._refresh()

    def _refresh(self, *_args: object) -> None:
        # Clear first: invalid input must never leave a stale picture visible.
        for plan in self._plans:
            plan.set_view(None)
        self._three_d.set_mesh(None)
        try:
            view = make_niva_arm_view(self.controller.project, str(self._arm.currentData()))
            mesh = schematic_mesh(view)
        except (ValueError, TypeError, OverflowError, ArithmeticError):
            self._status.setText(tr('niva_arms.invalid'))
            return
        for plan in self._plans:
            plan.set_view(view)
        self._three_d.set_mesh(mesh)
        lengths = ', '.join(f'{math.dist(a, b):.2f}' for a, b in view.segments)
        self._status.setText(tr('niva_arms.lengths', lengths=lengths))
