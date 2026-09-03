from __future__ import annotations

import io
from dataclasses import asdict, dataclass
from pathlib import PurePosixPath

from PIL import Image

from artwork_archive import ArchiveEntry, read_artwork_archive
from artwork_matching import candidate_score, classify_candidate, required_positions
from artwork_rendering import ArtworkRenderError, RenderedArtwork, render_artwork
from extract_to_plan_sheet import extract_artwork_crops_bytes


@dataclass(frozen=True)
class ManifestRecord:
    contract: str
    position: str
    status: str
    path: str | None = None
    detail: str | None = None

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PackageResolution:
    slots: dict[tuple[str, str], bytes]
    records: tuple[ManifestRecord, ...]
    ignored: tuple[str, ...]


def _png_artwork(data: bytes) -> RenderedArtwork:
    with Image.open(io.BytesIO(data)) as image:
        return RenderedArtwork(data, image.width, image.height)


def resolve_artwork_package(data: bytes, format_key: str, contracts: set[str]) -> PackageResolution:
    entries = read_artwork_archive(data)
    classified = [(entry, classify_candidate(entry.path, contracts, format_key)) for entry in entries]
    slots: dict[tuple[str, str], bytes] = {}
    records = []
    used_paths: set[str] = set()

    for contract in sorted(contracts):
        full_sheet_entries = [
            entry for entry, candidate in classified
            if candidate.contract == contract and candidate.position is None
            and PurePosixPath(entry.path).suffix.lower() in {".jpg", ".jpeg", ".png"}
        ]
        for position in required_positions(format_key):
            pool = [
                (entry, candidate) for entry, candidate in classified
                if candidate.contract == contract and candidate.position == position and not candidate.ambiguous
            ]
            pool.sort(key=lambda pair: candidate_score(pair[1]), reverse=True)
            if len(pool) > 1 and candidate_score(pool[0][1]) == candidate_score(pool[1][1]):
                records.append(ManifestRecord(contract, position, "ambiguous", detail=", ".join(item.path for item, _ in pool)))
                continue
            failures = []
            selected = None
            for entry, _candidate in pool:
                try:
                    selected = (entry, render_artwork(entry), "matched")
                    break
                except ArtworkRenderError as exc:
                    failures.append(f"{entry.path}: {exc}")

            if selected is None and position in {"front", "back"}:
                for entry in full_sheet_entries:
                    crops = extract_artwork_crops_bytes(entry.data)
                    if crops:
                        selected = (entry, _png_artwork(crops[0 if position == "front" else 1]), "fallback")
                        break

            if selected:
                entry, rendered, status = selected
                slots[(contract, position)] = rendered.png
                used_paths.add(entry.path)
                records.append(ManifestRecord(contract, position, status, entry.path, "; ".join(rendered.warnings) or None))
            else:
                records.append(ManifestRecord(contract, position, "unreadable" if pool else "missing", detail="; ".join(failures) or None))

    ignored = tuple(entry.path for entry in entries if entry.path not in used_paths)
    return PackageResolution(slots, tuple(records), ignored)
