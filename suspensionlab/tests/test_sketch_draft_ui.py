"""Проверки пользовательского пробного холста."""

from PySide6.QtCore import QPointF, Qt
from PySide6.QtWidgets import QMessageBox

from suspensionlab.ui.sketch_draft_dialog import SketchDraftDialog


def test_mouse_points_undo_redo_and_plane_lock(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    a = canvas.to_screen((0, 0)).toPoint()
    b = canvas.to_screen((20, 10)).toPoint()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=a)
    assert canvas.pending == (0, 0)
    assert not dialog.plane.isEnabled()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=b)
    assert canvas.draft.entities[0].end == (20, 10)
    dialog._undo()
    assert not canvas.draft.entities
    assert not dialog.plane.isEnabled()  # redo must never change coordinate plane
    dialog._redo()
    assert len(canvas.draft.entities) == 1
    canvas.draft.entities.clear()


def test_exact_input_cancel_and_close_warning(qtbot, monkeypatch):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.canvas.add_point((1.234, -2.345))
    dialog.canvas.add_point((4.567, 5.678))
    assert dialog.canvas.draft.entities[0].start == (1.234, -2.345)
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    assert not dialog.close()
    assert dialog.isVisible()
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    assert dialog.close()


def test_screen_mapping_and_grid(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    point = (13.0, -17.0)
    assert canvas.to_world(canvas.to_screen(point), snap=False) == point
    assert canvas.to_world(canvas.to_screen(point)) == (10, -20)
    canvas.hover = (10, -20)
    canvas.pending = (0, 0)
    canvas.repaint()
    assert canvas.to_world(QPointF(canvas.width() / 2, canvas.height() / 2)) == (0, 0)
    canvas.pending = None


def test_selection_delete_undo_and_point_snap(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((2, 3))
    canvas.add_point((42, 3))
    # An endpoint wins over the grid when close enough in screen pixels.
    assert canvas.mouse_point(canvas.to_screen((2.5, 3))) == (2, 3)
    assert canvas.snap_label == "точка"
    dialog.tool.setCurrentIndex(2)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((22, 3)).toPoint())
    assert canvas.selected == 0
    assert dialog.edit_button.isEnabled()
    dialog._delete()
    assert not canvas.draft.entities
    dialog._undo()
    assert len(canvas.draft.entities) == 1
    dialog._saved = dialog._document()


def test_save_open_and_dirty_warning(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.plane.setCurrentText("XZ")
    dialog.plane_offset.setValue(12.125)
    dialog.canvas.add_point((1, 2))
    dialog.canvas.add_point((30, 40))
    path = tmp_path / "sketch.slsketch"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    assert dialog._save()
    assert not dialog._dirty()
    dialog.canvas.add_point((50, 60))
    dialog.canvas.add_point((70, 80))
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Cancel)
    dialog._new()
    assert len(dialog.canvas.draft.entities) == 2
    # Discard is confirmed, failed open must still not replace the document.
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.No)
    bad = tmp_path / "bad.slsketch"
    bad.write_text("invalid")
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(bad), ""))
    dialog._open()
    assert len(dialog.canvas.draft.entities) == 2 and dialog._dirty()
    monkeypatch.setattr(QFileDialog, "getOpenFileName", lambda *args, **kwargs: (str(path), ""))
    dialog._open()
    assert dialog.plane.currentText() == "XZ" and dialog.plane_offset.value() == 12.125
    assert len(dialog.canvas.draft.entities) == 1 and not dialog._dirty()
    assert not dialog.plane.isEnabled()


def test_circle_editor_and_invalid_radius(qtbot):
    from suspensionlab.model.sketch_draft import make_entity
    from suspensionlab.ui.sketch_draft_dialog import EntityEditor

    parent = SketchDraftDialog()
    qtbot.addWidget(parent)
    editor = EntityEditor(make_entity("circle", (5, 6), (8, 10)), parent)
    qtbot.addWidget(editor)
    editor.values[0].setValue(10)
    editor.values[2].setValue(10)
    result = editor.result_entity()
    assert result.start == (10, 6)
    assert result.size == 10
    editor.values[2].setValue(0)
    import pytest

    with pytest.raises(ValueError):
        editor.result_entity()


def test_rectangle_preview_undo_save_and_chain(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from suspensionlab.model.sketch_io import read_sketch

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    dialog.tool.setCurrentIndex(3)
    canvas.add_point((0, 0))
    canvas.hover = (40, 30)
    canvas.repaint()
    assert not canvas.draft.entities  # preview is not a command
    canvas.add_point((40, 30))
    assert len(canvas.draft.entities) == 4
    dialog._undo()
    assert not canvas.draft.entities
    dialog._redo()
    assert len(canvas.draft.entities) == 4
    dialog.tool.setCurrentIndex(4)
    canvas.add_point((100, 100))
    canvas.add_point((150, 100))
    canvas.add_point((150, 150))
    assert len(canvas.draft.entities) == 6
    assert canvas.pending == (150, 150)
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: QMessageBox.StandardButton.Ok)
    assert not dialog._save()  # finish chain before saving
    canvas.cancel()
    path = tmp_path / "drawing.slsketch"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    assert dialog._save()
    assert tuple(canvas.draft.entities) == read_sketch(path).entities
    dialog._undo()
    assert len(canvas.draft.entities) == 5 and dialog._dirty()
    dialog._redo()
    assert not dialog._dirty()


def test_midpoint_snap_and_measurement_is_not_a_document_change(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((0, 0))
    canvas.add_point((40, 0))
    dialog._saved = dialog._document()
    assert canvas.mouse_point(canvas.to_screen((20, 1))) == (20, 0)
    assert canvas.snap_label == "середина"
    dialog.tool.setCurrentIndex(5)
    canvas.add_point((0, 0))
    assert not dialog._dirty() and canvas.pending is None
    canvas.hover = (3, 4)
    canvas.repaint()
    canvas.add_point((3, 4))
    assert "5.000" in dialog.status.text()
    assert not dialog._dirty()
    assert len(canvas.draft.entities) == 1


def test_fit_entire_geometry_does_not_change_document(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((-800, -300))
    canvas.add_point((900, 500))
    dialog.tool.setCurrentIndex(1)
    canvas.add_point((1200, 300))
    canvas.add_point((1500, 300))
    dialog._saved = dialog._document()
    assert canvas.fit_view()
    for p in ((-800, -300), (900, 500), (900, 300), (1500, 300), (1200, 600), (1200, 0)):
        screen = canvas.to_screen(p)
        assert 0 <= screen.x() <= canvas.width()
        assert 0 <= screen.y() <= canvas.height()
    assert not dialog._dirty()


def test_measurement_on_empty_document_does_not_lock_plane(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tool.setCurrentIndex(5)
    dialog.canvas.add_point((1, 2))
    assert dialog.plane.isEnabled() and not dialog._dirty()
    dialog.plane.setCurrentText("YZ")
    assert dialog.canvas.measure_start is None
    dialog.canvas.add_point((1, 2))
    dialog.canvas.add_point((4, 6))
    assert "5.000" in dialog.status.text()
    assert not dialog.canvas.draft.entities
    # Restore the intentionally changed plane so fixture cleanup is quiet.
    dialog.plane.setCurrentText("XY")


def test_contour_check_highlight_is_invalidated_on_edit(qtbot, monkeypatch):
    messages = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: messages.append(args[2]))
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((0, 0))
    canvas.add_point((40, 0))
    before = dialog._document()
    dialog._check_contours()
    assert "Открытый конец" in messages[-1]
    assert canvas.diagnostic_indices == {0}
    assert len(canvas.diagnostic_points) == 2
    assert dialog._document() == before
    canvas.repaint()
    canvas.add_point((40, 0))
    canvas.add_point((40, 40))
    assert not canvas.diagnostic_indices
    assert canvas.diagnostic_snapshot is None
    dialog._saved = dialog._document()


def test_contour_check_blocks_pending_and_clears_on_tolerance_change(qtbot, monkeypatch):
    warnings, reports = [], []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    monkeypatch.setattr(QMessageBox, "information", lambda *args: reports.append(args[2]))
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tool.setCurrentIndex(3)
    dialog.canvas.add_point((0, 0))
    dialog._check_contours()
    assert warnings and not reports
    dialog.canvas.add_point((10, 10))
    dialog._check_contours()
    assert "Замечаний не найдено" in reports[-1]
    assert "не гарантирует" in reports[-1]
    assert dialog.canvas.diagnostic_snapshot is not None
    dialog.contour_tolerance.setValue(0.02)
    assert dialog.canvas.diagnostic_snapshot is None
    dialog._saved = dialog._document()


def test_dxf_export_confirmation_pending_and_dirty_state(qtbot, tmp_path, monkeypatch):
    import ezdxf
    from PySide6.QtWidgets import QFileDialog

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.plane.setCurrentText("YZ")
    dialog.plane_offset.setValue(12)
    dialog.canvas.add_point((1, 2))
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args[2]))
    assert not dialog._export_dxf() and warnings
    dialog.canvas.add_point((3, 4))
    before = dialog._document()
    notices = []
    monkeypatch.setattr(QMessageBox, "question", lambda *args: notices.append(args[2]) or QMessageBox.StandardButton.No)
    assert not dialog._export_dxf() and "YZ" in notices[-1] and "не сохраняются" in notices[-1]
    target = tmp_path / "drawing.dxf"
    monkeypatch.setattr(QMessageBox, "question", lambda *args: QMessageBox.StandardButton.Yes)
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(target), ""))
    assert dialog._export_dxf()
    assert dialog._document() == before and dialog._dirty()
    assert len(ezdxf.readfile(target).modelspace()) == 1
    # Existing target stays untouched, and export never marks the sketch saved.
    original = target.read_bytes()
    assert not dialog._export_dxf() and target.read_bytes() == original
    assert dialog._dirty()
    dialog._saved = dialog._document()


def test_arc_creation_edit_roundtrip_and_contour_guard(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from suspensionlab.model.sketch_draft import arc_end
    from suspensionlab.model.sketch_io import read_sketch
    from suspensionlab.ui.sketch_draft_dialog import EntityEditor

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    dialog.tool.setCurrentIndex(6)
    dialog.arc_angle.setValue(-90)
    canvas.add_point((0, 0))
    canvas.hover = (10, 0)
    canvas.repaint()
    canvas.add_point((10, 0))
    arc = canvas.draft.entities[0]
    assert arc.kind == "arc" and arc.sweep_deg == -90
    assert abs(arc_end(arc)[1] + 10) < 1e-9
    editor = EntityEditor(arc, dialog)
    qtbot.addWidget(editor)
    editor.values[3].setValue(45)
    assert editor.result_entity().sweep_deg == 45
    reports = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: reports.append(args[2]))
    dialog._check_contours()
    assert "Открытый конец" in reports[-1]
    path = tmp_path / "arc.slsketch"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    assert dialog._save() and read_sketch(path).entities == (arc,)
    dialog._undo()
    assert not canvas.draft.entities
    dialog._redo()
    assert canvas.draft.entities == [arc] and not dialog._dirty()


def test_trim_mouse_and_atomic_undo(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    for start, end in (((0, 0), (100, 0)), ((40, -40), (40, 40)), ((70, -40), (70, 40))):
        canvas.add_point(start)
        canvas.add_point(end)
    original = tuple(canvas.draft.entities)
    dialog.tool.setCurrentIndex(7)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((55, 0)).toPoint())
    assert len(canvas.draft.entities) == 4
    assert canvas.draft.entities[0].end == (40, 0)
    assert canvas.draft.entities[1].start == (70, 0)
    dialog._undo()
    assert tuple(canvas.draft.entities) == original
    dialog._redo()
    assert len(canvas.draft.entities) == 4
    dialog._saved = dialog._document()


def test_tangent_two_lines_mouse_cancel_and_apply(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui.sketch_draft_dialog import TangentChoiceDialog

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    for start, end in (((-100, 0), (100, 0)), ((0, -100), (0, 100))):
        canvas.add_point(start)
        canvas.add_point(end)
    dialog.tool.setCurrentIndex(8)
    monkeypatch.setattr(TangentChoiceDialog, "exec", lambda self: QDialog.DialogCode.Rejected)
    for point in ((50, 0), (0, 50)):
        qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen(point).toPoint())
    assert len(canvas.draft.entities) == 2 and not canvas.construction_indices
    monkeypatch.setattr(TangentChoiceDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    for point in ((50, 0), (0, 50)):
        qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen(point).toPoint())
    assert len(canvas.draft.entities) == 3
    assert abs(canvas.draft.entities[-1].size - 10) < 1e-8
    dialog._undo()
    assert len(canvas.draft.entities) == 2
    dialog._saved = dialog._document()


def test_tangent_three_lines_mouse(qtbot, monkeypatch):
    from PySide6.QtWidgets import QDialog

    from suspensionlab.ui.sketch_draft_dialog import TangentChoiceDialog

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    for start, end in (((0, 0), (100, 0)), ((100, 0), (0, 100)), ((0, 100), (0, 0))):
        canvas.add_point(start)
        canvas.add_point(end)
    dialog.tool.setCurrentIndex(9)
    monkeypatch.setattr(TangentChoiceDialog, "exec", lambda self: QDialog.DialogCode.Accepted)
    for point in ((50, 0), (50, 50), (0, 50)):
        qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen(point).toPoint())
    assert len(canvas.draft.entities) == 4 and canvas.draft.entities[-1].kind == "circle"
    dialog._saved = dialog._document()


def test_trim_circle_click_creates_arc_and_undo(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    dialog.tool.setCurrentIndex(1)
    canvas.add_point((0, 0))
    canvas.add_point((30, 0))
    dialog.tool.setCurrentIndex(0)
    canvas.add_point((-50, 0))
    canvas.add_point((50, 0))
    old = tuple(canvas.draft.entities)
    dialog.tool.setCurrentIndex(7)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((0, 30)).toPoint())
    assert canvas.draft.entities[0].kind == "arc"
    assert canvas.draft.entities[0].sweep_deg == 180
    dialog._undo()
    assert tuple(canvas.draft.entities) == old
    dialog._saved = dialog._document()


def test_undo_during_tangent_selection_cancels_selection_first(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    for start, end in (((-40, 0), (40, 0)), ((0, -40), (0, 40))):
        canvas.add_point(start)
        canvas.add_point(end)
    dialog.tool.setCurrentIndex(8)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((30, 0)).toPoint())
    assert canvas.construction_indices == [0]
    dialog._undo()
    assert not canvas.construction_indices and len(canvas.draft.entities) == 2
    dialog._undo()
    assert len(canvas.draft.entities) == 1
    dialog._saved = dialog._document()


def test_trim_arc_mouse_and_contour_check(qtbot, monkeypatch):
    reports = []
    monkeypatch.setattr(QMessageBox, "information", lambda *args: reports.append(args[2]))
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    dialog.tool.setCurrentIndex(6)
    dialog.arc_angle.setValue(180)
    canvas.add_point((0, 0))
    canvas.add_point((60, 0))
    dialog.tool.setCurrentIndex(0)
    canvas.add_point((-60, 0))
    canvas.add_point((60, 0))
    dialog._check_contours()
    assert "Замечаний не найдено" in reports[-1]
    # A vertical cutting line intersects the interior of the semicircle.
    canvas.add_point((0, -80))
    canvas.add_point((0, 80))
    original = tuple(canvas.draft.entities)
    dialog.tool.setCurrentIndex(7)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((42.426, 42.426)).toPoint())
    assert canvas.draft.entities[0].kind == "arc"
    assert abs(canvas.draft.entities[0].sweep_deg - 90) < 1e-8
    dialog._undo()
    assert tuple(canvas.draft.entities) == original
    dialog._saved = dialog._document()


def test_tangent_choice_shows_alternate_preview(qtbot):
    from suspensionlab.model.sketch_construction import tangent_circles
    from suspensionlab.model.sketch_draft import make_entity
    from suspensionlab.ui.sketch_draft_dialog import TangentChoiceDialog

    parent = SketchDraftDialog()
    qtbot.addWidget(parent)
    lines = (make_entity("line", (-100, 0), (100, 0)), make_entity("line", (0, -100), (0, 100)))
    circles = tangent_circles(lines, 10)
    choice = TangentChoiceDialog(lines, circles, parent)
    qtbot.addWidget(choice)
    choice.show()
    assert choice.selected_circle() == circles[0]
    choice.choice.setCurrentIndex(1)
    assert choice.selected_circle() == circles[1] and choice.preview.index == 1
    assert not choice.preview.grab().isNull()


def test_dimension_placement_edit_delete_undo_and_save(qtbot, tmp_path, monkeypatch):
    from PySide6.QtWidgets import QFileDialog

    from suspensionlab.model.sketch_draft import dimension_text
    from suspensionlab.model.sketch_io import read_sketch

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((0, 0))
    canvas.add_point((60, 20))
    dialog.tool.setCurrentIndex(10)
    dialog.dimension_style.setCurrentIndex(1)  # горизонтальный
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((30, 10)).toPoint())
    assert canvas.dimension_target == 0
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((30, 40)).toPoint())
    assert len(canvas.draft.dimensions) == 1
    assert dimension_text(canvas.draft.dimensions[0], canvas.draft.entities[0]) == "60.000 мм"
    assert not canvas.grab().isNull()
    canvas.draft.replace(0, "line", (0, 0), (80, 20))
    assert dimension_text(canvas.draft.dimensions[0], canvas.draft.entities[0]) == "80.000 мм"
    dialog._undo()
    assert dimension_text(canvas.draft.dimensions[0], canvas.draft.entities[0]) == "60.000 мм"
    path = tmp_path / "dimensions.slsketch"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", lambda *args, **kwargs: (str(path), ""))
    assert dialog._save()
    assert read_sketch(path).dimensions == tuple(canvas.draft.dimensions)
    dialog.tool.setCurrentIndex(2)
    canvas.selected = 0
    dialog._delete()
    assert len(canvas.draft.entities) == 1 and "размер" in dialog.status.text().lower()
    dialog.tool.setCurrentIndex(11)
    dim_pos = canvas.draft.dimensions[0].position
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen(dim_pos).toPoint())
    assert not canvas.draft.dimensions
    dialog._undo()
    assert len(canvas.draft.dimensions) == 1 and not dialog._dirty()


def test_fillet_mouse_preserves_reference_and_is_one_undo(qtbot):
    from suspensionlab.model.sketch_draft import dimension_text

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    for first, second in (((0, 0), (100, 0)), ((0, 0), (0, 100))):
        canvas.add_point(first)
        canvas.add_point(second)
    canvas.draft.add_dimension(0, (50, -20))
    original = tuple(canvas.draft.entities)
    dialog.tool.setCurrentIndex(12)
    for point in ((50, 0), (0, 50)):
        qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen(point).toPoint())
    assert len(canvas.draft.entities) == 3 and canvas.draft.entities[-1].kind == "arc"
    assert dimension_text(canvas.draft.dimensions[0], canvas.draft.entities[0]) == "90.000 мм"
    dialog._undo()
    assert tuple(canvas.draft.entities) == original and len(canvas.draft.dimensions) == 1
    dialog._saved = dialog._document()


def test_dimension_style_incompatible_selection_is_rejected(qtbot):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((0, 0))
    canvas.add_point((50, 0))
    dialog.tool.setCurrentIndex(10)
    dialog.dimension_style.setCurrentIndex(4)  # диаметр не отрезка
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((25, 0)).toPoint())
    assert canvas.dimension_target is None and not canvas.draft.dimensions
    assert "не подходит" in dialog.status.text()
    dialog._saved = dialog._document()


def test_pending_dimension_undo_and_save_are_safe(qtbot, monkeypatch):
    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((0, 0))
    canvas.add_point((50, 0))
    dialog.tool.setCurrentIndex(10)
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=canvas.to_screen((25, 0)).toPoint())
    assert canvas.dimension_target == 0
    warnings = []
    monkeypatch.setattr(QMessageBox, "warning", lambda *args: warnings.append(args))
    assert not dialog._save() and not dialog._export_dxf()
    dialog._check_contours()
    assert len(warnings) == 3
    dialog._undo()
    assert canvas.dimension_target is None and len(canvas.draft.entities) == 1
    dialog._undo()
    assert not canvas.draft.entities
    dialog._redo()
    assert len(canvas.draft.entities) == 1
    dialog._saved = dialog._document()


def test_click_dimension_label_edits_geometry_and_undo(qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    canvas = dialog.canvas
    canvas.add_point((0, 0))
    canvas.add_point((50, 0))
    canvas.draft.add_dimension(0, (25, 20), "auto")
    monkeypatch.setattr(QInputDialog, "getDouble", lambda *args, **kwargs: (80, True))
    position = canvas._dimension_label_rect(canvas.draft.dimensions[0]).center().toPoint()
    qtbot.mouseClick(canvas, Qt.MouseButton.LeftButton, pos=position)
    assert canvas.draft.entities[0].size == 80
    assert canvas.pending is None
    dialog._undo()
    assert canvas.draft.entities[0].size == 50
    dialog._redo()
    assert canvas.draft.entities[0].size == 80
    dialog._saved = dialog._document()


def test_extrusion_opens_preview_and_preserves_sketch(qtbot, monkeypatch):
    from PySide6.QtWidgets import QInputDialog

    from suspensionlab.ui.sketch_draft_dialog import SketchExtrusionPreview

    dialog = SketchDraftDialog()
    qtbot.addWidget(dialog)
    dialog.show()
    dialog.tool.setCurrentIndex(3)
    dialog.canvas.add_point((0, 0))
    dialog.canvas.add_point((50, 25))
    original = dialog._document()
    monkeypatch.setattr(QInputDialog, "getDouble", lambda *args, **kwargs: (10, True))
    captured = []
    def fake_exec(preview):
        captured.append(preview.view.mesh)
        assert not preview.view.grab().isNull()
        return 0
    monkeypatch.setattr(SketchExtrusionPreview, "exec", fake_exec)
    dialog._extrude_preview()
    assert captured[0] is not None and len(captured[0].triangles) == 12
    assert dialog._document() == original
    dialog._saved = original
