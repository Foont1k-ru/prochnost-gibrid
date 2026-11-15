"""CPU-отрисовка CAD-сетки, без зависимости от GUI или расчётного проекта."""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

from .cad_mesh import project_points

COLORS = [(v * 3 // 4, v * 9 // 10, v) for v in range(256)]
HIGHLIGHT_COLORS = [(min(255, v + 50), v * 2 // 3, v // 6) for v in range(256)]


def triangle_shades(triangles: np.ndarray) -> np.ndarray:
    normals = np.cross(triangles[:, 1] - triangles[:, 0], triangles[:, 2] - triangles[:, 0])
    sizes = np.linalg.norm(normals, axis=1)
    intensity = np.abs(normals[:, 0] * 0.25 - normals[:, 1] * 0.45 + normals[:, 2] * 0.86) / np.maximum(sizes, 1e-20)
    return np.clip((intensity * 100 + 105).astype(np.uint8), 105, 205)


def screen_projection(triangles: np.ndarray, center: np.ndarray, radius: float,
                      yaw: float, elevation: float, zoom: float, width: int, height: int,
                      margin: float = 24.) -> tuple[np.ndarray, np.ndarray]:
    """Пиксельные координаты и тот же порядок, что используется в отрисовке."""
    projected, order = project_points(triangles, center, yaw, elevation)
    scale = max(1., min(width - margin, height - margin)) / (2 * radius) * zoom
    projected[:, :, 0] = width / 2 + projected[:, :, 0] * scale
    projected[:, :, 1] = height / 2 - projected[:, :, 1] * scale
    return projected, order


def pick_triangle(triangles: np.ndarray, center: np.ndarray, radius: float,
                  yaw: float, elevation: float, zoom: float, width: int, height: int,
                  x: int, y: int, margin: float = 24., highlight: np.ndarray | None = None,
                  through: bool = False) -> int | None:
    """Какой треугольник последним рисуется в пикселе, не инженерный hit-test.

    PIL сам разрешает граничные и вырожденные случаи, как при отрисовке.
    Вспомогательный кадр содержит только треугольники, потенциально
    перекрывающие выбранный пиксель.
    При сквозной подсветке выбранное рисуется повторно поверх остальных.
    """
    if not (0 <= x < width and 0 <= y < height):
        return None
    if highlight is not None and (highlight.shape != (len(triangles),) or highlight.dtype.kind != "b"):
        raise ValueError("Некорректная маска подсветки")
    projected, order = screen_projection(triangles, center, radius, yaw, elevation, zoom, width, height, margin)
    coords = np.trunc(projected).astype(np.int64)
    # Грубый отбор по прямоугольникам сокращает число вызовов PIL, но не
    # определяет результат: окончательное совпадение проверяет сам растеризатор.
    hit = ((coords[:, :, 0].min(axis=1) <= x) & (coords[:, :, 0].max(axis=1) >= x) &
           (coords[:, :, 1].min(axis=1) <= y) & (coords[:, :, 1].max(axis=1) >= y))
    candidates = order[hit[order]]
    if not len(candidates):
        return None
    image = Image.new("RGB", (width, height), (0, 0, 0))
    draw = ImageDraw.Draw(image)

    def draw_candidates(indices: np.ndarray) -> None:
        for index in indices:
            identifier = int(index) + 1
            points = coords[index].reshape(6).tolist()
            draw.polygon(points, fill=((identifier >> 16) & 255, (identifier >> 8) & 255, identifier & 255))

    draw_candidates(candidates)
    if through and highlight is not None:
        draw_candidates(candidates[highlight[candidates]])
    pixel = image.getpixel((x, y))
    assert isinstance(pixel, tuple) and len(pixel) == 3
    r, g, b = pixel
    value = (r << 16) | (g << 8) | b
    return value - 1 if value else None


def rasterize(triangles: np.ndarray, shades: np.ndarray, center: np.ndarray, radius: float,
              yaw: float, elevation: float, zoom: float, width: int, height: int,
              background: tuple[int, int, int], margin: float = 24.,
              highlight: np.ndarray | None = None, through: bool = False) -> Image.Image:
    """Ортографический приближённый просмотр с сортировкой по средней глубине."""
    if highlight is not None and (highlight.shape != (len(triangles),) or highlight.dtype.kind != "b"):
        raise ValueError("Некорректная маска подсветки")
    projected, order = screen_projection(triangles, center, radius, yaw, elevation, zoom, width, height, margin)
    coordinates = projected[order].reshape(-1, 6).tolist()
    colors = shades[order].tolist()
    image = Image.new("RGB", (width, height), background)
    draw = ImageDraw.Draw(image)
    if highlight is None:
        for points, shade in zip(coordinates, colors, strict=True):
            draw.polygon(points, fill=COLORS[shade])
    else:
        selected = highlight[order].tolist()
        for points, shade, chosen in zip(coordinates, colors, selected, strict=True):
            draw.polygon(points, fill=(HIGHLIGHT_COLORS if chosen else COLORS)[shade])
        if through:
            # Нарочито поверх всех деталей — это проекция, не физическое перекрытие.
            for points, shade, chosen in zip(coordinates, colors, selected, strict=True):
                if chosen:
                    draw.polygon(points, fill=HIGHLIGHT_COLORS[shade])
    return image
