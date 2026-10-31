"""Main entry"""

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

import contextlib
import gzip
import tempfile
import shutil
import logging
import io

from pathlib import Path
from uefi_firmware.uefi import FirmwareVolume
from uefi_firmware.utils import search_firmware_volumes

logger = logging.getLogger("imagefv-extractor")


def _get_file_extension(header: bytes) -> str:
    """Determine file extension from magic bytes"""

    magic_map = {
        b"\x7fELF": "elf",
        b"\x1f\x8b": "gz",
        b"BM": "bmp",
        b"\x89PNG": "png",
        b"GIF": "gif",
        b"PK\x03\x04": "zip",
        b"BZh": "bz2",
        b"<?xml": "xml",
        b"<": "xml",
    }

    for magic, ext in magic_map.items():
        if header.startswith(magic):
            return ext

    if header[:4] in {b"\xff\xd8\xff\xe0", b"\xff\xd8\xff\xe1"}:
        return "jpg"

    return "bin"


def _extract_gzip_stream(data: bytes, output_path: Path) -> bool:
    """Extract gzip data efficiently"""

    try:
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as gzfile:
            with open(output_path, "wb") as out:
                shutil.copyfileobj(gzfile, out, length=1024*1024)

        return True
    except OSError as e:
        logger.warning("Failed to decompress gzip: %s", e)
        return False


def _extract_gzip_bounded(data: bytes, start_offset: int,
        next_offset: int | None, output_path: Path) -> bool:
    """Extract single gzip stream bounded by next gzip header"""

    try:
        gzip_data = data[start_offset:next_offset] if next_offset else data[start_offset:]

        with gzip.GzipFile(fileobj=io.BytesIO(gzip_data)) as gzfile:
            extracted = gzfile.read()

        if extracted:
            with open(output_path, "wb") as out:
                out.write(extracted)

            return True
    except (OSError, EOFError) as e:
        logger.debug("Failed to extract gzip at offset 0x%x: %s", start_offset, e)

    return False


def _extract_and_rename_archive(section_data: bytes, offset: int,
        next_offset: int | None, output_path: Path, idx: int) -> str | None:
    """Extract and rename archive with proper extension"""

    if not _extract_gzip_bounded(section_data, offset, next_offset, output_path):
        return None

    try:
        size = output_path.stat().st_size

        with open(output_path, "rb") as archive_file:
            header = archive_file.read(4)

        ext = _get_file_extension(header)
        better_path = output_path.parent / f"archive_{idx:04d}.{ext}"
        output_path.rename(better_path)

        logger.info(
            "Extracted archive %3d at offset 0x%08x -> %s (%.1f MB)",
            idx,
            offset,
            better_path.name,
            size / 1024 / 1024,
        )
        return str(better_path)
    except OSError as e:
        logger.error("Failed to rename archive at offset 0x%x: %s", offset, e)
        return None


def _find_gzip_offsets(data: bytes) -> list[int]:
    """Find all gzip stream offsets by scanning for magic bytes"""

    return [
        offset
        for offset in range(len(data) - 1)
        if data[offset:offset + 2] == b"\x1f\x8b"
    ]


def _extract_file_label(parent_dir: Path) -> str | None:
    """Extract file label from UI section if available"""

    ui_file = parent_dir / "section0.ui"
    if not ui_file.exists():
        return None

    try:
        with open(ui_file, "rb") as ui_data_file:
            ui_data = ui_data_file.read()

        if len(ui_data) > 2:
            decoded = ui_data.decode("utf-16-le", errors="ignore")
            file_label = decoded.split("\x00")[0].strip()

            if file_label and len(file_label) > 1:
                return file_label

    except (OSError, UnicodeDecodeError) as e:
        logger.debug("Could not extract label from %s: %s", ui_file, e)

    return None


def _is_file_label_safe(file_label: str) -> bool:
    """Return whether a firmware-provided label can be used as a filename"""

    return (
        file_label not in {"", ".", ".."}
        and "\x00" not in file_label
        and "/" not in file_label
        and "\\" not in file_label
        and ":" not in file_label
        and Path(file_label).name == file_label
    )


def _process_large_binary_section(file_label: str, section_data: bytes,
        output_subdir: Path, extracted_files: dict[str, str]) -> int:
    """Process large binary sections with multiple gzip archives"""

    raw_path = output_subdir / file_label
    output_subdir.mkdir(parents=True, exist_ok=True)

    try:
        with open(raw_path, "wb") as section_file:
            section_file.write(section_data)

        logger.info("Saved: %s (%d bytes)", file_label, len(section_data))
        extracted_files[f"{file_label}_raw"] = str(raw_path)
    except OSError as e:
        logger.error("Failed to save %s: %s", file_label, e)
        return 0

    gzip_offsets = _find_gzip_offsets(section_data)
    logger.info("Found %d gzip stream(s) in %s", len(gzip_offsets), file_label)

    if not gzip_offsets:
        return 0

    archives_dir = output_subdir / "images"
    archives_dir.mkdir(parents=True, exist_ok=True)

    extracted_count = 0
    for idx, offset in enumerate(gzip_offsets):
        next_offset = gzip_offsets[idx + 1] if idx + 1 < len(gzip_offsets) else None
        output_path = archives_dir / f"archive_{idx:04d}.bin"
        extracted_path = _extract_and_rename_archive(
            section_data,
            offset,
            next_offset,
            output_path,
            idx,
        )
        if not extracted_path:
            logger.debug("Could not extract gzip at offset 0x%x", offset)
        else:
            extracted_files[f"{file_label}_archive_{idx}"] = extracted_path
            extracted_count += 1

    logger.info("Successfully extracted %d archive(s) from %s", extracted_count, file_label)
    return extracted_count


def _extract_from_section(file_label: str, section_data: bytes, output_subdir: Path,
        output_dir: Path, extracted_files: dict[str, str]) -> str | None:
    """Extract images from firmware file section"""

    if file_label.endswith(".bmp") or len(section_data) < 1024*1024:
        output_path = output_dir / file_label
        try:
            with open(output_path, "wb") as output_file:
                output_file.write(section_data)

            logger.info("Extracted: %s (%d bytes)", file_label, len(section_data))
            return str(output_path)
        except OSError as e:
            logger.error("Failed to save %s: %s", file_label, e)
            return None

    output_subdir.mkdir(parents=True, exist_ok=True)

    if len(section_data) >= 2 and section_data[0:2] == b"\x1f\x8b":
        extracted_path = output_subdir / f"{file_label}.extracted"

        logger.info("Detected gzip compression in %s", file_label)

        if _extract_gzip_stream(section_data, extracted_path):
            size = extracted_path.stat().st_size
            logger.info("Extracted: %s (gzip) -> %s (%d bytes)", file_label, extracted_path.name, size)
            return str(extracted_path)

    if len(section_data) > 1024*1024:
        gzip_offsets = _find_gzip_offsets(section_data)

        if len(gzip_offsets) > 1:
            logger.info("Detected multiple gzip streams in %s, extracting all...", file_label)
            _process_large_binary_section(file_label, section_data, output_subdir, extracted_files)
            return str(output_subdir / file_label)

    output_path = output_subdir / file_label
    try:
        with open(output_path, "wb") as output_file:
            output_file.write(section_data)

        logger.info("Extracted: %s (raw) (%d bytes)", file_label, len(section_data))
        return str(output_path)
    except OSError as e:
        logger.error("Failed to save %s: %s", file_label, e)
        return None


def _process_raw_files(dump_dir: Path, output_dir: Path, extracted_files: dict[str, str]) -> None:
    """Find and process .raw files from dump directory"""

    for raw_file in dump_dir.rglob("*.raw"):
        try:
            parent_dir = raw_file.parent.name

            if not parent_dir.startswith("file-"):
                continue

            file_label = _extract_file_label(raw_file.parent)

            if not file_label or len(file_label) <= 1:
                file_label = parent_dir[5:].lower()

            if not _is_file_label_safe(file_label):
                logger.warning("Skipping unsafe firmware file label: %r", file_label)
                continue

            with open(raw_file, "rb") as raw_data_file:
                section_data = raw_data_file.read()

            output_subdir = output_dir / file_label
            extracted = _extract_from_section(
                file_label,
                section_data,
                output_subdir,
                output_dir,
                extracted_files,
            )

            if extracted:
                extracted_files[file_label] = extracted
        except OSError as e:
            logger.warning("Error processing %s: %s", raw_file, e)


def extract_images(firmware_file: str | Path, output_dir: str | Path = "extracted_images") -> dict[str, str]:
    """
    Extract images from a firmware file and return their labels and paths

    :param firmware_file: Path to the imagefv firmware image
    :type firmware_file: str | pathlib.Path

    :param output_dir: Directory where extracted files will be written
    :type output_dir: str | pathlib.Path

    :returns: A mapping from extracted image labels to output paths. The mapping is
        empty when no images were extracted
    :rtype: dict[str, str]
    :raises OSError: If the output directory cannot be created
    """

    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    extracted_files: dict[str, str] = {}
    firmware_file = Path(firmware_file)

    if not firmware_file.exists():
        logger.error("File not found: %s", firmware_file)
        return extracted_files

    try:
        with firmware_file.open("rb") as elf_data_file:
            data = elf_data_file.read()

        volumes = search_firmware_volumes(data)

        if not volumes:
            logger.error("No UEFI firmware volumes found in file")
            return extracted_files

        logger.info("Found %d firmware volume(s)", len(volumes))

        with tempfile.TemporaryDirectory() as tmpdir:
            tmpdir_path = Path(tmpdir)

            for offset in volumes:
                logger.info("Processing FV at offset: 0x%x", offset)
                try:
                    fv = FirmwareVolume(
                        data[offset-40:],
                        name=f"0x{offset-40:x}"
                    )

                    if fv.valid_header:
                        logger.info("FV Size: %d bytes", fv.size)

                        if fv.process():
                            logger.info("FV processed successfully, dumping files...")
                            with contextlib.redirect_stdout(io.StringIO()):
                                fv.dump(str(tmpdir_path))
                            _process_raw_files(tmpdir_path, output_dir, extracted_files)
                        else:
                            logger.warning("Failed to process FV at 0x%x", offset)
                    else:
                        logger.debug("Invalid FV header at offset 0x%x", offset)
                except OSError as e:
                    logger.warning("Error processing FV at offset 0x%x: %s", offset, e)

    except OSError as e:
        logger.error("Error processing ELF: %s", e)

    return extracted_files
