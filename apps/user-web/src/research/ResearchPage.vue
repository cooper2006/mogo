<script setup lang="ts">
/**
 * /research 竞品深度调研页（子路由接入墨攻平台，产品经理拍板的部署形态）。
 * 输入竞品名 → 一次交互 → 综合判断 + 四章分栏渲染；数据层见 researchService.ts（mock 先行）。
 */
import { computed, ref } from 'vue'
import {
    CHAPTER_ORDER,
    CHAPTER_TITLES,
    generateResearch,
    researchSources,
    type ResearchReport
} from './researchService'

const subject = ref('')
const loading = ref(false)
const error = ref('')
const report = ref<ResearchReport | null>(null)

const canSubmit = computed(() => subject.value.trim().length > 0 && !loading.value)

async function submit() {
    const name = subject.value.trim()
    if (!name || loading.value) return
    loading.value = true
    error.value = ''
    report.value = null
    try {
        report.value = await generateResearch(name)
    } catch (e) {
        error.value = e instanceof Error ? e.message : String(e)
    } finally {
        loading.value = false
    }
}
</script>

<template>
    <div class="research-page">
        <header class="rp-header">
            <h1 class="rp-title">竞品深度调研</h1>
            <p class="rp-subtitle">输入竞品名，一次交互得到 analyst-grade 调研报告：市场情报 · 功能对比 · 财务估值 · 社媒舆情 + 综合判断</p>
            <form class="rp-form" @submit.prevent="submit">
                <input
                    v-model="subject"
                    class="rp-input"
                    placeholder="例如：钉钉"
                    :disabled="loading"
                    autocomplete="off"
                />
                <button class="rp-btn" type="submit" :disabled="!canSubmit">
                    {{ loading ? '调研生成中…' : '开始调研' }}
                </button>
            </form>
            <p v-if="error" class="rp-error">{{ error }}</p>
            <p v-if="report?.mock" class="rp-mock-badge">mock 数据（001 端到端验收通过后切换真实数据源）</p>
        </header>

        <template v-if="report">
            <section class="rp-judgment">
                <h2 class="rp-judgment-title">综合判断</h2>
                <p class="rp-judgment-verdict">{{ report.judgment.verdict }}</p>
                <ul class="rp-judgment-points">
                    <li v-for="(p, i) in report.judgment.points" :key="i">{{ p }}</li>
                </ul>
            </section>

            <section class="rp-chapters">
                <article
                    v-for="key in CHAPTER_ORDER"
                    :key="key"
                    class="rp-chapter"
                >
                    <h3 class="rp-chapter-title">{{ CHAPTER_TITLES[key] }}</h3>
                    <div
                        v-for="(s, i) in report.chapters.find((c) => c.key === key)?.sections ?? []"
                        :key="i"
                        class="rp-section"
                    >
                        <h4 class="rp-section-heading">{{ s.heading }}</h4>
                        <p class="rp-section-body">{{ s.body }}</p>
                    </div>
                    <footer class="rp-sources">
                        数据源：{{ researchSources[key].join(' · ') }}
                    </footer>
                </article>
            </section>

            <footer class="rp-meta">
                生成时间：{{ new Date(report.generatedAt).toLocaleString('zh-CN') }}
                <span v-if="report.mock">（mock）</span>
            </footer>
        </template>

        <section v-else-if="!loading" class="rp-empty">
            输入竞品名开始；报告将以四章分栏呈现，综合判断置顶。
        </section>
    </div>
</template>

<style scoped>
.research-page {
    max-width: 1280px;
    margin: 0 auto;
    padding: 32px 24px 64px;
    font-family: var(--font-sans, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif);
    color: var(--text-1, #1f2329);
}
.rp-title { font-size: 28px; font-weight: 700; margin: 0 0 8px; }
.rp-subtitle { color: var(--text-3, #646a73); margin: 0 0 20px; font-size: 14px; }
.rp-form { display: flex; gap: 12px; }
.rp-input {
    flex: 1; max-width: 480px; padding: 10px 14px; font-size: 15px;
    border: 1px solid var(--line-3, #d0d3d6); border-radius: 8px;
    background: var(--bg-2, #fff); color: inherit; outline: none;
}
.rp-input:focus { border-color: var(--brand-6, #3370ff); }
.rp-btn {
    padding: 10px 24px; font-size: 15px; font-weight: 600; color: #fff;
    background: var(--brand-6, #3370ff); border: none; border-radius: 8px; cursor: pointer;
}
.rp-btn:disabled { opacity: 0.55; cursor: not-allowed; }
.rp-error { color: #d83931; font-size: 13px; margin-top: 8px; }
.rp-mock-badge {
    display: inline-block; margin-top: 8px; padding: 2px 10px; font-size: 12px;
    background: #fff7e8; color: #ad6800; border: 1px solid #ffd591; border-radius: 999px;
}
.rp-judgment {
    margin-top: 28px; padding: 20px 24px; border-radius: 12px;
    background: var(--bg-4, #f2f3f5); border-left: 4px solid var(--brand-6, #3370ff);
}
.rp-judgment-title { margin: 0 0 8px; font-size: 18px; font-weight: 700; }
.rp-judgment-verdict { margin: 0 0 12px; font-size: 15px; line-height: 1.7; }
.rp-judgment-points { margin: 0; padding-left: 20px; font-size: 14px; line-height: 1.9; color: var(--text-2, #4e5969); }
.rp-chapters {
    display: grid; grid-template-columns: repeat(4, 1fr); gap: 16px; margin-top: 24px;
}
@media (max-width: 1100px) { .rp-chapters { grid-template-columns: repeat(2, 1fr); } }
@media (max-width: 640px) { .rp-chapters { grid-template-columns: 1fr; } }
.rp-chapter {
    padding: 16px; border: 1px solid var(--line-3, #d0d3d6); border-radius: 12px;
    background: var(--bg-2, #fff); display: flex; flex-direction: column;
}
.rp-chapter-title { margin: 0 0 12px; font-size: 15px; font-weight: 700; color: var(--brand-6, #3370ff); }
.rp-section { margin-bottom: 12px; }
.rp-section-heading { margin: 0 0 4px; font-size: 13px; font-weight: 600; }
.rp-section-body { margin: 0; font-size: 13px; line-height: 1.7; color: var(--text-2, #4e5969); }
.rp-sources { margin-top: auto; padding-top: 10px; border-top: 1px dashed var(--line-3, #d0d3d6); font-size: 11px; color: var(--text-3, #8f959e); }
.rp-meta { margin-top: 24px; font-size: 12px; color: var(--text-3, #8f959e); }
.rp-empty { margin-top: 48px; text-align: center; color: var(--text-3, #8f959e); font-size: 14px; }
</style>
