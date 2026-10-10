import axios, { AxiosResponse } from 'axios'
import { useUserStore } from '@/stores/user'
import { ElMessage } from 'element-plus'

const api = axios.create({
  baseURL: '/kb-management/api/v1',
  timeout: 30000
})

// Request interceptor: attach JWT
api.interceptors.request.use((config) => {
  const store = useUserStore()
  if (store.token) {
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
      const store = useUserStore()
      store.logout()
      window.location.href = '/kb-management/login'
    }
    const msg = err.response?.data?.message || err.message || '网络错误'
    ElMessage.error(msg)
    return Promise.reject(err)
  }
)

export default api
