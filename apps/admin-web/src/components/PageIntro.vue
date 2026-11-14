<template>
  <div class="mg-page-head">
    <div class="mg-page-head__text">
      <h1 class="mg-page-title">{{ title }}</h1>
      <p v-if="description" class="mg-page-desc">{{ description }}</p>
      <div v-if="tags.length" class="mg-page-tags">
        <n-tag v-for="tag in tags" :key="tag" size="small" round :bordered="false">{{ tag }}</n-tag>
      </div>
    </div>
    <div v-if="$slots.actions" class="mg-page-actions">
      <slot name="actions" />
    </div>
  </div>
</template>

<script setup lang="ts">
import { NTag } from 'naive-ui';

/**
 * 页面头部（设计规范唯一入口）
 *
 * 所有业务页面的标题区都必须使用本组件，禁止页面内自写 h1/h2 + 副标题布局，
 * 以保证标题层级、间距、深浅主题表现一致。规范见 docs/design-system.md。
 */
withDefaults(
  defineProps<{
    title: string;
    description?: string;
    tags?: string[];
  }>(),
  {
    description: '',
    tags: () => [],
  },
);
</script>

<style scoped>
.mg-page-tags {
  display: flex;
  align-items: center;
  gap: var(--mg-space-2);
  flex-wrap: wrap;
  margin-top: var(--mg-space-1);
}
</style>
