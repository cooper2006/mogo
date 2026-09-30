# Portainer Stack 专用部署清单 —— 面向「无外网、镜像靠离线导入」的生产环境。
#
#!TEMPLATE-ONLY 【这是模板，不能直接上传部署】__MOGO_TAG__ 是版本占位符。
#!TEMPLATE-ONLY 用 deploy/production/prepare-release.sh 渲染出
#!TEMPLATE-ONLY prod-images-<TAG>/docker-compose.portainer.yml 后才是可直接部署的清单。
#!TEMPLATE-ONLY （以 #!TEMPLATE-ONLY 开头的行在渲染时会被删掉。）
#
# 与仓库根目录 docker-compose.yml 的差异（都是为了适配 Portainer Stack）：
#   1. 所有 ${VAR} 已解析为字面量。Portainer 会对 ${VAR} 做插值，未定义的变量会变成空串，
#      因此这里不留任何 ${...}；仅保留 $$（compose 转义成字面 $，供容器内 shell 使用）。
#   2. 所有镜像写死为 ghcr.io/himovo/<svc>:__MOGO_TAG__ 与官方基础镜像，pull_policy: never，
#      避免无外网时 Portainer 尝试拉取镜像而失败。
#   3. gateway 的 nginx.conf 原本是相对路径 bind mount（./deploy/docker/nginx.conf），
#      Portainer Stack 会把相对路径解析到它自己的 stack 目录，文件必然不存在。
#      改为 base64 内嵌到环境变量，容器启动时解码落盘。
#   4. 省略 runtime-pool profile 下的 dsh-runtime-host-1/2/3 与 dsh-runtime-host-lb
#      （默认不启动，且 lb 依赖 nginx 基础镜像，生产上不需要）。
#   5. 去掉顶层 name:，项目名由 Portainer 的 Stack 名决定（部署时填 mogo）。
#
# 前置条件：以下 11 个镜像已通过 Portainer 导入到生产 Docker：
#   alpine:3.21 / mongo:6.0.20 / redis:7.4.2-alpine / semitechnologies/weaviate:1.25.7
#   ghcr.io/himovo/{chat-api,admin-api,document-parser,dsh-runtime-host,user-web,admin-web,gateway}:__MOGO_TAG__
# 另：document-api 与 document-worker 共用 ghcr.io/himovo/document-parser:__MOGO_TAG__。

x-python-healthcheck: &python-healthcheck
  interval: 10s
  timeout: 5s
  retries: 20
  start_period: 30s

services:
  bootstrap:
    image: alpine:3.21
    pull_policy: never
    restart: "no"
    environment:
      MOGO_PORT: "3000"
    volumes:
      - deployment-secrets:/run/askai-secrets
    command:
      - /bin/sh
      - -ec
      - |
        umask 077
        secret_file=/run/askai-secrets/runtime.env
        random_hex() { head -c 48 /dev/urandom | od -An -tx1 | tr -d ' \n'; }
        if [ ! -s "$$secret_file" ]; then
          admin_secret="$$(random_hex)"
          admin_backend_service_token="$$(random_hex)"
          document_service_token="$$(random_hex)"
          document_callback_token="$$(random_hex)"
          temp_file="$${secret_file}.tmp"
          {
            echo "END_USER_AUTH_SECRET=$$(random_hex)"
            echo "ASKAI_ADMIN_JWT_SECRET=$$admin_secret"
            echo "ADMIN_BACKEND_SERVICE_TOKEN=$$admin_backend_service_token"
            echo "ASKAI_ADMIN_BACKEND_SERVICE_TOKEN=$$admin_backend_service_token"
            echo "MODEL_CONFIG_SECRET=$$admin_secret"
            echo "DSH_MODEL_GATEWAY_SIGNING_SECRET=$$(random_hex)"
            echo "DSH_RUNTIME_HOST_TOKEN=$$(random_hex)"
            echo "DOCUMENT_PROCESSING_SERVICE_TOKEN=$$document_service_token"
            echo "ASKAI_ADMIN_DOCUMENT_PROCESSING_SERVICE_TOKEN=$$document_service_token"
            echo "MOVO_DOC_PROCESSING_SERVICE_TOKEN=$$document_service_token"
            echo "ASKAI_ADMIN_DOCUMENT_PROCESSING_CALLBACK_TOKEN=$$document_callback_token"
            echo "MOVO_DOC_PROCESSING_CALLBACK_TOKEN=$$document_callback_token"
            echo "MOVO_DOC_PROCESSING_ADMIN_JWT_SECRET=$$admin_secret"
          } > "$$temp_file"
          mv "$$temp_file" "$$secret_file"
        fi
        if ! grep -q '^DSH_RUNTIME_HOST_TOKEN=' "$$secret_file"; then
          temp_file="$${secret_file}.tmp"
          cp "$$secret_file" "$$temp_file"
          echo "DSH_RUNTIME_HOST_TOKEN=$$(random_hex)" >> "$$temp_file"
          mv "$$temp_file" "$$secret_file"
        fi
        admin_backend_service_token="$$(sed -n 's/^ADMIN_BACKEND_SERVICE_TOKEN=//p' "$$secret_file" | head -n 1)"
        if [ -z "$$admin_backend_service_token" ]; then
          admin_backend_service_token="$$(sed -n 's/^ASKAI_ADMIN_BACKEND_SERVICE_TOKEN=//p' "$$secret_file" | head -n 1)"
        fi
        if [ -z "$$admin_backend_service_token" ]; then
          admin_backend_service_token="$$(random_hex)"
        fi
        temp_file="$${secret_file}.tmp"
        sed '/^ADMIN_BACKEND_SERVICE_TOKEN=/d; /^ASKAI_ADMIN_BACKEND_SERVICE_TOKEN=/d' "$$secret_file" > "$$temp_file"
        {
          echo "ADMIN_BACKEND_SERVICE_TOKEN=$$admin_backend_service_token"
          echo "ASKAI_ADMIN_BACKEND_SERVICE_TOKEN=$$admin_backend_service_token"
        } >> "$$temp_file"
        mv "$$temp_file" "$$secret_file"
        echo "MOVO deployment secrets are ready."
        echo "After services become healthy, open http://localhost:$${MOGO_PORT:-3000}/admin/setup"

  mongo:
    image: mongo:6.0.20
    pull_policy: never
    restart: unless-stopped
    volumes:
      - mongo-data:/data/db
    networks:
      - backend
    healthcheck:
      test: ["CMD", "mongosh", "--quiet", "--eval", "db.adminCommand('ping').ok"]
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 20s

  redis:
    image: redis:7.4.2-alpine
    pull_policy: never
    restart: unless-stopped
    command: ["redis-server", "--appendonly", "yes"]
    volumes:
      - redis-data:/data
    networks:
      - backend
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 10s
      timeout: 5s
      retries: 20

  weaviate:
    image: semitechnologies/weaviate:1.25.7
    pull_policy: never
    restart: unless-stopped
    environment:
      QUERY_DEFAULTS_LIMIT: "25"
      AUTHENTICATION_ANONYMOUS_ACCESS_ENABLED: "true"
      PERSISTENCE_DATA_PATH: /var/lib/weaviate
      DEFAULT_VECTORIZER_MODULE: none
      CLUSTER_HOSTNAME: node1
      DISABLE_TELEMETRY: "true"
    volumes:
      - weaviate-data:/var/lib/weaviate
    networks:
      - backend
    healthcheck:
      test: ["CMD-SHELL", "wget --spider -q http://127.0.0.1:8080/v1/.well-known/ready"]
      interval: 10s
      timeout: 5s
      retries: 30
      start_period: 30s

  # DSH Runtime Host 把 kernel session 状态放在进程内存里，同一个 kernel_session_id
  # 必须始终落到同一个实例。默认单实例。
  dsh-runtime-host:
    image: ghcr.io/himovo/dsh-runtime-host:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - dsh-runtime-data:/data/dsh-runtime
    depends_on:
      bootstrap:
        condition: service_completed_successfully
    networks:
      - backend
    healthcheck:
      test:
        - CMD-SHELL
        - >-
          set -a; . /run/askai-secrets/runtime.env; set +a;
          node -e "fetch('http://127.0.0.1:8101/health',{headers:{authorization:'Bearer '+process.env.DSH_RUNTIME_HOST_TOKEN}}).then(r=>{if(!r.ok)process.exit(1);return r.json()}).then(v=>{if(v.ok!==true||v.kernel!=='dsh')process.exit(1)}).catch(()=>process.exit(1))"
      interval: 10s
      timeout: 5s
      retries: 20
      start_period: 20s

  chat-api:
    image: ghcr.io/himovo/chat-api:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    environment:
      OPENAI_API_KEY: ""
      MONGODB_URI: mongodb://mongo:27017
      MONGODB_DB: mogo_dev
      ALLOWED_ORIGINS: http://localhost:3000
      STORAGE_BACKEND: local
      LOCAL_STORAGE_PATH: /app/storage
      FILE_PUBLIC_PATH_PREFIX: /askai-api/api/files
      BACKEND_INTERNAL_BASE_URL: http://chat-api:8000
      ADMIN_API_BASE_URL: http://admin-api:8100
      DOCUMENT_PROCESSING_BASE_URL: http://document-api:8200
      KNOWLEDGE_LOCAL_STORAGE_DIR: /data/knowledge-documents
      TOKEN_USAGE_PUSH_ENABLED: "false"
      AUTO_INSTALL_SYSTEM_DEPS_ON_START: "false"
      AUTO_INSTALL_PLAYWRIGHT_ON_START: "false"
      REQUEST_DEBUG_SNAPSHOT_ENABLED: "false"
      DSH_RUNTIME_HOST_URL: http://dsh-runtime-host:8101
      DSH_RUNTIME_HOSTS_URL: ""
      DSH_TOOL_GATEWAY_URL: http://chat-api:8000/internal/dsh/tools
      DSH_MODEL_GATEWAY_URL: http://chat-api:8000/internal/dsh/model/generate
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - askai-storage:/app/storage
      - knowledge-storage:/data/knowledge-documents
    depends_on:
      bootstrap:
        condition: service_completed_successfully
      mongo:
        condition: service_healthy
      document-api:
        condition: service_healthy
      dsh-runtime-host:
        condition: service_healthy
    networks:
      - public
      - backend
    healthcheck:
      <<: *python-healthcheck
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()"]

  admin-api:
    image: ghcr.io/himovo/admin-api:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    environment:
      ASKAI_ADMIN_APP_ENV: production
      ASKAI_ADMIN_MONGODB_URI: mongodb://mongo:27017
      ASKAI_ADMIN_MONGODB_DB: mogo_dev
      ASKAI_ADMIN_TENANT_BOOTSTRAP_ADMIN_ENABLED: "false"
      ASKAI_ADMIN_BACKEND_BASE_URL: http://chat-api:8000
      ASKAI_ADMIN_PUBLIC_BASE_URL: ""
      ASKAI_ADMIN_REDIS_URL: redis://redis:6379/0
      ASKAI_ADMIN_WEAVIATE_ENDPOINT: http://weaviate:8080
      ASKAI_ADMIN_DOCUMENT_PROCESSING_BASE_URL: http://document-api:8200
      ASKAI_ADMIN_ADMIN_API_PUBLIC_BASE_URL: http://admin-api:8100
      ASKAI_ADMIN_USER_PORTAL_BASE_URL: http://localhost:3000
      ASKAI_ADMIN_KNOWLEDGE_STORAGE_TYPE: local
      ASKAI_ADMIN_KNOWLEDGE_LOCAL_STORAGE_DIR: /data/knowledge-documents
      ASKAI_ADMIN_ADMIN_STATIC_DIR: /data/admin-static
      ASKAI_ADMIN_CORS_ORIGINS: '["http://localhost:3000"]'
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - knowledge-storage:/data/knowledge-documents
      - admin-static:/data/admin-static
    depends_on:
      bootstrap:
        condition: service_completed_successfully
      mongo:
        condition: service_healthy
      document-api:
        condition: service_healthy
    networks:
      - public
      - backend
    healthcheck:
      <<: *python-healthcheck
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=3).read()"]

  document-api:
    image: ghcr.io/himovo/document-parser:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    command: ["api"]
    environment: &document-environment
      MOVO_DOC_PROCESSING_APP_ENV: production
      MOVO_DOC_PROCESSING_LOCAL_STORAGE_DIR: /data/knowledge-documents
      MOVO_DOC_PROCESSING_REDIS_URL: redis://redis:6379/0
      MOVO_DOC_PROCESSING_MONGODB_URI: mongodb://mongo:27017
      MOVO_DOC_PROCESSING_MONGODB_DB: mogo_dev
      MOVO_DOC_PROCESSING_WEAVIATE_ENDPOINT: http://weaviate:8080
      MOVO_DOC_PROCESSING_WEAVIATE_COLLECTION_NAME: AskAIKnowledgeChunks
      MOVO_DOC_PROCESSING_WEAVIATE_DISTANCE_METRIC: cosine
      MOVO_DOC_PROCESSING_AZURE_EMBEDDING_ENDPOINT: ""
      MOVO_DOC_PROCESSING_AZURE_EMBEDDING_DEPLOYMENT_NAME: text_embedding
      MOVO_DOC_PROCESSING_AZURE_EMBEDDING_API_VERSION: 2025-04-01-preview
      MOVO_DOC_PROCESSING_AZURE_EMBEDDING_API_KEY: ""
      MOVO_DOC_PROCESSING_DASHSCOPE_API_KEY: ""
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - knowledge-storage:/data/knowledge-documents
    depends_on:
      bootstrap:
        condition: service_completed_successfully
      mongo:
        condition: service_healthy
      redis:
        condition: service_healthy
      weaviate:
        condition: service_healthy
    networks:
      - public
      - backend
    healthcheck:
      <<: *python-healthcheck
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8200/api/health', timeout=3).read()"]

  document-worker:
    image: ghcr.io/himovo/document-parser:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    command: ["worker"]
    environment: *document-environment
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - knowledge-storage:/data/knowledge-documents
    depends_on:
      bootstrap:
        condition: service_completed_successfully
      mongo:
        condition: service_healthy
      redis:
        condition: service_healthy
      weaviate:
        condition: service_healthy
    networks:
      - public
      - backend

  user-web:
    image: ghcr.io/himovo/user-web:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    networks:
      - public
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/ >/dev/null"]
      interval: 10s
      timeout: 5s
      retries: 20

  admin-web:
    image: ghcr.io/himovo/admin-web:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    networks:
      - public
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/ >/dev/null"]
      interval: 10s
      timeout: 5s
      retries: 20

  gateway:
    image: ghcr.io/himovo/gateway:__MOGO_TAG__
    pull_policy: never
    restart: unless-stopped
    ports:
      - "3000:80"
    environment:
      # deploy/docker/nginx.conf 的 base64。见文件头说明：Portainer Stack 无法使用
      # 相对路径 bind mount，且 compose 插值会破坏 nginx 配置里的 $http_upgrade 等变量，
      # 所以编码后在容器启动时解码落盘。
      MOGO_GATEWAY_NGINX_CONF_B64: "bWFwICRodHRwX3VwZ3JhZGUgJGNvbm5lY3Rpb25fdXBncmFkZSB7CiAgICBkZWZhdWx0IHVwZ3JhZGU7CiAgICAnJyBjbG9zZTsKfQoKc2VydmVyIHsKICAgIGxpc3RlbiA4MDsKICAgIHNlcnZlcl9uYW1lIF87CiAgICBhYnNvbHV0ZV9yZWRpcmVjdCBvZmY7CiAgICBjbGllbnRfbWF4X2JvZHlfc2l6ZSAyMjBtOwoKICAgIGxvY2F0aW9uID0gL2hlYWx0aHogewogICAgICAgIGFjY2Vzc19sb2cgb2ZmOwogICAgICAgIGFkZF9oZWFkZXIgQ29udGVudC1UeXBlIHRleHQvcGxhaW47CiAgICAgICAgcmV0dXJuIDIwMCAnb2snOwogICAgfQoKICAgIGxvY2F0aW9uID0gL3NldHVwIHsKICAgICAgICByZXR1cm4gMzAyIC9hZG1pbi9zZXR1cDsKICAgIH0KCiAgICBsb2NhdGlvbiA9IC9hZG1pbiB7CiAgICAgICAgcmV0dXJuIDMwMiAvYWRtaW4vOwogICAgfQoKICAgIGxvY2F0aW9uIC9hZG1pbi8gewogICAgICAgIHByb3h5X3Bhc3MgaHR0cDovL2FkbWluLXdlYi87CiAgICAgICAgcHJveHlfaHR0cF92ZXJzaW9uIDEuMTsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIEhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLUhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLVByb3RvICRzY2hlbWU7CiAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Gb3IgJHByb3h5X2FkZF94X2ZvcndhcmRlZF9mb3I7CiAgICB9CgogICAgbG9jYXRpb24gL2FkbWluLWFwaS8gewogICAgICAgIHByb3h5X3Bhc3MgaHR0cDovL2FkbWluLWFwaTo4MTAwLzsKICAgICAgICBwcm94eV9odHRwX3ZlcnNpb24gMS4xOwogICAgICAgIHByb3h5X3NldF9oZWFkZXIgSG9zdCAkaHR0cF9ob3N0OwogICAgICAgIHByb3h5X3NldF9oZWFkZXIgWC1Gb3J3YXJkZWQtSG9zdCAkaHR0cF9ob3N0OwogICAgICAgIHByb3h5X3NldF9oZWFkZXIgWC1SZWFsLUlQICRyZW1vdGVfYWRkcjsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLUZvciAkcHJveHlfYWRkX3hfZm9yd2FyZGVkX2ZvcjsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLVByb3RvICRzY2hlbWU7CiAgICAgICAgcHJveHlfcmVhZF90aW1lb3V0IDYwMHM7CiAgICAgICAgcHJveHlfc2VuZF90aW1lb3V0IDYwMHM7CiAgICAgICAgcHJveHlfYnVmZmVyaW5nIG9mZjsKICAgIH0KCiAgICBsb2NhdGlvbiAvYXNrYWktYXBpLyB7CiAgICAgICAgcHJveHlfcGFzcyBodHRwOi8vY2hhdC1hcGk6ODAwMC87CiAgICAgICAgcHJveHlfaHR0cF92ZXJzaW9uIDEuMTsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIEhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLUhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtUmVhbC1JUCAkcmVtb3RlX2FkZHI7CiAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Gb3IgJHByb3h5X2FkZF94X2ZvcndhcmRlZF9mb3I7CiAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Qcm90byAkc2NoZW1lOwogICAgICAgIHByb3h5X3NldF9oZWFkZXIgVXBncmFkZSAkaHR0cF91cGdyYWRlOwogICAgICAgIHByb3h5X3NldF9oZWFkZXIgQ29ubmVjdGlvbiAkY29ubmVjdGlvbl91cGdyYWRlOwogICAgICAgIHByb3h5X3JlYWRfdGltZW91dCA2MDBzOwogICAgICAgIHByb3h5X3NlbmRfdGltZW91dCA2MDBzOwogICAgICAgIHByb3h5X2J1ZmZlcmluZyBvZmY7CiAgICB9CgogICAgbG9jYXRpb24gL2FwaS8gewogICAgICAgIHByb3h5X3Bhc3MgaHR0cDovL2NoYXQtYXBpOjgwMDA7CiAgICAgICAgcHJveHlfaHR0cF92ZXJzaW9uIDEuMTsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIEhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLUhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtUmVhbC1JUCAkcmVtb3RlX2FkZHI7CiAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Gb3IgJHByb3h5X2FkZF94X2ZvcndhcmRlZF9mb3I7CiAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Qcm90byAkc2NoZW1lOwogICAgICAgIHByb3h5X3NldF9oZWFkZXIgVXBncmFkZSAkaHR0cF91cGdyYWRlOwogICAgICAgIHByb3h5X3NldF9oZWFkZXIgQ29ubmVjdGlvbiAkY29ubmVjdGlvbl91cGdyYWRlOwogICAgICAgIHByb3h5X3JlYWRfdGltZW91dCA2MDBzOwogICAgICAgIHByb3h5X3NlbmRfdGltZW91dCA2MDBzOwogICAgICAgIHByb3h5X2J1ZmZlcmluZyBvZmY7CiAgICB9CgogICAgbG9jYXRpb24gLyB7CiAgICAgICAgcHJveHlfcGFzcyBodHRwOi8vdXNlci13ZWI7CiAgICAgICAgcHJveHlfaHR0cF92ZXJzaW9uIDEuMTsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIEhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLUhvc3QgJGh0dHBfaG9zdDsKICAgICAgICBwcm94eV9zZXRfaGVhZGVyIFgtRm9yd2FyZGVkLVByb3RvICRzY2hlbWU7CiAgICAgICAgcHJveHlfc2V0X2hlYWRlciBYLUZvcndhcmRlZC1Gb3IgJHByb3h5X2FkZF94X2ZvcndhcmRlZF9mb3I7CiAgICB9Cn0K"
    command:
      - /bin/sh
      - -ec
      - |
        printf '%s' "$$MOGO_GATEWAY_NGINX_CONF_B64" | base64 -d > /etc/nginx/conf.d/default.conf
        nginx -t
        exec nginx -g 'daemon off;'
    depends_on:
      chat-api:
        condition: service_healthy
      admin-api:
        condition: service_healthy
      user-web:
        condition: service_healthy
      admin-web:
        condition: service_healthy
    networks:
      - public
    healthcheck:
      test: ["CMD-SHELL", "wget -qO- http://127.0.0.1/healthz >/dev/null"]
      interval: 10s
      timeout: 5s
      retries: 20

networks:
  public:
  backend:
    internal: true

volumes:
  deployment-secrets:
    name: movo_deployment-secrets
  mongo-data:
    name: movo_mongo-data
  redis-data:
    name: movo_redis-data
  weaviate-data:
    name: movo_weaviate-data
  dsh-runtime-data:
    name: movo_dsh-runtime-data
  askai-storage:
    name: movo_askai-storage
  knowledge-storage:
    name: movo_knowledge-storage
  admin-static:
    name: movo_admin-static
