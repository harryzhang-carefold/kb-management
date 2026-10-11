<template>
  <div class="page-container chat-page">
    <div class="chat-layout">
      <!-- Sidebar: conversations -->
      <div class="chat-sidebar">
        <el-button class="new-chat-btn" @click="newConversation">
          <el-icon><Plus /></el-icon> 新对话
        </el-button>
        <div class="conv-list">
          <div
            v-for="conv in conversations"
            :key="conv.id"
            class="conv-item"
            :class="{ active: conv.id === currentConvId }"
            @click="selectConversation(conv)"
          >
            <div class="conv-title">{{ conv.title || '新对话' }}</div>
            <div class="conv-meta">{{ conv.message_count }} 条消息</div>
            <el-icon class="conv-delete" @click.stop="handleDeleteConv(conv)"><Delete /></el-icon>
          </div>
        </div>
      </div>

      <!-- Chat area -->
      <div class="chat-main">
        <div class="messages" ref="messagesRef">
          <div v-if="messages.length === 0" class="empty-chat">
            <div class="empty-icon">💬</div>
            <p>开始提问，AI 将基于知识库内容回答</p>
          </div>
          <div v-for="(msg, i) in messages" :key="i" class="message" :class="msg.role">
            <div class="msg-avatar">
              <el-avatar :size="32">{{ msg.role === 'user' ? '我' : 'AI' }}</el-avatar>
            </div>
            <div class="msg-body">
              <div class="msg-text" v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)"></div>
              <div class="msg-text" v-else>{{ msg.content }}</div>
              <div class="msg-sources" v-if="msg.sources && msg.sources.length">
                <span class="sources-label">参考来源:</span>
                <el-tag v-for="(src, si) in msg.sources" :key="si" size="small" class="source-tag">
                  {{ (src as any).filename || `片段 ${(si as number) + 1}` }}
                </el-tag>
              </div>
            </div>
          </div>
          <div v-if="streaming" class="message assistant">
            <div class="msg-avatar"><el-avatar :size="32">AI</el-avatar></div>
            <div class="msg-body">
              <div class="msg-text streaming-text" v-html="renderMarkdown(streamText)"></div>
              <span class="cursor-blink">|</span>
            </div>
          </div>
        </div>

        <!-- Input -->
        <div class="chat-input">
          <el-input
            v-model="question"
            type="textarea"
            :rows="3"
            placeholder="输入问题，Enter 发送，Shift+Enter 换行"
            @keydown.enter.exact.prevent="sendQuestion"
          />
          <div class="input-right">
            <el-radio-group v-model="retrievalMode" size="small" class="mode-group">
              <el-radio-button value="hybrid">混合</el-radio-button>
              <el-radio-button value="vector">向量</el-radio-button>
              <el-radio-button value="keyword">关键词</el-radio-button>
              <el-radio-button value="pageindex">PageIndex</el-radio-button>
            </el-radio-group>
            <el-button
              type="primary"
              class="send-btn"
              :disabled="!question.trim() || streaming"
              :loading="streaming"
              @click="sendQuestion"
            >
              <el-icon><Promotion /></el-icon> 发送
            </el-button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, nextTick, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { ElMessage, ElMessageBox } from 'element-plus'
import { chatStream, listConversations, getConversation, deleteConversation as apiDeleteConv } from '@/api'
import { marked } from 'marked'

const route = useRoute()
const kbId = route.params.id as string

const messages = ref<any[]>([])
const conversations = ref<any[]>([])
const currentConvId = ref<string | null>(null)
const question = ref('')
const streaming = ref(false)
const streamText = ref('')
const retrievalMode = ref<'hybrid' | 'vector' | 'keyword' | 'pageindex'>('hybrid')
const messagesRef = ref<HTMLElement | null>(null)

const renderMarkdown = (text: string): string => {
  try {
    return marked.parse(text || '') as string
  } catch {
    return text
  }
}

const scrollToBottom = () => {
  nextTick(() => {
    if (messagesRef.value) {
      messagesRef.value.scrollTop = messagesRef.value.scrollHeight
    }
  })
}

const newConversation = () => {
  currentConvId.value = null
  messages.value = []
}

const selectConversation = async (conv: any) => {
  currentConvId.value = conv.id
  try {
    const data: any = await getConversation(kbId, conv.id)
    messages.value = (data.messages || []).map((m: any) => ({
      role: m.role === 'user' ? 'user' : 'assistant',
      content: m.content,
      sources: m.sources || []
    }))
    scrollToBottom()
  } catch { /* ignore */ }
}

const handleDeleteConv = async (conv: any) => {
  try {
    await ElMessageBox.confirm('确定删除此对话？', '确认', { type: 'warning' })
    await apiDeleteConv(kbId, conv.id)
    if (currentConvId.value === conv.id) newConversation()
    await fetchConversations()
    ElMessage.success('已删除')
  } catch { /* cancelled */ }
}

const sendQuestion = () => {
  const q = question.value.trim()
  if (!q || streaming.value) return

  messages.value.push({ role: 'user', content: q })
  question.value = ''
  streaming.value = true
  streamText.value = ''
  scrollToBottom()

  let fullText = ''
  let sources: any[] = []

  chatStream(
    kbId,
    q,
    currentConvId.value ?? undefined,
    (token: string) => {
      fullText += token
      streamText.value = fullText
      scrollToBottom()
    },
    (data: any) => {
      streaming.value = false
      sources = data.sources || sources
      if (data.conversation_id) currentConvId.value = data.conversation_id
      messages.value.push({
        role: 'assistant',
        content: fullText || (data.full || data.answer || ''),
        sources
      })
      streamText.value = ''
      scrollToBottom()
      fetchConversations()
    },
    (err: string) => {
      streaming.value = false
      streamText.value = ''
      ElMessage.error(err || '请求失败')
    },
    retrievalMode.value
  )
}

const fetchConversations = async () => {
  try {
    const data: any = await listConversations(kbId)
    conversations.value = Array.isArray(data) ? data : (data?.items || [])
  } catch { /* ignore */ }
}

onMounted(fetchConversations)
</script>

<style scoped>
.chat-page {
  height: calc(100vh - 120px);
  display: flex;
  flex-direction: column;
}
.chat-layout {
  display: flex;
  flex: 1;
  min-height: 0;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}
.chat-sidebar {
  width: 240px;
  border-right: 1px solid #e4e7ed;
  display: flex;
  flex-direction: column;
}
.new-chat-btn { margin: 12px; }
.conv-list { flex: 1; overflow-y: auto; }
.conv-item {
  padding: 10px 12px;
  cursor: pointer;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  align-items: center;
  gap: 8px;
}
.conv-item:hover { background: #f5f7fa; }
.conv-item.active { background: #ecf5ff; }
.conv-title {
  flex: 1;
  font-size: 13px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.conv-meta { font-size: 11px; color: #c0c4cc; }
.conv-delete { opacity: 0; cursor: pointer; color: #f56c6c; }
.conv-item:hover .conv-delete { opacity: 1; }

.chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.messages {
  flex: 1;
  overflow-y: auto;
  padding: 20px;
}
.empty-chat {
  text-align: center;
  color: #c0c4cc;
  padding-top: 100px;
}
.empty-icon { font-size: 48px; margin-bottom: 12px; }

.message {
  display: flex;
  gap: 10px;
  margin-bottom: 16px;
}
.message.user { flex-direction: row-reverse; }
.msg-avatar { flex-shrink: 0; }
.msg-body {
  max-width: 70%;
  background: #f5f7fa;
  border-radius: 8px;
  padding: 12px 16px;
}
.message.user .msg-body { background: #ecf5ff; }
.msg-text {
  font-size: 14px;
  line-height: 1.7;
  word-break: break-word;
}
.msg-text :deep(p) { margin: 0 0 8px; }
.msg-text :deep(ul), .msg-text :deep(ol) { margin: 0 0 8px 20px; }
.msg-text :deep(code) { background: #e8e8e8; padding: 2px 4px; border-radius: 3px; font-size: 13px; }
.msg-text :deep(pre) { background: #2d2d2d; color: #f8f8f2; padding: 12px; border-radius: 6px; overflow-x: auto; margin: 8px 0; }
.msg-sources {
  margin-top: 8px;
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}
.sources-label { font-size: 12px; color: #909399; }
.source-tag { font-size: 11px; }
.streaming-text { min-height: 20px; }
.cursor-blink {
  animation: blink 1s infinite;
  color: #409eff;
  font-weight: bold;
}
@keyframes blink { 0%,50% { opacity: 1; } 51%,100% { opacity: 0; } }

.chat-input {
  padding: 12px 20px;
  border-top: 1px solid #e4e7ed;
  display: flex;
  gap: 10px;
  align-items: flex-end;
}
.input-right {
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 8px;
  flex-shrink: 0;
}
.mode-group { white-space: nowrap; }
.send-btn { height: 60px; }
</style>
