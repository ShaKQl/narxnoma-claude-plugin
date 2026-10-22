"""Drive Excel through COM (PowerShell) to add PivotTables and to verify a workbook."""

import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent


class ExcelUnavailable(RuntimeError):
    pass


@dataclass
class ComResult:
    ok: bool
    lines: list[str] = field(default_factory=list)

    @property
    def warnings(self) -> list[str]:
        return [ln for ln in self.lines if ln.startswith("WARN")]

    @property
    def model(self) -> str:
        return next((ln[6:] for ln in self.lines if ln.startswith("MODEL ")), "")

    def __str__(self) -> str:
        return "\n".join(self.lines)


def excel_available() -> bool:
    """True when this is Windows, PowerShell is present and the Excel COM class is registered.
    Checked through the registry: starting Excel just to ask costs seconds and may pop a dialog."""
    if sys.platform != "win32" or not shutil.which("powershell"):
        return False
    probe = subprocess.run(
        [
            "powershell",
            "-NoProfile",
            "-Command",
            "if (Test-Path 'Registry::HKEY_CLASSES_ROOT\\Excel.Application') {'yes'} else {'no'}",
        ],
        capture_output=True,
        text=True,
        timeout=60,
    )
    return probe.stdout.strip() == "yes"


def _run(script: str, args: list[str], timeout: int) -> ComResult:
    if not excel_available():
        raise ExcelUnavailable(
            "desktop Excel is not available here (needs Windows + Excel); "
            "use the raw-OOXML pivots or open the workbook and Insert > PivotTable"
        )
    cmd = [
        "powershell",
        "-NoProfile",
        "-ExecutionPolicy",
        "Bypass",
        "-File",
        str(HERE / script),
        *args,
    ]
    p = subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout
    )
    lines = [ln.rstrip() for ln in (p.stdout or "").splitlines() if ln.strip()]
    if p.returncode != 0:
        lines.append(
            "FAILED " + (p.stderr or "").strip().splitlines()[0] if p.stderr.strip() else "FAILED"
        )
    return ComResult(ok=p.returncode == 0, lines=lines)


def add_pivots(
    path: str | Path, out: str | Path | None = None, model: str = "auto", timeout: int = 600
) -> ComResult:
    """Flat PivotTables + slicers + chart; Data Model when `model` allows and Excel has it."""
    args = ["-Path", str(Path(path).resolve()), "-Model", model]
    if out:
        args += ["-Out", str(Path(out).resolve())]
    return _run("pivots.ps1", args, timeout)


def verify(path: str | Path, probe: str = "", save: bool = False, timeout: int = 300) -> ComResult:
    """Let Excel open and recalculate the workbook, then report formula errors, tables, pivots,
    slicers and conditional-format rule counts. `save=True` also bakes the calculated values in,
    so viewers that cannot calculate (previews, pandas) see numbers."""
    args = ["-Path", str(Path(path).resolve())]
    if probe:
        args += ["-Probe", probe]
    if save:
        args.append("-Save")
    return _run("verify.ps1", args, timeout)


def error_count(result: ComResult) -> int | None:
    for ln in result.lines:
        if ln.startswith("ERRORS_TOTAL"):
            return int(ln.split()[1])
    return None
