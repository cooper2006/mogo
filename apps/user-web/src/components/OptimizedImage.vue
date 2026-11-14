<script setup lang="ts">
// apps/user-web/src/components/OptimizedImage.vue
// 026 T037 — 图片优化组件（FR-24）
//
// WebP/AVIF 优先（<picture> 源协商）+ 原生懒加载（loading="lazy" + decoding="async"）
// + 响应式 srcset/sizes。
//
// 用法：<OptimizedImage src="/assets/images/banner.png" alt="banner" :widths="[320,640,1280]" />
// 若已有 WebP/AVIF 变体可传 webpSrc / avifSrc，否则浏览器仅按 srcset 挑尺寸不转格式。

import { computed } from 'vue'

const props = withDefaults(
  defineProps<{
    src: string
    webpSrc?: string
    avifSrc?: string
    alt: string
    widths?: number[]
    sizes?: string
    width?: number
    height?: number
    imgClass?: string
  }>(),
  { widths: () => [320, 640, 1280] },
)

function buildSrcset(base: string, widths: number[]): string {
  return widths.map((w) => `${base} ${w}w`).join(', ')
}

const imgSrcset = computed(() => buildSrcset(props.src, props.widths))
const webpSrcset = computed(() => (props.webpSrc ? buildSrcset(props.webpSrc, props.widths) : ''))
const avifSrcset = computed(() => (props.avifSrc ? buildSrcset(props.avifSrc, props.widths) : ''))
</script>

<template>
  <picture>
    <source v-if="avifSrcset" type="image/avif" :srcset="avifSrcset" :sizes="sizes" />
    <source v-if="webpSrcset" type="image/webp" :srcset="webpSrcset" :sizes="sizes" />
    <img
      :src="src"
      :srcset="imgSrcset"
      :sizes="sizes"
      :alt="alt"
      :width="width"
      :height="height"
      :class="imgClass"
      loading="lazy"
      decoding="async"
      fetchpriority="low"
    />
  </picture>
</template>