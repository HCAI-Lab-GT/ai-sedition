"""Environment loading for model construction."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv


def load_project_dotenv(root: Path | None = None) -> bool:
    """Load a dotenv file only from an explicit project workspace."""
    if root is None:
        workspace = os.environ.get("AI_SEDITION_WORKSPACE")
        if not workspace:
            return False
        root = Path(workspace)
    dotenv_path = root.expanduser().resolve() / ".env"
    if not dotenv_path.is_file():
        return False
    return bool(load_dotenv(dotenv_path))
