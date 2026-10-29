<script setup lang="ts">
import { computed } from 'vue';
import { t } from '@/composables/i18n';

const props = defineProps<{
  current: number;
}>();

const steps = computed(() => [
  t('部署检测'),
  t('创建平台超管'),
  t('完成'),
]);
</script>

<template>
  <nav class="progress-card" :aria-label="t('初始化进度')">
    <ol>
      <li
        v-for="(step, index) in steps"
        :key="step"
        :class="{ active: current === index + 1, complete: current > index + 1 }"
        :aria-current="current === index + 1 ? 'step' : undefined"
      >
        <span class="step-marker">
          <svg v-if="current > index + 1" viewBox="0 0 24 24" aria-hidden="true">
            <path d="m5 12 4 4L19 6" />
          </svg>
          <span v-else>{{ index + 1 }}</span>
        </span>
        <span class="step-label">{{ step }}</span>
      </li>
    </ol>
  </nav>
</template>

<style scoped>
.progress-card {
  padding: 16px 24px;
  border: 1px solid var(--mg-border);
  border-radius: 18px;
  background: color-mix(in srgb, var(--mg-bg-surface) 92%, transparent);
  box-shadow: 0 12px 36px rgba(27, 55, 116, .08);
}

ol {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  margin: 0;
  padding: 0;
  list-style: none;
}

li {
  position: relative;
  display: flex;
  align-items: center;
  gap: 10px;
  color: var(--mg-text-3);
  font-size: 12px;
  font-weight: 600;
}

li:not(:last-child)::after {
  position: absolute;
  z-index: 0;
  top: 50%;
  right: 12px;
  left: 48px;
  height: 1px;
  background: #dfe7f5;
  content: '';
}

.step-marker {
  position: relative;
  z-index: 1;
  display: grid;
  width: 30px;
  height: 30px;
  flex: 0 0 30px;
  place-items: center;
  border: 1px solid var(--mg-border);
  border-radius: 50%;
  background: var(--mg-bg-surface);
}

.step-marker svg {
  width: 16px;
  fill: none;
  stroke: currentColor;
  stroke-linecap: round;
  stroke-linejoin: round;
  stroke-width: 2.4;
}

.step-label {
  position: relative;
  z-index: 1;
  padding-right: 10px;
  background: var(--mg-bg-surface);
  white-space: nowrap;
}

li.active { color: var(--mg-brand); }
li.active .step-marker { border-color: var(--mg-brand); background: var(--mg-brand); color: #fff; box-shadow: 0 0 0 4px #e8efff; }
li.complete { color: #248466; }
li.complete .step-marker { border-color: #b7ead8; background: #e8f8f2; color: var(--mg-success-text); }
li.complete::after { background: #b7ead8; }

@media (max-width: 540px) {
  .progress-card { padding: 14px 16px; }
  li { align-items: flex-start; gap: 7px; font-size: 12px; }
  li:not(:last-child)::after { right: 8px; left: 38px; }
  .step-marker { width: 26px; height: 26px; flex-basis: 26px; }
  .step-label { display: none; }
}
</style>
