from __future__ import annotations

import io
from dataclasses import dataclass
from pathlib import PurePosixPath

import fitz
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


def _normalize(image: Image.Image, warnings: tuple[str, ...] = ()) -> RenderedArtwork:
    image = ImageOps.exif_transpose(image).convert("RGBA")
    alpha = image.getchannel("A")
    alpha_box = alpha.getbbox()
    if alpha_box and alpha_box != (0, 0, image.width, image.height):
        box = alpha_box
    else:
        rgb = image.convert("RGB")
        background = Image.new("RGB", rgb.size, rgb.getpixel((0, 0)))
        mask = ImageChops.difference(rgb, background).convert("L").point(
            lambda value: 255 if value > 12 else 0
        )
        box = mask.getbbox()
    if box is None:
        raise ArtworkRenderError("Artwork is visually blank.")
    image = image.crop(box)
    padding = max(4, round(max(image.size) * 0.03))
    canvas = Image.new("RGBA", (image.width + padding * 2, image.height + padding * 2), (255, 255, 255, 0))
    canvas.alpha_composite(image, (padding, padding))
    stream = io.BytesIO(); canvas.save(stream, "PNG")
    return RenderedArtwork(stream.getvalue(), canvas.width, canvas.height, warnings)


def render_artwork(entry: ArchiveEntry) -> RenderedArtwork:
    suffix = PurePosixPath(entry.path).suffix.lower()
    if suffix == ".pdf":
        try:
            document = fitz.open(stream=entry.data, filetype="pdf")
            if document.page_count < 1:
                raise ArtworkRenderError("PDF contains no pages.")
            pixmap = document[0].get_pixmap(matrix=fitz.Matrix(2, 2), alpha=True)
            image = Image.open(io.BytesIO(pixmap.tobytes("png")))
            warnings = ("Only the first PDF page was used.",) if document.page_count > 1 else ()
            return _normalize(image, warnings)
        except ArtworkRenderError:
            raise
        except Exception as exc:
            raise ArtworkRenderError("PDF artwork could not be rendered.") from exc
        finally:
            if "document" in locals():
                document.close()
    try:
        with Image.open(io.BytesIO(entry.data)) as source:
            source.seek(0); source.load()
            return _normalize(source.copy())
    except ArtworkRenderError:
        raise
    except (UnidentifiedImageError, OSError, EOFError) as exc:
        raise ArtworkRenderError(f"{suffix.lstrip('.').upper()} artwork could not be decoded.") from exc
