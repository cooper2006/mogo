import { computed, reactive, ref } from 'vue'
import { fetchOrgBilling } from '../api/auth'
import { uploadChatDocument, uploadChatImage, type UploadedDocument, type UploadedImage } from '../api/chat'
import { getSession, type ChatMessage, type SessionDetail } from '../api/sessions'
import { fetchChatMessageEvents, startChatStream, type ChatStreamHandle } from './useChatStream'
import { startSessionLiveStream, type SessionLiveAccessRevokedReason, type SessionLiveExecutionEvent, type SessionLiveStreamHandle } from './useSessionLiveStream'
import { getLocale, t } from './i18n'
import { resumeBrowserInterventionTaskUntilSettled } from './tasks/browserInterventionTaskFlow'
import {
  browserInterventionTransition,
  normalizeBrowserIntervention,
  type BrowserInterventionTransition,
} from './browser/browserInterventionProjection'
import type { ExecutionStoreV3 } from '../features/execution-v3/stores/executionStore'
import type { DshTaskChangeSet } from '../platform/types'
import { isExecutionEventV3, type ExecutionEventV3 } from '../features/execution-v3/domain/protocol'
import { ensureMessageExecutionV3 } from '../features/execution-v3/stores/messageExecution'
import { refreshAfterRun } from './chatRuntimeRefresh'
import { applyAssistantContentEvent } from '../features/execution-v3/domain/assistantContent'
import type { BrowserAssistanceHandoff } from './browser/useBrowserWorkspace'
import { stopChatGeneration } from './chatCancellation'

export type RuntimeDocumentInfo = {
  id?: string
  type: 'pdf' | 'docx' | 'ppt' | 'pptx' | 'md' | 'txt' | 'html' | 'xlsx' | 'presentation_preview_bundle'
  url: string
  filename?: string
  title?: string
  object_path?: string
  signed_url?: string
  content_type?: string
  size?: number
  bundle?: Record<string, any>
}

export type RuntimeImageInfo = {
  object_path?: string
  url?: string
  signed_url?: string
  filename?: string
  content_type?: string
  size?: number
}

export type RuntimeMessage = {
  role: 'user' | 'assistant'
  content: string
  plan?: any
  progress?: { content: string; timestamp?: string }[]
  _id?: string
  _execV3?: ExecutionStoreV3
  _provisionalTextByItem?: Record<string, string>
  _backendSid?: string
  message_id?: string
  execution_events?: any[]
  documents?: RuntimeDocumentInfo[]
  images?: RuntimeImageInfo[]
  evidence_bundles?: any[]
  evidenceBundles?: any[]
  trigger_source?: string
  scheduled_job_id?: string
  scheduled_run_id?: string
  created_at?: string
  _codeChanges?: DshTaskChangeSet
}

export type PendingRuntimeDocument = {
  file: File
  kind: RuntimeDocumentInfo['type']
}

export type RuntimeIntervention = {
  reason: string
  category: string
  url?: string
  domain?: string
  screenshot?: string
  suspension_id?: string
  run_id?: string
  node_id?: string
  browser_session_id?: string
  tab_id?: string
  resumable?: boolean
  handoff?: BrowserAssistanceHandoff
} | null

export type ChatRuntimePane = {
  key: string
  sessionId: string | null
  messages: RuntimeMessage[]
  running: boolean
  stopping: boolean
  lastActivatedAt: number
  activeStream: ChatStreamHandle | null
  abortController: AbortController | null
  activeAssistantMessageId: string | null
  activeIntervention: RuntimeIntervention
  authResumeController: AbortController | null
  operationId: number
  activeAuthToken: string | null
  executionLocation: 'server' | 'desktop' | 'remote_sandbox'
  runtimePresetId: string
  modelInstanceId: string
  codeProject: { workspace_id: string; git_branch: string; worktree: boolean } | null
  /**
   * Session-level view tab (028): 'chat' = conversation, 'trajectory' = process.
   * Kept per-pane so switching sessions never leaks the selected tab.
   */
  activeView: 'chat' | 'trajectory'
  /**
   * P3 SSE：共享会话（access='shared'）的实时订阅句柄；owner 或非共享会话为
   * null。会话关闭/重置时 stop()。
   */
  sessionLiveHandle: SessionLiveStreamHandle | null
}

type SendInput = {
  text: string
  images: File[]
  documents: PendingRuntimeDocument[]
  knowledgeQaEnabled: boolean
  selectedSkillId?: string
  modelId?: string
  authToken: string | null
  userId: string | null
  tenantId: string | null
  locale: 'zh' | 'en'
  timezone: string
}

type RuntimeCallbacks = {
  onSessionMissing?: (sessionId: string) => void
  onSessionResolved?: (sessionId: string) => void
  onSessionUpdated?: (sessionId: string) => void | Promise<void>
  onQuotaRefresh?: () => void | Promise<void>
  onLoginRequired?: () => void
  /** P3 SSE：共享会话实时流检测到访问被撤销/成员退出（participant_removed /
   *  participant_left）。宿主应提示并退出该共享会话。 */
  onSharedAccessLost?: (sessionId: string, reason: SessionLiveAccessRevokedReason) => void
}

export type ExternalTurnHandle = {
  pane: ChatRuntimePane
  assistant: RuntimeMessage
  apply(event: ExecutionEventV3): boolean
  finish(): void
  setCodeChanges(changes: DshTaskChangeSet): void
}

const state = reactive({
  panes: [] as ChatRuntimePane[],
  activeKey: '',
  unreadSessionIds: new Set<string>(),
})

let localSeq = 0
let messageSeq = 0
const MAX_CACHED_PANES = 8

function nextLocalKey() {
  localSeq += 1
  return `local_${Date.now()}_${localSeq}`
}

function nextMessageId() {
  messageSeq += 1
  return `msg_${Date.now()}_${messageSeq}`
}

function ensureMessageId<T extends RuntimeMessage>(msg: T): T {
  if (msg._id) return msg
  return { ...msg, _id: nextMessageId() }
}

function normalizeMessages(raw: ChatMessage[] | RuntimeMessage[] | undefined): RuntimeMessage[] {
  if (!raw?.length) return []
  const result: RuntimeMessage[] = []
  for (const item of raw) {
    const role = item.role === 'user' ? 'user' : 'assistant'
    const msg = ensureMessageId({ ...(item as RuntimeMessage), role, content: item.content || '' })
    result.push(msg)
  }
  return result
}

function createPane(input: { key?: string; sessionId: string | null; messages?: ChatMessage[] | RuntimeMessage[]; running?: boolean }): ChatRuntimePane {
  return {
    key: input.key || nextLocalKey(),
    sessionId: input.sessionId,
    messages: normalizeMessages(input.messages),
    running: Boolean(input.running),
    stopping: false,
    lastActivatedAt: Date.now(),
    activeStream: null,
    abortController: null,
    activeAssistantMessageId: null,
    activeIntervention: null,
    authResumeController: null,
    operationId: 0,
    activeAuthToken: null,
    executionLocation: 'server',
    runtimePresetId: 'askai-enterprise',
    modelInstanceId: '',
    codeProject: null,
    activeView: 'chat',
    sessionLiveHandle: null,
  }
}

function findPaneByKey(key: string) {
  return state.panes.find((pane) => pane.key === key) || null
}

function findPaneBySessionId(sessionId: string) {
  return state.panes.find((pane) => pane.sessionId === sessionId) || null
}

function activePane() {
  return findPaneByKey(state.activeKey)
}

function setActivePane(pane: ChatRuntimePane) {
  pane.lastActivatedAt = Date.now()
  state.activeKey = pane.key
}

function pruneInactivePanes() {
  const activeKey = state.activeKey
  const mustKeep = new Set<string>()
  for (const pane of state.panes) {
    if (pane.running || pane.key === activeKey) {
      mustKeep.add(pane.key)
    }
  }

  const keepBySession = new Set<string>()
  const sessionPanes = state.panes
    .filter((pane) => pane.sessionId)
    .sort((a, b) => b.lastActivatedAt - a.lastActivatedAt)
  for (const pane of sessionPanes.slice(0, MAX_CACHED_PANES)) {
    keepBySession.add(pane.key)
  }

  state.panes = state.panes.filter((pane) => mustKeep.has(pane.key) || keepBySession.has(pane.key))
}

function clearUnread(sessionId: string | null) {
  if (!sessionId || !state.unreadSessionIds.has(sessionId)) return
  const next = new Set(state.unreadSessionIds)
  next.delete(sessionId)
  state.unreadSessionIds = next
}

function markUnread(sessionId: string) {
  if (!sessionId) return
  const next = new Set(state.unreadSessionIds)
  next.add(sessionId)
  state.unreadSessionIds = next
}

function setPaneRunning(pane: ChatRuntimePane, running: boolean) {
  const wasRunning = pane.running
  pane.running = running
  if (wasRunning && !running && pane.sessionId && pane.key !== state.activeKey) {
    markUnread(pane.sessionId)
  }
  if (!running) pruneInactivePanes()
}

/** 目标字段为空时，用另一个 pane 的同名字段填充（保留 keeper 已有运行态）。 */
function copyPaneFieldIfAbsent<K extends 'activeStream' | 'abortController' | 'activeAssistantMessageId' | 'activeIntervention' | 'authResumeController'>(
  keeper: ChatRuntimePane,
  removed: ChatRuntimePane,
  field: K,
): void {
  if (!keeper[field] && removed[field]) keeper[field] = removed[field]
}

/** 同会话两个 pane 合并：保留仍在运行的那一个，迁移运行态并从列表移除被丢弃者。 */
function mergeDuplicatePane(pane: ChatRuntimePane, duplicate: ChatRuntimePane, sessionId: string, callbacks: RuntimeCallbacks): void {
  const keepRunningPane = pane.running || !duplicate.running
  const keeper = keepRunningPane ? pane : duplicate
  const removed = keepRunningPane ? duplicate : pane
  keeper.sessionId = sessionId
  keeper.modelInstanceId = pane.modelInstanceId || keeper.modelInstanceId || duplicate.modelInstanceId
  keeper.lastActivatedAt = Math.max(keeper.lastActivatedAt, removed.lastActivatedAt)
  if (!keeper.messages.length && removed.messages.length) keeper.messages = removed.messages
  copyPaneFieldIfAbsent(keeper, removed, 'activeStream')
  copyPaneFieldIfAbsent(keeper, removed, 'abortController')
  copyPaneFieldIfAbsent(keeper, removed, 'activeAssistantMessageId')
  copyPaneFieldIfAbsent(keeper, removed, 'activeIntervention')
  copyPaneFieldIfAbsent(keeper, removed, 'authResumeController')
  if (state.activeKey === removed.key) state.activeKey = keeper.key
  state.panes = state.panes.filter((item) => item !== removed)
  callbacks.onSessionResolved?.(sessionId)
}

function resolvePaneSession(pane: ChatRuntimePane, sessionId: string, callbacks: RuntimeCallbacks = {}) {
  if (!sessionId) return
  const duplicate = state.panes.find((item) => item !== pane && item.sessionId === sessionId)
  if (duplicate) {
    mergeDuplicatePane(pane, duplicate, sessionId, callbacks)
    return
  }
  pane.sessionId = sessionId
  callbacks.onSessionResolved?.(sessionId)
}

function ensureExecV3(msg: RuntimeMessage): ExecutionStoreV3 {
  return ensureMessageExecutionV3(msg)
}

async function uploadImages(userId: string, files: File[], authToken?: string | null): Promise<UploadedImage[]> {
  const uploaded: UploadedImage[] = []
  for (const file of files) {
    uploaded.push(await uploadChatImage(userId, file, authToken))
  }
  return uploaded
}

async function uploadDocuments(userId: string, docs: PendingRuntimeDocument[], authToken?: string | null): Promise<RuntimeDocumentInfo[]> {
  const uploaded: RuntimeDocumentInfo[] = []
  for (const item of docs) {
    const result: UploadedDocument = await uploadChatDocument(userId, item.file, authToken)
    uploaded.push({
      type: item.kind,
      url: result.url || result.signed_url || '',
      filename: result.filename || item.file.name,
      title: result.filename || item.file.name,
      object_path: result.object_path,
      signed_url: result.signed_url,
      content_type: result.content_type,
      size: result.size,
    })
  }
  return uploaded
}

function resetPanePreview(pane: ChatRuntimePane) {
  pane.activeIntervention = null
}

/** 判断输入是否包含可发送内容（文本、图片、附件或已选技能）。 */
function hasSendContent(input: SendInput, text: string): boolean {
  return Boolean(text || input.images.length > 0 || input.documents.length > 0 || input.selectedSkillId)
}

/** 具备发送所需基础身份（令牌、用户与非 default 空间）的发送输入。 */
type SendInputReady = SendInput & { authToken: string; userId: string; tenantId: string }

/** 判断当前输入是否具备发送所需的基础身份。 */
function hasSendIdentity(input: SendInput): input is SendInputReady {
  const hasBase = input.authToken && input.userId && input.tenantId
  return Boolean(hasBase) && input.tenantId !== 'default'
}

/** 额度或附件链路失败时写入错误消息并复位 running 状态。 */
function pushSendFailure(pane: ChatRuntimePane, input: SendInput, uploadErr: unknown): void {
  pane.messages.push({
    _id: nextMessageId(),
    role: 'assistant',
    content: `[Error: ${input.locale === 'zh' ? '附件上传失败' : 'Failed to upload attachments'}: ${uploadErr}]`,
  })
  setPaneRunning(pane, false)
  pane.activeAuthToken = null
}

/** 校验可用额度；不足时写入提示消息并复位 running，返回是否可继续发送。 */
async function checkSendQuota(pane: ChatRuntimePane, operationId: number, input: SendInputReady): Promise<boolean> {
  const quota = await fetchOrgBilling(input.authToken).catch((uploadErr) => {
    pushSendFailure(pane, input, uploadErr)
    return null
  })
  if (!quota || pane.operationId !== operationId) return false
  const remaining = Number(quota.data?.remainingPoints ?? 0)
  const unlimited = quota.data?.unlimited === true
  if (quota.ok && (unlimited || remaining > 0)) return true
  const isEnterprise = quota.data?.spaceType === 'enterprise'
  pane.messages.push({
    _id: nextMessageId(),
    role: 'assistant',
    content: isEnterprise
      ? '当前企业分派额度已用尽，请联系企业管理员调整额度。'
      : '个人赠送额度已用尽，请升级或切换到有可用额度的空间。',
  })
  setPaneRunning(pane, false)
  return false
}

type PreparedAttachments = { images: UploadedImage[]; documents: RuntimeDocumentInfo[] }

/** 上传本轮附件；失败时写入错误消息并复位 running，返回 null 表示不可继续。 */
async function prepareSendAttachments(
  pane: ChatRuntimePane,
  operationId: number,
  input: SendInputReady,
): Promise<PreparedAttachments | null> {
  try {
    const uploadedImages = await uploadImages(input.userId, input.images, input.authToken)
    if (pane.operationId !== operationId) return null
    const uploadedDocuments = await uploadDocuments(input.userId, input.documents, input.authToken)
    return { images: uploadedImages, documents: uploadedDocuments }
  } catch (uploadErr) {
    pushSendFailure(pane, input, uploadErr)
    return null
  }
}

function buildUserMessage(text: string, images: UploadedImage[], documents: RuntimeDocumentInfo[]): RuntimeMessage {
  return {
    _id: nextMessageId(),
    role: 'user',
    content: text,
    images: images as RuntimeImageInfo[],
    documents,
    created_at: new Date().toISOString(),
  }
}

/** 追加空的 assistant 占位消息并复位执行态，返回该消息。 */
function appendAssistantMessage(pane: ChatRuntimePane): RuntimeMessage {
  const assistantMsg: RuntimeMessage = { _id: nextMessageId(), role: 'assistant', content: '' }
  pane.messages.push(assistantMsg)
  pane.activeAssistantMessageId = assistantMsg._id || null
  ensureExecV3(assistantMsg).reset()
  resetPanePreview(pane)
  return assistantMsg
}

type ApiChatMessage = {
  role: RuntimeMessage['role']
  content: string
  images: RuntimeImageInfo[]
  documents: RuntimeDocumentInfo[]
}

function toApiChatMessage(m: RuntimeMessage): ApiChatMessage {
  return { role: m.role, content: m.content, images: m.images || [], documents: m.documents || [] }
}

/** 组装发给后端的聊天补全请求体。 */
function buildChatStreamRequest(pane: ChatRuntimePane, input: SendInput) {
  return {
    modelId: input.modelId || undefined,
    knowledgeQaEnabled: input.knowledgeQaEnabled,
    timezone: input.timezone,
    messages: pane.messages.slice(0, -1).map(toApiChatMessage),
    output_spec: {
      user_id: input.userId || undefined,
      tenant_id: input.tenantId || undefined,
      task_id: pane.sessionId || undefined,
      selected_skill_id: input.selectedSkillId || undefined,
      manual_skill_selected: Boolean(input.selectedSkillId) || undefined,
    },
  }
}

/** 流首帧带回会话 id 时，同步 model 绑定并解析 pane 归属。 */
function handleStreamSessionId(pane: ChatRuntimePane, input: SendInput, assistantMsg: RuntimeMessage, sid: string, callbacks: RuntimeCallbacks): void {
  if (input.modelId) pane.modelInstanceId = input.modelId
  assistantMsg._backendSid = sid
  resolvePaneSession(pane, sid, callbacks)
}

/** 后端流的游标与终止态，供同一轮内的恢复逻辑共享。 */
type BackendStreamState = { cursor: number; terminalReceived: boolean }

function findRuntimeMessage(pane: ChatRuntimePane, messageId: string | undefined): RuntimeMessage | undefined {
  return pane.messages.find((item) => item._id === messageId)
}

/** 应用 V3 事件，返回 store 是否真的接受了它。 */
function applyRuntimeV3Event(store: ExecutionStoreV3, ev: ExecutionEventV3): boolean {
  const before = store.state.rawEvents.length
  store.applyEvent(ev)
  return store.state.rawEvents.length > before
}

function isTerminalRunEvent(ev: ExecutionEventV3): boolean {
  return ev.type === 'run.completed' || ev.type === 'run.failed' || ev.type === 'run.cancelled'
}

/** 记录后端流的终止事件，供 EOF 后判定是否需要主动恢复。 */
function markBackendTerminal(state: BackendStreamState, ev: ExecutionEventV3, fromBackend: boolean): void {
  if (fromBackend && isTerminalRunEvent(ev)) state.terminalReceived = true
}

/** 按事件流序列号推进后端游标。 */
function advanceBackendCursor(state: BackendStreamState, ev: ExecutionEventV3): void {
  const sequence = Number(ev.stream_seq_end || ev.stream_seq || 0)
  state.cursor = sequence > 0 ? Math.max(state.cursor, sequence) : state.cursor + 1
}

/** 按浏览器接管迁移结果更新 pane 当前干预。 */
function applyInterventionTransition(pane: ChatRuntimePane, transition: BrowserInterventionTransition): void {
  if (transition.kind === 'cleared') pane.activeIntervention = null
  if (transition.kind === 'activated') pane.activeIntervention = transition.intervention
}

/** 后端流失败且无法恢复时，向本地 assistant 消息写入错误事件。 */
async function recordLocalStreamError(
  assistantMsg: RuntimeMessage,
  ctrl: AbortController,
  input: SendInput,
  error: unknown,
  recovered: boolean,
): Promise<void> {
  if (recovered || ctrl.signal.aborted) return
  const detail = error as { message?: string } | null
  const errText = String(detail?.message || error || (input.locale === 'zh' ? '请求失败' : 'Request failed'))
  const localErrorId = 'err_' + Math.random().toString(36).slice(2)
  ensureExecV3(assistantMsg).applyEvent({
    v: 3,
    event_id: localErrorId,
    id: localErrorId,
    ts: Date.now(),
    type: 'item.failed',
    item_kind: 'error',
    item_id: 'local_error',
    revision: 1,
    payload: { message: errText },
  } as ExecutionEventV3)
}

/** 复位本轮流的运行态标记（调用前需确认操作未被后续操作取代）。 */
function cleanupStreamState(pane: ChatRuntimePane): void {
  pane.activeStream = null
  pane.abortController = null
  pane.activeAssistantMessageId = null
  const authCtrl = pane.authResumeController as AbortController | null
  if (authCtrl && authCtrl.signal.aborted) pane.authResumeController = null
  setPaneRunning(pane, false)
}

/** 将 execV3 的产物、事件与证据包写回 assistant 消息。 */
function finalizeAssistantArtifacts(assistantMsg: RuntimeMessage): void {
  const artifacts = assistantMsg._execV3?.state.artifacts || []
  const docs: RuntimeDocumentInfo[] = artifacts.map((a) => ({
    type: a.kind as RuntimeDocumentInfo['type'],
    url: a.url || '',
    signed_url: a.signed_url,
    object_path: a.object_path,
    filename: a.filename,
    title: a.title,
    content_type: a.content_type,
    size: a.size,
    bundle: a.bundle,
  }))
  if (docs.length) assistantMsg.documents = docs
  assistantMsg.execution_events = assistantMsg._execV3?.state.rawEvents || undefined
  assistantMsg.evidence_bundles = assistantMsg._execV3?.state.evidenceBundles || undefined
}

type ChatTurnContext = {
  pane: ChatRuntimePane
  input: SendInput
  callbacks: RuntimeCallbacks
  assistantMsg: RuntimeMessage
  operationId: number
}

/** 执行一次完整的后端聊天流：发起、事件回流、断线恢复与浏览器接管续跑。 */
async function executeChatStreamTurn(ctx: ChatTurnContext): Promise<void> {
  const { pane, input, callbacks, assistantMsg, operationId } = ctx
  const ctrl = new AbortController()
  pane.abortController = ctrl
  const backendStream: BackendStreamState = { cursor: 0, terminalReceived: false }
  let activeHandle: ChatStreamHandle | null = null

  const applyAssistantEvent = (ev: ExecutionEventV3, options: { fromBackend?: boolean } = {}) => {
    const msg = findRuntimeMessage(pane, assistantMsg._id)
    if (!msg || !isExecutionEventV3(ev)) return
    const accepted = applyRuntimeV3Event(ensureExecV3(msg), ev)
    markBackendTerminal(backendStream, ev, Boolean(options.fromBackend))
    if (!accepted) return
    if (options.fromBackend) advanceBackendCursor(backendStream, ev)
    applyAssistantContentEvent(msg, ev)
    applyInterventionTransition(pane, browserInterventionTransition(ev))
  }

  const recoverDisconnectedStream = async (showRecoveryEvent = true): Promise<boolean> => {
    const messageId = assistantMsg.message_id || activeHandle?.messageId || ''
    if (!messageId) return false
    if (showRecoveryEvent) {
      applyAssistantEvent({
        v: 3,
        event_id: `recover_${messageId}`,
        id: `recover_${messageId}`,
        ts: Date.now(),
        type: 'item.completed',
        item_kind: 'commentary',
        item_id: `recover_${messageId}`,
        revision: 1,
        payload: {
          message: input.locale === 'zh' ? '连接中断，正在恢复进度' : 'Connection interrupted, recovering progress',
        },
      })
    }
    let after = backendStream.cursor
    while (!ctrl.signal.aborted) {
      try {
        const recovered = await fetchChatMessageEvents(messageId, after, { authToken: input.authToken })
        for (const ev of recovered.events) applyAssistantEvent(ev, { fromBackend: true })
        after = recovered.next_cursor
        backendStream.cursor = recovered.next_cursor
        if (!recovered.live && recovered.status !== 'live') return true
      } catch {
        // The recovery endpoint can be unavailable during the same network outage.
      }
      await new Promise((resolve) => setTimeout(resolve, 2000))
    }
    return false
  }

  try {
    const handle = startChatStream(
      buildChatStreamRequest(pane, input),
      (ev) => applyAssistantEvent(ev, { fromBackend: true }),
      {
        authToken: input.authToken,
        onSessionId: (sid) => handleStreamSessionId(pane, input, assistantMsg, sid, callbacks),
        onMessageId: (mid) => { assistantMsg.message_id = mid },
      },
    )
    activeHandle = handle
    pane.activeStream = handle
    ctrl.signal.addEventListener('abort', () => handle.abort())
    await handle.done
    if (!ctrl.signal.aborted && !backendStream.terminalReceived) {
      // A proxy may close a streaming response cleanly. Verify the backend run
      // reached a terminal state instead of treating EOF as task completion.
      await recoverDisconnectedStream(true)
    }
    if (pane.sessionId && input.userId && input.authToken) {
      await resumeBrowserInterventionTaskUntilSettled({
        userId: input.userId,
        sessionId: pane.sessionId,
        authToken: input.authToken,
        modelId: input.modelId || undefined,
        locale: input.locale,
        signal: ctrl.signal,
        getIntervention: () => pane.activeIntervention,
        getMessages: () => pane.messages.slice(0, -1).map(toApiChatMessage),
        setWaitController: (controller) => { pane.authResumeController = controller },
        setRunning: (running) => setPaneRunning(pane, running),
        setActiveHandle: (resumed) => {
          activeHandle = resumed
          pane.activeStream = resumed
        },
        clearIntervention: () => { pane.activeIntervention = null },
        onEvent: (ev) => applyAssistantEvent(ev, { fromBackend: true }),
        onMessageId: (mid) => {
          backendStream.cursor = 0
          backendStream.terminalReceived = false
          assistantMsg.message_id = mid
        },
      })
    }
  } catch (error: any) {
    if (error?.name !== 'AbortError') {
      const recovered = await recoverDisconnectedStream().catch(() => false)
      await recordLocalStreamError(assistantMsg, ctrl, input, error, recovered)
    }
  } finally {
    // Returning here intentionally overrides any error/value from the try block
    // only when this operation was superseded; see control-flow note above.
    // eslint-disable-next-line no-unsafe-finally -- intentional early return when operation superseded
    if (pane.operationId !== operationId) return
    // Transport completion owns the running flag. Clear it before any optional
    // refresh callback so a slow or failed sidebar/billing request can never
    // leave the composer stuck in its loading state.
    cleanupStreamState(pane)
    finalizeAssistantArtifacts(assistantMsg)
    await refreshAfterRun(callbacks, assistantMsg._backendSid || pane.sessionId)
  }
}

async function sendMessage(key: string, input: SendInput, callbacks: RuntimeCallbacks = {}) {
  const pane = findPaneByKey(key)
  if (!pane) return
  pane.authResumeController?.abort()
  pane.authResumeController = null
  if (pane.running) {
    await stopGeneration(key)
    return
  }

  const text = input.text.trim()
  if (!hasSendContent(input, text)) return
  if (!hasSendIdentity(input)) {
    callbacks.onLoginRequired?.()
    return
  }

  pane.operationId += 1
  const operationId = pane.operationId
  setPaneRunning(pane, true)
  pane.activeAuthToken = input.authToken

  if (!(await checkSendQuota(pane, operationId, input))) return

  const prepared = await prepareSendAttachments(pane, operationId, input)
  if (!prepared) return
  if (pane.operationId !== operationId) return

  pane.messages.push(buildUserMessage(text, prepared.images, prepared.documents))
  const assistantMsg = appendAssistantMessage(pane)
  await executeChatStreamTurn({ pane, input, callbacks, assistantMsg, operationId })
}

async function stopGeneration(key: string) {
  const pane = findPaneByKey(key)
  if (!pane) return false
  return await stopChatGeneration(pane, (running) => setPaneRunning(pane, running))
}

export function useChatRuntimeStore(callbacks: RuntimeCallbacks = {}) {
  const panes = computed(() => state.panes)
  const activeChatKey = computed(() => state.activeKey)
  const activeChatPane = computed(() => activePane())
  const runningSessionIds = computed(() => {
    const ids = new Set<string>()
    for (const pane of state.panes) {
      if (pane.running && pane.sessionId) ids.add(pane.sessionId)
    }
    return ids
  })
  const unreadSessionIdSet = computed(() => state.unreadSessionIds)
  const currentSessionId = computed(() => activePane()?.sessionId || null)

  function reset() {
    for (const pane of state.panes) {
      pane.activeStream?.abort()
      pane.abortController?.abort()
      pane.authResumeController?.abort()
      pane.sessionLiveHandle?.stop()
    }
    state.panes = []
    state.activeKey = ''
    state.unreadSessionIds = new Set()
  }

  function startLocalSession() {
    const pane = createPane({ sessionId: null })
    state.panes = [...state.panes, pane]
    setActivePane(pane)
    pruneInactivePanes()
    return pane
  }

  // -- P3 SSE：共享会话实时流 ---------------------------------------------
  // 本地无 himovo 的 pane-live 骨架，也不搬其 T5/T8/T9 投影；这里只在
  // 「共享参与者（access='shared'）」打开会话时叠加一条 SSE 订阅，把
  // 收到的 V3 执行事件增量应用到本地已有的 _execV3 行（幂等），控制帧
  // 触发权威刷新（重新 getSession 合并）后以 COLD_ATTACH 重新开流。

  function mergeSessionMessages(existing: RuntimeMessage[], incoming: ChatMessage[] | undefined): RuntimeMessage[] {
    if (!incoming?.length) return existing
    const byMessageId = new Map<string, RuntimeMessage>()
    for (const row of existing) {
      if (row.message_id) byMessageId.set(row.message_id, row)
    }
    const merged: RuntimeMessage[] = []
    const incomingIds = new Set<string>()
    for (const item of incoming) {
      if (item.message_id) incomingIds.add(item.message_id)
      const prev = item.message_id ? byMessageId.get(item.message_id) : undefined
      const msg = ensureMessageId({
        ...(item as RuntimeMessage),
        role: item.role === 'user' ? 'user' : 'assistant',
        content: item.content || '',
      })
      if (prev?._id) msg._id = prev._id // 复用 _id 防渲染闪烁
      if (prev?._execV3) msg._execV3 = prev._execV3 // 保留已应用执行事件
      if (prev?._provisionalTextByItem) msg._provisionalTextByItem = prev._provisionalTextByItem
      merged.push(msg)
    }
    // 保留本地乐观/未持久化行（无 message_id 或后端暂未提及），避免刷新丢行。
    const orphans = existing.filter((row) => !row.message_id || !incomingIds.has(row.message_id))
    return orphans.length ? [...merged, ...orphans] : merged
  }

  function applyLiveExecution(pane: ChatRuntimePane, event: SessionLiveExecutionEvent): void {
    const row = pane.messages.find(
      (m) => m.role === 'assistant' && m.message_id === event.message_id,
    )
    if (!row) return
    const store = ensureExecV3(row)
    const before = store.state.rawEvents.length
    store.applyEvent(event.event)
    if (store.state.rawEvents.length === before) return
    applyAssistantContentEvent(row, event.event)
  }

  async function refreshSharedSessionPane(
    pane: ChatRuntimePane,
    sessionId: string,
    userId: string,
    tenantId: string | undefined,
    authToken: string | null,
  ): Promise<void> {
    try {
      const detail = await getSession(sessionId, userId, tenantId, authToken)
      pane.messages = mergeSessionMessages(pane.messages, detail.messages)
      if (detail.runtime_preset_id) pane.runtimePresetId = detail.runtime_preset_id
      if (detail.model_instance_id !== undefined && detail.model_instance_id !== null) pane.modelInstanceId = detail.model_instance_id
      if (detail.code_project !== undefined) pane.codeProject = detail.code_project
    } catch {
      // 网络/权限失败：保留现有消息，等待下一次触发。
    }
  }

  function reopenSharedSessionLive(
    pane: ChatRuntimePane,
    sessionId: string,
    userId: string,
    tenantId: string | undefined,
    authToken: string | null,
  ): void {
    pane.sessionLiveHandle?.stop()
    pane.sessionLiveHandle = null
    startSharedSessionLive(pane, sessionId, userId, tenantId, authToken)
  }

  function startSharedSessionLive(
    pane: ChatRuntimePane,
    sessionId: string,
    userId: string,
    tenantId: string | undefined,
    authToken: string | null,
  ): void {
    pane.sessionLiveHandle?.stop()
    const handle = startSessionLiveStream({
      sessionId,
      paneKey: pane.key,
      authToken,
      onExecution: (event) => applyLiveExecution(pane, event),
      // thread.changed：控制帧，游标有 gap/溢出/非法 → 权威刷新后 COLD_ATTACH 重开。
      onThreadChanged: () => {
        void refreshSharedSessionPane(pane, sessionId, userId, tenantId, authToken)
          .then(() => reopenSharedSessionLive(pane, sessionId, userId, tenantId, authToken))
      },
      // members.changed：成员变化 → 权威刷新（列表由宿主 onSessionUpdated 刷新）。
      onMembersChanged: () => {
        void refreshSharedSessionPane(pane, sessionId, userId, tenantId, authToken)
      },
      onTurnStarted: () => {
        void refreshSharedSessionPane(pane, sessionId, userId, tenantId, authToken)
      },
      onTurnCompleted: () => {
        void refreshSharedSessionPane(pane, sessionId, userId, tenantId, authToken)
        void refreshAfterRun(callbacks, sessionId)
      },
      // session.access.revoked：终止流，通知宿主提示并退出共享会话。
      onAccessLost: (_paneKey, reason) => {
        pane.sessionLiveHandle = null
        callbacks.onSharedAccessLost?.(sessionId, reason)
      },
    })
    pane.sessionLiveHandle = handle
  }

  async function selectSession(sessionId: string, userId: string, tenantId?: string, authToken?: string | null) {
    clearUnread(sessionId)
    const existing = findPaneBySessionId(sessionId)
    if (existing) {
      setActivePane(existing)
      return existing
    }
    const detail: SessionDetail = await getSession(sessionId, userId, tenantId, authToken)
    const pane = createPane({
      key: `session_${detail.id}`,
      sessionId: detail.id,
      messages: detail.messages || [],
    })
    pane.executionLocation = detail.execution_location || 'server'
    pane.runtimePresetId = detail.runtime_preset_id || 'askai-enterprise'
    pane.modelInstanceId = detail.model_instance_id || ''
    pane.codeProject = detail.code_project || null
    state.panes = [...state.panes, pane]
    setActivePane(pane)
    pruneInactivePanes()
    // P3 SSE：共享参与者（access='shared'）打开会话即订阅实时流，owner 由
    // 本地 POST 流/恢复循环负责，不在此叠加。
    if (detail.access === 'shared' && authToken) {
      startSharedSessionLive(pane, detail.id, userId, tenantId, authToken)
    }
    if (detail.active_run?.message_id && authToken) {
      const assistant = [...pane.messages].reverse().find(
        (item) => item.role === 'assistant' && item.message_id === detail.active_run?.message_id,
      )
      if (assistant) {
        const restoredStore = ensureExecV3(assistant)
        pane.activeIntervention = normalizeBrowserIntervention(restoredStore.state.intervention)
        const controller = new AbortController()
        pane.abortController = controller
        pane.activeAssistantMessageId = assistant._id || null
        setPaneRunning(pane, true)
        void (async () => {
          const store = restoredStore
          store.resumeLive()
          let cursor = Math.max(0, ...store.state.rawEvents.map((event) => Number(event.stream_seq_end || event.stream_seq || 0)))
          try {
            try {
              while (!controller.signal.aborted) {
                const recovered = await fetchChatMessageEvents(detail.active_run!.message_id, cursor, { authToken })
                for (const event of recovered.events) {
                  if (!isExecutionEventV3(event)) continue
                  store.applyEvent(event)
                  applyAssistantContentEvent(assistant, event)
                  const transition = browserInterventionTransition(event)
                  if (transition.kind === 'cleared') pane.activeIntervention = null
                  if (transition.kind === 'activated') pane.activeIntervention = transition.intervention
                }
                cursor = recovered.next_cursor
                if (!recovered.live && recovered.status !== 'live') break
                await new Promise((resolve) => setTimeout(resolve, 2000))
              }
            } catch {
              // Sidebar polling and a future re-open provide another recovery path.
            }
            if (pane.activeIntervention) {
              await resumeBrowserInterventionTaskUntilSettled({
                userId,
                sessionId: detail.id,
                authToken,
                locale: getLocale(),
                signal: controller.signal,
                getIntervention: () => pane.activeIntervention,
                getMessages: () => pane.messages,
                setWaitController: (waitController) => { pane.authResumeController = waitController },
                setRunning: (running) => setPaneRunning(pane, running),
                setActiveHandle: (handle) => { pane.activeStream = handle },
                clearIntervention: () => { pane.activeIntervention = null },
                onEvent: (event) => {
                  store.applyEvent(event)
                  applyAssistantContentEvent(assistant, event)
                  const transition = browserInterventionTransition(event)
                  if (transition.kind === 'cleared') pane.activeIntervention = null
                  if (transition.kind === 'activated') pane.activeIntervention = transition.intervention
                },
                onMessageId: (messageId) => { assistant.message_id = messageId },
              })
            }
          } finally {
            if (pane.abortController === controller) pane.abortController = null
            pane.activeAssistantMessageId = null
            setPaneRunning(pane, false)
            await refreshAfterRun(callbacks, pane.sessionId)
          }
        })()
      }
    }
    return pane
  }

  function removeSession(sessionId: string) {
    const pane = findPaneBySessionId(sessionId)
    pane?.authResumeController?.abort()
    pane?.sessionLiveHandle?.stop()
    state.panes = state.panes.filter((item) => item.sessionId !== sessionId)
    clearUnread(sessionId)
    if (currentSessionId.value === sessionId) {
      startLocalSession()
    }
  }

  function sessionIsRunning(sessionId: string) {
    return runningSessionIds.value.has(sessionId)
  }

  function sessionIsUnread(sessionId: string) {
    return unreadSessionIdSet.value.has(sessionId)
  }

  function clearPaneIntervention(key: string) {
    const pane = findPaneByKey(key)
    if (pane) pane.activeIntervention = null
  }

  function setPanePreviewExpanded(_key: string, _expanded: boolean) {
    // Kept as an API boundary for future sidecar persistence; current expansion
    // remains local to ChatWindow because it is visual-only state.
  }

  /** Switch a pane between the conversation view and the trajectory view (028). */
  function setPaneView(key: string, view: 'chat' | 'trajectory') {
    const pane = findPaneByKey(key)
    if (pane) pane.activeView = view
  }

  /**
   * Renderer-neutral boundary for a Runtime owned by the desktop main process.
   * It deliberately reuses the authoritative message and V3 execution stores;
   * local Code must not grow a second chat/timeline implementation.
   */
  function beginExternalTurn(key: string, text: string, sessionId: string): ExternalTurnHandle {
    const pane = findPaneByKey(key)
    if (!pane) throw new Error('chat pane is unavailable')
    if (pane.running) throw new Error('chat pane already has an active turn')
    resolvePaneSession(pane, sessionId, callbacks)
    pane.executionLocation = 'desktop'
    pane.runtimePresetId = 'code'
    const user: RuntimeMessage = {
      _id: nextMessageId(), role: 'user', content: text, created_at: new Date().toISOString(),
    }
    const assistant: RuntimeMessage = { _id: nextMessageId(), role: 'assistant', content: '' }
    pane.messages.push(user, assistant)
    pane.activeAssistantMessageId = assistant._id || null
    ensureExecV3(assistant).reset()
    resetPanePreview(pane)
    setPaneRunning(pane, true)
    return {
      pane,
      assistant,
      apply(event: ExecutionEventV3) {
        if (!isExecutionEventV3(event)) return false
        const store = ensureExecV3(assistant)
        const before = store.state.rawEvents.length
        store.applyEvent(event)
        if (store.state.rawEvents.length === before) return false
        applyAssistantContentEvent(assistant, event)
        return true
      },
      finish() {
        pane.activeAssistantMessageId = null
        setPaneRunning(pane, false)
        void refreshAfterRun(callbacks, pane.sessionId)
      },
      setCodeChanges(changes: DshTaskChangeSet) {
        const target = pane.messages.find(message => message._id === assistant._id)
        if (target) target._codeChanges = changes
      },
    }
  }

  return {
    panes,
    activeChatKey,
    activeChatPane,
    currentSessionId,
    runningSessionIds,
    unreadSessionIdSet,
    reset,
    startLocalSession,
    selectSession,
    removeSession,
    sessionIsRunning,
    sessionIsUnread,
    clearUnread,
    clearPaneIntervention,
    setPanePreviewExpanded,
    setPaneView,
    beginExternalTurn,
    sendMessage: (key: string, input: SendInput) => sendMessage(key, input, callbacks),
    stopGeneration,
  }
}
