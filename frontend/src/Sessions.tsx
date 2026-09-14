import { useRef, useState } from 'react'

export default function SessionsPage({ focus }: { focus: string | null }) {
  const iframeRef = useRef<HTMLIFrameElement | null>(null)
  const [loading, setLoading] = useState(true)
  const [reloadKey, setReloadKey] = useState(0)

  // Construct initial URL — deep link to session if focus provided
  const targetPath = focus ? `/c/${encodeURIComponent(focus)}` : ''
  const iframeSrc = `/omnigent-app${targetPath}`

  const handleRefresh = () => {
    setLoading(true)
    setReloadKey((k) => k + 1)
  }

  const handleOpenExternal = () => {
    window.open(iframeSrc, '_blank', 'noopener,noreferrer')
  }

  return (
    <div className="omn-embed-container">
      {/* Top Bar for Omnigent Integration */}
      <div className="omn-embed-topbar">
        <div className="omn-embed-brand">
          <span className="omn-pulse-dot" />
          <strong>Omnigent Client</strong>
          <span className="chip muted">Official Frontend Engine</span>
          {focus && (
            <span className="chip ok" title={`Focused on session: ${focus}`}>
              Session: <code>{focus.slice(0, 12)}…</code>
            </span>
          )}
        </div>

        <div className="omn-embed-actions">
          <button className="ghost" onClick={handleRefresh} title="Reload Omnigent Interface">
            ⟳ Refresh
          </button>
          <button className="ghost" onClick={handleOpenExternal} title="Open Omnigent in full window">
            Open in New Tab ↗
          </button>
        </div>
      </div>

      {/* Loading Overlay */}
      {loading && (
        <div className="omn-embed-loading">
          <div className="omn-pulse-dot" style={{ width: 14, height: 14 }} />
          <span>Connecting to Omnigent Server…</span>
        </div>
      )}

      {/* Official Omnigent Frontend App Frame */}
      <iframe
        key={`${iframeSrc}-${reloadKey}`}
        ref={iframeRef}
        src={iframeSrc}
        title="Omnigent Official App"
        className="omn-embed-frame"
        onLoad={() => setLoading(false)}
        allow="clipboard-read; clipboard-write; microphone; camera"
      />
    </div>
  )
}