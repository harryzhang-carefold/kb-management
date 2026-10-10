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
export const updateKb = (id: string, data: { name?: string; description?: string }) =>
  api.put(`/knowledge-bases/${id}`, data)
export const deleteKb = (id: string) => api.delete(`/knowledge-bases/${id}`)

// Documents
export const listDocs = (kbId: string) => api.get(`/knowledge-bases/${kbId}/documents`)
export const uploadDoc = (kbId: string, file: File) => {
  const fd = new FormData()
  fd.append('file', file)
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

// Search
export const search = (kbId: string, query: string, topK = 10) =>
  api.post(`/knowledge-bases/${kbId}/search`, { query, top_k: topK })

// Chat
export const chatStream = (
  kbId: string,
  question: string,
  conversationId: string | undefined,
  onToken: (text: string) => void,
  onDone: (data: any) => void,
  onError: (err: string) => void
) => {
  const store = (window as any).__userStore
  const token = store?.token || localStorage.getItem('kb_token') || ''
  const body: Record<string, unknown> = { question }
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
    const read = () => {
      reader.read().then(({ done, value }) => {
        if (done) { onDone(fullText); return }
        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''
        for (const line of lines) {
          if (line.startsWith('data: ')) {
            const payload = line.slice(6).trim()
            try {
              const data = JSON.parse(payload)
              if (data.type === 'token' && data.content) {
                fullText += data.content
                onToken(data.content)
              } else if (data.type === 'done') {
                onDone(data)
              } else if (data.type === 'error') {
                onError(data.message)
              }
            } catch { /* ignore parse errors */ }
          }
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
