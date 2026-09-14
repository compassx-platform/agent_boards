import { useEffect } from 'react'
import { BrowserRouter, useNavigate, useLocation } from 'react-router-dom'
import { OmnigentApp } from './omnigent/embed'
import './omnigent/index.css'
import 'katex/dist/katex.min.css'
import 'streamdown/styles.css'

function SessionFocusSync({ focus }: { focus: string | null }) {
  const navigate = useNavigate()
  const location = useLocation()

  useEffect(() => {
    if (focus && focus !== 'c') {
      const target = `/sessions/c/${encodeURIComponent(focus)}`
      if (location.pathname !== target) {
        navigate(target, { replace: true })
      }
    }
  }, [focus, navigate, location.pathname])

  return null
}

export default function SessionsPage({
  focus,
  isDarkMode = false,
}: {
  focus: string | null
  isDarkMode?: boolean
}) {
  return (
    <div className="omn-embed-container">
      <SessionFocusSync focus={focus} />
      <OmnigentApp basename="/sessions" isDarkMode={isDarkMode} />
    </div>
  )
}