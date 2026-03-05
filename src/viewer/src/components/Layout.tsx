import { Link, Outlet } from 'react-router-dom'

export default function Layout() {
  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100vh' }}>
      <header
        style={{
          padding: '0.75rem 1.5rem',
          borderBottom: '1px solid #e0e0e0',
          display: 'flex',
          alignItems: 'center',
          gap: '1.5rem',
        }}
      >
        <Link to="/" style={{ textDecoration: 'none', color: 'inherit' }}>
          <h1 style={{ margin: 0, fontSize: '1.25rem' }}>EXTube 3D Viewer</h1>
        </Link>
        <nav style={{ display: 'flex', gap: '1rem', fontSize: '0.875rem' }}>
          <Link to="/" style={{ color: '#2563eb', textDecoration: 'none' }}>
            새 작업
          </Link>
          <Link to="/jobs" style={{ color: '#2563eb', textDecoration: 'none' }}>
            히스토리
          </Link>
        </nav>
      </header>
      <main style={{ flex: 1, position: 'relative' }}>
        <Outlet />
      </main>
    </div>
  )
}
