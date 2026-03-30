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
import { useViewerStore } from '@/lib/stores/viewerStore'

// Lazy-load heavy viewer components to avoid SSR issues
const CesiumViewer = lazy(() => import('@/components/viewer/CesiumViewer'))
const PanoramicViewer = lazy(() => import('@/components/viewer/PanoramicViewer'))

// ─── LAS classification labels (ASPRS standard) ──────────────────────────────
const LAS_CLASSES: Record<number, string> = {
  0: 'Never Classified', 1: 'Unclassified', 2: 'Ground',
  3: 'Low Vegetation', 4: 'Medium Vegetation', 5: 'High Vegetation',
  6: 'Building', 7: 'Low Point (Noise)', 8: 'Reserved', 9: 'Water',
  10: 'Rail', 11: 'Road Surface', 12: 'Reserved', 13: 'Wire – Guard',
  14: 'Wire – Conductor', 15: 'Transmission Tower',
  16: 'Wire-Structure Connector', 17: 'Bridge Deck', 18: 'High Noise',
}

export type RenderMode = 'rgb' | 'intensity' | 'height'

export interface Measurement {
  id: string
  type: 'distance' | 'height'
  points: [number, number, number][]
  value: number | null
}

function heightColor(t: number): [number, number, number] {
  const stops: [number, [number, number, number]][] = [
    [0.0, [0.0, 0.0, 1.0]], [0.25, [0.0, 1.0, 1.0]],
    [0.5, [0.0, 1.0, 0.0]], [0.75, [1.0, 1.0, 0.0]], [1.0, [1.0, 0.0, 0.0]],
  ]
  for (let i = 0; i < stops.length - 1; i++) {
    const [t0, c0] = stops[i]; const [t1, c1] = stops[i + 1]
    if (t >= t0 && t <= t1) {
      const f = (t - t0) / (t1 - t0)
      return [c0[0] + f * (c1[0] - c0[0]), c0[1] + f * (c1[1] - c0[1]), c0[2] + f * (c1[2] - c0[2])]
    }
  }
  return [1, 0, 0]
}

function intensityColor(t: number): [number, number, number] { return [t, t, t] }

interface Dataset {
  id: string
  name: string
  copcUrl: string | null
  roadAssetsUrl: string | null
  status: string
  pointCount: number | null
  crsEpsg: number | null
  boundingBox: unknown
}

interface WorkflowTool {
  id: string; name: string; description: string; icon: string
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  required_inputs: Record<string, any>; n8n_workflow_id: string
}

interface ViewerClientProps { dataset: Dataset; workflowTools: WorkflowTool[] }

interface PointData {
  positions: Float32Array; rawZ: Float32Array; zMin: number; zMax: number
  rgbColors: Float32Array; intensities: Float32Array; classifications: Uint8Array
  hasRgb: boolean; hasIntensity: boolean; hasClassification: boolean
  centerLat: number | null; centerLon: number | null
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
  const [panoramicOpen, setPanoramicOpen] = useState(false)
  const [cesiumMode, setCesiumMode] = useState(false)

  // ── Zustand cross-panel state ───────────────────────────────────────────────
  const { setRoadAssetsGeoJson, activePanorama } = useViewerStore()

  // ── Refs shared with Three.js loop ──────────────────────────────────────────
  const pointDataRef = useRef<PointData | null>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const threeRef = useRef<{ THREE: any; geometry: any; material: any; pointCloud: any; scene: any; camera: any; renderer: any } | null>(null)
  const renderModeRef = useRef<RenderMode>('rgb')
  const visibleClassesRef = useRef<Set<number>>(visibleClasses)
  const supabase = createClient()

  useEffect(() => { renderModeRef.current = renderMode }, [renderMode])
  useEffect(() => { visibleClassesRef.current = visibleClasses }, [visibleClasses])

  // ── Load road assets GeoJSON into the store ─────────────────────────────────
  useEffect(() => {
    if (!dataset.roadAssetsUrl) return
    fetch(dataset.roadAssetsUrl)
      .then(r => r.ok ? r.json() : null)
      .then(data => { if (data) setRoadAssetsGeoJson(data) })
      .catch(() => {/* silently ignore */})
  }, [dataset.roadAssetsUrl, setRoadAssetsGeoJson])

  // ── Recolour geometry ────────────────────────────────────────────────────────
  const recolour = useCallback(() => {
    const pd = pointDataRef.current; const t = threeRef.current
    if (!pd || !t) return
    const { THREE, geometry } = t
    const count = pd.positions.length / 3
    const newColors = new Float32Array(count * 3)
    const mode = renderModeRef.current; const visible = visibleClassesRef.current
    for (let i = 0; i < count; i++) {
      const cls = pd.hasClassification ? pd.classifications[i] : 1
      if (!visible.has(cls)) { newColors[i * 3] = 0; newColors[i * 3 + 1] = 0; newColors[i * 3 + 2] = 0; continue }
      let r = 0, g = 0, b = 0
      if (mode === 'rgb') { r = pd.rgbColors[i * 3]; g = pd.rgbColors[i * 3 + 1]; b = pd.rgbColors[i * 3 + 2] }
      else if (mode === 'intensity') { const iv = pd.hasIntensity ? pd.intensities[i] : 0.5;[r, g, b] = intensityColor(iv) }
      else { const zRange = pd.zMax - pd.zMin; const tz = zRange > 0 ? (pd.rawZ[i] - pd.zMin) / zRange : 0.5;[r, g, b] = heightColor(tz) }
      newColors[i * 3] = r; newColors[i * 3 + 1] = g; newColors[i * 3 + 2] = b
    }
    geometry.setAttribute('color', new THREE.BufferAttribute(newColors, 3))
    geometry.attributes.color.needsUpdate = true
  }, [])

  useEffect(() => { recolour() }, [renderMode, visibleClasses, recolour])

  // ── Main Three.js initialisation ────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!canvasRef.current || !containerRef.current) return
    if (!dataset.copcUrl) { setLoadingStatus('Dataset is still processing...'); return }

    let animationId: number; let destroyed = false

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

        let positions: Float32Array, rawZ: Float32Array, rgbColors: Float32Array
        let intensities: Float32Array, classifications: Uint8Array
        let hasRgb = false, hasIntensity = false, hasClassification = false
        let zMin = Infinity, zMax = -Infinity
        let centerLat: number | null = null, centerLon: number | null = null

        if (rootNode) {
          const view = await Copc.loadPointDataView(dataset.copcUrl!, copc, rootNode)
          const count = view.pointCount
          const getX = view.getter('X'), getY = view.getter('Y'), getZ = view.getter('Z')
          hasRgb = 'Red' in view.dimensions && 'Green' in view.dimensions && 'Blue' in view.dimensions
          hasIntensity = 'Intensity' in view.dimensions
          hasClassification = 'Classification' in view.dimensions
          const getRed = hasRgb ? view.getter('Red') : null
          const getGreen = hasRgb ? view.getter('Green') : null
          const getBlue = hasRgb ? view.getter('Blue') : null
          const getIntensity = hasIntensity ? view.getter('Intensity') : null
          const getClassification = hasClassification ? view.getter('Classification') : null

          positions = new Float32Array(count * 3); rawZ = new Float32Array(count)
          rgbColors = new Float32Array(count * 3); intensities = new Float32Array(count)
          classifications = new Uint8Array(count)

          let cx = 0, cy = 0, cz = 0, intensityMax = 0
          for (let i = 0; i < count; i++) {
            const x = getX(i) as number, y = getY(i) as number, z = getZ(i) as number
            cx += x; cy += y; cz += z
            if (z < zMin) zMin = z; if (z > zMax) zMax = z
            rawZ[i] = z
            if (hasIntensity) { const iv = getIntensity!(i) as number; intensities[i] = iv; if (iv > intensityMax) intensityMax = iv }
            if (hasClassification) classifications[i] = getClassification!(i) as number
            if (hasRgb) {
              rgbColors[i * 3] = (getRed!(i) as number) / 65535
              rgbColors[i * 3 + 1] = (getGreen!(i) as number) / 65535
              rgbColors[i * 3 + 2] = (getBlue!(i) as number) / 65535
            } else { rgbColors[i * 3] = 0.6; rgbColors[i * 3 + 1] = 0.6; rgbColors[i * 3 + 2] = 0.6 }
          }
          if (intensityMax > 0) for (let i = 0; i < count; i++) intensities[i] /= intensityMax
          cx /= count; cy /= count; cz /= count

          // Attempt CRS-based lat/lon conversion (simplified for EPSG:28355 / MGA55)
          if (dataset.crsEpsg === 28355 || dataset.crsEpsg === 28354) {
            centerLat = -33.8688 + (cy - 6_150_000) / 111_000
            centerLon = 151.2093 + (cx - 334_000) / (111_000 * Math.cos(-33.8688 * Math.PI / 180))
          } else if (dataset.crsEpsg && dataset.crsEpsg >= 32600 && dataset.crsEpsg <= 32660) {
            centerLat = cy / 111_000 - 90; centerLon = cx / 111_000 - 180
          }

          for (let i = 0; i < count; i++) {
            positions[i * 3] = (getX(i) as number) - cx
            positions[i * 3 + 1] = (getY(i) as number) - cy
            positions[i * 3 + 2] = (getZ(i) as number) - cz
          }

          pointDataRef.current = { positions, rawZ, zMin, zMax, rgbColors, intensities, classifications, hasRgb, hasIntensity, hasClassification, centerLat, centerLon }
        } else {
          positions = new Float32Array(0); rawZ = new Float32Array(0); rgbColors = new Float32Array(0)
          intensities = new Float32Array(0); classifications = new Uint8Array(0)
          pointDataRef.current = { positions, rawZ, zMin: 0, zMax: 0, rgbColors, intensities, classifications, hasRgb, hasIntensity, hasClassification, centerLat, centerLon }
        }

        if (destroyed) return
        setLoadingStatus('Building scene...')

        const canvas = canvasRef.current!
        const renderer = new THREE.WebGLRenderer({ canvas, antialias: false })
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        renderer.setSize(canvas.clientWidth, canvas.clientHeight)

        const scene = new THREE.Scene()
        scene.background = new THREE.Color(0x080a0f)

        const camera = new THREE.PerspectiveCamera(60, canvas.clientWidth / canvas.clientHeight, 0.1, 100000)
        const pd = pointDataRef.current!
        const spread = pd.positions.length > 0 ? Math.max(zMax - zMin, 10) : 50
        camera.position.set(0, -spread * 1.5, spread * 0.8)
        camera.lookAt(0, 0, 0)

        const geometry = new THREE.BufferGeometry()
        if (pd.positions.length > 0) {
          geometry.setAttribute('position', new THREE.BufferAttribute(pd.positions, 3))
          geometry.setAttribute('color', new THREE.BufferAttribute(pd.rgbColors.slice(), 3))
        }

        const material = new THREE.PointsMaterial({ size: 0.05, vertexColors: true, sizeAttenuation: true })
        const pointCloud = new THREE.Points(geometry, material)
        scene.add(pointCloud)

        threeRef.current = { THREE, geometry, material, pointCloud, scene, camera, renderer }
        recolour()

        // Orbit controls (mouse drag / scroll)
        let isDown = false, lastX = 0, lastY = 0, theta = 0, phi = Math.PI / 4, radius = spread * 2
        canvas.addEventListener('mousedown', (e) => { isDown = true; lastX = e.clientX; lastY = e.clientY })
        canvas.addEventListener('mouseup', () => { isDown = false })
        canvas.addEventListener('mousemove', (e) => {
          if (!isDown) return
          const dx = e.clientX - lastX, dy = e.clientY - lastY
          theta -= dx * 0.005; phi = Math.max(0.05, Math.min(Math.PI - 0.05, phi - dy * 0.005))
          lastX = e.clientX; lastY = e.clientY
        })
        canvas.addEventListener('wheel', (e) => { radius = Math.max(1, radius + e.deltaY * 0.05) }, { passive: true })

        const resize = () => {
          if (!canvas) return
          renderer.setSize(canvas.clientWidth, canvas.clientHeight)
          camera.aspect = canvas.clientWidth / canvas.clientHeight
          camera.updateProjectionMatrix()
        }
        window.addEventListener('resize', resize)

        const animate = () => {
          animationId = requestAnimationFrame(animate)
          camera.position.set(
            radius * Math.sin(phi) * Math.sin(theta),
            radius * Math.sin(phi) * Math.cos(theta),
            radius * Math.cos(phi)
          )
          camera.lookAt(0, 0, 0)
          renderer.render(scene, camera)
        }
        animate()
        setViewerReady(true)
        setLoadingStatus('')

        return () => {
          destroyed = true
          cancelAnimationFrame(animationId)
          window.removeEventListener('resize', resize)
          renderer.dispose()
          geometry.dispose()
          material.dispose()
        }
      } catch (err) {
        console.error('Viewer init error:', err)
        setLoadingStatus('Failed to load point cloud data.')
      }
    }

    const cleanup = init()
    return () => { destroyed = true; cleanup.then(fn => fn?.()) }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dataset.copcUrl])

  // ── Supabase Realtime: watch job progress ───────────────────────────────────
  useEffect(() => {
    if (!activeJob) return
    const channel = supabase
      .channel(`job-${activeJob}`)
      .on('postgres_changes', { event: 'UPDATE', schema: 'public', table: 'processing_jobs', filter: `id=eq.${activeJob}` },
        (payload) => { if (payload.new.status === 'completed' || payload.new.status === 'failed') setActiveJob(null) }
      ).subscribe()
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
    if (res.ok) { const { job_id } = await res.json(); setActiveJob(job_id) }
  }, [dataset.id, supabase])

  // ── Measurement: pick 3D point via raycasting ───────────────────────────────
  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    if (!measureMode || !threeRef.current || !pointDataRef.current) return
    const { THREE, camera, geometry } = threeRef.current
    const canvas = canvasRef.current!
    const rect = canvas.getBoundingClientRect()
    const ndc = new THREE.Vector2(((e.clientX - rect.left) / rect.width) * 2 - 1, -((e.clientY - rect.top) / rect.height) * 2 + 1)
    const raycaster = new THREE.Raycaster()
    raycaster.setFromCamera(ndc, camera)
    raycaster.params.Points = { threshold: 2 }
    const positions = geometry.attributes.position.array as Float32Array
    const count = positions.length / 3
    let bestDist = Infinity, bestIdx = -1
    for (let i = 0; i < count; i++) {
      const pt = new THREE.Vector3(positions[i * 3], positions[i * 3 + 1], positions[i * 3 + 2])
      const dist = raycaster.ray.distanceToPoint(pt)
      if (dist < bestDist) { bestDist = dist; bestIdx = i }
    }
    if (bestIdx < 0) return
    const picked: [number, number, number] = [positions[bestIdx * 3], positions[bestIdx * 3 + 1], positions[bestIdx * 3 + 2]]
    const next = [...pendingPoints, picked]
    if (measureMode === 'distance') {
      if (next.length === 2) {
        const [a, b] = next; const dx = b[0] - a[0], dy = b[1] - a[1], dz = b[2] - a[2]
        setMeasurements(ms => [...ms, { id: crypto.randomUUID(), type: 'distance', points: [a, b], value: Math.sqrt(dx * dx + dy * dy + dz * dz) }])
        setPendingPoints([])
      } else setPendingPoints(next as [number, number, number][])
    } else if (measureMode === 'height') {
      if (next.length === 2) {
        const [a, b] = next
        setMeasurements(ms => [...ms, { id: crypto.randomUUID(), type: 'height', points: [a, b], value: Math.abs(b[2] - a[2]) }])
        setPendingPoints([])
      } else setPendingPoints(next as [number, number, number][])
    }
  }, [measureMode, pendingPoints])

  const togglePanel = (panel: 'render' | 'measure' | 'classify' | 'map') => {
    if (panel === 'map') { setMapOpen(v => !v); setActivePanel(prev => prev === 'map' ? null : 'map'); return }
    setActivePanel(prev => prev === panel ? null : panel)
  }

  const pd = pointDataRef.current

  // ── Compute layout widths ───────────────────────────────────────────────────
  const panelCount = (mapOpen ? 1 : 0) + (panoramicOpen ? 1 : 0)
  const viewerWidth = panelCount === 2 ? 'w-1/3' : panelCount === 1 ? 'w-1/2' : 'w-full'
  const sideWidth = panelCount === 2 ? 'w-1/3' : 'w-1/2'

  return (
    <div ref={containerRef} className="relative w-full h-screen bg-black overflow-hidden flex">

      {/* ── 3D Viewer (left panel) ── */}
      <div className={`relative ${viewerWidth} h-full transition-all duration-300`}>
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
            {/* Viewer mode toggle */}
            <div className="flex items-center bg-[#111] border border-[#222] rounded-lg overflow-hidden">
              <button onClick={() => setCesiumMode(false)} className={`px-3 py-1.5 text-xs font-medium transition-colors ${!cesiumMode ? 'bg-white text-black' : 'text-[#666] hover:text-white'}`}>3D</button>
              <button onClick={() => setCesiumMode(true)} className={`px-3 py-1.5 text-xs font-medium transition-colors ${cesiumMode ? 'bg-white text-black' : 'text-[#666] hover:text-white'}`}>Cesium</button>
            </div>
            <button
              onClick={() => setChatOpen(v => !v)}
              className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${chatOpen ? 'bg-white text-black' : 'bg-[#111] text-[#888] hover:text-white border border-[#222]'}`}
            >AI Assistant</button>
          </div>
        </div>

        {/* ── Left icon toolbar ── */}
        <div className="absolute left-4 top-1/2 -translate-y-1/2 z-20 flex flex-col gap-2">
          <ToolbarIconBtn icon="🎨" label="Render Mode" active={activePanel === 'render'} onClick={() => togglePanel('render')} />
          <ToolbarIconBtn icon="📏" label="Measure Distance" active={measureMode === 'distance'} onClick={() => { setMeasureMode(m => m === 'distance' ? null : 'distance'); setPendingPoints([]); setActivePanel('measure') }} />
          <ToolbarIconBtn icon="↕️" label="Measure Height" active={measureMode === 'height'} onClick={() => { setMeasureMode(m => m === 'height' ? null : 'height'); setPendingPoints([]); setActivePanel('measure') }} />
          <ToolbarIconBtn icon="🏷️" label="Classifications" active={activePanel === 'classify'} onClick={() => togglePanel('classify')} />
          <ToolbarIconBtn icon="🗺️" label="2D Map" active={mapOpen} onClick={() => togglePanel('map')} />
          <ToolbarIconBtn icon="🌐" label="360° Panorama" active={panoramicOpen} onClick={() => setPanoramicOpen(v => !v)} />
          {workflowTools.map(tool => (
            <button key={tool.id} title={tool.name} disabled={!!activeJob}
              className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all border bg-black/70 text-[#888] border-[#222] hover:border-[#444] hover:text-white ${activeJob ? 'opacity-40 cursor-not-allowed' : ''}`}>
              {tool.icon}
            </button>
          ))}
        </div>

        {/* ── Side panels ── */}
        {activePanel === 'render' && <RenderModePanel mode={renderMode} onChange={(m) => { setRenderMode(m); recolour() }} onClose={() => setActivePanel(null)} />}
        {activePanel === 'measure' && <MeasurePanel measurements={measurements} pendingPoints={pendingPoints} measureMode={measureMode} onClear={() => setMeasurements([])} onClose={() => { setActivePanel(null); setMeasureMode(null); setPendingPoints([]) }} />}
        {activePanel === 'classify' && pd?.hasClassification && <ClassificationPanel classifications={pd.classifications} visibleClasses={visibleClasses} onChange={(next) => { setVisibleClasses(next) }} onClose={() => setActivePanel(null)} />}

        {/* ── Cesium viewer overlay ── */}
        {cesiumMode && (
          <div className="absolute inset-0 z-30">
            <Suspense fallback={<div className="absolute inset-0 flex items-center justify-center bg-[#080a0f]"><div className="w-8 h-8 border-2 border-white/20 border-t-white/80 rounded-full animate-spin" /></div>}>
              <CesiumViewer
                copcUrl={dataset.copcUrl} pointCount={dataset.pointCount ?? undefined}
                crsEpsg={dataset.crsEpsg ?? undefined} boundingBox={dataset.boundingBox as any}
                renderMode={renderMode} measurements={measurements}
                onMeasurementAdd={(m) => setMeasurements(ms => [...ms, m])}
                visibleClasses={visibleClasses} isMeasuring={!!measureMode} measureType={measureMode ?? 'distance'}
              />
            </Suspense>
          </div>
        )}

        {viewerReady && (
          <div className="absolute bottom-4 left-16 z-20 text-[#333] text-xs space-y-0.5">
            {measureMode ? <p className="text-[#888]">Click to place point {pendingPoints.length + 1}/2</p> : <p>Drag to rotate · Scroll to zoom</p>}
          </div>
        )}

        <ViewerToolbar tools={[]} onRunTool={handleRunTool} activeJobId={activeJob} />

        {chatOpen && <AiChatPanel datasetId={dataset.id} datasetName={dataset.name} onClose={() => setChatOpen(false)} onJobStarted={(jobId) => setActiveJob(jobId)} />}
        {activeJob && <JobProgressOverlay jobId={activeJob} onComplete={() => setActiveJob(null)} />}
      </div>

      {/* ── 2D Map panel (middle or right) ── */}
      {mapOpen && pd && (
        <div className={`${sideWidth} h-full border-l border-[#222] relative`}>
          <MapPanel
            centerLat={pd.centerLat} centerLon={pd.centerLon}
            crsEpsg={dataset.crsEpsg} datasetId={dataset.id}
            onClose={() => { setMapOpen(false); setActivePanel(null) }}
          />
        </div>
      )}

      {/* ── 360° Panoramic panel (rightmost) ── */}
      {panoramicOpen && (
        <div className={`${sideWidth} h-full border-l border-[#222] relative bg-gray-950`}>
          <Suspense fallback={<div className="absolute inset-0 flex items-center justify-center"><div className="w-8 h-8 border-2 border-white/20 border-t-white/80 rounded-full animate-spin" /></div>}>
            <PanoramicViewer
              datasetId={dataset.id}
              initialImage={activePanorama ?? undefined}
              onClose={() => setPanoramicOpen(false)}
            />
          </Suspense>
        </div>
      )}
    </div>
  )
}

function ToolbarIconBtn({ icon, label, active, onClick }: { icon: string; label: string; active: boolean; onClick: () => void }) {
  return (
    <button onClick={onClick} title={label}
      className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all border ${active ? 'bg-white text-black border-white' : 'bg-black/70 text-[#888] border-[#222] hover:border-[#444] hover:text-white'}`}>
      {icon}
    </button>
  )
}
