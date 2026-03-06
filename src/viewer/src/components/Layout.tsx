import { Link, Outlet } from 'react-router-dom'
import { useAuth } from '../contexts/AuthContext'

export default function Layout() {
  const { user, logout } = useAuth()

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
          <Link to="/gallery" style={{ color: '#2563eb', textDecoration: 'none' }}>
            갤러리
          </Link>
        </nav>
        {user && (
          <div
            style={{
              marginLeft: 'auto',
              display: 'flex',
              alignItems: 'center',
              gap: '0.75rem',
              fontSize: '0.875rem',
            }}
          >
            <span style={{ color: '#666' }}>{user.username}</span>
            <button
              onClick={logout}
              style={{
                padding: '0.25rem 0.5rem',
                border: '1px solid #ccc',
                borderRadius: '4px',
                background: '#fff',
                cursor: 'pointer',
                fontSize: '0.8125rem',
              }}
            >
              로그아웃
            </button>
          </div>
        )}
      </header>
      <main style={{ flex: 1, position: 'relative' }}>
        <Outlet />
      </main>
    </div>
  )
}
