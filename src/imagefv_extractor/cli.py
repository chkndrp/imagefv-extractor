"""CLI interface"""

# Extract bootloader/charging pictures from imagefv blobs
# Copyright (C) 2026 chkndrp
#
# This library is free software; you can redistribute it and/or modify it
# under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation; either version 3 of the License, or
# (at your option) any later version.
#
# This library is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.

import argparse
import logging

from collections.abc import Sequence
from pathlib import Path
from .extract import extract_images

logger = logging.getLogger("imagefv-extractor")


class _PrefixFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        return f"(x) {super().format(record)}"


def _configure_logging(verbose: bool) -> None:
    logger.setLevel(logging.DEBUG if verbose else logging.INFO)
    logger.propagate = False

    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(_PrefixFormatter("%(message)s"))
        logger.addHandler(handler)


def main(argv: Sequence[str] | None = None) -> int:
    """CLI main entry"""

    parser = argparse.ArgumentParser(
        description="Extract bootloader/charging pictures from imagefv blobs",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    parser.add_argument(
        "input",
        nargs="+",
        help="Input file(s) to process"
    )
    parser.add_argument(
        "-o", "--output",
        default="extracted_images",
        help="Output directory",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )
    args = parser.parse_args(argv)

    _configure_logging(args.verbose)

    failed = False
    for input_file in args.input:
        logger.info("Processing: %s", input_file)
        logger.info("Output directory: %s", args.output)

        output_dir = Path(args.output)
        if len(args.input) > 1:
            output_dir /= Path(input_file).stem

        try:
            extracted_files = extract_images(input_file, output_dir)
        except OSError as error:
            logger.error("Could not prepare output for %s: %s", input_file, error)
            failed = True
            continue

        if extracted_files:
            logger.info(
                "Successfully extracted %d item(s)",
                len(extracted_files),
            )
        else:
            logger.error("Failed to extract images from %s", input_file)
            failed = True

    logger.info("Extraction complete!")
    return int(failed)
