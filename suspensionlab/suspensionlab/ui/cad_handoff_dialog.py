"""Явное подтверждение перехода: сведения прокручиваются, предупреждение всегда видно."""
from PySide6.QtWidgets import QDialog, QDialogButtonBox, QLabel, QTextEdit, QVBoxLayout, QWidget


class CadHandoffDialog(QDialog):
    def __init__(self, summary: str, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle('Предварительная CAD-заготовка')
        self.resize(720, 580)
        layout = QVBoxLayout(self)
        warning = QLabel('Это условная дискретная проверка, не проверка CAD и не допуск к изготовлению. '
                         'При выявленных проблемах можно открыть черновик только для изучения.', self)
        warning.setWordWrap(True)
        layout.addWidget(warning)
        self.summary = QTextEdit(self)
        self.summary.setReadOnly(True)
        self.summary.setAcceptRichText(False)
        self.summary.setPlainText(summary)
        layout.addWidget(self.summary, 1)
        buttons = QDialogButtonBox(self)
        accept = buttons.addButton('Открыть черновик', QDialogButtonBox.ButtonRole.AcceptRole)
        cancel = buttons.addButton('Отмена', QDialogButtonBox.ButtonRole.RejectRole)
        accept.setAutoDefault(False)
        cancel.setDefault(True)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
