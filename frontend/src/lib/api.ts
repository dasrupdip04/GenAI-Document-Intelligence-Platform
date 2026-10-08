const API_URL = import.meta.env.VITE_API_URL || 'http://localhost:8000'
import { supabase } from './supabase'

export async function apiRequest<T>(path: string, options: RequestInit = {}): Promise<T> {
  const session = await supabase.auth.getSession()
  const token = (await session.data.session)?.access_token

  const response = await fetch(`${API_URL}${path}`, {
    ...options,
    headers: {
      ...(options.body instanceof FormData ? {} : { 'Content-Type': 'application/json' }),
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
      ...(options.headers || {}),
    },
  })

  if (!response.ok) {
    const errorBody = await response.text()
    throw new Error(errorBody || 'API request failed')
  }

  if (response.status === 204) {
    return undefined as T
  }

  return response.json() as Promise<T>
}

export async function uploadDocument(file: File) {
  const session = await supabase.auth.getSession()
  const token = (await session.data.session)?.access_token

  const formData = new FormData()
  formData.append('file', file)

  const response = await fetch(`${API_URL}/api/v1/documents`, {
    method: 'POST',
    headers: token ? { Authorization: `Bearer ${token}` } : {},
    body: formData,
  })

  if (!response.ok) {
    const errorBody = await response.text()
    throw new Error(errorBody || 'Upload failed')
  }

  return response.json()
}
