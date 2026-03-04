import { Suspense } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import PointCloud from './PointCloud'

interface ViewerCanvasProps {
  plyUrl: string | null
}

export default function ViewerCanvas({ plyUrl }: ViewerCanvasProps) {
  return (
    <Canvas camera={{ position: [3, 3, 3] }}>
      <ambientLight intensity={0.5} />
      <directionalLight position={[5, 5, 5]} />
      {plyUrl ? (
        <Suspense fallback={null}>
          <PointCloud url={plyUrl} />
        </Suspense>
      ) : (
        <mesh>
          <boxGeometry />
          <meshStandardMaterial color="royalblue" />
        </mesh>
      )}
      <gridHelper args={[10, 10]} />
      <OrbitControls />
    </Canvas>
  )
}
