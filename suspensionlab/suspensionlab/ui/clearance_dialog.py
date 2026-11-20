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
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from ..core.suspension_clearance import calculate_link_clearance, eligible_links
from ..i18n import tr
from ..model.entities import Axle

LOG = logging.getLogger(__name__)


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
        intro = QLabel('Левая сторона, только выбранные связи и дискретные рассчитанные положения. '
                       'Задайте радиусы условных капсул; размеры реальных деталей автоматически не определяются. '
                       'Двухопорный рычаг — две капсулы, не пластина. Капсулы имеют сферические концы.', self)
        intro.setWordWrap(True)
        layout.addWidget(intro)
        self.links: dict[str, tuple[QCheckBox, QDoubleSpinBox]] = {}
        for code in eligible_links(axle):
            spec = axle.spec.link(code)
            assert spec is not None
            row = QHBoxLayout()
            check = QCheckBox(tr(spec.name_key), self)
            radius = QDoubleSpinBox(self)
            radius.setDecimals(3)
            radius.setRange(0, 1000000)
            radius.setSpecialValueText('не задан')
            radius.setSuffix(' мм')
            radius.setAccessibleName(f'Радиус: {tr(spec.name_key)}')
            row.addWidget(check, 1)
            row.addWidget(QLabel('Радиус', self))
            row.addWidget(radius)
            layout.addLayout(row)
            self.links[code] = (check, radius)
            check.toggled.connect(self._clear_result)
            radius.valueChanged.connect(self._clear_result)
        row = QHBoxLayout()
        row.addWidget(QLabel('Требуемый запас между капсулами', self))
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
        self.output.setPlainText('Не рассчитано. Выберите не менее двух связей и задайте каждой положительный радиус.')

    def invalidate(self) -> None:
        self.run_button.setEnabled(False)
        self.output.setPlainText('Проект или параметры хода изменились. Результат устарел; закройте окно и откройте заново.')

    def run_check(self) -> None:
        if not self.is_current():
            self.invalidate()
            return
        radii = {code: radius.value() for code, (check, radius) in self.links.items() if check.isChecked()}
        try:
            sweep = calculate_link_clearance(self.axle, self.start, self.end, self.spacing, radii, self.margin.value())
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
        labels = {code: tr(self.axle.spec.link(code).name_key) for code in self.links}  # type: ignore[union-attr]
        omitted = ', '.join(labels[code] for code in sweep.omitted) or 'нет'
        lines = [f'Левая сторона, сетка {self.start:g}…{self.end:g} мм, максимальный шаг {self.spacing:g} мм.',
                 'Радиусы: ' + ', '.join(f'{labels[code]} — {radii[code]:g} мм' for code in sweep.selected),
                 f'Заданный запас: {self.margin.value():g} мм. Невыбранные связи не проверены: {omitted}.',
                 'Сравниваются только пары выбранных связей; внутри одной связи проверок нет.',
                 'Колесо, кулак, кузов, пружина, амортизатор, тяга и коромысло, привод и реальные детали не проверены.',
                 'Между точками сетки движение и столкновения не проверены. Не является разрешением на изготовление.', '']
        status = {'overlap': 'наложение', 'touch': 'касание', 'low_clearance': 'меньше запаса',
                  'limit': 'у границы запаса', 'clear': 'больше запаса', 'unknown_no_pose': 'нет решения позы',
                  'unknown_geometry': 'нет корректной геометрии',
                  'excluded_shared_point': 'не проверено: общий шарнир (вся пара исключена)'}
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
                lines.append(text)
        self.output.setPlainText('\n'.join(lines))
