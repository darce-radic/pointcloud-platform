'use client'

import { useEffect, useRef } from 'react'
import * as THREE from 'three'
import { POINT_CLOUD_3D } from './pointCloud3DData'

// ── Asset geometry definitions (matching the 2D demo data) ────────────────────
// All coordinates in the same normalised space: X 0-50, Y -6 to +7, Z in metres

function buildAssetObjects(): THREE.Object3D[] {
  const objects: THREE.Object3D[] = []

  // Road surface — flat semi-transparent plane at z=0
  {
    const geo = new THREE.PlaneGeometry(50, 8)
    const mat = new THREE.MeshBasicMaterial({
      color: 0xa3a3a3,
      transparent: true,
      opacity: 0.12,
      side: THREE.DoubleSide,
    })
    const mesh = new THREE.Mesh(geo, mat)
    mesh.rotation.x = -Math.PI / 2
    mesh.position.set(25, 0.01, 0)
    mesh.userData = { type: 'road_surface' }
    objects.push(mesh)

    // Road surface outline
    const edges = new THREE.EdgesGeometry(geo)
    const line = new THREE.LineSegments(edges, new THREE.LineBasicMaterial({ color: 0xa3a3a3, transparent: true, opacity: 0.4 }))
    line.rotation.x = -Math.PI / 2
    line.position.set(25, 0.02, 0)
    line.userData = { type: 'road_surface' }
    objects.push(line)
  }

  // Centreline — dashed line at road centre
  {
    const points: THREE.Vector3[] = []
    for (let x = 0; x <= 50; x += 0.5)
      points.push(new THREE.Vector3(x, 0.05, Math.sin(x * 0.08) * 0.15))
    const geo = new THREE.BufferGeometry().setFromPoints(points)
    const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xf59e0b, transparent: true, opacity: 0.9 }))
    line.userData = { type: 'road_centreline' }
    objects.push(line)
  }

  // Kerb lines — raised orange lines at road edges
  {
    for (const ySide of [-4, 4]) {
      const pts: THREE.Vector3[] = []
      for (let x = 0; x <= 50; x += 0.5)
        pts.push(new THREE.Vector3(x, 0.12, ySide))
      const geo = new THREE.BufferGeometry().setFromPoints(pts)
      const line = new THREE.Line(geo, new THREE.LineBasicMaterial({ color: 0xfb923c, linewidth: 2 }))
      line.userData = { type: 'kerb' }
      objects.push(line)
    }
  }

  // Road markings — white lines
  {
    // Left edge marking
    const leftPts: THREE.Vector3[] = []
    for (let x = 0; x <= 50; x += 0.5)
      leftPts.push(new THREE.Vector3(x, 0.03, -3.5))
    const leftGeo = new THREE.BufferGeometry().setFromPoints(leftPts)
    const leftLine = new THREE.Line(leftGeo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8 }))
    leftLine.userData = { type: 'road_marking' }
    objects.push(leftLine)

    // Right edge marking
    const rightPts: THREE.Vector3[] = []
    for (let x = 0; x <= 50; x += 0.5)
      rightPts.push(new THREE.Vector3(x, 0.03, 3.5))
    const rightGeo = new THREE.BufferGeometry().setFromPoints(rightPts)
    const rightLine = new THREE.Line(rightGeo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.8 }))
    rightLine.userData = { type: 'road_marking' }
    objects.push(rightLine)

    // Centre dashes
    for (let x = 2; x < 50; x += 4) {
      const dashPts = [
        new THREE.Vector3(x, 0.03, 0),
        new THREE.Vector3(x + 2, 0.03, 0),
      ]
      const dashGeo = new THREE.BufferGeometry().setFromPoints(dashPts)
      const dashLine = new THREE.Line(dashGeo, new THREE.LineBasicMaterial({ color: 0xffffff, transparent: true, opacity: 0.7 }))
      dashLine.userData = { type: 'road_marking' }
      objects.push(dashLine)
    }
  }

  // Traffic signs — red pole + flat sign board
  {
    for (const [sx, sz] of [[10, -4.5], [35, -4.5]]) {
      // Pole
      const poleGeo = new THREE.CylinderGeometry(0.05, 0.05, 3.2, 8)
      const poleMat = new THREE.MeshBasicMaterial({ color: 0xef4444 })
      const pole = new THREE.Mesh(poleGeo, poleMat)
      pole.position.set(sx, 1.6, sz)
      pole.userData = { type: 'traffic_sign' }
      objects.push(pole)

      // Sign board
      const boardGeo = new THREE.BoxGeometry(0.6, 0.6, 0.05)
      const boardMat = new THREE.MeshBasicMaterial({ color: 0xef4444, transparent: true, opacity: 0.85 })
      const board = new THREE.Mesh(boardGeo, boardMat)
      board.position.set(sx, 3.4, sz)
      board.userData = { type: 'traffic_sign' }
      objects.push(board)
    }
  }

  // Drain / manhole covers — cyan circles at road edge
  {
    for (const [dx, dz] of [[15, 3.8], [30, 3.8]]) {
      const geo = new THREE.CircleGeometry(0.3, 16)
      const mat = new THREE.MeshBasicMaterial({ color: 0x38bdf8, transparent: true, opacity: 0.85, side: THREE.DoubleSide })
      const mesh = new THREE.Mesh(geo, mat)
      mesh.rotation.x = -Math.PI / 2
      mesh.position.set(dx, 0.04, dz)
      mesh.userData = { type: 'drain_manhole' }
      objects.push(mesh)

      // Outline ring
      const ringGeo = new THREE.RingGeometry(0.28, 0.32, 16)
      const ringMat = new THREE.MeshBasicMaterial({ color: 0x38bdf8, side: THREE.DoubleSide })
      const ring = new THREE.Mesh(ringGeo, ringMat)
      ring.rotation.x = -Math.PI / 2
      ring.position.set(dx, 0.05, dz)
      ring.userData = { type: 'drain_manhole' }
      objects.push(ring)
    }
  }

  return objects
}

// ── Simple orbit controls (no external dependency) ────────────────────────────
class SimpleOrbitControls {
  private isDragging = false
  private isRightDragging = false
  private lastX = 0
  private lastY = 0
  private theta = -0.4   // horizontal angle (radians)
  private phi = 1.1      // vertical angle (radians, 0=top, PI/2=side)
  private radius = 35
  private target = new THREE.Vector3(25, 0, 0)

  constructor(
    private camera: THREE.PerspectiveCamera,
    private domElement: HTMLCanvasElement,
  ) {
    this.updateCamera()
    this.bind()
  }

  private bind() {
    this.domElement.addEventListener('mousedown', this.onMouseDown)
    this.domElement.addEventListener('mousemove', this.onMouseMove)
    this.domElement.addEventListener('mouseup', this.onMouseUp)
    this.domElement.addEventListener('wheel', this.onWheel, { passive: false })
    this.domElement.addEventListener('contextmenu', (e) => e.preventDefault())
    this.domElement.addEventListener('touchstart', this.onTouchStart, { passive: false })
    this.domElement.addEventListener('touchmove', this.onTouchMove, { passive: false })
    this.domElement.addEventListener('touchend', this.onTouchEnd)
  }

  dispose() {
    this.domElement.removeEventListener('mousedown', this.onMouseDown)
    this.domElement.removeEventListener('mousemove', this.onMouseMove)
    this.domElement.removeEventListener('mouseup', this.onMouseUp)
    this.domElement.removeEventListener('wheel', this.onWheel)
    this.domElement.removeEventListener('touchstart', this.onTouchStart)
    this.domElement.removeEventListener('touchmove', this.onTouchMove)
    this.domElement.removeEventListener('touchend', this.onTouchEnd)
  }

  private onMouseDown = (e: MouseEvent) => {
    if (e.button === 0) this.isDragging = true
    if (e.button === 2) this.isRightDragging = true
    this.lastX = e.clientX
    this.lastY = e.clientY
  }

  private onMouseMove = (e: MouseEvent) => {
    const dx = e.clientX - this.lastX
    const dy = e.clientY - this.lastY
    this.lastX = e.clientX
    this.lastY = e.clientY
    if (this.isDragging) {
      this.theta -= dx * 0.005
      this.phi = Math.max(0.1, Math.min(Math.PI - 0.1, this.phi + dy * 0.005))
      this.updateCamera()
    }
    if (this.isRightDragging) {
      const panSpeed = this.radius * 0.001
      this.target.x -= dx * panSpeed
      this.target.z += dy * panSpeed
      this.updateCamera()
    }
  }

  private onMouseUp = () => { this.isDragging = false; this.isRightDragging = false }

  private onWheel = (e: WheelEvent) => {
    e.preventDefault()
    this.radius = Math.max(5, Math.min(80, this.radius + e.deltaY * 0.05))
    this.updateCamera()
  }

  private touchStartDist = 0
  private onTouchStart = (e: TouchEvent) => {
    e.preventDefault()
    if (e.touches.length === 1) {
      this.isDragging = true
      this.lastX = e.touches[0].clientX
      this.lastY = e.touches[0].clientY
    } else if (e.touches.length === 2) {
      this.isDragging = false
      this.touchStartDist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      )
    }
  }

  private onTouchMove = (e: TouchEvent) => {
    e.preventDefault()
    if (e.touches.length === 1 && this.isDragging) {
      const dx = e.touches[0].clientX - this.lastX
      const dy = e.touches[0].clientY - this.lastY
      this.lastX = e.touches[0].clientX
      this.lastY = e.touches[0].clientY
      this.theta -= dx * 0.005
      this.phi = Math.max(0.1, Math.min(Math.PI - 0.1, this.phi + dy * 0.005))
      this.updateCamera()
    } else if (e.touches.length === 2) {
      const dist = Math.hypot(
        e.touches[0].clientX - e.touches[1].clientX,
        e.touches[0].clientY - e.touches[1].clientY,
      )
      this.radius = Math.max(5, Math.min(80, this.radius - (dist - this.touchStartDist) * 0.05))
      this.touchStartDist = dist
      this.updateCamera()
    }
  }

  private onTouchEnd = () => { this.isDragging = false }

  private updateCamera() {
    const x = this.target.x + this.radius * Math.sin(this.phi) * Math.sin(this.theta)
    const y = this.target.y + this.radius * Math.cos(this.phi)
    const z = this.target.z + this.radius * Math.sin(this.phi) * Math.cos(this.theta)
    this.camera.position.set(x, y, z)
    this.camera.lookAt(this.target)
  }

  reset() {
    this.theta = -0.4
    this.phi = 1.1
    this.radius = 35
    this.target.set(25, 0, 0)
    this.updateCamera()
  }
}

// ── Component ─────────────────────────────────────────────────────────────────
interface Props {
  visibleLayers: Set<string>
}

export default function PointCloud3DViewer({ visibleLayers }: Props) {
  const mountRef = useRef<HTMLDivElement>(null)
  const rendererRef = useRef<THREE.WebGLRenderer | null>(null)
  const sceneRef = useRef<THREE.Scene | null>(null)
  const assetObjectsRef = useRef<THREE.Object3D[]>([])
  const controlsRef = useRef<SimpleOrbitControls | null>(null)
  const animFrameRef = useRef<number>(0)

  useEffect(() => {
    const mount = mountRef.current
    if (!mount) return

    // Scene
    const scene = new THREE.Scene()
    scene.background = new THREE.Color(0x0a0a0a)
    sceneRef.current = scene

    // Subtle fog for depth
    scene.fog = new THREE.FogExp2(0x0a0a0a, 0.008)

    // Camera
    const camera = new THREE.PerspectiveCamera(55, mount.clientWidth / mount.clientHeight, 0.1, 500)

    // Renderer
    const renderer = new THREE.WebGLRenderer({ antialias: true })
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
    renderer.setSize(mount.clientWidth, mount.clientHeight)
    mount.appendChild(renderer.domElement)
    rendererRef.current = renderer

    // Orbit controls
    const controls = new SimpleOrbitControls(camera, renderer.domElement)
    controlsRef.current = controls

    // ── Point cloud geometry ──────────────────────────────────────────────────
    const positions = new Float32Array(POINT_CLOUD_3D.length * 3)
    const colors = new Float32Array(POINT_CLOUD_3D.length * 3)

    for (let i = 0; i < POINT_CLOUD_3D.length; i++) {
      const [x, y, z, r, g, b] = POINT_CLOUD_3D[i]
      // Three.js: X=right, Y=up, Z=towards camera
      // Our data: X=along road, Y=across road, Z=height
      positions[i * 3 + 0] = x
      positions[i * 3 + 1] = z        // Z becomes Y (height)
      positions[i * 3 + 2] = y        // Y becomes Z (depth)
      colors[i * 3 + 0] = r / 255
      colors[i * 3 + 1] = g / 255
      colors[i * 3 + 2] = b / 255
    }

    const ptGeo = new THREE.BufferGeometry()
    ptGeo.setAttribute('position', new THREE.BufferAttribute(positions, 3))
    ptGeo.setAttribute('color', new THREE.BufferAttribute(colors, 3))

    const ptMat = new THREE.PointsMaterial({
      size: 0.12,
      vertexColors: true,
      sizeAttenuation: true,
    })

    const pointCloud = new THREE.Points(ptGeo, ptMat)
    scene.add(pointCloud)

    // ── Ground grid ───────────────────────────────────────────────────────────
    const gridHelper = new THREE.GridHelper(60, 30, 0x222222, 0x1a1a1a)
    gridHelper.position.set(25, -0.01, 0)
    scene.add(gridHelper)

    // ── Asset overlays ────────────────────────────────────────────────────────
    const assetObjects = buildAssetObjects()
    assetObjectsRef.current = assetObjects
    // Remap Y/Z for Three.js coordinate system
    for (const obj of assetObjects) {
      // Swap Y and Z on position
      const p = obj.position
      obj.position.set(p.x, p.y, p.z)  // already in correct space for this scene
      scene.add(obj)
    }

    // ── Ambient light ─────────────────────────────────────────────────────────
    scene.add(new THREE.AmbientLight(0xffffff, 0.6))

    // ── Resize handler ────────────────────────────────────────────────────────
    const onResize = () => {
      if (!mount) return
      camera.aspect = mount.clientWidth / mount.clientHeight
      camera.updateProjectionMatrix()
      renderer.setSize(mount.clientWidth, mount.clientHeight)
    }
    window.addEventListener('resize', onResize)

    // ── Render loop ───────────────────────────────────────────────────────────
    const animate = () => {
      animFrameRef.current = requestAnimationFrame(animate)
      renderer.render(scene, camera)
    }
    animate()

    return () => {
      cancelAnimationFrame(animFrameRef.current)
      window.removeEventListener('resize', onResize)
      controls.dispose()
      renderer.dispose()
      if (mount.contains(renderer.domElement)) mount.removeChild(renderer.domElement)
    }
  }, [])

  // Update asset visibility when visibleLayers changes
  useEffect(() => {
    for (const obj of assetObjectsRef.current) {
      const t = obj.userData.type as string
      if (t) obj.visible = visibleLayers.has(t)
    }
    // Force re-render
    if (rendererRef.current && sceneRef.current) {
      // The animation loop handles this automatically
    }
  }, [visibleLayers])

  return (
    <div className="relative w-full h-full">
      <div ref={mountRef} className="w-full h-full" />
      {/* Controls hint */}
      <div className="absolute bottom-3 left-1/2 -translate-x-1/2 text-xs text-white/30 pointer-events-none select-none">
        Left drag to orbit · Right drag to pan · Scroll to zoom
      </div>
      {/* Reset button */}
      <button
        onClick={() => controlsRef.current?.reset()}
        className="absolute top-3 right-3 w-8 h-8 rounded-full bg-white/5 border border-white/10 text-white/50 hover:bg-white/10 hover:text-white/80 transition-all flex items-center justify-center text-sm"
        title="Reset view"
      >
        ⟳
      </button>
    </div>
  )
}
