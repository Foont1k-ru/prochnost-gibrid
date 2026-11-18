"""Переносит ошибки JUnit в аннотации GitHub, не меняя результат pytest."""
from __future__ import annotations

import sys
from pathlib import Path
from xml.etree import ElementTree


def escape(value: str) -> str:
    return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")


def main(path: Path) -> None:
    if not path.is_file():
        print("JUnit report not found")
        return
    root = ElementTree.parse(path).getroot()
    for case in root.iter("testcase"):
        for item in case:
            if item.tag in ("failure", "error"):
                name = case.get("classname", "") + "." + case.get("name", "")
                details = f"{name}\n{item.get('message', '')}\n{item.text or ''}"
                print("::error::" + escape(details[:60000]))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
