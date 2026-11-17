"""Независимая проверка OCP и изолированного процесса для четырёх сторон."""
import math

import pytest

pytest.importorskip('OCP', exc_type=ImportError)

from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_assembly, build_front_arm_tubes_preview  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.bent_tube import make_bend_path  # noqa: E402
from suspensionlab.model.entities import Project  # noqa: E402
from suspensionlab.model.front_tube_arm import make_front_tube_arm  # noqa: E402
from suspensionlab.model.niva_arm_views import FRONT  # noqa: E402


def test_front_arm_tubes_are_real_valid_cad_for_all_four_arms():
    p = Project.create_default()
    for code, xyz in {'uca_f_in': (0, 0, 0), 'uca_r_in': (0, -100, 0), 'ubj': (100, 100, 0),
                      'lca_f_in': (0, 0, 0), 'lca_r_in': (0, -100, 0), 'lbj': (100, 100, 0)}.items():
        point = p.front.hardpoints[code]
        point.x, point.y, point.z = xyz
    for key in FRONT:
        sign = -1 if key.endswith('_right') else 1
        bends = {'front': {'vertex_mm': [100, 0, 0], 'radius_mm': 20},
                 'rear': {'vertex_mm': [100, -100*sign, 0], 'radius_mm': 25}}
        for specs in ({}, bends):
            doc = make_front_tube_arm(p, key, 10, 2, specs)
            shape = build_front_arm_tubes_preview(doc)
            assert BRepCheck_Analyzer(shape).IsValid()
            props = GProp_GProps()
            BRepGProp.VolumeProperties_s(shape, props)
            if specs:
                length = sum(make_bend_path(start, specs[leg]['vertex_mm'], (100, 100*sign, 0),
                                            specs[leg]['radius_mm'], 10).length
                             for leg, start in [('front', (0, 0, 0)), ('rear', (0, -100*sign, 0))])
            else:
                length = math.sqrt(20000) + math.sqrt(50000)
            assert props.Mass() == pytest.approx(math.pi * (10**2 - 8**2) * length, rel=1e-6)
            with pytest.raises(ValueError):
                build_assembly(doc)
        mesh = WeldmentCadJob().run(doc)
        assert len(mesh.triangles) > 0 and mesh.skipped_faces == mesh.recovered_faces == 0
