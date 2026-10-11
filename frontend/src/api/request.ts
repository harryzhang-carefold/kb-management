import axios, { AxiosResponse } from 'axios'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/kb-management/api/v1',
  timeout: 30000
})

// 深链只读模式：DocView 在发起请求前设置；此模式下用 ?token=（view_token）
// 而非 localStorage JWT 鉴权，且 401 不跳登录、只提示（token 过期/无效）。
;(window as any).__kbTokenMode = ''

// Request interceptor: attach JWT（token 模式下改用 ?token= query 传 view_token）
api.interceptors.request.use((config) => {
  const store = useUserStore()
  const viewToken = (window as any).__kbTokenMode || ''
  if (viewToken) {
    config.params = { ...(config.params || {}), token: viewToken }
  } else if (store.token) {
    config.headers.Authorization = `Bearer ${store.token}`
  }
  return config
})

// Response interceptor: unwrap data
api.interceptors.response.use(
  (res: AxiosResponse) => {
    const data = res.data
    if (data.code !== 0) {
      ElMessage.error(data.message || '请求失败')
      return Promise.reject(new Error(data.message))
    }
    return data.data as any
  },
  (err) => {
    if (err.response?.status === 401) {
      // token 模式（深链只读）：不跳登录，仅提示 token 无效/过期
      if (!(window as any).__kbTokenMode) {
        const store = useUserStore()
        store.logout()
        window.location.href = '/kb-management/login'
      }
    }
    const msg = err.response?.data?.message || err.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

export default api
