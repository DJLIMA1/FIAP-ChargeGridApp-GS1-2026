"""On-screen panel/totem text never mentions simulation, demo or test payment.

Scans the string literals that reach the LCD (the kiosk strings table, the panel UI, the totem
views and the kiosk flow), skipping comments. Contract tokens the server sends and the firmware
only keeps in its model (never drawn) are allowed explicitly.
"""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
FIRMWARE = ROOT / "firmware/esp32"
SCREEN_SOURCES = [
    FIRMWARE / "include/ui/strings_ptbr.h",
    FIRMWARE / "src/panel_ui.cpp",
    FIRMWARE / "src/kiosk_flow.cpp",
    *sorted((FIRMWARE / "src/ui").glob("*.cpp")),
]
FORBIDDEN = re.compile(r"simulad|simulaç|\bdemo\b|demonstra|modo teste|\bteste\b|modo apresenta|ilustrativ", re.IGNORECASE)
# Contract values (kiosk_flow.cpp labelFrom/methodFrom): parsed, stored in the model, not rendered.
PROTOCOL_TOKENS = {"SIMULADO", "TESTE", "simulated"}


def string_literals(source):
    """C++ string literals outside comments (plain, prefixed and raw)."""
    literals, i, n = [], 0, len(source)
    while i < n:
        if source.startswith("//", i):
            i = source.find("\n", i)
            i = n if i < 0 else i
        elif source.startswith("/*", i):
            end = source.find("*/", i + 2)
            i = n if end < 0 else end + 2
        elif source[i] == "'":
            i += 1
            while i < n and source[i] != "'":
                i += 2 if source[i] == "\\" else 1
            i += 1
        elif source.startswith('R"', i) and (i == 0 or not (source[i - 1].isalnum() or source[i - 1] == "_")):
            open_paren = source.find("(", i + 2)
            delimiter = source[i + 2:open_paren]
            close = source.find(")" + delimiter + '"', open_paren)
            literals.append(source[open_paren + 1:close])
            i = close + len(delimiter) + 2
        elif source[i] == '"':
            j, chunk = i + 1, []
            while j < n and source[j] != '"':
                if source[j] == "\\":
                    chunk.append(source[j:j + 2])
                    j += 2
                else:
                    chunk.append(source[j])
                    j += 1
            literals.append("".join(chunk))
            i = j + 1
        else:
            i += 1
    return literals


def test_literal_scanner_skips_comments_and_reads_raw_strings():
    sample = '// "simulado"\n/* "TESTE" */ x = "a\\"b"; y = R"J({"k":1})J"; c = \'"\'; z = "ok";'
    assert string_literals(sample) == ['a\\"b', '{"k":1}', "ok"]


def test_screen_strings_have_no_simulation_demo_or_test_wording():
    offenders = []
    for path in SCREEN_SOURCES:
        for literal in string_literals(path.read_text(encoding="utf-8")):
            if literal in PROTOCOL_TOKENS:
                continue
            if FORBIDDEN.search(literal):
                offenders.append(f"{path.relative_to(ROOT)}: {literal!r}")
    assert offenders == []


def test_the_strings_table_is_scanned():
    table = string_literals((FIRMWARE / "include/ui/strings_ptbr.h").read_text(encoding="utf-8"))
    assert "Iniciar recarga" in table and "Sem cobrança" in table
    assert "Sem o app? Pague aqui" in string_literals((FIRMWARE / "src/panel_ui.cpp").read_text(encoding="utf-8"))
