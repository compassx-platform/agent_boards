import { useCallback } from 'react'
import { renderMarkdown } from '../lib/markdown'

/**
 * Markdown bubble, matching the Omnigent chat surface: GFM-rendered and
 * sanitized, with a Copy button on each fenced code block.
 */
export default function Md({ text, className }: { text: string; className?: string }) {
  const ref = useCallback((node: HTMLDivElement | null) => {
    if (!node) return
    for (const pre of Array.from(node.querySelectorAll('pre'))) {
      if (pre.querySelector('.md-copy')) continue
      const btn = document.createElement('button')
      btn.type = 'button'
      btn.className = 'md-copy'
      btn.textContent = 'Copy'
      btn.onclick = () => {
        const code = pre.querySelector('code')
        const text = code?.textContent ?? pre.textContent ?? ''
        void navigator.clipboard?.writeText(text).catch(() => undefined)
        btn.textContent = 'Copied!'
        setTimeout(() => {
          btn.textContent = 'Copy'
        }, 1500)
      }
      pre.appendChild(btn)
    }
  }, [])

  return (
    <div
      ref={ref}
      className={className ?? 'md-content'}
      dangerouslySetInnerHTML={{ __html: renderMarkdown(text) }}
    />
  )
}