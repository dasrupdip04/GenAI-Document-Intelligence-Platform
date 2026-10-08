import { useEffect, useState } from 'react'
import { apiRequest, uploadDocument } from './lib/api'
import { supabase } from './lib/supabase'
import './App.css'

type User = { id: string; email: string; role: string }
type DocumentItem = { id: string; filename: string; file_type: string; file_size: number; status: string }
type Conversation = { id: string; title: string; updated_at?: string }
type Citation = { id: string; document_id: string; filename: string; page_number?: number | null; relevance_score?: number }
type ChatMessage = { id: string; role: 'user' | 'assistant'; content: string; citations?: Citation[] }

function LoginPage() {
  const [error, setError] = useState('')
  const login = async () => {
    const { error } = await supabase.auth.signInWithOAuth({ provider: 'google', options: { redirectTo: window.location.origin } })
    if (error) setError(error.message)
  }
  return <main className="login"><p className="eyebrow">DOCUMENT INTELLIGENCE</p><h1>Your documents,<br />ready to answer.</h1><p>Upload your files and ask questions grounded in their contents.</p><button onClick={() => void login()}>Continue with Google</button>{error && <p className="error">{error}</p>}</main>
}

function Dashboard({ user, logout }: { user: User; logout: () => void }) {
  const [documents, setDocuments] = useState<DocumentItem[]>([])
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selected, setSelected] = useState<string | null>(null)
  const [messages, setMessages] = useState<ChatMessage[]>([])
  const [question, setQuestion] = useState('')
  const [busy, setBusy] = useState(false)
  const [notice, setNotice] = useState('')

  const refresh = async () => {
    try {
      const [docs, chats] = await Promise.all([apiRequest<DocumentItem[]>('/api/v1/documents'), apiRequest<Conversation[]>('/api/v1/conversations')])
      setDocuments(docs); setConversations(chats)
    } catch (err) { setNotice(err instanceof Error ? err.message : 'Could not load your workspace') }
  }
  useEffect(() => { void refresh() }, [])
  useEffect(() => {
    if (!selected) { setMessages([]); return }
    let alive = true
    void apiRequest<{ messages: ChatMessage[] }>(`/api/v1/conversations/${selected}`).then(data => { if (alive) setMessages(data.messages ?? []) }).catch(err => setNotice(err.message))
    return () => { alive = false }
  }, [selected])
  useEffect(() => {
    const timer = window.setInterval(() => { void refresh() }, 5000)
    return () => window.clearInterval(timer)
  }, [])

  const upload = async (event: React.ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0]; if (!file) return
    setBusy(true); setNotice('')
    try { await uploadDocument(file); await refresh() } catch (err) { setNotice(err instanceof Error ? err.message : 'Upload failed') }
    finally { setBusy(false); event.target.value = '' }
  }
  const newChat = async () => {
    try { const chat = await apiRequest<Conversation>('/api/v1/conversations', { method: 'POST', body: JSON.stringify({ title: 'New conversation' }) }); setSelected(chat.id); await refresh() }
    catch (err) { setNotice(err instanceof Error ? err.message : 'Could not create conversation') }
  }
  const send = async (event: React.FormEvent) => {
    event.preventDefault(); if (!selected || !question.trim() || busy) return
    const text = question.trim(); setQuestion(''); setBusy(true); setNotice('')
    try { const answer = await apiRequest<ChatMessage>(`/api/v1/conversations/${selected}/messages`, { method: 'POST', body: JSON.stringify({ content: text }) }); setMessages(current => [...current, { id: crypto.randomUUID(), role: 'user', content: text }, answer]); await refresh() }
    catch (err) { setQuestion(text); setNotice(err instanceof Error ? err.message : 'Question failed') }
    finally { setBusy(false) }
  }

  return <div className="app-shell"><header className="topbar"><a className="brand" href="#">Papertrail<span> AI</span></a><div className="account"><span>{user.email}</span><button className="quiet" onClick={logout}>Sign out</button></div></header>
    <div className="workspace"><aside className="sidebar"><button className="new-chat" onClick={() => void newChat()}>＋ <span>New conversation</span></button><p className="section-label">YOUR CHATS</p><nav>{conversations.map(chat => <button key={chat.id} className={`chat-link ${selected === chat.id ? 'active' : ''}`} onClick={() => setSelected(chat.id)}>{chat.title || 'Conversation'}</button>)}</nav><div className="sidebar-bottom"><p className="section-label">YOUR LIBRARY</p><label className="upload-button">{busy ? 'Working…' : '＋ Upload a document'}<input type="file" accept=".pdf,.docx,.txt" onChange={upload} disabled={busy} /></label><div className="file-list">{documents.map(doc => <div className="file-item" key={doc.id}><span className="file-icon">▤</span><span className="file-name" title={doc.filename}>{doc.filename}<small>{doc.file_type.toUpperCase()} · {doc.status}</small></span><i className={`status-dot ${doc.status.toLowerCase()}`} /></div>)}{documents.length === 0 && <p className="muted small">No documents yet.</p>}</div></div></aside>
    <main className="chat-area">{notice && <div className="notice">{notice}<button onClick={() => setNotice('')}>×</button></div>}{selected ? <><div className="conversation-head"><div><span className="eyebrow">DOCUMENT CHAT</span><h2>{conversations.find(c => c.id === selected)?.title || 'Conversation'}</h2></div></div><div className="messages">{messages.length === 0 ? <div className="empty-chat"><div className="sparkle">✳</div><h3>What would you like to know?</h3><p>Answers will be grounded in the documents in your library.</p></div> : messages.map(message => <article className={`message ${message.role}`} key={message.id}><div className="message-label">{message.role === 'user' ? 'YOU' : 'PAPERTRAIL'}</div><div className="message-content">{message.content}</div>{message.citations?.length ? <div className="citations">{message.citations.map(c => <span className="citation" key={c.id}>↗ {c.filename}{c.page_number ? ` · p. ${c.page_number}` : ''}</span>)}</div> : null}</article>)}</div><form className="composer" onSubmit={send}><textarea value={question} onChange={e => setQuestion(e.target.value)} placeholder="Ask a question about your documents…" rows={2} /><button disabled={!question.trim() || busy}>{busy ? '…' : '↑'}</button><small>AI responses may be inaccurate. Check citations against your documents.</small></form></> : <div className="welcome"><div className="welcome-mark">✳</div><span className="eyebrow">YOUR DOCUMENT WORKSPACE</span><h1>Good to see you.</h1><p>Upload a PDF, DOCX, or text file, then start a conversation to explore what’s inside.</p><label className="welcome-upload">Upload your first document<input type="file" accept=".pdf,.docx,.txt" onChange={upload} disabled={busy} /></label><span className="welcome-foot">SIGNED IN AS {user.email}</span></div>}</main></div></div>
}

export default function App() {
  const [sessionReady, setSessionReady] = useState(false)
  const [user, setUser] = useState<User | null>(null)
  useEffect(() => {
    let alive = true
    const sync = async () => {
      const { data: { session } } = await supabase.auth.getSession()
      if (!alive) return
      if (session) { try { setUser(await apiRequest<User>('/api/v1/auth/me')) } catch { setUser(null) } }
      setSessionReady(true)
    }
    void sync()
    const { data: { subscription } } = supabase.auth.onAuthStateChange((_event, session) => {
      if (!session) { setUser(null); setSessionReady(true) }
      else { window.setTimeout(() => { void apiRequest<User>('/api/v1/auth/me').then(setUser).catch(() => setUser(null)) }, 0) }
    })
    return () => { alive = false; subscription.unsubscribe() }
  }, [])
  const logout = async () => { await supabase.auth.signOut(); setUser(null) }
  if (!sessionReady) return <div className="loading">Opening your workspace…</div>
  return user ? <Dashboard user={user} logout={() => void logout()} /> : <LoginPage />
}
