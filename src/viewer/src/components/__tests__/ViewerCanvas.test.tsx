import { render, screen } from '@testing-library/react'
import { describe, expect, it, vi } from 'vitest'

vi.mock('@react-three/fiber', () => ({
  Canvas: ({ children }: { children: React.ReactNode }) => <div data-testid="canvas">{children}</div>,
  useThree: () => ({ camera: {}, gl: {}, scene: {} }),
  useFrame: () => {},
}))

vi.mock('@react-three/drei', () => ({
  OrbitControls: () => <div data-testid="orbit-controls" />,
}))

vi.mock('../PointCloud', () => ({
  default: () => <div data-testid="point-cloud" />,
}))

vi.mock('../PotreePointCloud', () => ({
  default: () => <div data-testid="potree-point-cloud" />,
}))

vi.mock('../GaussianSplatViewer', () => ({
  default: () => <div data-testid="gaussian-splat-viewer" />,
}))

vi.mock('../ViewerControls', () => ({
  default: () => <div data-testid="viewer-controls" />,
}))

import ViewerCanvas from '../ViewerCanvas'

describe('ViewerCanvas', () => {
  it('renders PointCloud when plyUrl is provided', () => {
    render(<ViewerCanvas plyUrl="/test.ply" potreeUrl={null} splatUrl={null} />)
    expect(screen.getByTestId('point-cloud')).toBeInTheDocument()
  })

  it('renders PotreePointCloud when potreeUrl is provided', () => {
    render(<ViewerCanvas plyUrl={null} potreeUrl="/test/metadata.json" splatUrl={null} />)
    expect(screen.getByTestId('potree-point-cloud')).toBeInTheDocument()
  })

  it('renders GaussianSplatViewer when splatUrl is provided', () => {
    render(<ViewerCanvas plyUrl={null} potreeUrl={null} splatUrl="/test.splat" />)
    expect(screen.getByTestId('gaussian-splat-viewer')).toBeInTheDocument()
  })

  it('renders placeholder box when no URLs provided', () => {
    render(<ViewerCanvas plyUrl={null} potreeUrl={null} splatUrl={null} />)
    expect(screen.queryByTestId('point-cloud')).not.toBeInTheDocument()
    expect(screen.queryByTestId('potree-point-cloud')).not.toBeInTheDocument()
    expect(screen.queryByTestId('gaussian-splat-viewer')).not.toBeInTheDocument()
  })
})
