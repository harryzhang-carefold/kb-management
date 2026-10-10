<template>
  <el-container class="layout">
    <el-aside width="220px" class="aside">
      <div class="logo">
        <span class="logo-icon">📚</span>
        <span class="logo-text">知识库管理</span>
      </div>
      <el-menu
        :default-active="route.path"
        router
        class="side-menu"
      >
        <el-menu-item index="/">
          <el-icon><Folder /></el-icon>
          <span>知识库列表</span>
        </el-menu-item>
        <el-menu-item index="/profile">
          <el-icon><User /></el-icon>
          <span>个人设置</span>
        </el-menu-item>
      </el-menu>
      <div class="user-info">
        <el-avatar :size="36" class="avatar">
          {{ store.displayName?.charAt(0)?.toUpperCase() || 'U' }}
        </el-avatar>
        <div class="user-meta">
          <div class="user-name">{{ store.displayName }}</div>
          <el-button text size="small" type="danger" @click="handleLogout">退出</el-button>
        </div>
      </div>
    </el-aside>
    <el-container>
      <el-header class="header">
        <div class="header-title">{{ currentTitle }}</div>
      </el-header>
      <el-main class="main">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessageBox } from 'element-plus'
import { useUserStore } from '@/stores/user'

const route = useRoute()
const router = useRouter()
const store = useUserStore()

const currentTitle = computed(() => {
  const path = route.path
  if (path === '/') return '知识库列表'
  if (path.startsWith('/kb/') && path.endsWith('/search')) return '知识搜索'
  if (path.startsWith('/kb/') && path.endsWith('/chat')) return '智能问答'
  if (path.startsWith('/kb/')) return '知识库详情'
  if (path === '/profile') return '个人设置'
  return '知识库管理'
})

const handleLogout = async () => {
  try {
    await ElMessageBox.confirm('确定退出登录？', '提示', { type: 'warning' })
    store.logout()
    router.push('/login')
  } catch { /* cancelled */ }
}
</script>

<style scoped>
.layout {
  height: 100vh;
}
.aside {
  background: #fff;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
}
.logo {
  padding: 20px 16px;
  font-size: 18px;
  font-weight: 700;
  color: #303133;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  gap: 8px;
}
.logo-icon { font-size: 24px; }
.side-menu {
  border-right: none;
  flex: 1;
}
.user-info {
  padding: 16px;
  border-top: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
  gap: 10px;
}
.user-meta {
  flex: 1;
  display: flex;
  flex-direction: column;
}
.user-name {
  font-size: 13px;
  font-weight: 500;
  color: #303133;
}
.header {
  background: #fff;
  border-bottom: 1px solid #e4e7ed;
  display: flex;
  align-items: center;
}
.header-title {
  font-size: 16px;
  font-weight: 600;
  color: #303133;
}
.main {
  background: #f5f7fa;
  overflow-y: auto;
}
</style>
