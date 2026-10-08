FROM nginx:1.31.5-alpine3.24-slim

# Opt-in: only apply Alpine security patches when MOVO_SECURITY_REFRESH is set
# (CI passes its run id). Skipping keeps this layer cacheable locally.
ARG MOVO_SECURITY_REFRESH=
RUN if [ -n "${MOVO_SECURITY_REFRESH}" ] && [ "${MOVO_SECURITY_REFRESH}" != "false" ]; then \
        apk upgrade --no-cache; \
    else \
        echo "Skip apk upgrade (set MOVO_SECURITY_REFRESH to apply security patches)"; \
    fi
