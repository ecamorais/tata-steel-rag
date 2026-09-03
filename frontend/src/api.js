// import.meta.env only exists under Vite -- optional-chained so this file
// also works when imported directly under plain Node (used to smoke-test
// this wrapper against the real backend before wiring it into any page).
const API_BASE_URL = import.meta.env?.VITE_API_BASE_URL || 'http://localhost:8000'

function extractErrorMessage(body) {
  if (!body) return 'Something went wrong.'
  const detail = body.detail
  if (typeof detail === 'string') return detail
  if (Array.isArray(detail)) {
    // FastAPI/Pydantic validation errors: [{loc, msg, type}, ...]
    return detail.map((d) => d.msg).join('; ')
  }
  if (detail && typeof detail === 'object') {
    return detail.message || JSON.stringify(detail)
  }
  return 'Something went wrong.'
}

async function request(path, { method = 'GET', token, json, formData } = {}) {
  const headers = {}
  if (token) headers.Authorization = `Bearer ${token}`

  let body
  if (formData) {
    body = formData
  } else if (json !== undefined) {
    headers['Content-Type'] = 'application/json'
    body = JSON.stringify(json)
  }

  const response = await fetch(`${API_BASE_URL}${path}`, { method, headers, body })

  let data = null
  try {
    data = await response.json()
  } catch {
    data = null
  }

  if (!response.ok) {
    throw new Error(extractErrorMessage(data))
  }
  return data
}

export function signup(username, email, password) {
  return request('/signup', { method: 'POST', json: { username, email, password } })
}

export function login(username, password) {
  return request('/login', { method: 'POST', json: { username, password } })
}

export function ask(query, token, fiscalYear) {
  const payload = { query }
  if (fiscalYear) payload.fiscal_year = fiscalYear
  return request('/ask', { method: 'POST', token, json: payload })
}

export function uploadPdf(file, token) {
  const formData = new FormData()
  formData.append('file', file)
  return request('/upload', { method: 'POST', token, formData })
}

export function getHistory(token) {
  return request('/history', { method: 'GET', token })
}
