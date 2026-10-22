"""Panel packaging and physical QA name the firmware version the panel really reports."""
import ast
import re
from pathlib import Path

from tools import package_panel

ROOT = Path(__file__).resolve().parents[2]


def _runtime_version():
    runtime = (ROOT / "firmware/esp32/include/runtime.h").read_text()
    return re.search(r'#define CHARGEGRID_FIRMWARE_VERSION "([^"]+)"', runtime).group(1)


def _constant(path, name):
    # qa_panel_reboot imports pyserial at module level: read the constant without importing it.
    for node in ast.parse(path.read_text()).body:
        if isinstance(node, ast.Assign) and any(getattr(target, "id", None) == name for target in node.targets):
            return ast.literal_eval(node.value)
    raise AssertionError(f"{name} not found in {path}")


def test_package_and_reboot_qa_use_the_firmware_version_from_runtime_h():
    assert _runtime_version() == "0.9.7"
    assert package_panel.FIRMWARE_VERSION == _runtime_version()
    assert _constant(ROOT / "tools/qa_panel_reboot.py", "FIRMWARE_VERSION") == _runtime_version()


def test_no_stale_firmware_version_is_left_in_the_tools():
    for name in ("package_panel.py", "qa_panel_reboot.py"):
        text = (ROOT / "tools" / name).read_text()
        assert not re.search(r"0\.3\.\d", text), name
    source = (ROOT / "tools/package_panel.py").read_text()
    assert 'f"builds/chargegrid-waveshare-7-{FIRMWARE_VERSION}.zip"' in source
    assert "# ChargeGrid panel {FIRMWARE_VERSION}" in source
    # The status line the reboot QA matches is the one main.cpp prints.
    main = (ROOT / "firmware/esp32/src/main.cpp").read_text()
    assert "[status] state=%s " in main and "firmware=%s\\n" in main
