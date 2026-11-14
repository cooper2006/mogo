from __future__ import annotations

import hashlib
import os
import shutil
import urllib.request
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RapidOcrAsset:
    relative_path: str
    url: str
    sha256: str | None = None


# Docling's default RapidOCR downloader only guarantees the default Chinese
# models. MOGO configures PDF OCR for both Chinese and English, so the English
# detector, recognizer and recognition dictionary must also be bundled.
REQUIRED_ENGLISH_ASSETS = (
    RapidOcrAsset(
        relative_path="onnx/PP-OCRv4/det/en_PP-OCRv3_det_mobile.onnx",
        url=(
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/"
            "onnx/PP-OCRv4/det/en_PP-OCRv3_det_mobile.onnx"
        ),
        sha256="ea07c15d38ac40cd69da3c493444ec75b44ff23840553ff8ba102c1219ed39c2",
    ),
    RapidOcrAsset(
        relative_path="onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx",
        url=(
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/"
            "onnx/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile.onnx"
        ),
        sha256="e8770c967605983d1570cdf5352041dfb68fa0c21664f49f47b155abd3e0e318",
    ),
    RapidOcrAsset(
        relative_path="paddle/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile/en_dict.txt",
        url=(
            "https://www.modelscope.cn/models/RapidAI/RapidOCR/resolve/v3.8.0/"
            "paddle/PP-OCRv4/rec/en_PP-OCRv4_rec_mobile/en_dict.txt"
        ),
    ),
)


def required_english_paths(model_root: Path) -> tuple[Path, ...]:
    return tuple(model_root / asset.relative_path for asset in REQUIRED_ENGLISH_ASSETS)


def download_required_english_assets(model_root: Path) -> None:
    timeout = float(os.environ.get("MOGO_MODEL_DOWNLOAD_TIMEOUT", "120"))
    for asset in REQUIRED_ENGLISH_ASSETS:
        destination = model_root / asset.relative_path
        if _is_valid(destination, asset.sha256):
            print(f"RapidOCR asset already present: {destination}")
            continue

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f"{destination.name}.tmp")
        temporary.unlink(missing_ok=True)
        print(f"Downloading RapidOCR asset: {asset.url}")
        try:
            with urllib.request.urlopen(asset.url, timeout=timeout) as response:
                with temporary.open("wb") as output:
                    shutil.copyfileobj(response, output)
            if not _is_valid(temporary, asset.sha256):
                raise RuntimeError(f"RapidOCR asset checksum validation failed: {asset.relative_path}")
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)


def _is_valid(path: Path, expected_sha256: str | None) -> bool:
    if not path.is_file() or path.stat().st_size == 0:
        return False
    if not expected_sha256:
        return True
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest() == expected_sha256
