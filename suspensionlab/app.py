"""Точка входа: запуск приложения из корня проекта (``python app.py``).

Сам код приложения находится в пакете :mod:`suspensionlab`.
"""

from __future__ import annotations

from suspensionlab.app import main

if __name__ == "__main__":
    raise SystemExit(main())
