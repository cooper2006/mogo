FROM python:3.10-slim-bookworm

ARG MOGO_PIP_INDEX_URL=
WORKDIR /app
COPY requirements.txt .

# pip ships its own CA bundle (vendored certifi) and ignores the system trust
# store. Behind a TLS-terminating proxy the server certificate chains to a
# private root CA that only the proxy's own store trusts, so pip's bundle fails
# the handshake with CERTIFICATE_VERIFY_FAILED while the rest of the image
# verifies the same host fine.
#
# The fix is to hand pip a CA bundle that includes the proxy's root. It is
# mounted rather than COPYed: the mount is read-only, exists only for this RUN,
# and BuildKit still folds the file's digest into the cache key -- so an
# unchanged CA hits cache just like COPY did, and the certificate never lands
# in a shipped image layer.
#
# Same contract as the other bundles (scripts/apt_packages_bundle.sh and
# friends): the file is not tracked in git. Run `bash scripts/proxy_ca_bundle.sh
# pack` once after cloning -- the bind mount fails loudly when the source is
# missing, which is deliberate, because a build that silently fell back to
# pip's own bundle would fail later with a confusing TLS error.
ARG TARGETARCH
RUN --mount=type=bind,source=proxy-root.crt,target=/tmp/proxy-root.crt \
    set -eux; \
    pip_cert_args=""; \
    if [ -s /tmp/proxy-root.crt ]; then \
        cat /etc/ssl/certs/ca-certificates.crt /tmp/proxy-root.crt > /tmp/combined-ca.crt; \
        pip_cert_args="--cert /tmp/combined-ca.crt"; \
        echo "Using system CA bundle plus the proxy root for pip"; \
    else \
        echo "No proxy root CA in the build context; pip uses its own bundle."; \
    fi; \
    if [ -n "${MOGO_PIP_INDEX_URL}" ]; then \
        python -m pip install --no-cache-dir ${pip_cert_args} --index-url "${MOGO_PIP_INDEX_URL}" -r requirements.txt; \
    else \
        python -m pip install --no-cache-dir ${pip_cert_args} -r requirements.txt; \
    fi; \
    rm -f /tmp/combined-ca.crt

COPY app ./app
COPY entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8300"]
