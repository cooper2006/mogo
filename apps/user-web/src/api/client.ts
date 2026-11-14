import axios, { type AxiosInstance, type CreateAxiosDefaults } from 'axios'
import { installAuthExpiryInterceptor } from './authExpiry'


export function createApiClient(config: CreateAxiosDefaults = {}): AxiosInstance {
  const client = axios.create(config)
  client.interceptors.request.use((request) => {
    const token = typeof window !== 'undefined' ? window.localStorage.getItem('auth_token') : ''
    if (token && !request.headers.Authorization) {
      request.headers.Authorization = `Bearer ${token}`
    }
    return request
  })
  // 401 统一走会话失效语义：装在 createApiClient 里，所有 api 模块
  // （skills / knowledge / chat / 分享收件箱…）行为一致。此前只有 api/auth.ts
  // 单独装，其余模块遇到过期 token 只会静默 401 刷 Console，既不提示也不登出。
  installAuthExpiryInterceptor(client)
  return client
}
