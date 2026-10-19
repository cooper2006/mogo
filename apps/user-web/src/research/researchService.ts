/**
 * /research 调研服务层 —— 门禁 001 端到端验收已通过，改为走真接口
 * /askai-api/api/chat/completions（前端登录态 auth_token）。返回结构与 mock 层一致，
 * 页面与四章渲染不感知差异。数据源由 researchConfig 控制，切换时无需改代码重构。
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

/** 调研数据源配置——切换真/假接口只需改这里，无需动服务层签名或页面代码 */
export interface ResearchConfig {
    useMock: boolean
    endpoint: string
    version: string
}

export const researchConfig: ResearchConfig = {
    useMock: false,
    endpoint: '/askai-api/api/chat/completions',
    version: '1.0.0'
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
    metadata: { createdAt: string; version: string }
    judgment: { verdict: string; points: string[] }
    chapters: Chapter[]
}

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

/** mock 报告生成：竞品名 → 四章 + 综合判断（结构与真接口约定一致） */
async function mockReport(subject: string, selected?: ChapterKey[]): Promise<ResearchReport> {
    await delay(900)
    const allChapters: Chapter[] = [
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
    const chapters = selected && selected.length > 0
        ? allChapters.filter((c) => selected.includes(c.key))
        : allChapters
    const now = new Date().toISOString()
    return {
        subject,
        generatedAt: now,
        mock: researchConfig.useMock,
        metadata: { createdAt: now, version: researchConfig.version },
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
 * opts.chapter 可按需指定生成哪些章节（不传则全量四章）。
 * researchConfig.useMock 为 false 时走真接口 /askai-api/api/chat/completions。
 */
export async function generateResearch(
    subject: string,
    opts?: { chapter?: ChapterKey[] }
): Promise<ResearchReport> {
    if (researchConfig.useMock) return mockReport(subject, opts?.chapter)
    return realReport(subject, opts?.chapter)
}

/** 真接口：POST /askai-api/api/chat/completions，用前端登录态 auth_token */
async function realReport(subject: string, selected?: ChapterKey[]): Promise<ResearchReport> {
    const token = typeof window !== 'undefined' ? window.localStorage.getItem('auth_token') : null
    if (!token) throw new Error('未登录，请先登录再使用调研')

    const resp = await fetch(researchConfig.endpoint, {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
            Authorization: `Bearer ${token}`,
        },
        body: JSON.stringify({
            messages: [{ role: 'user', content: researchPrompt(subject, selected) }],
            output_spec: { format: 'json' },
        }),
    })
    if (!resp.ok) {
        let msg = `调研请求失败：${resp.status}`
        try {
            const json = await resp.json()
            if (json?.detail) msg = String(json.detail)
            else if (json?.message) msg = String(json.message)
        } catch { /* keep status-based message */ }
        throw new Error(msg)
    }
    const text = await resp.text()
    const assistant = extractAssistantContent(text)
    let data: any = null
    try { data = JSON.parse(assistant) } catch { data = null }
    const now = new Date().toISOString()
    if (!data || !Array.isArray(data.chapters)) {
        // 降级：原文整段放进单章，保证页面不空白
        return {
            subject,
            generatedAt: now,
            mock: false,
            metadata: { createdAt: now, version: researchConfig.version },
            judgment: { verdict: '调研已完成（未返回结构化报告，以下为模型原文）', points: [assistant.slice(0, 300)] },
            chapters: [{ key: 'market', title: '① 市场情报', sources: researchSources.market, sections: [{ heading: '模型原文', body: assistant }] }],
        }
    }
    const chapters = (data.chapters as any[])
        .filter((c) => !selected || selected.includes(c.key as ChapterKey))
        .map((c: any) => ({
            key: c.key,
            title: c.title || c.key,
            sources: researchSources[c.key as ChapterKey] || [],
            sections: (c.sections || []).map((s: any) => ({ heading: s.heading || '', body: s.body || '' })),
        }))
    return {
        subject,
        generatedAt: now,
        mock: false,
        metadata: { createdAt: now, version: researchConfig.version },
        judgment: data.judgment || { verdict: '', points: [] },
        chapters,
    }
}

function researchPrompt(subject: string, selected?: ChapterKey[]): string {
    const chapterList = selected && selected.length > 0
        ? selected.map((k) => `{"key":"${k}","title":"${CHAPTER_TITLES[k]}","sections":[{"heading":"...","body":"..."}]}`).join(',')
        : `{"key":"market","title":"① 市场情报","sections":[{"heading":"...","body":"..."}]},
    {"key":"features","title":"② 产品功能对比","sections":[{"heading":"...","body":"..."}]},
    {"key":"finance","title":"③ 财务估值","sections":[{"heading":"...","body":"..."}]},
    {"key":"sentiment","title":"④ 社媒舆情","sections":[{"heading":"...","body":"..."}]}`
    return `你是一名资深行业分析师。请针对竞品「${subject}」输出一份结构化调研报告，且**只输出一个合法的 JSON 对象，不要包含 Markdown 代码块或任何说明文字**。JSON Schema：
{
  "judgment": {"verdict": "一句话综合判断结论", "points": ["市场","产品","财务","舆情"四个维度各一条要点]},
  "chapters": [
    ${chapterList}
  ]
}
要求：章节顺序固定为市场情报→产品功能对比→财务估值→社媒舆情；每章 2–3 个 section，每个 section 有 heading 与 body；语言用中文；所有字段都要填写，不要留空。`
}

function extractAssistantContent(ndjson: string): string {
    const parts: string[] = []
    for (const line of ndjson.split('\n')) {
        const s = line.trim()
        if (!s) continue
        try {
            const ev = JSON.parse(s)
            if (!ev || typeof ev !== 'object') continue
            const content =
                ev.choices?.[0]?.delta?.content ??
                ev.choices?.[0]?.message?.content ??
                ev.message?.content ??
                ev.content ??
                ev.text ??
                ev.delta?.content
            if (typeof content === 'string') parts.push(content)
        } catch { /* ignore non-JSON lines */ }
    }
    return parts.join('')
}
