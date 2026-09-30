<template>
  <div class="health-page">
    <n-card class="health-card" :bordered="false">
      <div class="page-head">
        <div>
          <h2>{{ t('服务健康') }}</h2>
          <p>{{ t('查看平台核心依赖服务的实时状态。') }}</p>
        </div>
        <n-button secondary :loading="loading" @click="loadHealth">{{ t('刷新') }}</n-button>
      </div>

      <n-spin :show="loading">
        <n-list v-if="services.length" class="service-list">
          <n-list-item v-for="service in services" :key="service.key">
            <n-space justify="space-between" align="center" style="width: 100%">
              <span class="service-copy">
                <strong>{{ service.label }}</strong>
                <small>{{ service.message }}</small>
              </span>
              <n-space :size="8" align="center">
                <n-tag v-if="service.core" size="small" round :bordered="false">{{ t('核心服务') }}</n-tag>
                <n-tag :type="service.ok ? 'success' : 'error'" size="small" round>
                  {{ service.ok ? t('正常') : t('异常') }}
                </n-tag>
              </n-space>
            </n-space>
          </n-list-item>
        </n-list>

        <div v-else class="empty-state">{{ t('暂无服务状态') }}</div>
      </n-spin>
    </n-card>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { useMessage } from 'naive-ui';
import axios from 'axios';
import { fetchSystemHealth, type SystemHealthService } from '@/api/platform';
import { t } from '@/composables/i18n';

const message = useMessage();
const loading = ref(false);
const services = ref<SystemHealthService[]>([]);

function parseError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) return String(error.response?.data?.detail || error.message || fallback);
  return fallback;
}

async function loadHealth() {
  loading.value = true;
  try {
    services.value = await fetchSystemHealth();
  } catch (error) {
    message.error(parseError(error, t('加载失败')));
  } finally {
    loading.value = false;
  }
}

onMounted(loadHealth);
</script>

<style scoped>
.health-page {
  padding: 20px;
}

.health-card {
  border-radius: 18px;
  box-shadow: 0 18px 48px rgba(27, 55, 116, 0.08);
}

.page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 18px;
}

.page-head h2 {
  margin: 0 0 6px;
  font-size: 22px;
}

.page-head p {
  margin: 0;
  color: #64748b;
  font-size: 13px;
}

.service-copy strong,
.service-copy small {
  display: block;
}

.service-copy strong {
  color: #10204a;
  font-size: 14px;
}

.service-copy small {
  margin-top: 4px;
  color: #64748b;
  font-size: 12px;
  line-height: 1.5;
}

.empty-state {
  padding: 48px 0;
  color: #64748b;
  text-align: center;
}
</style>
