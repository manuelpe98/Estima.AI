"""Confronto tra stato di fatto e stato di progetto, per le ristrutturazioni."""
from __future__ import annotations
from .models import RoomQuantity, RoomComparison

AREA_TOLLERANZA_M2 = 1.0


def compare_stati(rooms_sdf: list[RoomQuantity], rooms_sdp: list[RoomQuantity]) -> list[RoomComparison]:
    sdf_by_label = {r.label.upper(): r for r in rooms_sdf}
    sdp_by_label = {r.label.upper(): r for r in rooms_sdp}
    labels = set(sdf_by_label) | set(sdp_by_label)

    result = []
    for label in sorted(labels):
        sdf = sdf_by_label.get(label)
        sdp = sdp_by_label.get(label)
        if sdf and not sdp:
            stato = "demolito"
        elif sdp and not sdf:
            stato = "nuovo"
        elif abs(sdf.area_m2 - sdp.area_m2) > AREA_TOLLERANZA_M2:
            stato = "superficie_variata"
        else:
            stato = "invariato"
        result.append(RoomComparison(
            label=label,
            area_sdf_m2=sdf.area_m2 if sdf else None,
            area_sdp_m2=sdp.area_m2 if sdp else None,
            stato=stato,
        ))
    return result
