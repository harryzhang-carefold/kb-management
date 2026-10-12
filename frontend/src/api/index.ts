import api from './request'

// Auth
export const login = (username: string, password: string) =>
  api.post('/auth/login', { username, password })

export const getProfile = () => api.get('/auth/me')

export const changePassword = (old_password: string, new_password: string) =>
  api.put('/auth/password', { old_password, new_password })

// Knowledge Bases
export const listKbs = () => api.get('/knowledge-bases')
export const createKb = (name: string, description?: string) =>
  api.post('/knowledge-bases', { name, description })
export const getKb = (id: string) => api.get(`/knowledge-bases/${id}`)
export const updateKb = (id: string, data: { name?: string; description?: string; chunk_size?: number; chunk_overlap?: number; status?: string }) =>
  api.put(`/knowledge-bases/${id}`, data)
export const deleteKb = (id: string) => api.delete(`/knowledge-bases/${id}`)

// Documents
export const listDocs = (kbId: string) => api.get(`/knowledge-bases/${kbId}/documents`)
export const uploadDoc = (kbId: string, file: File, indexType: 'embedding' | 'pageindex' = 'embedding') => {
  const fd = new FormData()
  fd.append('file', file)
  fd.append('index_type', indexType)  // v2：按文档二选一索引方式
  return api.post(`/knowledge-bases/${kbId}/documents`, fd, {
    headers: { 'Content-Type': 'multipart/form-data' },
    timeout: 120000
  })
}
export const getDoc = (kbId: string, docId: string) =>
  api.get(`/knowledge-bases/${kbId}/documents/${docId}`)
export const getDocContent = (kbId: string, docId: string) =>
  api.get(`/knowledge-bases/${kbId}/documents/${docId}/content`)
export const deleteDoc = (kbId: string, docId: string) =>
  api.delete(`/knowledge-bases/${kbId}/documents/${docId}`)
export const reparseDoc = (kbId: string, docId: string) =>
  api.post(`/knowledge-bases/${kbId}/documents/${docId}/reparse`)
// v2：文档级重建索引，按该文档 index_type 执行（pageindex → 建树 / embedding → 分块+向量）
export const reindexDoc = (kbId: string, docId: string) =>
  api.post(`/knowledge-bases/${kbId}/documents/${docId}/reindex`)
export const rebuildPageindex = (kbId: string, docId: string) =>
  api.post(`/knowledge-bases/${kbId}/documents/${docId}/pageindex/rebuild`)

// Search（mode: auto（智能，默认）/ hybrid / vector / keyword / pageindex）
export const search = (kbId: string, query: string, topK = 10, mode = 'auto') =>
  api.post(`/knowledge-bases/${kbId}/search`, { query, top_k: topK, mode })

// Chat
// retrievalMode: auto（智能，默认）/ hybrid / vector / keyword / pageindex
export const chatStream = (
  kbId: string,
  question: string,
  conversationId: string | undefined,
  onToken: (text: string) => void,
  onDone: (data: any) => void,
  onError: (err: string) => void,
  retrievalMode = 'auto'
) => {
  const store = (window as any).__userStore
  const token = store?.token || localStorage.getItem('kb_token') || ''
  const body: Record<string, unknown> = { question, retrieval_mode: retrievalMode }
  if (conversationId) body.conversation_id = conversationId

  fetch(`/kb-management/api/v1/knowledge-bases/${kbId}/chat`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${token}` },
    body: JSON.stringify(body)
  }).then((res) => {
    if (!res.ok) {
      res.text().then(t => onError(t))
      return
    }
    const reader = res.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''
    let fullText = ''
    let sources: any[] = []
    let conversationIdOut: string | null = null
    let notice: string | null = null
    const read = () => {
      reader.read().then(({ done, value }) => {
        if (done) { onDone({ full: fullText, sources, conversation_id: conversationIdOut, notice }); return }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        let currentEvent = ''
        for (const line of lines) {
          // 兼容 SSE `event:` 行 与 `data.type` 两种协议
          if (line.startsWith('event: ')) {
            currentEvent = line.slice(7).trim()
            continue
          }
          if (!line.startsWith('data: ')) continue
          const payload = line.slice(6).trim()
          try {
            const data = JSON.parse(payload)
            const type = data.type || currentEvent
            if (type === 'token' && (data.token || data.content)) {
              const t = data.token || data.content
              fullText += t
              onToken(t)
            } else if (type === 'sources') {
              sources = data.sources || []
            } else if (type === 'meta') {
              if (data.conversation_id) conversationIdOut = data.conversation_id
              // auto（智能）模式的 0 命中/降级提示（meta.notice，非 error 事件）
              if (data.notice) notice = data.notice
            } else if (type === 'done') {
              onDone({ full: fullText, sources, conversation_id: conversationIdOut, notice, ...data })
              return
            } else if (type === 'error') {
              onError(data.message || '未知错误')
              return
            }
          } catch { /* ignore parse errors */ }
        }
        read()
      })
    }
    read()
  }).catch(err => onError(err.message))
}

export const listConversations = (kbId: string) =>
  api.get(`/knowledge-bases/${kbId}/conversations`)
export const getConversation = (kbId: string, convId: string) =>
  api.get(`/knowledge-bases/${kbId}/conversations/${convId}`)
export const deleteConversation = (kbId: string, convId: string) =>
  api.delete(`/knowledge-bases/${kbId}/conversations/${convId}`)
