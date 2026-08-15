from __future__ import annotations

import argparse
import hashlib
import zipfile
from pathlib import Path


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--binary", required=True, type=Path)
    parser.add_argument("--platform", required=True)
    parser.add_argument("--arch", required=True)
    parser.add_argument("--output", default="release-artifacts", type=Path)
    args = parser.parse_args()

    args.output.mkdir(parents=True, exist_ok=True)
    archive = args.output / f"Savox76Giveaway-{args.platform}-{args.arch}.zip"
    executable_name = "Savox76Giveaway.exe" if args.platform == "windows" else "Savox76Giveaway"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as bundle:
        bundle.write(args.binary, executable_name)
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    archive.with_suffix(archive.suffix + ".sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )


if __name__ == "__main__":
    main()
