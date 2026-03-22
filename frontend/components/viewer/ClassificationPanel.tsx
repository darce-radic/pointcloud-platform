'use client'

// ASPRS LAS classification labels
const LAS_CLASSES: Record<number, string> = {
  0: 'Never Classified',
  1: 'Unclassified',
  2: 'Ground',
  3: 'Low Vegetation',
  4: 'Medium Vegetation',
  5: 'High Vegetation',
  6: 'Building',
  7: 'Low Point (Noise)',
  8: 'Reserved',
  9: 'Water',
  10: 'Rail',
  11: 'Road Surface',
  12: 'Reserved',
  13: 'Wire – Guard',
  14: 'Wire – Conductor',
  15: 'Transmission Tower',
  16: 'Wire Connector',
  17: 'Bridge Deck',
  18: 'High Noise',
}

// Distinct colours per class (CSS hex)
const CLASS_COLORS: Record<number, string> = {
  0: '#555555',
  1: '#888888',
  2: '#c8a46e',  // Ground – sandy brown
  3: '#4caf50',  // Low veg – light green
  4: '#2e7d32',  // Med veg – mid green
  5: '#1b5e20',  // High veg – dark green
  6: '#ef5350',  // Building – red
  7: '#f44336',  // Noise – bright red
  8: '#9e9e9e',
  9: '#42a5f5',  // Water – blue
  10: '#ff9800', // Rail – orange
  11: '#bdbdbd', // Road – grey
  12: '#9e9e9e',
  13: '#ffee58', // Wire – yellow
  14: '#fdd835',
  15: '#ff6f00',
  16: '#ffa000',
  17: '#8d6e63', // Bridge – brown
  18: '#e53935',
}

interface ClassificationPanelProps {
  classifications: Uint8Array
  visibleClasses: Set<number>
  onChange: (next: Set<number>) => void
  onClose: () => void
}

export default function ClassificationPanel({
  classifications,
  visibleClasses,
  onChange,
  onClose,
}: ClassificationPanelProps) {
  // Count points per class
  const counts: Record<number, number> = {}
  for (let i = 0; i < classifications.length; i++) {
    const c = classifications[i]
    counts[c] = (counts[c] ?? 0) + 1
  }
  const presentClasses = Object.keys(counts).map(Number).sort((a, b) => a - b)
  const total = classifications.length

  const toggle = (cls: number) => {
    const next = new Set(visibleClasses)
    if (next.has(cls)) {
      next.delete(cls)
    } else {
      next.add(cls)
    }
    onChange(next)
  }

  const showAll = () => onChange(new Set(presentClasses))
  const hideAll = () => onChange(new Set())

  return (
    <div className="absolute left-20 top-1/2 -translate-y-1/2 z-20 w-72 bg-black/90 border border-[#222] rounded-xl p-4 backdrop-blur-sm max-h-[70vh] flex flex-col">
      <div className="flex items-center justify-between mb-3 flex-shrink-0">
        <h3 className="text-white text-sm font-medium">Classifications</h3>
        <div className="flex items-center gap-2">
          <button onClick={showAll} className="text-[#555] hover:text-white text-xs transition-colors">All</button>
          <span className="text-[#333] text-xs">·</span>
          <button onClick={hideAll} className="text-[#555] hover:text-white text-xs transition-colors">None</button>
          <button onClick={onClose} className="text-[#444] hover:text-white transition-colors text-lg leading-none ml-1">×</button>
        </div>
      </div>

      <div className="overflow-y-auto flex-1 space-y-1">
        {presentClasses.map(cls => {
          const label = LAS_CLASSES[cls] ?? `Class ${cls}`
          const color = CLASS_COLORS[cls] ?? '#888888'
          const count = counts[cls] ?? 0
          const pct = total > 0 ? ((count / total) * 100).toFixed(1) : '0'
          const visible = visibleClasses.has(cls)

          return (
            <button
              key={cls}
              onClick={() => toggle(cls)}
              className={`w-full flex items-center gap-3 p-2.5 rounded-lg transition-all border text-left ${
                visible
                  ? 'border-[#222] bg-[#0a0a0a]'
                  : 'border-transparent bg-transparent opacity-40'
              }`}
            >
              {/* Colour dot */}
              <div
                className="w-3 h-3 rounded-full flex-shrink-0"
                style={{ backgroundColor: color }}
              />
              {/* Label */}
              <div className="flex-1 min-w-0">
                <p className="text-white text-xs truncate">{label}</p>
                <div className="flex items-center gap-2 mt-0.5">
                  {/* Mini bar */}
                  <div className="flex-1 h-0.5 bg-[#1a1a1a] rounded-full overflow-hidden">
                    <div
                      className="h-full rounded-full"
                      style={{ width: `${pct}%`, backgroundColor: color }}
                    />
                  </div>
                  <span className="text-[#444] text-xs tabular-nums flex-shrink-0">{pct}%</span>
                </div>
              </div>
              {/* Toggle indicator */}
              <div className={`w-4 h-4 rounded border flex items-center justify-center flex-shrink-0 transition-colors ${
                visible ? 'border-white bg-white' : 'border-[#333] bg-transparent'
              }`}>
                {visible && <span className="text-black text-xs leading-none">✓</span>}
              </div>
            </button>
          )
        })}
      </div>

      <div className="mt-3 pt-3 border-t border-[#111] flex-shrink-0">
        <p className="text-[#333] text-xs text-center">
          {visibleClasses.size}/{presentClasses.length} classes visible
        </p>
      </div>
    </div>
  )
}
