"""
Private file storage for prescription files.

Files live under PRIVATE_STORAGE_DIR, which is never served as static/media. Names are
random (the client's file name is never used on disk). Every path is resolved and checked
to be inside the storage root, so a bad stored path cannot read or delete other files.
"""
import hashlib
import os
import re
import uuid
from pathlib import Path

ALLOWED_EXTENSIONS = {"jpg", "png", "pdf"}
_SAFE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")


class StorageError(Exception):
    pass


class FileStorage:
    def __init__(self, root: Path):
        self.root = Path(root)

    def _resolve(self, relative: str) -> Path:
        if not isinstance(relative, str) or not relative or relative.startswith(("/", "\\")) or ".." in Path(relative).parts:
            raise StorageError("Invalid storage path.")
        root = self.root.resolve()
        path = (root / relative).resolve()
        if root not in path.parents:
            raise StorageError("Invalid storage path.")
        return path

    def save(self, user_id: str, ext: str, data: bytes) -> tuple[str, str]:
        """Writes a new private file. Returns (relative_path, sha256_hex)."""
        if not _SAFE_ID.match(user_id or ""):
            raise StorageError("Invalid user id.")
        if ext not in ALLOWED_EXTENSIONS:
            raise StorageError("Invalid file extension.")
        relative = f"prescriptions/{user_id}/{uuid.uuid4().hex}.{ext}"
        path = self._resolve(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "xb") as handle:       # "x": never overwrite an existing file
            handle.write(data)
        try:
            os.chmod(path, 0o600)              # owner-only where the OS supports it
        except OSError:
            pass
        return relative, hashlib.sha256(data).hexdigest()

    def read(self, relative: str) -> bytes:
        path = self._resolve(relative)
        try:
            return path.read_bytes()
        except FileNotFoundError as exc:
            raise StorageError("File not found.") from exc

    def delete(self, relative: str) -> bool:
        path = self._resolve(relative)
        try:
            path.unlink()
            return True
        except FileNotFoundError:
            return False
