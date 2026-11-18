"""Предварительная группировка граней STEP для изолированного просмотра.

Это не список связей и не идентификация сборки для расчёта. Несколько
вхождений одного описания изделия собираются в одну группу.
"""
from __future__ import annotations

MAX_PART_GROUPS = 512
MAX_PART_NAME = 128
MAX_GROUP_FACES = 100_000


def collect_part_groups(tool, shape):
    """Сопоставить твёрдые тела с простыми определениями XCAF по топологии."""
    from OCP.collections import Sequence_TDF_Label
    from OCP.TDataStd import TDataStd_Name
    from OCP.TopAbs import TopAbs_ShapeEnum
    from OCP.TopExp import TopExp_Explorer

    labels = Sequence_TDF_Label()
    tool.GetShapes(labels)
    # 0 всегда означает несопоставленную геометрию, никогда не отбрасываем её.
    names = ["Без имени / прочие"]
    definitions = []
    # При превышении лимитов не угадываем группы по неполному набору определений.
    fallback = ((names[0],), {})
    if labels.Length() > MAX_PART_GROUPS * 4:
        return fallback
    for i in range(1, labels.Length() + 1):
        label = labels.Value(i)
        if not tool.IsSimpleShape_s(label):
            continue
        definition = tool.GetShape_s(label)
        if definition.IsNull():
            continue
        solids = TopExp_Explorer(definition, TopAbs_ShapeEnum.TopAbs_SOLID)
        current = []
        while solids.More():
            current.append(solids.Current())
            if len(current) > MAX_PART_GROUPS:
                break
            solids.Next()
        if not current:
            continue
        if len(names) >= MAX_PART_GROUPS or len(definitions) + len(current) > MAX_PART_GROUPS:
            return fallback
        attr = TDataStd_Name()
        text = attr.Get().ToExtString() if label.FindAttribute(TDataStd_Name.GetID_s(), attr) else ""
        text = "".join(c if c.isprintable() else " " for c in text).strip()[:MAX_PART_NAME]
        names.append(text or "Без имени")
        definitions.extend((solid, len(names) - 1) for solid in current)
    face_groups = {}
    solids = TopExp_Explorer(shape, TopAbs_ShapeEnum.TopAbs_SOLID)
    processed = face_count = 0
    while solids.More():
        if processed >= MAX_PART_GROUPS * 2:
            return fallback
        solid = solids.Current()
        matches = {group for ref, group in definitions if solid.IsPartner(ref)}
        group = next(iter(matches)) if len(matches) == 1 else 0
        faces = TopExp_Explorer(solid, TopAbs_ShapeEnum.TopAbs_FACE)
        while faces.More():
            # hash используется только для поиска: IsSame дополнительно защищает от коллизий.
            face_count += 1
            if face_count > MAX_GROUP_FACES:
                return fallback
            face = faces.Current()
            face_groups.setdefault(hash(face), []).append((face, group))
            faces.Next()
        processed += 1
        solids.Next()
    return tuple(names), face_groups


def face_group(face, groups) -> int:
    matches = {group for candidate, group in groups.get(hash(face), ()) if face.IsSame(candidate)}
    return next(iter(matches)) if len(matches) == 1 else 0
