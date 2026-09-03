# ZIP Artwork Package Upload Design

Date: 2026-09-03
Status: Proposed for user review

## Purpose

Replace Station 2's loose JPG-only upload with one artwork-package ZIP upload per generated workbook. The package may contain full spec-sheet JPGs plus source artwork in PSD and PDF files. The application will recursively discover files, match them to purchase-order teams and required embroidery positions, prefer clean source artwork, and use spec-sheet panel extraction only as a fallback.

This removes the normal workflow's dependence on fixed JPG crop coordinates and accommodates packages whose folder names and nesting differ between garment types.

## User Workflow

Station 1 remains unchanged:

1. Select the garment type: Mocktail, Flannigan, or Belvedere.
2. Upload one or more purchase-order PDFs.
3. Generate the workbook and worksheets.

Station 2 changes to:

1. Upload one ZIP package containing the artwork and spec-sheet files for the purchase order batch.
2. The server safely scans the package and builds a proposed team/position match manifest.
3. The server inserts unambiguous matches into the workbook.
4. The page reports matched, missing, ambiguous, unsupported, and unreadable files.
5. Download the completed workbook.

The user does not need to reorganize the package or select individual files.

## Supported Inputs

The ZIP scanner supports these relevant file types:

- `.psd`: preferred source when its merged/composite preview can be decoded.
- `.pdf`: second-choice source, rendered from the first page.
- `.jpg`, `.jpeg`, `.png`: full spec sheets or already-rasterized artwork.

Other files are ignored and listed only when useful for diagnosing a missing match. macOS metadata such as `__MACOSX`, `.DS_Store`, and resource-fork files is silently ignored.

Archives are rejected when they are encrypted, malformed, exceed configured compressed or expanded size limits, contain too many entries, contain path traversal, or contain nested archives. Archive entries are processed without trusting their paths as filesystem destinations.

## Garment-Type Configuration

Each workbook format defines its required artwork positions and accepted naming signals.

### Flannigan

- Required positions: `front`
- Folder hints: `artwork`, `art`, `front`, `chest`
- Filename placement signals: front/chest embroidery prefixes when present
- Because only one position exists, an artwork file matched confidently to a team can fill `front` even if it has no placement signal.

### Mocktail

- Required positions: `back`, `front`
- Folder hints: `back`; `front`, `chest`
- Filename placement signals: `APFGN` for back and `EMLNF` for front/chest, plus aliases observed in real packages

### Belvedere

- Required positions: `back`, `front`, `hood`
- Folder hints: `back`; `front`, `chest`; `hood`, `head`
- Filename placement signals: `APFGN` for back, `EMLNF` for front/chest, and `EMBL` for hood, plus aliases observed in real packages

The configuration, not branching spread throughout the scanner, owns these rules so future garment types can be added without rewriting matching logic.

## Package Discovery and Matching

### Team identity

The purchase order remains the authority for the set of expected contracts and team codes. For every purchase-order row, the application records:

- Full contract code, such as `UNC66804BCQ`.
- Short team code, such as `UNC`.
- Required positions from the selected garment type.

Candidate package files receive a team score using normalized, case-insensitive path and filename text:

1. Exact full contract-code match: strongest evidence.
2. Delimited short team-code match: accepted when it identifies exactly one purchase-order team.
3. Embedded short code adjacent to a known artwork prefix, such as `APFGNUNC`: accepted when unique.

Arbitrary substring matches are not accepted when they could identify multiple teams. For example, a short code inside an unrelated word is not sufficient.

### Placement identity

Candidate files receive a placement score from:

1. A known filename marker, such as `APFGN`, `EMLNF`, or `EMBL`.
2. A recognized folder component, such as `Back`, `Chest`, or `Hood`.
3. The single required position for a one-position format such as Flannigan.

Filename and folder signals are case-insensitive and tolerate spaces, punctuation, and nesting. When filename and folder placement signals conflict, the candidate is ambiguous and is not inserted automatically.

### Candidate ranking

For each expected `(contract, position)` slot, candidates are ranked in this order:

1. Unique team and placement confidence.
2. Source quality: decodable PSD, then decodable PDF, then already-isolated raster artwork, then full spec-sheet JPG fallback.
3. Exact full contract match over short team-code match.

If candidates remain tied at the same confidence and quality, the slot is reported as ambiguous. The application never resolves a tie using ZIP order or filename sorting.

## Artwork Rendering

### PSD

Decode the PSD's merged/composite image. Preserve alpha when available. If the PSD cannot be decoded or has no usable composite, continue to the PDF candidate for the same slot and report the PSD as unreadable.

### PDF

Render the first page at a resolution sufficient for the largest Excel artwork slot. Preserve transparency when the renderer provides it; otherwise use a white background. Multi-page artwork PDFs are reported as warnings and only page one is used.

### Isolated raster artwork

Use the raster directly after orientation normalization and whitespace trimming.

### Full spec-sheet raster fallback

Detect the bordered artwork panels structurally. Map the left panel to front/chest and the right panel to back. Only reuse front artwork for another position when the format configuration explicitly allows it. If a required position such as Hood has a dedicated source-art candidate, that candidate takes precedence over any reuse rule.

If panel borders cannot be detected or the resulting crop lacks meaningful visual content, report the file as unreadable instead of inserting a white or guessed image.

### Normalization

All selected artwork is converted to PNG for Excel insertion. Before conversion:

- Apply EXIF orientation.
- Trim transparent margins.
- For opaque images, trim only near-uniform edge-connected background; do not remove white regions enclosed by the artwork.
- Retain a small padding margin around the resulting artwork.
- Preserve aspect ratio and fit within the configured Excel slot.
- Do not upscale tiny images beyond a configurable quality threshold without issuing a warning.

## Manifest and Error Handling

Station 2 displays results grouped by workbook sheet and contract. Each required position has one of these states:

- `matched`: source chosen and inserted.
- `fallback`: inserted from a full spec-sheet raster rather than source artwork.
- `missing`: no candidate matched the team and position.
- `ambiguous`: multiple candidates tied or team/placement signals conflicted.
- `unreadable`: a matched file could not be decoded, rendered, or validated.

The completed workbook is still downloadable when some slots are unresolved. Unresolved cells remain blank. The manifest includes the original ZIP path for every selected or rejected candidate so the user can correct the package without guessing.

API errors distinguish invalid ZIPs, archive safety violations, unsupported content, and expired workbook sessions. Internal parser details and server paths are not exposed.

## API and UI Changes

The existing `POST /api/enrich` route will accept one required `package` ZIP upload instead of a list of loose `artwork` images. Its response retains counts and a report but expands the report to slot-level structured records.

Station 2 will:

- Accept `.zip` only.
- Explain that the ZIP may contain folders and mixed PSD/PDF/JPG/PNG files.
- Show upload progress and a scanning state for large packages.
- Render per-team positions and their result states.
- Keep the final workbook download action available after processing.

The server remains responsible for all matching decisions; the browser only displays the returned manifest.

## Internal Components

Implementation will separate the pipeline into focused units:

1. `archive_reader`: validates and enumerates ZIP entries safely.
2. `package_matcher`: normalizes names and scores team/placement candidates using garment configuration.
3. `artwork_renderer`: decodes PSD, renders PDF, accepts raster artwork, and normalizes output PNGs.
4. `spec_sheet_extractor`: provides bordered-panel JPG fallback.
5. `workbook_enricher`: inserts resolved PNGs into configured worksheet slots.
6. `manifest_builder`: records deterministic results and user-facing diagnostics.

These boundaries allow archive safety, matching, rendering, and workbook behavior to be tested independently.

## Testing Strategy

Tests will be written before implementation and will cover:

- ZIP traversal, absolute paths, encrypted entries, oversized expansion, entry-count limits, malformed archives, and nested archives.
- Belvedere-style `Back`/`Chest`/`Hood` folders.
- Flannigan-style generic `Artwork` folders.
- Different capitalization, punctuation, nesting, and harmless unrelated files.
- Full contract matches, unique short-code matches, ambiguous short codes, and misleading substrings.
- Conflicting filename and folder placement signals.
- PSD-over-PDF preference and fallback when the preferred file is unreadable.
- PDF rendering and PSD composite decoding.
- White/transparent margin trimming without clipping artwork.
- Full-sheet panel extraction fallback for the supplied Belvedere and Flannigan examples.
- Blank-crop rejection.
- End-to-end workbook generation with the expected number of images and correct Excel display bounds for each garment type.

The supplied Belvedere ZIP is the principal integration fixture. Synthetic small archives and images cover edge cases without adding large binary fixtures unnecessarily.

## Dependency and Deployment Considerations

PDF artwork requires a renderer rather than text-only PDF parsing. The implementation plan will select a Python package that works in the deployed Render environment without relying on an unconfigured desktop application. PSD support will first use Pillow's composite decoding and add another dependency only if real supplied PSDs prove unsupported.

Archive and rendered-image limits will be chosen to accommodate the approximately 40 MB supplied Belvedere package while protecting server memory and disk. Temporary extracted/rendered data remains scoped to the existing workbook session and is removed with that session.

## Migration and Compatibility

Station 1 and workbook templates remain unchanged. The current panel-border detector remains as the JPG fallback. Loose-image Station 2 uploads are replaced rather than maintained as a second workflow, keeping the interface and matching behavior unambiguous.

Existing active sessions created before deployment may require the user to regenerate the workbook before uploading a ZIP. This is acceptable because sessions are already temporary.

## Success Criteria

- A user can upload the supplied Belvedere ZIP without reorganizing it.
- Every unambiguous Back, Front/Chest, and Hood source artwork file is assigned to the correct purchase-order team and workbook column.
- A Flannigan package with a generic Artwork folder fills its single artwork column without relying on the folder name.
- Minor folder and filename variations do not break unique matches.
- Ambiguous files are reported and never silently assigned.
- No artwork is clipped, contaminated by a neighboring panel, or inserted as a visually blank image.
- The generated workbook preserves existing formulas, formatting, row sizing, and print settings.
