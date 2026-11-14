"""Точка входа пробной Windows-сборки; обычный запуск открывает приложение."""
from __future__ import annotations

import sys
import traceback
from pathlib import Path


def main() -> int:
    # Специальная проверка запускается только явно в CI, с отдельным путём отчёта.
    if len(sys.argv) == 3 and sys.argv[1] in ("--packaging-check", "--packaging-startup-check"):
        report = Path(sys.argv[2])
        try:
            from suspensionlab.packaging_smoke import run_packaging_check, run_startup_check

            if sys.argv[1] == "--packaging-check":
                run_packaging_check()
            else:
                run_startup_check()
        except Exception:
            report.write_text(traceback.format_exc(), encoding="utf-8")
            return 1
        report.write_text("OK\n", encoding="utf-8")
        return 0
    from suspensionlab.app import main as app_main

    return app_main()


if __name__ == "__main__":
    raise SystemExit(main())
