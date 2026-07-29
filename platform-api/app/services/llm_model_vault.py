"""Model vault: staged download, disk accounting, and atomic move.

All artifact files land under the configured vault path. Temporary downloads
live in a per-job directory and are atomically moved into the artifact folder
only after scanning and manifest signing succeed. Quarantine on any failure.
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass
from pathlib import Path

from app.config import get_settings


class VaultError(Exception):
    """Raised when a vault operation cannot be completed safely."""


@dataclass(frozen=True)
class ArtifactPaths:
    artifact_dir: Path
    storage_path: Path
    relative_path: str


class ModelVault:
    """Local storage manager for model artifact files."""

    def __init__(self, base_path: str | None = None, max_bytes: int | None = None) -> None:
        settings = get_settings()
        self.base_path = Path(base_path or settings.llm_model_vault_path)
        self.max_bytes = max_bytes if max_bytes is not None else settings.llm_model_vault_max_bytes
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _artifact_dir(self, artifact_id: int) -> Path:
        return self.base_path / "artifacts" / str(artifact_id)

    def storage_path(self, artifact_id: int, filename: str) -> Path:
        """Resolved, absolute storage path for an artifact file."""
        if "/" in filename or "\\" in filename or filename.startswith("."):
            raise VaultError("Invalid artifact filename")
        dest = self._artifact_dir(artifact_id) / filename
        resolved = dest.resolve()
        # Ensure the destination cannot escape the vault base path.
        if not str(resolved).startswith(str(self.base_path.resolve())):
            raise VaultError("Artifact path escapes vault root")
        return resolved

    def temp_dir(self) -> Path:
        """Create a temporary per-job directory inside the vault."""
        temp = Path(tempfile.mkdtemp(prefix="stage-", dir=str(self.base_path / "tmp")))
        return temp

    def _total_vault_bytes(self) -> int:
        total = 0
        for dirpath, _dirnames, filenames in os.walk(self.base_path):
            for f in filenames:
                fp = os.path.join(dirpath, f)
                try:
                    total += os.path.getsize(fp)
                except OSError:
                    pass
        return total

    def reserve_space(self, required_bytes: int) -> None:
        """Assert the vault can fit another artifact."""
        if required_bytes > self.max_bytes:
            raise VaultError(
                f"Artifact size {required_bytes} exceeds vault max {self.max_bytes}"
            )
        current = self._total_vault_bytes()
        # Allow up to twice the artifact size during staging (temp + final).
        if current + required_bytes * 2 > self.max_bytes:
            raise VaultError("Vault quota exceeded")

    def assert_disk_space(self, path: Path, required_bytes: int) -> None:
        """Check that ``path``'s filesystem has at least ``required_bytes`` free."""
        try:
            stat = shutil.disk_usage(path)
        except OSError as exc:
            raise VaultError(f"Cannot read disk usage for {path}: {exc}") from exc
        # Keep a 5 GiB reserve.
        if stat.free < required_bytes + 5 * 1024 * 1024 * 1024:
            raise VaultError(f"Insufficient disk space at {path}: {stat.free} bytes free")

    def atomic_move(self, source: Path, destination: Path) -> None:
        """Move a fully verified file into its final artifact location atomically."""
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Do not overwrite an existing verified file.
        if destination.exists():
            raise VaultError(f"Artifact file already exists: {destination}")
        shutil.move(str(source), str(destination))

    def remove_temp(self, temp: Path) -> None:
        if temp.exists():
            shutil.rmtree(temp, ignore_errors=True)
