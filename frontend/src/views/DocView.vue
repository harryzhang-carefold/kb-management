<template>
  <div class="page-container doc-view">
    <!-- 头部 -->
    <div class="page-header">
      <div>
        <h2 class="page-title">
          <el-icon class="page-title-icon"><Document /></el-icon>
          {{ doc?.filename || '文档' }}
        </h2>
        <div class="page-desc" v-if="doc?.file_type">
          <el-tag size="small" type="info">{{ doc.file_type }}</el-tag>
          <el-tag size="small" type="success" v-if="doc?.chunk_count">{{ doc.chunk_count }} 分块</el-tag>
          <el-tag size="small" type="warning" v-if="piStatusLabel">{{ piStatusLabel }}</el-tag>
          <span v-if="doc?.file_size" class="file-size">{{ formatSize(doc.file_size) }}</span>
        </div>
      </div>
      <div class="header-actions">
        <!-- 深链只读模式：隐藏写入口（上传/重解析/重建索引/删除） -->
        <el-button v-if="!isTokenMode" size="small" @click="router.push(`/kb/${kbId}`)">
          <el-icon><Back /></el-icon> 返回知识库
        </el-button>
        <el-button size="small" @click="openInNewTab">
          <el-icon><Link /></el-icon> 在新窗口打开
        </el-button>
      </div>
    </div>

    <!-- 定位失败提示条 -->
    <el-alert
      v-if="locateNotice"
      :title="locateNotice"
      type="warning"
      :closable="false"
      show-icon
      class="locate-notice"
    />

    <!-- token 无效/过期提示条（深链只读模式） -->
    <el-alert
      v-if="tokenNotice"
      :title="tokenNotice"
      type="error"
      :closable="false"
      show-icon
      class="locate-notice"
    />

    <!-- 原文内嵌区（三态） -->
    <el-card class="embed-card" v-loading="loading" :body-style="{ padding: '0' }">
      <!-- ① PDF → iframe（hash 锚点在加载后经 contentWindow 追加，避免随 URL 发给服务端） -->
      <iframe
        v-if="isPdf && fileUrl"
        :src="fileUrl"
        @load="onPdfLoaded"
        class="pdf-embed"
        title="PDF 预览"
      />

      <!-- ② 图片 → img 直显 -->
      <div v-else-if="isImage && fileUrl" class="image-embed-wrap">
        <img :src="fileUrl" class="image-embed" :alt="doc?.filename" />
      </div>

      <!-- ③ 其他 → 文本视图 -->
      <div v-else-if="fullText" class="text-embed-wrap">
        <!-- 节点定位：全文中按 char 区间高亮 -->
        <div v-if="nodeRange" class="text-embed" ref="fullTextRef">
          <span
            v-for="(seg, i) in textSegments"
            :key="i"
            :class="{ 'text-highlight': seg.highlight }"
          >{{ seg.text }}</span>
        </div>
        <!-- 无节点定位：纯全文 -->
        <pre v-else class="text-embed" ref="fullTextRef">{{ fullText }}</pre>
      </div>

      <!-- 文档尚未解析 -->
      <el-empty
        v-else-if="!loading"
        :description="emptyDesc"
        class="empty-inline"
      />
    </el-card>

    <!-- 分块列表（?chunk=N 定位模式） -->
    <div v-if="chunks.length" class="chunks-section">
      <div class="chunks-header">
        <h3 class="chunks-title">
          <el-icon><List /></el-icon> 分块列表
        </h3>
        <el-tag size="small" type="info">共 {{ chunks.length }} 块</el-tag>
        <el-tag v-if="targetChunkIndex !== null" size="small" type="success">
          定位 → Chunk #{{ targetChunkIndex }}
        </el-tag>
      </div>
      <div class="chunks-list">
        <div
          v-for="c in chunks"
          :key="c.chunk_index"
          :id="`chunk-${c.chunk_index}`"
          :class="['chunk-item', { 'chunk-highlight': highlightedChunk === c.chunk_index }]"
        >
          <div class="chunk-header">
            <el-tag size="small" type="info">Chunk #{{ c.chunk_index }}</el-tag>
            <span class="chunk-meta">{{ c.token_count }} tokens</span>
          </div>
          <pre class="chunk-content">{{ c.content }}</pre>
        </div>
      </div>
    </div>

    <!-- 分块加载中 -->
    <div v-if="loadingChunks" class="chunks-loading">
      <el-icon class="is-loading"><Loading /></el-icon>
      <span>正在加载全部分块…</span>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, computed, onMounted, nextTick } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { getDoc, getDocContent } from '@/api'
import api from '@/api/request'

const route = useRoute()
const router = useRouter()

const kbId = route.params.id as string
const docId = route.params.docId as string

// ---- 只读 token 模式（?token=）----
const viewToken = (route.query.token as string) || ''
const isTokenMode = computed(() => !!viewToken)

// 在发起任何 API 请求前设置 token 模式
onMounted(() => {
  if (viewToken) {
    ;(window as any).__kbTokenMode = viewToken
  }
  init()
})

// ---- 状态 ----
const loading = ref(true)
const doc = ref<any>(null)
const fullText = ref('')
const docMeta = ref<Record<string, any>>({})
const fileUrl = ref('')

// 分块
const loadingChunks = ref(false)
const chunks = ref<any[]>([])
const targetChunkIndex = ref<number | null>(null)
const highlightedChunk = ref<number | null>(null)

// 节点定位
const nodeRange = ref<{ start: number; end: number; title: string } | null>(null)

// 定位失败提示
const locateNotice = ref('')

// token 无效/过期提示（深链只读模式）
const tokenNotice = ref('')

// refs
const fullTextRef = ref<HTMLElement | null>(null)

// ---- 计算属性 ----
const isPdf = computed(() => doc.value?.file_type === 'pdf')

const IMAGE_TYPES = ['jpg', 'jpeg', 'png', 'webp', 'tiff', 'bmp']
const isImage = computed(() => IMAGE_TYPES.includes((doc.value?.file_type || '').toLowerCase()))

const piStatusLabel = computed(() => {
  const s = doc.value?.meta?.pageindex_status
  if (!s || s === 'none') return ''
  const map: Record<string, string> = {
    building: '建树中', ok: 'PageIndex 树索引', degraded: '降级树', failed: '建树失败'
  }
  return map[s] || s
})

const emptyDesc = computed(() => {
  if (doc.value?.status === 'parsing' || doc.value?.status === 'uploaded') {
    return '文档正在解析中，请稍候…'
  }
  if (doc.value?.status === 'failed') {
    return `解析失败：${doc.value?.error_message || '未知错误'}`
  }
  return '文档尚未解析完成，暂无原文内容'
})

// 文本分段（节点定位高亮）
const textSegments = computed(() => {
  if (!nodeRange.value || !fullText.value) return []
  const { start, end } = nodeRange.value
  const segs: { text: string; highlight: boolean }[] = []
  if (start > 0) {
    segs.push({ text: fullText.value.slice(0, start), highlight: false })
  }
  if (end > start) {
    segs.push({ text: fullText.value.slice(start, end), highlight: true })
  }
  if (end < fullText.value.length) {
    segs.push({ text: fullText.value.slice(end), highlight: false })
  }
  return segs
})

// 文件内嵌 URL（download 端点 + ?token=）
const buildFileUrl = () => {
  const base = `/kb-management/api/v1/knowledge-bases/${kbId}/documents/${docId}/download`
  if (viewToken) {
    fileUrl.value = `${base}?token=${viewToken}`
  }
  // 非 token 模式：不设置 fileUrl（浏览器 iframe/img 无法带 Authorization 头）
}

// PDF 加载后注入 #page=1 锚点（同源时生效；跨域时静默忽略）
const onPdfLoaded = (e: Event) => {
  const frame = e.target as HTMLIFrameElement
  try {
    const win = frame.contentWindow
    if (win) win.location.hash = '#page=1'
  } catch {
    /* 跨域 PDF 内嵌时无法访问 contentWindow，忽略 */
  }
}

// ---- 初始化 ----
const init = async () => {
  try {
    await Promise.all([fetchDoc(), fetchContent()])
    buildFileUrl()
  } catch (e: any) {
    const status = e?.response?.status
    if (isTokenMode.value && (status === 401 || status === 403)) {
      tokenNotice.value = '链接中的 token 无效或已过期，无法查看该文档（请重新从引用深链打开）'
      return
    }
    ElMessage.error(e.message || '加载文档失败')
  } finally {
    loading.value = false
  }

  // 定位
  const chunkParam = route.query.chunk as string | undefined
  const nodeParam = route.query.node as string | undefined

  if (chunkParam !== undefined) {
    targetChunkIndex.value = parseInt(chunkParam, 10) || 0
    await locateChunk()
  } else if (nodeParam) {
    await locateNode(nodeParam)
  }
}

const fetchDoc = async () => {
  const data: any = await getDoc(kbId, docId)
  doc.value = data?.document || data
}

const fetchContent = async () => {
  try {
    const data: any = await getDocContent(kbId, docId)
    fullText.value = data?.content || ''
    docMeta.value = data?.meta || {}
  } catch {
    // 文档可能尚未解析完，不阻断主流程
  }
}

// ---- 分块定位 ----
const locateChunk = async () => {
  if (targetChunkIndex.value === null) return
  loadingChunks.value = true
  try {
    await fetchAllChunks()
    // 目标 chunk 存在？
    const target = chunks.value.find(c => c.chunk_index === targetChunkIndex.value)
    if (!target) {
      locateNotice.value = `未找到 Chunk #${targetChunkIndex.value}（文档可能尚未完成分块或分块已重建）`
      return
    }
    await nextTick()
    scrollToChunk(targetChunkIndex.value!)
  } catch (e: any) {
    locateNotice.value = `加载分块失败：${e.message || e}`
  } finally {
    loadingChunks.value = false
  }
}

const fetchAllChunks = async () => {
  const all: any[] = []
  let page = 1
  const pageSize = 100
  while (true) {
    const data: any = await api.get(
      `/knowledge-bases/${kbId}/documents/${docId}/chunks`,
      { params: { page, page_size: pageSize } }
    )
    const items = data?.items || []
    all.push(...items)
    const total = data?.total || 0
    if (all.length >= total || items.length < pageSize) break
    page++
    // 安全上限：最多 50 页
    if (page > 50) break
  }
  chunks.value = all
}

const scrollToChunk = (chunkIndex: number) => {
  const el = document.getElementById(`chunk-${chunkIndex}`)
  if (el) {
    el.scrollIntoView({ behavior: 'smooth', block: 'center' })
    highlightedChunk.value = chunkIndex
    // 3 秒后取消高亮
    setTimeout(() => {
      if (highlightedChunk.value === chunkIndex) {
        highlightedChunk.value = null
      }
    }, 3000)
  }
}

// ---- 节点定位 ----
const locateNode = async (nodeId: string) => {
  // 从 content 的 meta 里取 pageindex_tree
  const tree = docMeta.value?.pageindex_tree
  if (!tree?.root) {
    locateNotice.value = `未找到 PageIndex 树索引（文档可能尚未建树或索引方式为 Embedding），无法定位节点 ${nodeId}`
    return
  }
  const node = findNodeInTree(tree.root, nodeId)
  if (!node) {
    locateNotice.value = `节点 ${nodeId} 在 PageIndex 树中未找到（树可能已重建）`
    return
  }
  const start = node.start ?? 0
  const end = node.end ?? 0
  if (start >= end) {
    locateNotice.value = `节点 ${nodeId} 的字符区间无效（start=${start}, end=${end}）`
    return
  }
  nodeRange.value = { start, end, title: node.title || '' }

  // 滚动到高亮区域（定位 span 直接 scrollIntoView，兼容分段渲染）
  await nextTick()
  const hl = document.querySelector<HTMLElement>('.text-highlight')
  if (hl) {
    hl.scrollIntoView({ behavior: 'smooth', block: 'center' })
  } else if (fullTextRef.value) {
    fullTextRef.value.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }
}

const findNodeInTree = (node: any, targetId: string): any | null => {
  if (node.node_id === targetId) return node
  // 前缀匹配：targetId 是某节点的前缀时取最长匹配
  let best: any = null
  const walk = (n: any) => {
    if (n.node_id === targetId) { best = n; return }
    if (targetId.startsWith(n.node_id) && n.node_id.length > (best?.node_id?.length || 0)) {
      best = n
    }
    for (const c of n.children || []) walk(c)
  }
  walk(node)
  return best
}

// ---- 工具 ----
const formatSize = (bytes: number) => {
  if (!bytes) return ''
  if (bytes < 1024) return bytes + ' B'
  if (bytes < 1048576) return (bytes / 1024).toFixed(1) + ' KB'
  return (bytes / 1048576).toFixed(1) + ' MB'
}

const openInNewTab = () => {
  const url = window.location.href
  window.open(url, '_blank')
}
</script>

<style scoped>
.doc-view {
  min-height: 100vh;
}

.page-header {
  display: flex;
  justify-content: space-between;
  align-items: flex-start;
  margin-bottom: 16px;
}

.page-title {
  font-size: 1.25rem;
  font-weight: 600;
  display: flex;
  align-items: center;
  gap: 8px;
  margin: 0;
}

.page-title-icon {
  font-size: 1.1rem;
  color: var(--el-color-primary);
}

.page-desc {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-top: 6px;
  flex-wrap: wrap;
}

.file-size {
  font-size: 0.8rem;
  color: #909399;
}

.header-actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}

.locate-notice {
  margin-bottom: 12px;
}

/* ---- 原文内嵌 ---- */
.embed-card {
  margin-bottom: 20px;
  overflow: hidden;
}

.pdf-embed {
  width: 100%;
  height: 70vh;
  border: none;
  display: block;
}

.image-embed-wrap {
  display: flex;
  justify-content: center;
  align-items: flex-start;
  padding: 16px;
  background: #f5f7fa;
  overflow: auto;
  max-height: 70vh;
}

.image-embed {
  max-width: 100%;
  max-height: 68vh;
  object-fit: contain;
}

.text-embed-wrap {
  padding: 16px;
  max-height: 70vh;
  overflow: auto;
}

.text-embed {
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace;
  font-size: 0.85rem;
  line-height: 1.7;
  color: #303133;
  min-height: 200px;
}

.text-highlight {
  background-color: #fef08a;
  border-radius: 2px;
  padding: 1px 0;
  transition: background-color 0.5s ease;
}

.empty-inline {
  padding: 40px 0;
}

/* ---- 分块列表 ---- */
.chunks-section {
  margin-bottom: 20px;
}

.chunks-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 12px;
}

.chunks-title {
  font-size: 1rem;
  font-weight: 600;
  margin: 0;
  display: flex;
  align-items: center;
  gap: 6px;
}

.chunks-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.chunk-item {
  border: 1px solid #e4e7ed;
  border-radius: 6px;
  overflow: hidden;
  transition: border-color 0.3s, box-shadow 0.3s;
}

.chunk-item.chunk-highlight {
  border-color: var(--el-color-success);
  box-shadow: 0 0 0 2px rgba(103, 194, 58, 0.25);
}

.chunk-header {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 8px 12px;
  background: #f5f7fa;
  border-bottom: 1px solid #e4e7ed;
}

.chunk-meta {
  font-size: 0.75rem;
  color: #909399;
}

.chunk-content {
  margin: 0;
  padding: 10px 12px;
  white-space: pre-wrap;
  word-break: break-word;
  font-family: 'SFMono-Regular', Consolas, Menlo, monospace;
  font-size: 0.8rem;
  line-height: 1.6;
  color: #303133;
  max-height: 200px;
  overflow-y: auto;
}

.chunks-loading {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 16px;
  color: #909399;
  font-size: 0.9rem;
}
</style>
