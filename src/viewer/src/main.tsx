import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter, Route, Routes } from 'react-router-dom'
import App from './App.tsx'
import Layout from './components/Layout.tsx'
import GalleryPage from './components/GalleryPage.tsx'
import JobHistory from './components/JobHistory.tsx'
import LoginPage from './components/LoginPage.tsx'
import ProtectedRoute from './components/ProtectedRoute.tsx'
import { AuthProvider } from './contexts/AuthContext.tsx'
import { ToastProvider } from './components/Toast.tsx'

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <BrowserRouter>
      <AuthProvider>
        <ToastProvider>
          <Routes>
            <Route element={<Layout />}>
              <Route path="/login" element={<LoginPage />} />
              <Route path="/gallery" element={<GalleryPage />} />
              <Route element={<ProtectedRoute />}>
                <Route path="/" element={<App />} />
                <Route path="/jobs" element={<JobHistory />} />
                <Route path="/jobs/:jobId" element={<App />} />
              </Route>
            </Route>
          </Routes>
        </ToastProvider>
      </AuthProvider>
    </BrowserRouter>
  </StrictMode>,
)
