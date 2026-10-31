import { apiClient } from './client'

export type TopicMode = 'off' | 'denylist' | 'allowlist'

export interface TopicTerm {
  keyword: string
  synonyms: string[]
}

export interface TopicRule {
  id: string
  name?: string
  enabled: boolean
  terms: TopicTerm[]
}

export interface TopicPolicy {
  mode: TopicMode
  rules: TopicRule[]
  updatedAt?: string | null
}

export interface TopicTestResult {
  allowed: boolean
  matchedRule: { id: string; keyword: string } | null
  mode: TopicMode
}

export interface TopicSummary {
  mode: TopicMode
  ruleCount: number
  enabledRuleCount: number
  updatedAt?: string | null
}

export interface TopicRulePage {
  items: TopicRule[]
  total: number
  page: number
  pageSize: number
}

export interface TopicChanges {
  mode: TopicMode
  updatedAt?: string | null
  upserts: TopicRule[]
  deletes: string[]
}

export async function fetchTopicSummary(): Promise<TopicSummary> {
  const { data } = await apiClient.get<TopicSummary>('/api/v1/settings/topic-admission/summary')
  return data
}

export async function fetchTopicRules(params: { q: string; status: string; page: number; pageSize?: number; offset?: number }): Promise<TopicRulePage> {
  const { data } = await apiClient.get<TopicRulePage>('/api/v1/settings/topic-admission/rules', { params: { pageSize: 10, ...params } })
  return data
}

export async function saveTopicChanges(changes: TopicChanges): Promise<TopicSummary> {
  const { data } = await apiClient.put<TopicSummary>('/api/v1/settings/topic-admission/changes', changes)
  return data
}

export async function previewTopicChanges(text: string, changes: TopicChanges): Promise<TopicTestResult> {
  const { data } = await apiClient.post<TopicTestResult>('/api/v1/settings/topic-admission/preview', { text, ...changes })
  return data
}

export async function fetchTopicPolicy(): Promise<TopicPolicy> {
  const { data } = await apiClient.get<TopicPolicy>('/api/v1/settings/topic-admission')
  return data
}

export async function saveTopicPolicy(policy: TopicPolicy): Promise<TopicPolicy> {
  const { data } = await apiClient.put<TopicPolicy>('/api/v1/settings/topic-admission', policy)
  return data
}

export async function testTopicPolicy(text: string, policy: TopicPolicy): Promise<TopicTestResult> {
  const { data } = await apiClient.post<TopicTestResult>('/api/v1/settings/topic-admission/test', { text, policy })
  return data
}
