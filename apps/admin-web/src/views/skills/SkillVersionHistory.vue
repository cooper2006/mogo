<!-- 004 FR-3 version history (audit 2026-10-03).

Before this, ``GET /skills/{id}/releases`` had **zero** admin-web consumers —
a skill publish was visible to no one in the UI and the release lineage was
untraceable. This panel sits inside the skill detail modal and shows the
ordered release log (version / date / digest / release notes) pulled from the
004 endpoint.
-->
<template>
  <section class="version-history">
    <header class="version-header">
      <span>{{ t('发布历史') }}</span>
      <n-button text size="small" :loading="loading" @click="loadReleases">{{ t('刷新') }}</n-button>
    </header>
    <n-empty v-if="!loading && releases.length === 0" :description="t('暂无发布记录')" />
    <n-timeline v-else vertical>
      <n-timeline-item
        v-for="rel in releases"
        :key="rel.id"
        :title="rel.version || t('未命名版本')"
        :time="rel.createdAt"
        :dot-color="releaseDotColor(rel)"
      >
        <div class="timeline-body">
          <div v-if="rel.digest" class="digest">
            {{ t('SHA-256') }}: <code>{{ rel.digest }}</code>
          </div>
          <div v-if="rel.releaseNotes" class="notes">{{ rel.releaseNotes }}</div>
        </div>
      </n-timeline-item>
    </n-timeline>
  </section>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue';
import { NTimeline, NTimelineItem, NEmpty, NButton } from 'naive-ui';
import type { SkillRelease } from '@/api/skills';
import { fetchSkillReleases } from '@/api/skills';
import { t } from '@/composables/i18n';

const props = defineProps<{ skillId: string }>();
const releases = ref<SkillRelease[]>([]);
const loading = ref(false);

async function loadReleases() {
  loading.value = true;
  try {
    releases.value = await fetchSkillReleases(props.skillId, 20);
  } finally {
    loading.value = false;
  }
}

function releaseDotColor(rel: SkillRelease): string {
  if (!rel.version) return '#aaa';
  return '#16a34a';
}

onMounted(loadReleases);
defineExpose({ loadReleases });
</script>

<style scoped>
.version-history { margin-top: 20px; border-top: 1px solid #e4eaf4; padding-top: 16px; }
.version-header { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; font-weight: 600; color: #17233d; }
.timeline-body { display: flex; flex-direction: column; gap: 6px; }
.digest { font-size: 12px; color: #52627d; }
.digest code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; word-break: break-all; }
.notes { font-size: 13px; color: #17233d; white-space: pre-wrap; margin-top: 2px; }
</style>
