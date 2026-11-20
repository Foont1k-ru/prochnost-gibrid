"""Экспериментальная проверка явно выбранных осевых капсул."""
from __future__ import annotations

import logging
from collections.abc import Callable

from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.suspension_clearance import calculate_link_clearance, eligible_objects
from ..i18n import tr
from ..model.entities import Axle

LOG = logging.getLogger(__name__)
_EXTRA_LABELS = {'spring_capsule': 'Пружина (капсула)', 'damper_capsule': 'Амортизатор (капсула)',
                 'rod_capsule': 'Тяга коромысла (капсула)', 'rocker_capsule': 'Коромысло (две капсулы)',
                 'wheel_cylinder': 'Колесо (сплошной цилиндр)'}


def _label(axle: Axle, code: str) -> str:
    if code in _EXTRA_LABELS:
        return _EXTRA_LABELS[code]
    spec = axle.spec.link(code)
    if spec is None:
        raise ValueError('Неизвестная связь')
    return tr(spec.name_key)


class ClearanceDialog(QDialog):
    """Настройки временные; результат не сохраняется и не переносится в проект."""

    def __init__(self, axle: Axle, start: float, end: float, spacing: float,
                 is_current: Callable[[], bool], parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.axle, self.start, self.end, self.spacing = axle, start, end, spacing
        self.is_current = is_current
        self.setWindowTitle('Проверка условных капсул')
        self.resize(700, 650)
        layout = QVBoxLayout(self)
        intro = QLabel('Левая сторона, только выбранные формы и дискретные рассчитанные положения. '
                       'Задайте радиусы; размеры не берутся из модели автоматически. Рычаг и коромысло — '
                       'две капсулы, не пластина. Колесо — сплошной цилиндр, не шина.', self)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(240)
        entries = QWidget(scroll)
        entries_layout = QVBoxLayout(entries)
        self.links: dict[str, tuple[QCheckBox, QDoubleSpinBox]] = {}
        for code in eligible_objects(axle):
            label = _label(axle, code)
            row = QHBoxLayout()
            check = QCheckBox(label, entries)
            radius = QDoubleSpinBox(entries)
            radius.setDecimals(3)
            radius.setRange(0, 1000000)
            radius.setSpecialValueText('не задан')
            radius.setSuffix(' мм')
            radius.setAccessibleName(f'Радиус: {label}')
            row.addWidget(check, 1)
            row.addWidget(QLabel('Радиус', entries))
            row.addWidget(radius)
            entries_layout.addLayout(row)
            self.links[code] = (check, radius)
            check.toggled.connect(self._clear_result)
            radius.valueChanged.connect(self._clear_result)
        row = QHBoxLayout()
        row.addWidget(QLabel('Ширина цилиндра колеса', entries))
        self.wheel_width = QDoubleSpinBox(entries)
        self.wheel_width.setDecimals(3)
        self.wheel_width.setRange(0, 1000000)
        self.wheel_width.setSpecialValueText('не задана')
        self.wheel_width.setSuffix(' мм')
        row.addWidget(self.wheel_width)
        entries_layout.addLayout(row)
        self.wheel_width.valueChanged.connect(self._clear_result)
        scroll.setWidget(entries)
        layout.addWidget(scroll)
        row = QHBoxLayout()
        row.addWidget(QLabel('Требуемый запас между формами', self))
        self.margin = QDoubleSpinBox(self)
        self.margin.setRange(0, 1000000)
        self.margin.setDecimals(3)
        self.margin.setSuffix(' мм')
        row.addWidget(self.margin)
        row.addStretch()
        layout.addLayout(row)
        self.margin.valueChanged.connect(self._clear_result)
        self.run_button = QPushButton('Рассчитать выбранные пары', self)
        self.run_button.clicked.connect(self.run_check)
        layout.addWidget(self.run_button)
        self.output = QTextEdit(self)
        self.output.setReadOnly(True)
        self.output.setAcceptRichText(False)
        layout.addWidget(self.output, 1)
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Close, self)
        buttons.button(QDialogButtonBox.StandardButton.Close).setText('Закрыть')
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        self._clear_result()

    def _clear_result(self, *_args: object) -> None:
        if not self.is_current():
            self.invalidate()
            return
        self.output.setPlainText('Не рассчитано. Выберите не менее двух форм, задайте радиусы и ширину колеса при выборе.')

    def invalidate(self) -> None:
        self.run_button.setEnabled(False)
        self.output.setPlainText('Проект или параметры хода изменились. Результат устарел; закройте окно и откройте заново.')

    def run_check(self) -> None:
        if not self.is_current():
            self.invalidate()
            return
        radii = {code: radius.value() for code, (check, radius) in self.links.items() if check.isChecked()}
        try:
            sweep = calculate_link_clearance(self.axle, self.start, self.end, self.spacing, radii, self.margin.value(),
                                             wheel_width_mm=self.wheel_width.value())
        except (ValueError, KeyError, ArithmeticError) as error:
            self.output.setPlainText(f'Не рассчитано: {error}. Ничего не проверено.')
            return
        except Exception:
            LOG.exception('Ошибка проверки условных капсул')
            self.output.setPlainText('Ошибка расчёта. Ничего не проверено.')
            return
        if not self.is_current():
            self.invalidate()
            return
        labels = {code: _label(self.axle, code) for code in self.links}
        omitted = ', '.join(labels[code] for code in sweep.omitted) or 'нет'
        wheel_info = f'. Ширина цилиндра колеса: {self.wheel_width.value():g} мм.' if 'wheel_cylinder' in radii else ''
        lines = [f'Левая сторона, сетка {self.start:g}…{self.end:g} мм, максимальный шаг {self.spacing:g} мм.',
                 'Радиусы: ' + ', '.join(f'{labels[code]} — {radii[code]:g} мм' for code in sweep.selected) + wheel_info,
                 f'Заданный запас: {self.margin.value():g} мм. Невыбранные формы не проверены: {omitted}.',
                 'Сравниваются только пары выбранных форм; внутри одной формы проверок нет.',
                 'Кулак, кузов, привод и реальные детали не проверены; цилиндр — не настоящая шина.',
                 'Известные соединённые пары исключены целиком; даже вдали от шарнира они не проверены.',
                 'Отрицательный зазор с цилиндром не означает глубину проникновения.',
                 'Между точками сетки движение и столкновения не проверены. Не является разрешением на изготовление.', '']
        status = {'overlap': 'наложение', 'touch': 'касание', 'low_clearance': 'меньше запаса',
                  'limit': 'у границы запаса', 'clear': 'больше запаса', 'unknown_no_pose': 'нет решения позы',
                  'unknown_geometry': 'нет корректной геометрии',
                  'excluded_shared_point': 'не проверено: известное соединение (вся пара исключена)'}
        all_pairs = [pair for sample in sweep.samples for pair in sample.pairs]
        measured = [pair for pair in all_pairs if pair.measurement is not None]
        lines.append(f'Проверено пар на позах: {len(measured)} из {len(all_pairs)}; '
                     f'не проверено: {len(all_pairs) - len(measured)}.')
        lines.append('Состояния на позах: ' + ', '.join(
            f'{status[code]} — {sum(pair.status == code for pair in all_pairs)}'
            for code in ('overlap', 'touch', 'low_clearance', 'limit', 'clear')) + '.')
        if measured:
            lines.append(f'Минимальный условный зазор на решённых позах: '
                         f'{min(pair.measurement.clearance_mm for pair in measured if pair.measurement is not None):.3f} мм.')
        else:
            lines.append('Нет измеренных пар; минимальный зазор не определён.')
        lines.append('')
        for sample in sweep.samples:
            failure = f' (отказ кинематики: {sample.pose_error})' if sample.pose_error else ''
            lines.append(f'Ход {sample.travel_mm:+.2f} мм:{failure}')
            for pair in sample.pairs:
                text = f'  {labels[pair.first]} / {labels[pair.second]}: {status[pair.status]}'
                if pair.measurement is not None:
                    text += (f'; зазор {pair.measurement.clearance_mm:.3f} мм '
                             f'(ветви {pair.first_pivot}, {pair.second_pivot})')
                elif pair.detail:
                    text += f'; {pair.detail}'
                lines.append(text)
        self.output.setPlainText('\n'.join(lines))
