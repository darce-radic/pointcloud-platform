'use client'

import type { RenderMode } from './ViewerClient'

interface RenderModePanelProps {
  mode: RenderMode
  onChange: (mode: RenderMode) => void
  onClose: () => void
}

const MODES: { id: RenderMode; label: string; description: string; gradient: string }[] = [
  {
    id: 'rgb',
    label: 'True Colour',
    description: 'RGB values captured by the scanner',
    gradient: 'from-red-500 via-green-500 to-blue-500',
  },
  {
    id: 'intensity',
    label: 'Intensity',
    description: 'Laser return intensity (greyscale)',
    gradient: 'from-black to-white',
  },
  {
    id: 'height',
    label: 'Elevation',
    description: 'Height above lowest point (blue → red)',
    gradient: 'from-blue-600 via-green-500 via-yellow-400 to-red-600',
  },
]

export default function RenderModePanel({ mode, onChange, onClose }: RenderModePanelProps) {
  return (
    <div className="absolute left-20 top-1/2 -translate-y-1/2 z-20 w-64 bg-black/90 border border-[#222] rounded-xl p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-4">
        <h3 className="text-white text-sm font-medium">Render Mode</h3>
        <button onClick={onClose} className="text-[#444] hover:text-white transition-colors text-lg leading-none">×</button>
      </div>

      <div className="space-y-2">
        {MODES.map(m => (
          <button
            key={m.id}
            onClick={() => onChange(m.id)}
            className={`w-full text-left p-3 rounded-lg border transition-all ${
              mode === m.id
                ? 'border-white bg-[#111]'
                : 'border-[#1a1a1a] hover:border-[#333] bg-transparent'
            }`}
          >
            <div className="flex items-center gap-3">
              {/* Colour swatch */}
              <div className={`w-8 h-5 rounded bg-gradient-to-r ${m.gradient} flex-shrink-0`} />
              <div>
                <p className="text-white text-xs font-medium">{m.label}</p>
                <p className="text-[#555] text-xs mt-0.5">{m.description}</p>
              </div>
              {mode === m.id && (
                <div className="ml-auto w-1.5 h-1.5 rounded-full bg-white flex-shrink-0" />
              )}
            </div>
          </button>
        ))}
      </div>
    </div>
  )
}
