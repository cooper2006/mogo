/**
 * /research 调研服务层 —— mock 先行（产品经理拍板：门禁 001 端到端验收通过前只走 mock，
 * 不得真实调用 /askai-api/api/chat/completions，否则会被 fail-closed 拒掉）。
 *
 * 切真接口的方式：把 USE_MOCK 置 false 并填好 askaiEndpoint。页面与四章渲染不感知差异，
 * 因为返回的是同一种 ResearchReport 结构。
 */

/** 四章数据源配置（可配置：按需增删来源，优先级由 ORDER 定义） */
export const researchSources: Record<ChapterKey, string[]> = {
    market: ['行业分析报告', '公司官网/新闻稿', '百度指数'],
    features: ['产品官网', '帮助文档/更新日志', '应用商店'],
    finance: ['财报/招股书', '券商研报', '一级市场融资数据'],
    sentiment: ['微博', '知乎', '微信公众号/脉脉']
}

/** 章节优先级：综合判断 > 市场情报/功能对比 > 财务估值/社媒舆情（产品经理定） */
export const CHAPTER_ORDER = ['market', 'features', 'finance', 'sentiment'] as const
export type ChapterKey = (typeof CHAPTER_ORDER)[number]

export const CHAPTER_TITLES: Record<ChapterKey, string> = {
    market: '① 市场情报',
    features: '② 产品功能对比',
    finance: '③ 财务估值',
    sentiment: '④ 社媒舆情'
}

export interface Chapter {
    key: ChapterKey
    title: string
    sources: string[]
    sections: { heading: string; body: string }[]
}

export interface ResearchReport {
    subject: string
    generatedAt: string
    mock: boolean
    judgment: { verdict: string; points: string[] }
    chapters: Chapter[]
}

/** 门禁验收通过前保持 true；切真接口置 false（见文件头注释） */
const USE_MOCK = true
const askaiEndpoint = '/askai-api/api/chat/completions'

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** mock 报告生成：竞品名 → 四章 + 综合判断（结构与真接口约定一致） */
async function mockReport(subject: string): Promise<ResearchReport> {
    await delay(900)
    const chapters: Chapter[] = [
        {
            key: 'market',
            title: CHAPTER_TITLES.market,
            sources: researchSources.market,
            sections: [
                {
                    heading: '定位与体量',
                    body: `${subject} 处于企业协同/OA 赛道的第一梯队（mock 数据），目标市场以中大型组织数字化转型为主，近年增速放缓、存量竞争加剧。`
                },
                {
                    heading: '竞争格局',
                    body: `与同类产品相比，${subject} 在生态整合与政企渠道占优，但在垂直场景深度与开放能力上面临新进入者的挤压（mock 数据）。`
                }
            ]
        },
        {
            key: 'features',
            title: CHAPTER_TITLES.features,
            sources: researchSources.features,
            sections: [
                {
                    heading: '核心能力矩阵',
                    body: `IM/音视频/文档协同/开放平台四条主线齐全；${subject} 的差异化在于内置 AI 助手与低代码扩展，短板在第三方集成的粒度控制（mock 数据）。`
                },
                {
                    heading: '与我方对比',
                    body: `我方在数据私有化与权限治理上领先；${subject} 在移动端体验与生态应用数量上领先（mock 数据）。`
                }
            ]
        },
        {
            key: 'finance',
            title: CHAPTER_TITLES.finance,
            sources: researchSources.finance,
            sections: [
                {
                    heading: '营收与估值',
                    body: `${subject} 所属主体营收结构以订阅为主、定制为辅；可比公司 EV/Revenue 区间 5–9x，估值受 AI 叙事支撑（mock 数据）。`
                },
                {
                    heading: '盈利性',
                    body: `销售费用率逐年下降、研发费用率维持高位，尚未见到公开的独立盈利口径（mock 数据）。`
                }
            ]
        },
        {
            key: 'sentiment',
            title: CHAPTER_TITLES.sentiment,
            sources: researchSources.sentiment,
            sections: [
                {
                    heading: '声量与情绪',
                    body: `近 30 天声量集中在“AI 更新”与“收费调整”两个话题，整体情绪中性偏正，负评主要来自稳定性与客服响应（mock 数据）。`
                },
                {
                    heading: '典型观点',
                    body: `用户认可其生态完整，抱怨集中在强绑定与迁移成本；KOL 观点分歧在私有化能力（mock 数据）。`
                }
            ]
        }
    ]
    return {
        subject,
        generatedAt: new Date().toISOString(),
        mock: USE_MOCK,
        judgment: {
            verdict: `${subject} 是第一梯队的全功能竞品，我方应在私有化与权限治理保持差异，同时补齐生态与移动端体验。`,
            points: [
                '市场：赛道进入存量竞争，AI 能力成为替换决策的主要变量。',
                '产品：对方生态占优，我方在数据主权与治理深度上占优。',
                '财务：可比估值 5–9x EV/Revenue，AI 叙事是主要溢价来源。',
                '舆情：中性偏正，负评集中在稳定性与收费，是我方切入点。'
            ]
        },
        chapters
    }
}

/**
 * 统一入口：竞品名 → ResearchReport。
 * mock 关闭后走真接口；骨架阶段不实现真调用（001 验收闸门未过，见文件头）。
 */
export async function generateResearch(subject: string): Promise<ResearchReport> {
    if (USE_MOCK) return mockReport(subject)
    // TODO(切真接口): POST askaiEndpoint，prompt 约定四章结构后解析成 ResearchReport
    throw new Error(`真接口尚未接入（${askaiEndpoint}），请等待 001 端到端验收通过`)
}
