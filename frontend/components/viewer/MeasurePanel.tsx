'use client'

import type { Measurement } from './ViewerClient'

interface MeasurePanelProps {
  measurements: Measurement[]
  pendingPoints: [number, number, number][]
  measureMode: 'distance' | 'height' | null
  onClear: () => void
  onClose: () => void
}

function fmt(v: number | null): string {
  if (v === null) return '—'
  if (v >= 1000) return `${(v / 1000).toFixed(3)} km`
  return `${v.toFixed(3)} m`
}

export default function MeasurePanel({
  measurements,
  pendingPoints,
  measureMode,
  onClear,
  onClose,
}: MeasurePanelProps) {
  return (
    <div className="absolute left-20 top-1/2 -translate-y-1/2 z-20 w-72 bg-black/90 border border-[#222] rounded-xl p-4 backdrop-blur-sm max-h-[70vh] flex flex-col">
      <div className="flex items-center justify-between mb-4 flex-shrink-0">
        <h3 className="text-white text-sm font-medium">Measurements</h3>
        <div className="flex items-center gap-2">
          {measurements.length > 0 && (
            <button
              onClick={onClear}
              className="text-[#555] hover:text-white text-xs transition-colors"
            >
              Clear all
            </button>
          )}
          <button onClick={onClose} className="text-[#444] hover:text-white transition-colors text-lg leading-none">×</button>
        </div>
      </div>

      {/* Active measurement hint */}
      {measureMode && (
        <div className="mb-3 p-2.5 rounded-lg bg-[#111] border border-[#222] flex-shrink-0">
          <p className="text-white text-xs font-medium">
            {measureMode === 'distance' ? '📏 Distance' : '↕️ Height'} mode active
          </p>
          <p className="text-[#555] text-xs mt-1">
            {pendingPoints.length === 0
              ? 'Click first point on the cloud'
              : 'Click second point to complete'}
          </p>
          {pendingPoints.length === 1 && (
            <div className="mt-2 text-[#444] text-xs font-mono">
              P1: ({pendingPoints[0][0].toFixed(2)}, {pendingPoints[0][1].toFixed(2)}, {pendingPoints[0][2].toFixed(2)})
            </div>
          )}
        </div>
      )}

      {/* Results list */}
      <div className="overflow-y-auto flex-1 space-y-2">
        {measurements.length === 0 && !measureMode && (
          <p className="text-[#444] text-xs text-center py-4">
            Use 📏 or ↕️ buttons to start measuring
          </p>
        )}
        {[...measurements].reverse().map((m, idx) => (
          <div key={m.id} className="p-3 rounded-lg bg-[#0a0a0a] border border-[#1a1a1a]">
            <div className="flex items-center justify-between mb-1">
              <span className="text-[#666] text-xs">
                {m.type === 'distance' ? '📏 Distance' : '↕️ Height'} #{measurements.length - idx}
              </span>
              <span className="text-white text-sm font-medium tabular-nums">{fmt(m.value)}</span>
            </div>
            <div className="text-[#333] text-xs font-mono space-y-0.5">
              <div>A: ({m.points[0][0].toFixed(1)}, {m.points[0][1].toFixed(1)}, {m.points[0][2].toFixed(1)})</div>
              <div>B: ({m.points[1][0].toFixed(1)}, {m.points[1][1].toFixed(1)}, {m.points[1][2].toFixed(1)})</div>
            </div>
          </div>
        ))}
      </div>
    </div>
  )
}
