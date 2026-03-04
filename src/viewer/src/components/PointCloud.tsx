import { useMemo } from 'react'
import { useLoader } from '@react-three/fiber'
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js'
import * as THREE from 'three'

interface PointCloudProps {
  url: string
}

export default function PointCloud({ url }: PointCloudProps) {
  const geometry = useLoader(PLYLoader, url)

  const pointSize = useMemo(() => {
    geometry.computeBoundingBox()
    const box = geometry.boundingBox
    if (box) {
      const size = new THREE.Vector3()
      box.getSize(size)
      const maxDim = Math.max(size.x, size.y, size.z)
      return maxDim * 0.005
    }
    return 0.02
  }, [geometry])

  const hasColors = geometry.hasAttribute('color')

  return (
    <points>
      <primitive object={geometry} attach="geometry" />
      <pointsMaterial
        size={pointSize}
        vertexColors={hasColors}
        color={hasColors ? undefined : '#4a90d9'}
        sizeAttenuation
      />
    </points>
  )
}
