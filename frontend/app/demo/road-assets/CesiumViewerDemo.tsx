'use client'

/**
 * CesiumViewerDemo.tsx
 *
 * A self-contained CesiumJS viewer for the Road Assets demo page.
 * Accepts a live COPC URL and a GeoJSON FeatureCollection of road assets,
 * renders the point cloud as a 3D Tiles tileset, and overlays the GeoJSON
 * as coloured Cesium entities (polygons, polylines, billboards).
 *
 * This is intentionally separate from the main ViewerClient CesiumViewer
 * so the demo page has no dependency on the full viewer state machine.
 */

import { useEffect, useRef, useState } from 'react'

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
}

interface CesiumViewerDemoProps {
  copcUrl: string | null
  boundingBox?: {
    minX: number; minY: number; minZ: number
    maxX: number; maxY: number; maxZ: number
  } | null
  roadAssetsGeoJson: GeoFeatureCollection | null
}

// Asset type → Cesium colour hex
const ASSET_COLORS: Record<string, string> = {
  road_surface:    '#a3a3a3',
  road_centreline: '#f59e0b',
  road_marking:    '#ffffff',
  kerb:            '#fb923c',
  traffic_sign:    '#ef4444',
  drain_manhole:   '#38bdf8',
  manhole:         '#38bdf8',
  drain:           '#7dd3fc',
}

export default function CesiumViewerDemo({ copcUrl, boundingBox, roadAssetsGeoJson }: CesiumViewerDemoProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const viewerRef = useRef<any>(null)
  const tilesetRef = useRef<any>(null)
  const overlayRef = useRef<any>(null) // EntityCollection for GeoJSON overlay
  const [isLoading, setIsLoading] = useState(true)
  const [loadError, setLoadError] = useState<string | null>(null)

  // ── Initialise Cesium ───────────────────────────────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    let viewer: any = null
    let destroyed = false

    const init = async () => {
      try {
        const Cesium = await import('cesium')
        await import('cesium/Build/Cesium/Widgets/widgets.css')

        ;(window as any).CESIUM_BASE_URL =
          process.env.NEXT_PUBLIC_CESIUM_BASE_URL ?? '/cesium'

        if (destroyed) return

        Cesium.Ion.defaultAccessToken =
          process.env.NEXT_PUBLIC_CESIUM_ION_TOKEN ||
          'eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJqdGkiOiJlYWE1OWUxNy1mMWZiLTQzYjYtYTQ0OS1kMWFjYmFkNjc4ZTciLCJpZCI6NTc3MzMsImlhdCI6MTYyNzg0NTE4Mn0.XcKpgANiY19MC4bdFUXMVEBToBmqS8kuYpUlxJHYZxk'

        viewer = new Cesium.Viewer(containerRef.current!, {
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
          terrain: Cesium.Terrain.fromWorldTerrain({
            requestWaterMask: false,
            requestVertexNormals: false,
          }),
        })

        viewer.scene.backgroundColor = Cesium.Color.fromCssColorString('#080a0f')
        viewer.scene.globe.enableLighting = false
        viewer.scene.globe.baseColor = Cesium.Color.fromCssColorString('#1a1a2e')
        ;(viewer.cesiumWidget.creditContainer as HTMLElement).style.display = 'none'

        viewerRef.current = viewer

        // Load COPC point cloud
        if (copcUrl) {
          await loadPointCloud(Cesium, viewer, copcUrl)
        } else {
          // Fly to bounding box centre or default
          const lon = boundingBox ? (boundingBox.minX + boundingBox.maxX) / 2 : 151.2093
          const lat = boundingBox ? (boundingBox.minY + boundingBox.maxY) / 2 : -33.8688
          viewer.camera.flyTo({
            destination: Cesium.Cartesian3.fromDegrees(lon, lat, 500),
            orientation: { heading: 0, pitch: Cesium.Math.toRadians(-45), roll: 0 },
          })
          setIsLoading(false)
        }

      } catch (err: any) {
        if (!destroyed) {
          console.error('CesiumViewerDemo init error:', err)
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

  // ── Load COPC as 3D Tiles ───────────────────────────────────────────────────
  const loadPointCloud = async (Cesium: any, viewer: any, url: string) => {
    try {
      setIsLoading(true)
      setLoadError(null)

      const tileset = await Cesium.Cesium3DTileset.fromUrl(url, {
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

      viewer.scene.primitives.add(tileset)
      tilesetRef.current = tileset

      // Default RGB style
      tileset.style = new Cesium.Cesium3DTileStyle({ color: 'color("white")', pointSize: 2 })

      await viewer.zoomTo(tileset)
      tileset.allTilesLoaded.addEventListener(() => setIsLoading(false))
      setIsLoading(false)

    } catch (err: any) {
      console.error('Failed to load point cloud:', err)
      setLoadError(`Could not load point cloud: ${err?.message || 'Unknown error'}`)
      setIsLoading(false)
    }
  }

  // ── Overlay GeoJSON road assets as Cesium entities ─────────────────────────
  useEffect(() => {
    if (!viewerRef.current || !roadAssetsGeoJson) return

    const viewer = viewerRef.current
    if (!viewer || viewer.isDestroyed()) return

    import('cesium').then(Cesium => {
      // Remove previous overlay entities
      if (overlayRef.current) {
        viewer.entities.removeAll()
        overlayRef.current = null
      }

      for (const feature of roadAssetsGeoJson.features) {
        const assetType = String(feature.properties.asset_type || '')
        const colorHex = ASSET_COLORS[assetType] || '#888888'
        const cesiumColor = Cesium.Color.fromCssColorString(colorHex)
        const geom = feature.geometry

        if (geom.type === 'Polygon') {
          // Build a flat polygon on the ground
          const ring = geom.coordinates[0]
          const positions = ring.map(([lon, lat, alt]) =>
            Cesium.Cartesian3.fromDegrees(lon, lat, alt ?? 0)
          )
          viewer.entities.add({
            polygon: {
              hierarchy: new Cesium.PolygonHierarchy(positions),
              material: cesiumColor.withAlpha(0.25),
              outline: true,
              outlineColor: cesiumColor.withAlpha(0.8),
              outlineWidth: 1,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
          })

        } else if (geom.type === 'LineString') {
          const positions = geom.coordinates.map(([lon, lat, alt]) =>
            Cesium.Cartesian3.fromDegrees(lon, lat, alt ?? 0)
          )
          viewer.entities.add({
            polyline: {
              positions,
              width: 2,
              material: new Cesium.ColorMaterialProperty(cesiumColor.withAlpha(0.9)),
              clampToGround: true,
            },
          })

        } else if (geom.type === 'Point') {
          const [lon, lat, alt] = geom.coordinates
          viewer.entities.add({
            position: Cesium.Cartesian3.fromDegrees(lon, lat, alt ?? 0),
            point: {
              pixelSize: 8,
              color: cesiumColor,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 1,
              heightReference: Cesium.HeightReference.CLAMP_TO_GROUND,
            },
            label: {
              text: ASSET_COLORS[assetType] ? assetType.replace(/_/g, ' ') : assetType,
              font: '11px sans-serif',
              fillColor: Cesium.Color.WHITE,
              outlineColor: Cesium.Color.BLACK,
              outlineWidth: 2,
              style: Cesium.LabelStyle.FILL_AND_OUTLINE,
              verticalOrigin: Cesium.VerticalOrigin.BOTTOM,
              pixelOffset: new Cesium.Cartesian2(0, -12),
              show: false, // only show on hover via InfoBox
            },
          })
        }
      }

      overlayRef.current = true
    })
  }, [roadAssetsGeoJson])

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div className="relative w-full h-full bg-[#080a0f]">
      <div ref={containerRef} className="absolute inset-0" />

      {isLoading && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#080a0f]/80 backdrop-blur-sm z-10 pointer-events-none">
          <div className="w-8 h-8 border-2 border-white/20 border-t-white/80 rounded-full animate-spin mb-3" />
          <p className="text-sm text-white/60">Loading 3D point cloud…</p>
        </div>
      )}

      {loadError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center bg-[#080a0f]/90 z-10 p-8">
          <div className="text-red-400 text-4xl mb-4">⚠</div>
          <p className="text-sm text-white/70 text-center max-w-sm">{loadError}</p>
          <p className="text-xs text-white/30 mt-3 text-center">
            The point cloud may still be processing. Switch to 2D view to see extracted assets.
          </p>
        </div>
      )}

      {!copcUrl && !isLoading && !loadError && (
        <div className="absolute inset-0 flex flex-col items-center justify-center z-10 pointer-events-none">
          <div className="text-white/10 text-6xl mb-4">☁</div>
          <p className="text-sm text-white/40">Point cloud not yet processed</p>
          <p className="text-xs text-white/20 mt-1">Switch to 2D view to see extracted assets</p>
        </div>
      )}

      {/* GeoJSON overlay legend */}
      {roadAssetsGeoJson && !isLoading && (
        <div className="absolute bottom-4 left-4 bg-black/70 border border-white/10 rounded-lg px-3 py-2 text-[10px] text-white/50 backdrop-blur-sm pointer-events-none z-10">
          {roadAssetsGeoJson.features.length} road assets overlaid
        </div>
      )}
    </div>
  )
}
