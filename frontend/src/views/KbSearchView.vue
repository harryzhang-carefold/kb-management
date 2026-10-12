<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">知识搜索 — {{ kbName }}</h2>
    </div>

    <el-card class="search-card">
      <div class="search-toolbar">
        <el-input
          v-model="query"
          placeholder="输入搜索关键词，例如：如何部署系统？"
          size="large"
          clearable
          @keyup.enter="doSearch"
        >
          <template #append>
            <el-button type="primary" @click="doSearch" :loading="searching">
              <el-icon><Search /></el-icon> 搜索
            </el-button>
          </template>
        </el-input>
        <el-radio-group v-model="mode" size="default" class="mode-group">
          <el-radio-button value="auto">智能（推荐）</el-radio-button>
          <el-radio-button value="hybrid">混合</el-radio-button>
          <el-radio-button value="vector">向量</el-radio-button>
          <el-radio-button value="keyword">关键词</el-radio-button>
          <el-radio-button value="pageindex">PageIndex</el-radio-button>
        </el-radio-group>
        <span class="mode-hint">智能模式：按本知识库的索引构成自动选择检索方式</span>
      </div>
    </el-card>

    <!-- auto（智能）0 命中 / 降级提示条：灰色，非红色错误弹窗（F6/F7） -->
    <div v-if="hint" class="notice-bar">{{ hint }}</div>

    <!-- Results -->
    <div v-if="results.length > 0" class="results">
      <div class="result-meta">
        找到 <b>{{ results.length }}</b> 条结果，耗时 <b>{{ searchTime }}</b>ms
      </div>
      <el-card v-for="(item, i) in results" :key="i" class="result-card" shadow="hover">
        <div class="result-header">
          <el-tag size="small" :type="matchTypeTag(item.match_type)">
            {{ matchTypeLabel(item.match_type) }}
          </el-tag>
          <span class="result-score">相关度: {{ (item.score * 100).toFixed(1) }}%</span>
          <span class="result-source" v-if="item.filename">📄 {{ item.filename }}</span>
        </div>
        <div class="result-content" v-html="highlightContent(item.content)"></div>
        <div class="result-footer" v-if="item.metadata">
          <span v-for="(val, key) in item.metadata" :key="key" class="meta-tag">
            {{ key }}: {{ val }}
          </span>
        </div>
      </el-card>
    </div>

    <el-empty v-if="searched && results.length === 0" description="未找到相关结果" />
    <el-empty v-if="!searched" description="输入关键词开始搜索" />
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage } from 'element-plus'
import { search, getKb } from '@/api'

const route = useRoute()
const kbId = route.params.id as string
const kbName = ref('')
const query = ref('')
const mode = ref<'auto' | 'hybrid' | 'vector' | 'keyword' | 'pageindex'>('auto')
const results = ref<any[]>([])
const hint = ref('')
const searching = ref(false)
const searched = ref(false)
const searchTime = ref(0)

const doSearch = async () => {
  if (!query.value.trim()) {
    ElMessage.warning('请输入搜索关键词')
    return
  }
  searching.value = true
  searched.value = true
  hint.value = ''
  const start = Date.now()
  try {
    const data: any = await search(kbId, query.value.trim(), 10, mode.value)
    results.value = data.items || data.results || []
    searchTime.value = data.took_ms || (Date.now() - start)
    if (data.message) hint.value = data.message
    if (data.error) hint.value = data.error
  } catch { /* handled */ } finally {
    searching.value = false
  }
}

const matchTypeLabel = (t: string) => {
  const map: Record<string, string> = {
    vector: '向量', keyword: '关键词', hybrid: '混合', pageindex: 'PageIndex'
  }
  return map[t] || t
}
const matchTypeTag = (t: string) => {
  const map: Record<string, string> = {
    vector: '', keyword: 'warning', hybrid: 'success', pageindex: 'danger'
  }
  return (map[t] || 'info') as any
}

const highlightContent = (content: string) => {
  if (!query.value.trim()) return content
  const words = query.value.trim().split(/\s+/).filter(w => w.length > 1)
  let html = content.replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
  for (const w of words) {
    html = html.replace(new RegExp(`(${w.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')})`, 'gi'), '<mark>$1</mark>')
  }
  return html
}

onMounted(async () => {
  try {
    const data: any = await getKb(kbId)
    kbName.value = data?.name || ''
  } catch { /* ignore */ }
})
</script>

<style scoped>
.page-header { margin-bottom: 20px; }
.page-title { margin: 0; font-size: 20px; font-weight: 600; }
.search-card { margin-bottom: 20px; }
.search-toolbar {
  display: flex;
  gap: 12px;
  align-items: center;
}
.search-toolbar .el-input { flex: 1; }
.mode-group { flex-shrink: 0; white-space: nowrap; }
.mode-hint { font-size: 12px; color: #909399; flex-shrink: 0; }
/* auto（智能）提示条：灰色提示，非红色错误弹窗 */
.notice-bar {
  margin-bottom: 16px;
  padding: 8px 12px;
  background: #f4f4f5;
  border: 1px solid #e9e9eb;
  border-radius: 4px;
  color: #909399;
  font-size: 13px;
  line-height: 1.5;
}
.result-meta {
  font-size: 14px;
  color: #909399;
  margin-bottom: 12px;
}
.result-card { margin-bottom: 12px; }
.result-header {
  display: flex;
  align-items: center;
  gap: 10px;
  margin-bottom: 8px;
}
.result-score { font-size: 13px; color: #909399; }
.result-source { font-size: 13px; color: #606266; }
.result-content {
  font-size: 14px;
  line-height: 1.8;
  color: #303133;
}
.result-content :deep(mark) {
  background: #fff3cd;
  color: #856404;
  padding: 0 2px;
  border-radius: 2px;
}
.result-footer {
  margin-top: 8px;
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.meta-tag {
  font-size: 12px;
  color: #909399;
  background: #f5f7fa;
  padding: 2px 8px;
  border-radius: 4px;
}
</style>
