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
        { path: 'profile', name: 'Profile', component: () => import('@/views/ProfileView.vue') }
      ]
    }
  ]
})

// Auth guard
router.beforeEach((to) => {
  const store = useUserStore()
  if (to.name !== 'Login' && !store.isLoggedIn) {
    return { name: 'Login' }
  }
  if (to.name === 'Login' && store.isLoggedIn) {
    return { name: 'KbList' }
  }
})

export default router
