"""Предварительное разделение вхождений XCAF для визуального просмотра.

Вхождения не становятся расчётными деталями или шарнирами. При неоднозначном
совпадении грань остаётся в общей группе, но не приписывается экземпляру.
"""
from __future__ import annotations

from .cad_parts import MAX_GROUP_FACES, face_group

MAX_INSTANCES = 1024  # включая номер 0 для неопределённых граней
MAX_NODES = 4096
MAX_DEPTH = 64


class _TraversalLimitError(Exception):
    pass


def collect_instances(tool, part_faces):
    """Найти листовые вхождения и сопоставить их расположенным граням.

    Исключительно для фильтра просмотра. Если обход неподдерживаемой иерархии
    или лимиты не позволяют надёжно разделить вхождения, возвращаем пустую карту.
    """
    from OCP.collections import Sequence_TDF_Label
    from OCP.TDF import TDF_Label
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location

    fallback = ((0,), {})
    instance_groups = [0]
    instance_faces = {}
    nodes = faces_seen = 0

    def visit(label, parent_location, depth):
        nonlocal nodes, faces_seen
        nodes += 1
        if nodes > MAX_NODES or depth > MAX_DEPTH:
            raise _TraversalLimitError
        if tool.IsReference_s(label):
            definition = TDF_Label()
            if not tool.GetReferredShape_s(label, definition):
                return
            parent_location = parent_location.Multiplied(tool.GetLocation_s(label))
            label = definition
        if tool.IsAssembly_s(label):
            components = Sequence_TDF_Label()
            if tool.GetComponents_s(label, components, False):
                for i in range(1, components.Length() + 1):
                    visit(components.Value(i), parent_location, depth + 1)
            return
        shape = tool.GetShape_s(label)
        if shape.IsNull():
            return
        shape = shape.Moved(parent_location)
        explorer = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_FACE)
        faces = []
        matched_groups = set()
        while explorer.More():
            faces_seen += 1
            if faces_seen > MAX_GROUP_FACES:
                raise _TraversalLimitError
            face = explorer.Current()
            group = face_group(face, part_faces)
            if group:
                matched_groups.add(group)
                faces.append(face)
            explorer.Next()
        if len(matched_groups) != 1 or not faces:
            return
        if len(instance_groups) >= MAX_INSTANCES:
            raise _TraversalLimitError
        instance = len(instance_groups)
        instance_groups.append(next(iter(matched_groups)))
        for face in faces:
            instance_faces.setdefault(hash(face), []).append((face, instance))

    try:
        roots = Sequence_TDF_Label()
        tool.GetFreeShapes(roots)
        for i in range(1, roots.Length() + 1):
            visit(roots.Value(i), TopLoc_Location(), 0)
    except Exception:
        # Группировка не должна мешать просмотру геометрии при ошибках XCAF.
        return fallback
    return tuple(instance_groups), instance_faces
