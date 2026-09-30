<template>
  <div class="setup-page">
    <div class="setup-panel">
      <header class="setup-copy">
        <div class="brand-mark">
          <img :src="movoLogo" alt="MOVO" />
        </div>
        <div>
          <div class="eyebrow">MOGO PLATFORM SETUP</div>
          <h1>{{ setupStore.completed ? t('系统已准备就绪') : t('初始化平台服务') }}</h1>
          <p>{{ heroDescription }}</p>
        </div>
      </header>

      <SetupProgressSteps :current="currentStep" />

      <n-card class="setup-card" :bordered="false">
        <SetupCompleteStep
          v-if="setupStore.completed"
          :platform-admin-username="createdUsername"
          @login="router.push('/login')"
          @create-tenant="router.push('/platform/tenants')"
        />

        <template v-else>
          <template v-if="currentStep === 1">
            <SetupDeploymentStatus
              :ready="setupStore.ready"
              :loading="setupStore.loading"
              :services="setupStore.services"
              @refresh="refreshStatus"
            />
            <n-alert v-if="!setupStore.ready" type="warning" :show-icon="true" class="readiness-alert">
              {{ t('核心服务（MongoDB）尚未就绪，无法继续；其余服务可稍后恢复。') }}
            </n-alert>
            <n-alert v-else-if="setupStore.platformAdminMissing" type="info" :show-icon="true" class="readiness-alert">
              {{ t('尚未检测到平台超级管理员。请在此创建，或配置环境变量 ASKAI_ADMIN_PLATFORM_ADMIN_PASSWORD。') }}
            </n-alert>
            <div class="deployment-actions">
              <n-button block type="primary" size="large" :disabled="!setupStore.ready" @click="currentStep = 2">
                {{ t('下一步：创建平台超管') }}
              </n-button>
            </div>
          </template>

          <SetupPlatformAdminStep
            v-else-if="currentStep === 2"
            v-model="platformAdminForm"
            :submitting="submitting"
            @submit="submitPlatformAdmin"
          />
        </template>
      </n-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, onMounted, reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useMessage } from 'naive-ui';
import axios from 'axios';
import movoLogo from '@/assets/images/movo-logo.png';
import { createPlatformAdmin } from '@/api/setup';
import SetupCompleteStep from '@/components/setup/SetupCompleteStep.vue';
import SetupDeploymentStatus from '@/components/setup/SetupDeploymentStatus.vue';
import SetupPlatformAdminStep from '@/components/setup/SetupPlatformAdminStep.vue';
import SetupProgressSteps from '@/components/setup/SetupProgressSteps.vue';
import type { SetupPlatformAdminForm } from '@/components/setup/types';
import { t } from '@/composables/i18n';
import { useSetupStore } from '@/stores/setup';

const router = useRouter();
const message = useMessage();
const setupStore = useSetupStore();
const currentStep = ref(1);
const submitting = ref(false);
const createdUsername = ref('');

const platformAdminForm = reactive<SetupPlatformAdminForm>({
  username: 'platform',
  password: '',
  displayName: t('平台管理员'),
});

const heroDescription = computed(() => setupStore.completed
  ? (setupStore.platformAdminMissing
    ? t('平台已就绪，但尚未检测到可用的平台超级管理员。请配置环境变量后重启服务。')
    : t('平台已准备就绪。请登录平台控制台创建第一个租户。'))
  : t('引导流程只会创建平台超级管理员，不会创建任何租户。'));

function parseError(error: unknown, fallback: string) {
  if (axios.isAxiosError(error)) return String(error.response?.data?.detail || error.message || fallback);
  return fallback;
}

function validatePlatformAdmin() {
  if (platformAdminForm.username.trim().length < 3) return t('平台管理员账号至少 3 位');
  if (platformAdminForm.password.trim().length < 10) return t('平台管理员密码至少 10 位');
  if (platformAdminForm.displayName.trim().length < 2) return t('请填写平台管理员显示名');
  return '';
}

async function submitPlatformAdmin() {
  const error = validatePlatformAdmin();
  if (error) return void message.warning(error);
  submitting.value = true;
  try {
    await createPlatformAdmin({
      username: platformAdminForm.username.trim(),
      password: platformAdminForm.password,
      displayName: platformAdminForm.displayName.trim(),
    });
    createdUsername.value = platformAdminForm.username.trim();
    await setupStore.ensureStatus(true);
    currentStep.value = 3;
    message.success(t('平台超级管理员已创建'));
  } catch (error) {
    message.error(parseError(error, t('创建平台超级管理员失败')));
  } finally {
    submitting.value = false;
  }
}

async function refreshStatus() {
  try { await setupStore.ensureStatus(true); }
  catch { message.error(t('部署状态刷新失败')); }
}

onMounted(async () => {
  try {
    await setupStore.ensureStatus();
    if (setupStore.completed) {
      // Decision 12: /setup degrades to a shortcut entry once the platform admin
      // exists; fall back to step 2 so a missing admin can still be created.
      currentStep.value = setupStore.platformAdminMissing ? 2 : 3;
    }
  } catch (error) {
    console.error(error);
    message.error(t('无法获取初始化状态，请检查 admin-api 是否已启动'));
  }
});
</script>

<style scoped>
.setup-page {
  min-height: 100vh;
  padding: 36px 20px 56px;
  background:
    radial-gradient(circle at 12% 4%, rgba(99, 142, 255, .15), transparent 30%),
    radial-gradient(circle at 88% 88%, rgba(69, 112, 229, .1), transparent 28%),
    #f1f5ff;
}

.setup-panel { display: grid; width: min(820px, 100%); margin: 0 auto; gap: 16px; }
.setup-copy { display: flex; align-items: center; gap: 20px; padding: 22px 26px; border-radius: 22px; background: linear-gradient(135deg, #1d3e91, #315ec8); color: #fff; box-shadow: 0 18px 48px rgba(35, 73, 160, .2); }
.brand-mark { display: grid; width: 64px; height: 58px; flex: 0 0 64px; place-items: center; border: 1px solid rgba(255,255,255,.22); border-radius: 17px; background: rgba(255,255,255,.12); }
.brand-mark img { display: block; width: 48px; height: 40px; object-fit: contain; }
.eyebrow { font-size: 11px; font-weight: 700; letter-spacing: .18em; color: rgba(255,255,255,.72); }
.setup-copy h1 { margin: 5px 0 4px; font-size: clamp(26px, 4vw, 34px); line-height: 1.2; }
.setup-copy p { max-width: 650px; margin: 0; color: rgba(255,255,255,.82); font-size: 14px; line-height: 1.6; }
.setup-card { border-radius: 22px; box-shadow: 0 24px 70px rgba(27, 55, 116, .12); }
.readiness-alert { margin-bottom: 18px; }
.deployment-actions { margin-top: 4px; }

@media (max-width: 600px) {
  .setup-page { padding: 18px 12px 32px; }
  .setup-copy { align-items: flex-start; padding: 20px; border-radius: 18px; }
  .brand-mark { width: 48px; height: 44px; flex-basis: 48px; border-radius: 13px; }
  .brand-mark img { width: 38px; height: 32px; }
  .setup-copy h1 { font-size: 25px; }
}
</style>
