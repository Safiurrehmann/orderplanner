from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import PurePosixPath


@dataclass(frozen=True)
class ArtworkPosition:
    name: str
    folders: tuple[str, ...]
    prefixes: tuple[str, ...]


@dataclass(frozen=True)
class PackageCandidate:
    path: str
    contract: str | None
    position: str | None
    kind: str
    team_confidence: int
    placement_confidence: int
    ambiguous: bool = False


FORMAT_POSITIONS = {
    "flannigan": (ArtworkPosition("front", ("art", "artwork", "front", "chest"), ("emlnf", "embl")),),
    "mocktail": (
        ArtworkPosition("back", ("back",), ("apfgn",)),
        ArtworkPosition("front", ("front", "chest"), ("emlnf",)),
    ),
    "belvedere": (
        ArtworkPosition("back", ("back",), ("apfgn",)),
        ArtworkPosition("front", ("front", "chest"), ("emlnf",)),
        ArtworkPosition("hood", ("hood", "head"), ("embl",)),
    ),
}
QUALITY = {"psd": 4, "pdf": 3, "png": 2, "jpg": 2, "jpeg": 2}


def required_positions(format_key: str) -> tuple[str, ...]:
    return tuple(position.name for position in FORMAT_POSITIONS[format_key])


def _tokens(value: str) -> set[str]:
    return {token for token in re.split(r"[^a-z0-9]+", value.lower()) if token}


def classify_candidate(path: str, contracts: set[str], format_key: str) -> PackageCandidate:
    normalized = re.sub(r"[^A-Z0-9]", "", path.upper())
    filename = PurePosixPath(path).name
    exact = {contract for contract in contracts if contract in normalized}
    short = set()
    for contract in contracts:
        team = contract[:3]
        delimited = re.search(rf"(?:^|[^A-Z0-9]){re.escape(team)}(?:[^A-Z0-9]|$)", path.upper())
        prefixed = any(
            prefix.upper() + team in normalized
            for position in FORMAT_POSITIONS[format_key]
            for prefix in position.prefixes
        )
        if delimited or prefixed:
            short.add(contract)
    matches = exact or short
    contract = next(iter(matches)) if len(matches) == 1 else None
    team_confidence = 2 if exact and contract else 1 if contract else 0

    folder_tokens = set().union(*(_tokens(part) for part in PurePosixPath(path).parts[:-1])) if PurePosixPath(path).parts[:-1] else set()
    filename_key = re.sub(r"[^a-z0-9]", "", filename.lower())
    folder_positions = {position.name for position in FORMAT_POSITIONS[format_key] if folder_tokens.intersection(position.folders)}
    prefix_positions = {position.name for position in FORMAT_POSITIONS[format_key] if any(prefix in filename_key for prefix in position.prefixes)}
    conflict = bool(folder_positions and prefix_positions and folder_positions != prefix_positions)
    possible = prefix_positions or folder_positions
    if not possible and len(FORMAT_POSITIONS[format_key]) == 1 and contract:
        possible = {FORMAT_POSITIONS[format_key][0].name}
    position = next(iter(possible)) if len(possible) == 1 and not conflict else None
    return PackageCandidate(
        path=path, contract=contract, position=position,
        kind=PurePosixPath(filename).suffix.lower().lstrip("."),
        team_confidence=team_confidence,
        placement_confidence=2 if prefix_positions and position else 1 if position else 0,
        ambiguous=conflict or len(matches) > 1 or len(possible) > 1,
    )


def candidate_score(candidate: PackageCandidate) -> tuple[int, int, int]:
    return (candidate.team_confidence, candidate.placement_confidence, QUALITY.get(candidate.kind, 0))


def rank_candidates(candidates: list[PackageCandidate]) -> tuple[PackageCandidate | None, bool]:
    eligible = [candidate for candidate in candidates if candidate.contract and candidate.position and not candidate.ambiguous]
    if not eligible:
        return None, False
    ranked = sorted(eligible, key=candidate_score, reverse=True)
    tied = len(ranked) > 1 and candidate_score(ranked[0]) == candidate_score(ranked[1])
    return (None if tied else ranked[0]), tied
