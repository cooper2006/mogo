<script setup lang="ts">
/**
 * 055 菜单管理 —— admin-web 侧边栏展示配置的唯一管理入口。
 *
 * 左侧树由静态 appRoutes 派生（menuCatalog），本页只编辑「展示覆盖层」：
 * 显隐、顺序、中英名称、图标。隐藏路由 / 旧路径 redirect 只在下方只读区展示，
 * 不参与菜单树编辑，避免造出没有组件的菜单项。
 */
import { computed, onMounted, ref } from 'vue';
import { onBeforeRouteLeave } from 'vue-router';
import {
  NAlert, NButton, NCard, NDataTable, NEmpty, NInput, NModal, NSelect,
  NSpace, NSwitch, NTag, useMessage,
} from 'naive-ui';
import PageIntro from '@/components/PageIntro.vue';
import { t } from '@/composables/i18n';
import {
  ICON_OPTIONS, menuCatalog, type MenuNodeDef,
} from '@/composables/menuCatalog';
import type { MenuNodeOverride } from '@/api/menu-settings';
import { useAuthStore } from '@/stores/auth';
import { useMenuConfigStore } from '@/stores/menuConfig';

interface EditableRow {
  def: MenuNodeDef;
  visible: boolean;
  labelZh: string;
  labelEn: string;
  iconKey: string | null;
  order: number | null;
  locked: boolean;
}

interface DisplayRow {
  row: EditableRow;
  level: 0 | 1;
  /** 分组本身没命中筛选，仅作为其下命中项的上下文标题。 */
  contextOnly?: boolean;
}

interface DiffLine {
  key: string;
  field: string;
  from: string;
  to: string;
}

const message = useMessage();
const authStore = useAuthStore();
const menuStore = useMenuConfigStore();

const rows = ref<EditableRow[]>([]);
const savedSnapshot = ref('[]');
const search = ref('');
const onlyModified = ref(false);
const showDiff = ref(false);
const showReadonly = ref(false);
const ready = ref(false);

const tenantKey = computed(() => authStore.profile?.tenantId || '');

function effectiveOrder(row: EditableRow): number {
  return row.order ?? row.def.staticOrder;
}

function isModified(row: EditableRow): boolean {
  return (
    !row.visible ||
    Boolean(row.labelZh.trim()) ||
    Boolean(row.labelEn.trim()) ||
    (row.iconKey !== null && row.iconKey !== row.def.iconKey) ||
    row.order !== null
  );
}

function currentNodes(): MenuNodeOverride[] {
  return rows.value.filter(isModified).map((row) => ({
    key: row.def.key,
    parentKey: row.def.parentKey,
    label:
      row.labelZh.trim() || row.labelEn.trim()
        ? {
            ...(row.labelZh.trim() ? { 'zh-CN': row.labelZh.trim().slice(0, 80) } : {}),
            ...(row.labelEn.trim() ? { 'en-US': row.labelEn.trim().slice(0, 80) } : {}),
          }
        : null,
    iconKey: row.iconKey !== row.def.iconKey ? row.iconKey : null,
    visible: row.visible ? null : false,
    order: row.order,
    locked: row.locked || undefined,
  }));
}

const dirty = computed(() => JSON.stringify(currentNodes()) !== savedSnapshot.value);
const modifiedCount = computed(() => rows.value.filter(isModified).length);

function reorderRows() {
  const byOrder = (a: EditableRow, b: EditableRow) =>
    effectiveOrder(a) - effectiveOrder(b) || a.def.staticOrder - b.def.staticOrder;
  const roots = rows.value.filter((row) => row.def.parentKey === null).sort(byOrder);
  const ordered: EditableRow[] = [];
  for (const root of roots) {
    ordered.push(root);
    if (root.def.isGroup) {
      ordered.push(
        ...rows.value.filter((row) => row.def.parentKey === root.def.key).sort(byOrder),
      );
    }
  }
  rows.value = ordered;
}

function initRows() {
  const overrides = menuStore.overrides;
  rows.value = menuCatalog.nodes.map((def) => {
    const override = overrides.get(def.key);
    return {
      def,
      visible: def.locked ? true : override?.visible !== false,
      labelZh: override?.label?.['zh-CN'] || '',
      labelEn: override?.label?.['en-US'] || '',
      iconKey: override?.iconKey ?? null,
      order: override?.order ?? null,
      locked: def.locked,
    };
  });
  reorderRows();
  savedSnapshot.value = JSON.stringify(currentNodes());
  ready.value = true;
}

function displayTitle(row: EditableRow): string {
  // 侧边栏走 t(title)，管理页必须一致：有些 title 本身是 i18n key（如 dshPlugins.title）。
  return row.labelZh.trim() || t(row.def.title);
}

function matches(row: EditableRow): boolean {
  const query = search.value.trim().toLowerCase();
  if (onlyModified.value && !isModified(row)) return false;
  if (!query) return true;
  return `${row.def.key} ${t(row.def.title)} ${row.labelZh} ${row.labelEn}`
    .toLowerCase()
    .includes(query);
}

const displayRows = computed<DisplayRow[]>(() => {
  const out: DisplayRow[] = [];
  let groupIndex = -1;
  for (const row of rows.value) {
    if (row.def.parentKey === null) {
      if (!row.def.isGroup) {
        if (matches(row)) out.push({ row, level: 0 });
        groupIndex = -1;
        continue;
      }
      const hit = matches(row);
      out.push({ row, level: 0, contextOnly: !hit });
      groupIndex = out.length - 1;
      continue;
    }
    if (groupIndex >= 0 && matches(row)) {
      out.push({ row, level: 1 });
      out[groupIndex].contextOnly = false;
    }
  }
  return out.filter((item) => !item.contextOnly && (item.level === 1 || matches(item.row)));
});

function canMove(row: EditableRow, delta: number): boolean {
  const siblings = rows.value.filter((item) => item.def.parentKey === row.def.parentKey);
  const index = siblings.indexOf(row);
  return index >= 0 && index + delta >= 0 && index + delta < siblings.length;
}

function move(row: EditableRow, delta: number) {
  if (!canMove(row, delta)) return;
  const siblings = rows.value.filter((item) => item.def.parentKey === row.def.parentKey);
  const other = siblings[siblings.indexOf(row) + delta];
  const a = rows.value.indexOf(row);
  const b = rows.value.indexOf(other);
  [rows.value[a], rows.value[b]] = [rows.value[b], rows.value[a]];
  // 顺序是组级属性：同组全部写入显式 order，避免保存后顺序回弹。
  rows.value
    .filter((item) => item.def.parentKey === row.def.parentKey)
    .forEach((item, index) => {
      item.order = index;
    });
  reorderRows();
}

function resetRow(row: EditableRow) {
  if (row.locked) return;
  row.visible = true;
  row.labelZh = '';
  row.labelEn = '';
  row.iconKey = null;
  // 顺序是组级属性：还原任一行时一并清掉同组的显式顺序，避免留下「已修改」残留。
  const siblings = rows.value.filter((item) => item.def.parentKey === row.def.parentKey);
  if (siblings.some((item) => item.order !== null)) {
    siblings.forEach((item) => {
      item.order = null;
    });
    reorderRows();
  }
}

function flat(node: MenuNodeOverride | undefined) {
  return {
    显示: node?.visible === false ? '隐藏' : '显示',
    中文名: node?.label?.['zh-CN'] || '（默认）',
    英文名: node?.label?.['en-US'] || '（默认）',
    图标: node?.iconKey || '（默认）',
    顺序: node?.order === null || node?.order === undefined ? '（默认）' : String(node.order),
  };
}

const diffLines = computed<DiffLine[]>(() => {
  const saved = new Map<string, MenuNodeOverride>(
    (JSON.parse(savedSnapshot.value || '[]') as MenuNodeOverride[]).map((node) => [node.key, node]),
  );
  const current = new Map(currentNodes().map((node) => [node.key, node]));
  const lines: DiffLine[] = [];
  for (const key of new Set([...saved.keys(), ...current.keys()])) {
    const before = flat(saved.get(key));
    const after = flat(current.get(key));
    for (const field of Object.keys(before) as Array<keyof typeof before>) {
      if (before[field] !== after[field]) {
        lines.push({ key, field, from: before[field], to: after[field] });
      }
    }
  }
  return lines;
});

const readonlyColumns = [
  { title: '路径', key: 'key', width: 300, ellipsis: { tooltip: true } },
  { title: '名称', key: 'title', width: 160 },
  { title: '类型', key: 'kind', width: 110, render: (row: (typeof menuCatalog.readonly)[number]) => (row.kind === 'redirect' ? '旧路径重定向' : '隐藏页面') },
  { title: '跳转目标', key: 'target', ellipsis: { tooltip: true } },
];

async function refresh(force = false) {
  await menuStore.load(tenantKey.value, force);
  initRows();
}

async function onSave() {
  try {
    await menuStore.save(currentNodes());
    initRows();
    message.success('菜单配置已保存，侧边栏已更新');
  } catch (error) {
    message.error(`保存失败：${String((error as Error)?.message || error)}`);
  }
}

async function onReset() {
  if (!window.confirm('确定恢复默认菜单？所有自定义显示、顺序与名称都会被清除。')) return;
  try {
    await menuStore.reset();
    initRows();
    message.success('已恢复默认菜单');
  } catch (error) {
    message.error(`恢复失败：${String((error as Error)?.message || error)}`);
  }
}

onMounted(async () => {
  await refresh(false);
});

onBeforeRouteLeave(() => {
  if (!dirty.value) return true;
  return window.confirm('有未保存的菜单变更，确定离开吗？');
});
</script>

<template>
  <div class="mg-page">
    <PageIntro
      :title="t('菜单管理')"
      description="集中配置侧边栏菜单的显示、顺序、名称与图标；路由与 URL 保持不变。"
      :tags="['055 · 菜单管理', '租户级默认方案']"
    >
      <template #actions>
        <NSpace>
          <NButton size="small" @click="refresh(true)">刷新</NButton>
          <NButton size="small" @click="showDiff = true">变更预览</NButton>
          <NButton size="small" @click="onReset">恢复默认</NButton>
          <NButton
            size="small"
            type="primary"
            :loading="menuStore.saving"
            :disabled="!dirty"
            @click="onSave"
          >保存</NButton>
        </NSpace>
      </template>
    </PageIntro>

    <NAlert type="warning" :bordered="false" style="margin-bottom: 16px">
      菜单配置只控制<strong>展示</strong>，不是权限：隐藏某个菜单后，直接输入 URL 仍可打开该页面。
      访问控制由后端接口与角色判定负责。锁定项（工作台 / 菜单管理 / 平台控制台）不可隐藏。
    </NAlert>

    <NAlert v-if="menuStore.loadFailed" type="error" :bordered="false" style="margin-bottom: 16px">
      菜单配置接口暂不可用，当前展示的是系统默认菜单；此时保存可能失败，请稍后点「刷新」重试。
    </NAlert>

    <NCard>
      <template #header>
        <div class="menu-toolbar">
          <NSpace align="center">
            <NInput
              v-model:value="search"
              clearable
              placeholder="搜索路径或名称"
              style="width: 240px"
            />
            <NButton size="small" :type="onlyModified ? 'primary' : 'default'" @click="onlyModified = !onlyModified">
              仅看已修改
            </NButton>
            <NTag size="small" :bordered="false">已修改 {{ modifiedCount }} 项</NTag>
            <span v-if="menuStore.updatedAt" class="menu-meta">上次保存：{{ menuStore.updatedAt }}</span>
          </NSpace>
          <span class="menu-meta">共 {{ menuCatalog.nodes.length }} 个可管理节点 / {{ menuCatalog.readonly.length }} 条只读路由</span>
        </div>
      </template>

      <NEmpty v-if="ready && !displayRows.length" description="没有匹配的菜单项" />

      <div v-else class="menu-tree">
        <div
          v-for="item in displayRows"
          :key="item.row.def.key"
          class="menu-row"
          :class="{ 'menu-row--child': item.level === 1, 'menu-row--group': item.row.def.isGroup }"
        >
          <div class="menu-row__info">
            <span class="menu-row__title">{{ displayTitle(item.row) }}</span>
            <code class="menu-row__path">{{ item.row.def.key }}</code>
            <NTag v-if="item.row.def.isGroup" size="small" :bordered="false">分组</NTag>
            <NTag v-if="item.row.locked" size="small" type="warning" :bordered="false">锁定</NTag>
            <NTag v-if="item.row.def.platformOnly" size="small" :bordered="false">平台</NTag>
            <NTag v-if="isModified(item.row)" size="small" type="success" :bordered="false">已修改</NTag>
            <NTag v-else size="small" :bordered="false">默认</NTag>
            <NTag v-if="!item.row.visible" size="small" type="error" :bordered="false">已隐藏</NTag>
          </div>
          <div class="menu-row__controls">
            <NSwitch
              v-model:value="item.row.visible"
              :disabled="item.row.locked"
              size="small"
              aria-label="菜单显示"
            />
            <NInput
              v-model:value="item.row.labelZh"
              size="small"
              placeholder="中文名（留空用默认）"
              style="width: 170px"
            />
            <NInput
              v-model:value="item.row.labelEn"
              size="small"
              placeholder="English label"
              style="width: 160px"
            />
            <NSelect
              v-model:value="item.row.iconKey"
              :options="ICON_OPTIONS"
              clearable
              size="small"
              placeholder="图标"
              style="width: 130px"
            />
            <NButton size="tiny" :disabled="!canMove(item.row, -1)" @click="move(item.row, -1)">↑</NButton>
            <NButton size="tiny" :disabled="!canMove(item.row, 1)" @click="move(item.row, 1)">↓</NButton>
            <NButton
              v-if="isModified(item.row)"
              size="tiny"
              quaternary
              title="还原本行显示与名称，并把所在分组的顺序恢复默认"
              @click="resetRow(item.row)"
            >还原</NButton>
          </div>
        </div>
      </div>
    </NCard>

    <NCard style="margin-top: 16px">
      <template #header>
        <div class="menu-toolbar">
          <span class="menu-card-title">{{ t('只读路由') }}</span>
          <NButton size="small" @click="showReadonly = !showReadonly">
            {{ showReadonly ? '收起' : '展开' }}
          </NButton>
        </div>
      </template>
      <div v-if="showReadonly" class="mg-card__body">
        <p class="menu-meta" style="margin: 0 0 12px">
          以下为隐藏页面与旧路径重定向，仅用于查看现有 URL 与跳转目标，不能编入菜单树。
        </p>
        <NDataTable
          :columns="readonlyColumns"
          :data="menuCatalog.readonly"
          :pagination="{ pageSize: 10 }"
          size="small"
          bordered
        />
      </div>
      <div v-else class="menu-meta" style="padding: 4px 0">
        隐藏页面与旧路径重定向共 {{ menuCatalog.readonly.length }} 条，点击「展开」查看。
      </div>
    </NCard>

    <NModal v-model:show="showDiff" title="变更预览" preset="card" style="width: 720px">
      <NEmpty v-if="!diffLines.length" description="当前没有未保存的变更" />
      <NDataTable v-else :columns="[
        { title: '路径', key: 'key', width: 220 },
        { title: '字段', key: 'field', width: 90 },
        { title: '原值', key: 'from' },
        { title: '新值', key: 'to' },
      ]" :data="diffLines" size="small" bordered :max-height="360" />
      <template #footer>
        <div class="menu-meta">共 {{ diffLines.length }} 项字段变更；保存后侧边栏立即生效。</div>
      </template>
    </NModal>
  </div>
</template>

<style scoped>
.menu-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--mg-space-3);
  flex-wrap: wrap;
  width: 100%;
}

.menu-card-title {
  font-weight: var(--mg-weight-semibold);
  color: var(--mg-text-1);
}

.menu-meta {
  font-size: 12px;
  color: var(--mg-text-3);
}

.menu-tree {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.menu-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--mg-space-3);
  flex-wrap: wrap;
  padding: 10px 12px;
  border: 1px solid var(--mg-border);
  border-radius: var(--mg-radius-md, 8px);
  background: var(--mg-bg-surface);
}

.menu-row--group {
  background: var(--mg-bg-subtle);
  font-weight: var(--mg-weight-semibold);
}

.menu-row--child {
  margin-left: 28px;
  background: var(--mg-bg-surface-hover, var(--mg-bg-surface));
}

.menu-row__info,
.menu-row__controls {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

.menu-row__title {
  min-width: 110px;
  color: var(--mg-text-1);
}

.menu-row__path {
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  font-size: 12px;
  color: var(--mg-text-3);
}
</style>
