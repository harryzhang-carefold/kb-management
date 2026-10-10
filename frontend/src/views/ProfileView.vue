<template>
  <div class="page-container">
    <h2 class="page-title">个人设置</h2>

    <el-card class="profile-card">
      <template #header><span>账户信息</span></template>
      <el-descriptions :column="2" border>
        <el-descriptions-item label="用户名">{{ store.username }}</el-descriptions-item>
        <el-descriptions-item label="显示名">{{ store.displayName }}</el-descriptions-item>
        <el-descriptions-item label="角色">
          <el-tag>{{ store.role }}</el-tag>
        </el-descriptions-item>
      </el-descriptions>
    </el-card>

    <el-card class="pwd-card">
      <template #header><span>修改密码</span></template>
      <el-form label-width="100px" style="max-width: 480px">
        <el-form-item label="当前密码">
          <el-input v-model="oldPwd" type="password" show-password />
        </el-form-item>
        <el-form-item label="新密码">
          <el-input v-model="newPwd" type="password" show-password />
        </el-form-item>
        <el-form-item label="确认新密码">
          <el-input v-model="confirmPwd" type="password" show-password />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="changing" @click="handleChangePwd">修改密码</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { ElMessage } from 'element-plus'
import { changePassword } from '@/api'
import { useUserStore } from '@/stores/user'

const store = useUserStore()
const oldPwd = ref('')
const newPwd = ref('')
const confirmPwd = ref('')
const changing = ref(false)

const handleChangePwd = async () => {
  if (!oldPwd.value || !newPwd.value) {
    ElMessage.warning('请填写完整')
    return
  }
  if (newPwd.value !== confirmPwd.value) {
    ElMessage.warning('两次密码不一致')
    return
  }
  if (newPwd.value.length < 6) {
    ElMessage.warning('新密码至少 6 位')
    return
  }
  changing.value = true
  try {
    await changePassword(oldPwd.value, newPwd.value)
    ElMessage.success('密码修改成功')
    oldPwd.value = ''
    newPwd.value = ''
    confirmPwd.value = ''
  } catch { /* handled */ } finally {
    changing.value = false
  }
}
</script>

<style scoped>
.page-title { margin-bottom: 20px; }
.profile-card, .pwd-card { margin-bottom: 20px; }
</style>
