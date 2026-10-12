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

    <!-- Upload（v2：上传时按文档二选一索引方式） -->
    <el-card class="upload-card">
      <div class="upload-options">
        <span class="upload-options-label">索引方式：</span>
        <el-radio-group v-model="indexType">
          <el-radio-button value="embedding">Embedding（分块+向量）</el-radio-button>
          <el-radio-button value="pageindex">PageIndex（树索引）</el-radio-button>
        </el-radio-group>
        <span class="upload-options-desc" v-if="indexType === 'pageindex'">
          无向量、基于层级树 + LLM 推理检索；上传后异步建树（约 30-120s），一个文档只建一种索引。
        </span>
        <span class="upload-options-desc" v-else>
          现有行为：解析 → 分块 → 向量索引（Embedding + ES 混合/向量/关键词检索）。
        </span>
      </div>
      <el-upload
        drag
        :action="uploadUrl"
        :headers="uploadHeaders"
        :data="uploadData"
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
      <el-table-column label="索引方式" width="120" align="center">
        <template #default="{ row }">
          <el-tag size="small" :type="(row.meta?.index_type || 'embedding') === 'pageindex' ? 'danger' : ''">
            {{ (row.meta?.index_type || 'embedding') === 'pageindex' ? 'PageIndex' : 'Embedding' }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column label="PageIndex" width="90" align="center">
        <template #default="{ row }">
          <el-tag v-if="piStatus(row)" size="small" :type="piTagType(row)">{{ piStatus(row) }}</el-tag>
          <span v-else class="pi-none">-</span>
        </template>
      </el-table-column>
      <el-table-column label="状态" width="100" align="center">
        <template #default="{ row }">
          <el-tag :type="statusType(row.status)" size="small">{{ statusLabel(row.status) }}</el-tag>
        </template>
      </el-table-column>
      <el-table-column label="上传时间" width="160">
        <template #default="{ row }">{{ formatTime(row.uploaded_at) }}</template>
      </el-table-column>
      <el-table-column label="操作" width="260" align="center">
        <template #default="{ row }">
          <el-button size="small" @click="handleViewContent(row)" :disabled="row.status === 'parsing' || row.status === 'chunking' || row.status === 'uploaded'">查看</el-button>
          <el-button size="small" @click="handleReparse(row)" :disabled="row.status === 'parsing' || row.status === 'chunking'">重新解析</el-button>
          <el-button size="small" type="warning" @click="handleReindex(row)" :disabled="row.status === 'parsing' || row.status === 'chunking' || row.status === 'uploaded'">重建索引</el-button>
          <el-button size="small" type="danger" @click="handleDeleteDoc(row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>

    <!-- Auto-refresh for processing docs -->
    <div v-if="processingHint" class="processing-hint">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span v-if="hasPiBuilding">有文档正在构建 PageIndex 树索引，</span>有文档正在处理中，自动刷新中...
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
import { getKb, listDocs, deleteDoc, reparseDoc, getDocContent, reindexDoc } from '@/api'
import { useUserStore } from '@/stores/user'
import { marked } from 'marked'

const route = useRoute()
const router = useRouter()
const store = useUserStore()
const kbId = route.params.id as string

const kb = ref<any>(null)
const docs = ref<any[]>([])
const loading = ref(false)
// v2：上传时按文档二选一索引方式（默认 pageindex；显式选 embedding 时走原分块+向量行为）
const indexType = ref<'embedding' | 'pageindex'>('pageindex')
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
// v2：随 multipart 表单附带 index_type（el-upload 的 data 选项 → 表单字段）
const uploadData = computed(() => ({ index_type: indexType.value }))

const hasProcessing = computed(() =>
  docs.value.some(d => d.status === 'parsing' || d.status === 'chunking' || d.status === 'uploading')
)
const processingHint = computed(() =>
  hasProcessing.value || hasPiBuilding.value
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
    if (processingHint.value) {
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

// ---------- PageIndex / 重建索引（v2：按文档 index_type 执行） ----------
const piStatus = (row: any): string => {
  const s = row.meta?.pageindex_status
  if (!s || s === 'none') return ''
  const label: Record<string, string> = {
    building: '建树中', ok: '已建树', degraded: '降级树', failed: '建树失败'
  }
  return label[s] || s
}
const piTagType = (row: any): any => {
  const map: Record<string, string> = {
    building: 'warning', ok: 'success', degraded: 'info', failed: 'danger'
  }
  return map[row.meta?.pageindex_status] || 'info'
}

const handleReindex = async (row: any) => {
  const it = row.meta?.index_type || 'embedding'
  const label = it === 'pageindex' ? 'PageIndex 树索引（LLM 建树约 30-120s）' : 'Embedding 分块+向量索引'
  try {
    await ElMessageBox.confirm(`确定按「${label}」重建「${row.filename}」的索引？`, '确认', { type: 'warning' })
    await reindexDoc(kbId, row.id)
    ElMessage.success('已提交重建索引任务')
    fetchDocs()
  } catch { /* cancelled */ }
}

const hasPiBuilding = computed(() =>
  docs.value.some(d => d.meta?.pageindex_status === 'building')
)

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
  if (processingHint.value) startPolling()
})

onUnmounted(stopPolling)

watch(processingHint, (val) => {
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
.pi-none { color: #c0c4cc; }
.upload-card { margin-bottom: 20px; }
.upload-options {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-wrap: wrap;
  margin-bottom: 14px;
}
.upload-options-label { font-size: 14px; font-weight: 600; }
.upload-options-desc { font-size: 12px; color: #909399; }
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
