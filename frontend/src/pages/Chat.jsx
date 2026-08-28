import { useRef, useState } from 'react'
import { ask, uploadPdf } from '../api'
import { useAuth } from '../context/AuthContext'

export default function Chat() {
  const { token, username, logout } = useAuth()

  const [query, setQuery] = useState('')
  const [asking, setAsking] = useState(false)
  const [askError, setAskError] = useState('')
  const [answer, setAnswer] = useState(null)

  const [uploadStatus, setUploadStatus] = useState(null)
  const [uploading, setUploading] = useState(false)
  const fileInputRef = useRef(null)

  async function handleAsk(event) {
    event.preventDefault()
    if (!query.trim()) return
    setAsking(true)
    setAskError('')
    setAnswer(null)
    try {
      const result = await ask(query, token)
      setAnswer(result)
    } catch (err) {
      setAskError(err.message)
    } finally {
      setAsking(false)
    }
  }

  async function handleUpload(event) {
    event.preventDefault()
    const file = fileInputRef.current?.files?.[0]
    if (!file) return
    setUploading(true)
    setUploadStatus(null)
    try {
      const result = await uploadPdf(file, token)
      setUploadStatus({
        type: 'success',
        message: `Uploaded ${result.source_file}: ${result.chunks_added} chunk(s) added, ${result.total_chunks} total chunks in the corpus.`,
      })
      if (fileInputRef.current) fileInputRef.current.value = ''
    } catch (err) {
      setUploadStatus({ type: 'error', message: err.message })
    } finally {
      setUploading(false)
    }
  }

  return (
    <div className="min-h-screen bg-slate-50">
      <header className="flex items-center justify-between border-b border-slate-200 bg-white px-6 py-4">
        <h1 className="text-lg font-semibold text-slate-900">Tata Steel RAG</h1>
        <div className="flex items-center gap-4 text-sm text-slate-500">
          <span>{username}</span>
          <button type="button" onClick={logout} className="text-slate-900 underline">
            Log out
          </button>
        </div>
      </header>

      <main className="mx-auto flex max-w-2xl flex-col gap-8 px-4 py-8">
        <section>
          <form onSubmit={handleAsk} className="flex gap-2">
            <input
              type="text"
              value={query}
              onChange={(e) => setQuery(e.target.value)}
              placeholder="Ask a question about the annual reports..."
              className="flex-1 rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-slate-500 focus:outline-none"
            />
            <button
              type="submit"
              disabled={asking || !query.trim()}
              className="rounded-md bg-slate-900 px-4 py-2 text-sm font-medium text-white hover:bg-slate-700 disabled:opacity-50"
            >
              {asking ? 'Asking...' : 'Ask'}
            </button>
          </form>

          {askError && <p className="mt-3 text-sm text-red-600">{askError}</p>}

          {answer && (
            <div className="mt-4 rounded-lg border border-slate-200 bg-white p-4">
              <p className="whitespace-pre-wrap text-sm text-slate-800">{answer.answer}</p>
              {answer.citations.length > 0 && (
                <div className="mt-3 border-t border-slate-100 pt-3">
                  <p className="mb-1 text-xs font-medium uppercase tracking-wide text-slate-400">Sources</p>
                  <ul className="space-y-1">
                    {answer.citations.map((citation, index) => (
                      <li key={`${citation.source_file}-${citation.page_number}-${index}`} className="text-xs text-slate-500">
                        {citation.source_file}, page {citation.page_number}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          )}
        </section>

        <section className="rounded-lg border border-slate-200 bg-white p-4">
          <h2 className="mb-2 text-sm font-medium text-slate-700">Upload a new annual report (PDF)</h2>
          <form onSubmit={handleUpload} className="flex items-center gap-2">
            <input ref={fileInputRef} type="file" accept="application/pdf" className="flex-1 text-sm text-slate-600" />
            <button
              type="submit"
              disabled={uploading}
              className="rounded-md border border-slate-300 px-4 py-2 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:opacity-50"
            >
              {uploading ? 'Uploading...' : 'Upload'}
            </button>
          </form>
          {uploadStatus && (
            <p className={`mt-3 text-sm ${uploadStatus.type === 'success' ? 'text-green-600' : 'text-red-600'}`}>
              {uploadStatus.message}
            </p>
          )}
        </section>
      </main>
    </div>
  )
}
