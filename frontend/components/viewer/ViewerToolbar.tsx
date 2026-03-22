'use client'

import { useState } from 'react'

interface WorkflowTool {
  id: string
  name: string
  description: string
  icon: string
  required_inputs: Record<string, { type: string; label: string; default?: unknown }>
  n8n_workflow_id: string
}

interface ViewerToolbarProps {
  tools: WorkflowTool[]
  onRunTool: (toolId: string, inputs: Record<string, unknown>) => Promise<void>
  activeJobId: string | null
}

export default function ViewerToolbar({ tools, onRunTool, activeJobId }: ViewerToolbarProps) {
  const [selectedTool, setSelectedTool] = useState<WorkflowTool | null>(null)
  const [inputs, setInputs] = useState<Record<string, unknown>>({})
  const [running, setRunning] = useState(false)

  const handleSelectTool = (tool: WorkflowTool) => {
    if (selectedTool?.id === tool.id) {
      setSelectedTool(null)
      setInputs({})
      return
    }
    setSelectedTool(tool)
    // Pre-fill defaults
    const defaults: Record<string, unknown> = {}
    Object.entries(tool.required_inputs ?? {}).forEach(([key, spec]) => {
      if (spec.default !== undefined) defaults[key] = spec.default
    })
    setInputs(defaults)
  }

  const handleRun = async () => {
    if (!selectedTool) return
    setRunning(true)
    try {
      await onRunTool(selectedTool.id, inputs)
      setSelectedTool(null)
      setInputs({})
    } finally {
      setRunning(false)
    }
  }

  return (
    <>
      {/* Toolbar strip on the left */}
      <div className="absolute left-4 top-1/2 -translate-y-1/2 z-20 flex flex-col gap-2">
        {tools.map(tool => (
          <button
            key={tool.id}
            onClick={() => handleSelectTool(tool)}
            disabled={!!activeJobId}
            title={tool.name}
            className={`w-10 h-10 rounded-xl flex items-center justify-center text-lg transition-all border ${
              selectedTool?.id === tool.id
                ? 'bg-white text-black border-white'
                : 'bg-black/70 text-[#888] border-[#222] hover:border-[#444] hover:text-white'
            } ${activeJobId ? 'opacity-40 cursor-not-allowed' : ''}`}
          >
            {tool.icon}
          </button>
        ))}
      </div>

      {/* Tool detail panel */}
      {selectedTool && (
        <div className="absolute left-20 top-1/2 -translate-y-1/2 z-20 w-72 bg-black/90 border border-[#222] rounded-xl p-5 backdrop-blur-sm">
          <div className="flex items-start justify-between mb-3">
            <div>
              <h3 className="text-white text-sm font-medium">{selectedTool.name}</h3>
              <p className="text-[#555] text-xs mt-0.5">{selectedTool.description}</p>
            </div>
            <button
              onClick={() => { setSelectedTool(null); setInputs({}) }}
              className="text-[#444] hover:text-white transition-colors text-lg leading-none ml-2"
            >
              ×
            </button>
          </div>

          {/* Dynamic inputs */}
          {Object.keys(selectedTool.required_inputs ?? {}).length > 0 && (
            <div className="space-y-3 mb-4">
              {Object.entries(selectedTool.required_inputs).map(([key, spec]) => (
                <div key={key}>
                  <label className="block text-[#666] text-xs mb-1">{spec.label}</label>
                  {spec.type === 'number' ? (
                    <input
                      type="number"
                      value={inputs[key] as number ?? ''}
                      onChange={e => setInputs(v => ({ ...v, [key]: parseFloat(e.target.value) }))}
                      className="w-full bg-[#111] border border-[#222] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-[#444]"
                    />
                  ) : spec.type === 'select' ? (
                    <select
                      value={inputs[key] as string ?? ''}
                      onChange={e => setInputs(v => ({ ...v, [key]: e.target.value }))}
                      className="w-full bg-[#111] border border-[#222] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-[#444]"
                    >
                      {((spec as { options?: string[] }).options ?? []).map((opt: string) => (
                        <option key={opt} value={opt}>{opt}</option>
                      ))}
                    </select>
                  ) : (
                    <input
                      type="text"
                      value={inputs[key] as string ?? ''}
                      onChange={e => setInputs(v => ({ ...v, [key]: e.target.value }))}
                      className="w-full bg-[#111] border border-[#222] rounded-lg px-3 py-2 text-white text-sm focus:outline-none focus:border-[#444]"
                    />
                  )}
                </div>
              ))}
            </div>
          )}

          <button
            onClick={handleRun}
            disabled={running}
            className="w-full bg-white text-black text-sm font-medium py-2.5 rounded-lg hover:bg-[#e0e0e0] transition-colors disabled:opacity-50 disabled:cursor-not-allowed flex items-center justify-center gap-2"
          >
            {running ? (
              <>
                <span className="w-3.5 h-3.5 border border-black border-t-transparent rounded-full animate-spin" />
                Running...
              </>
            ) : (
              `Run ${selectedTool.name}`
            )}
          </button>
        </div>
      )}
    </>
  )
}
