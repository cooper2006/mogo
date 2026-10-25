// 026 T048 — k6 冒烟测试（FR-31，作为 locust 的补充）
//
// 用法：
//   TARGET_HOST=http://localhost:8000 \
//   K6_VUS=10 K6_DURATION=30s k6 run benchmarks/k6/smoke.js
//
// 覆盖最小健康面：根路径 / 与就绪端点 /ready 可达，且不返回 5xx。
// 并发级别通过 K6_VUS 控制（1/10/50/100），默认 10。

import http from 'k6/http';
import { check, sleep } from 'k6';

const TARGET_HOST = __ENV.TARGET_HOST || 'http://localhost:8000';

export const options = {
  vus: Number(__ENV.K6_VUS || 10),
  duration: __ENV.K6_DURATION || '30s',
  thresholds: {
    http_req_failed: ['rate<0.01'],
    http_req_duration: ['p(95)<2000'],
  },
};

export default function () {
  const root = http.get(`${TARGET_HOST}/`);
  check(root, {
    'root reachable': (r) => r.status < 500,
  });

  // 就绪端点：依赖可达时 200，依赖不可达 503（均 < 500 视为可观测）
  const ready = http.get(`${TARGET_HOST}/ready`);
  check(ready, {
    'ready reachable': (h) => h.status < 500,
    'ready json': (h) => h.headers['content-type'].includes('application/json'),
  });

  sleep(1);
}