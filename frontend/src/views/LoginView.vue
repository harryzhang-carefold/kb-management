<template>
  <div class="login-page">
    <div class="login-card">
      <h1 class="login-title">📚 知识库管理系统</h1>
      <p class="login-subtitle">Knowledge Base Management System</p>
      <el-form @submit.prevent="handleLogin" class="login-form">
        <el-form-item>
          <el-input
            v-model="username"
            placeholder="用户名"
            prefix-icon="User"
            size="large"
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-form-item>
          <el-input
            v-model="password"
            type="password"
            placeholder="密码"
            prefix-icon="Lock"
            size="large"
            show-password
            @keyup.enter="handleLogin"
          />
        </el-form-item>
        <el-button
          type="primary"
          size="large"
          class="login-btn"
          :loading="loading"
          @click="handleLogin"
        >
          登 录
        </el-button>
      </el-form>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useUserStore } from '@/stores/user'

const router = useRouter()
const store = useUserStore()
const username = ref('')
const password = ref('')
const loading = ref(false)

const handleLogin = async () => {
  if (!username.value || !password.value) {
    ElMessage.warning('请输入用户名和密码')
    return
  }
  loading.value = true
  try {
    await store.login(username.value, password.value)
    ElMessage.success('登录成功')
    router.push('/')
  } catch (e: any) {
    ElMessage.error(e.message || '登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  height: 100vh;
  display: flex;
  align-items: center;
  justify-content: center;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
}
.login-card {
  background: #fff;
  border-radius: 12px;
  padding: 48px 40px;
  width: 400px;
  box-shadow: 0 20px 60px rgba(0,0,0,0.15);
}
.login-title {
  text-align: center;
  font-size: 24px;
  color: #303133;
  margin-bottom: 8px;
}
.login-subtitle {
  text-align: center;
  font-size: 14px;
  color: #909399;
  margin-bottom: 32px;
}
.login-form {
  margin-top: 16px;
}
.login-btn {
  width: 100%;
  margin-top: 8px;
}
</style>
