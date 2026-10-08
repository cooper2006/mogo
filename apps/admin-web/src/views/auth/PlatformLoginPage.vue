<template>
  <div class="login-page">
    <div class="login-panel">
      <div class="login-copy">
        <img class="login-logo" :src="movoLogo" alt="MOVO" />
        <h1>{{ t('平台控制台') }}</h1>
        <p>{{ t('仅平台超级管理员可访问，用于管理各企业租户的生命周期。') }}</p>
      </div>

      <n-card class="login-card" :bordered="false">
        <n-form label-placement="top" @submit.prevent="handleLogin">
          <n-form-item :label="t('管理员账号')">
            <n-input v-model:value="form.username" :placeholder="t('请输入账号')" @keydown.enter.prevent="handleLogin" />
          </n-form-item>
          <n-form-item :label="t('密码')">
            <n-input
              v-model:value="form.password"
              type="password"
              show-password-on="click"
              :placeholder="t('输入密码')"
              @keydown.enter.prevent="handleLogin"
            />
          </n-form-item>
          <n-space vertical :size="14">
            <n-button block type="primary" size="large" :loading="loading" attr-type="submit">
              {{ t('平台管理员登录') }}
            </n-button>
            <n-button block quaternary size="small" @click="router.push('/login')">
              {{ t('返回') }}
            </n-button>
          </n-space>
        </n-form>
      </n-card>
    </div>
  </div>
</template>

<script setup lang="ts">
import { reactive, ref } from 'vue';
import { useRouter } from 'vue-router';
import { useMessage } from 'naive-ui';
import { login } from '@/api/auth';
import { PLATFORM_MAIN_ID, useAuthStore } from '@/stores/auth';
import { t } from '@/composables/i18n';
import movoLogo from '@/assets/images/movo-logo.png';

const router = useRouter();
const message = useMessage();
const authStore = useAuthStore();
const loading = ref(false);
const form = reactive({
  username: '',
  password: '',
});

async function handleLogin() {
  loading.value = true;
  try {
    const result = await login({ ...form, tenantId: PLATFORM_MAIN_ID });
    if ('requiresTenantSelection' in result && result.requiresTenantSelection) {
      message.error(t('平台管理员登录失败'));
      return;
    }
    authStore.login(result);
    message.success(t('登录成功'));
    router.push('/platform/tenants');
  } catch (error) {
    console.error(error);
    message.error(t('登录失败，请检查账号密码或 admin-api 是否已启动'));
  } finally {
    loading.value = false;
  }
}
</script>

<style scoped>
.login-page {
  min-height: 100vh;
  display: grid;
  place-items: center;
  padding: 32px;
}

.login-panel {
  display: grid;
  grid-template-columns: 1.1fr 420px;
  gap: 28px;
  width: min(1100px, 100%);
}

.login-copy {
  padding: 38px;
  border-radius: 28px;
  background:
    radial-gradient(circle at top left, rgba(112, 155, 255, 0.34), transparent 34%),
    linear-gradient(135deg, #18306f, #2449a9 48%, #0d1d4f);
  color: #effbf8;
  box-shadow: 0 30px 80px rgba(25, 49, 116, 0.24);
}

.login-logo {
  display: block;
  width: 112px;
  height: 90px;
  object-fit: contain;
  filter: drop-shadow(0 8px 18px rgba(0, 0, 0, 0.16));
}

.login-copy h1 {
  margin: 16px 0 14px;
  font-size: 42px;
  line-height: 1.08;
}

.login-copy p {
  margin: 0;
  font-size: 16px;
  line-height: 1.7;
  color: rgba(239, 251, 248, 0.82);
}

.login-card {
  border-radius: 28px;
  box-shadow: 0 30px 80px rgba(23, 46, 43, 0.12);
}

@media (max-width: 980px) {
  .login-panel {
    grid-template-columns: 1fr;
  }

  .login-copy h1 {
    font-size: 34px;
  }
}
</style>
