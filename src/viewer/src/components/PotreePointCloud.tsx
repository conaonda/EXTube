import { useEffect, useRef } from 'react'
import { useFrame, useThree } from '@react-three/fiber'
import { PointCloudOctree, Potree } from 'potree-core'
import * as THREE from 'three'

interface PotreePointCloudProps {
  url: string
  pointBudget?: number
  pointSize?: number
  onLoad?: (info: { pointCount: number; defaultPointSize: number }) => void
}

export default function PotreePointCloud({
  url,
  pointBudget = 2_000_000,
  pointSize,
  onLoad,
}: PotreePointCloudProps) {
  const { camera, gl } = useThree()
  const groupRef = useRef<THREE.Group>(null)
  const potreeRef = useRef<Potree | null>(null)
  const pcoRef = useRef<PointCloudOctree | null>(null)

  useEffect(() => {
    const potree = new Potree()
    potree.pointBudget = pointBudget
    potreeRef.current = potree

    const baseUrl = url.replace(/metadata\.json$/, '')

    potree
      .loadPointCloud('metadata.json', baseUrl)
      .then((pco: PointCloudOctree) => {
        pcoRef.current = pco
        if (groupRef.current) {
          groupRef.current.add(pco)
        }

        const box = pco.pcoGeometry.boundingBox
        const size = new THREE.Vector3()
        box.getSize(size)
        const defaultSize = Math.max(size.x, size.y, size.z) * 0.005

        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        const geom = pco.pcoGeometry as any
        const numPoints: number = geom.numPoints ?? geom.pointCount ?? 0

        onLoad?.({
          pointCount: numPoints,
          defaultPointSize: defaultSize,
        })
      })

    const group = groupRef.current
    return () => {
      if (pcoRef.current && group) {
        group.remove(pcoRef.current)
        pcoRef.current.dispose()
        pcoRef.current = null
      }
      potreeRef.current = null
    }
  }, [url, pointBudget, onLoad])

  useEffect(() => {
    if (pcoRef.current && pointSize !== undefined) {
      pcoRef.current.material.size = pointSize
    }
  }, [pointSize])

  useEffect(() => {
    if (potreeRef.current) {
      potreeRef.current.pointBudget = pointBudget
    }
  }, [pointBudget])

  useFrame(() => {
    if (potreeRef.current && pcoRef.current) {
      potreeRef.current.updatePointClouds(
        [pcoRef.current],
        camera,
        gl,
      )
    }
  })

  return <group ref={groupRef} />
}
