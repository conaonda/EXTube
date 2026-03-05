import { Suspense, useCallback, useRef, useState } from 'react'
import { Canvas } from '@react-three/fiber'
import { OrbitControls } from '@react-three/drei'
import PointCloud from './PointCloud'
import PotreePointCloud from './PotreePointCloud'
import GaussianSplatViewer from './GaussianSplatViewer'
import ViewerControls from './ViewerControls'
import type { OrbitControls as OrbitControlsImpl } from 'three-stdlib'

interface ViewerCanvasProps {
  plyUrl: string | null
  potreeUrl: string | null
  splatUrl: string | null
}

const DEFAULT_CAMERA_POS: [number, number, number] = [3, 3, 3]

export default function ViewerCanvas({ plyUrl, potreeUrl, splatUrl }: ViewerCanvasProps) {
  const [pointSize, setPointSize] = useState(0.02)
  const [bgColor, setBgColor] = useState('#000000')
  const [showBoundingBox, setShowBoundingBox] = useState(false)
  const [pointCount, setPointCount] = useState<number | null>(null)
  const controlsRef = useRef<OrbitControlsImpl>(null)

  const handleResetCamera = useCallback(() => {
    const controls = controlsRef.current
    if (controls) {
      controls.object.position.set(...DEFAULT_CAMERA_POS)
      controls.target.set(0, 0, 0)
      controls.update()
    }
  }, [])

  const handlePointCloudLoad = useCallback(
    (info: { pointCount: number; defaultPointSize: number }) => {
      setPointCount(info.pointCount)
      setPointSize(info.defaultPointSize)
    },
    [],
  )

  const hasData = plyUrl || potreeUrl || splatUrl

  return (
    <>
      <Canvas
        camera={{ position: DEFAULT_CAMERA_POS }}
        gl={{ antialias: !splatUrl }}
        style={{ background: bgColor }}
      >
        <ambientLight intensity={0.5} />
        <directionalLight position={[5, 5, 5]} />
        {splatUrl ? (
          <GaussianSplatViewer
            url={splatUrl}
            onLoad={handlePointCloudLoad}
          />
        ) : potreeUrl ? (
          <PotreePointCloud
            url={potreeUrl}
            pointSize={pointSize}
            onLoad={handlePointCloudLoad}
          />
        ) : plyUrl ? (
          <Suspense fallback={null}>
            <PointCloud
              url={plyUrl}
              pointSize={pointSize}
              showBoundingBox={showBoundingBox}
              onLoad={handlePointCloudLoad}
            />
          </Suspense>
        ) : (
          <mesh>
            <boxGeometry />
            <meshStandardMaterial color="royalblue" />
          </mesh>
        )}
        <gridHelper args={[10, 10]} />
        <OrbitControls ref={controlsRef} />
      </Canvas>
      {hasData && (
        <ViewerControls
          pointSize={pointSize}
          onPointSizeChange={setPointSize}
          bgColor={bgColor}
          onBgColorChange={setBgColor}
          showBoundingBox={showBoundingBox}
          onToggleBoundingBox={() => setShowBoundingBox((v) => !v)}
          onResetCamera={handleResetCamera}
          pointCount={pointCount}
          isPotree={!!potreeUrl}
        />
      )}
    </>
  )
}
