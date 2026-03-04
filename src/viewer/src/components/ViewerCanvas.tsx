import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'

export default function ViewerCanvas() {
  return (
    <Canvas camera={{ position: [3, 3, 3] }}>
      <ambientLight intensity={0.5} />
      <directionalLight position={[5, 5, 5]} />
      <mesh>
        <boxGeometry />
        <meshStandardMaterial color="royalblue" />
      </mesh>
      <gridHelper args={[10, 10]} />
      <OrbitControls />
    </Canvas>
  )
}
