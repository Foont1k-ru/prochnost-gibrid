"""Две силовые точки: явная предварительная оценка жёсткости кандидата."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QLineEdit,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ..core.spring_rate_estimate import SpringRateEstimate, SpringRatePoints
from ..i18n import tr

MAX_CANDIDATE_RATE = 10000.0


class SpringRateDialog(QDialog):
    def __init__(self, free_length_text: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle(tr("spring_rate.title"))
        self.resize(650, 460)
        notice = QLabel(tr("spring_rate.notice"), self)
        notice.setWordWrap(True)
        self._fields = {key: QLineEdit(self) for key in ("free", "length1", "force1", "length2", "force2")}
        self._fields["free"].setText(free_length_text)
        self._fields["free"].setReadOnly(True)
        form = QFormLayout()
        for key, edit in self._fields.items():
            edit.setPlaceholderText(tr("spring_rate.required"))
            form.addRow(tr(f"spring_rate.{key}"), edit)
            edit.textChanged.connect(self._update)
        self._result = QLabel(self)
        self._result.setWordWrap(True)
        self._buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        self._apply = self._buttons.button(QDialogButtonBox.StandardButton.Ok)
        self._apply.setText(tr("spring_rate.apply"))
        self._buttons.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("spring_rate.cancel"))
        self._buttons.accepted.connect(self.accept)
        self._buttons.rejected.connect(self.reject)
        layout = QVBoxLayout(self)
        content = QWidget(self)
        content_layout = QVBoxLayout(content)
        content_layout.addWidget(notice)
        content_layout.addLayout(form)
        content_layout.addWidget(self._result)
        content_layout.addStretch(1)
        scroll = QScrollArea(self)
        scroll.setWidgetResizable(True)
        scroll.setWidget(content)
        layout.addWidget(scroll, 1)
        layout.addWidget(self._buttons)
        self.estimate: SpringRateEstimate | None = None
        self.points: SpringRatePoints | None = None
        self._update()

    def _update(self, *_args: object) -> None:
        self.estimate = None
        self.points = None
        self._apply.setEnabled(False)
        try:
            def parse(key: str) -> float:
                return float(self._fields[key].text().strip().replace(",", "."))
            free = parse("free")
            if not 0 < free <= 2000:
                raise ValueError
            points = SpringRatePoints(parse("length1"), parse("force1"), parse("length2"), parse("force2"))
            result = points.estimate(free)
            if result.rate_n_mm > MAX_CANDIDATE_RATE:
                raise ValueError
        except (ValueError, OverflowError):
            self._result.setText(tr("spring_rate.invalid", maximum=MAX_CANDIDATE_RATE))
            return
        self.estimate = result
        self.points = points
        self._result.setText(tr("spring_rate.preview", rate=repr(result.rate_n_mm),
                                zero=repr(result.extrapolated_zero_length_mm),
                                force1=repr(result.model_force_1_n), force2=repr(result.model_force_2_n)))
        self._apply.setEnabled(True)
