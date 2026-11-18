"""Самодостаточный SVG предварительных CAD-видов; не чертёж для изготовления."""
from __future__ import annotations

import os
import tempfile
from contextlib import suppress
from pathlib import Path
from typing import Any
from xml.etree import ElementTree as ET

from ..core.cad_assembly_projection import MAX_SEGMENTS, PLANES
from ..core.cad_assembly_projection_job import CadAssemblyProjection, parse_projection
from ..core.cad_transport import CadPreviewError
from ..model.cad_projection_layout import dimension_segments, projection_layout, reference_caption

WIDTH, HEIGHT = 1200, 560
PANEL_WIDTH, PANEL_HEIGHT = 380., 350.
MAX_SVG_BYTES = 8_000_000


class SvgProjectionError(ValueError):
    """Некорректная проекция или невозможность безопасно создать новый SVG."""


def _number(x: float) -> str:
    return f'{x:.3f}'


def _text(parent: ET.Element, x: float, y: float, value: str, **attrs: str) -> ET.Element:
    element = ET.SubElement(parent, 'text', {'x': _number(x), 'y': _number(y), **attrs})
    element.text = value
    return element


def projection_svg(projection: CadAssemblyProjection, assembly_version: str, *, dimensions: bool) -> bytes:
    """Статичный обзор текущего снимка; отдельные масштабы, без внешних ссылок."""
    if not isinstance(projection, CadAssemblyProjection) or assembly_version not in ('0.15', '0.16'):
        raise SvgProjectionError('unsupported assembly')
    if type(dimensions) is not bool or not isinstance(projection.views, tuple) or len(projection.views) != 3:
        raise SvgProjectionError('invalid settings')
    try:
        if sum(len(view) for view in projection.views) > MAX_SEGMENTS:
            raise SvgProjectionError('too many segments')
        # The file must never include malformed, stale, or inconsistent bounds.
        source: dict[str, Any] = {'views': {plane: [list(line) for line in view]
                                           for plane, view in zip(PLANES, projection.views, strict=True)},
                                  'bounds_mm': list(projection.bounds_mm)}
        checked = parse_projection(source)
        root = ET.Element('svg', {'xmlns': 'http://www.w3.org/2000/svg',
                                  'width': str(WIDTH), 'height': str(HEIGHT),
                                  'viewBox': f'0 0 {WIDTH} {HEIGHT}', 'role': 'img',
                                  'aria-label': 'Предварительные CAD-виды сборки, не производственный чертёж'})
        ET.SubElement(root, 'rect', {'x': '0', 'y': '0', 'width': str(WIDTH), 'height': str(HEIGHT), 'fill': 'white'})
        title = ET.SubElement(root, 'title')
        title.text = 'Предварительные CAD-виды сборки; не использовать для изготовления'
        desc = ET.SubElement(root, 'desc')
        desc.text = ('Ортографические видимые линии предварительных тел, скрытые линии не показаны. '
                     'Размеры — справочные габариты в осях кузова, без допусков.')
        base = ET.SubElement(root, 'g', {'font-family': 'sans-serif', 'fill': '#263541'})
        _text(base, 30, 30, 'ПРЕДВАРИТЕЛЬНЫЕ CAD-ВИДЫ СБОРКИ .KIMA', **{'font-size': '20', 'font-weight': 'bold'})
        _text(base, 30, 57, 'НЕ ПРОИЗВОДСТВЕННЫЙ ЧЕРТЁЖ — НЕ ИСПОЛЬЗОВАТЬ ДЛЯ ИЗГОТОВЛЕНИЯ',
              fill='#a12e21', **{'font-size': '15', 'font-weight': 'bold'})
        plate = 'с условной пластиной' if assembly_version == '0.16' else 'без пластины'
        _text(base, 30, 79, f'Снимок .kima {assembly_version}, {plate}; может отличаться от файла и текущего проекта.',
              **{'font-size': '13'})
        _text(base, 30, 99, 'Видимые линии; скрытые не показаны. Масштабы видов различаются.', **{'font-size': '13'})
        for i, (plane, lines) in enumerate(zip(PLANES, checked.views, strict=True)):
            frame = projection_layout(checked.bounds_mm, plane, PANEL_WIDTH, PANEL_HEIGHT)
            panel = ET.SubElement(base, 'g', {'transform': f'translate({_number(30 + i * PANEL_WIDTH)},115)'})
            ET.SubElement(panel, 'rect', {'x': '0', 'y': '0', 'width': _number(PANEL_WIDTH),
                                          'height': _number(PANEL_HEIGHT), 'fill': 'none', 'stroke': '#cbd5df'})
            _text(panel, 8, 20, f'{plane}: +{plane[0]} →, +{plane[1]} ↑',
                  **{'font-size': '14', 'font-weight': 'bold'})
            commands: list[str] = []
            for x1, y1, x2, y2 in lines:
                a, b = frame.screen(x1, y1), frame.screen(x2, y2)
                commands.append(f'M {_number(a[0])} {_number(a[1])} L {_number(b[0])} {_number(b[1])}')
            ET.SubElement(panel, 'path', {'d': ' '.join(commands), 'fill': 'none', 'stroke': '#254b70',
                                          'stroke-width': '1.3'})
            if dimensions:
                commands = [f'M {_number(x1)} {_number(y1)} L {_number(x2)} {_number(y2)}'
                            for x1, y1, x2, y2 in dimension_segments(frame)]
                ET.SubElement(panel, 'path', {'d': ' '.join(commands), 'fill': 'none', 'stroke': '#9b5016',
                                              'stroke-width': '1'})
                x1, ybottom = frame.screen(frame.u_min, frame.v_min)
                _, ytop = frame.screen(frame.u_max, frame.v_max)
                _text(panel, PANEL_WIDTH / 2, ybottom + 29., reference_caption(plane[0], frame.width_mm),
                      fill='#9b5016', **{'font-size': '13', 'text-anchor': 'middle'})
                x, y = x1 - 20., (ytop + ybottom) / 2
                _text(panel, 0, 0, reference_caption(plane[1], frame.height_mm), fill='#9b5016',
                      transform=f'translate({_number(x)},{_number(y)}) rotate(-90)',
                      **{'font-size': '13', 'text-anchor': 'middle'})
        _text(base, 30, 491, 'Габариты справочные, по всем телам включая скрытые; округление 0,1 мм — не допуск.',
              **{'font-size': '13'})
        _text(base, 30, 511, 'Тела могут пересекаться. Подрезки, сварка, монтаж, прочность и технология не проверены.',
              **{'font-size': '13'})
        _text(base, 30, 531, 'Отдельная визуальная копия; не связана с проектом или исходной сборкой.',
              **{'font-size': '13'})
        content = ET.tostring(root, encoding='utf-8', xml_declaration=True)
        if len(content) > MAX_SVG_BYTES:
            raise SvgProjectionError('output exceeds limit')
        return content
    except SvgProjectionError:
        raise
    except (CadPreviewError, TypeError, ValueError, OverflowError, MemoryError) as error:
        raise SvgProjectionError('invalid projection') from error


def write_new_projection_svg(path: str | Path, projection: CadAssemblyProjection, assembly_version: str, *,
                             dimensions: bool) -> Path:
    """Атомарно создать только новый SVG; существующие файлы не заменяются."""
    target = Path(path)
    if target.suffix.lower() != '.svg':
        raise SvgProjectionError('incorrect extension')
    content = projection_svg(projection, assembly_version, dimensions=dimensions)
    temporary: str | None = None
    try:
        if target.is_symlink():
            raise SvgProjectionError('symlink destination is not supported')
        with tempfile.NamedTemporaryFile(mode='wb', dir=target.parent, prefix='.projection-',
                                         suffix='.tmp', delete=False) as handle:
            temporary = handle.name
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        # Create-if-absent on the same filesystem. Even a destination created
        # while the dialog was open is never replaced.
        os.link(temporary, target)
        return target
    except OSError as error:
        raise SvgProjectionError('cannot create new SVG') from error
    finally:
        if temporary is not None:
            with suppress(OSError):
                os.unlink(temporary)
