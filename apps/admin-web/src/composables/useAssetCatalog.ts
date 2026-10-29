/**
 * 045 资产中心共享数据源 —— 能力资产 / 技能 / 信任评级 / 门户上架四块数据，
 * 由前端 join 成统一资产列表，供 PortalListingPage / TrustRatingPage /
 * SkillsPage / PortalApprovalPage 复用（§5 方案 B）。
 *
 * 与 `AssetsPage.vue` 的 join 逻辑保持同源：统一 key = `${asset_type}:${asset_key}`。
 * 技能按 `lifecycle.authoring_mode` 判定上架态，能力资产按 `portal_listings` 判定。
 */
import { computed, ref } from 'vue'
import { fetchCapabilities, type CapabilityAsset, type AssetCategory } from '@/api/capabilities'
import { fetchSkills, type SkillItem } from '@/api/skills'
import { fetchTrustRatings, type TrustRating } from '@/api/trustRatings'
import { fetchPortalListings, type PortalListing } from '@/api/portal'

export type CatalogAssetType = 'skill' | 'capability_asset'

/** 统一资产行（§3.2）：skill / mcp / tool / connector 四类。 */
export interface CatalogAsset {
  key: string
  assetType: CatalogAssetType
  assetKey: string
  name: string
  category: AssetCategory
  kind: string
  state: string
  /** 资产是否处于可上架的可用态（技能按 lifecycle + enabled，能力资产按 state）。 */
  active: boolean
  /** 是否已上架门户。 */
  listed: boolean
  /** 036 信任评级 L1–L4；未评级为 null。 */
  level: string | null
  /** 资产 owner：技能取评级 owner_id，能力资产取 owner_role。 */
  owner: string
  endpoint?: string
}

/** 能力资产 kind → 资产类别（§3.2）：rest / tool / 未知统一归 tool。 */
export function mapCapabilityCategory(kind: string): AssetCategory {
  if (kind === 'mcp') return 'mcp'
  if (kind === 'connector') return 'connector'
  return 'tool'
}

/** 技能是否可上架（platform 需已发布，package / community 视为已发布）。 */
export function isSkillActive(skill: SkillItem): boolean {
  if (!skill.enabled) return false
  const lifecycle = skill.lifecycle
  if (lifecycle?.authoringMode === 'platform') {
    return lifecycle.publicationStatus === 'published'
  }
  return true
}

/** 技能是否已上架门户（对齐 AssetsPage `isSkillListed`）。 */
export function isSkillListed(skill: SkillItem): boolean {
  const lifecycle = skill.lifecycle
  if (lifecycle?.authoringMode === 'platform') {
    return lifecycle.publicationStatus === 'published'
  }
  return true
}

export function useAssetCatalog() {
  const capabilities = ref<CapabilityAsset[]>([])
  const skills = ref<SkillItem[]>([])
  const ratings = ref<TrustRating[]>([])
  const listings = ref<PortalListing[]>([])
  const loading = ref(false)
  const error = ref('')

  async function load(): Promise<void> {
    if (loading.value) return
    loading.value = true
    error.value = ''
    try {
      const [caps, sks, rat, lst] = await Promise.all([
        fetchCapabilities().catch(() => [] as CapabilityAsset[]),
        fetchSkills().catch(() => [] as SkillItem[]),
        fetchTrustRatings().catch(() => [] as TrustRating[]),
        fetchPortalListings({ publishedOnly: false }).catch(() => [] as PortalListing[]),
      ])
      capabilities.value = caps
      skills.value = sks
      ratings.value = rat
      listings.value = lst
    } catch (e: any) {
      error.value = e?.response?.data?.detail || String(e)
    } finally {
      loading.value = false
    }
  }

  /** 评级 map：key = `${asset_type}:${asset_key}`。 */
  const ratingByKey = computed(() => {
    const m = new Map<string, TrustRating>()
    ratings.value.forEach((r) => m.set(`${r.asset_type}:${r.asset_key}`, r))
    return m
  })

  /** 上架 map：同 key。 */
  const listingByKey = computed(() => {
    const m = new Map<string, PortalListing>()
    listings.value.forEach((l) => m.set(`${l.asset_type}:${l.asset_key}`, l))
    return m
  })

  /** 统一资产列表（技能 + 能力资产，按 key 去重）。 */
  const assets = computed<CatalogAsset[]>(() => {
    const next: CatalogAsset[] = []
    skills.value.forEach((s) => {
      const key = `skill:${s.id}`
      const r = ratingByKey.value.get(key)
      next.push({
        key,
        assetType: 'skill',
        assetKey: s.id,
        name: s.name,
        category: 'skill',
        kind: s.lifecycle?.authoringMode ?? 'package',
        state: s.lifecycle?.publicationStatus ?? '',
        active: isSkillActive(s),
        listed: isSkillListed(s),
        level: r?.level ?? null,
        owner: r?.owner_id ?? '',
      })
    })
    capabilities.value.forEach((c) => {
      const key = `capability_asset:${c.asset_id}`
      const l = listingByKey.value.get(key)
      const r = ratingByKey.value.get(key)
      next.push({
        key,
        assetType: 'capability_asset',
        assetKey: c.asset_id,
        name: c.name,
        category: mapCapabilityCategory(c.kind),
        kind: c.kind,
        state: c.state,
        active: c.state === 'active',
        listed: l?.published === true,
        level: r?.level ?? null,
        owner: c.owner_role,
        endpoint: c.endpoint,
      })
    })
    return next
  })

  /** 按统一 key 索引，供详情 / 审批 / 上架页直接查评级 + owner。 */
  const byKey = computed(() => {
    const m = new Map<string, CatalogAsset>()
    assets.value.forEach((a) => m.set(a.key, a))
    return m
  })

  return {
    capabilities,
    skills,
    ratings,
    listings,
    loading,
    error,
    load,
    assets,
    byKey,
    ratingByKey,
    listingByKey,
  }
}
