'use client'
import { useEffect, useRef } from 'react'

interface MapPanelProps {
  centerLat: number | null
  centerLon: number | null
  crsEpsg: number | null
  onClose: () => void
}

/**
 * MapPanel — 2D satellite/street map panel rendered alongside the 3D viewer.
 * Uses Leaflet with OpenStreetMap tiles. Leaflet is loaded client-side only
 * to avoid SSR issues with the `window` object.
 */
export default function MapPanel({ centerLat, centerLon, onClose }: MapPanelProps) {
  const mapRef = useRef<HTMLDivElement>(null)
  // Keep a ref to the Leaflet map instance so we can destroy it on unmount
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const leafletMapRef = useRef<any>(null)

  useEffect(() => {
    if (!mapRef.current) return

    // Dynamically import Leaflet to avoid SSR issues
    import('leaflet').then((L) => {
      // Leaflet requires its CSS — inject it once
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
      const zoom = centerLat !== null ? 16 : 4

      // Destroy existing map instance if any (React StrictMode double-mount)
      if (leafletMapRef.current) {
        leafletMapRef.current.remove()
        leafletMapRef.current = null
      }

      const map = L.map(mapRef.current!, { zoomControl: true }).setView([lat, lon], zoom)
      leafletMapRef.current = map

      // Satellite layer (Esri World Imagery)
      const satellite = L.tileLayer(
        'https://server.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/tile/{z}/{y}/{x}',
        { attribution: 'Tiles © Esri', maxZoom: 19 }
      )

      // Street layer (OpenStreetMap)
      const streets = L.tileLayer(
        'https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png',
        { attribution: '© OpenStreetMap contributors', maxZoom: 19 }
      )

      satellite.addTo(map)

      // Layer control
      L.control.layers(
        { 'Satellite': satellite, 'Streets': streets },
        {},
        { position: 'topright' }
      ).addTo(map)

      // Drop a marker at the dataset centre if coordinates are known
      if (centerLat !== null && centerLon !== null) {
        L.marker([centerLat, centerLon])
          .addTo(map)
          .bindPopup('Point cloud centre')
          .openPopup()
      }
    })

    return () => {
      if (leafletMapRef.current) {
        leafletMapRef.current.remove()
        leafletMapRef.current = null
      }
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [centerLat, centerLon])

  return (
    <div className="relative flex flex-col w-full h-full bg-gray-950 border-l border-gray-700">
      {/* Header */}
      <div className="flex items-center justify-between px-3 py-2 bg-gray-900 border-b border-gray-700 shrink-0">
        <span className="text-xs font-semibold text-gray-300 uppercase tracking-wider">2D Map</span>
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
