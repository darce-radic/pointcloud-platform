'use client'

import { useEffect, useRef, useState, useCallback, lazy, Suspense } from 'react'
import { createClient } from '@/lib/supabase/client'
import AiChatPanel from '@/components/ai-chat/AiChatPanel'
import ViewerToolbar from '@/components/viewer/ViewerToolbar'
import JobProgressOverlay from '@/components/viewer/JobProgressOverlay'
import RenderModePanel from '@/components/viewer/RenderModePanel'
import MeasurePanel from '@/components/viewer/MeasurePanel'
import ClassificationPanel from '@/components/viewer/ClassificationPanel'
import MapPanel from '@/components/viewer/MapPanel'

// Lazy-load CesiumViewer to avoid SSR issues with the heavy Cesium bundle
const CesiumViewer = lazy(() => import('@/components/viewer/CesiumViewer'))

// ─── LAS classification labels (ASPRS standard) ──────────────────────────────
const LAS_CLASSES: Record<number, string> = {
  0: 'Never Classified',
  1: 'Unclassified',
  2: 'Ground',
  3: 'Low Vegetation',
  4: 'Medium Vegetation',
  5: 'High Vegetation',
  6: 'Building',
  7: 'Low Point (Noise)',
  8: 'Reserved',
  9: 'Water',
  10: 'Rail',
  11: 'Road Surface',
  12: 'Reserved',
  13: 'Wire – Guard',
  14: 'Wire – Conductor',
  15: 'Transmission Tower',
  16: 'Wire-Structure Connector',
  17: 'Bridge Deck',
  18: 'High Noise',
}

export type RenderMode = 'rgb' | 'intensity' | 'height'

export interface Measurement {
  id: string
  type: 'distance' | 'height'
  points: [number, number, number][]
  value: number | null // metres
}

// Colour ramp: blue → cyan → green → yellow → red
function heightColor(t: number): [number, number, number] {
  const stops: [number, [number, number, number]][] = [
    [0.0, [0.0, 0.0, 1.0]],
    [0.25, [0.0, 1.0, 1.0]],
    [0.5, [0.0, 1.0, 0.0]],
    [0.75, [1.0, 1.0, 0.0]],
    [1.0, [1.0, 0.0, 0.0]],
  ]
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, c0] = stops[i]
    const [t1, c1] = stops[i + 1]
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0)
      return [
        c0[0] + f * (c1[0] - c0[0]),
        c0[1] + f * (c1[1] - c0[1]),
        c0[2] + f * (c1[2] - c0[2]),
      ]
    }
  }
  return [1, 0, 0]
}

// Greyscale ramp for intensity
function intensityColor(t: number): [number, number, number] {
  return [t, t, t]
}

interface Dataset {
  id: string
  name: string
  copcUrl: string | null
  status: string
  pointCount: number | null
  crsEpsg: number | null
  boundingBox: unknown
}

interface WorkflowTool {
  id: string
  name: string
  description: string
  icon: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  required_inputs: Record<string, any>
  n8n_workflow_id: string
}

interface ViewerClientProps {
  dataset: Dataset
  workflowTools: WorkflowTool[]
}

// Raw point data stored after first load so we can re-colour without re-fetching
interface PointData {
  positions: Float32Array       // centred XYZ
  rawZ: Float32Array            // original Z values (for height ramp)
  zMin: number
  zMax: number
  rgbColors: Float32Array       // normalised RGB (0-1), or fallback grey
  intensities: Float32Array     // normalised intensity (0-1)
  classifications: Uint8Array   // LAS class codes
  hasRgb: boolean
  hasIntensity: boolean
  hasClassification: boolean
  // geographic centre (WGS84 approx) for map panel
  centerLat: number | null
  centerLon: number | null
}

export default function ViewerClient({ dataset, workflowTools }: ViewerClientProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)

  const [viewerReady, setViewerReady] = useState(false)
  const [loadingStatus, setLoadingStatus] = useState('Initialising viewer...')
  const [chatOpen, setChatOpen] = useState(false)
  const [activeJob, setActiveJob] = useState<string | null>(null)

  // ── Viewer feature state ────────────────────────────────────────────────────
  const [renderMode, setRenderMode] = useState<RenderMode>('rgb')
  const [activePanel, setActivePanel] = useState<'render' | 'measure' | 'classify' | 'map' | null>(null)
  const [measurements, setMeasurements] = useState<Measurement[]>([])
  const [measureMode, setMeasureMode] = useState<'distance' | 'height' | null>(null)
  const [pendingPoints, setPendingPoints] = useState<[number, number, number][]>([])
  const [visibleClasses, setVisibleClasses] = useState<Set<number>>(new Set(Object.keys(LAS_CLASSES).map(Number)))
  const [mapOpen, setMapOpen] = useState(false)
  const [cesiumMode, setCesiumMode] = useState(false)

  // ── Refs shared with Three.js loop ──────────────────────────────────────────
  const pointDataRef = useRef<PointData | null>(null)
  const threeRef = useRef<{
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    THREE: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    geometry: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    material: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    pointCloud: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    scene: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    camera: any
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    renderer: any
  } | null>(null)

  const renderModeRef = useRef<RenderMode>('rgb')
  const visibleClassesRef = useRef<Set<number>>(visibleClasses)

  const supabase = createClient()

  // ── Keep refs in sync ───────────────────────────────────────────────────────
  useEffect(() => { renderModeRef.current = renderMode }, [renderMode])
  useEffect(() => { visibleClassesRef.current = visibleClasses }, [visibleClasses])

  // ── Recolour geometry when render mode or visibility changes ────────────────
  const recolour = useCallback(() => {
    const pd = pointDataRef.current
    const t = threeRef.current
    if (!pd || !t) return

    const { THREE, geometry } = t
    const count = pd.positions.length / 3
    const newColors = new Float32Array(count * 3)

    const mode = renderModeRef.current
    const visible = visibleClassesRef.current

    for (let i = 0; i < count; i++) {
      // Classification visibility mask — set to black/transparent if hidden
      const cls = pd.hasClassification ? pd.classifications[i] : 1
      if (!visible.has(cls)) {
        newColors[i * 3] = 0
        newColors[i * 3 + 1] = 0
        newColors[i * 3 + 2] = 0
        continue
      }

      let r = 0, g = 0, b = 0
      if (mode === 'rgb') {
        r = pd.rgbColors[i * 3]
        g = pd.rgbColors[i * 3 + 1]
        b = pd.rgbColors[i * 3 + 2]
      } else if (mode === 'intensity') {
        const iv = pd.hasIntensity ? pd.intensities[i] : 0.5;
        [r, g, b] = intensityColor(iv)
      } else {
        // height
        const zRange = pd.zMax - pd.zMin
        const t = zRange > 0 ? (pd.rawZ[i] - pd.zMin) / zRange : 0.5;
        [r, g, b] = heightColor(t)
      }
      newColors[i * 3] = r
      newColors[i * 3 + 1] = g
      newColors[i * 3 + 2] = b
    }

    geometry.setAttribute('color', new THREE.BufferAttribute(newColors, 3))
    geometry.attributes.color.needsUpdate = true
  }, [])

  // Trigger recolour whenever mode or visibility changes
  useEffect(() => { recolour() }, [renderMode, visibleClasses, recolour])

  // ── Main Three.js initialisation ────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!canvasRef.current || !containerRef.current) return
    if (!dataset.copcUrl) {
      setLoadingStatus('Dataset is still processing...')
      return
    }

    let animationId: number
    let destroyed = false

    const init = async () => {
      try {
        setLoadingStatus('Loading Three.js...')
        const THREE = await import('three')
        if (destroyed) return

        setLoadingStatus('Reading COPC header...')
        const { Copc } = await import('copc')
        if (destroyed) return

        const copc = await Copc.create(dataset.copcUrl!)
        const { header, info } = copc
        if (destroyed) return

        setLoadingStatus(`Loading ${(header.pointCount / 1_000_000).toFixed(1)}M points...`)

        const nodes = await Copc.loadHierarchyPage(dataset.copcUrl!, info.rootHierarchyPage)
        const rootKey = '0-0-0-0'
        const rootNode = nodes.nodes[rootKey]

        let positions: Float32Array
        let rawZ: Float32Array
        let rgbColors: Float32Array
        let intensities: Float32Array
        let classifications: Uint8Array
        let hasRgb = false
        let hasIntensity = false
        let hasClassification = false
        let zMin = Infinity, zMax = -Infinity
        let centerLat: number | null = null
        let centerLon: number | null = null

        if (rootNode) {
          const view = await Copc.loadPointDataView(dataset.copcUrl!, copc, rootNode)
          const count = view.pointCount

          const getX = view.getter('X')
          const getY = view.getter('Y')
          const getZ = view.getter('Z')

          hasRgb = 'Red' in view.dimensions && 'Green' in view.dimensions && 'Blue' in view.dimensions
          hasIntensity = 'Intensity' in view.dimensions
          hasClassification = 'Classification' in view.dimensions

          const getRed = hasRgb ? view.getter('Red') : null
          const getGreen = hasRgb ? view.getter('Green') : null
          const getBlue = hasRgb ? view.getter('Blue') : null
          const getIntensity = hasIntensity ? view.getter('Intensity') : null
          const getClassification = hasClassification ? view.getter('Classification') : null

          positions = new Float32Array(count * 3)
          rawZ = new Float32Array(count)
          rgbColors = new Float32Array(count * 3)
          intensities = new Float32Array(count)
          classifications = new Uint8Array(count)

          // Compute centroid
          let cx = 0, cy = 0, cz = 0
          let intensityMax = 0
          for (let i = 0; i < count; i++) {
            const x = getX(i) as number
            const y = getY(i) as number
            const z = getZ(i) as number
            cx += x; cy += y; cz += z
            if (z < zMin) zMin = z
            if (z > zMax) zMax = z
            if (hasIntensity) {
              const iv = getIntensity!(i) as number
              if (iv > intensityMax) intensityMax = iv
            }
          }
          cx /= count; cy /= count; cz /= count

          // Try to get approximate WGS84 centre from COPC header bounds
          if (header.min && header.max) {
            const midX = (header.min[0] + header.max[0]) / 2
            const midY = (header.min[1] + header.max[1]) / 2
            // If CRS is WGS84 (EPSG:4326) or similar, use directly
            // Otherwise use as-is (map will show approximate location)
            if (dataset.crsEpsg === 4326) {
              centerLon = midX
              centerLat = midY
            } else if (dataset.crsEpsg === 4283) {
              centerLon = midX
              centerLat = midY
            } else {
              // Rough fallback: treat as projected, map may be off
              centerLon = midX
              centerLat = midY
            }
          }

          for (let i = 0; i < count; i++) {
            const x = getX(i) as number
            const y = getY(i) as number
            const z = getZ(i) as number
            positions[i * 3] = x - cx
            positions[i * 3 + 1] = y - cy
            positions[i * 3 + 2] = z - cz
            rawZ[i] = z

            if (hasRgb && getRed && getGreen && getBlue) {
              rgbColors[i * 3] = (getRed(i) as number) / 65535
              rgbColors[i * 3 + 1] = (getGreen(i) as number) / 65535
              rgbColors[i * 3 + 2] = (getBlue(i) as number) / 65535
            } else {
              rgbColors[i * 3] = 0.5
              rgbColors[i * 3 + 1] = 0.7
              rgbColors[i * 3 + 2] = 1.0
            }

            if (hasIntensity && getIntensity) {
              intensities[i] = intensityMax > 0 ? (getIntensity(i) as number) / intensityMax : 0
            } else {
              intensities[i] = 0.5
            }

            if (hasClassification && getClassification) {
              classifications[i] = (getClassification(i) as number) & 0x1F // mask to 5 bits
            } else {
              classifications[i] = 1
            }
          }

          // Discover which classes are present
          const presentClasses = new Set<number>()
          for (let i = 0; i < count; i++) presentClasses.add(classifications[i])
          setVisibleClasses(presentClasses)

          pointDataRef.current = {
            positions, rawZ, zMin, zMax,
            rgbColors, intensities, classifications,
            hasRgb, hasIntensity, hasClassification,
            centerLat, centerLon,
          }
        } else {
          positions = new Float32Array(0)
          rawZ = new Float32Array(0)
          rgbColors = new Float32Array(0)
          intensities = new Float32Array(0)
          classifications = new Uint8Array(0)
        }

        if (destroyed) return
        setLoadingStatus('Rendering...')

        const canvas = canvasRef.current!
        const container = containerRef.current!
        const width = container.clientWidth
        const height = container.clientHeight

        const renderer = new THREE.WebGLRenderer({ canvas, antialias: false })
        renderer.setSize(width, height)
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        renderer.setClearColor(0x000000)

        const scene = new THREE.Scene()
        const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 100000)
        const bbox = header.min && header.max
          ? Math.max(
              header.max[0] - header.min[0],
              header.max[1] - header.min[1],
              header.max[2] - header.min[2]
            )
          : 1000
        camera.position.set(0, -bbox * 0.8, bbox * 0.5)
        camera.lookAt(0, 0, 0)

        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))

        // Build initial colour buffer (RGB mode)
        const initialColors = new Float32Array(rgbColors)
        geometry.setAttribute('color', new THREE.BufferAttribute(initialColors, 3))

        const material = new THREE.PointsMaterial({
          size: 2,
          sizeAttenuation: false,
          vertexColors: true,
        })

        const pointCloud = new THREE.Points(geometry, material)
        scene.add(pointCloud)

        threeRef.current = { THREE, geometry, material, pointCloud, scene, camera, renderer }

        // Orbit controls
        let isDragging = false
        let prevMouse = { x: 0, y: 0 }
        const spherical = { theta: 0, phi: Math.PI / 3, radius: bbox * 1.2 }

        const updateCamera = () => {
          camera.position.set(
            spherical.radius * Math.sin(spherical.phi) * Math.sin(spherical.theta),
            -spherical.radius * Math.sin(spherical.phi) * Math.cos(spherical.theta),
            spherical.radius * Math.cos(spherical.phi)
          )
          camera.lookAt(0, 0, 0)
        }
        updateCamera()

        canvas.addEventListener('mousedown', (e) => {
          isDragging = true
          prevMouse = { x: e.clientX, y: e.clientY }
        })
        canvas.addEventListener('mouseup', () => { isDragging = false })
        canvas.addEventListener('mousemove', (e) => {
          if (!isDragging) return
          const dx = (e.clientX - prevMouse.x) * 0.005
          const dy = (e.clientY - prevMouse.y) * 0.005
          spherical.theta -= dx
          spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, spherical.phi + dy))
          prevMouse = { x: e.clientX, y: e.clientY }
          updateCamera()
        })
        canvas.addEventListener('wheel', (e) => {
          spherical.radius *= e.deltaY > 0 ? 1.1 : 0.9
          spherical.radius = Math.max(1, spherical.radius)
          updateCamera()
        }, { passive: true })

        const onResize = () => {
          const w = container.clientWidth
          const h = container.clientHeight
          renderer.setSize(w, h)
          camera.aspect = w / h
          camera.updateProjectionMatrix()
        }
        window.addEventListener('resize', onResize)

        const animate = () => {
          if (destroyed) return
          animationId = requestAnimationFrame(animate)
          renderer.render(scene, camera)
        }
        animate()

        setViewerReady(true)

        return () => {
          window.removeEventListener('resize', onResize)
          renderer.dispose()
          geometry.dispose()
          material.dispose()
        }
      } catch (err) {
        console.error('Viewer error:', err)
        setLoadingStatus('Failed to load point cloud. Please try again.')
      }
    }

    init()

    return () => {
      destroyed = true
      if (animationId) cancelAnimationFrame(animationId)
    }
  }, [dataset.copcUrl, dataset.name, dataset.crsEpsg])

  // ── Supabase Realtime job updates ───────────────────────────────────────────
  useEffect(() => {
    if (!activeJob) return
    const channel = supabase
      .channel(`job-${activeJob}`)
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'processing_jobs', filter: `id=eq.${activeJob}` },
        (payload) => {
          const job = payload.new as { status: string; id: string }
          if (job.status === 'completed' || job.status === 'failed') setActiveJob(null)
        }
      )
      .subscribe()
    return () => { supabase.removeChannel(channel) }
  }, [activeJob, supabase])

  const handleRunTool = useCallback(async (toolId: string, inputs: Record<string, unknown>) => {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return
    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
    const res = await fetch(`${apiUrl}/api/v1/workflow-tools/${toolId}/run`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', 'Authorization': `Bearer ${session.access_token}` },
      body: JSON.stringify({ dataset_id: dataset.id, inputs }),
    })
    if (res.ok) {
      const { job_id } = await res.json()
      setActiveJob(job_id)
    }
  }, [dataset.id, supabase])

  // ── Measurement: pick 3D point via raycasting ───────────────────────────────
  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!measureMode || !threeRef.current || !pointDataRef.current) return
    const { THREE, camera, geometry } = threeRef.current
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    const ndc = new THREE.Vector2(
      ((e.clientX - rect.left) / rect.width) * 2 - 1,
      -((e.clientY - rect.top) / rect.height) * 2 + 1
    )

    // Raycast against point cloud bounding sphere for approximate pick
    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    raycaster.params.Points = { threshold: 2 }

    const positions = geometry.attributes.position.array as Float32Array
    const count = positions.length / 3

    // Find closest point to ray
    let bestDist = Infinity
    let bestIdx = -1
    for (let i = 0; i < count; i++) {
      const pt = new THREE.Vector3(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
      const dist = raycaster.ray.distanceToPoint(pt)
      if (dist < bestDist) { bestDist = dist; bestIdx = i }
    }
    if (bestIdx < 0) return

    const picked: [number, number, number] = [
      positions[bestIdx * 3],
      positions[bestIdx * 3 + 1],
      positions[bestIdx * 3 + 2],
    ]

    const next = [...pendingPoints, picked]

    if (measureMode === 'distance') {
      if (next.length === 2) {
        const [a, b] = next
        const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2]
        const dist = Math.sqrt(dx * dx + dy * dy + dz * dz)
        setMeasurements(ms => [...ms, {
          id: crypto.randomUUID(),
          type: 'distance',
          points: [a, b],
          value: dist,
        }])
        setPendingPoints([])
      } else {
        setPendingPoints(next as [number, number, number][])
      }
    } else if (measureMode === 'height') {
      if (next.length === 2) {
        const [a, b] = next
        const heightDiff = Math.abs(b[2] - a[2])
        setMeasurements(ms => [...ms, {
          id: crypto.randomUUID(),
          type: 'height',
          points: [a, b],
          value: heightDiff,
        }])
        setPendingPoints([])
      } else {
        setPendingPoints(next as [number, number, number][])
      }
    }
  }, [measureMode, pendingPoints])

  const togglePanel = (panel: 'render' | 'measure' | 'classify' | 'map') => {
    if (panel === 'map') {
      setMapOpen(v => !v)
      setActivePanel(prev => prev === 'map' ? null : 'map')
      return
    }
    setActivePanel(prev => prev === panel ? null : panel)
  }

  const pd = pointDataRef.current

  return (
    <div ref={containerRef} className="relative w-full h-screen bg-black overflow-hidden flex">
      {/* ── 3D Viewer (left side, or full width when map closed) ── */}
      <div className={`relative ${mapOpen ? 'w-1/2' : 'w-full'} h-full transition-all duration-300`}>
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full"
          onClick={handleCanvasClick}
          style={{ cursor: measureMode ? 'crosshair' : 'default' }}
        />

        {/* Loading overlay */}
        {!viewerReady && (
          <div className="absolute inset-0 flex items-center justify-center bg-black z-10">
            <div className="text-center">
              <div className="w-8 h-8 border border-white border-t-transparent rounded-full animate-spin mx-auto mb-4" />
              <p className="text-[#555] text-sm">{loadingStatus}</p>
            </div>
          </div>
        )}

        {/* Top bar */}
        <div className="absolute top-0 left-0 right-0 h-12 flex items-center justify-between px-4 bg-gradient-to-b from-black/80 to-transparent z-20 pointer-events-none">
          <div className="flex items-center gap-3 pointer-events-auto">
            <a href="/datasets" className="text-[#555] hover:text-white transition-colors text-sm">←</a>
            <span className="text-white text-sm font-medium">{dataset.name}</span>
            {dataset.pointCount && (
              <span className="text-[#444] text-xs">{(dataset.pointCount / 1_000_000).toFixed(1)}M pts</span>
            )}
          </div>
          <div className="flex items-center gap-2 pointer-events-auto">
            {/* Viewer mode toggle: Three.js ↔ Cesium */}
            <div className="flex items-center bg-[#111] border border-[#222] rounded-lg overflow-hidden">
              <button
                onClick={() => setCesiumMode(false)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  !cesiumMode ? 'bg-white text-black' : 'text-[#666] hover:text-white'
                }`}
              >
                3D
              </button>
              <button
                onClick={() => setCesiumMode(true)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  cesiumMode ? 'bg-white text-black' : 'text-[#666] hover:text-white'
                }`}
              >
                Cesium
              </button>
            </div>
            <button
              onClick={() => setChatOpen(v => !v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${chatOpen ? 'bg-white text-black' : 'bg-[#111] text-[#888] hover:text-white border border-[#222]'}`}
            >
              AI Assistant
            </button>
          </div>
        </div>

        {/* ── Left icon toolbar ── */}
        <div className="absolute left-4 top-1/2 -translate-y-1/2 z-20 flex flex-col gap-2">
          {/* Render mode */}
          <ToolbarIconBtn
            icon="🎨"
            label="Render Mode"
            active={activePanel === 'render'}
            onClick={() => togglePanel('render')}
          />
          {/* Measure distance */}
          <ToolbarIconBtn
            icon="📏"
            label="Measure Distance"
            active={measureMode === 'distance'}
            onClick={() => {
              setMeasureMode(m => m === 'distance' ? null : 'distance')
              setPendingPoints([])
              setActivePanel('measure')
            }}
          />
          {/* Measure height */}
          <ToolbarIconBtn
            icon="↕️"
            label="Measure Height"
            active={measureMode === 'height'}
            onClick={() => {
              setMeasureMode(m => m === 'height' ? null : 'height')
              setPendingPoints([])
              setActivePanel('measure')
            }}
          />
          {/* Classification */}
          <ToolbarIconBtn
            icon="🏷️"
            label="Classifications"
            active={activePanel === 'classify'}
            onClick={() => togglePanel('classify')}
          />
          {/* Map */}
          <ToolbarIconBtn
            icon="🗺️"
            label="2D Map"
            active={mapOpen}
            onClick={() => togglePanel('map')}
          />

          {/* Workflow tools (existing) */}
          {workflowTools.map(tool => (
            <button
              key={tool.id}
              title={tool.name}
              disabled={!!activeJob}
              className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all border bg-black/70 text-[#888] border-[#222] hover:border-[#444] hover:text-white ${activeJob ? 'opacity-40 cursor-not-allowed' : ''}`}
            >
              {tool.icon}
            </button>
          ))}
        </div>

        {/* ── Side panels ── */}
        {activePanel === 'render' && (
          <RenderModePanel
            mode={renderMode}
            onChange={(m) => { setRenderMode(m); recolour() }}
            onClose={() => setActivePanel(null)}
          />
        )}

        {activePanel === 'measure' && (
          <MeasurePanel
            measurements={measurements}
            pendingPoints={pendingPoints}
            measureMode={measureMode}
            onClear={() => setMeasurements([])}
            onClose={() => { setActivePanel(null); setMeasureMode(null); setPendingPoints([]) }}
          />
        )}

        {activePanel === 'classify' && pd?.hasClassification && (
          <ClassificationPanel
            classifications={pd.classifications}
            visibleClasses={visibleClasses}
            onChange={(next) => { setVisibleClasses(next) }}
            onClose={() => setActivePanel(null)}
          />
        )}

        {/* ── Cesium viewer overlay (replaces Three.js canvas when active) ── */}
        {cesiumMode && (
          <div className="absolute inset-0 z-30">
            <Suspense fallback={
              <div className="absolute inset-0 flex items-center justify-center bg-[#080a0f]">
                <div className="w-8 h-8 border-2 border-white/20 border-t-white/80 rounded-full animate-spin" />
              </div>
            }>
              <CesiumViewer
                copcUrl={dataset.copcUrl}
                pointCount={dataset.pointCount ?? undefined}
                crsEpsg={dataset.crsEpsg ?? undefined}
                boundingBox={dataset.boundingBox as any}
                renderMode={renderMode}
                measurements={measurements}
                onMeasurementAdd={(m) => setMeasurements(ms => [...ms, m])}
                visibleClasses={visibleClasses}
                isMeasuring={!!measureMode}
                measureType={measureMode ?? 'distance'}
              />
            </Suspense>
          </div>
        )}

        {/* Controls hint */}
        {viewerReady && (
          <div className="absolute bottom-4 left-16 z-20 text-[#333] text-xs space-y-0.5">
            {measureMode
              ? <p className="text-[#888]">Click to place point {pendingPoints.length + 1}/2</p>
              : <p>Drag to rotate · Scroll to zoom</p>
            }
          </div>
        )}

        {/* Workflow toolbar (existing) */}
        <ViewerToolbar
          tools={[]}
          onRunTool={handleRunTool}
          activeJobId={activeJob}
        />

        {chatOpen && (
          <AiChatPanel
            datasetId={dataset.id}
            datasetName={dataset.name}
            onClose={() => setChatOpen(false)}
            onJobStarted={(jobId) => setActiveJob(jobId)}
          />
        )}

        {activeJob && (
          <JobProgressOverlay
            jobId={activeJob}
            onComplete={() => setActiveJob(null)}
          />
        )}
      </div>

      {/* ── 2D Map panel (right side) ── */}
      {mapOpen && pd && (
        <div className="w-1/2 h-full border-l border-[#222] relative">
          <MapPanel
            centerLat={pd.centerLat}
            centerLon={pd.centerLon}
            crsEpsg={dataset.crsEpsg}
            onClose={() => { setMapOpen(false); setActivePanel(null) }}
          />
        </div>
      )}
    </div>
  )
}

// ── Small reusable icon button ─────────────────────────────────────────────────
function ToolbarIconBtn({ icon, label, active, onClick }: {
  icon: string
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <button
      onClick={onClick}
      title={label}
      className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all border ${
        active
          ? 'bg-white text-black border-white'
          : 'bg-black/70 text-[#888] border-[#222] hover:border-[#444] hover:text-white'
      }`}
    >
      {icon}
    </button>
  )
}
