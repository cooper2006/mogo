#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck source=internal_service_auth.sh
source "$SCRIPT_DIR/internal_service_auth.sh"

export ASKAI_ADMIN_JWT_SECRET="test-admin-jwt-secret"
unset ADMIN_BACKEND_SERVICE_TOKEN ASKAI_ADMIN_BACKEND_SERVICE_TOKEN \
    MOGO_DOC_PROCESSING_SERVICE_TOKEN ASKAI_ADMIN_DOCUMENT_PROCESSING_SERVICE_TOKEN \
    DOCUMENT_PROCESSING_SERVICE_TOKEN MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET
mogo_prepare_internal_service_auth
test -n "$ADMIN_BACKEND_SERVICE_TOKEN"
test "$ADMIN_BACKEND_SERVICE_TOKEN" = "$ASKAI_ADMIN_BACKEND_SERVICE_TOKEN"
test -n "$MOGO_DOC_PROCESSING_SERVICE_TOKEN"
test "$MOGO_DOC_PROCESSING_SERVICE_TOKEN" = "$DOCUMENT_PROCESSING_SERVICE_TOKEN"
test "$ASKAI_ADMIN_DOCUMENT_PROCESSING_SERVICE_TOKEN" = "$MOGO_DOC_PROCESSING_SERVICE_TOKEN"
test "$MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET" = "$ASKAI_ADMIN_JWT_SECRET"

ADMIN_BACKEND_SERVICE_TOKEN="canonical-token"
ASKAI_ADMIN_BACKEND_SERVICE_TOKEN="stale-alias"
mogo_prepare_internal_service_auth
test "$ADMIN_BACKEND_SERVICE_TOKEN" = "canonical-token"
test "$ASKAI_ADMIN_BACKEND_SERVICE_TOKEN" = "canonical-token"

unset ADMIN_BACKEND_SERVICE_TOKEN
ASKAI_ADMIN_BACKEND_SERVICE_TOKEN="legacy-token"
mogo_prepare_internal_service_auth
test "$ADMIN_BACKEND_SERVICE_TOKEN" = "legacy-token"
test "$ASKAI_ADMIN_BACKEND_SERVICE_TOKEN" = "legacy-token"

ASKAI_ADMIN_JWT_SECRET="canonical-jwt-secret"
MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET="stale-jwt-secret"
mogo_prepare_internal_service_auth
test "$MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET" = "stale-jwt-secret"
test "$ASKAI_ADMIN_JWT_SECRET" = "stale-jwt-secret"

unset MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET
ASKAI_ADMIN_JWT_SECRET="askai-canonical"
mogo_prepare_internal_service_auth
test "$MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET" = "askai-canonical"
test "$ASKAI_ADMIN_JWT_SECRET" = "askai-canonical"

# 品牌归一：MOGO_ 前缀优先于 ASKAI_
MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET="mogo-canonical"
ASKAI_ADMIN_JWT_SECRET="askai-stale"
mogo_prepare_internal_service_auth
test "$MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET" = "mogo-canonical"
test "$ASKAI_ADMIN_JWT_SECRET" = "mogo-canonical"

echo "internal service auth checks passed"
