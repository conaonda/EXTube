import type { ReactNode } from 'react'

export default function Layout({ children }: { children: ReactNode }) {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header
        style={{
          padding: '0.75rem 1.5rem',
          borderBottom: '1px solid #e0e0e0',
          display: 'flex',
          alignItems: 'center',
        }}
      >
        <h1 style={{ margin: 0, fontSize: '1.25rem' }}>EXTube 3D Viewer</h1>
      </header>
      <main style={{ flex: 1, position: 'relative' }}>{children}</main>
    </div>
  )
}
