from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import PurePosixPath
from zipfile import BadZipFile, ZipFile

MAX_ARCHIVE_ENTRIES = 500
MAX_COMPRESSED_BYTES = 75 * 1024 * 1024
MAX_EXPANDED_BYTES = 300 * 1024 * 1024
SUPPORTED_SUFFIXES = {".psd", ".pdf", ".jpg", ".jpeg", ".png"}
IGNORED_NAMES = {".ds_store", "thumbs.db"}


class ArchiveError(ValueError):
    pass


@dataclass(frozen=True)
class ArchiveEntry:
    path: str
    data: bytes


def _safe_path(name: str) -> PurePosixPath:
    path = PurePosixPath(name.replace("\\", "/"))
    if path.is_absolute() or ".." in path.parts or any(part.endswith(":") for part in path.parts):
        raise ArchiveError(f"Archive contains an unsafe path: {name}")
    return path


def read_artwork_archive(data: bytes) -> list[ArchiveEntry]:
    if len(data) > MAX_COMPRESSED_BYTES:
        raise ArchiveError("ZIP exceeds the 75 MB upload limit.")
    try:
        with ZipFile(BytesIO(data)) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ARCHIVE_ENTRIES:
                raise ArchiveError("ZIP contains too many entries.")
            if sum(info.file_size for info in infos) > MAX_EXPANDED_BYTES:
                raise ArchiveError("ZIP expands beyond the 300 MB limit.")
            entries = []
            for info in infos:
                path = _safe_path(info.filename)
                if info.flag_bits & 0x1:
                    raise ArchiveError("Encrypted ZIP entries are not supported.")
                if info.is_dir() or "__MACOSX" in path.parts or path.name.lower() in IGNORED_NAMES:
                    continue
                if path.suffix.lower() == ".zip":
                    raise ArchiveError("A nested archive is not supported.")
                if path.suffix.lower() in SUPPORTED_SUFFIXES:
                    entries.append(ArchiveEntry(path.as_posix(), archive.read(info)))
            return entries
    except BadZipFile as exc:
        raise ArchiveError("The uploaded file is not a valid ZIP archive.") from exc
