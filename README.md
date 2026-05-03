# Metadata Scrubber

![Python](https://img.shields.io/badge/Python-3.10+-3776AB?logo=python&logoColor=white)
![Tests](https://img.shields.io/badge/Tests-passing-brightgreen)
![License](https://img.shields.io/badge/License-MIT-green)

> **Difficulty:** Beginner | **Language:** Python | **Requires:** Pillow, pikepdf, python-docx, mutagen

Privacy tool that strips embedded metadata from files before sharing them. Supports JPEG/PNG/TIFF (EXIF, IPTC, XMP), PDF (document info + XMP stream), DOCX (core properties), and MP3 (ID3 tags). Optionally normalises filesystem timestamps. Single-file and batch directory modes with JSON output for scripting.

---

## What Gets Removed

| Format | Metadata Removed |
|--------|----------------|
| JPEG / TIFF | EXIF (GPS, camera model, serial, date, software), IPTC, XMP |
| PNG | tEXt / iTXt / zTXt metadata chunks |
| PDF | `/Info` dict (author, creator, producer, creation date) + XMP stream |
| DOCX | Core properties (author, last modified by, company, revision, dates) |
| MP3 | All ID3v2 tags (artist, album, comment, encoder, cover art) |

---

## Project Structure

```
06-metadata-scrubber/
├── README.md
├── .gitignore
├── src/
│   ├── scrubber.py       ← Scrubber library (per-format functions + dispatcher)
│   ├── main.py           ← CLI: scrub / batch / inspect
│   └── requirements.txt
└── docs/
    └── NOTES.md
```

---

## Installation

```bash
cd src
pip install -r requirements.txt
```

---

## Usage

```bash
# Inspect metadata without removing it
python main.py inspect photo.jpg

# Scrub a single file (writes photo_clean.jpg)
python main.py scrub photo.jpg

# Scrub in-place (overwrites original)
python main.py scrub photo.jpg --in-place

# Scrub to a specific output path
python main.py scrub document.pdf --out /tmp/clean.pdf

# Scrub all supported files in a directory
python main.py batch ./uploads/

# Recursive batch + zero out filesystem timestamps
python main.py batch ./uploads/ --recursive --normalise-ts

# JSON output (pipe to jq)
python main.py scrub photo.jpg --json | jq '.tags_found'
```

**Example output:**
```
────────────── METADATA INSPECT ──────────────
  File    : photo.jpg
  Status  : ✓
  Found   : 14 tag(s)
    - EXIF:Make
    - EXIF:Model
    - EXIF:Software
    - EXIF:DateTime
    - EXIF:GPSInfo
    - EXIF:GPSLatitude
    - EXIF:GPSLongitude
    ...
```

---

## How It Works

### Images (Pillow)
Metadata is stripped by converting the image to raw pixel data and re-encoding it without any metadata markers. This is the only fully reliable method — patching EXIF offsets inline is fragile and can corrupt files.

### PDFs (pikepdf)
PDFs store metadata in two places: the `/Info` dictionary in the trailer and an optional XMP stream. pikepdf's `open_metadata()` context manager clears both atomically.

### DOCX (python-docx)
DOCX files are ZIP archives containing XML. Core properties live in `docProps/core.xml`. python-docx exposes them as Python attributes; clearing and re-saving rewrites the XML.

### MP3 (mutagen)
`ID3.delete()` removes the ID3v2 header entirely, leaving only the audio stream.

---

---

## Challenges & Extensions

- Add **HEIC/HEIF** support (iPhone photos) using `pyheif` or `pillow-heif`
- Add **video metadata** scrubbing with `ffmpeg` subprocess
- Add a **diff report** showing exactly what changed
- Build a **drag-and-drop GUI** with `tkinter` or `PyQt6`
- Integrate with a **web upload form** (Flask) for browser-based scrubbing

---

## References

- [Pillow EXIF docs](https://pillow.readthedocs.io/en/stable/reference/ExifTags.html)
- [pikepdf docs](https://pikepdf.readthedocs.io/)
- [ExifTool — reference implementation](https://exiftool.org/)
- [MAT2 — Metadata Anonymisation Toolkit](https://0xacab.org/jvoisin/mat2)
- MITRE ATT&CK: [T1592 — Gather Victim Host Information](https://attack.mitre.org/techniques/T1592/)

---

