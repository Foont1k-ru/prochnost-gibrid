"""Проверки B-rep и изолированного процесса CAD, если OCP установлен."""
import math

import pytest

pytest.importorskip('OCP', exc_type=ImportError)

from OCP.BRepCheck import BRepCheck_Analyzer  # noqa: E402
from OCP.BRepGProp import BRepGProp  # noqa: E402
from OCP.GProp import GProp_GProps  # noqa: E402

from suspensionlab.core.cad_kim_prototype import build_assembly, build_rear_tube_preview  # noqa: E402
from suspensionlab.core.cad_weldment_job import WeldmentCadJob  # noqa: E402
from suspensionlab.model.bent_tube import make_bend_path  # noqa: E402
from suspensionlab.model.entities import Project  # noqa: E402
from suspensionlab.model.rear_tube import make_rear_tube  # noqa: E402


def test_real_cad_straight_and_bent_tube_volume_and_worker():
    p = Project.create_default()
    p.rear.type_code, p.rear.layout = 'live_axle_coil', '4link_panhard'
    p.rear.ensure_points(overwrite=True)
    for code, xyz in {'ll_in_l': (0, 0, 0), 'll_out_l': (100, 100, 0)}.items():
        point = p.rear.hardpoints[code]
        point.x, point.y, point.z = xyz
    bend = {'vertex_mm': [100, 0, 0], 'radius_mm': 20}
    for spec in (None, bend):
        doc = make_rear_tube(p, 'rear_lower_left', 10, 2, spec)
        shape = build_rear_tube_preview(doc)
        assert BRepCheck_Analyzer(shape).IsValid()
        props = GProp_GProps()
        BRepGProp.VolumeProperties_s(shape, props)
        length = math.sqrt(20000) if spec is None else make_bend_path((0, 0, 0), (100, 0, 0),
                                                                       (100, 100, 0), 20, 10).length
        assert props.Mass() == pytest.approx(math.pi * (10**2 - 8**2) * length, rel=1e-6)
        mesh = WeldmentCadJob().run(doc)
        assert len(mesh.triangles) > 0 and mesh.skipped_faces == mesh.recovered_faces == 0
        with pytest.raises(ValueError):
            build_assembly(doc)
