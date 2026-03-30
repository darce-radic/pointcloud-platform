/**
 * Viewer Store — Zustand store for cross-panel state synchronization.
 *
 * This store is the single source of truth for the tri-panel viewer:
 *   - 3D Point Cloud panel (CesiumViewer / Three.js canvas)
 *   - 2D Map panel (Leaflet / MapPanel)
 *   - 360° Panoramic panel (Pannellum)
 *
 * When the user clicks an asset in any panel, all three panels update
 * simultaneously via this shared state.
 */
import { create } from 'zustand'

export interface PanoramicImage {
  id: string
  image_url: string
  thumbnail_url: string | null
  lat: number
  lon: number
  heading_deg: number | null
  captured_at: string | null
  sequence_index: number | null
}

export interface SelectedAsset {
  id: string
  asset_type: string
  lat: number
  lon: number
  properties: Record<string, unknown>
}

export interface CameraPosition {
  lat: number
  lon: number
  heading?: number
}

interface ViewerState {
  // ── Active panoramic image ────────────────────────────────────────────────
  activePanorama: PanoramicImage | null
  setActivePanorama: (image: PanoramicImage | null) => void

  // ── Selected asset (synced across all panels) ─────────────────────────────
  selectedAsset: SelectedAsset | null
  setSelectedAsset: (asset: SelectedAsset | null) => void

  // ── Camera / map position (synced across 2D map and 3D viewer) ───────────
  cameraPosition: CameraPosition | null
  setCameraPosition: (pos: CameraPosition) => void

  // ── Panel visibility ──────────────────────────────────────────────────────
  panoramaOpen: boolean
  setPanoramaOpen: (open: boolean) => void

  // ── Trajectory data (loaded once, shared across panels) ──────────────────
  trajectoryImages: PanoramicImage[]
  setTrajectoryImages: (images: PanoramicImage[]) => void

  // ── Road assets GeoJSON (loaded once, shared across panels) ──────────────
  roadAssetsGeoJson: GeoJSON.FeatureCollection | null
  setRoadAssetsGeoJson: (geojson: GeoJSON.FeatureCollection | null) => void

  // ── Reset all state ───────────────────────────────────────────────────────
  reset: () => void
}

const initialState = {
  activePanorama: null,
  selectedAsset: null,
  cameraPosition: null,
  panoramaOpen: false,
  trajectoryImages: [],
  roadAssetsGeoJson: null,
}

export const useViewerStore = create<ViewerState>((set) => ({
  ...initialState,

  setActivePanorama: (image) =>
    set((state) => ({
      activePanorama: image,
      // When a panorama is selected, sync the camera position to its location
      cameraPosition: image
        ? { lat: image.lat, lon: image.lon, heading: image.heading_deg ?? undefined }
        : state.cameraPosition,
      panoramaOpen: image !== null,
    })),

  setSelectedAsset: (asset) =>
    set((state) => ({
      selectedAsset: asset,
      // When an asset is selected, move the camera to it
      cameraPosition: asset
        ? { lat: asset.lat, lon: asset.lon }
        : state.cameraPosition,
    })),

  setCameraPosition: (pos) => set({ cameraPosition: pos }),

  setPanoramaOpen: (open) => set({ panoramaOpen: open }),

  setTrajectoryImages: (images) => set({ trajectoryImages: images }),

  setRoadAssetsGeoJson: (geojson) => set({ roadAssetsGeoJson: geojson }),

  reset: () => set(initialState),
}))
