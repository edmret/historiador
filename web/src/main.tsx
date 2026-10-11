import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'

import './index.css'

const container = document.getElementById('root')

if (!container) {
  throw new Error('Mount failed: #root is missing from index.html')
}

/*
 * Placeholder shell. The router and the real views (run view, graph view, event
 * stream, kanban, command palette) are owned by other workstreams.
 *
 * The markup is inlined rather than extracted into a component on purpose: an
 * entry module that declares a component but exports nothing breaks Fast Refresh
 * (`react-refresh/only-export-components`). Replace the <main> element below
 * with the router root — a one-line swap; nothing else in this file changes.
 */
createRoot(container).render(
  <StrictMode>
    <main className="flex h-full items-center justify-center p-8">
      <p className="text-sm tracking-wide opacity-60">
        Historiador dashboard — shell mounted, awaiting router.
      </p>
    </main>
  </StrictMode>,
)
