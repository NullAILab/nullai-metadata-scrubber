"""
main.py — Metadata Scrubber CLI

Subcommands:
    scrub   <file>        Scrub a single file
    batch   <dir>         Scrub all supported files in a directory
    inspect <file>        Show metadata without removing anything

Options:
    --in-place          Overwrite the original file
    --out <path>        Write cleaned file to this path (scrub only)
    --normalise-ts      Zero out filesystem timestamps after scrubbing
    --recursive         Process subdirectories too (batch only)
    --dry-run           Show what would be removed without writing (inspect mode)
    --json              Output results as JSON

Usage:
    python main.py scrub photo.jpg
    python main.py scrub photo.jpg --in-place
    python main.py scrub document.pdf --out /tmp/clean.pdf
    python main.py batch ./uploads/ --recursive
    python main.py inspect report.docx
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

from scrubber import scrub, scrub_image, scrub_pdf, scrub_docx, scrub_audio
from scrubber import ScrubResult, _IMAGE_EXTS, _PDF_EXTS, _DOCX_EXTS, _AUDIO_EXTS

_ALL_EXTS = _IMAGE_EXTS | _PDF_EXTS | _DOCX_EXTS | _AUDIO_EXTS


# ---------------------------------------------------------------------------
# Inspect (read-only metadata dump)
# ---------------------------------------------------------------------------

def inspect_file(path: Path) -> ScrubResult:
    """Return a ScrubResult with tags_found populated but nothing removed."""
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:
        result = scrub_image(path, in_place=False,
                             out_path=Path(os.devnull) if sys.platform != "win32" else Path("NUL"))
    elif ext in _PDF_EXTS:
        result = scrub_pdf(path, in_place=False,
                           out_path=Path("NUL") if sys.platform == "win32" else Path("/dev/null"))
    elif ext in _DOCX_EXTS:
        result = scrub_docx(path, in_place=False, out_path=None)
    elif ext in _AUDIO_EXTS:
        result = scrub_audio(path, in_place=False, out_path=None)
    else:
        from scrubber import ScrubResult
        result = ScrubResult(str(path), False,
                             error=f"Unsupported file type: {ext}")
    return result


# ---------------------------------------------------------------------------
# Rendering
# ---------------------------------------------------------------------------

def _separator(title: str = "", width: int = 56) -> str:
    if title:
        pad = (width - len(title) - 2) // 2
        return "─" * pad + f" {title} " + "─" * (width - pad - len(title) - 2)
    return "─" * width


def render_result(result: ScrubResult, mode: str = "scrub") -> None:
    status = "✓" if result.success else "✗"
    print(f"\n{_separator('METADATA ' + mode.upper())}")
    print(f"  File    : {result.file}")
    print(f"  Status  : {status}")

    if result.error:
        print(f"  Error   : {result.error}")
    else:
        print(f"  Found   : {len(result.tags_found)} tag(s)")
        if result.tags_found:
            for tag in result.tags_found:
                print(f"    - {tag}")
        if mode == "scrub" and result.tags_removed:
            print(f"  Removed : {len(result.tags_removed)} tag(s)")
        elif mode == "inspect" and not result.tags_found:
            print("  (file appears clean)")
    print()


def render_batch_summary(results: list[ScrubResult]) -> None:
    ok      = [r for r in results if r.success]
    failed  = [r for r in results if not r.success]
    total   = sum(len(r.tags_removed) for r in ok)
    print(f"\n{_separator('BATCH SUMMARY')}")
    print(f"  Files processed : {len(results)}")
    print(f"  Succeeded       : {len(ok)}")
    print(f"  Failed          : {len(failed)}")
    print(f"  Total tags removed: {total}")
    if failed:
        print("\n  Failures:")
        for r in failed:
            print(f"    {r.file} — {r.error}")
    print()


# ---------------------------------------------------------------------------
# Commands
# ---------------------------------------------------------------------------

import os


def cmd_scrub(args: argparse.Namespace) -> None:
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"[!] File not found: {path}")

    out = Path(args.out) if args.out else None
    result = scrub(path, in_place=args.in_place, out_path=out,
                   normalise_fs=args.normalise_ts)

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        render_result(result, mode="scrub")

    sys.exit(0 if result.success else 1)


def cmd_batch(args: argparse.Namespace) -> None:
    base = Path(args.directory)
    if not base.is_dir():
        sys.exit(f"[!] Not a directory: {base}")

    pattern = "**/*" if args.recursive else "*"
    files = [p for p in base.glob(pattern) if p.is_file() and p.suffix.lower() in _ALL_EXTS]

    if not files:
        print("[!] No supported files found.")
        return

    results: list[ScrubResult] = []
    for f in sorted(files):
        r = scrub(f, in_place=args.in_place, normalise_fs=args.normalise_ts)
        results.append(r)
        if not args.json:
            tag_count = len(r.tags_found)
            status = "OK" if r.success else "FAIL"
            print(f"  [{status}] {f.name:<40} {tag_count} tag(s)")

    if args.json:
        print(json.dumps([asdict(r) for r in results], indent=2))
    else:
        render_batch_summary(results)

    all_ok = all(r.success for r in results)
    sys.exit(0 if all_ok else 1)


def cmd_inspect(args: argparse.Namespace) -> None:
    path = Path(args.file)
    if not path.exists():
        sys.exit(f"[!] File not found: {path}")

    result = inspect_file(path)

    if args.json:
        print(json.dumps(asdict(result), indent=2))
    else:
        render_result(result, mode="inspect")


# ---------------------------------------------------------------------------
# Argument parser
# ---------------------------------------------------------------------------

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="scrubber",
        description="File metadata scrubber — JPEG, PNG, PDF, DOCX, MP3",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument("--json", action="store_true", help="Machine-readable JSON output")

    sub = p.add_subparsers(dest="command", required=True)

    # scrub
    sc = sub.add_parser("scrub", help="Scrub a single file")
    sc.add_argument("file")
    sc.add_argument("--in-place",     action="store_true")
    sc.add_argument("--out",          metavar="PATH")
    sc.add_argument("--normalise-ts", action="store_true",
                    help="Zero out filesystem timestamps")
    sc.set_defaults(func=cmd_scrub)

    # batch
    bt = sub.add_parser("batch", help="Scrub all supported files in a directory")
    bt.add_argument("directory")
    bt.add_argument("--in-place",     action="store_true")
    bt.add_argument("--recursive", "-r", action="store_true")
    bt.add_argument("--normalise-ts", action="store_true")
    bt.set_defaults(func=cmd_batch)

    # inspect
    ins = sub.add_parser("inspect", help="Show metadata without removing it")
    ins.add_argument("file")
    ins.set_defaults(func=cmd_inspect)

    return p


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
