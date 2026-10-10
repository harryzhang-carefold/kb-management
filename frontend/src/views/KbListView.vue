<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">知识库</h2>
      <el-button type="primary" @click="showCreateDialog = true">
        <el-icon><Plus /></el-icon> 新建知识库
      </el-button>
    </div>

    <el-table :data="kbs" v-loading="loading" stripe>
      <el-table-column prop="name" label="名称" width="200">
        <template #default="{ row }">
          <router-link :to="`/kb/${row.id}`" class="kb-link">{{ row.name }}</router-link>
        </template>
      </el-table-column>
      <el-table-column prop="description" label="描述" show-overflow-tooltip />
      <el-table-column prop="doc_count" label="文档数" width="80" align="center" />
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="goSearch(row.id)">搜索</el-button>
          <el-button size="small" type="success" @click="goChat(row.id)">问答</el-button>
          <el-button size="small" type="danger" @click="handleDelete(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-empty v-if="!loading && kbs.length === 0" description="暂无知识库，点击「新建知识库」创建" />

    <!-- Create Dialog -->
    <el-dialog v-model="showCreateDialog" title="新建知识库" width="480px">
      <el-form @submit.prevent="handleCreate">
        <el-form-item label="名称" required>
          <el-input v-model="newName" placeholder="请输入知识库名称" maxlength="100" />
        </el-form-item>
        <el-form-item label="描述">
          <el-input v-model="newDesc" type="textarea" placeholder="可选描述" :rows="3" maxlength="500" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="showCreateDialog = false">取消</el-button>
        <el-button type="primary" :loading="creating" @click="handleCreate">创建</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { listKbs, createKb, deleteKb } from '@/api'

const router = useRouter()
const kbs = ref<any[]>([])
const loading = ref(false)
const showCreateDialog = ref(false)
const creating = ref(false)
const newName = ref('')
const newDesc = ref('')

const fetchKbs = async () => {
  loading.value = true
  try {
    const data: any = await listKbs()
    kbs.value = Array.isArray(data) ? data : (data?.items || [])
  } finally {
    loading.value = false
  }
}

const handleCreate = async () => {
  if (!newName.value.trim()) {
    ElMessage.warning('请输入名称')
    return
  }
  creating.value = true
  try {
    await createKb(newName.value.trim(), newDesc.value.trim())
    ElMessage.success('创建成功')
    showCreateDialog.value = false
    newName.value = ''
    newDesc.value = ''
    await fetchKbs()
  } finally {
    creating.value = false
  }
}

const handleDelete = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确定删除知识库「${row.name}」？所有文档将被删除。`, '警告', { type: 'warning' })
    await deleteKb(row.id)
    ElMessage.success('已删除')
    await fetchKbs()
  } catch { /* cancelled */ }
}

const goSearch = (id: string) => router.push(`/kb/${id}/search`)
const goChat = (id: string) => router.push(`/kb/${id}/chat`)

onMounted(fetchKbs)
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
}
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.kb-link {
  color: #409eff;
  text-decoration: none;
}
.kb-link:hover { text-decoration: underline; }
</style>
