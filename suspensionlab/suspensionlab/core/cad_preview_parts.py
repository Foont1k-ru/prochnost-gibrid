"""Identity of the *displayed* parts of supported experimental previews.

Paths address direct children of the CAD compound built for the same snapshot.
These are display identities, not persistent feature references or weldments.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class PreviewPart:
    identifier: str
    path: tuple[int, ...]
    name: str = ''
    label_key: str = ''


def preview_parts(document: dict[str, Any]) -> tuple[PreviewPart, ...]:
    if document.get('format') != 'kima-assembly':
        return ()
    version = document.get('version')
    if version in ('0.2', '0.3', '0.15', '0.16'):
        return tuple(PreviewPart(p['id'], (i,), name=p['name']) for i, p in enumerate(document['parts']))
    if version == '0.4':
        return (PreviewPart('tube', (), name=document['name']),)
    if version == '0.5':
        return (PreviewPart('tube_front', (0,), label_key='weldment_3d.part_front'),
                PreviewPart('tube_rear', (1,), label_key='weldment_3d.part_rear'))
    if version == '0.6':
        return (PreviewPart('source_tube', (0,), label_key='weldment_3d.part_source_tube'),
                PreviewPart('paired_tube', (1,), label_key='weldment_3d.part_paired_tube'))
    if version in ('0.7', '0.11'):
        return tuple(PreviewPart(f'{side}_tube_{leg}', (i, j),
                                 label_key=f'weldment_3d.part_{side}_{leg}')
                     for i, side in enumerate(('source', 'paired'))
                     for j, leg in enumerate(('front', 'rear')))
    return ()
