"""
scrubber.py — File metadata scrubber library.

Supports:
  - JPEG/JPG/TIFF — EXIF, IPTC, XMP via Pillow
  - PNG           — tEXt/iTXt/zTXt chunks via Pillow
  - PDF           — document info dict + XMP stream via pikepdf
  - DOCX          — core properties XML via python-docx
  - MP3           — ID3 tags via mutagen
  - Generic       — file-system timestamps (mtime/atime) normalisation

Each scrub function returns a ScrubResult describing what was found and removed.

Requirements:
    pip install Pillow pikepdf python-docx mutagen
"""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

try:
    from PIL import Image
    from PIL.ExifTags import TAGS
    _PIL_AVAILABLE = True
except ImportError:
    _PIL_AVAILABLE = False

try:
    import pikepdf
    _PIKE_AVAILABLE = True
except ImportError:
    _PIKE_AVAILABLE = False

try:
    from docx import Document
    from docx.oxml.ns import qn
    import lxml.etree as etree
    _DOCX_AVAILABLE = True
except ImportError:
    _DOCX_AVAILABLE = False

try:
    from mutagen.id3 import ID3, ID3NoHeaderError
    from mutagen.mp3 import MP3
    _MUTAGEN_AVAILABLE = True
except ImportError:
    _MUTAGEN_AVAILABLE = False


# ---------------------------------------------------------------------------
# Result type
# ---------------------------------------------------------------------------

@dataclass
class ScrubResult:
    file: str
    success: bool
    tags_found: list[str] = field(default_factory=list)
    tags_removed: list[str] = field(default_factory=list)
    error: Optional[str] = None

    @property
    def clean(self) -> bool:
        """True if no metadata was found (already clean)."""
        return self.success and not self.tags_found


# ---------------------------------------------------------------------------
# JPEG / TIFF / PNG scrubber (Pillow)
# ---------------------------------------------------------------------------

def _exif_tag_name(tag_id: int) -> str:
    return TAGS.get(tag_id, str(tag_id))


def scrub_image(path: Path, in_place: bool = False, out_path: Optional[Path] = None) -> ScrubResult:
    """
    Remove all EXIF/IPTC/XMP metadata from a JPEG, TIFF, or PNG file.

    Args:
        path:     Input file path.
        in_place: If True, overwrite the original file.
        out_path: If provided (and in_place is False), write cleaned file here.
                  Defaults to <original>_clean.<ext>.

    Returns:
        ScrubResult with tags_found / tags_removed lists.
    """
    if not _PIL_AVAILABLE:
        return ScrubResult(str(path), False, error="Pillow not installed (pip install Pillow)")

    result = ScrubResult(str(path), False)

    try:
        img = Image.open(path)
        tags_found: list[str] = []

        # Collect EXIF tags
        exif_data = img._getexif() if hasattr(img, "_getexif") else None
        if exif_data:
            for tag_id, val in exif_data.items():
                name = _exif_tag_name(tag_id)
                if val:
                    tags_found.append(f"EXIF:{name}")

        # PNG text chunks
        if img.format == "PNG":
            for key in img.info:
                if key not in ("dpi", "aspect"):
                    tags_found.append(f"PNG:{key}")

        # Strip all metadata by re-saving with a fresh image
        data = list(img.getdata())
        clean_img = Image.new(img.mode, img.size)
        clean_img.putdata(data)

        if in_place:
            dest = path
        elif out_path:
            dest = out_path
        else:
            dest = path.with_name(f"{path.stem}_clean{path.suffix}")

        # Use save_all for multi-frame images (TIFF)
        save_kwargs: dict = {}
        if img.format in ("JPEG", "JPG"):
            save_kwargs["format"] = "JPEG"
        elif img.format == "TIFF":
            save_kwargs["format"] = "TIFF"
        elif img.format == "PNG":
            save_kwargs["format"] = "PNG"

        clean_img.save(dest, **save_kwargs)

        result.tags_found   = tags_found
        result.tags_removed = tags_found[:]   # all found tags are removed
        result.success      = True

    except Exception as exc:
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# PDF scrubber (pikepdf)
# ---------------------------------------------------------------------------

def scrub_pdf(path: Path, in_place: bool = False, out_path: Optional[Path] = None) -> ScrubResult:
    """Remove document info dictionary and XMP metadata stream from a PDF."""
    if not _PIKE_AVAILABLE:
        return ScrubResult(str(path), False, error="pikepdf not installed (pip install pikepdf)")

    result = ScrubResult(str(path), False)

    try:
        pdf = pikepdf.open(path, allow_overwriting_input=in_place)
        tags_found: list[str] = []

        # Document info dict
        with pdf.open_metadata() as meta:
            for key in list(meta.keys()):
                tags_found.append(f"PDF:{key}")
                del meta[key]

        # Also clear the /Info dict directly
        if "/Info" in pdf.trailer:
            info = pdf.trailer["/Info"]
            for k in list(info.keys()):
                if k not in ("/Producer", "/Creator"):   # optional: keep these
                    tag = k.lstrip("/")
                    if f"PDF:{tag}" not in tags_found:
                        tags_found.append(f"PDF:{tag}")
                    del info[k]

        if in_place:
            dest = path
        elif out_path:
            dest = out_path
        else:
            dest = path.with_name(f"{path.stem}_clean{path.suffix}")

        pdf.save(dest)
        result.tags_found   = tags_found
        result.tags_removed = tags_found[:]
        result.success      = True

    except Exception as exc:
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# DOCX scrubber (python-docx)
# ---------------------------------------------------------------------------

_DOCX_CORE_PROPS = [
    "author", "category", "comments", "content_status",
    "created", "description", "identifier", "keywords",
    "language", "last_modified_by", "last_printed",
    "modified", "revision", "subject", "title", "version",
]


def scrub_docx(path: Path, in_place: bool = False, out_path: Optional[Path] = None) -> ScrubResult:
    """Remove core properties (author, title, etc.) from a DOCX file."""
    if not _DOCX_AVAILABLE:
        return ScrubResult(str(path), False, error="python-docx not installed (pip install python-docx)")

    result = ScrubResult(str(path), False)

    try:
        if not in_place:
            tmp = path.with_name(f"{path.stem}_scrub_tmp{path.suffix}")
            shutil.copy2(path, tmp)
            work_path = tmp
        else:
            work_path = path

        doc = Document(work_path)
        props = doc.core_properties
        tags_found: list[str] = []

        for attr in _DOCX_CORE_PROPS:
            val = getattr(props, attr, None)
            if val:
                tags_found.append(f"DOCX:{attr}={val!r}")
                setattr(props, attr, "" if isinstance(val, str) else None)

        if in_place:
            dest = path
        elif out_path:
            dest = out_path
            shutil.copy2(work_path, dest)
            doc.save(dest)
        else:
            dest = path.with_name(f"{path.stem}_clean{path.suffix}")

        doc.save(dest)

        if not in_place:
            work_path.unlink(missing_ok=True)

        result.tags_found   = tags_found
        result.tags_removed = tags_found[:]
        result.success      = True

    except Exception as exc:
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# MP3 / audio scrubber (mutagen)
# ---------------------------------------------------------------------------

def scrub_audio(path: Path, in_place: bool = False, out_path: Optional[Path] = None) -> ScrubResult:
    """Remove ID3 tags from an MP3 file."""
    if not _MUTAGEN_AVAILABLE:
        return ScrubResult(str(path), False, error="mutagen not installed (pip install mutagen)")

    result = ScrubResult(str(path), False)

    try:
        tags_found: list[str] = []
        try:
            id3 = ID3(str(path))
            for tag in id3.keys():
                tags_found.append(f"ID3:{tag}")
        except ID3NoHeaderError:
            result.success = True
            result.tags_found = []
            return result

        if not in_place:
            if out_path:
                dest = out_path
            else:
                dest = path.with_name(f"{path.stem}_clean{path.suffix}")
            shutil.copy2(path, dest)
            work = ID3(str(dest))
        else:
            work = id3

        work.delete()
        work.save()

        result.tags_found   = tags_found
        result.tags_removed = tags_found[:]
        result.success      = True

    except Exception as exc:
        result.error = str(exc)

    return result


# ---------------------------------------------------------------------------
# Filesystem timestamp normaliser
# ---------------------------------------------------------------------------

_EPOCH = time.mktime(time.strptime("2000-01-01 00:00:00", "%Y-%m-%d %H:%M:%S"))


def normalise_timestamps(path: Path) -> None:
    """
    Set mtime and atime to a fixed epoch (2000-01-01) to prevent
    filesystem timestamps from leaking creation/modification history.
    """
    os.utime(path, (_EPOCH, _EPOCH))


# ---------------------------------------------------------------------------
# Dispatcher
# ---------------------------------------------------------------------------

_IMAGE_EXTS  = {".jpg", ".jpeg", ".tiff", ".tif", ".png"}
_PDF_EXTS    = {".pdf"}
_DOCX_EXTS   = {".docx"}
_AUDIO_EXTS  = {".mp3"}


def scrub(path: Path, in_place: bool = False, out_path: Optional[Path] = None,
          normalise_fs: bool = False) -> ScrubResult:
    """
    Auto-detect file type and run the appropriate scrubber.

    Args:
        path:         Path to the input file.
        in_place:     Overwrite the original.
        out_path:     Write cleaned copy here (ignored when in_place=True).
        normalise_fs: Also zero out filesystem timestamps after scrubbing.

    Returns:
        ScrubResult.
    """
    ext = path.suffix.lower()

    if ext in _IMAGE_EXTS:
        result = scrub_image(path, in_place=in_place, out_path=out_path)
    elif ext in _PDF_EXTS:
        result = scrub_pdf(path, in_place=in_place, out_path=out_path)
    elif ext in _DOCX_EXTS:
        result = scrub_docx(path, in_place=in_place, out_path=out_path)
    elif ext in _AUDIO_EXTS:
        result = scrub_audio(path, in_place=in_place, out_path=out_path)
    else:
        result = ScrubResult(str(path), False,
                             error=f"Unsupported file type: {ext or '(no extension)'}")

    if normalise_fs and result.success:
        target = path if in_place else (out_path or path.with_name(f"{path.stem}_clean{path.suffix}"))
        if target.exists():
            normalise_timestamps(target)

    return result
