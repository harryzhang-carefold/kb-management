<template>
  <div class="page-container">
    <div class="page-header">
      <h2 class="page-title">知识搜索 — {{ kbName }}</h2>
    </div>

    <el-card class="search-card">
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
    </el-card>

    <!-- Results -->
    <div v-if="results.length > 0" class="results">
      <div class="result-meta">
        找到 <b>{{ results.length }}</b> 条结果，耗时 <b>{{ searchTime }}</b>ms
      </div>
      <el-card v-for="(item, i) in results" :key="i" class="result-card" shadow="hover">
        <div class="result-header">
          <el-tag size="small" :type="item.match_type === 'vector' ? '' : item.match_type === 'keyword' ? 'warning' : 'success'">
            {{ item.match_type === 'vector' ? '向量' : item.match_type === 'keyword' ? '关键词' : '混合' }}
          </el-tag>
          <span class="result-score">相关度: {{ (item.score * 100).toFixed(1) }}%</span>
          <span class="result-source" v-if="item.file_name">📄 {{ item.file_name }}</span>
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
const results = ref<any[]>([])
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
  const start = Date.now()
  try {
    const data: any = await search(kbId, query.value.trim(), 10)
    results.value = data.results || []
    searchTime.value = data.took_ms || (Date.now() - start)
  } catch { /* handled */ } finally {
    searching.value = false
  }
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
