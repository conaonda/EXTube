import { useEffect, useRef } from 'react'
import { useThree, useFrame } from '@react-three/fiber'
import {
  SparkRenderer,
  SplatMesh,
} from '@sparkjsdev/spark'

interface GaussianSplatViewerProps {
  url: string
  onLoad?: (info: { pointCount: number; defaultPointSize: number }) => void
}

export default function GaussianSplatViewer({
  url,
  onLoad,
}: GaussianSplatViewerProps) {
  const { gl, scene } = useThree()
  const sparkRendererRef = useRef<SparkRenderer | null>(null)
  const splatMeshRef = useRef<SplatMesh | null>(null)

  useEffect(() => {
    const sparkRenderer = new SparkRenderer({ renderer: gl })
    sparkRendererRef.current = sparkRenderer

    const splatMesh = new SplatMesh({ url })
    splatMeshRef.current = splatMesh
    scene.add(splatMesh)

    splatMesh.initialized.then(() => {
      const numSplats = splatMesh.packedSplats?.numSplats ?? 0
      onLoad?.({
        pointCount: numSplats,
        defaultPointSize: 0.02,
      })
    }).catch((err: unknown) => {
      console.error('[GaussianSplatViewer] Load failed:', err)
    })

    return () => {
      scene.remove(splatMesh)
      splatMesh.dispose()
      // SparkRenderer has no dispose method in v0.1.x
      sparkRendererRef.current = null
      splatMeshRef.current = null
    }
  }, [url, gl, scene, onLoad])

  useFrame(() => {
    if (sparkRendererRef.current) {
      sparkRendererRef.current.update({ scene })
    }
  })

  return null
}
