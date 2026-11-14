FROM python:3.10-slim-bookworm
WORKDIR /app
COPY proxy.py .
USER 65534:65534
CMD ["python", "proxy.py"]
