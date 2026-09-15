import { useEffect } from 'react'
import { useNavigate, useLocation } from 'react-router-dom'
import OmnigentApp from '../App'
import { RoutingProvider, basenamedRouting } from '../lib/routing'

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
}: {
  focus: string | null
  isDarkMode?: boolean
}) {
  return (
    <div className="flex-1 w-full h-full min-h-0 relative overflow-hidden bg-background text-foreground flex flex-col">
      <SessionFocusSync focus={focus} />
      <RoutingProvider value={basenamedRouting('/sessions')}>
        <OmnigentApp basename="/sessions" />
      </RoutingProvider>
    </div>
  )
}