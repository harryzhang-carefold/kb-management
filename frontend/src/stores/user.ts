import { defineStore } from 'pinia'
import { login as apiLogin, getProfile } from '@/api'

interface UserState {
  token: string
  username: string
  displayName: string
  role: string
}

export const useUserStore = defineStore('user', {
  state: (): UserState => ({
    token: localStorage.getItem('kb_token') || '',
    username: '',
    displayName: '',
    role: ''
  }),
  getters: {
    isLoggedIn: (s) => !!s.token
  },
  actions: {
    async login(username: string, password: string) {
      const data: any = await apiLogin(username, password)
      this.token = data.access_token
      this.username = data.user.username
      this.displayName = data.user.display_name || data.user.username
      this.role = data.user.role
      localStorage.setItem('kb_token', this.token)
      ;(window as any).__userStore = this
    },
    async fetchProfile() {
      const data: any = await getProfile()
      this.username = data.username
      this.displayName = data.display_name || data.username
      this.role = data.role
    },
    logout() {
      this.token = ''
      this.username = ''
      this.displayName = ''
      this.role = ''
      localStorage.removeItem('kb_token')
    }
  }
})
