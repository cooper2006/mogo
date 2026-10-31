from __future__ import annotations

import os
from pathlib import Path

from docling.datamodel.pipeline_options import PdfPipelineOptions, RapidOcrOptions
from docling.models.stages.ocr.rapid_ocr_model import RapidOcrModel
from docling.pipeline.standard_pdf_pipeline import StandardPdfPipeline

from rapidocr_assets import required_english_paths


def main() -> None:
    artifacts_path = Path(os.environ.get("DOCLING_ARTIFACTS_PATH", "/opt/docling/models"))
    if not artifacts_path.is_dir() or not any(artifacts_path.rglob("*")):
        raise RuntimeError(f"Docling model assets are missing: {artifacts_path}")
    rapidocr_root = artifacts_path / RapidOcrModel._model_repo_folder
    missing = [str(path) for path in required_english_paths(rapidocr_root) if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required RapidOCR English assets are missing: {', '.join(missing)}")

    options = PdfPipelineOptions(artifacts_path=artifacts_path)
    options.do_ocr = True
    options.ocr_options = RapidOcrOptions(
        force_full_page_ocr=True,
        lang=["chinese", "english"],
        backend="onnxruntime",
    )
    StandardPdfPipeline(options)
    print(f"Docling offline runtime ready: {artifacts_path}")


if __name__ == "__main__":
    main()
