<!-- 033-canary-rollout US4: Skill 灰度配置页（FR-013）。

承载：创建/查看灰度（租户 + 比例阶梯 + 影子开关）、当前档位与推进历史、
影子统计、手动推进与一键回滚。调用 admin-api `POST/GET /api/skills/canary/*`。
-->
<template>
  <section class="canary-config">
    <header class="page-header">
      <h1>{{ t('灰度发布') }}</h1>
      <div class="header-actions">
        <n-button secondary :loading="loading" @click="load">{{ t('刷新') }}</n-button>
        <n-button v-if="rollout" type="warning" :loading="advancing" @click="onAdvance">
          {{ t('手动推进') }}
        </n-button>
        <n-button
          v-if="rollout"
          type="error"
          secondary
          :loading="rollingBack"
          @click="onRollback"
        >
          {{ t('一键回滚') }}
        </n-button>
      </div>
    </header>

    <n-spin :show="loading">
      <n-alert v-if="notice" type="warning" closable class="notice" @close="notice = ''">
        {{ notice }}
      </n-alert>

      <!-- 尚未创建灰度：显示创建表单 -->
      <n-card v-if="!rollout && !loading" :title="t('创建灰度')" class="card">
        <n-form label-placement="left" label-width="120">
          <n-form-item :label="t('候选版本号')">
            <n-input-number v-model:value="form.version" :min="1" :step="1" />
          </n-form-item>
          <n-form-item :label="t('稳定版本号')">
            <n-input-number v-model:value="form.stableVersion" :min="0" :step="1" />
          </n-form-item>
          <n-form-item :label="t('目标租户(逗号分隔)')">
            <n-input v-model:value="form.targetTenants" :placeholder="t('留空 = 全部租户')" />
          </n-form-item>
          <n-form-item :label="t('初始流量比例')">
            <n-input-number
              v-model:value="form.trafficRatio"
              :min="0.01"
              :max="1"
              :step="0.01"
              :precision="2"
            />
          </n-form-item>
          <n-form-item :label="t('阶梯档位(%)')">
            <div class="ladder-editor">
              <n-input-number
                v-for="(step, index) in form.ladder"
                :key="index"
                v-model:value="step.value"
                :min="1"
                :max="100"
                :step="1"
                size="small"
              />
            </div>
          </n-form-item>
          <n-form-item :label="t('开启影子模式')">
            <n-switch v-model:value="form.shadowEnabled" />
          </n-form-item>
          <n-button type="primary" :loading="creating" @click="onCreate">
            {{ t('开始灰度') }}
          </n-button>
        </n-form>
      </n-card>

      <!-- 灰度进行中：状态 + 阶梯 + 影子统计 -->
      <template v-if="rollout">
        <n-card class="card" :title="t('当前状态')">
          <div class="stat-grid">
            <n-statistic :label="t('状态')" :value="rollout.state" />
            <n-statistic :label="t('流量比例')" :value="Math.round(rollout.traffic_ratio * 100) + '%'" />
            <n-statistic :label="t('当前档位')" :value="rollout.current_step" />
            <n-statistic :label="t('错误率')" :value="(rollout.error_rate * 100).toFixed(2) + '%'" />
            <n-statistic :label="t('影子')" :value="rollout.shadow_enabled ? t('已开启') : t('已关闭')" />
          </div>
          <div class="state-actions">
            <n-switch
              :value="rollout.shadow_enabled"
              size="small"
              :loading="togglingShadow"
              @update:value="onToggleShadow"
            />
            <span class="state-action-label">{{ t('影子模式') }}</span>
          </div>
        </n-card>

        <n-card class="card" :title="t('推进历史')">
          <n-empty v-if="!rollout.ladder_history.length" :description="t('暂无推进记录')" />
          <n-timeline v-else>
            <n-timeline-item
              v-for="(item, index) in rollout.ladder_history"
              :key="index"
              :title="(item.ratio * 100).toFixed(0) + '%'"
              :time="item.entered_at || ''"
              :type="item.promoted_at ? 'success' : 'default'"
            >
              <div class="timeline-body">
                {{ t('进入时间') }}: {{ item.entered_at || '—' }}
                <span v-if="item.promoted_at"> · {{ t('推进') }}: {{ item.promoted_at }}</span>
              </div>
            </n-timeline-item>
          </n-timeline>
        </n-card>

        <n-card class="card" :title="t('影子统计')">
          <div class="stat-grid">
            <n-statistic :label="t('影子调用数')" :value="rollout.shadow_stats?.total ?? 0" />
            <n-statistic
              :label="t('成功率')"
              :value="((rollout.shadow_stats?.success_rate ?? 0) * 100).toFixed(1) + '%'"
            />
            <n-statistic
              :label="t('平均耗时(ms)')"
              :value="rollout.shadow_stats?.avg_duration_ms?.toFixed(0) ?? '0'"
            />
          </div>
        </n-card>
      </template>
    </n-spin>
  </section>
</template>

<script setup lang="ts">
import { onMounted, reactive, ref } from 'vue';
import { useRoute } from 'vue-router';
import {
  NAlert, NButton, NCard, NEmpty, NForm, NFormItem, NInput, NInputNumber,
  NSpin, NStatistic, NSwitch, NTimeline, NTimelineItem, useMessage,
} from 'naive-ui';
import { t } from '@/composables/i18n';
import {
  advanceCanary, createCanaryRollout, fetchCanaryRollout,
  rollbackCanary, toggleCanaryShadow,
  type CanaryEvaluateDto,
} from '@/api/skillCanary';

const route = useRoute();
const message = useMessage();
const skillId = String(route.params.id || '');

const loading = ref(false);
const creating = ref(false);
const advancing = ref(false);
const rollingBack = ref(false);
const togglingShadow = ref(false);
const notice = ref('');
const rollout = ref<CanaryEvaluateDto | null>(null);

const form = reactive({
  version: 1,
  stableVersion: 0,
  targetTenants: '',
  trafficRatio: 0.01,
  ladder: [{ value: 1 }, { value: 10 }, { value: 50 }, { value: 100 }],
  shadowEnabled: false,
});

async function load() {
  loading.value = true;
  try {
    rollout.value = await fetchCanaryRollout(skillId);
    notice.value = '';
  } catch {
    // 404 → 尚未创建灰度，展示创建表单。
    rollout.value = null;
  } finally {
    loading.value = false;
  }
}

async function onCreate() {
  if (!skillId) return;
  creating.value = true;
  try {
    await createCanaryRollout({
      skill_id: skillId,
      version: form.version,
      stable_version: form.stableVersion,
      target_tenants: form.targetTenants
        ? form.targetTenants.split(',').map((item) => item.trim()).filter(Boolean)
        : [],
      traffic_ratio: form.trafficRatio,
      ladder: form.ladder.map((item) => ({ ratio: (item.value ?? 1) / 100 })),
      shadow_enabled: form.shadowEnabled,
    });
    message.success(t('灰度已创建'));
    await load();
  } catch (error: any) {
    notice.value = t('创建失败') + ': ' + String(error?.response?.data?.detail || error?.message || error);
  } finally {
    creating.value = false;
  }
}

async function onAdvance() {
  advancing.value = true;
  try {
    const result = await advanceCanary(skillId);
    message.success(
      result.promoted
        ? t('已推进到 100%，灰度完成')
        : result.advanced
          ? t('已推进到档位') + ' ' + Math.round(result.traffic_ratio * 100) + '%'
          : t('暂不满足推进条件') + '：' + (result.reason || ''),
    );
    await load();
  } catch (error: any) {
    notice.value = t('推进失败') + ': ' + String(error?.response?.data?.detail || error?.message);
  } finally {
    advancing.value = false;
  }
}

async function onToggleShadow(value: boolean) {
  togglingShadow.value = true;
  try {
    await toggleCanaryShadow(skillId, value);
    message.success(value ? t('影子模式已开启') : t('影子模式已关闭'));
    await load();
  } catch (error: any) {
    notice.value = t('操作失败') + ': ' + String(error?.response?.data?.detail || error?.message);
  } finally {
    togglingShadow.value = false;
  }
}

async function onRollback() {
  rollingBack.value = true;
  try {
    await rollbackCanary(skillId);
    message.success(t('已回滚到稳定版本'));
    await load();
  } catch (error: any) {
    notice.value = t('回滚失败') + ': ' + String(error?.response?.data?.detail || error?.message);
  } finally {
    rollingBack.value = false;
  }
}

onMounted(load);
</script>

<style scoped>
.canary-config { display: flex; flex-direction: column; gap: 16px; }
.page-header { display: flex; align-items: center; justify-content: space-between; }
.page-header h1 { font-size: 18px; margin: 0; }
.header-actions { display: flex; gap: 8px; }
.card { margin-bottom: 0; }
.notice { margin-bottom: 12px; }
.stat-grid { display: flex; flex-wrap: wrap; gap: 24px; }
.ladder-editor { display: flex; flex-wrap: wrap; gap: 8px; align-items: center; }
.ladder-editor::after { content: '%'; }
.state-actions { margin-top: 12px; display: flex; align-items: center; gap: 8px; }
.state-action-label { color: var(--mg-text-3); }
.timeline-body { color: var(--mg-text-2); font-size: 13px; }
</style>