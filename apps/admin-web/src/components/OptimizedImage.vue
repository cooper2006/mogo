<script setup lang="ts">
/**
 * 026 T037 — 图片优化组件（FR-24）
 *
 * WebP/AVIF 优先（`<picture>` 源协商）+ 原生懒加载（`loading="lazy"` +
 * `decoding="async"`）+ 响应式 `srcset`/`sizes`。
 *
 * 用法：
 *   <OptimizedImage src="/assets/images/logo.png" alt="logo" :widths="[320,640,1280]" />
 *
 * 说明：若同一图片已提供 WebP/AVIF 变体，可传 `webpSrc` / `avifSrc`；
 * 未传时回退到 `src`（浏览器仅按 `srcset` 挑尺寸，不转换格式）。
 */
import { computed } from 'vue';

const props = withDefaults(
  defineProps<{
    src: string;
    /** 备选 WebP 源（可选） */
    webpSrc?: string;
    /** 备选 AVIF 源（可选） */
    avifSrc?: string;
    alt: string;
    /** 响应式候选宽度（生成 srcset） */
    widths?: number[];
    /** 当前渲染宽度描述（sizes 属性） */
    sizes?: string;
    /** 兜底宽度（无 srcset 时） */
    width?: number;
    height?: number;
    /** 图片类名透传 */
    imgClass?: string;
  }>(),
  { widths: () => [320, 640, 1280] },
);

/** 生成 srcset：`src 320w, src 640w, ...` */
function buildSrcset(base: string, widths: number[]): string {
  return widths.map((w) => `${base} ${w}w`).join(', ');
}

const imgSrcset = computed(() => buildSrcset(props.src, props.widths));
const webpSrcset = computed(() =>
  props.webpSrc ? buildSrcset(props.webpSrc, props.widths) : '',
);
const avifSrcset = computed(() =>
  props.avifSrc ? buildSrcset(props.avifSrc, props.widths) : '',
);
</script>

<template>
  <picture>
    <source
      v-if="avifSrcset"
      type="image/avif"
      :srcset="avifSrcset"
      :sizes="sizes"
    />
    <source
      v-if="webpSrcset"
      type="image/webp"
      :srcset="webpSrcset"
      :sizes="sizes"
    />
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