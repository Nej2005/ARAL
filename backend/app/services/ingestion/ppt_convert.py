"""Legacy .ppt -> .pptx through LibreOffice headless (BACKEND.md §5.2)."""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from app.config import settings


class PptConversionUnavailable(Exception):
    pass


class PptConversionFailed(Exception):
    pass


def _soffice() -> str | None:
    cand = settings.soffice_path or "soffice"
    if Path(cand).is_file():
        return cand
    return shutil.which(cand)


def convert_ppt_to_pptx(src: str | Path) -> Path:
    """Returns the path of a .pptx next to `src` (same stem)."""
    exe = _soffice()
    if not exe:
        raise PptConversionUnavailable("LibreOffice (soffice) was not found.")
    src = Path(src)
    outdir = Path(tempfile.mkdtemp(prefix="ppt2pptx_"))
    try:
        res = subprocess.run(
            [exe, "--headless", "--convert-to", "pptx", "--outdir", str(outdir), str(src)],
            capture_output=True, text=True, timeout=180,
        )
    except (subprocess.TimeoutExpired, OSError) as e:
        raise PptConversionFailed(str(e)) from e
    produced = outdir / (src.stem + ".pptx")
    if res.returncode != 0 or not produced.exists():
        raise PptConversionFailed((res.stderr or res.stdout or "conversion failed").strip()[:500])
    dest = src.with_suffix(".pptx")
    shutil.move(str(produced), str(dest))
    shutil.rmtree(outdir, ignore_errors=True)
    return dest
