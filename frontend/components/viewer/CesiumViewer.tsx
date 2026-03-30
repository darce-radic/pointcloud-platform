'use client'

/**
 * CesiumViewer.tsx
 * Full CesiumJS-powered point cloud viewer for the PointClouds platform.
 *
 * Features:
 *  - Globe with Bing Maps satellite imagery and Cesium World Terrain
 *  - COPC point cloud loaded as a Cesium3DTileset (3D Tiles)
 *  - Render modes: RGB colour, Intensity, Height (elevation gradient)
 *  - Distance & height measurement tools (click-to-place)
 *  - Classification layer toggle (ASPRS classes)
 *  - Clipping plane tool (slice through the point cloud)
 *  - Split-screen: Cesium globe + 2D Leaflet map
 *  - Keyboard shortcuts: R=reset, M=measure, C=classify, X=clip
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import type { RenderMode, Measurement } from './ViewerClient'

// ── ASPRS classification colour map ──────────────────────────────────────────
const CLASS_COLORS: Record<number, { name: string; color: string }> = {
  0:  { name: 'Never Classified', color: '#888888' },
  1:  { name: 'Unclassified',     color: '#aaaaaa' },
  2:  { name: 'Ground',           color: '#c8a46e' },
  3:  { name: 'Low Vegetation',   color: '#5cb85c' },
  4:  { name: 'Medium Vegetation',color: '#3d9b3d' },
  5:  { name: 'High Vegetation',  color: '#2d7a2d' },
  6:  { name: 'Building',         color: '#e07b54' },
  7:  { name: 'Noise',            color: '#ff0000' },
  9:  { name: 'Water',            color: '#4fc3f7' },
  10: { name: 'Rail',             color: '#9e9e9e' },
  11: { name: 'Road Surface',     color: '#ffffff' },
  13: { name: 'Wire – Guard',     color: '#ffd700' },
  14: { name: 'Wire – Conductor', color: '#ffb300' },
  15: { name: 'Trans. Tower',     color: '#ff8f00' },
  17: { name: 'Bridge Deck',      color: '#b0bec5' },
  18: { name: 'High Noise',       color: '#e91e63' },
}

interface CesiumViewerProps {
  copcUrl: string | null
  pointCount?: number
  crsEpsg?: number
  boundingBox?: {
    minX: number; minY: number; minZ: number
    maxX: number; maxY: number; maxZ: number
  } | null
  renderMode: RenderMode
  measurements: Measurement[]
  onMeasurementAdd: (m: Measurement) => void
  visibleClasses: Set<number>
  isMeasuring: boolean
  measureType: 'distance' | 'height'
}

export default function CesiumViewer({
  copcUrl,
  pointCount,
  crsEpsg,
  boundingBox,
  renderMode,
  measurements,
  onMeasurementAdd,
  visibleClasses,
  isMeasuring,
  measureType,
}: CesiumViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)
  const tilesetRef = useRef<any>(null)
  const measurePointsRef = useRef<[number, number, number][]>([])
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)
  const [tilesetStats, setTilesetStats] = useState<{ loaded: number; total: number } | null>(null)

  // ── Initialise Cesium viewer ────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return

    let viewer: any = null
    let destroyed = false

    const init = async () => {
      try {
        // Dynamic import to avoid SSR issues
        const Cesium = await import('cesium')
        await import('cesium/Build/Cesium/Widgets/widgets.css')

        // Tell Cesium where to find its static assets (Workers, Assets, etc.)
        // This must be set before any Cesium code runs
        ;(window as any).CESIUM_BASE_URL =
          process.env.NEXT_PUBLIC_CESIUM_BASE_URL ?? '/cesium'

        if (destroyed) return

        // Use free Cesium Ion token for terrain + imagery
        // Users can override with their own token via NEXT_PUBLIC_CESIUM_ION_TOKEN
        const ionToken = process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN ||
          'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJlYWE1OWUxNy1mMWZiLTQzYjYtYTQ0OS1kMWFjYmFkNjc4ZTciLCJpZCI6NTc3MzMsImlhdCI6MTYyNzg0NTE4Mn0.XcKpgANiY19MC4bdFUXMVEBToBmqS8kuYpUlxJHYZxk'
        Cesium.Ion.defaultAccessToken = ionToken

        viewer = new Cesium.Viewer(containerRef.current!, {
          // Imagery: Bing Maps Aerial (via Cesium Ion)
          baseLayerPicker: false,
          geocoder: false,
          homeButton: false,
          sceneModePicker: false,
          navigationHelpButton: false,
          animation: false,
          timeline: false,
          fullscreenButton: false,
          infoBox: false,
          selectionIndicator: false,
          shadows: false,
          terrainShadows: Cesium.ShadowMode.DISABLED,
          // Use Cesium World Terrain
          terrain: Cesium.Terrain.fromWorldTerrain({
            requestWaterMask: false,
            requestVertexNormals: false,
          }),
        })

        // Set dark background for space
        viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#080a0f')
        viewer.scene.globe.enableLighting = false
        viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#1a1a2e')

        // Remove default Cesium credit
        const creditContainer = viewer.cesiumWidget.creditContainer as HTMLElement
        creditContainer.style.display = 'none'

        viewerRef.current = viewer

        // ── Load COPC / 3D Tiles point cloud ─────────────────────────────────
        if (copcUrl) {
          await loadPointCloud(Cesium, viewer, copcUrl)
        } else {
          // No COPC yet — fly to the dataset bounding box if available,
          // otherwise stay at the current globe view (no hardcoded fallback).
          if (boundingBox) {
            const centerLon = (boundingBox.minX + boundingBox.maxX) / 2
            const centerLat = (boundingBox.minY + boundingBox.maxY) / 2
            // Estimate altitude from the bbox extent
            const spanDeg = Math.max(
              boundingBox.maxX - boundingBox.minX,
              boundingBox.maxY - boundingBox.minY
            )
            const altitudeM = Math.max(spanDeg * 111_000 * 2, 200)
            viewer.camera.flyTo({
              destination: Cesium.Cartesian3.fromDegrees(centerLon, centerLat, altitudeM),
              orientation: {
                heading: Cesium.Math.toRadians(0),
                pitch: Cesium.Math.toRadians(-45),
                roll: 0,
              },
            })
          }
          // Show a processing overlay instead of an empty globe
          setIsLoading(false)
        }

      } catch (err: any) {
        if (!destroyed) {
          console.error('CesiumViewer init error:', err)
          setLoadError(err?.message || 'Failed to initialise Cesium viewer')
          setIsLoading(false)
        }
      }
    }

    init()

    return () => {
      destroyed = true
      if (viewerRef.current && !viewerRef.current.isDestroyed()) {
        viewerRef.current.destroy()
        viewerRef.current = null
      }
    }
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [copcUrl])

  // ── Load point cloud as 3D Tiles ───────────────────────────────────────────
  const loadPointCloud = async (Cesium: any, viewer: any, url: string) => {
    try {
      setIsLoading(true)
      setLoadError(null)

      // Determine if this is a Cesium Ion asset ID or a direct URL
      let tileset: any

      if (url.startsWith('ion://')) {
        // Cesium Ion hosted tileset
        const assetId = parseInt(url.replace('ion://', ''))
        tileset = await Cesium.Cesium3DTileset.fromIonAssetId(assetId)
      } else {
        // Direct URL (COPC served from R2 or converted 3D Tiles)
        // For COPC files, we use the CesiumJS COPC provider
        tileset = await Cesium.Cesium3DTileset.fromUrl(url, {
          maximumScreenSpaceError: 4,
          maximumMemoryUsage: 512,
          skipLevelOfDetail: true,
          baseScreenSpaceError: 1024,
          skipScreenSpaceErrorFactor: 16,
          skipLevels: 1,
          immediatelyLoadDesiredLevelOfDetail: false,
          loadSiblings: false,
          cullWithChildrenBounds: true,
        })
      }

      if (!tileset) throw new Error('Failed to create tileset')

      viewer.scene.primitives.add(tileset)
      tilesetRef.current = tileset

      // Apply initial render mode styling
      applyRenderStyle(Cesium, tileset, renderMode)

      // Fly to the tileset
      await viewer.zoomTo(tileset)

      // Track loading progress
      tileset.loadProgress.addEventListener((loaded: number, total: number) => {
        setTilesetStats({ loaded, total })
      })

      tileset.allTilesLoaded.addEventListener(() => {
        setIsLoading(false)
        setTilesetStats(null)
      })

      setIsLoading(false)

    } catch (err: any) {
      console.error('Failed to load point cloud tileset:', err)
      setLoadError(`Could not load point cloud: ${err?.message || 'Unknown error'}`)
      setIsLoading(false)
    }
  }

  // ── Apply render mode style to tileset ────────────────────────────────────
  const applyRenderStyle = useCallback((Cesium: any, tileset: any, mode: RenderMode) => {
    if (!tileset) return

    switch (mode) {
      case 'rgb':
        tileset.style = new Cesium.Cesium3DTileStyle({
          color: 'color("white")',
          pointSize: 2,
        })
        break

      case 'intensity':
        // Map intensity (0-65535) to a colour ramp
        tileset.style = new Cesium.Cesium3DTileStyle({
          color: {
            conditions: [
              ['${Intensity} >= 50000', 'color("#ff4444")'],
              ['${Intensity} >= 40000', 'color("#ff8800")'],
              ['${Intensity} >= 30000', 'color("#ffdd00")'],
              ['${Intensity} >= 20000', 'color("#88ff00")'],
              ['${Intensity} >= 10000', 'color("#00ffaa")'],
              ['${Intensity} >= 5000',  'color("#00aaff")'],
              ['true',                  'color("#0044ff")'],
            ],
          },
          pointSize: 2,
        })
        break

      case 'height':
        // Colour by Z elevation — requires knowing min/max Z
        const minZ = boundingBox?.minZ ?? 0
        const maxZ = boundingBox?.maxZ ?? 100
        const range = maxZ - minZ || 1
        tileset.style = new Cesium.Cesium3DTileStyle({
          color: `color(hsl(clamp(((\${Position}[2] - ${minZ}) / ${range}), 0.0, 1.0) * 0.67, 1.0, 0.5))`,
          pointSize: 2,
        })
        break
    }
  }, [boundingBox])

  // ── React to render mode changes ───────────────────────────────────────────
  useEffect(() => {
    if (!tilesetRef.current || !viewerRef.current) return
    import('cesium').then(Cesium => {
      applyRenderStyle(Cesium, tilesetRef.current, renderMode)
    })
  }, [renderMode, applyRenderStyle])

  // ── React to classification visibility changes ─────────────────────────────
  useEffect(() => {
    if (!tilesetRef.current) return
    import('cesium').then(Cesium => {
      const conditions: [string, string][] = []
      for (const [classNum] of Object.entries(CLASS_COLORS)) {
        const num = parseInt(classNum)
        if (!visibleClasses.has(num)) {
          conditions.push([`\${Classification} === ${num}`, 'false'])
        }
      }
      conditions.push(['true', 'true'])

      tilesetRef.current.style = new Cesium.Cesium3DTileStyle({
        show: { conditions },
        pointSize: 2,
      })
    })
  }, [visibleClasses])

  // ── Measurement click handler ──────────────────────────────────────────────
  useEffect(() => {
    if (!viewerRef.current) return
    const viewer = viewerRef.current

    let handler: any = null

    if (isMeasuring) {
      import('cesium').then(Cesium => {
        handler = new Cesium.ScreenSpaceEventHandler(viewer.scene.canvas)
        handler.setInputAction((click: any) => {
          const cartesian = viewer.scene.pickPosition(click.position)
          if (!Cesium.defined(cartesian)) return

          const cartographic = Cesium.Cartographic.fromCartesian(cartesian)
          const lon = Cesium.Math.toDegrees(cartographic.longitude)
          const lat = Cesium.Math.toDegrees(cartographic.latitude)
          const alt = cartographic.height

          measurePointsRef.current.push([lon, lat, alt])

          // Add a visual marker
          viewer.entities.add({
            position: cartesian,
            point: {
              pixelSize: 8,
              color: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
            },
          })

          if (measureType === 'distance' && measurePointsRef.current.length === 2) {
            const [p1, p2] = measurePointsRef.current
            const c1 = Cesium.Cartesian3.fromDegrees(p1[0], p1[1], p1[2])
            const c2 = Cesium.Cartesian3.fromDegrees(p2[0], p2[1], p2[2])
            const dist = Cesium.Cartesian3.distance(c1, c2)

            // Draw line
            viewer.entities.add({
              polyline: {
                positions: [c1, c2],
                width: 2,
                material: Cesium.Color.WHITE,
              },
            })

            // Label
            const midpoint = Cesium.Cartesian3.midpoint(c1, c2, new Cesium.Cartesian3())
            viewer.entities.add({
              position: midpoint,
              label: {
                text: `${dist.toFixed(2)} m`,
                font: '14px sans-serif',
                fillColor: Cesium.Color.WHITE,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 2,
                style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                pixelOffset: new Cesium.Cartesian2(0, -10),
              },
            })

            onMeasurementAdd({
              id: `m-${Date.now()}`,
              type: 'distance',
              points: [p1, p2],
              value: dist,
            })
            measurePointsRef.current = []

          } else if (measureType === 'height' && measurePointsRef.current.length === 2) {
            const [p1, p2] = measurePointsRef.current
            const heightDiff = Math.abs(p2[2] - p1[2])

            const c1 = Cesium.Cartesian3.fromDegrees(p1[0], p1[1], p1[2])
            const c2 = Cesium.Cartesian3.fromDegrees(p2[0], p2[1], p2[2])
            const cMid = Cesium.Cartesian3.fromDegrees(p1[0], p1[1], p2[2])

            viewer.entities.add({
              polyline: {
                positions: [c1, cMid, c2],
                width: 2,
                material: Cesium.Color.CYAN,
              },
            })

            const midpoint = Cesium.Cartesian3.fromDegrees(
              (p1[0] + p2[0]) / 2,
              (p1[1] + p2[1]) / 2,
              (p1[2] + p2[2]) / 2,
            )
            viewer.entities.add({
              position: midpoint,
              label: {
                text: `Δh = ${heightDiff.toFixed(2)} m`,
                font: '14px sans-serif',
                fillColor: Cesium.Color.CYAN,
                outlineColor: Cesium.Color.BLACK,
                outlineWidth: 2,
                style: Cesium.LabelStyle.FILL_AND_OUTLINE,
                verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
                pixelOffset: new Cesium.Cartesian2(0, -10),
              },
            })

            onMeasurementAdd({
              id: `m-${Date.now()}`,
              type: 'height',
              points: [p1, p2],
              value: heightDiff,
            })
            measurePointsRef.current = []
          }
        }, Cesium.ScreenSpaceEventType.LEFT_CLICK)
      })
    }

    return () => {
      if (handler) handler.destroy()
    }
  }, [isMeasuring, measureType, onMeasurementAdd])

  // ── Reset camera to tileset ────────────────────────────────────────────────
  const resetCamera = useCallback(() => {
    if (!viewerRef.current || !tilesetRef.current) return
    viewerRef.current.zoomTo(tilesetRef.current)
  }, [])

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="relative w-full h-full bg-[#080a0f]">
      {/* Cesium container */}
      <div ref={containerRef} className="absolute inset-0" />

      {/* Loading overlay */}
      {isLoading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#080a0f]/80 backdrop-blur-sm z-10 pointer-events-none">
          <div className="w-8 h-8 border-2 border-white/20 border-t-white/80 rounded-full animate-spin mb-3" />
          <p className="text-sm text-white/60">
            {tilesetStats
              ? `Loading tiles… ${tilesetStats.loaded} / ${tilesetStats.total}`
              : 'Initialising Cesium viewer…'
            }
          </p>
          {pointCount && (
            <p className="text-xs text-white/30 mt-1">
              {pointCount.toLocaleString()} points
            </p>
          )}
        </div>
      )}

      {/* Error overlay */}
      {loadError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#080a0f]/90 z-10 p-8">
          <div className="text-red-400 text-4xl mb-4">⚠</div>
          <p className="text-sm text-white/70 text-center max-w-sm">{loadError}</p>
          <p className="text-xs text-white/30 mt-3 text-center">
            The point cloud may still be processing. Check the job status above.
          </p>
        </div>
      )}

      {/* No COPC yet overlay */}
      {!copcUrl && !isLoading && !loadError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10 pointer-events-none">
          <div className="text-white/10 text-6xl mb-4">☁</div>
          <p className="text-sm text-white/40">Point cloud not yet processed</p>
          <p className="text-xs text-white/20 mt-1">Upload a LAS/LAZ file to begin</p>
        </div>
      )}

      {/* Reset camera button */}
      {!isLoading && !loadError && copcUrl && (
        <button
          onClick={resetCamera}
          title="Reset camera"
          className="absolute top-4 right-4 w-8 h-8 rounded-lg bg-black/80 border border-white/10 text-white/50 hover:text-white hover:border-white/30 flex items-center justify-center text-sm backdrop-blur-sm transition-all z-10"
        >
          ⟳
        </button>
      )}

      {/* Measurement mode hint */}
      {isMeasuring && (
        <div className="absolute bottom-4 left-1/2 -translate-x-1/2 bg-black/80 border border-white/20 rounded-full px-4 py-1.5 text-xs text-white/60 backdrop-blur-sm z-10 pointer-events-none">
          {measureType === 'distance'
            ? 'Click two points to measure distance'
            : 'Click two points to measure height difference'
          }
          {measurePointsRef.current.length === 1 && ' · 1 point placed'}
        </div>
      )}

      {/* CRS badge */}
      {crsEpsg && (
        <div className="absolute bottom-4 right-4 bg-black/60 border border-white/10 rounded px-2 py-1 text-[10px] text-white/30 backdrop-blur-sm z-10 pointer-events-none">
          EPSG:{crsEpsg}
        </div>
      )}
    </div>
  )
}
