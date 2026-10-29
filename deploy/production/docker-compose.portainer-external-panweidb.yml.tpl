# Portainer Stack 专门化清单 —— 面向「无外网 + AMD64 + 外部 PanWeiDB + 栈内 Redis」的生产环境。
#
#!TEMPLATE-ONLY 【这是模板，不能直接上传部署】__MOGO_TAG__ 是版本占位符。
#!TEMPLATE-ONLY 用 deploy/production/prepare-release.sh --external-db 渲染出
#!TEMPLATE-ONLY prod-images-<TAG>/docker-compose.portainer.yml 后才是可直接部署的清单。
#!TEMPLATE-ONLY （以 #!TEMPLATE-ONLY 开头的行在渲染时会被删掉。）
#
# 与 docker-compose.portainer.yml.tpl（自带数据库版本）的差异：
#   1. **去掉 mongo 容器**：MongoDB 不再使用（数据后端切到 PanWeiDB），应用也不依赖它。
#      本清单所有服务不连 mongo，也不声明 mongo 依赖。
#   2. **去掉 panweidb 容器**：PanWeiDB 由外部实例提供（本例 172.17.5.145:17700）。
#      应用通过 PANWEIDB_HOST / PANWEIDB_PORT / ... 连接外部库，不再起内部 panweidb。
#   3. **保留 redis 容器（栈内）**：Redis 仍由本栈拉起（redis:7.4.2-alpine），
#      应用通过 redis://redis:6379/<db> 连接。需要外部 Redis 时可把
#      ASKAI_ADMIN_REDIS_URL / MOGO_DOC_PROCESSING_REDIS_URL / MOGO_KERNEL_REDIS_URL
#      改成外部地址，并把 redis 服务挪到 profiles: [never]。
#   4. **保留 weaviate 容器**：向量库仍由本栈拉起（semitechnologies/weaviate:1.25.7）。
#   5. MOGO_DATA_BACKEND 固定为 panweidb，应用走 PanWeiDB 数据后端。
#   6. 外部 PanWeiDB 连接信息**默认写死**进清单（见下），运维可按需改 Portainer 环境变量面板。
#
# 与基础 portainer 模板一致的适配点：
#   - 所有 ${VAR} 已解析为字面量；仅保留 $$（compose 转义成字面 $，供容器内 shell 使用）。
#   - 所有镜像写死 + pull_policy: never，避免无外网时拉取失败。
#   - 每个服务显式 platform: linux/amd64。离线导入的镜像本来就是 amd64，这条把约束
#     写进清单：镜像架构不符时 Docker 在启动阶段直接报 platform mismatch，而不是等到
#     进程 exec 才以 "exec format error" 暴露。amd64 主机上该字段无副作用。
#   - gateway 的 nginx.conf 以 base64 内嵌（见 base 模板说明），非 bind mount。
#   - 去掉顶层 name:，项目名由 Portainer 的 Stack 名决定（部署时填 mogo）。
#
# 前置条件：以下镜像已通过 Portainer 离线导入到生产 Docker：
#   alpine:3.21 / redis:7.4.2-alpine / semitechnologies/weaviate:1.25.7
#   ghcr.io/mogoai/{chat-api,admin-api,document-parser,dsh-runtime-host,user-web,admin-web,gateway}:__MOGO_TAG__
# 另：document-api 与 document-worker 共用 ghcr.io/mogoai/document-parser:__MOGO_TAG__。
#
# redis / weaviate 两个镜像名保留成 ${VAR:-默认值} 形式（Portainer Stack 环境变量面板可覆盖，
# 指到内网镜像仓库里的同名镜像）；其余镜像名已写死。
#
# 外部 PanWeiDB 连接信息（默认，对应运维提供的实例）：
#   PANWEIDB_HOST=172.17.5.145
#   PANWEIDB_PORT=17700
#   PANWEIDB_USER=boncuser
#   PANWEIDB_PASSWORD=1qaz!QAZ
#   PANWEIDB_DB=mogo
#   PANWEIDB_SCHEMA=public
# ⚠️ 注意：PANWEIDB_PASSWORD 含 `!`，运维如在 Portainer 环境变量面板手动填写，
#   请直接原样粘贴，不要加单引号（shell 引号会让 `!` history 展开异常）。

x-python-healthcheck: &python-healthcheck
  interval: 10s
  timeout: 5s
  retries: 20
  start_period: 30s

services:
  bootstrap:
    image: alpine:3.21
    platform: linux/amd64
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
            echo "MOGO_DOC_PROCESSING_SERVICE_TOKEN=$$document_service_token"
            echo "ASKAI_ADMIN_DOCUMENT_PROCESSING_CALLBACK_TOKEN=$$document_callback_token"
            echo "MOGO_DOC_PROCESSING_CALLBACK_TOKEN=$$document_callback_token"
            echo "MOGO_DOC_PROCESSING_ADMIN_JWT_SECRET=$$admin_secret"
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
        # runtime.env 会被 node 用户容器只读挂载，需要 world-readable
        # 目录也要 world-executable，否则 node 用户无法穿越目录读取文件
        chmod 755 /run/askai-secrets
        chmod 644 "$$secret_file"
        echo "MOGO deployment secrets are ready."
        echo "After services become healthy, open http://localhost:$${MOGO_PORT:-3000}/admin/setup"

  # ⚠️ 外部 PanWeiDB 模式：不再起内部 mongo / panweidb 容器。
  # 这两个服务被挪到永不被启用的 profile `never`，compose 不会创建它们的容器。
  # 应用侧也不声明对它们的 depends_on，因此无依赖残留。
  # 若仍需栈内 redis 之外的数据库实例，请勿把 redis 也挪进 `never`。
  mongo:
    profiles: [never]

  panweidb:
    profiles: [never]

  redis:
    image: ${MOGO_REDIS_IMAGE:-redis:7.4.2-alpine}
    platform: linux/amd64
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
    image: ${MOGO_WEAVIATE_IMAGE:-semitechnologies/weaviate:1.25.7}
    platform: linux/amd64
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
    image: ghcr.io/mogoai/dsh-runtime-host:__MOGO_TAG__
    platform: linux/amd64
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
    image: ghcr.io/mogoai/chat-api:__MOGO_TAG__
    platform: linux/amd64
    pull_policy: never
    restart: unless-stopped
    environment:
      OPENAI_API_KEY: ""
      # 数据后端：PanWeiDB（外部实例）
      MOGO_DATA_BACKEND: panweidb
      PANWEIDB_HOST: "__PANWEIDB_HOST__"
      PANWEIDB_PORT: "__PANWEIDB_PORT__"
      PANWEIDB_USER: "__PANWEIDB_USER__"
      PANWEIDB_PASSWORD: "__PANWEIDB_PASSWORD__"
      PANWEIDB_DB: "__PANWEIDB_DB__"
      PANWEIDB_SCHEMA: "__PANWEIDB_SCHEMA__"
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
      # chat-api 的 DSH 锁 / session 归属缓存走独立 DB（DB/1），与业务缓存（DB/0）分开
      MOGO_KERNEL_REDIS_URL: redis://redis:6379/1
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - askai-storage:/app/storage
      - knowledge-storage:/data/knowledge-documents
    depends_on:
      bootstrap:
        condition: service_completed_successfully
      document-api:
        condition: service_healthy
      dsh-runtime-host:
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
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/ready', timeout=3).read()"]

  admin-api:
    image: ghcr.io/mogoai/admin-api:__MOGO_TAG__
    platform: linux/amd64
    pull_policy: never
    restart: unless-stopped
    environment:
      ASKAI_ADMIN_APP_ENV: production
      # 数据后端：PanWeiDB（外部实例）
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
      # 数据后端：PanWeiDB（外部实例）
      MOGO_DATA_BACKEND: panweidb
      PANWEIDB_HOST: "__PANWEIDB_HOST__"
      PANWEIDB_PORT: "__PANWEIDB_PORT__"
      PANWEIDB_USER: "__PANWEIDB_USER__"
      PANWEIDB_PASSWORD: "__PANWEIDB_PASSWORD__"
      PANWEIDB_DB: "__PANWEIDB_DB__"
      PANWEIDB_SCHEMA: "__PANWEIDB_SCHEMA__"
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - knowledge-storage:/data/knowledge-documents
      - admin-static:/data/admin-static
    depends_on:
      bootstrap:
        condition: service_completed_successfully
      document-api:
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
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8100/health', timeout=3).read()"]

  document-api:
    image: ghcr.io/mogoai/document-parser:__MOGO_TAG__
    platform: linux/amd64
    pull_policy: never
    restart: unless-stopped
    command: ["api"]
    environment: &document-environment
      MOGO_DOC_PROCESSING_APP_ENV: production
      MOGO_DOC_PROCESSING_LOCAL_STORAGE_DIR: /data/knowledge-documents
      MOGO_DOC_PROCESSING_REDIS_URL: redis://redis:6379/0
      MOGO_DOC_PROCESSING_WEAVIATE_ENDPOINT: http://weaviate:8080
      MOGO_DOC_PROCESSING_WEAVIATE_COLLECTION_NAME: AskAIKnowledgeChunks
      MOGO_DOC_PROCESSING_WEAVIATE_DISTANCE_METRIC: cosine
      MOGO_DOC_PROCESSING_AZURE_EMBEDDING_ENDPOINT: ""
      MOGO_DOC_PROCESSING_AZURE_EMBEDDING_DEPLOYMENT_NAME: text_embedding
      MOGO_DOC_PROCESSING_AZURE_EMBEDDING_API_VERSION: 2025-04-01-preview
      MOGO_DOC_PROCESSING_AZURE_EMBEDDING_API_KEY: ""
      MOGO_DOC_PROCESSING_DASHSCOPE_API_KEY: ""
      # 数据后端：PanWeiDB（外部实例）
      MOGO_DATA_BACKEND: panweidb
      PANWEIDB_HOST: "__PANWEIDB_HOST__"
      PANWEIDB_PORT: "__PANWEIDB_PORT__"
      PANWEIDB_USER: "__PANWEIDB_USER__"
      PANWEIDB_PASSWORD: "__PANWEIDB_PASSWORD__"
      PANWEIDB_DB: "__PANWEIDB_DB__"
      PANWEIDB_SCHEMA: "__PANWEIDB_SCHEMA__"
    volumes:
      - deployment-secrets:/run/askai-secrets:ro
      - knowledge-storage:/data/knowledge-documents
    depends_on:
      bootstrap:
        condition: service_completed_successfully
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
    image: ghcr.io/mogoai/document-parser:__MOGO_TAG__
    platform: linux/amd64
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
      redis:
        condition: service_healthy
      weaviate:
        condition: service_healthy
    networks:
      - public
      - backend

  user-web:
    image: ghcr.io/mogoai/user-web:__MOGO_TAG__
    platform: linux/amd64
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
    image: ghcr.io/mogoai/admin-web:__MOGO_TAG__
    platform: linux/amd64
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
    image: ghcr.io/mogoai/gateway:__MOGO_TAG__
    platform: linux/amd64
    pull_policy: never
    restart: unless-stopped
    user: root
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
    name: mogo_deployment-secrets
  redis-data:
    name: mogo_redis-data
  weaviate-data:
    name: mogo_weaviate-data
  dsh-runtime-data:
    name: mogo_dsh-runtime-data
  askai-storage:
    name: mogo_askai-storage
  knowledge-storage:
    name: mogo_knowledge-storage
  admin-static:
    name: mogo_admin-static
