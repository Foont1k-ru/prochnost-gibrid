"""Отчёт пробного совмещения с полными координатами и диагностикой пар."""
from __future__ import annotations

from collections.abc import Callable

from ..core.cad_registration import RegistrationEvaluation
from ..core.cad_source_guard import SourceSummary
from ..model.point_csv import PointRecord
from .csv_report import CSVReport


def registration_report(result: RegistrationEvaluation, records: tuple[PointRecord, ...],
                        cad: tuple[tuple[float, float, float], ...], fit_mask: tuple[bool, ...],
                        translate: Callable[[str], str], sources: tuple[str, ...] | None = None,
                        source_check: SourceSummary | None = None) -> CSVReport:
    if sources is None:
        sources = ("manual_or_edited",) * len(cad)
    if not (len(records) == len(cad) == len(fit_mask) == len(result.points) == len(sources)):
        raise ValueError("Несогласованные данные отчёта")
    if any(source not in ("manual_or_edited", "surface_preview") for source in sources):
        raise ValueError("Несогласованные данные отчёта")
    if source_check is not None and (source_check.has_conflict or
                                     source_check.known_points != sources.count("surface_preview") or
                                     source_check.unknown_points != sources.count("manual_or_edited") or
                                     source_check.distinct_sources != (1 if source_check.known_points else 0)):
        raise ValueError("Несогласованная проверка источников")
    t = translate
    tf = result.fit.transform
    metadata = [(t("cad_registration.report_notice"), t("cad_registration.output")),
                (t("cad_registration.report_direction"), "CAD_mm -> project_mm"),
                ("fit_count", str(sum(fit_mask))), ("control_count", str(len(fit_mask) - sum(fit_mask))),
                ("fit_rms_mm", repr(result.fit.rms_mm)), ("fit_max_mm", repr(result.fit.max_mm)),
                ("control_rms_mm", "" if result.control_rms_mm is None else repr(result.control_rms_mm)),
                ("control_max_mm", "" if result.control_max_mm is None else repr(result.control_max_mm))]
    if source_check is not None:
        metadata.extend((("surface_points_with_digest", str(source_check.known_points)),
                         ("manual_or_edited_unverified", str(source_check.unknown_points)),
                         ("distinct_surface_content_at_load", str(source_check.distinct_sources)),
                         (t("cad_registration.report_source_warning"), t("cad_registration.source_check_warning"))))
    metadata.append((t("cad_registration.distance_report_warning"), t("cad_registration.distance_warning")))
    for prefix, comparison in (("fit_segments", result.fit_distances),
                               ("control_segments", result.control_distances)):
        metadata.append((f"{prefix}_count", str(comparison.count if comparison else 0)))
        if comparison is not None:
            metadata.extend(((f"{prefix}_rms_difference_mm", repr(comparison.rms_difference_mm)),
                             (f"{prefix}_worst_row_1", str(comparison.first_row + 1)),
                             (f"{prefix}_worst_row_2", str(comparison.second_row + 1)),
                             (f"{prefix}_worst_cad_length_mm", repr(comparison.cad_length_mm)),
                             (f"{prefix}_worst_project_length_mm", repr(comparison.project_length_mm)),
                             (f"{prefix}_worst_project_minus_cad_mm", repr(comparison.difference_mm))))
    metadata.extend((f"R{i + 1}{j + 1}", repr(tf.rotation[i][j])) for i in range(3) for j in range(3))
    metadata.extend((f"t_{axis}_mm", repr(value)) for axis, value in zip("xyz", tf.translation, strict=True))
    rows = []
    for row, (record, point, selected, residual, source) in enumerate(zip(records, cad, fit_mask, result.points, sources, strict=True), 1):
        name = t(record.name_key) if record.name_key else record.code
        rows.append((str(row), "fit" if selected else "control", record.role, record.type_code, record.code,
                     name, record.representation, source, *(repr(v) for v in point), *(repr(v) for v in record.xyz),
                     *(repr(v) for v in residual.predicted_mm), *(repr(v) for v in residual.delta_mm),
                     repr(residual.distance_mm)))
    columns = ("row", "purpose", "axle", "axle_type", "point_code", "point_name", "representation",
               "cad_input", "cad_x_mm", "cad_y_mm", "cad_z_mm", "project_x_mm", "project_y_mm", "project_z_mm",
               "transformed_cad_x_mm", "transformed_cad_y_mm", "transformed_cad_z_mm",
               "delta_x_mm", "delta_y_mm", "delta_z_mm", "distance_mm")
    return CSVReport(tuple(metadata), columns, tuple(rows))
