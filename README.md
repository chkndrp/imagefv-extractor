# imagefv-extractor
![PyPI - Version](https://img.shields.io/pypi/v/imagefv-extractor?logo=python&logoColor=white) ![PyPI - Downloads](https://img.shields.io/pypi/dm/imagefv-extractor?logo=python&logoColor=white) ![PyPI - Typing](https://img.shields.io/pypi/types/imagefv-extractor?logo=python&logoColor=white)

Extract bootloader/charging pictures from `imagefv` blobs

---

## Install
```shell
# With PyPi (recommended)
pip install imagefv_extractor
```

```shell
# When running from source/clone
pip install -r requirements.txt
```

---

## Using as a CLI tool:
```
usage: extractor.py [-h] [-o OUTPUT] [-v] input [input ...]

Extract bootloader/charging pictures from imagefv blobs

positional arguments:
  input                Input file(s) to process

options:
  -h, --help           show this help message and exit
  -o, --output OUTPUT  Output directory (default: extracted_images)
  -v, --verbose        Enable verbose logging (default: False)
```

1. Prepare an `imagefv` blob from firmware or pull it from a device via `adb`, then run:
2. Run the CLI against the image

```shell
# PyPi
python -m imagefv_extractor ./imagefv.bin
```

```shell
# Source/clone
python ./extractor.py ./imagefv.bin
```

---

## Using as a Python library

This project can also be used as a library for other tools that want to integrate this.
There is one public function:

```python
extract_images(firmware_file, output_dir="extracted_images") -> dict[str, str]
```

- `firmware_file` (`str | pathlib.Path`): Path to the imagefv firmware image.
- `output_dir` (`str | pathlib.Path`): Directory where extracted files will be written. Defaults to `"extracted_images"`.
- **Returns:**
    - A mapping of extracted image labels to their output paths.
    - An empty mapping if the input is unrecognized or no images are extracted.
- **Raises:** `OSError` if the output directory cannot be created.

#### **Quick example:**
```python
# from pathlib import Path
from imagefv_extractor import extract_images

# extracted = extract_images(
#     Path("./imagefv.elf"),
#     output_dir=Path("./extracted_images"),
# )

extracted = extract_images(
    "./imagefv.elf",
    output_dir="./extracted_images",
)

for label, path in extracted.items():
    print(f"{label}: {path}")
    # Example output:
    # logo.img_raw: extracted_images/logo.img/logo.img
    # logo.img_archive_0: extracted_images/logo.img/images/archive_0000.bmp
    # ...
```

## How it works:
1. The script scans the input file for `UEFI` structures using the `uefi-firmware` package
2. If it finds them, it dumps all files/sections to a temporary directory
3. Then it identifies the dumped files for known types (defined in `magic_map` struct) and organizes them
4. And also if found, any files containing GZip archives (most commonly `logo.img`) are extracted

## Is it possible to repackage it, and create custom splashes?
During investigation, i have noticed the `imagefv` blob contains some CoT certificates, 
so it is absolutely possible that this partition is verified during the `XBL` phase,
causing the device not to boot if it is altered.

```
DECIMAL       HEXADECIMAL     DESCRIPTION
--------------------------------------------------------------------------------
0             0x0             ELF, 32-bit LSB executable, ARM, version 1 (SYSV)
4096          0x1000          UEFI PI Firmware Volume, volume size: 6291456, header size: 0, revision: 0, EFI Firmware File System v2, GUID: 8C8CE578-8A3D-4F1C-3599-896185C32DD3
4216          0x1078          LZMA compressed data, properties: 0x5D, dictionary size: 16777216 bytes, uncompressed size: 7237640 bytes
6296088       0x601218        Certificate in DER format (x509 v3), header length: 4, sequence length: 596
6296688       0x601470        Certificate in DER format (x509 v3), header length: 4, sequence length: 685
6297377       0x601721        Certificate in DER format (x509 v3), header length: 4, sequence length: 720
```

I also couldn't find any open-source (re)packaging tools for it either, so one would need to be created. However i'm not risking a hard-brick.

Here are some references to it being loaded on `xiaomi-amethyst` during `ABL` phase:
```
GetAdjustLogoIndexpDisplayInfo->uDisplayWidth 1220: 2712, country_info = 1, uLogoIndex = 0, realLogoIndex = 128!
Display_Utils_RenderSplashScreen: load imagefv name is: logo.img
LoadCompressedImageFromLogoData: Setvariable Logo Image returned eStatus: Success, LogoMagic: LOGO!!!
LoadCompressedImageFromLogoData: LogoCompressedBlockNum:9 LogoCompressedBytesNum:35458 
Display_Utils_RenderSplashScreen: CompressedData size is: 35458 logo index = 128
DeCompressLogoData: DecompressBufferSize:9925976  ScratchSize:131072
DeCompressLogoData: logo decompress done, use time: 19ms
Display_Utils_RenderSplashScreen: OEM Logo Successfully Loaded
```

## Requirements
- Python 3.10 or newer
- Installed `uefi_firmware` pip package
