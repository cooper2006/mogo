<script setup lang="ts">
// 位于 <n-message-provider> 内部的桥接组件：naive-ui 的 useMessage 只能由
// provider 的后代调用。App.vue 是 provider 的宿主，无法在自身 setup 顶层调用，
// 所以在这里取到 api 后注册给 App.vue 使用。
import { useMessage } from 'naive-ui'
import { registerAppMessage } from '../composables/appMessage'

registerAppMessage(useMessage())
</script>

<template>
  <span aria-hidden="true" style="display: none" />
</template>
