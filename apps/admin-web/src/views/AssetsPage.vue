<script setup lang="ts">
import { computed, onMounted, ref } from 'vue';
import { useRouter } from 'vue-router';
import { NCard, NButton, NTag, NSelect, NEmpty, NAffix } from 'naive-ui';
import PageIntro from '../components/PageIntro.vue';
import { fetchCapabilities, type CapabilityAsset, type AssetCategory } from '../api/capabilities';
import { fetchSkills, type SkillItem } from '../api/skills';
import { fetchTrustRatings, type TrustRating } from '../api/trustRatings';
import { fetchPortalListings, fetchPortalApprovals, type PortalListing, type PortalApprovalItem } from '../api/portal';

// 045 资产中心（FR-1/2/3/4/5）—— admin-web 统一资产视图。
// 后端补 `GET /api/v1/capabilities/list`（批次1，018），其余四块复用既有 admin
// 接口（skills / trust-ratings / portal-admin），五块数据由前端 join 成统一资产列表。

interface AssetRow {
  key: string;                       // `${asset_type}:${asset_key}`，与上架/评级/申领同源
  assetType: 'skill' | 'capability_asset';
  assetKey: string;
  name: string;
  category: AssetCategory;           // skill / mcp / tool / connector（FR-4）
  level: string | null;              // 可信评级 L1–L4
  listed: boolean;                   // 是否上架门户（FR-3）
  grantCount: number;                // 已授权 grant 次数（FR-5）
  recentGrant: PortalApprovalItem | null; // 最近一次申领明细（FR-5）
}

const router = useRouter();
const loading = ref(true);
const error = ref('');
const rows = ref<AssetRow[]>([]);
const assetCategory = ref<AssetCategory | 'all'>('all');

/** 类型下拉 4 项（FR-4），key 与 category 同值，label 与 §3.2 类别一致。 */
const categoryOptions = [
  { label: '技能', value: 'skill' },
  { label: 'MCP 能力', value: 'mcp' },
  { label: '工具', value: 'tool' },
  { label: '连接器', value: 'connector' },
];

/** 类别映射（§3.2）：能力资产 kind → category；技能统一归 skill。 */
function mapCapabilityCategory(kind: string): AssetCategory {
  if (kind === 'mcp') return 'mcp';
  if (kind === 'connector') return 'connector';
  return 'tool'; // rest / tool / 未知统一归 tool
}

/** 上架标志判定（§3.2）：技能按 authoring_mode，能力资产按 portal_listings 存在。 */
function isSkillListed(skill: SkillItem): boolean {
  const lifecycle = skill.lifecycle;
  if (lifecycle?.authoringMode === 'platform') {
    return lifecycle?.publicationStatus === 'published';
  }
  return true; // package / community 走 enabled，这里简化为已上架
}

async function loadAll() {
  loading.value = true;
  error.value = '';
  try {
    // 五块并发：能力资产（新接口）+ 技能 + 评级 + 上架 + 申领（复用）。
    const [caps, skills, ratings, listings, requests] = await Promise.all([
      fetchCapabilities().catch(() => [] as CapabilityAsset[]),
      fetchSkills().catch(() => [] as SkillItem[]),
      fetchTrustRatings().catch(() => [] as TrustRating[]),
      fetchPortalListings().catch(() => [] as PortalListing[]),
      fetchPortalApprovals().catch(() => [] as PortalApprovalItem[]),
    ]);

    // 评级 map：key = `${asset_type}:${asset_key}`（与 trust_ratings.asset_type/asset_key 同源）。
    const ratingMap = new Map<string, TrustRating>();
    ratings.forEach((r) => ratingMap.set(`${r.asset_type}:${r.asset_key}`, r));

    // 上架 map：同 key。
    const listingMap = new Map<string, PortalListing>();
    listings.forEach((l) => listingMap.set(`${l.asset_type}:${l.asset_key}`, l));

    // 申领 map：按 status=granted 聚合，按 updated_at 倒序取最近 1 条（§3.3）。
    const grantMap = new Map<string, PortalApprovalItem[]>();
    requests
      .filter((r) => r.status === 'granted')
      .forEach((r) => {
        const k = `${r.asset_type}:${r.asset_key}`;
        const arr = grantMap.get(k) ?? [];
        arr.push(r);
        grantMap.set(k, arr);
      });
    grantMap.forEach((arr) =>
      arr.sort((a, b) =>
        (b.granted_at || b.decided_at || '').localeCompare(a.granted_at || a.decided_at || ''),
      ),
    );

    const next: AssetRow[] = [];
    skills.forEach((s) => {
      const key = `skill:${s.id}`;
      next.push({
        key,
        assetType: 'skill',
        assetKey: s.id,
        name: s.name,
        category: 'skill',
        level: ratingMap.get(key)?.level ?? null,
        listed: isSkillListed(s),
        grantCount: grantMap.get(key)?.length ?? 0,
        recentGrant: grantMap.get(key)?.[0] ?? null,
      });
    });
    caps.forEach((c) => {
      const key = `capability_asset:${c.asset_id}`;
      next.push({
        key,
        assetType: 'capability_asset',
        assetKey: c.asset_id,
        name: c.name,
        category: mapCapabilityCategory(c.kind),
        level: ratingMap.get(key)?.level ?? null,
        listed: listingMap.has(key),
        grantCount: grantMap.get(key)?.length ?? 0,
        recentGrant: grantMap.get(key)?.[0] ?? null,
      });
    });
    rows.value = next;
  } catch {
    error.value = '资产中心数据加载失败';
  } finally {
    loading.value = false;
  }
}

const filteredRows = computed(() =>
  assetCategory.value === 'all' ? rows.value : rows.value.filter((r) => r.category === assetCategory.value),
);

const categorySummary = computed(() => {
  const base = { skill: 0, mcp: 0, tool: 0, connector: 0 };
  rows.value.forEach((r) => {
    base[r.category] += 1;
  });
  return base;
});

function goTrustRating(row: AssetRow) {
  router.push({ path: '/assets/ratings', query: { asset_type: row.assetType, asset_key: row.assetKey } });
}
function goPortalListing(row: AssetRow) {
  router.push({ path: '/assets/listings', query: { asset_type: row.assetType, asset_key: row.assetKey } });
}
function goPortalApproval(row: AssetRow) {
  router.push({ path: '/assets/approvals', query: { asset_type: row.assetType, asset_key: row.assetKey } });
}

onMounted(loadAll);
</script>

<template>
  <div class="mg-page">
    <PageIntro title="资产中心" description="统一查看技能与能力资产的上架、评级与申领状态。" />

    <NAffix :offset-distance="80">
      <div class="filter-bar">
        <div class="filter-field">
          <div class="mg-caption">资产类型</div>
          <NSelect
            v-model:value="assetCategory"
            :options="[{ label: '全部', value: 'all' }, ...categoryOptions]"
            style="width: 160px"
          />
        </div>
        <div class="summary-line mg-text-2">
          技能 <strong>{{ categorySummary.skill }}</strong>
          · MCP <strong>{{ categorySummary.mcp }}</strong>
          · 工具 <strong>{{ categorySummary.tool }}</strong>
          · 连接器 <strong>{{ categorySummary.connector }}</strong>
        </div>
        <NButton size="small" :loading="loading" @click="loadAll">刷新</NButton>
      </div>
    </NAffix>

    <div v-if="loading" class="state-block mg-text-3">加载中…</div>

    <div v-else-if="error" class="state-block state-block--error">
      <div>{{ error }}</div>
      <div class="state-retry">
        <NButton size="tiny" @click="loadAll">重试</NButton>
      </div>
    </div>

    <NEmpty
      v-else-if="filteredRows.length === 0"
      description="暂无资产，请调整筛选或先在各管理页上架资产。"
      class="state-block"
    />

    <div v-else class="asset-grid">
      <NCard v-for="row in filteredRows" :key="row.key" size="small" hoverable class="asset-card">
        <div class="asset-row">
          <div class="asset-main">
            <div class="asset-name">{{ row.name }}</div>
            <div class="asset-meta mg-caption">
              <span>{{ row.assetType === 'skill' ? '技能' : '能力资产' }}</span>
              <span aria-hidden="true">·</span>
              <span>{{ row.category }}</span>
              <span aria-hidden="true">·</span>
              <span>已授权 {{ row.grantCount }} 次</span>
            </div>
            <div v-if="row.recentGrant" class="asset-grant mg-caption">
              最近申领：{{ row.recentGrant.asset_name }} · {{ row.recentGrant.granted_at || row.recentGrant.decided_at }}
            </div>
          </div>
          <div class="asset-tags">
            <NTag v-if="row.listed" type="success" size="small">已上架</NTag>
            <NTag v-else type="default" size="small">未上架</NTag>
            <NTag v-if="row.level" size="small" :bordered="false">评级 {{ row.level }}</NTag>
          </div>
        </div>
        <div class="asset-actions">
          <NButton size="tiny" quaternary @click="goTrustRating(row)">评级</NButton>
          <NButton size="tiny" quaternary @click="goPortalListing(row)">上架</NButton>
          <NButton size="tiny" quaternary @click="goPortalApproval(row)">申领</NButton>
        </div>
      </NCard>
    </div>
  </div>
</template>

<style scoped>
/* 颜色与间距全部来自设计令牌（styles/tokens.css），深色主题自动跟随。 */
.filter-bar {
  display: flex;
  align-items: center;
  gap: var(--mg-space-4);
  flex-wrap: wrap;
  padding: var(--mg-space-3) var(--mg-space-4);
  border: 1px solid var(--mg-border);
  border-radius: var(--mg-radius-lg);
  background: var(--mg-bg-surface);
  box-shadow: var(--mg-shadow-sm);
}

.filter-field {
  display: flex;
  flex-direction: column;
  gap: var(--mg-space-1);
}

.summary-line {
  font-size: var(--mg-font-size-sm);
}

.summary-line strong {
  color: var(--mg-text-1);
  font-weight: var(--mg-weight-semibold);
  font-variant-numeric: tabular-nums;
}

.state-block {
  padding: var(--mg-space-8) var(--mg-space-4);
  text-align: center;
}

.state-block--error {
  border: 1px solid var(--mg-danger-border);
  border-radius: var(--mg-radius-lg);
  background: var(--mg-danger-bg);
  color: var(--mg-danger-text);
}

.state-retry {
  margin-top: var(--mg-space-2);
}

.asset-grid {
  display: grid;
  gap: var(--mg-space-3);
  grid-template-columns: repeat(auto-fill, minmax(360px, 1fr));
}

.asset-card {
  transition: box-shadow var(--mg-transition-fast), border-color var(--mg-transition-fast);
}

.asset-card:hover {
  border-color: var(--mg-brand-soft-border);
  box-shadow: var(--mg-shadow-md);
}

.asset-row {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--mg-space-4);
}

.asset-main {
  min-width: 0;
}

.asset-name {
  font-size: var(--mg-font-size-base);
  font-weight: var(--mg-weight-medium);
  color: var(--mg-text-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-meta {
  display: flex;
  align-items: center;
  gap: var(--mg-space-1);
  margin-top: var(--mg-space-1);
  flex-wrap: wrap;
}

.asset-grant {
  margin-top: var(--mg-space-1);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.asset-tags {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  flex-shrink: 0;
}

.asset-actions {
  display: flex;
  align-items: center;
  gap: var(--mg-space-2);
  margin-top: var(--mg-space-3);
  padding-top: var(--mg-space-3);
  border-top: 1px solid var(--mg-divider);
}
</style>
