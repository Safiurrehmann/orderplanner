# ZIP Artwork Package Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace loose JPG artwork uploads with one safe ZIP-package upload that resolves PSD/PDF/raster artwork to the correct purchase-order team and garment position, with structural JPG extraction as fallback.

**Architecture:** Introduce focused archive, matching, rendering, and resolution modules. `server.py` will coordinate these modules and pass normalized PNG bytes to the existing workbook insertion code; the browser will upload one ZIP and display a slot-level manifest returned by the server.

**Tech Stack:** Python 3.9+, FastAPI, OpenPyXL, Pillow, PyMuPDF, standard-library `zipfile`, vanilla JavaScript, `unittest`.

**Spec:** `docs/superpowers/specs/2026-09-03-zip-artwork-package-design.md`

## Global Constraints

- Station 1 and the three workbook templates remain unchanged.
- Station 2 accepts one `.zip` package rather than loose artwork files.
- Source priority is decodable PSD, PDF, isolated raster, then full spec-sheet raster fallback.
- Ambiguous team or placement matches are reported and never guessed.
- Full-sheet JPG extraction uses structural panel detection and rejects blank crops.
- The supplied approximately 40 MB Belvedere ZIP must be accepted.
- ZIP processing must reject traversal, absolute paths, encryption, nested archives, excessive entries, and excessive expanded size.
- Generated images preserve aspect ratio and remain within each configured Excel display box.

## File Structure

- Create `artwork_archive.py`: safe in-memory ZIP validation and entry enumeration.
- Create `artwork_matching.py`: format position definitions, path normalization, team/placement classification, and candidate ranking.
- Create `artwork_rendering.py`: PSD/PDF/raster decoding, trimming, blank validation, and PNG normalization.
- Create `artwork_package.py`: package-level resolution and manifest assembly.
- Modify `extract_to_plan_sheet.py`: expose format positions and keep spec-sheet panel extraction as fallback.
- Modify `server.py`: accept ZIP upload and enrich workbooks from resolved slots.
- Modify `static/index.html`: replace loose artwork input with package upload copy and controls.
- Modify `static/app.js`: ZIP validation, upload, and structured manifest rendering.
- Modify `README.md` and `requirements.txt`: document workflow and add the PDF-rendering dependency.
- Create `tests/test_artwork_archive.py`, `tests/test_artwork_matching.py`, `tests/test_artwork_rendering.py`, `tests/test_artwork_package.py`, and `tests/test_server_package.py`.
- Modify `tests/test_artwork_extraction.py`: preserve panel-fallback regression coverage.

---

### Task 1: Garment Positions and Deterministic Path Matching

**Files:**
- Create: `artwork_matching.py`
- Modify: `extract_to_plan_sheet.py`
- Test: `tests/test_artwork_matching.py`

**Interfaces:**
- Consumes: `WorkbookFormat.key`, purchase-order contract strings, and ZIP entry paths.
- Produces: `ArtworkPosition`, `PackageCandidate`, `FORMAT_POSITIONS`, `classify_candidate(path, contracts, format_key)`, and `rank_candidates(candidates)`.

- [ ] **Step 1: Write failing tests for format positions and name variations**

```python
# tests/test_artwork_matching.py
import unittest

from artwork_matching import classify_candidate, required_positions


class ArtworkMatchingTests(unittest.TestCase):
    def test_belvedere_uses_folder_and_embroidery_prefixes(self):
        contracts = {"UNC66804BCQ", "ECU66804BCQ"}
        candidate = classify_candidate(
            "PK73498/hood/AD EMBLUNC-6C.psd", contracts, "belvedere"
        )
        self.assertEqual("UNC66804BCQ", candidate.contract)
        self.assertEqual("hood", candidate.position)
        self.assertEqual("psd", candidate.kind)
        self.assertFalse(candidate.ambiguous)

    def test_flannigan_generic_artwork_folder_needs_no_position_marker(self):
        candidate = classify_candidate(
            "PO/Artwork/AD CAL-1C.jpg", {"CAL65999FGA"}, "flannigan"
        )
        self.assertEqual(("CAL65999FGA", "front"), (candidate.contract, candidate.position))

    def test_short_code_inside_unrelated_word_is_not_a_match(self):
        candidate = classify_candidate(
            "PO/Artwork/recall-notes.jpg", {"CAL65999FGA"}, "flannigan"
        )
        self.assertIsNone(candidate.contract)

    def test_conflicting_folder_and_filename_positions_are_ambiguous(self):
        candidate = classify_candidate(
            "PO/Hood/JR APFGNUNC-2C.pdf", {"UNC66804BCQ"}, "belvedere"
        )
        self.assertTrue(candidate.ambiguous)

    def test_required_positions_are_format_specific(self):
        self.assertEqual(("front",), required_positions("flannigan"))
        self.assertEqual(("back", "front"), required_positions("mocktail"))
        self.assertEqual(("back", "front", "hood"), required_positions("belvedere"))
```

- [ ] **Step 2: Run the matching tests and confirm the missing module failure**

Run: `./.venv/bin/python -m unittest tests.test_artwork_matching -v`

Expected: `ModuleNotFoundError: No module named 'artwork_matching'`.

- [ ] **Step 3: Implement format configuration and candidate classification**

```python
# artwork_matching.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
import re


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
    "flannigan": (ArtworkPosition("front", ("art", "artwork", "front", "chest"), ("emlnf",)),),
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


def required_positions(format_key: str) -> tuple[str, ...]:
    return tuple(position.name for position in FORMAT_POSITIONS[format_key])


def _tokens(value: str) -> tuple[str, ...]:
    return tuple(token for token in re.split(r"[^a-z0-9]+", value.lower()) if token)


def classify_candidate(path: str, contracts: set[str], format_key: str) -> PackageCandidate:
    normalized = re.sub(r"[^A-Z0-9]", "", path.upper())
    filename = PurePosixPath(path).name
    extension = PurePosixPath(filename).suffix.lower().lstrip(".")
    exact = [contract for contract in contracts if contract in normalized]
    short = [
        contract for contract in contracts
        if re.search(rf"(?:^|[^A-Z0-9]){re.escape(contract[:3])}(?:[^A-Z0-9]|$)", path.upper())
        or any(prefix.upper() + contract[:3] in normalized for position in FORMAT_POSITIONS[format_key] for prefix in position.prefixes)
    ]
    matches = exact or short
    contract = matches[0] if len(set(matches)) == 1 else None
    team_confidence = 2 if exact and contract else 1 if contract else 0

    folder_tokens = {token for part in PurePosixPath(path).parts[:-1] for token in _tokens(part)}
    filename_normalized = re.sub(r"[^a-z0-9]", "", filename.lower())
    folder_positions = {p.name for p in FORMAT_POSITIONS[format_key] if folder_tokens.intersection(p.folders)}
    prefix_positions = {p.name for p in FORMAT_POSITIONS[format_key] if any(prefix in filename_normalized for prefix in p.prefixes)}
    conflict = bool(folder_positions and prefix_positions and folder_positions != prefix_positions)
    possible = prefix_positions or folder_positions
    if not possible and len(FORMAT_POSITIONS[format_key]) == 1 and contract:
        possible = {FORMAT_POSITIONS[format_key][0].name}
    position = next(iter(possible)) if len(possible) == 1 and not conflict else None
    placement_confidence = 2 if prefix_positions and position else 1 if position else 0
    return PackageCandidate(path, contract, position, extension, team_confidence, placement_confidence, conflict or len(set(matches)) > 1 or len(possible) > 1)
```

Add a `positions: tuple[str, ...]` field to `WorkbookFormat`, populate it from the same canonical names, and assert during module initialization that it matches `required_positions(fmt.key)`.

- [ ] **Step 4: Add ranking tests and minimal ranking implementation**

```python
def test_psd_wins_over_pdf_at_equal_confidence(self):
    candidates = [
        classify_candidate("Back/JR APFGNUNC.pdf", {"UNC66804BCQ"}, "belvedere"),
        classify_candidate("Back/JR APFGNUNC.psd", {"UNC66804BCQ"}, "belvedere"),
    ]
    winner, tied = rank_candidates(candidates)
    self.assertEqual("psd", winner.kind)
    self.assertFalse(tied)
```

```python
QUALITY = {"psd": 4, "pdf": 3, "png": 2, "jpg": 2, "jpeg": 2}


def rank_candidates(candidates: list[PackageCandidate]) -> tuple[PackageCandidate | None, bool]:
    eligible = [candidate for candidate in candidates if candidate.contract and candidate.position and not candidate.ambiguous]
    if not eligible:
        return None, False
    ranked = sorted(eligible, key=lambda c: (c.team_confidence, c.placement_confidence, QUALITY.get(c.kind, 0)), reverse=True)
    best_score = (ranked[0].team_confidence, ranked[0].placement_confidence, QUALITY.get(ranked[0].kind, 0))
    tied = sum((c.team_confidence, c.placement_confidence, QUALITY.get(c.kind, 0)) == best_score for c in ranked) > 1
    return (None if tied else ranked[0]), tied
```

- [ ] **Step 5: Run tests and commit**

Run: `./.venv/bin/python -m unittest tests.test_artwork_matching -v`

Expected: all matching tests pass.

```bash
git add artwork_matching.py extract_to_plan_sheet.py tests/test_artwork_matching.py
git commit -m "Add garment-aware artwork matching"
```

---

### Task 2: Safe ZIP Enumeration

**Files:**
- Create: `artwork_archive.py`
- Test: `tests/test_artwork_archive.py`

**Interfaces:**
- Consumes: uploaded ZIP bytes.
- Produces: `ArchiveEntry(path: str, data: bytes)` and `read_artwork_archive(data: bytes) -> list[ArchiveEntry]`.
- Raises: `ArchiveError(message)` for user-correctable invalid packages.

- [ ] **Step 1: Write failing archive safety tests**

```python
# tests/test_artwork_archive.py
import io
import unittest
from zipfile import ZIP_DEFLATED, ZipFile

from artwork_archive import ArchiveError, read_artwork_archive


def make_zip(entries):
    stream = io.BytesIO()
    with ZipFile(stream, "w", ZIP_DEFLATED) as archive:
        for path, data in entries:
            archive.writestr(path, data)
    return stream.getvalue()


class ArtworkArchiveTests(unittest.TestCase):
    def test_returns_supported_files_recursively(self):
        entries = read_artwork_archive(make_zip([
            ("PO/Back/JR APFGNUNC.pdf", b"%PDF-test"),
            ("PO/.DS_Store", b"metadata"),
            ("PO/notes.txt", b"notes"),
        ]))
        self.assertEqual(["PO/Back/JR APFGNUNC.pdf"], [entry.path for entry in entries])

    def test_rejects_parent_traversal(self):
        with self.assertRaisesRegex(ArchiveError, "unsafe path"):
            read_artwork_archive(make_zip([("../outside.jpg", b"image")]))

    def test_rejects_nested_archive(self):
        with self.assertRaisesRegex(ArchiveError, "nested archive"):
            read_artwork_archive(make_zip([("PO/more.zip", b"PK")]))
```

Add separate tests that patch module limits to prove rejection at `MAX_ARCHIVE_ENTRIES + 1` and `MAX_EXPANDED_BYTES + 1`. Construct an encrypted-entry test by setting `ZipInfo.flag_bits |= 0x1` before `writestr` and assert `ArchiveError("encrypted")`.

- [ ] **Step 2: Run tests and verify the missing module failure**

Run: `./.venv/bin/python -m unittest tests.test_artwork_archive -v`

Expected: missing `artwork_archive` module.

- [ ] **Step 3: Implement bounded in-memory enumeration**

```python
# artwork_archive.py
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
            result = []
            for info in infos:
                path = _safe_path(info.filename)
                if info.flag_bits & 0x1:
                    raise ArchiveError("Encrypted ZIP entries are not supported.")
                if info.is_dir() or "__MACOSX" in path.parts or path.name.lower() in IGNORED_NAMES:
                    continue
                suffix = path.suffix.lower()
                if suffix == ".zip":
                    raise ArchiveError("A nested archive is not supported.")
                if suffix in SUPPORTED_SUFFIXES:
                    result.append(ArchiveEntry(path.as_posix(), archive.read(info)))
            return result
    except BadZipFile as exc:
        raise ArchiveError("The uploaded file is not a valid ZIP archive.") from exc
```

- [ ] **Step 4: Run tests and commit**

Run: `./.venv/bin/python -m unittest tests.test_artwork_archive -v`

Expected: all archive tests pass.

```bash
git add artwork_archive.py tests/test_artwork_archive.py
git commit -m "Add safe artwork ZIP reader"
```

---

### Task 3: Artwork Rendering, Trimming, and Blank Validation

**Files:**
- Create: `artwork_rendering.py`
- Modify: `requirements.txt`
- Test: `tests/test_artwork_rendering.py`

**Interfaces:**
- Consumes: `ArchiveEntry` and optional spec-sheet fallback position.
- Produces: `render_artwork(entry) -> RenderedArtwork` where `RenderedArtwork.png: bytes`, `width: int`, `height: int`, and `warnings: tuple[str, ...]`.
- Raises: `ArtworkRenderError` when a candidate cannot produce meaningful visible artwork.

- [ ] **Step 1: Add PyMuPDF dependency and failing raster-normalization tests**

Add `PyMuPDF>=1.24,<2` to `requirements.txt`, install it with `./.venv/bin/pip install -r requirements.txt`, then add:

```python
# tests/test_artwork_rendering.py
import io
import unittest
from PIL import Image, ImageDraw

from artwork_archive import ArchiveEntry
from artwork_rendering import ArtworkRenderError, render_artwork


def png_fixture(draw):
    image = Image.new("RGBA", (200, 160), (255, 255, 255, 0))
    draw(ImageDraw.Draw(image))
    stream = io.BytesIO()
    image.save(stream, "PNG")
    return stream.getvalue()


class ArtworkRenderingTests(unittest.TestCase):
    def test_trims_transparent_margin_and_keeps_padding(self):
        data = png_fixture(lambda draw: draw.rectangle((70, 50, 129, 109), fill=(10, 80, 180, 255)))
        rendered = render_artwork(ArchiveEntry("Front/UNC.png", data))
        image = Image.open(io.BytesIO(rendered.png))
        self.assertLess(image.width, 100)
        self.assertLess(image.height, 100)
        self.assertGreater(image.width, 60)
        self.assertGreater(image.height, 60)

    def test_rejects_visually_blank_raster(self):
        image = Image.new("RGB", (200, 160), "white")
        stream = io.BytesIO(); image.save(stream, "JPEG")
        with self.assertRaisesRegex(ArtworkRenderError, "blank"):
            render_artwork(ArchiveEntry("Front/UNC.jpg", stream.getvalue()))
```

- [ ] **Step 2: Run raster tests and verify they fail because rendering is absent**

Run: `./.venv/bin/python -m unittest tests.test_artwork_rendering -v`

Expected: missing `artwork_rendering` module.

- [ ] **Step 3: Implement raster normalization and content validation**

```python
# artwork_rendering.py
from dataclasses import dataclass
import io
from PIL import Image, ImageChops, ImageOps, UnidentifiedImageError

from artwork_archive import ArchiveEntry


class ArtworkRenderError(ValueError):
    pass


@dataclass(frozen=True)
class RenderedArtwork:
    png: bytes
    width: int
    height: int
    warnings: tuple[str, ...] = ()


def _content_box(image: Image.Image):
    rgba = image.convert("RGBA")
    alpha_box = rgba.getchannel("A").getbbox()
    if alpha_box and alpha_box != (0, 0, rgba.width, rgba.height):
        return alpha_box
    rgb = rgba.convert("RGB")
    background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
    difference = ImageChops.difference(rgb, background).convert("L").point(lambda p: 255 if p > 12 else 0)
    return difference.getbbox()


def _normalize(image: Image.Image, warnings=()):
    image = ImageOps.exif_transpose(image).convert("RGBA")
    box = _content_box(image)
    if box is None:
        raise ArtworkRenderError("Artwork is visually blank.")
    image = image.crop(box)
    padding = max(4, round(max(image.size) * 0.03))
    canvas = Image.new("RGBA", (image.width + padding * 2, image.height + padding * 2), (255, 255, 255, 0))
    canvas.alpha_composite(image, (padding, padding))
    stream = io.BytesIO(); canvas.save(stream, "PNG")
    return RenderedArtwork(stream.getvalue(), canvas.width, canvas.height, tuple(warnings))
```

Implement raster opening with `Image.open(io.BytesIO(entry.data))`, `image.load()`, and `_normalize(image)`; translate decoding exceptions to `ArtworkRenderError`.

- [ ] **Step 4: Add failing PDF and PSD decoding tests**

Create a one-page PDF fixture in the test with PyMuPDF drawing APIs and a layered PSD characterization test using one real supplied PSD path when present. The PSD test must skip with an explicit message only when the integration fixture is absent.

```python
def test_renders_first_pdf_page(self):
    import fitz
    document = fitz.open(); page = document.new_page(width=200, height=100)
    page.draw_rect((40, 20, 160, 80), color=(0, 0, 1), fill=(0, 0, 1))
    rendered = render_artwork(ArchiveEntry("Back/UNC.pdf", document.tobytes()))
    self.assertTrue(rendered.png.startswith(b"\x89PNG"))

def test_decodes_real_psd_composite(self):
    path = Path("/Users/mac/Documents/personal projects/primeKnitwear/docs/PK73498 [IBS] [PBX]/Chest/AD EMLNFUNC-1C.psd")
    if not path.exists(): self.skipTest("Belvedere PSD integration fixture unavailable")
    rendered = render_artwork(ArchiveEntry(path.name, path.read_bytes()))
    self.assertGreater(rendered.width, 20)
    self.assertGreater(rendered.height, 20)
```

- [ ] **Step 5: Implement PDF and PSD paths**

```python
def _open_pdf(data: bytes):
    import fitz
    try:
        document = fitz.open(stream=data, filetype="pdf")
        if document.page_count < 1:
            raise ArtworkRenderError("PDF contains no pages.")
        pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True)
        image = Image.open(io.BytesIO(pixmap.tobytes("png")))
        warnings = ("Only the first PDF page was used.",) if document.page_count > 1 else ()
        return image, warnings
    except ArtworkRenderError:
        raise
    except Exception as exc:
        raise ArtworkRenderError("PDF artwork could not be rendered.") from exc


def render_artwork(entry: ArchiveEntry) -> RenderedArtwork:
    suffix = Path(entry.path).suffix.lower()
    if suffix == ".pdf":
        image, warnings = _open_pdf(entry.data)
        return _normalize(image, warnings)
    try:
        with Image.open(io.BytesIO(entry.data)) as source:
            source.seek(0)
            source.load()
            return _normalize(source.copy())
    except ArtworkRenderError:
        raise
    except (UnidentifiedImageError, OSError) as exc:
        raise ArtworkRenderError(f"{suffix.lstrip('.').upper()} artwork could not be decoded.") from exc
```

- [ ] **Step 6: Run tests and commit**

Run: `./.venv/bin/python -m unittest tests.test_artwork_rendering -v`

Expected: raster, PDF, and available PSD tests pass.

```bash
git add artwork_rendering.py requirements.txt tests/test_artwork_rendering.py
git commit -m "Add source artwork rendering and normalization"
```

---

### Task 4: Package Resolution and JPG Panel Fallback

**Files:**
- Create: `artwork_package.py`
- Modify: `extract_to_plan_sheet.py`
- Test: `tests/test_artwork_package.py`
- Test: `tests/test_artwork_extraction.py`

**Interfaces:**
- Consumes: ZIP bytes, selected format key, and expected contracts.
- Produces: `PackageResolution(slots, records, ignored)` where `slots[(contract, position)] = png_bytes` and records are serializable `ManifestRecord` values.
- Uses: `read_artwork_archive`, `classify_candidate`, `rank_candidates`, `render_artwork`, and `extract_artwork_crops_bytes`.

- [ ] **Step 1: Refactor panel extraction behind a bytes interface with characterization tests**

Add this test before changing production code:

```python
def test_bytes_interface_matches_path_interface(self):
    path = self._save_fixture(self._draw_belvedere_fixture)
    from_path = extract_artwork_crops(path)
    from_bytes = extract_artwork_crops_bytes(path.read_bytes())
    self.assertEqual(from_path, from_bytes)
```

Implement `extract_artwork_crops_bytes(data: bytes)` by moving the current Pillow open/detect/crop behavior into the bytes function. Keep `extract_artwork_crops(path)` as `return extract_artwork_crops_bytes(path.read_bytes())` so existing callers remain compatible.

- [ ] **Step 2: Run extraction tests and commit the compatibility refactor**

Run: `./.venv/bin/python -m unittest tests.test_artwork_extraction -v`

Expected: all panel tests pass.

```bash
git add extract_to_plan_sheet.py tests/test_artwork_extraction.py
git commit -m "Expose in-memory spec sheet extraction"
```

- [ ] **Step 3: Write failing package-resolution tests**

```python
# tests/test_artwork_package.py
import io
import unittest
from zipfile import ZipFile

from artwork_package import resolve_artwork_package


class ArtworkPackageTests(unittest.TestCase):
    def test_resolves_belvedere_positions_and_prefers_psd(self):
        package = package_fixture({
            "PO/Back/JR APFGNUNC.pdf": valid_pdf_artwork(),
            "PO/Back/JR APFGNUNC.psd": valid_psd_artwork(),
            "PO/Chest/AD EMLNFUNC.png": valid_png_artwork(),
            "PO/Hood/AD EMBLUNC.png": valid_png_artwork(),
        })
        result = resolve_artwork_package(package, "belvedere", {"UNC66804BCQ"})
        self.assertEqual({("UNC66804BCQ", "back"), ("UNC66804BCQ", "front"), ("UNC66804BCQ", "hood")}, set(result.slots))
        back = next(record for record in result.records if record.position == "back")
        self.assertTrue(back.path.endswith(".psd"))
        self.assertEqual("matched", back.status)

    def test_tied_candidates_are_ambiguous_and_not_inserted(self):
        package = package_fixture({
            "PO/Chest/AD EMLNFUNC-a.png": valid_png_artwork(),
            "PO/Chest/AD EMLNFUNC-b.png": valid_png_artwork(),
        })
        result = resolve_artwork_package(package, "belvedere", {"UNC66804BCQ"})
        self.assertNotIn(("UNC66804BCQ", "front"), result.slots)
        self.assertEqual("ambiguous", next(r.status for r in result.records if r.position == "front"))
```

Add tests for unreadable PSD falling through to PDF, unmatched files, missing slots, and full-sheet JPG fallback. Use small generated fixtures except for one supplied Belvedere ZIP integration test.

- [ ] **Step 4: Implement resolver and manifest types**

```python
# artwork_package.py
from __future__ import annotations

from dataclasses import asdict, dataclass

from artwork_archive import ArchiveEntry, read_artwork_archive
from artwork_matching import classify_candidate, rank_candidates, required_positions
from artwork_rendering import ArtworkRenderError, render_artwork
from extract_to_plan_sheet import extract_artwork_crops_bytes


@dataclass(frozen=True)
class ManifestRecord:
    contract: str
    position: str
    status: str
    path: str | None = None
    detail: str | None = None

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class PackageResolution:
    slots: dict[tuple[str, str], bytes]
    records: tuple[ManifestRecord, ...]
    ignored: tuple[str, ...]


def resolve_artwork_package(data: bytes, format_key: str, contracts: set[str]) -> PackageResolution:
    entries = read_artwork_archive(data)
    classified = [(entry, classify_candidate(entry.path, contracts, format_key)) for entry in entries]
    slots = {}; records = []; used_paths = set()
    for contract in sorted(contracts):
        for position in required_positions(format_key):
            pool = [(entry, candidate) for entry, candidate in classified if candidate.contract == contract and candidate.position == position]
            winner, tied = rank_candidates([candidate for _, candidate in pool])
            if tied:
                records.append(ManifestRecord(contract, position, "ambiguous", detail=", ".join(entry.path for entry, _ in pool)))
                continue
            ordered = sorted(pool, key=lambda pair: candidate_score(pair[1]), reverse=True)
            selected = None
            failures = []
            for entry, candidate in ordered:
                try:
                    rendered, status = render_candidate(entry, position)
                    selected = (entry, rendered, status)
                    break
                except ArtworkRenderError as exc:
                    failures.append(f"{entry.path}: {exc}")
            if selected:
                entry, rendered, status = selected; slots[(contract, position)] = rendered.png; used_paths.add(entry.path)
                records.append(ManifestRecord(contract, position, status, entry.path, "; ".join(rendered.warnings) or None))
            else:
                records.append(ManifestRecord(contract, position, "unreadable" if pool else "missing", detail="; ".join(failures) or None))
    ignored = tuple(entry.path for entry in entries if entry.path not in used_paths)
    return PackageResolution(slots, tuple(records), ignored)
```

Define `candidate_score` once using the same exported quality/confidence tuple as the matcher. `render_candidate(entry, position)` returns `(RenderedArtwork, "matched")` for a PSD/PDF/isolated raster candidate.

After the source-art candidate loop, resolve JPG fallbacks separately: collect exact-contract raster entries whose position is `None`, call `extract_artwork_crops_bytes`, and select tuple index `0` for `front` or `1` for `back`. Return `(RenderedArtwork, "fallback")` after normalizing the selected crop. Do not treat a top-level full-sheet JPG as a source candidate for `hood`. A dedicated Hood source always wins; any future front-to-hood reuse must be an explicit per-format configuration flag and is not enabled by this task.

- [ ] **Step 5: Run resolver and all extraction/rendering tests**

Run: `./.venv/bin/python -m unittest tests.test_artwork_package tests.test_artwork_extraction tests.test_artwork_rendering -v`

Expected: all tests pass, including unreadable-source fallback and ambiguity rejection.

- [ ] **Step 6: Commit**

```bash
git add artwork_package.py extract_to_plan_sheet.py tests/test_artwork_package.py tests/test_artwork_extraction.py
git commit -m "Resolve ZIP artwork packages with raster fallback"
```

---

### Task 5: Workbook Enrichment Service and ZIP API

**Files:**
- Modify: `server.py`
- Create: `tests/test_server_package.py`
- Modify: `requirements.txt`

**Interfaces:**
- Consumes: existing session ID and one uploaded ZIP in multipart field `package`.
- Produces: existing completed workbook URL plus `report.records`, `report.ignored`, `matched_count`, `fallback_count`, and `slot_count`.

- [ ] **Step 1: Add the HTTP test dependency and failing endpoint tests**

Add `httpx>=0.27,<1` to `requirements.txt`, install requirements, then write:

```python
# tests/test_server_package.py
import unittest
from fastapi.testclient import TestClient

import server


class ServerPackageTests(unittest.TestCase):
    def setUp(self):
        self.client = TestClient(server.app)

    def test_enrich_requires_a_zip_package(self):
        session_id = create_test_session("flannigan", ["CAL65999FGA"])
        response = self.client.post("/api/enrich", data={"session_id": session_id})
        self.assertEqual(422, response.status_code)

    def test_enrich_rejects_non_zip_magic_bytes(self):
        session_id = create_test_session("flannigan", ["CAL65999FGA"])
        response = self.client.post(
            "/api/enrich",
            data={"session_id": session_id},
            files={"package": ("artwork.zip", b"not-a-zip", "application/zip")},
        )
        self.assertEqual(400, response.status_code)
        self.assertIn("valid ZIP", response.json()["detail"])
```

`create_test_session` must create a real temporary workbook through `build_workbook`, write `meta.json`, register it in `server.sessions`, and register cleanup with the test case; do not mock workbook behavior.

- [ ] **Step 2: Run endpoint tests and verify the old multipart contract fails**

Run: `./.venv/bin/python -m unittest tests.test_server_package -v`

Expected: failures showing `/api/enrich` still expects `artwork` files.

- [ ] **Step 3: Replace loose-image enrichment with ZIP resolution**

```python
# server.py
from artwork_archive import ArchiveError
from artwork_package import resolve_artwork_package

ZIP_MAGIC_BYTES = (b"PK\x03\x04", b"PK\x05\x06", b"PK\x07\x08")


@app.post("/api/enrich")
async def enrich_workbook(session_id: str = Form(...), package: UploadFile = File(...)) -> dict[str, object]:
    workdir = get_session(session_id)
    meta = json.loads((workdir / "meta.json").read_text(encoding="utf-8"))
    fmt = WORKBOOK_FORMATS[meta["format"]]
    contents = await package.read()
    if not package.filename or not package.filename.lower().endswith(".zip") or not contents.startswith(ZIP_MAGIC_BYTES):
        raise HTTPException(status_code=400, detail="Upload one valid ZIP artwork package.")
    contracts = {
        str(row["contract"]).upper()
        for rows in meta["sheets"].values()
        for row in rows if row.get("contract")
    }
    try:
        resolution = resolve_artwork_package(contents, fmt.key, contracts)
    except ArchiveError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    workbook = load_workbook(workdir / "plan_sheet.xlsx")
    for sheet in workbook.worksheets:
        for row in range(FIRST_DATA_ROW, sheet.max_row):
            contract = str(sheet.cell(row, 2).value or "").upper()
            for slot in fmt.image_slots:
                image_bytes = resolution.slots.get((contract, slot.source))
                if image_bytes:
                    add_artwork_to_row(sheet, row, slot.column, image_bytes, slot.box)
    workbook.save(workdir / "completed_plan_sheet.xlsx")
    records = [record.to_dict() for record in resolution.records]
    return {
        "download_url": f"/api/session/{session_id}/completed",
        "report": {"records": records, "ignored": list(resolution.ignored)},
        "matched_count": sum(record["status"] == "matched" for record in records),
        "fallback_count": sum(record["status"] == "fallback" for record in records),
        "slot_count": len(records),
    }
```

Update `ImageSlot.source` values to canonical positions (`front`, `back`, `hood`). Belvedere's H slot must use `hood`; only the resolver may apply an explicit fallback reuse rule.

- [ ] **Step 4: Add and pass a real workbook insertion test**

Test a generated Belvedere workbook with three resolved PNGs. Reopen the saved XLSX, inspect its drawing XML extents in the same manner as `tests/test_artwork_extraction.py`, and assert three images are anchored to columns F, G, and H within their configured boxes.

Run: `./.venv/bin/python -m unittest tests.test_server_package -v`

Expected: all endpoint and workbook tests pass.

- [ ] **Step 5: Commit**

```bash
git add server.py extract_to_plan_sheet.py requirements.txt tests/test_server_package.py
git commit -m "Accept ZIP packages for workbook enrichment"
```

---

### Task 6: Station 2 ZIP Upload and Slot-Level Manifest

**Files:**
- Modify: `static/index.html`
- Modify: `static/app.js`
- Modify: `static/styles.css`
- Test: manual browser/API verification documented in this task.

**Interfaces:**
- Consumes: `/api/enrich` structured report from Task 5.
- Produces: one ZIP upload control and grouped result rows for every contract/position.

- [ ] **Step 1: Change the Station 2 HTML contract**

Replace the loose-image input and its copy with:

```html
<p class="station-help">Upload the complete artwork package as one ZIP. Folder names and nesting may vary; source PSD/PDF artwork is preferred and spec-sheet JPGs are used as fallback.</p>
<label class="drop-zone" for="artwork-package" id="package-drop-zone">
  <input id="artwork-package" name="package" type="file" accept="application/zip,.zip" required>
  <strong id="artwork-label">Drop the artwork ZIP here, or click to choose</strong>
  <span>One package containing all teams for this purchase-order batch</span>
</label>
```

Keep the existing Station 2 form, progress area, final download link, and print-report action.

- [ ] **Step 2: Update client validation and multipart upload**

```javascript
const isZip = (file) => file.type === 'application/zip' || /\.zip$/i.test(file.name);

setupDropZone({
  input: document.querySelector('#artwork-package'),
  zone: document.querySelector('#package-drop-zone'),
  label: document.querySelector('#artwork-label'),
  predicate: isZip,
  invalidMessage: 'Upload one ZIP artwork package.',
  defaultLabel: 'Drop the artwork ZIP here, or click to choose',
  noun: 'package',
});

const formData = new FormData();
formData.append('session_id', sessionId);
formData.append('package', packageInput.files[0]);
```

Remove the loop that appends multiple `artwork` files.

- [ ] **Step 3: Render structured manifest records**

```javascript
const statusCopy = {
  matched: 'Source artwork inserted',
  fallback: 'Inserted from spec-sheet JPG',
  missing: 'Artwork missing',
  ambiguous: 'Needs review—multiple possible files',
  unreadable: 'File could not be used',
};

function renderPackageReport(report) {
  const groups = Map.groupBy
    ? Map.groupBy(report.records, record => record.contract)
    : report.records.reduce((map, record) => map.set(record.contract, [...(map.get(record.contract) || []), record]), new Map());
  reportRoot.replaceChildren(...Array.from(groups, ([contract, records]) => {
    const section = document.createElement('section');
    section.className = 'manifest-team';
    const heading = document.createElement('h4'); heading.textContent = contract; section.append(heading);
    const list = document.createElement('ul');
    records.forEach(record => {
      const item = document.createElement('li');
      item.dataset.status = record.status;
      item.textContent = `${record.position}: ${statusCopy[record.status]}${record.path ? ` — ${record.path}` : ''}`;
      list.append(item);
    });
    section.append(list); return section;
  }));
}
```

Use DOM `textContent`, not `innerHTML`, for archive paths and server-provided details.

- [ ] **Step 4: Add status styles and responsive behavior**

Add CSS for `.manifest-team` and status markers using existing paper/ink variables. Ensure long archive paths wrap with `overflow-wrap: anywhere`; do not add horizontal page scrolling.

- [ ] **Step 5: Run server and manually verify browser behavior**

Run: `./.venv/bin/uvicorn server:app --host 127.0.0.1 --port 8000`

Verify:

1. Station 2 accepts one ZIP and rejects JPG selection.
2. The supplied Belvedere ZIP uploads without being reorganized.
3. Progress copy changes from upload to scanning.
4. Each team shows Back, Front, and Hood status rows.
5. Ambiguous/missing rows are readable on narrow and desktop layouts.
6. The completed workbook link downloads successfully.

- [ ] **Step 6: Commit**

```bash
git add static/index.html static/app.js static/styles.css
git commit -m "Add ZIP package workflow to Station 2"
```

---

### Task 7: Real-Package Integration, Documentation, and Final Verification

**Files:**
- Modify: `tests/test_artwork_package.py`
- Modify: `README.md`
- Modify: `render.yaml` only if dependency installation configuration proves insufficient.

**Interfaces:**
- Consumes: all previous task interfaces.
- Produces: verified deployment-ready ZIP workflow and operator documentation.

- [ ] **Step 1: Add a supplied-Belvedere-package integration test**

```python
def test_supplied_belvedere_zip_resolves_all_available_source_slots(self):
    package = Path("/Users/mac/Documents/personal projects/primeKnitwear/docs/PK73498 [IBS] [PBX].zip")
    if not package.exists():
        self.skipTest("Supplied Belvedere package unavailable")
    contracts = {"ECU66804BCQ", "NCS66804BCQ", "PSU66804BCQ", "UKY66804BCQ", "UNC66804BCQ", "UTN66804BCQ"}
    result = resolve_artwork_package(package.read_bytes(), "belvedere", contracts)
    self.assertEqual(18, len(result.slots))
    self.assertFalse([record for record in result.records if record.status in {"missing", "ambiguous", "unreadable"}])
```

The test must assert all three positions per six teams and verify that source PSD/PDF paths, rather than top-level spec-sheet JPG paths, won ranking.

- [ ] **Step 2: Run the integration test and correct only evidence-backed matcher gaps**

Run: `./.venv/bin/python -m unittest tests.test_artwork_package.ArtworkPackageTests.test_supplied_belvedere_zip_resolves_all_available_source_slots -v`

Expected: PASS with 18 resolved slots. If it fails, print candidate classification and ranking evidence for the affected slot before changing rules; do not add broad substring aliases to make the fixture pass.

- [ ] **Step 3: Update README workflow and operational limits**

Document:

- ZIP upload replaces individual JPG upload.
- Supported source and fallback types.
- Folder names are hints, not rigid schema.
- Source priority and ambiguity policy.
- 75 MB compressed, 300 MB expanded, and 500-entry limits.
- Example Belvedere and Flannigan naming patterns.
- How missing/ambiguous/unreadable statuses affect the workbook.

- [ ] **Step 4: Run the complete automated verification suite**

Run:

```bash
./.venv/bin/python -m unittest discover -s tests -v
./.venv/bin/python -m py_compile server.py extract_to_plan_sheet.py artwork_archive.py artwork_matching.py artwork_rendering.py artwork_package.py
```

Expected: all tests pass with no failures or errors; compilation exits zero.

- [ ] **Step 5: Run a fresh end-to-end API check**

Start the server and use `curl` with the supplied PO and ZIP:

```bash
CONVERT_RESPONSE=$(curl -sS -F 'format=belvedere' -F 'pdfs=@/Users/mac/Documents/personal projects/primeKnitwear/docs/PurchaseOrder 73498 Belvedere.pdf;type=application/pdf' http://127.0.0.1:8000/api/convert)
SESSION_ID=$(printf '%s' "$CONVERT_RESPONSE" | ./.venv/bin/python -c 'import json,sys; print(json.load(sys.stdin)["session_id"])')
curl -sS -F "session_id=$SESSION_ID" -F 'package=@/Users/mac/Documents/personal projects/primeKnitwear/docs/PK73498 [IBS] [PBX].zip;type=application/zip' http://127.0.0.1:8000/api/enrich
```

Assert the enrich response reports 18 resolved slots, zero ambiguous slots, and a completed-workbook URL. Download the workbook and inspect its drawing XML to verify 18 image anchors remain within configured display sizes.

- [ ] **Step 6: Review repository state and commit**

Run: `git status --short && git diff --check && git diff --stat HEAD`

Expected: no whitespace errors and only intended files changed.

```bash
git add README.md tests/test_artwork_package.py render.yaml
git commit -m "Verify and document ZIP artwork workflow"
```

Do not add `render.yaml` if it did not require modification.
