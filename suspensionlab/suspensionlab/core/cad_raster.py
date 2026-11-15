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


def rasterize(triangles: np.ndarray, shades: np.ndarray, center: np.ndarray, radius: float,
              yaw: float, elevation: float, zoom: float, width: int, height: int,
              background: tuple[int, int, int], margin: float = 24.,
              highlight: np.ndarray | None = None, through: bool = False) -> Image.Image:
    """Ортографический приближённый просмотр с сортировкой по средней глубине."""
    if highlight is not None and (highlight.shape != (len(triangles),) or highlight.dtype.kind != "b"):
        raise ValueError("Некорректная маска подсветки")
    projected, order = project_points(triangles, center, yaw, elevation)
    scale = max(1., min(width - margin, height - margin)) / (2 * radius) * zoom
    projected[:, :, 0] = width / 2 + projected[:, :, 0] * scale
    projected[:, :, 1] = height / 2 - projected[:, :, 1] * scale
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
