'use client'

/**
 * RoadAssetsDemoClient.tsx
 *
 * Live-data version of the Road Assets demo page.
 * Fetches dataset metadata and GeoJSON from the API/R2 instead of using
 * hardcoded static files. Falls back to a "no dataset" state when no
 * datasetId is provided.
 *
 * Data flow:
 *   1. Accept `datasetId` prop from page.tsx (from ?id= query param)
 *   2. Fetch dataset row from GET /api/v1/datasets/{datasetId}
 *      → copc_url, road_assets_url, road_asset_stats, point_count, processing_jobs
 *   3. Fetch GeoJSON FeatureCollection from road_assets_url (public R2 URL)
 *   4. Render:
 *      - 2D canvas: live GeoJSON features drawn on top of a blank grid
 *      - 3D view: CesiumViewer with copc_url + roadAssetsGeoJSON prop
 *      - Stats panel: driven by dataset.point_count + road_asset_stats
 *      - Layer toggles: derived from unique asset_type values in GeoJSON
 *      - Pipeline: driven by processing_jobs status/progress
 */

import { useEffect, useRef, useState, useCallback, lazy, Suspense } from 'react'
import Link from 'next/link'

// Lazy-load CesiumViewer to avoid SSR issues
const CesiumViewerDemo = lazy(() => import('./CesiumViewerDemo'))

// ── Types ─────────────────────────────────────────────────────────────────────
type AssetType =
  | 'road_surface'
  | 'road_centreline'
  | 'road_marking'
  | 'kerb'
  | 'traffic_sign'
  | 'drain_manhole'
  | string // allow any asset_type from live data

interface GeoFeature {
  type: 'Feature'
  geometry:
    | { type: 'Polygon'; coordinates: number[][][] }
    | { type: 'LineString'; coordinates: number[][] }
    | { type: 'Point'; coordinates: number[] }
  properties: Record<string, string | number | boolean | null>
}

interface GeoFeatureCollection {
  type: 'FeatureCollection'
  features: GeoFeature[]
  metadata?: {
    road_marking_count?: number
    traffic_sign_count?: number
    drain_count?: number
    total_features?: number
  }
}

interface ProcessingJob {
  id: string
  job_type: string
  status: 'pending' | 'queued' | 'running' | 'processing' | 'completed' | 'failed' | 'cancelled'
  progress_pct?: number
  error_message?: string | null
  created_at: string
  completed_at?: string | null
}

interface DatasetRow {
  id: string
  name: string
  status: string
  point_count: number | null
  copc_url: string | null
  road_assets_url: string | null
  road_asset_stats: {
    total_features?: number
    road_marking_count?: number
    traffic_sign_count?: number
    drain_count?: number
  } | null
  bounding_box?: {
    min_x: number; min_y: number; min_z: number
    max_x: number; max_y: number; max_z: number
  } | null
  crs_epsg?: number | null
  processing_jobs?: ProcessingJob[]
}

// ── Colours & Labels ──────────────────────────────────────────────────────────
const COLORS: Record<string, string> = {
  road_surface:    '#a3a3a3',
  road_centreline: '#f59e0b',
  road_marking:    '#ffffff',
  kerb:            '#fb923c',
  traffic_sign:    '#ef4444',
  drain_manhole:   '#38bdf8',
  manhole:         '#38bdf8',
  drain:           '#7dd3fc',
}

const LABELS: Record<string, string> = {
  road_surface:    'Road Surface',
  road_centreline: 'Centreline',
  road_marking:    'Road Marking',
  kerb:            'Kerb',
  traffic_sign:    'Traffic Sign',
  drain_manhole:   'Drain / Manhole',
  manhole:         'Manhole',
  drain:           'Drain',
}

const DRAW_ORDER: string[] = [
  'road_surface',
  'road_centreline',
  'kerb',
  'road_marking',
  'drain_manhole',
  'manhole',
  'drain',
  'traffic_sign',
]

const PIPELINE_STEPS = [
  { name: 'Ground Classification',   desc: 'Separates ground from non-ground returns using progressive morphological filter' },
  { name: 'Road Surface Extraction', desc: 'Identifies paved road surface via NDVI + reflectance thresholding' },
  { name: 'Marking Detection',       desc: 'Detects high-intensity retroreflective road markings' },
  { name: 'Kerb Detection',          desc: 'Finds height discontinuities at road edges using local normal estimation' },
  { name: 'Sign Detection',          desc: 'Clusters vertical high-intensity returns above 2m using PointPillars' },
  { name: 'Drain Detection',         desc: 'Identifies circular low-intensity depressions in road surface' },
]

// ── Tooltip data ──────────────────────────────────────────────────────────────
interface TooltipState {
  visible: boolean
  x: number
  y: number
  title: string
  props: [string, string][]
}

// ── Props ─────────────────────────────────────────────────────────────────────
interface RoadAssetsDemoClientProps {
  datasetId?: string | null
}

// ── Main component ────────────────────────────────────────────────────────────
export default function RoadAssetsDemoClient({ datasetId }: RoadAssetsDemoClientProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const wrapRef = useRef<HTMLDivElement>(null)

  // ── Live data state ─────────────────────────────────────────────────────────
  const [dataset, setDataset] = useState<DatasetRow | null>(null)
  const [geoJson, setGeoJson] = useState<GeoFeatureCollection | null>(null)
  const [loadingDataset, setLoadingDataset] = useState(false)
  const [loadingGeoJson, setLoadingGeoJson] = useState(false)
  const [dataError, setDataError] = useState<string | null>(null)

  // ── UI state ────────────────────────────────────────────────────────────────
  const featuresRef = useRef<GeoFeature[]>([])
  const [visibleLayers, setVisibleLayers] = useState<Set<string>>(new Set(DRAW_ORDER))
  const [tooltip, setTooltip] = useState<TooltipState>({ visible: false, x: 0, y: 0, title: '', props: [] })
  const [hoveredAsset, setHoveredAsset] = useState<string | null>(null)
  const [activeStep, setActiveStep] = useState<number | null>(null)
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('2d')

  // Transform state for 2D canvas
  const transform = useRef({ x: 0, y: 0, scale: 1 })
  const dragging = useRef(false)
  const dragStart = useRef({ x: 0, y: 0 })
  const bounds = useRef({ minX: -10, maxX: 60, minY: -10, maxY: 10 })

  // ── Fetch dataset metadata ──────────────────────────────────────────────────
  useEffect(() => {
    if (!datasetId) return

    const apiUrl = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'
    setLoadingDataset(true)
    setDataError(null)

    fetch(`${apiUrl}/api/v1/datasets/${datasetId}`, {
      headers: { 'Content-Type': 'application/json' },
    })
      .then(res => {
        if (!res.ok) throw new Error(`Dataset fetch failed: ${res.status}`)
        return res.json()
      })
      .then((data: DatasetRow) => {
        setDataset(data)
        setLoadingDataset(false)
      })
      .catch(err => {
        console.error('Failed to fetch dataset:', err)
        setDataError(err.message)
        setLoadingDataset(false)
      })
  }, [datasetId])

  // ── Fetch GeoJSON from road_assets_url ─────────────────────────────────────
  useEffect(() => {
    if (!dataset?.road_assets_url) return

    setLoadingGeoJson(true)

    fetch(dataset.road_assets_url)
      .then(res => {
        if (!res.ok) throw new Error(`GeoJSON fetch failed: ${res.status}`)
        return res.json()
      })
      .then((data: GeoFeatureCollection) => {
        setGeoJson(data)
        featuresRef.current = data.features || []

        // Compute bounds from feature coordinates
        let minX = Infinity, maxX = -Infinity, minY = Infinity, maxY = -Infinity
        for (const f of data.features) {
          const coords = flattenCoords(f.geometry)
          for (const [x, y] of coords) {
            if (x < minX) minX = x
            if (x > maxX) maxX = x
            if (y < minY) minY = y
            if (y > maxY) maxY = y
          }
        }
        if (isFinite(minX)) {
          const padX = (maxX - minX) * 0.1 || 5
          const padY = (maxY - minY) * 0.1 || 5
          bounds.current = { minX: minX - padX, maxX: maxX + padX, minY: minY - padY, maxY: maxY + padY }
        }

        // Initialise visible layers from live asset types
        const types = new Set(data.features.map(f => String(f.properties.asset_type || '')).filter(Boolean))
        setVisibleLayers(types)
        setLoadingGeoJson(false)
      })
      .catch(err => {
        console.error('Failed to fetch GeoJSON:', err)
        setLoadingGeoJson(false)
      })
  }, [dataset?.road_assets_url])

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

    // Draw features in order
    const features = featuresRef.current
    const orderedTypes = [...DRAW_ORDER, ...Array.from(visibleLayers).filter(t => !DRAW_ORDER.includes(t))]

    for (const assetType of orderedTypes) {
      if (!visibleLayers.has(assetType)) continue
      const typeFeatures = features.filter(f => f.properties.asset_type === assetType)
      const color = COLORS[assetType] || '#888888'
      const isHovered = hoveredAsset === assetType

      for (const feature of typeFeatures) {
        const geom = feature.geometry
        ctx.save()

        if (geom.type === 'Polygon') {
          const ring = geom.coordinates[0]
          ctx.beginPath()
          for (let i = 0; i < ring.length; i++) {
            const [sx, sy] = toScreen(ring[i][0], ring[i][1], canvas)
            if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy)
          }
          ctx.closePath()
          ctx.fillStyle = color + (isHovered ? '40' : '22')
          ctx.fill()
          ctx.strokeStyle = color + (isHovered ? 'cc' : '55')
          ctx.lineWidth = isHovered ? 2 : 1
          ctx.stroke()

        } else if (geom.type === 'LineString') {
          const pts = geom.coordinates
          ctx.beginPath()
          for (let i = 0; i < pts.length; i++) {
            const [sx, sy] = toScreen(pts[i][0], pts[i][1], canvas)
            if (i === 0) ctx.moveTo(sx, sy); else ctx.lineTo(sx, sy)
          }
          ctx.strokeStyle = color
          ctx.lineWidth = isHovered ? 3 : 1.5
          ctx.globalAlpha = isHovered ? 1 : 0.85
          ctx.stroke()

        } else if (geom.type === 'Point') {
          const [sx, sy] = toScreen(geom.coordinates[0], geom.coordinates[1], canvas)
          const r = Math.max(4, transform.current.scale * 0.4)
          ctx.beginPath()
          ctx.arc(sx, sy, isHovered ? r * 1.5 : r, 0, Math.PI * 2)
          ctx.fillStyle = color
          ctx.globalAlpha = isHovered ? 1 : 0.9
          ctx.fill()
          ctx.strokeStyle = '#000'
          ctx.lineWidth = 1
          ctx.stroke()
        }

        ctx.restore()
      }
    }
  }, [visibleLayers, hoveredAsset, toScreen])

  // ── Canvas resize & initial fit ─────────────────────────────────────────────
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
    const ro = new ResizeObserver(resize)
    ro.observe(wrap)
    return () => ro.disconnect()
  }, [fitView, draw])

  // ── Redraw when data or visibility changes ──────────────────────────────────
  useEffect(() => {
    draw()
  }, [draw, geoJson, visibleLayers, hoveredAsset])

  // ── Mouse interaction ───────────────────────────────────────────────────────
  const resetView = useCallback(() => {
    const canvas = canvasRef.current
    if (!canvas) return
    fitView(canvas)
    draw()
  }, [fitView, draw])

  const handleMouseMove = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current
    if (!canvas) return

    if (dragging.current) {
      const rect = canvas.getBoundingClientRect()
      const dx = e.clientX - rect.left - dragStart.current.x
      const dy = e.clientY - rect.top - dragStart.current.y
      transform.current.x += dx
      transform.current.y += dy
      dragStart.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
      draw()
      return
    }

    const rect = canvas.getBoundingClientRect()
    const mx = e.clientX - rect.left
    const my = e.clientY - rect.top
    const t = transform.current
    const wx = (mx - t.x) / t.scale
    const wy = (canvas.height - my - t.y) / t.scale

    let found: GeoFeature | null = null
    let foundType: string | null = null

    const features = featuresRef.current
    for (const f of [...features].reverse()) {
      const type = String(f.properties.asset_type || '')
      if (!visibleLayers.has(type)) continue
      const geom = f.geometry

      if (geom.type === 'Point') {
        const [px, py] = geom.coordinates
        const r = Math.max(4, t.scale * 0.4) / t.scale
        if (Math.hypot(wx - px, wy - py) <= r * 2) { found = f; foundType = type; break }
      } else if (geom.type === 'LineString') {
        for (let i = 0; i < geom.coordinates.length - 1; i++) {
          const d = distToSegment(wx, wy, geom.coordinates[i][0], geom.coordinates[i][1], geom.coordinates[i + 1][0], geom.coordinates[i + 1][1])
          if (d < 4 / t.scale) { found = f; foundType = type; break }
        }
        if (found) break
      } else if (geom.type === 'Polygon') {
        if (pointInPolygon(wx, wy, geom.coordinates[0])) { found = f; foundType = type; break }
      }
    }

    if (found && foundType) {
      setHoveredAsset(foundType)
      const props = Object.entries(found.properties)
        .filter(([k]) => k !== 'asset_type')
        .map(([k, v]) => [k, String(v)] as [string, string])
      setTooltip({
        visible: true,
        x: e.clientX + 12,
        y: e.clientY - 8,
        title: LABELS[foundType] || foundType,
        props,
      })
    } else {
      setHoveredAsset(null)
      setTooltip(t => ({ ...t, visible: false }))
    }
  }, [visibleLayers])

  const toggleLayer = useCallback((type: string) => {
    setVisibleLayers(prev => {
      const next = new Set(prev)
      if (next.has(type)) next.delete(type); else next.add(type)
      return next
    })
  }, [])

  // ── Derived stats from live data ────────────────────────────────────────────
  const stats = dataset?.road_asset_stats
  const totalPoints = dataset?.point_count?.toLocaleString() ?? '—'
  const totalAssets = stats?.total_features ?? geoJson?.features.length ?? '—'
  const roadMarkingCount = stats?.road_marking_count ?? (geoJson?.features.filter(f => f.properties.asset_type === 'road_marking').length ?? '—')
  const signCount = stats?.traffic_sign_count ?? (geoJson?.features.filter(f => f.properties.asset_type === 'traffic_sign').length ?? '—')
  const drainCount = stats?.drain_count ?? (geoJson?.features.filter(f => ['drain_manhole', 'drain', 'manhole'].includes(String(f.properties.asset_type))).length ?? '—')

  // Unique asset types from live GeoJSON for layer panel
  const liveAssetTypes = geoJson
    ? Array.from(new Set(geoJson.features.map(f => String(f.properties.asset_type || '')).filter(Boolean)))
    : []

  // Pipeline job status
  const roadJob = dataset?.processing_jobs?.find(j => j.job_type === 'road_assets' || j.job_type === 'road_asset_extraction')
  const jobStatus = roadJob?.status ?? null
  const jobProgress = roadJob?.progress_pct ?? null

  // ── Bounding box for CesiumViewer ───────────────────────────────────────────
  const bb = dataset?.bounding_box
  const cesiumBounds = bb ? { minX: bb.min_x, minY: bb.min_y, minZ: bb.min_z, maxX: bb.max_x, maxY: bb.max_y, maxZ: bb.max_z } : null

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="flex flex-col h-screen bg-black text-white overflow-hidden">
      {/* ── Header ── */}
      <header className="flex items-center justify-between px-5 py-3 border-b border-white/10 bg-black/90 backdrop-blur-sm shrink-0">
        <div className="flex items-center gap-3">
          <div className="w-6 h-6 rounded-md bg-white/10 flex items-center justify-center">
            <span className="text-[10px] font-bold text-white/70">PC</span>
          </div>
          <span className="text-sm font-semibold text-white/80">Road Asset Detection</span>
          {dataset && (
            <span className="text-xs text-white/30 border border-white/10 rounded px-2 py-0.5">{dataset.name}</span>
          )}
        </div>
        <div className="flex items-center gap-2">
          {/* View mode toggle */}
          <div className="flex items-center gap-1 bg-white/5 rounded-lg p-1 border border-white/10">
            {(['2d', '3d'] as const).map(mode => (
              <button
                key={mode}
                onClick={() => setViewMode(mode)}
                className={`px-3 py-1 rounded-md text-xs font-medium transition-all ${
                  viewMode === mode ? 'bg-white text-black' : 'text-white/50 hover:text-white'
                }`}
              >
                {mode.toUpperCase()}
              </button>
            ))}
          </div>
          <Link
            href="/auth/login"
            className="text-xs font-semibold bg-white text-black px-4 py-1.5 rounded-full hover:bg-white/90 transition-colors"
          >
            Get started free →
          </Link>
        </div>
      </header>

      {/* ── Body ── */}
      <div className="flex flex-1 overflow-hidden">
        {/* ── Sidebar ── */}
        <aside className="w-56 shrink-0 border-r border-white/10 bg-black/60 overflow-y-auto flex flex-col">
          {/* Loading / error state */}
          {loadingDataset && (
            <div className="p-4 text-xs text-white/40 flex items-center gap-2">
              <div className="w-3 h-3 border border-white/20 border-t-white/60 rounded-full animate-spin" />
              Loading dataset…
            </div>
          )}
          {dataError && (
            <div className="p-4 text-xs text-red-400/80">
              Failed to load dataset: {dataError}
            </div>
          )}
          {!datasetId && !loadingDataset && (
            <div className="p-4 text-xs text-white/30">
              No dataset selected. Pass <code className="text-white/50">?id=</code> to view live data.
            </div>
          )}

          {/* Stats */}
          <div className="p-4 border-b border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 mb-3">
              Dataset Summary
            </p>
            <div className="grid grid-cols-2 gap-2">
              {[
                { v: totalPoints,              l: 'Total Points' },
                { v: String(totalAssets),      l: 'Assets Found' },
                { v: String(roadMarkingCount), l: 'Markings' },
                { v: String(signCount),        l: 'Signs' },
              ].map(s => (
                <div key={s.l} className="bg-white/5 rounded-lg p-3 border border-white/5">
                  <div className="text-xl font-bold text-white">{s.v}</div>
                  <div className="text-[10px] text-white/40 mt-0.5">{s.l}</div>
                </div>
              ))}
            </div>
          </div>

          {/* Asset layers — derived from live GeoJSON */}
          <div className="p-4 border-b border-white/10">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 mb-3">
              Detected Assets
            </p>
            {loadingGeoJson ? (
              <div className="text-xs text-white/30 flex items-center gap-2">
                <div className="w-3 h-3 border border-white/20 border-t-white/60 rounded-full animate-spin" />
                Loading assets…
              </div>
            ) : liveAssetTypes.length > 0 ? (
              <div className="flex flex-col gap-1.5">
                {liveAssetTypes.map(type => {
                  const count = geoJson?.features.filter(f => f.properties.asset_type === type).length ?? 0
                  const active = visibleLayers.has(type)
                  return (
                    <button
                      key={type}
                      onClick={() => toggleLayer(type)}
                      className={`flex items-center gap-2.5 px-3 py-2.5 rounded-lg border text-left transition-all ${
                        active ? 'border-white/15 bg-white/5' : 'border-white/5 bg-transparent opacity-40'
                      }`}
                    >
                      <span className="w-2.5 h-2.5 rounded-full flex-shrink-0" style={{ background: COLORS[type] || '#888' }} />
                      <span className="text-sm flex-1 text-white/80">{LABELS[type] || type}</span>
                      <span className="text-[10px] bg-white/10 px-1.5 py-0.5 rounded-full text-white/40">{count}</span>
                    </button>
                  )
                })}
              </div>
            ) : (
              <p className="text-xs text-white/30">No assets detected yet.</p>
            )}
          </div>

          {/* Pipeline — driven by job status */}
          <div className="p-4">
            <p className="text-[10px] font-semibold uppercase tracking-widest text-white/30 mb-3">
              Processing Pipeline
            </p>
            {jobStatus === 'running' || jobStatus === 'processing' ? (
              <div className="mb-3">
                <div className="flex justify-between text-[10px] text-white/40 mb-1">
                  <span>Running…</span>
                  <span>{jobProgress ?? 0}%</span>
                </div>
                <div className="h-1 bg-white/10 rounded-full overflow-hidden">
                  <div
                    className="h-full bg-white/60 rounded-full transition-all duration-500"
                    style={{ width: `${jobProgress ?? 0}%` }}
                  />
                </div>
              </div>
            ) : null}
            <div className="flex flex-col gap-1.5">
              {PIPELINE_STEPS.map((step, i) => {
                const done = jobStatus === 'completed'
                const active = (jobStatus === 'running' || jobStatus === 'processing') && jobProgress != null
                  ? Math.floor((jobProgress / 100) * PIPELINE_STEPS.length) >= i
                  : false
                return (
                  <button
                    key={step.name}
                    onClick={() => setActiveStep(activeStep === i ? null : i)}
                    className="flex items-start gap-2.5 px-3 py-2 rounded-lg border border-white/5 bg-white/3 hover:bg-white/5 text-left transition-all"
                  >
                    <span className={`w-4 h-4 rounded-full flex items-center justify-center text-[9px] font-bold flex-shrink-0 mt-0.5 ${
                      done || active ? 'bg-white/20 text-white/80' : 'bg-white/8 text-white/30'
                    }`}>
                      {done || active ? '✓' : String(i + 1)}
                    </span>
                    <div className="flex-1 min-w-0">
                      <span className="text-xs text-white/70">{step.name}</span>
                      {activeStep === i && (
                        <p className="text-[10px] text-white/40 mt-1 leading-relaxed">{step.desc}</p>
                      )}
                    </div>
                  </button>
                )
              })}
            </div>
          </div>
        </aside>

        {/* ── Main viewer ── */}
        <div ref={wrapRef} className="relative flex-1 overflow-hidden bg-[#080a0f]">
          {viewMode === '3d' ? (
            <Suspense fallback={
              <div className="absolute inset-0 flex items-center justify-center">
                <div className="w-8 h-8 border-2 border-white/20 border-t-white/80 rounded-full animate-spin" />
              </div>
            }>
              <CesiumViewerDemo
                copcUrl={dataset?.copc_url ?? null}
                boundingBox={cesiumBounds}
                roadAssetsGeoJson={geoJson}
              />
            </Suspense>
          ) : (
            <canvas
              style={{ display: 'block' }}
              ref={canvasRef}
              className="block cursor-grab active:cursor-grabbing"
              onMouseMove={handleMouseMove}
              onMouseDown={e => {
                dragging.current = true
                const rect = canvasRef.current!.getBoundingClientRect()
                dragStart.current = { x: e.clientX - rect.left, y: e.clientY - rect.top }
              }}
              onMouseUp={() => { dragging.current = false }}
              onMouseLeave={() => {
                dragging.current = false
                setHoveredAsset(null)
                setTooltip(t => ({ ...t, visible: false }))
              }}
              onWheel={e => {
                e.preventDefault()
                const canvas = canvasRef.current
                if (!canvas) return
                const rect = canvas.getBoundingClientRect()
                const mx = e.clientX - rect.left
                const my = e.clientY - rect.top
                const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15
                transform.current.x = mx - (mx - transform.current.x) * factor
                transform.current.y = my - (my - transform.current.y) * factor
                transform.current.scale *= factor
                draw()
              }}
            />
          )}

          {/* No data overlay */}
          {!loadingDataset && !loadingGeoJson && !geoJson && viewMode === '2d' && (
            <div className="absolute inset-0 flex flex-col items-center justify-center pointer-events-none">
              <div className="text-white/10 text-6xl mb-4">⬡</div>
              <p className="text-sm text-white/40">
                {datasetId ? 'Road assets not yet processed for this dataset.' : 'No dataset selected.'}
              </p>
              <p className="text-xs text-white/20 mt-1">
                {datasetId ? 'Trigger road asset extraction to generate results.' : 'Pass ?id= to view live data.'}
              </p>
            </div>
          )}

          {/* Controls */}
          <div className="absolute top-4 right-4 flex flex-col gap-1.5 z-10">
            {[
              { label: '⟳', title: 'Reset view', onClick: resetView },
              {
                label: '+', title: 'Zoom in',
                onClick: () => {
                  const c = canvasRef.current; if (!c) return
                  const cx = c.width / 2, cy = c.height / 2
                  transform.current.x = cx - (cx - transform.current.x) * 1.3
                  transform.current.y = cy - (cy - transform.current.y) * 1.3
                  transform.current.scale *= 1.3; draw()
                },
              },
              {
                label: '−', title: 'Zoom out',
                onClick: () => {
                  const c = canvasRef.current; if (!c) return
                  const cx = c.width / 2, cy = c.height / 2
                  transform.current.x = cx - (cx - transform.current.x) / 1.3
                  transform.current.y = cy - (cy - transform.current.y) / 1.3
                  transform.current.scale /= 1.3; draw()
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
              <p className="text-xs font-semibold text-white/80 mb-2">{tooltip.title}</p>
              <div className="flex flex-col gap-1">
                {tooltip.props.map(([k, v]) => (
                  <div key={k} className="flex justify-between gap-4">
                    <span className="text-[11px] text-white/40">{k}</span>
                    <span className="text-[11px] text-white/80 font-medium">{v}</span>
                  </div>
                ))}
              </div>
            </div>
          )}
        </div>
      </div>

      {/* ── Footer CTA ── */}
      <footer className="border-t border-white/10 bg-black/80 px-6 py-3 flex items-center justify-between shrink-0">
        <p className="text-xs text-white/30">
          {dataset
            ? `${totalPoints} points · ${totalAssets} assets detected`
            : 'Upload your own LiDAR data to detect assets automatically'}
        </p>
        <div className="flex items-center gap-3">
          <span className="text-xs text-white/30">
            Powered by PDAL + DBSCAN clustering
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
function distToSegment(px: number, py: number, ax: number, ay: number, bx: number, by: number): number {
  const dx = bx - ax, dy = by - ay
  const t = Math.max(0, Math.min(1, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
  return Math.hypot(px - (ax + t * dx), py - (ay + t * dy))
}

function pointInPolygon(px: number, py: number, ring: number[][]): boolean {
  let inside = false
  for (let i = 0, j = ring.length - 1; i < ring.length; j = i++) {
    const xi = ring[i][0], yi = ring[i][1]
    const xj = ring[j][0], yj = ring[j][1]
    if (((yi > py) !== (yj > py)) && (px < (xj - xi) * (py - yi) / (yj - yi) + xi)) inside = !inside
  }
  return inside
}

function flattenCoords(geom: GeoFeature['geometry']): number[][] {
  if (geom.type === 'Point') return [geom.coordinates]
  if (geom.type === 'LineString') return geom.coordinates
  if (geom.type === 'Polygon') return geom.coordinates[0]
  return []
}
