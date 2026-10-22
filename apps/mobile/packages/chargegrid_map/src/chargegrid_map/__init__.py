"""OpenFreeMap vector map and pointer-safe overlays for Flet."""
from dataclasses import field
from typing import Optional

import flet as ft


@ft.control('ChargeGridVectorMap')
class VectorMap(ft.LayoutControl):
    latitude: float = -23.5505
    longitude: float = -46.6333
    zoom: float = 13
    camera_revision: int = 0
    style_json: str = ''
    markers: list[dict] = field(default_factory=list)
    selected: Optional[str] = None
    interactive: bool = True
    credit_bottom: float = 8
    on_select: Optional[ft.ControlEventHandler['VectorMap']] = None
    on_camera: Optional[ft.ControlEventHandler['VectorMap']] = None
    on_ready: Optional[ft.ControlEventHandler['VectorMap']] = None


@ft.control('ChargeGridMapOverlay')
class MapOverlay(ft.LayoutControl):
    content: Optional[ft.Control] = None
