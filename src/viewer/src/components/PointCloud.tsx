import { useEffect, useMemo } from 'react'
import { useLoader } from '@react-three/fiber'
import { PLYLoader } from 'three/examples/jsm/loaders/PLYLoader.js'
import * as THREE from 'three'

interface PointCloudProps {
  url: string
  pointSize?: number
  showBoundingBox?: boolean
  onLoad?: (info: { pointCount: number; defaultPointSize: number }) => void
}

export default function PointCloud({
  url,
  pointSize,
  showBoundingBox = false,
  onLoad,
}: PointCloudProps) {
  const geometry = useLoader(PLYLoader, url)

  const defaultSize = useMemo(() => {
    geometry.computeBoundingBox()
    const box = geometry.boundingBox
    if (box) {
      const size = new THREE.Vector3()
      box.getSize(size)
      return Math.max(size.x, size.y, size.z) * 0.005
    }
    return 0.02
  }, [geometry])

  useEffect(() => {
    const count = geometry.attributes.position?.count ?? 0
    onLoad?.({ pointCount: count, defaultPointSize: defaultSize })
  }, [geometry, defaultSize, onLoad])

  const hasColors = geometry.hasAttribute('color')
  const size = pointSize ?? defaultSize

  const boxHelper = useMemo(() => {
    if (!showBoundingBox || !geometry.boundingBox) return null
    const box = geometry.boundingBox
    const center = new THREE.Vector3()
    const dims = new THREE.Vector3()
    box.getCenter(center)
    box.getSize(dims)
    return { center, dims }
  }, [geometry, showBoundingBox])

  return (
    <>
      <points>
        <primitive object={geometry} attach="geometry" />
        <pointsMaterial
          size={size}
          vertexColors={hasColors}
          color={hasColors ? undefined : '#4a90d9'}
          sizeAttenuation
        />
      </points>
      {boxHelper && (
        <mesh position={boxHelper.center}>
          <boxGeometry args={[boxHelper.dims.x, boxHelper.dims.y, boxHelper.dims.z]} />
          <meshBasicMaterial color="#ffaa00" wireframe />
        </mesh>
      )}
    </>
  )
}
