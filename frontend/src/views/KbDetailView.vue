<template>
  <div class="page-container">
    <div class="page-header">
      <div>
        <h2 class="page-title">{{ kb?.name }}</h2>
        <p class="page-desc" v-if="kb?.description">{{ kb.description }}</p>
      </div>
      <div>
        <el-button @click="router.push(`/kb/${kbId}/search`)">
          <el-icon><Search /></el-icon> 搜索
        </el-button>
        <el-button type="success" @click="router.push(`/kb/${kbId}/chat`)">
          <el-icon><ChatDotRound /></el-icon> 问答
        </el-button>
      </div>
    </div>

    <!-- Upload -->
    <el-card class="upload-card">
      <el-upload
        drag
        :action="uploadUrl"
        :headers="uploadHeaders"
        :show-file-list="false"
        :before-upload="beforeUpload"
        :on-success="onUploadSuccess"
        :on-error="onUploadError"
        accept=".txt,.md,.html,.htm,.docx,.pdf,.pptx,.xlsx,.jpg,.jpeg,.png,.bmp,.webp,.tiff"
      >
        <el-icon class="el-icon--upload"><UploadFilled /></el-icon>
        <div class="el-upload__text">拖拽文件到此处，或 <em>点击上传</em></div>
        <div class="el-upload__tip">支持 .txt .md .html .docx .pdf .pptx .xlsx .jpg .png .bmp .webp .tiff 格式</div>
      </el-upload>
    </el-card>

    <!-- Document List -->
    <el-table :data="docs" v-loading="loading" stripe>
      <el-table-column prop="filename" label="文件名" width="220" show-overflow-tooltip />
      <el-table-column prop="file_type" label="类型" width="70" align="center" />
      <el-table-column label="大小" width="90" align="center">
        <template #default="{ row }">{{ formatSize(row.file_size) }}</template>
      </el-table-column>
      <el-table-column prop="chunk_count" label="分块数" width="80" align="center" />
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="160">
        <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="200" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="handleViewContent(row)" :disabled="row.status === 'parsing' || row.status === 'chunking' || row.status === 'uploaded'">查看</el-button>
          <el-button size="small" @click="handleReparse(row)" :disabled="row.status === 'parsing' || row.status === 'chunking'">重新解析</el-button>
          <el-button size="small" type="danger" @click="handleDeleteDoc(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Auto-refresh for processing docs -->
    <div v-if="hasProcessing" class="processing-hint">
      <el-icon class="is-loading"><Loading /></el-icon>
      有文档正在处理中，自动刷新中...
    </div>

    <!-- 原文查看弹窗 -->
    <el-dialog v-model="contentVisible" :title="`📄 ${contentData.filename || ''}`" width="70%" top="5vh" destroy-on-close>
      <div class="doc-content-meta" v-if="contentData.file_type">
        <el-tag size="small" type="info">{{ contentData.file_type }}</el-tag>
        <el-tag size="small" type="success" v-if="contentData.chunk_count">{{ contentData.chunk_count }} 个分块</el-tag>
        <el-tag size="small" type="warning" v-if="contentData.meta?.parse_engine">{{ contentData.meta.parse_engine }}</el-tag>
        <el-tag size="small" type="info" v-if="contentData.meta?.page_count">{{ contentData.meta.page_count }} 页</el-tag>
        <el-radio-group v-model="contentMode" size="small" style="margin-left:auto">
          <el-radio-button value="rendered">渲染</el-radio-button>
          <el-radio-button value="raw">原文</el-radio-button>
        </el-radio-group>
      </div>
      <div class="doc-content-body" v-loading="contentLoading">
        <div v-if="contentMode === 'rendered'" class="doc-content-rendered" v-html="renderedContent"></div>
        <pre v-else class="doc-content-text">{{ contentData.content || '加载中...' }}</pre>
      </div>
    </el-dialog>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { getKb, listDocs, deleteDoc, reparseDoc, getDocContent } from '@/api'
import { useUserStore } from '@/stores/user'
import { marked } from 'marked'

const route = useRoute()
const router = useRouter()
const store = useUserStore()
const kbId = route.params.id as string

const kb = ref<any>(null)
const docs = ref<any[]>([])
const loading = ref(false)
let pollTimer: ReturnType<typeof setInterval> | null = null

// 原文查看
const contentVisible = ref(false)
const contentLoading = ref(false)
const contentMode = ref<'rendered' | 'raw'>('rendered')
const contentData = ref<any>({ filename: '', file_type: '', content: '', chunk_count: 0, meta: {} })

const renderedContent = computed(() => {
  const c = contentData.value.content || ''
  if (!c) return ''
  return marked.parse(c)
})

const handleViewContent = async (row: any) => {
  contentVisible.value = true
  contentLoading.value = true
  contentData.value = { filename: row.filename, file_type: row.file_type, content: '', chunk_count: row.chunk_count }
  try {
    const data: any = await getDocContent(kbId, row.id)
    contentData.value = data
  } catch (e: any) {
    contentData.value.content = `加载失败: ${e.message || e}`
  } finally {
    contentLoading.value = false
  }
}

const uploadUrl = computed(() => `/kb-management/api/v1/knowledge-bases/${kbId}/documents`)
const uploadHeaders = computed(() => ({
  Authorization: `Bearer ${store.token}`
}))

const hasProcessing = computed(() =>
  docs.value.some(d => d.status === 'parsing' || d.status === 'chunking' || d.status === 'uploading')
)

const fetchKb = async () => {
  try { kb.value = await getKb(kbId) } catch { /* ignore */ }
}

const fetchDocs = async () => {
  loading.value = true
  try {
    const data: any = await listDocs(kbId)
    docs.value = Array.isArray(data) ? data : (data?.items || [])
  } finally {
    loading.value = false
  }
}

const startPolling = () => {
  stopPolling()
  pollTimer = setInterval(() => {
    if (hasProcessing.value) {
      fetchDocs()
    } else {
      stopPolling()
    }
  }, 3000)
}

const stopPolling = () => {
  if (pollTimer) { clearInterval(pollTimer); pollTimer = null }
}

const beforeUpload = (file: File) => {
  const validExts = ['.txt', '.md', '.html', '.htm', '.docx', '.pdf', '.pptx', '.xlsx',
    '.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff']
  const ext = '.' + (file.name.split('.').pop() || '').toLowerCase()
  if (!validExts.includes(ext)) {
    ElMessage.error(`不支持的文件格式: ${ext}`)
    return false
  }
  // 按类型大小上限（与后端一致）
  const mb = file.size / 1024 / 1024
  let limit = 10
  if (ext === '.pdf') limit = 15
  else if (['.docx', '.pptx', '.xlsx'].includes(ext)) limit = 20
  else if (['.jpg', '.jpeg', '.png', '.bmp', '.webp', '.tiff'].includes(ext)) limit = 20
  if (mb > limit) {
    ElMessage.error(`文件过大（${ext} 上限 ${limit}MB）`)
    return false
  }
  return true
}

const onUploadSuccess = (res: any) => {
  if (res.code === 0) {
    ElMessage.success('上传成功，正在处理...')
    fetchDocs()
    startPolling()
  }
}

const onUploadError = (_err: any) => {
  ElMessage.error('上传失败')
}

const handleReparse = async (row: any) => {
  try {
    await reparseDoc(kbId, row.id)
    ElMessage.success('已重新提交解析')
    fetchDocs()
    startPolling()
  } catch { /* handled by interceptor */ }
}

const handleDeleteDoc = async (row: any) => {
  try {
    await ElMessageBox.confirm(`确定删除文档「${row.filename}」？`, '确认', { type: 'warning' })
    await deleteDoc(kbId, row.id)
    ElMessage.success('已删除')
    fetchDocs()
  } catch { /* cancelled */ }
}

const formatSize = (bytes: number) => {
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

const formatTime = (t: string) => t ? new Date(t).toLocaleString('zh-CN') : '-'

const statusType = (s: string) => {
  const map: Record<string, string> = {
    uploaded: 'info', parsing: 'warning', chunking: 'warning',
    indexed: 'success', failed: 'danger', uploading: 'warning'
  }
  return (map[s] || 'info') as any
}

const statusLabel = (s: string) => {
  const map: Record<string, string> = {
    uploaded: '已上传', parsing: '解析中', chunking: '分块中',
    indexed: '已索引', failed: '失败', uploading: '上传中'
  }
  return map[s] || s
}

onMounted(async () => {
  await fetchKb()
  await fetchDocs()
  if (hasProcessing.value) startPolling()
})

onUnmounted(stopPolling)

watch(hasProcessing, (val) => {
  if (val) startPolling()
  else stopPolling()
})
</script>

<style scoped>
.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 20px;
}
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.page-desc { color: #909399; font-size: 14px; margin-top: 4px; }
.upload-card { margin-bottom: 20px; }
.processing-hint {
  margin-top: 12px;
  color: #e6a23c;
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 14px;
}
.doc-content-meta {
  display: flex;
  gap: 8px;
  margin-bottom: 12px;
}
.doc-content-body {
  max-height: 65vh;
  overflow-y: auto;
  border: 1px solid #ebeef5;
  border-radius: 6px;
  padding: 16px;
  background: #fafafa;
}
.doc-content-text {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'JetBrains Mono', 'Fira Code', 'Consolas', monospace;
  font-size: 13px;
  line-height: 1.7;
  color: #303133;
  margin: 0;
}
.doc-content-rendered {
  font-size: 14px;
  line-height: 1.7;
  color: #303133;
}
.doc-content-rendered :deep(table) {
  border-collapse: collapse;
  margin: 12px 0;
  width: 100%;
  font-size: 13px;
}
.doc-content-rendered :deep(th),
.doc-content-rendered :deep(td) {
  border: 1px solid #dcdfe6;
  padding: 6px 10px;
  text-align: left;
}
.doc-content-rendered :deep(th) {
  background: #f5f7fa;
}
</style>
