import { createRouter, createWebHistory } from 'vue-router'
import { useUserStore } from '@/stores/user'

const router = createRouter({
  history: createWebHistory('/kb-management/'),
  routes: [
    { path: '/login', name: 'Login', component: () => import('@/views/LoginView.vue') },
    {
      path: '/',
      component: () => import('@/views/LayoutView.vue'),
      children: [
        { path: '', name: 'KbList', component: () => import('@/views/KbListView.vue') },
        { path: 'kb/:id', name: 'KbDetail', component: () => import('@/views/KbDetailView.vue') },
        { path: 'kb/:id/search', name: 'KbSearch', component: () => import('@/views/KbSearchView.vue') },
        { path: 'kb/:id/chat', name: 'KbChat', component: () => import('@/views/KbChatView.vue') },
        // 深链查看页（A3）：?chunk=N / ?node=n1.2.3 定位高亮，?token= 只读 view_token 鉴权
        { path: 'kb/:id/doc/:docId', name: 'KbDoc', component: () => import('@/views/DocView.vue') },
        { path: 'profile', name: 'Profile', component: () => import('@/views/ProfileView.vue') }
      ]
    }
  ]
})

// Auth guard
router.beforeEach((to) => {
  const store = useUserStore()
  // 深链查看页：带 ?token=（view_token 只读鉴权）时无需登录即可放行（A3）
  if (to.name === 'KbDoc' && to.query.token) {
    return true
  }
  if (to.name !== 'Login' && !store.isLoggedIn) {
    return { name: 'Login' }
  }
  if (to.name === 'Login' && store.isLoggedIn) {
    return { name: 'KbList' }
  }
})

export default router
