"""Die Windows-Startdateien müssen auf Windows laufen.

Beim Erzeugen über eine Unix-Shell wurde `>nul` still zu `>/dev/null`.
Auf Windows ist das ein ungültiger Pfad: Beim Doppelklick erschien nur
"Pfad nicht gefunden", ohne erkennbaren Zusammenhang. Prüfbar war das
nicht, weil Batch sich hier nicht ausführen lässt - also wird wenigstens
der Inhalt geprüft.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "tools"))

from erzeuge_startdateien import DATEIEN, ZIEL, pruefe  # noqa: E402


def test_alle_startdateien_sind_windowstauglich():
    fehler = pruefe()
    assert not fehler, "\n".join(fehler)


@pytest.mark.parametrize("name", sorted(DATEIEN))
def test_keine_unix_umleitung(name):
    """Der konkrete Fehler, der zwei Abende gekostet hat."""
    inhalt = (ZIEL / name).read_text(encoding="utf-8")
    assert "/dev/null" not in inhalt


@pytest.mark.parametrize("name", sorted(DATEIEN))
def test_python_wird_gefunden_auch_ohne_py(name):
    """Nicht jeder Rechner kennt `py`; dann muss `python` einspringen."""
    inhalt = (ZIEL / name).read_text(encoding="utf-8")
    assert "if errorlevel 1 set PY=python" in inhalt


def test_die_erzeugten_dateien_entsprechen_der_vorlage():
    """Von Hand geändert? Dann fällt es hier auf, nicht beim Nutzer."""
    from erzeuge_startdateien import DATEIEN as vorlage

    for name, inhalt in vorlage.items():
        erwartet = (inhalt + "\n").replace("\n", "\r\n").encode("utf-8")
        assert (ZIEL / name).read_bytes() == erwartet, f"{name} weicht ab"
