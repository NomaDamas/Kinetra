// R3F scene: replays a Trajectory (MuJoCo Z-up, wxyz). The whole world lives in a group rotated -90deg about X,
// which maps MuJoCo (x,y,z) -> Three (x,z,-y); quaternions are only reordered wxyz -> xyzw.
import { Component, Suspense, useEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Canvas, useFrame, useThree } from '@react-three/fiber'
import { Grid, OrbitControls, useGLTF } from '@react-three/drei'
import * as THREE from 'three'
import type { Geom, Trajectory } from '../types'
import type { LiveHandle } from '../live/types'

export interface Clock {
  t: number
}

const WORLD_ROT: [number, number, number] = [-Math.PI / 2, 0, 0]

function colorOf(rgba: [number, number, number, number]) {
  return new THREE.Color().setRGB(rgba[0], rgba[1], rgba[2], THREE.SRGBColorSpace)
}

function Mat({ rgba }: { rgba: [number, number, number, number] }) {
  const c = useMemo(() => colorOf(rgba), [rgba])
  return (
    <meshStandardMaterial
      color={c}
      metalness={0.25}
      roughness={0.55}
      transparent={rgba[3] < 0.999}
      opacity={rgba[3]}
    />
  )
}

function Primitive({ geom }: { geom: Geom }) {
  const s = geom.size
  const g = useMemo(() => {
    const t: string = geom.type === 'mesh' ? (s.length >= 3 ? 'box' : s.length === 2 ? 'capsule' : 'sphere') : geom.type
    switch (t) {
      case 'box':
        return new THREE.BoxGeometry(2 * (s[0] ?? 0.05), 2 * (s[1] ?? 0.05), 2 * (s[2] ?? 0.05))
      case 'sphere':
        return new THREE.SphereGeometry(s[0] ?? 0.05, 24, 16)
      case 'ellipsoid': {
        const e = new THREE.SphereGeometry(1, 24, 16)
        e.scale(s[0] ?? 0.05, s[1] ?? 0.05, s[2] ?? 0.05)
        return e
      }
      case 'capsule': {
        const c = new THREE.CapsuleGeometry(s[0] ?? 0.03, 2 * (s[1] ?? 0.1), 6, 16)
        c.rotateX(Math.PI / 2) // MuJoCo capsule axis = local z
        return c
      }
      case 'cylinder': {
        const c = new THREE.CylinderGeometry(s[0] ?? 0.05, s[0] ?? 0.05, 2 * (s[1] ?? 0.1), 24)
        c.rotateX(Math.PI / 2)
        return c
      }
      default:
        return null
    }
  }, [geom.type, s])
  useEffect(() => () => g?.dispose(), [g])
  if (!g) return null
  return (
    <mesh geometry={g} castShadow receiveShadow>
      <Mat rgba={geom.rgba} />
    </mesh>
  )
}

class Boundary extends Component<{ fallback: ReactNode; children: ReactNode }, { err: boolean }> {
  state = { err: false }
  static getDerivedStateFromError() {
    return { err: true }
  }
  render() {
    return this.state.err ? this.props.fallback : this.props.children
  }
}

const meshProbe = new Map<string, Promise<boolean>>()
function probe(url: string): Promise<boolean> {
  let p = meshProbe.get(url)
  if (!p) {
    p = fetch(url, { method: 'HEAD' })
      .then((r) => r.ok && !(r.headers.get('content-type') ?? '').includes('text/html'))
      .catch(() => false)
    meshProbe.set(url, p)
  }
  return p
}

function meshUrl(name: string) {
  const n = /\.[a-z0-9]+$/i.test(name) ? name : `${name}.glb`
  return /^(https?:)?\//.test(n) ? n : `/assets/${n}`
}

function GlbMesh({ url, rgba }: { url: string; rgba: [number, number, number, number] }) {
  const gltf = useGLTF(url)
  const obj = useMemo(() => {
    const c = gltf.scene.clone(true)
    const m = new THREE.MeshStandardMaterial({
      color: colorOf(rgba),
      metalness: 0.25,
      roughness: 0.55,
      transparent: rgba[3] < 0.999,
      opacity: rgba[3],
    })
    c.traverse((o) => {
      if ((o as THREE.Mesh).isMesh) (o as THREE.Mesh).material = m
    })
    return c
  }, [gltf, rgba])
  return <primitive object={obj} />
}

function MeshGeom({ geom }: { geom: Geom }) {
  const url = geom.mesh ? meshUrl(geom.mesh) : null
  const [ok, setOk] = useState<boolean | null>(null)
  useEffect(() => {
    let live = true
    if (url) probe(url).then((v) => live && setOk(v))
    return () => {
      live = false
    }
  }, [url])
  if (!url || ok === false) return <Primitive geom={geom} />
  if (ok === null) return null
  return (
    <Boundary fallback={<Primitive geom={geom} />}>
      <Suspense fallback={null}>
        <GlbMesh url={url} rgba={geom.rgba} />
      </Suspense>
    </Boundary>
  )
}

function GeomNode({ geom }: { geom: Geom }) {
  const q = geom.quat
  const quat = useMemo(() => new THREE.Quaternion(q[1], q[2], q[3], q[0]), [q])
  if (geom.type === 'plane') return null
  return (
    <group position={geom.pos} quaternion={quat}>
      {geom.type === 'mesh' ? <MeshGeom geom={geom} /> : <Primitive geom={geom} />}
    </group>
  )
}

const FLAME_GEOM = (() => {
  const g = new THREE.ConeGeometry(0.12, 1, 14, 1, true)
  g.translate(0, 0.5, 0) // base at origin, tip +Y
  g.rotateX(-Math.PI / 2) // tip -> local -Z (exhaust opposite the force)
  return g
})()
const FLAME_MAT = new THREE.MeshBasicMaterial({
  color: new THREE.Color('#ffb347'),
  transparent: true,
  opacity: 0.85,
  blending: THREE.AdditiveBlending,
  depthWrite: false,
  side: THREE.DoubleSide,
})

interface Props {
  traj: Trajectory
  clock: { current: Clock }
  follow: boolean
  trail: boolean
  /** Streaming state of a live run: `traj` is then preallocated and mutated in place (see live/useLiveSim.ts). */
  live?: LiveHandle
}

function frameIdx(traj: Trajectory, t: number, live?: LiveHandle) {
  // while streaming only the first `live.filled` frames are valid
  const n = live ? Math.max(1, Math.min(live.filled, traj.pos.length)) : traj.pos.length
  const f = Math.min(Math.max(t / traj.dt, 0), n - 1)
  const i0 = Math.floor(f)
  return { i0, i1: Math.min(i0 + 1, n - 1), a: f - i0, f }
}

/** Characteristic scale (m) from the first frame's bounding box. */
export function trajScale(traj: Trajectory): number {
  const f = traj.pos[0] ?? []
  const lo = [Infinity, Infinity, Infinity]
  const hi = [-Infinity, -Infinity, -Infinity]
  for (const p of f)
    for (let k = 0; k < 3; k++) {
      lo[k] = Math.min(lo[k], p[k])
      hi[k] = Math.max(hi[k], p[k])
    }
  const d = Math.hypot(hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2])
  return Math.max(Number.isFinite(d) ? d : 1, 1)
}

function mainBodyIndex(traj: Trajectory) {
  // First body that is not a pure thruster marker / wheel with geoms.
  const i = traj.bodies.findIndex((b) => b.geoms.length > 0)
  return i < 0 ? 0 : i
}

function World({ traj, clock, follow, trail, live }: Props) {
  const groups = useRef<(THREE.Group | null)[]>([])
  const flames = useRef<(THREE.Mesh | null)[]>([])
  const markers = useRef<(THREE.Mesh | null)[]>([])
  const main = useMemo(() => mainBodyIndex(traj), [traj])
  const scale = useMemo(() => trajScale(traj), [traj])
  const scratch = useMemo(
    () => ({ q0: new THREE.Quaternion(), q1: new THREE.Quaternion(), v: new THREE.Vector3() }),
    [],
  )

  const flameInfo = useMemo(() => {
    const out: { bodyIdx: number; name: string; values: number[]; max: number }[] = []
    traj.bodies.forEach((b, i) => {
      if (!b.name.startsWith('thr_')) return
      const s = traj.series.find((x) => x.name === `thrust_${b.name.slice(4)}`)
      if (s) out.push({ bodyIdx: i, name: s.name, values: s.values, max: Math.max(1e-9, ...s.values) })
    })
    return out
  }, [traj])

  const trailGeom = useMemo(() => {
    const n = traj.pos.length
    const arr = new Float32Array(n * 3)
    for (let i = 0; i < n; i++) {
      const p = traj.pos[i][main]
      arr[3 * i] = p[0]
      arr[3 * i + 1] = p[1]
      arr[3 * i + 2] = p[2]
    }
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', new THREE.BufferAttribute(arr, 3))
    g.setDrawRange(0, 1)
    return g
  }, [traj, main])
  // the ghost path shares the trail's position attribute (live runs mutate it in place)
  const ghostGeom = useMemo(() => {
    const g = new THREE.BufferGeometry()
    g.setAttribute('position', trailGeom.getAttribute('position'))
    return g
  }, [trailGeom])
  const trailFilled = useRef<{ geom: THREE.BufferGeometry | null; n: number; rev: number }>({ geom: null, n: 0, rev: -1 })
  const trailObj = useMemo(
    () => new THREE.Line(trailGeom, new THREE.LineBasicMaterial({ color: '#4fd1c5' })),
    [trailGeom],
  )
  const ghostObj = useMemo(
    () => new THREE.Line(ghostGeom, new THREE.LineBasicMaterial({ color: '#4fd1c5', transparent: true, opacity: 0.18 })),
    [ghostGeom],
  )
  if (!live) ghostGeom.setDrawRange(0, traj.pos.length)

  const controls = useThree((s) => s.controls) as unknown as { target: THREE.Vector3; update: () => void } | null
  const camera = useThree((s) => s.camera)

  // Reset camera framing when the trajectory changes.
  useEffect(() => {
    const p = traj.pos[0]?.[main] ?? [0, 0, 0]
    const d = Math.max(scale, 1.2) * 1.7
    camera.position.set(p[0] + d * 0.9, p[2] + d * 0.45, -p[1] + d * 0.9)
    const tgt = new THREE.Vector3(p[0], p[2] + scale * 0.2, -p[1])
    if (controls) {
      controls.target.copy(tgt)
      controls.update()
    } else camera.lookAt(tgt)
  }, [traj, controls, camera, main, scale])

  useFrame(() => {
    const t = clock.current.t
    if (live) {
      // the bounding sphere is computed from the preallocated (first-frame) positions: never frustum-cull a growing trail
      trailObj.frustumCulled = false
      ghostObj.frustumCulled = false
      // refresh the trail attribute for newly filled frames (or rebuild it after an in-place overwrite)
      const nf = Math.min(live.filled, traj.pos.length)
      const st = trailFilled.current
      const rev = live.rev ?? 0
      if (st.rev !== rev || st.geom !== trailGeom) {
        st.rev = rev
        st.geom = trailGeom
        st.n = 0
      }
      if (nf !== st.n) {
        const attr = trailGeom.getAttribute('position') as THREE.BufferAttribute
        const arr = attr.array as Float32Array
        for (let i = Math.min(st.n, nf); i < nf; i++) {
          const p = traj.pos[i][main]
          arr[3 * i] = p[0]
          arr[3 * i + 1] = p[1]
          arr[3 * i + 2] = p[2]
        }
        st.n = nf
        attr.needsUpdate = true
      }
      ghostGeom.setDrawRange(0, nf)
    }
    const { i0, i1, a, f } = frameIdx(traj, t, live)
    const P0 = traj.pos[i0]
    const P1 = traj.pos[i1]
    const Q0 = traj.quat[i0]
    const Q1 = traj.quat[i1]
    for (let b = 0; b < traj.bodies.length; b++) {
      const g = groups.current[b]
      if (!g) continue
      const p0 = P0[b]
      const p1 = P1[b]
      g.position.set(p0[0] + (p1[0] - p0[0]) * a, p0[1] + (p1[1] - p0[1]) * a, p0[2] + (p1[2] - p0[2]) * a)
      const a0 = Q0[b]
      const a1 = Q1[b]
      scratch.q0.set(a0[1], a0[2], a0[3], a0[0])
      scratch.q1.set(a1[1], a1[2], a1[3], a1[0])
      g.quaternion.copy(scratch.q0).slerp(scratch.q1, a)
    }
    flameInfo.forEach((fi, k) => {
      const m = flames.current[k]
      if (!m) return
      const v = fi.values[i0] ?? 0
      m.visible = v > 1e-6
      if (m.visible) {
        let norm = fi.max
        if (live) {
          const sm = live.seriesMax?.[fi.name]
          if (sm !== undefined && sm > 0) norm = sm
          else {
            fi.max = Math.max(fi.max, v)
            norm = fi.max
          }
        }
        const s = v / norm
        const flick = 0.92 + 0.08 * Math.sin(t * 90 + k * 1.7)
        m.scale.set(0.6 + 0.6 * s, 1, 0.6 + 0.6 * s).setZ(0.6 + 0.6 * s)
        m.scale.y = (0.6 + 2.6 * s) * flick * Math.max(0.6, scale / 4)
        m.scale.x = m.scale.z = (0.5 + 0.7 * s) * Math.max(0.6, scale / 4)
      }
    })
    traj.events.forEach((ev, k) => {
      const m = markers.current[k]
      if (m) m.visible = t >= ev.t
    })
    trailGeom.setDrawRange(0, trail ? Math.min(Math.floor(f) + 2, live ? Math.max(live.filled, 1) : traj.pos.length) : 0)
    ghostObj.visible = trail

    if (follow && controls) {
      const pm0 = P0[main]
      const pm1 = P1[main]
      const x = pm0[0] + (pm1[0] - pm0[0]) * a
      const y = pm0[1] + (pm1[1] - pm0[1]) * a
      const z = pm0[2] + (pm1[2] - pm0[2]) * a
      scratch.v.set(x, z, -y).sub(controls.target)
      controls.target.add(scratch.v)
      camera.position.add(scratch.v)
      controls.update()
    }
  })

  return (
    <group rotation={WORLD_ROT}>
      {traj.bodies.map((b, i) => (
        <group
          key={b.name + i}
          ref={(el) => {
            groups.current[i] = el
          }}
        >
          {b.geoms.map((g, k) => (
            <GeomNode key={k} geom={g} />
          ))}
          {flameInfo.map((fi, k) =>
            fi.bodyIdx === i ? (
              <mesh
                key={`fl${k}`}
                geometry={FLAME_GEOM}
                material={FLAME_MAT}
                visible={false}
                ref={(el) => {
                  flames.current[k] = el
                }}
              />
            ) : null,
          )}
        </group>
      ))}
      {traj.events.map((ev, k) =>
        ev.pos ? (
          <mesh
            key={`ev${k}`}
            position={ev.pos}
            visible={false}
            ref={(el) => {
              markers.current[k] = el
            }}
          >
            <sphereGeometry args={[Math.max(0.05, scale * 0.04), 16, 12]} />
            <meshBasicMaterial color={ev.kind === 'failure' ? '#ff5d5d' : '#ffd166'} />
          </mesh>
        ) : null,
      )}
      <primitive object={trailObj} />
      <primitive object={ghostObj} />
    </group>
  )
}

export function Scene(props: Props) {
  const scale = useMemo(() => trajScale(props.traj), [props.traj])
  const big = scale > 3
  return (
    <Canvas
      shadows
      dpr={[1, 1.75]}
      camera={{ position: [6, 4, 6], fov: 42, near: 0.05, far: 4000 }}
      gl={{ antialias: true, preserveDrawingBuffer: true }}
      style={{ background: 'linear-gradient(#0a0f16, #111a26)' }}
    >
      <color attach="background" args={['#0b1119']} />
      <fog attach="fog" args={['#0b1119', 40, 400]} />
      <hemisphereLight args={['#bcd4ff', '#101820', 0.9]} />
      <directionalLight position={[8, 14, 6]} intensity={2.1} castShadow shadow-mapSize={[1024, 1024]} />
      <directionalLight position={[-9, 6, -8]} intensity={0.6} color="#6fb7ff" />
      <Grid
        infiniteGrid
        cellSize={big ? 1 : 0.25}
        sectionSize={big ? 5 : 1}
        cellColor="#22364a"
        sectionColor="#3c6d8a"
        cellThickness={0.6}
        sectionThickness={1.1}
        fadeDistance={big ? 160 : 24}
        fadeStrength={1.4}
        position={[0, -0.002, 0]}
      />
      <Suspense fallback={null}>
        <World {...props} />
      </Suspense>
      <OrbitControls makeDefault enableDamping={false} maxPolarAngle={Math.PI * 0.495} minDistance={0.5} maxDistance={600} />
    </Canvas>
  )
}
