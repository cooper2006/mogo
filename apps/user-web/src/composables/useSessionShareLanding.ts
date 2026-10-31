import { ref } from 'vue'
import { joinSessionShare, type SessionShareError } from '../api/sessionSharing'
import { t } from './i18n'

function captureUrlToken(parameter: string): string | null {
  if (typeof window === 'undefined') return null
  const url = new URL(window.location.href)
  const token = url.searchParams.get(parameter)
  if (!token) return null
  url.searchParams.delete(parameter)
  window.history.replaceState({}, '', `${url.pathname}${url.search}${url.hash}`)
  return token
}

function shareSessionErrorToastMessage(error: SessionShareError): string {
  switch (error.code) {
    case 'session_not_found':
    case 'session_share_not_found':
      return t('session.share.error_join_not_found')
    case 'session_share_owner_required':
    case 'session_share_participant_required':
    case 'session_share_no_binding':
    case 'session_share_not_server':
    case 'http_error':
      return t('session.share.error_generic')
    case 'session_share_inactive':
      return t('session.share.error_inactive')
    case 'session_share_token_required':
      return t('session.share.error_token_required')
    default: {
      const exhaustive: never = error.code
      void exhaustive
      return t('session.share.error_generic')
    }
  }
}

export function useSessionShareLanding(options: {
  getUserId: () => string | null
  loadSharedSessions: () => Promise<unknown>
  selectSession: (sessionId: string) => Promise<unknown>
  showError: (message: string) => void
}) {
  const pendingSessionShareToken = ref<string | null>(null)
  const pendingSnapshotToken = ref<string | null>(null)

  function captureSessionShareToken(): void {
    const token = captureUrlToken('session-share')
    if (token) pendingSessionShareToken.value = token
  }

  function captureSnapshotToken(): void {
    const token = captureUrlToken('session-snapshot')
    if (token) pendingSnapshotToken.value = token
  }

  async function joinPendingSharedSession(): Promise<void> {
    const token = pendingSessionShareToken.value
    if (!token) return
    const result = await joinSessionShare(token)
    if (result.ok === false) {
      // Keep the link through an expired session so login can retry the join.
      if (result.error.status === 401) return
      pendingSessionShareToken.value = null
      options.showError(shareSessionErrorToastMessage(result.error))
      return
    }
    pendingSessionShareToken.value = null
    if (!options.getUserId()) return
    void options.loadSharedSessions().catch(() => {})
    await options.selectSession(result.data.session_id).catch(() => {})
  }

  return {
    pendingSnapshotToken, captureSessionShareToken, captureSnapshotToken,
    joinPendingSharedSession,
  }
}
