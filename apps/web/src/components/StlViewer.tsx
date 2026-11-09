import { Component, Suspense, useMemo, type ReactNode } from 'react'
import { Canvas, useLoader } from '@react-three/fiber'
import { Grid, OrbitControls } from '@react-three/drei'
import * as THREE from 'three'
import { STLLoader } from 'three/addons/loaders/STLLoader.js'

class Boundary extends Component<{ fallback: ReactNode; children: ReactNode }, { err: boolean }> {
  state = { err: false }
  static getDerivedStateFromError() {
    return { err: true }
  }
  render() {
    return this.state.err ? this.props.fallback : this.props.children
  }
}

function Model({ url }: { url: string }) {
  const geom = useLoader(STLLoader, url)
  const { g, radius } = useMemo(() => {
    const c = geom.clone()
    c.computeVertexNormals()
    c.computeBoundingBox()
    const box = c.boundingBox!
    const center = new THREE.Vector3()
    box.getCenter(center)
    // STL is z-up (CAD); the scene is y-up: rotate, then rest the part on the grid.
    c.translate(-center.x, -center.y, -center.z)
    c.rotateX(-Math.PI / 2)
    c.computeBoundingBox()
    const b2 = c.boundingBox!
    c.translate(0, -b2.min.y, 0)
    const size = new THREE.Vector3()
    b2.getSize(size)
    return { g: c, radius: Math.max(size.x, size.y, size.z) }
  }, [geom])
  const s = 1 / (radius || 1)
  return (
    <group scale={s}>
      <mesh geometry={g}>
        <meshStandardMaterial color="#9fb6cc" metalness={0.35} roughness={0.5} />
      </mesh>
      <lineSegments>
        <edgesGeometry args={[g, 30]} />
        <lineBasicMaterial color="#4fd1c5" />
      </lineSegments>
    </group>
  )
}

/** Orbitable preview of a binary/ASCII STL (CAD kernel output). Units are not shown in the scene; they are in the part params. */
export function StlViewer({ url, label }: { url: string; label: string }) {
  return (
    <div className="view stl" aria-label={`3D preview of ${label}`}>
      <Boundary fallback={<div className="view-empty">Could not load {url}</div>}>
        <Suspense fallback={<div className="view-empty">Loading CAD preview…</div>}>
          <Canvas camera={{ position: [1.3, 1.0, 1.5], fov: 40 }} dpr={[1, 1.75]}>
            <color attach="background" args={['#0b1119']} />
            <ambientLight intensity={0.7} />
            <directionalLight position={[2, 3, 2]} intensity={1.6} />
            <directionalLight position={[-2, 1, -2]} intensity={0.5} />
            <Model url={url} />
            <Grid position={[0, -0.001, 0]} args={[4, 4]} cellSize={0.1} sectionSize={0.5} cellColor="#1f2d3d" sectionColor="#2a3d52" fadeDistance={6} infiniteGrid />
            <OrbitControls makeDefault enablePan={false} minDistance={0.6} maxDistance={6} target={[0, 0.3, 0]} />
          </Canvas>
        </Suspense>
      </Boundary>
      <span className="view-tag">{label} · drag to orbit</span>
    </div>
  )
}
