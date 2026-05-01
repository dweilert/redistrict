import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import './index.css'
import App from './App.tsx'

// Diagnostic: log any task that blocks the main thread for >50ms.
// Helps explain "I clicked but nothing happened for 2 seconds" — those gaps
// are when the browser was running JS instead of dispatching the click event.
if ('PerformanceObserver' in window) {
  try {
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        if (entry.duration > 50) {
          // eslint-disable-next-line no-console
          console.warn(
            `[longtask] ${entry.duration.toFixed(0)}ms at +${entry.startTime.toFixed(0)}ms`,
            (entry as unknown as { name?: string }).name ?? '',
          );
        }
      }
    });
    observer.observe({ type: 'longtask', buffered: true });
  } catch {
    /* longtask isn't supported in all browsers — fine to ignore */
  }
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <App />
  </StrictMode>,
)
