import { useEffect, useRef, useState } from 'react'
import { apiRequest, uploadDocument } from './lib/api'
import { supabase } from './lib/supabase'
import './App.css'

type User = { id: string; email: string; role: string }
type DocumentItem = { id: string; filename: string; file_type: string; file_size: number; status: string; error_message?: string | null }
type ConversationDocument = Pick<DocumentItem, 'id' | 'filename' | 'file_type' | 'status' | 'error_message'>
type Conversation = { id: string; title: string; updated_at?: string }
type Citation = { id: string; chunk_id: string; document_id: string; filename: string; page_number?: number | null; relevance_score?: number }
type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; citations?: Citation[]; delivery?: 'sending' | 'failed' }
type ConversationDetail = Conversation & { messages: ChatMessage[]; documents: ConversationDocument[] }

let cachedApiUser: User | null = null
let cachedApiUserRequest: { userId: string; promise: Promise<User> } | null = null

function fetchApiUser(userId: string): Promise<User> {
  if (cachedApiUser?.id === userId) return Promise.resolve(cachedApiUser)
  if (cachedApiUserRequest?.userId === userId) return cachedApiUserRequest.promise
  const promise = apiRequest<User>('/api/v1/auth/me').then(user => {
    cachedApiUser = user
    return user
  })
  cachedApiUserRequest = { userId, promise }
  void promise.finally(() => {
    if (cachedApiUserRequest?.promise === promise) cachedApiUserRequest = null
  }).catch(() => undefined)
  return promise
}

function LoginPage() {
  const [error, setError] = useState('')
  const login = async () => {
    const { error } = await supabase.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } })
    if (error) setError(error.message)
  }
  return <main className="login"><p className="eyebrow">DOCUMENT INTELLIGENCE</p><h1>Your documents,<br />ready to answer.</h1><p>Upload your files and ask questions grounded in their contents.</p><button onClick={() => void login()}>Continue with Google</button>{error && <p className="error">{error}</p>}</main>
}

function AppWorkspace({ user, logout }: { user: User; logout: () => void }) {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [detail, setDetail] = useState<ConversationDetail | null>(null)
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [loading, setLoading] = useState(true)
  const [notice, setNotice] = useState('')
  const [page, setPage] = useState<'library' | 'chat'>('library')
  const fileInput = useRef<HTMLInputElement>(null)
  const sendingMessage = useRef(false)
  const libraryRequest = useRef<Promise<void> | null>(null)

  const refreshLibrary = async () => {
    if (libraryRequest.current) return libraryRequest.current
    libraryRequest.current = (async () => {
      try {
        const [docs, chats] = await Promise.all([
          apiRequest<DocumentItem[]>('/api/v1/documents'),
          apiRequest<Conversation[]>('/api/v1/conversations'),
        ])
        setDocuments(docs)
        setConversations(chats)
      } catch (err) {
        setNotice(err instanceof Error ? err.message : 'Could not load your workspace')
      } finally {
        setLoading(false)
        libraryRequest.current = null
      }
    })()
    return libraryRequest.current
  }
  const refreshChat = async (conversationId = detail?.id) => {
    if (!conversationId) return
    try { setDetail(await apiRequest<ConversationDetail>(`/api/v1/conversations/${conversationId}`)) }
    catch (err) { setNotice(err instanceof Error ? err.message : 'Could not load conversation') }
  }
  useEffect(() => { void refreshLibrary() }, [])

  const openConversation = async (id: string) => {
    setBusy(true); setNotice('')
    try { const value = await apiRequest<ConversationDetail>(`/api/v1/conversations/${id}`); setDetail(value); setPage('chat') }
    catch (err) { setNotice(err instanceof Error ? err.message : 'Could not open conversation') }
    finally { setBusy(false) }
  }
  const openDocument = async (doc: DocumentItem) => {
    if (doc.status !== 'READY') return
    setBusy(true); setNotice('')
    try {
      const chat = await apiRequest<Conversation>('/api/v1/conversations', {
        method: 'POST', body: JSON.stringify({ title: doc.filename, document_ids: [doc.id] }),
      })
      await openConversation(chat.id)
      await refreshLibrary()
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not open document chat') }
    finally { setBusy(false) }
  }
  const startFreshChat = async () => {
    if (!detail) return
    setBusy(true)
    try {
      const chat = await apiRequest<Conversation>('/api/v1/conversations', {
        method: 'POST', body: JSON.stringify({ title: 'New chat', document_ids: detail.documents.map(doc => doc.id) }),
      })
      await openConversation(chat.id)
      await refreshLibrary()
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not start a new chat') }
    finally { setBusy(false) }
  }
  const upload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]
    if (!file) return
    setBusy(true); setNotice('')
    try {
      const uploaded = await uploadDocument(file) as DocumentItem
      if (page === 'chat' && detail) {
        await apiRequest(`/api/v1/conversations/${detail.id}/documents`, {
          method: 'POST', body: JSON.stringify({ document_id: uploaded.id }),
        })
        await refreshChat(detail.id)
      }
      await refreshLibrary()
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Upload failed') }
    finally { setBusy(false); event.target.value = '' }
  }
  const detach = async (documentId: string) => {
    if (!detail) return
    try {
      await apiRequest(`/api/v1/conversations/${detail.id}/documents/${documentId}`, { method: 'DELETE' })
      await refreshChat(detail.id)
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not remove document from this chat') }
  }
  const deleteConversation = async (chat: Conversation) => {
    if (!window.confirm(`Delete “${chat.title || 'Conversation'}”? Its messages will be removed, but its documents will remain.`)) return
    try {
      await apiRequest(`/api/v1/conversations/${chat.id}`, { method: 'DELETE' })
      setConversations(current => current.filter(item => item.id !== chat.id))
      if (detail?.id === chat.id) {
        setDetail(null)
        setPage('library')
      }
    } catch (err) {
      setNotice(err instanceof Error ? err.message : 'Could not delete conversation')
    }
  }
  const send = async (event: React.FormEvent) => {
    event.preventDefault()
    if (!detail || !question.trim() || busy || sendingMessage.current) return
    sendingMessage.current = true
    const conversationId = detail.id
    const text = question.trim()
    const optimisticId = `optimistic-${crypto.randomUUID()}`
    setDetail(current => current?.id === conversationId ? {
      ...current,
      messages: [...current.messages, { id: optimisticId, role: 'user', content: text, delivery: 'sending' }],
    } : current)
    setQuestion(''); setBusy(true); setNotice('')
    try {
      const assistant = await apiRequest<ChatMessage>(`/api/v1/conversations/${conversationId}/messages`, {
        method: 'POST', body: JSON.stringify({ content: text }),
      })
      setDetail(current => current?.id === conversationId ? {
        ...current,
        messages: [...current.messages.map(message => message.id === optimisticId ? { ...message, delivery: undefined } : message), assistant],
      } : current)
    } catch (err) {
      setDetail(current => current?.id === conversationId ? {
        ...current,
        messages: current.messages.map(message => message.id === optimisticId ? { ...message, delivery: 'failed' } : message),
      } : current)
      setQuestion(text)
      setNotice(err instanceof Error ? err.message : 'Question failed')
    } finally {
      sendingMessage.current = false
      setBusy(false)
    }
  }

  return <div className="app-shell"><header className="topbar"><a className="brand" href="#" onClick={e => { e.preventDefault(); setPage('library') }}>Papertrail<span> AI</span></a><div className="account"><span>{user.email}</span><button className="quiet" onClick={logout}>Sign out</button></div></header>
    <div className="workspace"><aside className="sidebar"><button className={`chat-link ${page === 'library' ? 'active' : ''}`} onClick={() => setPage('library')}>▦ <span>Document library</span></button><p className="section-label">RECENT CHATS</p><nav>{conversations.map(chat => <div className="conversation-item" key={chat.id}><button className={`chat-link ${detail?.id === chat.id && page === 'chat' ? 'active' : ''}`} onClick={() => void openConversation(chat.id)}>{chat.title || 'Conversation'}</button><button className="conversation-delete" aria-label={`Delete ${chat.title || 'conversation'}`} onClick={() => void deleteConversation(chat)}>×</button></div>)}</nav><div className="sidebar-bottom"><p className="section-label">YOUR LIBRARY</p><div className="file-list">{documents.map(doc => <button key={doc.id} className="file-item file-button" onClick={() => void openDocument(doc)} disabled={doc.status !== 'READY'}><span className="file-icon">▤</span><span className="file-name" title={doc.filename}>{doc.filename}<small>{doc.file_type.toUpperCase()} · {doc.status}</small></span><i className={`status-dot ${doc.status.toLowerCase()}`} /></button>)}</div></div></aside>
    <main className="chat-area">{notice && <div className="notice">{notice}<button onClick={() => setNotice('')}>×</button></div>}
      {page === 'library' || !detail ? <section className="library-page"><div className="library-heading"><div><span className="eyebrow">YOUR WORKSPACE</span><h1>Document library</h1><p>Choose a ready document to start a grounded conversation.</p></div><button className="primary-action" onClick={() => fileInput.current?.click()} disabled={busy}>＋ Add Document</button><input ref={fileInput} type="file" accept=".pdf,.docx,.txt" onChange={upload} hidden /></div>
        {loading ? <p className="muted">Loading your documents…</p> : documents.length === 0 ? <div className="library-empty"><div className="welcome-mark">▤</div><h3>Your library is empty</h3><p>Add a PDF, DOCX, or text file to begin.</p><button className="primary-action" onClick={() => fileInput.current?.click()}>＋ Add Document</button></div> : <div className="document-grid">{documents.map(doc => <button className="document-card" key={doc.id} onClick={() => void openDocument(doc)} disabled={doc.status !== 'READY' || busy}><span className="document-symbol">▤</span><span className="document-name">{doc.filename}</span><span className="document-meta">{doc.file_type.toUpperCase()} · {(doc.file_size / 1024).toFixed(0)} KB</span><span className={`document-status ${doc.status.toLowerCase()}`}><i className={`status-dot ${doc.status.toLowerCase()}`} />{doc.status}</span>{doc.error_message && <span className="document-error">{doc.error_message}</span>}{doc.status === 'READY' && <span className="open-hint">Open chat →</span>}</button>)}</div>}
      </section> : <><div className="conversation-head"><div className="chat-title"><button className="quiet back-button" onClick={() => setPage('library')}>← Documents</button><h2>{detail.title}</h2></div><div className="chat-actions"><button className="quiet" onClick={() => void startFreshChat()} disabled={busy}>New chat</button><button className="primary-action compact" onClick={() => fileInput.current?.click()} disabled={busy}>＋ Add Document</button><input ref={fileInput} type="file" accept=".pdf,.docx,.txt" onChange={upload} hidden /></div></div>
        <div className="attached-documents"><span>DOCUMENTS</span>{detail.documents.map(doc => <span className={`document-chip ${doc.status.toLowerCase()}`} key={doc.id} title={doc.error_message || doc.status}>{doc.filename}<small>{doc.status}</small><button aria-label={`Remove ${doc.filename} from this chat`} onClick={() => void detach(doc.id)}>×</button></span>)}<button className="chip-add" onClick={() => fileInput.current?.click()}>＋ Add Document</button></div>
        <div className="messages">{detail.messages.length === 0 ? <div className="empty-chat"><div className="sparkle">✳</div><h3>What would you like to know?</h3><p>Answers will use the ready documents attached to this chat.</p></div> : detail.messages.map(message => <article className={`message ${message.role}`} key={message.id}><div className="message-label">{message.role === 'user' ? `YOU${message.delivery === 'sending' ? ' · SENDING' : message.delivery === 'failed' ? ' · ANSWER UNAVAILABLE' : ''}` : 'PAPERTRAIL'}</div><div className="message-content">{message.content}</div>{message.citations?.length ? <div className="citations">{message.citations.map(c => <span className="citation" key={c.id}>↗ {c.filename}{c.page_number ? ` · p. ${c.page_number}` : ''}</span>)}</div> : null}</article>)}</div>
        <form className="composer" onSubmit={send}><textarea value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask about your documents…" rows={2} /><button disabled={!question.trim() || busy || !detail.documents.some(doc => doc.status === 'READY')}>{busy ? '…' : '↑'}</button><small>{busy ? 'Working…' : 'Answers are grounded in the ready documents attached to this chat.'}</small></form></>}
    </main></div></div>
}

export default function App() {
  const [sessionReady, setSessionReady] = useState(false)
  const [user, setUser] = useState<User | null>(null)
  useEffect(() => {
    let alive = true
    const sync = async () => {
      const { data: { session } } = await supabase.auth.getSession()
      if (!alive) return
      if (session) { try { setUser(await fetchApiUser(session.user.id)) } catch { setUser(null) } }
      setSessionReady(true)
    }
    void sync()
    const { data: { subscription } } = supabase.auth.onAuthStateChange((event, session) => {
      if (event === 'SIGNED_OUT' || !session) {
        cachedApiUser = null
        cachedApiUserRequest = null
        setUser(null); setSessionReady(true)
      } else if (event === 'SIGNED_IN') {
        window.setTimeout(() => {
          void fetchApiUser(session.user.id).then(setUser).catch(() => setUser(null))
        }, 0)
      }
    })
    return () => { alive = false; subscription.unsubscribe() }
  }, [])
  const logout = async () => { await supabase.auth.signOut(); setUser(null) }
  if (!sessionReady) return <div className="loading">Opening your workspace…</div>
  return user ? <AppWorkspace user={user} logout={() => void logout()} /> : <LoginPage />
}
