/** Server-side directory browsing for the pure-web client.
 *
 * The web client has no native OS directory chooser, so directory selection
 * goes through the DSH ``browse`` capability exposed by chat-api. These
 * functions wrap the ``/api/v1/directories`` endpoints.
 */

import axios from 'axios'

const client = axios.create({
  timeout: 30000,
})

export interface DirectoryEntry {
  name: string
  path: string
  hidden: boolean
}

export interface DirectoryListing {
  path: string
  home: string
  crumbs: DirectoryEntry[]
  entries: DirectoryEntry[]
  truncated: boolean
}

export interface DirectoryBrowseResponse {
  code: number
  message: string | null
  data: DirectoryListing
}

export interface DirectoryCreateResponse {
  code: number
  message: string | null
  data: { path: string }
}

export interface DirectoryError {
  code: string
  message: string
  path: string
}

function authHeaders(authToken?: string | null) {
  return authToken ? { Authorization: `Bearer ${authToken}` } : {}
}

function handleError(error: unknown): never {
  const axiosError = error as Record<string, any> | undefined
  const detail = axiosError?.response?.data?.detail
  if (detail && typeof detail === 'object') {
    const err: DirectoryError = {
      code: String(detail.code || 'directory-unreadable'),
      message: String(detail.message || 'directory operation failed'),
      path: String(detail.path || ''),
    }
    throw err
  }
  throw new Error(
    (axiosError?.response?.data?.detail as string)
    || (axiosError?.message as string)
    || 'directory operation failed',
  )
}

/**
 * List one directory level of the browsable workspace root.
 *
 * @param path absolute directory to list; absent lists the root.
 * @param authToken optional Bearer token.
 */
export async function browseDirectory(
  path: string | null,
  authToken?: string | null,
): Promise<DirectoryListing> {
  try {
    const response = await client.get<DirectoryBrowseResponse>(
      '/askai-api/api/v1/directories',
      { params: { path: path ?? null }, headers: authHeaders(authToken) },
    )
    return response.data.data
  } catch (error) {
    const axiosError = error as Record<string, any> | undefined
    if (axiosError?.response?.status === 403) {
      throw { code: 'forbidden', message: '当前岗位未开通代码生成能力', path: '' } satisfies DirectoryError
    }
    handleError(error)
  }
}

/**
 * Create one child directory under an existing parent.
 *
 * @param parentPath absolute existing parent directory.
 * @param name single non-blank path segment.
 * @param authToken optional Bearer token.
 * @returns the created directory's absolute path.
 */
export async function createDirectory(
  parentPath: string,
  name: string,
  authToken?: string | null,
): Promise<string> {
  try {
    const response = await client.post<DirectoryCreateResponse>(
      '/askai-api/api/v1/directories',
      { path: parentPath, name },
      { headers: authHeaders(authToken) },
    )
    return response.data.data.path
  } catch (error) {
    const axiosError = error as Record<string, any> | undefined
    if (axiosError?.response?.status === 403) {
      throw { code: 'forbidden', message: '当前岗位未开通代码生成能力', path: '' } satisfies DirectoryError
    }
    handleError(error)
  }
}