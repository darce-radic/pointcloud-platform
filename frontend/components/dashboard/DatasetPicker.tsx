'use client'

/**
 * DatasetPicker.tsx
 *
 * A full-screen modal overlay that lets users browse, search, and filter
 * their datasets and navigate directly to the viewer, road assets demo,
 * or dataset detail page — no manual URL composition required.
 *
 * Usage:
 *   <DatasetPicker
 *     open={open}
 *     onClose={() => setOpen(false)}
 *     mode="road-assets"
 *   />
 */

import { useEffect, useState, useCallback, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import type { Dataset } from '@/types'

type PickerMode = 'viewer' | 'road-assets' | 'bim' | 'pick'
type FilterStatus = 'all' | 'ready' | 'processing' | 'failed'

interface DatasetPickerProps {
  open: boolean
  onClose: () => void
  onSelect?: (dataset: Dataset) => void
  mode?: PickerMode
  title?: string
}

// ── Helpers ───────────────────────────────────────────────────────────────────
function formatBytes(bytes: number | null): string {
  if (!bytes) return '—'
  if (bytes < 1_048_576) return `${(bytes / 1024).toFixed(1)} KB`
  if (bytes < 1_073_741_824) return `${(bytes / 1_048_576).toFixed(1)} MB`
  return `${(bytes / 1_073_741_824).toFixed(2)} GB`
}

function formatPoints(n: number | null): string {
  if (!n) return '—'
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M pts`
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K pts`
  return `${n} pts`
}

function timeAgo(dateStr: string): string {
  const diff = Date.now() - new Date(dateStr).getTime()
  const mins = Math.floor(diff / 60_000)
  if (mins < 1) return 'just now'
  if (mins < 60) return `${mins}m ago`
  const hrs = Math.floor(mins / 60)
  if (hrs < 24) return `${hrs}h ago`
  const days = Math.floor(hrs / 24)
  if (days < 30) return `${days}d ago`
  return new Date(dateStr).toLocaleDateString()
}

const STATUS_DOT: Record<string, string> = {
  ready:      'bg-white/60',
  processing: 'bg-white/80 animate-pulse',
  failed:     'bg-red-400',
  uploading:  'bg-white/20',
  uploaded:   'bg-white/20',
  pending:    'bg-white/10',
}

const STATUS_LABEL: Record<string, string> = {
  ready:      'Ready',
  processing: 'Processing',
  failed:     'Failed',
  uploading:  'Uploading',
  uploaded:   'Uploaded',
  pending:    'Pending',
}

const MODE_CONFIG: Record<PickerMode, { heading: string; cta: string; requiresReady: boolean }> = {
  'viewer':      { heading: 'Select dataset to open in 3D Viewer',     cta: 'Open in Viewer',    requiresReady: true  },
  'road-assets': { heading: 'Select dataset for Road Asset Detection',  cta: 'Open Road Assets',  requiresReady: false },
  'bim':         { heading: 'Select dataset for BIM Extraction',        cta: 'Open BIM Viewer',   requiresReady: true  },
  'pick':        { heading: 'Select a dataset',                         cta: 'Select',            requiresReady: false },
}

// ── Component ─────────────────────────────────────────────────────────────────
export default function DatasetPicker({ open, onClose, onSelect, mode = 'pick', title }: DatasetPickerProps) {
  const router = useRouter()
  const supabase = createClient()
  const searchRef = useRef<HTMLInputElement>(null)

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  const [statusFilter, setStatusFilter] = useState<FilterStatus>('all')
  const [hoveredId, setHoveredId] = useState<string | null>(null)

  const cfg = MODE_CONFIG[mode]

  // ── Fetch datasets ──────────────────────────────────────────────────────────
  const fetchDatasets = useCallback(async () => {
    setLoading(true)
    setError(null)
    try {
      const { data, error: err } = await supabase
        .from('datasets')
        .select('id, name, format, status, point_count, file_size_bytes, crs_epsg, bounding_box, copc_url, road_assets_url, created_at, updated_at, project_id, organization_id')
        .order('created_at', { ascending: false })
        .limit(200)

      if (err) throw err
      setDatasets((data as Dataset[]) || [])
    } catch (e: any) {
      setError(e.message || 'Failed to load datasets')
    } finally {
      setLoading(false)
    }
  }, [supabase])

  useEffect(() => {
    if (open) {
      fetchDatasets()
      // Focus search on open
      setTimeout(() => searchRef.current?.focus(), 100)
    }
  }, [open, fetchDatasets])

  // ── Keyboard: Escape to close ───────────────────────────────────────────────
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose()
    }
    if (open) window.addEventListener('keydown', handler)
    return () => window.removeEventListener('keydown', handler)
  }, [open, onClose])

  // ── Filtered list ───────────────────────────────────────────────────────────
  const filtered = datasets.filter(d => {
    const matchesQuery = !query || d.name.toLowerCase().includes(query.toLowerCase())
    const matchesStatus =
      statusFilter === 'all' ||
      (statusFilter === 'ready' && d.status === 'ready') ||
      (statusFilter === 'processing' && (d.status === 'processing' || d.status === 'uploading')) ||
      (statusFilter === 'failed' && d.status === 'failed')
    return matchesQuery && matchesStatus
  })

  // ── Handle selection ────────────────────────────────────────────────────────
  const handleSelect = useCallback((dataset: Dataset) => {
    if (onSelect) {
      onSelect(dataset)
      onClose()
      return
    }
    onClose()
    switch (mode) {
      case 'viewer':
        router.push(`/viewer/${dataset.id}`)
        break
      case 'road-assets':
        router.push(`/demo/road-assets?id=${dataset.id}`)
        break
      case 'bim':
        router.push(`/datasets/${dataset.id}`)
        break
      default:
        router.push(`/datasets/${dataset.id}`)
    }
  }, [mode, onSelect, onClose, router])

  if (!open) return null

  // ── Render ─────────────────────────────────────────────────────────────────
  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/80 backdrop-blur-sm"
      onClick={e => { if (e.target === e.currentTarget) onClose() }}
    >
      <div className="relative w-full max-w-2xl max-h-[80vh] flex flex-col bg-[#0a0a0a] border border-white/10 rounded-2xl shadow-2xl overflow-hidden">

        {/* ── Header ── */}
        <div className="flex items-center justify-between px-5 py-4 border-b border-white/8 shrink-0">
          <div>
            <h2 className="text-sm font-semibold text-white">{title ?? cfg.heading}</h2>
            <p className="text-xs text-white/30 mt-0.5">
              {datasets.length > 0 ? `${datasets.length} dataset${datasets.length !== 1 ? 's' : ''} available` : 'Loading…'}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-7 h-7 rounded-lg bg-white/5 hover:bg-white/10 border border-white/8 text-white/40 hover:text-white/80 flex items-center justify-center text-sm transition-all"
          >
            ✕
          </button>
        </div>

        {/* ── Search + filter bar ── */}
        <div className="flex items-center gap-2 px-4 py-3 border-b border-white/8 shrink-0">
          {/* Search */}
          <div className="relative flex-1">
            <span className="absolute left-3 top-1/2 -translate-y-1/2 text-white/30 text-xs pointer-events-none">⌕</span>
            <input
              ref={searchRef}
              type="text"
              placeholder="Search datasets…"
              value={query}
              onChange={e => setQuery(e.target.value)}
              className="w-full bg-white/5 border border-white/8 rounded-lg pl-8 pr-3 py-2 text-sm text-white placeholder-white/25 focus:outline-none focus:border-white/20 focus:bg-white/8 transition-all"
            />
            {query && (
              <button
                onClick={() => setQuery('')}
                className="absolute right-3 top-1/2 -translate-y-1/2 text-white/30 hover:text-white/60 text-xs"
              >
                ✕
              </button>
            )}
          </div>

          {/* Status filter pills */}
          <div className="flex items-center gap-1">
            {(['all', 'ready', 'processing', 'failed'] as FilterStatus[]).map(s => (
              <button
                key={s}
                onClick={() => setStatusFilter(s)}
                className={`px-2.5 py-1.5 rounded-md text-xs font-medium transition-all capitalize ${
                  statusFilter === s
                    ? 'bg-white text-black'
                    : 'bg-white/5 text-white/40 hover:text-white/70 hover:bg-white/8 border border-white/8'
                }`}
              >
                {s}
              </button>
            ))}
          </div>

          {/* Refresh */}
          <button
            onClick={fetchDatasets}
            disabled={loading}
            className="w-8 h-8 rounded-lg bg-white/5 border border-white/8 text-white/30 hover:text-white/60 hover:bg-white/8 flex items-center justify-center text-sm transition-all disabled:opacity-30"
            title="Refresh"
          >
            {loading ? (
              <span className="w-3 h-3 border border-white/20 border-t-white/60 rounded-full animate-spin block" />
            ) : '↻'}
          </button>
        </div>

        {/* ── Dataset list ── */}
        <div className="flex-1 overflow-y-auto">
          {error && (
            <div className="m-4 p-3 bg-red-900/20 border border-red-500/20 rounded-lg text-xs text-red-400">
              {error}
            </div>
          )}

          {!loading && filtered.length === 0 && (
            <div className="flex flex-col items-center justify-center py-16 text-center">
              <div className="text-white/10 text-4xl mb-3">◈</div>
              <p className="text-sm text-white/30">
                {query ? `No datasets matching "${query}"` : 'No datasets found'}
              </p>
              {!query && (
                <p className="text-xs text-white/20 mt-1">Upload a LAS/LAZ file to get started</p>
              )}
            </div>
          )}

          {filtered.length > 0 && (
            <div className="p-3 grid gap-2">
              {filtered.map(dataset => {
                const isDisabled = cfg.requiresReady && dataset.status !== 'ready'
                const isHovered = hoveredId === dataset.id
                const hasRoadAssets = !!(dataset as any).road_assets_url
                const hasCopc = !!dataset.copc_url

                return (
                  <button
                    key={dataset.id}
                    onClick={() => !isDisabled && handleSelect(dataset)}
                    onMouseEnter={() => setHoveredId(dataset.id)}
                    onMouseLeave={() => setHoveredId(null)}
                    disabled={isDisabled}
                    className={`w-full text-left rounded-xl border p-4 transition-all group ${
                      isDisabled
                        ? 'border-white/5 bg-white/2 opacity-40 cursor-not-allowed'
                        : isHovered
                          ? 'border-white/20 bg-white/6 cursor-pointer'
                          : 'border-white/8 bg-white/3 hover:border-white/15 hover:bg-white/5 cursor-pointer'
                    }`}
                  >
                    <div className="flex items-start gap-3">
                      {/* Status dot */}
                      <div className="mt-1.5 shrink-0">
                        <span className={`block w-2 h-2 rounded-full ${STATUS_DOT[dataset.status] || 'bg-white/20'}`} />
                      </div>

                      {/* Main content */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2 mb-1">
                          <span className="text-sm font-medium text-white/90 truncate">{dataset.name}</span>
                          {dataset.format && (
                            <span className="text-[10px] font-mono text-white/30 bg-white/5 px-1.5 py-0.5 rounded uppercase shrink-0">
                              {dataset.format}
                            </span>
                          )}
                        </div>

                        {/* Meta row */}
                        <div className="flex items-center gap-3 text-[11px] text-white/30">
                          <span>{STATUS_LABEL[dataset.status] || dataset.status}</span>
                          {dataset.point_count && <span>·</span>}
                          {dataset.point_count && <span>{formatPoints(dataset.point_count)}</span>}
                          {dataset.file_size_bytes && <span>·</span>}
                          {dataset.file_size_bytes && <span>{formatBytes(dataset.file_size_bytes)}</span>}
                          <span>·</span>
                          <span>{timeAgo(dataset.created_at)}</span>
                        </div>

                        {/* Capability badges */}
                        <div className="flex items-center gap-1.5 mt-2">
                          {hasCopc && (
                            <span className="text-[10px] text-white/40 bg-white/5 border border-white/8 px-1.5 py-0.5 rounded">
                              3D Viewer
                            </span>
                          )}
                          {hasRoadAssets && (
                            <span className="text-[10px] text-white/40 bg-white/5 border border-white/8 px-1.5 py-0.5 rounded">
                              Road Assets
                            </span>
                          )}
                          {(dataset as any).ifc_url && (
                            <span className="text-[10px] text-white/40 bg-white/5 border border-white/8 px-1.5 py-0.5 rounded">
                              BIM
                            </span>
                          )}
                          {dataset.crs_epsg && (
                            <span className="text-[10px] text-white/30 bg-white/3 border border-white/5 px-1.5 py-0.5 rounded font-mono">
                              EPSG:{dataset.crs_epsg}
                            </span>
                          )}
                        </div>
                      </div>

                      {/* CTA arrow */}
                      <div className={`shrink-0 flex items-center self-center transition-all ${
                        isDisabled ? 'opacity-0' : isHovered ? 'opacity-100 translate-x-0' : 'opacity-0 -translate-x-1'
                      }`}>
                        <span className="text-white/50 text-sm">→</span>
                      </div>
                    </div>

                    {/* Disabled reason */}
                    {isDisabled && (
                      <p className="text-[10px] text-white/25 mt-2 ml-5">
                        Dataset must be in &quot;ready&quot; state to use this feature
                      </p>
                    )}
                  </button>
                )
              })}
            </div>
          )}
        </div>

        {/* ── Footer ── */}
        <div className="px-5 py-3 border-t border-white/8 flex items-center justify-between shrink-0">
          <p className="text-[11px] text-white/25">
            {filtered.length !== datasets.length
              ? `Showing ${filtered.length} of ${datasets.length} datasets`
              : `${datasets.length} dataset${datasets.length !== 1 ? 's' : ''}`
            }
          </p>
          <button
            onClick={onClose}
            className="text-xs text-white/30 hover:text-white/60 transition-colors"
          >
            Cancel
          </button>
        </div>
      </div>
    </div>
  )
}
