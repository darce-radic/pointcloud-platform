'use client'
/**
 * PanoramicViewer — 360° equirectangular panoramic image viewer.
 *
 * Uses Pannellum (loaded via CDN script tag) to render 360° panoramic images
 * captured by mobile mapping vehicles. Integrates with the Zustand viewerStore
 * to synchronize the active panorama with the 2D map and 3D point cloud panels.
 *
 * Features:
 *  - Equirectangular 360° image rendering
 *  - Compass/heading indicator
 *  - Brightness and contrast controls
 *  - Navigate to next/previous image in the survey sequence
 *  - Click-to-inspect: clicking in the panorama emits a lat/lon to the store
 */

import { useEffect, useRef, useState, useCallback } from 'react'
import { useViewerStore, PanoramicImage } from '@/lib/stores/viewerStore'

declare global {
  interface Window {
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    pannellum: any
  }
}

interface PanoramicViewerProps {
  datasetId: string
  className?: string
  initialImage?: import('@/lib/stores/viewerStore').PanoramicImage
  onClose?: () => void
}
export default function PanoramicViewer({ datasetId, className = '', initialImage, onClose }: PanoramicViewerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const viewerRef = useRef<any>(null)
  const [pannellumLoaded, setPannellumLoaded] = useState(false)
  const [brightness, setBrightness] = useState(100)
  const [contrast, setContrast] = useState(100)
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const {
    activePanorama,
    trajectoryImages,
    setActivePanorama,
    setCameraPosition,
    panoramaOpen,
  } = useViewerStore()

  // ── Load Pannellum from CDN ────────────────────────────────────────────────
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (window.pannellum) {
      setPannellumLoaded(true)
      return
    }

    // Load Pannellum CSS
    const link = document.createElement('link')
    link.rel = 'stylesheet'
    link.href = 'https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.css'
    document.head.appendChild(link)

    // Load Pannellum JS
    const script = document.createElement('script')
    script.src = 'https://cdn.jsdelivr.net/npm/pannellum@2.5.6/build/pannellum.js'
    script.async = true
    script.onload = () => setPannellumLoaded(true)
    script.onerror = () => setError('Failed to load panoramic viewer library')
    document.head.appendChild(script)

    return () => {
      // Don't remove on cleanup — keep loaded for the session
    }
  }, [])

  // ── Initialise / update Pannellum when panorama changes ───────────────────
  useEffect(() => {
    if (!pannellumLoaded || !containerRef.current || !activePanorama) return

    setLoading(true)
    setError(null)

    // Destroy previous viewer instance
    if (viewerRef.current) {
      try {
        viewerRef.current.destroy()
      } catch {
        // ignore
      }
      viewerRef.current = null
    }

    try {
      viewerRef.current = window.pannellum.viewer(containerRef.current, {
        type: 'equirectangular',
        panorama: activePanorama.image_url,
        autoLoad: true,
        autoRotate: 0,
        compass: true,
        northOffset: activePanorama.heading_deg ?? 0,
        showControls: false, // we render our own controls
        mouseZoom: true,
        draggable: true,
        friction: 0.15,
        onLoad: () => setLoading(false),
        onError: (err: string) => {
          setLoading(false)
          setError(`Failed to load panorama: ${err}`)
        },
      })
    } catch (err) {
      setLoading(false)
      setError(`Viewer error: ${String(err)}`)
    }
  }, [pannellumLoaded, activePanorama])

  // ── Apply brightness/contrast via CSS filter ──────────────────────────────
  useEffect(() => {
    if (!containerRef.current) return
    const canvas = containerRef.current.querySelector('canvas')
    if (canvas) {
      canvas.style.filter = `brightness(${brightness}%) contrast(${contrast}%)`
    }
  }, [brightness, contrast])

  // ── Navigate to adjacent image in sequence ────────────────────────────────
  const navigateSequence = useCallback(
    async (direction: 'prev' | 'next') => {
      if (!activePanorama || trajectoryImages.length === 0) return

      const currentIdx = trajectoryImages.findIndex((img) => img.id === activePanorama.id)
      if (currentIdx === -1) return

      const nextIdx = direction === 'next' ? currentIdx + 1 : currentIdx - 1
      if (nextIdx < 0 || nextIdx >= trajectoryImages.length) return

      const nextImage = trajectoryImages[nextIdx]
      setActivePanorama(nextImage)
      setCameraPosition({ lat: nextImage.lat, lon: nextImage.lon, heading: nextImage.heading_deg ?? undefined })
    },
    [activePanorama, trajectoryImages, setActivePanorama, setCameraPosition]
  )

  // ── Fetch nearest image when camera position changes from other panels ─────
  const fetchNearestImage = useCallback(
    async (lat: number, lon: number) => {
      try {
        const res = await fetch(
          `/api/v1/datasets/${datasetId}/images/nearest?lat=${lat}&lon=${lon}`
        )
        if (!res.ok) return
        const img: PanoramicImage = await res.json()
        if (img.id !== activePanorama?.id) {
          setActivePanorama(img)
        }
      } catch {
        // silently ignore
      }
    },
    [datasetId, activePanorama, setActivePanorama]
  )

  // Subscribe to camera position changes from other panels
  useEffect(() => {
    const unsub = useViewerStore.subscribe(
      (state) => {
        const pos = state.cameraPosition
        if (pos && panoramaOpen) {
          fetchNearestImage(pos.lat, pos.lon)
        }
      }
    )
    return unsub
  }, [fetchNearestImage, panoramaOpen])

  const currentIndex = activePanorama
    ? trajectoryImages.findIndex((img) => img.id === activePanorama.id)
    : -1

  if (!activePanorama) {
    return (
      <div className={`flex items-center justify-center bg-gray-900 text-gray-500 text-sm ${className}`}>
        <div className="text-center">
          <svg className="w-12 h-12 mx-auto mb-3 opacity-30" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={1.5}
              d="M15 10l4.553-2.069A1 1 0 0121 8.82v6.36a1 1 0 01-1.447.894L15 14M3 8a2 2 0 012-2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V8z" />
          </svg>
          <p>Click a point on the map to load a panoramic image</p>
        </div>
      </div>
    )
  }

  return (
    <div className={`relative flex flex-col bg-black ${className}`}>
      {/* Pannellum container */}
      <div ref={containerRef} className="flex-1 w-full h-full" />

      {/* Loading overlay */}
      {loading && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/60 z-10">
          <div className="flex flex-col items-center gap-2">
            <div className="w-8 h-8 border-2 border-blue-400 border-t-transparent rounded-full animate-spin" />
            <span className="text-white text-sm">Loading panorama…</span>
          </div>
        </div>
      )}

      {/* Error overlay */}
      {error && (
        <div className="absolute inset-0 flex items-center justify-center bg-black/80 z-10">
          <div className="text-center text-red-400 px-4">
            <p className="font-medium mb-1">Failed to load panorama</p>
            <p className="text-xs text-gray-400">{error}</p>
          </div>
        </div>
      )}

      {/* Controls bar */}
      <div className="absolute bottom-0 left-0 right-0 bg-black/70 backdrop-blur-sm px-3 py-2 flex items-center gap-3 z-20">
        {/* Sequence navigation */}
        <button
          onClick={() => navigateSequence('prev')}
          disabled={currentIndex <= 0}
          className="p-1.5 rounded hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          title="Previous image"
        >
          <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M15 19l-7-7 7-7" />
          </svg>
        </button>

        <span className="text-xs text-gray-400 min-w-[60px] text-center">
          {currentIndex >= 0 ? `${currentIndex + 1} / ${trajectoryImages.length}` : '—'}
        </span>

        <button
          onClick={() => navigateSequence('next')}
          disabled={currentIndex >= trajectoryImages.length - 1}
          className="p-1.5 rounded hover:bg-white/10 disabled:opacity-30 disabled:cursor-not-allowed transition-colors"
          title="Next image"
        >
          <svg className="w-4 h-4 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2} d="M9 5l7 7-7 7" />
          </svg>
        </button>

        <div className="flex-1" />

        {/* Brightness control */}
        <div className="flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M12 3v1m0 16v1m9-9h-1M4 12H3m15.364 6.364l-.707-.707M6.343 6.343l-.707-.707m12.728 0l-.707.707M6.343 17.657l-.707.707M16 12a4 4 0 11-8 0 4 4 0 018 0z" />
          </svg>
          <input
            type="range" min={50} max={200} value={brightness}
            onChange={(e) => setBrightness(Number(e.target.value))}
            className="w-16 h-1 accent-blue-400"
            title={`Brightness: ${brightness}%`}
          />
        </div>

        {/* Contrast control */}
        <div className="flex items-center gap-1.5">
          <svg className="w-3.5 h-3.5 text-gray-400 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor">
            <path strokeLinecap="round" strokeLinejoin="round" strokeWidth={2}
              d="M20.354 15.354A9 9 0 018.646 3.646 9.003 9.003 0 0012 21a9.003 9.003 0 008.354-5.646z" />
          </svg>
          <input
            type="range" min={50} max={200} value={contrast}
            onChange={(e) => setContrast(Number(e.target.value))}
            className="w-16 h-1 accent-blue-400"
            title={`Contrast: ${contrast}%`}
          />
        </div>

        {/* Heading indicator */}
        {activePanorama.heading_deg !== null && (
          <span className="text-xs text-gray-400 font-mono">
            {Math.round(activePanorama.heading_deg ?? 0)}°
          </span>
        )}
      </div>
    </div>
  )
}
