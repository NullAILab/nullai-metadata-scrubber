# Architecture Notes — Metadata Scrubber

## Why re-save instead of patch?

The only fully reliable way to remove EXIF from a JPEG is to re-encode without
it. Patching byte offsets is fragile — marker lengths vary and a mistaken byte
can corrupt the file. Pillow re-encodes by converting to raw pixel data
(`getdata()`) and building a new Image from scratch, guaranteeing no metadata
survives.

## PDF metadata: two locations

PDFs store metadata in two places:
1. `/Info` dictionary in the trailer (key-value pairs)
2. XMP metadata stream attached to the document catalog

pikepdf's `open_metadata()` context manager handles both atomically: it reads
the XMP stream, lets you mutate the Python dict, and writes back a new XMP
block. The /Info dict is handled separately because pikepdf exposes it through
`pdf.trailer`.

## DOCX: it's a ZIP

DOCX files are ZIP archives. The core properties live in
`word/docProps/core.xml`. python-docx exposes them via `doc.core_properties`
with typed Python attributes. Clearing them and re-saving rewrites the XML in
place. No ZIP manipulation needed — python-docx handles that transparently.

## Mutagen ID3

Mutagen's `ID3.delete()` removes the ID3v2 header from an MP3 entirely. It
does not affect the audio stream. After deletion, `save()` writes an ID3v2.4
header with no frames. For maximum compatibility the recommended approach is
`id3.delete()` (removes header) followed by writing a 0-byte ID3 block.

## Filesystem timestamps

Even after metadata is stripped from file contents, the OS still records:
- `mtime` — last modification time
- `atime` — last access time
- `ctime` — inode change time (Linux) / creation time (Windows)

`os.utime()` normalises mtime and atime to a fixed epoch. `ctime` cannot be
set on Linux (it's kernel-managed). On Windows, `ctime` can be altered via the
Win32 `SetFileTime` API — that extension is out of scope here.

## Dispatcher pattern

`scrub()` is the single public entry point. It inspects the file extension and
calls the appropriate function. This lets callers ignore file type details and
lets the CLI be file-type-agnostic.
