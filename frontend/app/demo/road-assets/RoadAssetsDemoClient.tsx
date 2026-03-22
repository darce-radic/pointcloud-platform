'use client'

import { useEffect, useRef, useState, useCallback, lazy, Suspense } from 'react'
import Link from 'next/link'
import { POINT_CLOUD_DATA } from './pointCloudData'

const PointCloud3DViewer = lazy(() => import('./PointCloud3DViewer'))

// ── Types ─────────────────────────────────────────────────────────────────────
type AssetType =
  | 'road_surface'
  | 'road_centreline'
  | 'road_marking'
  | 'kerb'
  | 'traffic_sign'
  | 'drain_manhole'

interface GeoFeature {
  type: 'Feature'
  geometry:
    | { type: 'Polygon'; coordinates: number[][][] }
    | { type: 'LineString'; coordinates: number[][] }
    | { type: 'Point'; coordinates: number[] }
  properties: Record<string, string | number | boolean | null>
}

// ── Embedded GeoJSON data ─────────────────────────────────────────────────────
function buildDemoFeatures(): GeoFeature[] {
  const features: GeoFeature[] = []

  // Road surface polygon
  features.push({
    type: 'Feature',
    geometry: {
      type: 'Polygon',
      coordinates: [[[0, -4], [50, -4], [50, 4], [0, 4], [0, -4]]],
    },
    properties: {
      asset_type: 'road_surface',
      area_m2: 390.9,
      point_count: 12746,
      confidence: 0.95,
    },
  })

  // Road centreline (slight curve for realism)
  const cl: number[][] = []
  for (let x = 0; x <= 50; x += 0.5)
    cl.push([x, Math.sin(x * 0.08) * 0.15])
  features.push({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: cl },
    properties: {
      asset_type: 'road_centreline',
      length_m: 49.0,
      confidence: 0.92,
    },
  })

  // Road markings
  const mkCentre: number[][] = []
  const mkLeft: number[][] = []
  const mkRight: number[][] = []
  for (let x = 0; x <= 50; x += 0.5) {
    mkCentre.push([x, Math.sin(x * 0.08) * 0.15])
    mkLeft.push([x, 3.5 + Math.sin(x * 0.08) * 0.1])
    mkRight.push([x, -3.5 + Math.sin(x * 0.08) * 0.1])
  }
  features.push({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: mkCentre },
    properties: {
      asset_type: 'road_marking',
      marking_type: 'centre_line',
      length_m: 49.2,
      mean_intensity: 3840.5,
      confidence: 0.88,
    },
  })
  features.push({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: mkLeft },
    properties: {
      asset_type: 'road_marking',
      marking_type: 'left_edge_line',
      length_m: 49.1,
      mean_intensity: 3612.3,
      confidence: 0.87,
    },
  })
  features.push({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: mkRight },
    properties: {
      asset_type: 'road_marking',
      marking_type: 'right_edge_line',
      length_m: 49.1,
      mean_intensity: 3598.7,
      confidence: 0.87,
    },
  })

  // Kerbs
  const kl: number[][] = []
  const kr: number[][] = []
  for (let x = 0; x <= 50; x += 0.5) {
    kl.push([x, 4.5])
    kr.push([x, -4.5])
  }
  features.push({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: kl },
    properties: {
      asset_type: 'kerb',
      side: 'left_kerb',
      length_m: 50.0,
      mean_height_m: 0.12,
      confidence: 0.91,
    },
  })
  features.push({
    type: 'Feature',
    geometry: { type: 'LineString', coordinates: kr },
    properties: {
      asset_type: 'kerb',
      side: 'right_kerb',
      length_m: 50.0,
      mean_height_m: 0.12,
      confidence: 0.91,
    },
  })

  // Traffic signs
  features.push({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [10, 5.8] },
    properties: {
      asset_type: 'traffic_sign',
      sign_id: 'SIGN_001',
      pole_height_m: 3.2,
      sign_top_m: 3.2,
      mean_intensity: 4200.0,
      confidence: 0.85,
    },
  })
  features.push({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [35, 5.8] },
    properties: {
      asset_type: 'traffic_sign',
      sign_id: 'SIGN_002',
      pole_height_m: 3.2,
      sign_top_m: 3.2,
      mean_intensity: 4150.0,
      confidence: 0.85,
    },
  })

  // Drains
  features.push({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [15, 3.8] },
    properties: {
      asset_type: 'drain_manhole',
      drain_id: 'DRAIN_001',
      radius_m: 0.3,
      z_elevation_m: 0.002,
      point_count: 48,
      confidence: 0.78,
    },
  })
  features.push({
    type: 'Feature',
    geometry: { type: 'Point', coordinates: [30, 3.8] },
    properties: {
      asset_type: 'drain_manhole',
      drain_id: 'DRAIN_002',
      radius_m: 0.28,
      z_elevation_m: -0.001,
      point_count: 44,
      confidence: 0.78,
    },
  })

  return features
}

// ── Colours ───────────────────────────────────────────────────────────────────
const COLORS: Record<AssetType, string> = {
  road_surface: '#a3a3a3',
  road_centreline: '#f59e0b',
  road_marking: '#ffffff',
  kerb: '#fb923c',
  traffic_sign: '#ef4444',
  drain_manhole: '#38bdf8',
}

const LABELS: Record<AssetType, string> = {
  road_surface: 'Road Surface',
  road_centreline: 'Centreline',
  road_marking: 'Road Marking',
  kerb: 'Kerb',
  traffic_sign: 'Traffic Sign',
  drain_manhole: 'Drain / Manhole',
}

const DRAW_ORDER: AssetType[] = [
  'road_surface',
  'road_centreline',
  'kerb',
  'road_marking',
  'drain_manhole',
  'traffic_sign',
]

const PIPELINE_STEPS = [
  { name: 'Ground Classification', time: '0.3s', desc: 'Separates ground from non-ground returns using progressive morphological filter' },
  { name: 'Road Surface Extraction', time: '0.8s', desc: 'Identifies paved road surface via NDVI + reflectance thresholding' },
  { name: 'Marking Detection', time: '1.2s', desc: 'Detects high-intensity retroreflective road markings' },
  { name: 'Kerb Detection', time: '0.5s', desc: 'Finds height discontinuities at road edges using local normal estimation' },
  { name: 'Sign Detection', time: '0.9s', desc: 'Clusters vertical high-intensity returns above 2m using PointPillars' },
  { name: 'Drain Detection', time: '0.4s', desc: 'Identifies circular low-intensity depressions in road surface' },
]

// ── Tooltip data ──────────────────────────────────────────────────────────────
interface TooltipState {
  visible: boolean
  x: number
  y: number
  title: string
  props: [string, string][]
}

// ── Main component ────────────────────────────────────────────────────────────
export default function RoadAssetsDemoClient() {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)
  const features = useRef<GeoFeature[]>(buildDemoFeatures())

  const [visibleLayers, setVisibleLayers] = useState<Set<AssetType>>(
    new Set(DRAW_ORDER)
  )
  const [tooltip, setTooltip] = useState<TooltipState>({
    visible: false, x: 0, y: 0, title: '', props: [],
  })
  const [hoveredAsset, setHoveredAsset] = useState<AssetType | null>(null)
  const [activeStep, setActiveStep] = useState<number | null>(null)
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')

  // Transform state
  const transform = useRef({ x: 0, y: 0, scale: 1 })
  const dragging = useRef(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const bounds = useRef({ minX: 0, maxX: 50, minY: -6, maxY: 7 })

  // ── Coordinate helpers ──────────────────────────────────────────────────────
  const toScreen = useCallback(
    (wx: number, wy: number, canvas: HTMLCanvasElement): [number, number] => {
      const t = transform.current
      return [wx * t.scale + t.x, canvas.height - (wy * t.scale + t.y)]
    },
    []
  )

  const fitView = useCallback((canvas: HTMLCanvasElement) => {
    const b = bounds.current
    const W = canvas.width, H = canvas.height
    const pad = 80
    const scaleX = (W - pad * 2) / (b.maxX - b.minX)
    const scaleY = (H - pad * 2) / (b.maxY - b.minY)
    const s = Math.min(scaleX, scaleY)
    transform.current = {
      scale: s,
      x: (W - (b.maxX - b.minX) * s) / 2 - b.minX * s,
      y: (H - (b.maxY - b.minY) * s) / 2 - b.minY * s,
    }
  }, [])

  // ── Draw ────────────────────────────────────────────────────────────────────
  const draw = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    const ctx = canvas.getContext('2d')
    if (!ctx) return

    ctx.clearRect(0, 0, canvas.width, canvas.height)

    // ── Point cloud backdrop ──────────────────────────────────────────────────
    // Render raw LiDAR points as small coloured dots behind the vector assets
    const ptRadius = Math.max(1, transform.current.scale * 0.18)
    for (const pt of POINT_CLOUD_DATA) {
      const [sx, sy] = toScreen(pt[0], pt[1], canvas)
      // Skip points outside viewport (with margin)
      if (sx < -4 || sx > canvas.width + 4 || sy < -4 || sy > canvas.height + 4) continue
      ctx.beginPath()
      ctx.arc(sx, sy, ptRadius, 0, Math.PI * 2)
      ctx.fillStyle = `rgba(${pt[2]},${pt[3]},${pt[4]},${(pt[5] / 255).toFixed(2)})`
      ctx.fill()
    }

    // Subtle grid
    ctx.strokeStyle = 'rgba(255,255,255,0.03)'
    ctx.lineWidth = 1
    const gs = 5 * transform.current.scale
    if (gs > 8) {
      for (let gx = 0; gx < canvas.width; gx += gs) {
        ctx.beginPath(); ctx.moveTo(gx, 0); ctx.lineTo(gx, canvas.height); ctx.stroke()
      }
      for (let gy = 0; gy < canvas.height; gy += gs) {
        ctx.beginPath(); ctx.moveTo(0, gy); ctx.lineTo(canvas.width, gy); ctx.stroke()
      }
    }

    for (const layerType of DRAW_ORDER) {
      if (!visibleLayers.has(layerType)) continue
      for (const f of features.current) {
        if (f.properties.asset_type !== layerType) continue
        const color = COLORS[layerType]
        const isHovered = hoveredAsset === layerType
        const alpha = isHovered ? 1 : 0.85

        ctx.save()
        ctx.globalAlpha = alpha

        if (f.geometry.type === 'Polygon') {
          const ring = f.geometry.coordinates[0]
          ctx.beginPath()
          const [sx, sy] = toScreen(ring[0][0], ring[0][1], canvas)
          ctx.moveTo(sx, sy)
          for (let i = 1; i < ring.length; i++) {
            const [px, py] = toScreen(ring[i][0], ring[i][1], canvas)
            ctx.lineTo(px, py)
          }
          ctx.closePath()
          ctx.fillStyle = isHovered ? color + '30' : color + '18'
          ctx.fill()
          ctx.strokeStyle = color + '60'
          ctx.lineWidth = 1
          ctx.stroke()
        } else if (f.geometry.type === 'LineString') {
          const coords = f.geometry.coordinates
          ctx.beginPath()
          const [sx, sy] = toScreen(coords[0][0], coords[0][1], canvas)
          ctx.moveTo(sx, sy)
          for (let i = 1; i < coords.length; i++) {
            const [px, py] = toScreen(coords[i][0], coords[i][1], canvas)
            ctx.lineTo(px, py)
          }
          let lw = 1.5
          const dash: number[] = []
          if (layerType === 'road_centreline') {
            lw = 1.5
            const d = 6 * transform.current.scale / 10
            dash.push(d, d * 0.6)
          }
          if (layerType === 'kerb') lw = 2.5
          if (layerType === 'road_marking') lw = 1.5
          ctx.strokeStyle = color
          ctx.lineWidth = isHovered ? lw + 1 : lw
          ctx.setLineDash(dash)
          ctx.stroke()
          ctx.setLineDash([])
        } else if (f.geometry.type === 'Point') {
          const [px, py] = toScreen(
            f.geometry.coordinates[0],
            f.geometry.coordinates[1],
            canvas
          )
          const r = layerType === 'traffic_sign' ? 8 : 6
          // Glow
          const grd = ctx.createRadialGradient(px, py, 0, px, py, r + 8)
          grd.addColorStop(0, color + '40')
          grd.addColorStop(1, color + '00')
          ctx.beginPath()
          ctx.arc(px, py, r + 8, 0, Math.PI * 2)
          ctx.fillStyle = grd
          ctx.fill()
          // Circle
          ctx.beginPath()
          ctx.arc(px, py, r, 0, Math.PI * 2)
          ctx.fillStyle = color
          ctx.fill()
          ctx.strokeStyle = 'rgba(0,0,0,0.6)'
          ctx.lineWidth = 1.5
          ctx.stroke()
          // Icon
          ctx.fillStyle = '#000'
          ctx.font = `bold ${r - 1}px system-ui`
          ctx.textAlign = 'center'
          ctx.textBaseline = 'middle'
          ctx.fillText(layerType === 'traffic_sign' ? '▲' : '◉', px, py)
        }
        ctx.restore()
      }
    }
  }, [visibleLayers, hoveredAsset, toScreen])

  // ── Resize ──────────────────────────────────────────────────────────────────
  useEffect(() => {
    const canvas = canvasRef.current
    const wrap = wrapRef.current
    if (!canvas || !wrap) return
    const resize = () => {
      canvas.width = wrap.clientWidth
      canvas.height = wrap.clientHeight
      fitView(canvas)
      draw()
    }
    resize()
    window.addEventListener('resize', resize)
    return () => window.removeEventListener('resize', resize)
  }, [fitView, draw])

  useEffect(() => { draw() }, [draw])

  // ── Mouse interaction ───────────────────────────────────────────────────────
  const handleMouseMove = useCallback(
    (e: React.MouseEvent<HTMLCanvasElement>) => {
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top

      if (dragging.current) {
        transform.current.x += mx - dragStart.current.x
        transform.current.y += my - dragStart.current.y
        dragStart.current = { x: mx, y: my }
        draw()
        return
      }

      // Hit test points first
      let hit: GeoFeature | null = null
      for (const f of features.current) {
        if (!visibleLayers.has(f.properties.asset_type as AssetType)) continue
        if (f.geometry.type === 'Point') {
          const [px, py] = toScreen(
            f.geometry.coordinates[0],
            f.geometry.coordinates[1],
            canvas
          )
          if (Math.hypot(mx - px, my - py) < 14) { hit = f; break }
        }
      }
      // Then lines
      if (!hit) {
        for (const f of features.current) {
          if (!visibleLayers.has(f.properties.asset_type as AssetType)) continue
          if (f.geometry.type === 'LineString') {
            const coords = f.geometry.coordinates
            for (let i = 0; i < coords.length - 1; i++) {
              const [ax, ay] = toScreen(coords[i][0], coords[i][1], canvas)
              const [bx, by] = toScreen(coords[i + 1][0], coords[i + 1][1], canvas)
              if (distToSegment(mx, my, ax, ay, bx, by) < 8) { hit = f; break }
            }
            if (hit) break
          }
        }
      }

      if (hit) {
        const assetType = hit.properties.asset_type as AssetType
        setHoveredAsset(assetType)
        const propEntries: [string, string][] = Object.entries(hit.properties)
          .filter(([k]) => k !== 'asset_type')
          .map(([k, v]) => [
            k.replace(/_/g, ' '),
            typeof v === 'number'
              ? Number.isInteger(v) ? String(v) : v.toFixed(2)
              : String(v),
          ])
        let tx = e.clientX + 16
        let ty = e.clientY - 10
        if (tx + 220 > window.innerWidth) tx = e.clientX - 230
        setTooltip({
          visible: true,
          x: tx,
          y: ty,
          title: LABELS[assetType] || assetType,
          props: propEntries,
        })
      } else {
        setHoveredAsset(null)
        setTooltip(t => ({ ...t, visible: false }))
      }
    },
    [visibleLayers, toScreen, draw]
  )

  const handleWheel = useCallback(
    (e: WheelEvent) => {
      e.preventDefault()
      const canvas = canvasRef.current
      if (!canvas) return
      const rect = canvas.getBoundingClientRect()
      const mx = e.clientX - rect.left
      const my = e.clientY - rect.top
      const factor = e.deltaY < 0 ? 1.15 : 0.87
      transform.current.x = mx - (mx - transform.current.x) * factor
      transform.current.y = my - (my - transform.current.y) * factor
      transform.current.scale *= factor
      draw()
    },
    [draw]
  )

  useEffect(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    canvas.addEventListener('wheel', handleWheel, { passive: false })
    return () => canvas.removeEventListener('wheel', handleWheel)
  }, [handleWheel])

  const toggleLayer = (type: AssetType) => {
    setVisibleLayers(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type)
      else next.add(type)
      return next
    })
  }

  const resetView = () => {
    const canvas = canvasRef.current
    if (!canvas) return
    fitView(canvas)
    draw()
  }

  return (
    <div className="flex flex-col h-screen bg-black text-white overflow-hidden">
      {/* ── Header ── */}
      <header className="flex items-center gap-3 px-6 py-3 border-b border-white/10 bg-black/80 backdrop-blur-sm z-10 flex-shrink-0">
        <Link href="/" className="flex items-center gap-2 mr-2">
          <div className="w-7 h-7 rounded-lg bg-white/10 flex items-center justify-center text-sm">
            ☁
          </div>
          <span className="text-sm font-medium text-white/60 hover:text-white transition-colors">
            PointClouds
          </span>
        </Link>
        <span className="text-white/20">/</span>
        <span className="text-sm font-medium">Road Asset Detection</span>
        {/* 2D / 3D toggle */}
        <div className="ml-auto flex items-center gap-1 bg-white/5 border border-white/10 rounded-full p-0.5">
          <button
            onClick={() => setViewMode('2d')}
            className={`text-xs font-semibold px-3 py-1 rounded-full transition-all ${
              viewMode === '2d'
                ? 'bg-white text-black'
                : 'text-white/50 hover:text-white'
            }`}
          >
            2D
          </button>
          <button
            onClick={() => setViewMode('3d')}
            className={`text-xs font-semibold px-3 py-1 rounded-full transition-all ${
              viewMode === '3d'
                ? 'bg-white text-black'
                : 'text-white/50 hover:text-white'
            }`}
          >
            3D
          </button>
        </div>
        <span className="text-xs font-semibold bg-white/10 text-white/80 px-3 py-1 rounded-full">
          Demo
        </span>
        <Link
          href="/auth/login"
          className="text-xs font-semibold bg-white text-black px-4 py-1.5 rounded-full hover:bg-white/90 transition-colors"
        >
          Try with your data →
        </Link>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* ── Sidebar ── */}
        <aside className="w-72 flex-shrink-0 border-r border-white/10 overflow-y-auto bg-black">
          {/* Stats */}
          <div className="p-4 border-b border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 mb-3">
              Dataset Summary
            </p>
            <div className="grid grid-cols-2 gap-2">
              {[
                { v: '28,281', l: 'Total Points' },
                { v: '11', l: 'Assets Found' },
                { v: '390.9', l: 'Road Area m²' },
                { v: '49.0 m', l: 'Road Length' },
              ].map(s => (
                <div
                  key={s.l}
                  className="bg-white/5 rounded-lg p-3 border border-white/5"
                >
                  <div className="text-xl font-bold text-white">{s.v}</div>
                  <div className="text-[10px] text-white/40 mt-0.5">{s.l}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Asset layers */}
          <div className="p-4 border-b border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 mb-3">
              Detected Assets
            </p>
            <div className="flex flex-col gap-1.5">
              {(
                [
                  ['road_surface', 1],
                  ['road_centreline', 1],
                  ['road_marking', 3],
                  ['kerb', 2],
                  ['traffic_sign', 2],
                  ['drain_manhole', 2],
                ] as [AssetType, number][]
              ).map(([type, count]) => {
                const active = visibleLayers.has(type)
                return (
                  <button
                    key={type}
                    onClick={() => toggleLayer(type)}
                    className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border text-left transition-all ${
                      active
                        ? 'border-white/15 bg-white/5'
                        : 'border-white/5 bg-transparent opacity-40'
                    }`}
                  >
                    <span
                      className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                      style={{ background: COLORS[type] }}
                    />
                    <span className="text-sm flex-1 text-white/80">
                      {LABELS[type]}
                    </span>
                    <span className="text-[10px] bg-white/10 px-1.5 py-0.5 rounded-full text-white/40">
                      {count}
                    </span>
                  </button>
                )
              })}
            </div>
          </div>

          {/* Legend */}
          <div className="p-4 border-b border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 mb-3">
              Legend
            </p>
            <div className="flex flex-col gap-2">
              {(Object.entries(COLORS) as [AssetType, string][]).map(
                ([type, color]) => (
                  <div key={type} className="flex items-center gap-2.5">
                    {type === 'traffic_sign' || type === 'drain_manhole' ? (
                      <span
                        className="w-2.5 h-2.5 rounded-full flex-shrink-0"
                        style={{ background: color }}
                      />
                    ) : (
                      <span
                        className="w-5 h-0.5 rounded flex-shrink-0"
                        style={{ background: color }}
                      />
                    )}
                    <span className="text-xs text-white/50">{LABELS[type]}</span>
                  </div>
                )
              )}
            </div>
          </div>

          {/* Pipeline */}
          <div className="p-4">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 mb-3">
              Processing Pipeline
            </p>
            <div className="flex flex-col gap-1.5">
              {PIPELINE_STEPS.map((step, i) => (
                <button
                  key={step.name}
                  onClick={() => setActiveStep(activeStep === i ? null : i)}
                  className="flex items-start gap-2.5 px-3 py-2 rounded-lg border border-white/5 bg-white/3 hover:bg-white/5 text-left transition-all"
                >
                  <span className="w-4 h-4 rounded-full bg-white/15 flex items-center justify-center text-[9px] font-bold text-white/60 flex-shrink-0 mt-0.5">
                    ✓
                  </span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center justify-between gap-1">
                      <span className="text-xs text-white/70">{step.name}</span>
                      <span className="text-[10px] text-white/30 flex-shrink-0">
                        {step.time}
                      </span>
                    </div>
                    {activeStep === i && (
                      <p className="text-[10px] text-white/40 mt-1 leading-relaxed">
                        {step.desc}
                      </p>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        </aside>

        {/* ── Canvas / 3D Viewer ── */}
        <div
          ref={wrapRef}
          className="flex-1 relative overflow-hidden bg-[#080a0f]"
        >
          {viewMode === '3d' && (
            <Suspense fallback={
              <div className="absolute inset-0 flex items-center justify-center text-white/30 text-sm">
                Loading 3D viewer…
              </div>
            }>
              <PointCloud3DViewer visibleLayers={visibleLayers} />
            </Suspense>
          )}
          <canvas
            style={{ display: viewMode === '2d' ? 'block' : 'none' }}
            ref={canvasRef}
            className="block cursor-grab active:cursor-grabbing"
            onMouseMove={handleMouseMove}
            onMouseDown={e => {
              dragging.current = true
              const rect = canvasRef.current!.getBoundingClientRect()
              dragStart.current = {
                x: e.clientX - rect.left,
                y: e.clientY - rect.top,
              }
            }}
            onMouseUp={() => { dragging.current = false }}
            onMouseLeave={() => {
              dragging.current = false
              setHoveredAsset(null)
              setTooltip(t => ({ ...t, visible: false }))
            }}
          />

          {/* Controls */}
          <div className="absolute top-4 right-4 flex flex-col gap-1.5">
            {[
              { label: '⟳', title: 'Reset view', onClick: resetView },
              {
                label: '+',
                title: 'Zoom in',
                onClick: () => {
                  const c = canvasRef.current
                  if (!c) return
                  const cx = c.width / 2, cy = c.height / 2
                  transform.current.x = cx - (cx - transform.current.x) * 1.3
                  transform.current.y = cy - (cy - transform.current.y) * 1.3
                  transform.current.scale *= 1.3
                  draw()
                },
              },
              {
                label: '−',
                title: 'Zoom out',
                onClick: () => {
                  const c = canvasRef.current
                  if (!c) return
                  const cx = c.width / 2, cy = c.height / 2
                  transform.current.x = cx - (cx - transform.current.x) / 1.3
                  transform.current.y = cy - (cy - transform.current.y) / 1.3
                  transform.current.scale /= 1.3
                  draw()
                },
              },
            ].map(btn => (
              <button
                key={btn.label}
                title={btn.title}
                onClick={btn.onClick}
                className="w-8 h-8 rounded-lg bg-black/80 border border-white/10 text-white/50 hover:text-white hover:border-white/30 flex items-center justify-center text-sm backdrop-blur-sm transition-all"
              >
                {btn.label}
              </button>
            ))}
          </div>

          {/* Info bar */}
          {viewMode === '2d' && (
            <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/70 border border-white/10 rounded-full px-4 py-1.5 text-[11px] text-white/30 backdrop-blur-sm pointer-events-none">
              Scroll to zoom · Drag to pan · Hover assets for details
            </div>
          )}

          {/* Tooltip */}
          {tooltip.visible && (
            <div
              className="fixed z-50 bg-black/95 border border-white/15 rounded-xl p-3 min-w-[180px] pointer-events-none backdrop-blur-sm"
              style={{ left: tooltip.x, top: tooltip.y }}
            >
              <p className="text-xs font-semibold text-white/80 mb-2">
                {tooltip.title}
              </p>
              <div className="flex flex-col gap-1">
                {tooltip.props.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4">
                    <span className="text-[11px] text-white/40">{k}</span>
                    <span className="text-[11px] text-white/80 font-medium">
                      {v}
                    </span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer CTA ── */}
      <footer className="border-t border-white/10 bg-black/80 px-6 py-3 flex items-center justify-between flex-shrink-0">
        <p className="text-xs text-white/30">
          Processing 28,281 points · 7 detection stages · 4.1s total
        </p>
        <div className="flex items-center gap-3">
          <span className="text-xs text-white/30">
            Upload your own LiDAR data to detect assets automatically
          </span>
          <Link
            href="/auth/login"
            className="text-xs font-semibold bg-white text-black px-4 py-1.5 rounded-full hover:bg-white/90 transition-colors"
          >
            Get started free →
          </Link>
        </div>
      </footer>
    </div>
  )
}

// ── Geometry helpers ──────────────────────────────────────────────────────────
function distToSegment(
  px: number, py: number,
  ax: number, ay: number,
  bx: number, by: number
): number {
  const dx = bx - ax, dy = by - ay
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}
