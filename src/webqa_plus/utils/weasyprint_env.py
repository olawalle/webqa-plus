"""Runtime environment helpers for WeasyPrint native libraries."""

import os
import platform
from pathlib import Path


def configure_weasyprint_env() -> None:
    """Ensure macOS can locate Homebrew libs required by WeasyPrint."""
    if platform.system().lower() != "darwin":
        return

    candidates = [
        Path("/opt/homebrew/lib"),
        Path("/usr/local/lib"),
    ]

    existing = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
    current_entries = [entry for entry in existing.split(":") if entry]

    merged = list(current_entries)
    for path in candidates:
        if path.exists():
            path_str = str(path)
            if path_str not in merged:
                merged.append(path_str)

    if merged:
        os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = ":".join(merged)
