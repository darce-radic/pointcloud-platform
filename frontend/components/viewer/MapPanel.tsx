'use client'
import { useEffect, useRef, useCallback } from 'react'
import { useViewerStore, PanoramicImage } from '@/lib/stores/viewerStore'
import { API_BASE_URL } from '@/lib/api'

interface MapPanelProps {
  centerLat: number | null
  centerLon: number | null
  crsEpsg: number | null
  datasetId?: string
  onClose: () => void
}

/**
 * MapPanel — 2D satellite/street map panel rendered alongside the 3D viewer.
 *
 * Enhanced with:
 *  - Survey trajectory line (from panoramic_images sequence)
 *  - Camera position indicator (blue triangle) synced with 3D viewer
 *  - Road asset GeoJSON overlay with colour-coded markers
 *  - Click-on-map → fetch nearest panoramic image → update panoramic panel
 *  - Cross-panel sync via Zustand viewerStore
 */
export default function MapPanel({ centerLat, centerLon, datasetId, onClose }: MapPanelProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const leafletMapRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const cameraMarkerRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const trajectoryLayerRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const assetsLayerRef = useRef<any>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const panoramaMarkerRef = useRef<any>(null)

  const {
    trajectoryImages,
    roadAssetsGeoJson,
    cameraPosition,
    setActivePanorama,
    setCameraPosition,
    setTrajectoryImages,
  } = useViewerStore()

  // ── Asset type colour map ─────────────────────────────────────────────────
  const ASSET_COLORS: Record<string, string> = {
    traffic_sign: '#ef4444',
    road_marking: '#f59e0b',
    drain: '#3b82f6',
    manhole: '#8b5cf6',
    pole: '#10b981',
    default: '#6b7280',
  }

  // ── Fetch trajectory images on mount ─────────────────────────────────────
  useEffect(() => {
    if (!datasetId || trajectoryImages.length > 0) return
    fetch(`${API_BASE_URL}/api/v1/datasets/${datasetId}/images?limit=500`)
      .then((r) => r.ok ? r.json() : null)
      .then((data) => {
        if (data?.images?.length > 0) {
          setTrajectoryImages(data.images)
        }
      })
      .catch(() => {/* silently ignore */})
  }, [datasetId, trajectoryImages.length, setTrajectoryImages])

  // ── Initialise Leaflet map ────────────────────────────────────────────────
  useEffect(() => {
    if (!mapRef.current) return

    import('leaflet').then((L) => {
      if (!document.getElementById('leaflet-css')) {
        const link = document.createElement('link')
        link.id = 'leaflet-css'
        link.rel = 'stylesheet'
        link.href = 'https://unpkg.com/leaflet@1.9.4/dist/leaflet.css'
        document.head.appendChild(link)
      }

      // Fix default icon paths broken by webpack/next
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      delete (L.Icon.Default.prototype as any)._getIconUrl
      L.Icon.Default.mergeOptions({
        iconRetinaUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon-2x.png',
        iconUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-icon.png',
        shadowUrl: 'https://unpkg.com/leaflet@1.9.4/dist/images/marker-shadow.png',
      })

      const lat = centerLat ?? -33.8688
      const lon = centerLon ?? 151.2093
      const zoom = centerLat !== null ? 17 : 4

      if (leafletMapRef.current) {
        leafletMapRef.current.remove()
        leafletMapRef.current = null
      }

      const map = L.map(mapRef.current!, { zoomControl: true }).setView([lat, lon], zoom)
      leafletMapRef.current = map

      const satellite = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { attribution: 'Tiles © Esri', maxZoom: 21 }
      )
      const streets = L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        { attribution: '© OpenStreetMap contributors', maxZoom: 19 }
      )
      satellite.addTo(map)
      L.control.layers({ 'Satellite': satellite, 'Streets': streets }, {}, { position: 'topright' }).addTo(map)

      // ── Click on map → fetch nearest panoramic image ──────────────────────
      if (datasetId) {
        map.on('click', async (e: { latlng: { lat: number; lng: number } }) => {
          const { lat: clickLat, lng: clickLon } = e.latlng
          setCameraPosition({ lat: clickLat, lon: clickLon })
          try {
            const res = await fetch(
              `${API_BASE_URL}/api/v1/datasets/${datasetId}/images/nearest?lat=${clickLat}&lon=${clickLon}`
            )
            if (res.ok) {
              const img: PanoramicImage = await res.json()
              setActivePanorama(img)
            }
          } catch {/* silently ignore */}
        })
      }
    })

    return () => {
      if (leafletMapRef.current) {
        leafletMapRef.current.remove()
        leafletMapRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerLat, centerLon, datasetId])

  // ── Render trajectory line ────────────────────────────────────────────────
  useEffect(() => {
    const map = leafletMapRef.current
    if (!map || trajectoryImages.length === 0) return

    import('leaflet').then((L) => {
      // Remove existing trajectory layer
      if (trajectoryLayerRef.current) {
        map.removeLayer(trajectoryLayerRef.current)
      }

      const coords = trajectoryImages.map((img) => [img.lat, img.lon] as [number, number])
      const polyline = L.polyline(coords, {
        color: '#60a5fa',
        weight: 2,
        opacity: 0.8,
        dashArray: undefined,
      })
      polyline.addTo(map)
      trajectoryLayerRef.current = polyline

      // Add small dot markers for each image position
      const group = L.layerGroup()
      trajectoryImages.forEach((img, i) => {
        if (i % 5 !== 0) return // render every 5th point to avoid clutter
        const dot = L.circleMarker([img.lat, img.lon], {
          radius: 3,
          fillColor: '#93c5fd',
          fillOpacity: 0.7,
          color: '#1d4ed8',
          weight: 1,
        })
        dot.on('click', () => setActivePanorama(img))
        dot.bindTooltip(`Frame ${img.sequence_index ?? i}`, { direction: 'top', offset: [0, -4] })
        group.addLayer(dot)
      })
      group.addTo(map)
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [trajectoryImages])

  // ── Render road assets GeoJSON overlay ────────────────────────────────────
  useEffect(() => {
    const map = leafletMapRef.current
    if (!map || !roadAssetsGeoJson) return

    import('leaflet').then((L) => {
      if (assetsLayerRef.current) {
        map.removeLayer(assetsLayerRef.current)
      }

      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const layer = L.geoJSON(roadAssetsGeoJson as any, {
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        pointToLayer: (_feature: any, latlng: any) => {
          const assetType = _feature.properties?.asset_type ?? 'default'
          const color = ASSET_COLORS[assetType] ?? ASSET_COLORS.default
          return L.circleMarker(latlng, {
            radius: 6,
            fillColor: color,
            fillOpacity: 0.85,
            color: '#fff',
            weight: 1.5,
          })
        },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        style: (feature: any) => {
          const assetType = feature?.properties?.asset_type ?? 'default'
          return {
            color: ASSET_COLORS[assetType] ?? ASSET_COLORS.default,
            weight: 2,
            opacity: 0.8,
            fillOpacity: 0.3,
          }
        },
        // eslint-disable-next-line @typescript-eslint/no-explicit-any
        onEachFeature: (feature: any, lyr: any) => {
          const props = feature.properties ?? {}
          const lines = Object.entries(props)
            .filter(([k]) => !k.startsWith('_'))
            .map(([k, v]) => `<tr><td class="pr-2 text-gray-400">${k}</td><td class="font-mono">${v}</td></tr>`)
            .join('')
          lyr.bindPopup(
            `<div class="text-xs"><table>${lines}</table></div>`,
            { maxWidth: 280 }
          )
        },
      })
      layer.addTo(map)
      assetsLayerRef.current = layer
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [roadAssetsGeoJson])

  // ── Update camera position marker ─────────────────────────────────────────
  useEffect(() => {
    const map = leafletMapRef.current
    if (!map || !cameraPosition) return

    import('leaflet').then((L) => {
      // Create a directional triangle icon for the camera
      const headingRad = ((cameraPosition.heading ?? 0) * Math.PI) / 180
      const svgIcon = L.divIcon({
        html: `<svg width="20" height="20" viewBox="0 0 20 20" style="transform: rotate(${cameraPosition.heading ?? 0}deg)">
          <polygon points="10,2 17,18 10,14 3,18" fill="#3b82f6" stroke="#fff" stroke-width="1.5"/>
        </svg>`,
        className: '',
        iconSize: [20, 20],
        iconAnchor: [10, 10],
      })

      if (cameraMarkerRef.current) {
        cameraMarkerRef.current.setLatLng([cameraPosition.lat, cameraPosition.lon])
        cameraMarkerRef.current.setIcon(svgIcon)
      } else {
        const marker = L.marker([cameraPosition.lat, cameraPosition.lon], { icon: svgIcon })
        marker.addTo(map)
        cameraMarkerRef.current = marker
      }

      // Pan map to keep camera marker in view
      map.panTo([cameraPosition.lat, cameraPosition.lon], { animate: true, duration: 0.3 })
    })
  }, [cameraPosition])

  // ── Update panorama position marker ──────────────────────────────────────
  const activePanorama = useViewerStore((s) => s.activePanorama)
  useEffect(() => {
    const map = leafletMapRef.current
    if (!map || !activePanorama) return

    import('leaflet').then((L) => {
      const icon = L.divIcon({
        html: `<div style="width:10px;height:10px;background:#f59e0b;border:2px solid #fff;border-radius:50%;"></div>`,
        className: '',
        iconSize: [10, 10],
        iconAnchor: [5, 5],
      })

      if (panoramaMarkerRef.current) {
        panoramaMarkerRef.current.setLatLng([activePanorama.lat, activePanorama.lon])
      } else {
        const marker = L.marker([activePanorama.lat, activePanorama.lon], { icon })
        marker.addTo(map)
        panoramaMarkerRef.current = marker
      }
    })
  }, [activePanorama])

  return (
    <div className="relative flex flex-col w-full h-full bg-gray-950 border-l border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-700 shrink-0">
        <div className="flex items-center gap-3">
          <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">2D Map</span>
          {/* Legend */}
          <div className="flex items-center gap-2">
            <span className="flex items-center gap-1 text-xs text-gray-400">
              <span className="inline-block w-4 h-0.5 bg-blue-400" />Trajectory
            </span>
            {roadAssetsGeoJson && (
              <span className="flex items-center gap-1 text-xs text-gray-400">
                <span className="inline-block w-2 h-2 rounded-full bg-red-500" />Assets
              </span>
            )}
          </div>
        </div>
        <button
          onClick={onClose}
          className="text-gray-400 hover:text-white transition-colors text-lg leading-none"
          aria-label="Close map panel"
        >
          ✕
        </button>
      </div>

      {/* Map container */}
      <div ref={mapRef} className="flex-1 w-full" />

      {/* No-coordinates fallback */}
      {centerLat === null && (
        <div className="absolute inset-0 top-10 flex items-center justify-center pointer-events-none">
          <p className="text-xs text-gray-500 bg-gray-900/80 px-3 py-1.5 rounded">
            No geographic coordinates available for this dataset
          </p>
        </div>
      )}
    </div>
  )
}
