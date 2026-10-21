# MOGO Document Processing Service

This service owns asynchronous document processing tasks for MOGO.

Current scope:

- `POST /api/jobs/preview-convert`
- Converts Office documents to PDF with LibreOffice.
- Writes preview PDF to the configured storage.
- Calls back `admin-api` with preview metadata.
- Uses Redis + Celery worker for long-running jobs.
- Stores job state in MongoDB `document_jobs`.

Planned job types:

- `document_parse`
- `embedding`
- `index`

Run locally:

```bash
cd document-processing-service
python -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8200 --reload
```

Install Docling parser support:

```bash
.venv/bin/pip install --upgrade pip setuptools wheel
.venv/bin/pip install --prefer-binary -r requirements-docling.txt
```

The Docling requirements are pinned to the version set verified for this service. The standard Docker image also downloads the layout, table and RapidOCR model assets at build time and runs with Hugging Face offline mode enabled, so customer deployments do not download models on first document upload.

When Docling is not installed, the worker uses lightweight fallback parsers for TXT/Markdown/CSV/JSON, DOCX and text-based PDF files. Other formats fail with a clear task error until Docling is available.

Run worker locally:

```bash
cd document-processing-service
.venv/bin/celery -A app.workers.celery_app:celery_app worker --loglevel=info --queues=document_processing
```

LibreOffice must be installed on the host/container for Office preview conversion.
Redis and MongoDB must be available. In the repository root, `dev.sh` checks local Redis, creates `document-processing-service/.venv` when missing, installs base requirements, and starts both the API service and worker from that virtual environment.

Build Docker image:

```bash
cd document-processing-service
PUSH=false ./build_document_processing_bigpack.sh
```

The image includes the pinned Docling stack and offline model assets, LibreOffice, Chinese fonts and common OpenCV runtime libraries. The same image can run the API service or Celery worker:

```bash
docker run --rm -p 8200:8200 mogo-document-processing:dev-0.0.1 api
docker run --rm mogo-document-processing:dev-0.0.1 worker
```

For cluster deployment, set Redis, MongoDB, storage and callback variables through environment variables, for example `MOGO_DOC_PROCESSING_REDIS_URL`, `MOGO_DOC_PROCESSING_MONGODB_URI`, `MOGO_DOC_PROCESSING_MONGODB_DB`, `MOGO_DOC_PROCESSING_OSS_ENDPOINT`, `MOGO_DOC_PROCESSING_OSS_BUCKET`, `MOGO_DOC_PROCESSING_OSS_ACCESS_KEY_ID` and `MOGO_DOC_PROCESSING_OSS_ACCESS_KEY_SECRET`.

品牌归一（movo→mogo）说明：配置前缀已统一为 `MOGO_DOC_PROCESSING_`。更早的 `ASKAI_DOC_PROCESSING_` 在过渡期仍被接受，可直接沿用；建议改用 `MOGO_DOC_PROCESSING_` 前缀。
