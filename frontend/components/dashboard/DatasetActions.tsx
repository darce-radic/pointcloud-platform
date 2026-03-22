'use client'

import { useState } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

interface DatasetActionsProps {
  datasetId: string
  datasetStatus: string
  actionType: 'bim' | 'road-assets'
}

const ACTION_CONFIG = {
  bim: {
    endpoint: (id: string) => `/api/v1/datasets/${id}/bim-extraction`,
    label: 'Run BIM Extraction',
    runningLabel: 'Queuing...',
    description: 'Generates IFC + DXF floor plan',
  },
  'road-assets': {
    endpoint: (id: string) => `/api/v1/datasets/${id}/road-assets`,
    label: 'Detect Road Assets',
    runningLabel: 'Queuing...',
    description: 'Detects markings, signs, drains',
  },
}

export default function DatasetActions({ datasetId, datasetStatus, actionType }: DatasetActionsProps) {
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [queued, setQueued] = useState(false)
  const router = useRouter()
  const supabase = createClient()
  const config = ACTION_CONFIG[actionType]
  const isReady = datasetStatus === 'ready' || datasetStatus === 'completed'

  const handleTrigger = async () => {
    setLoading(true)
    setError(null)
    try {
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) throw new Error('Not authenticated')

      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
      const res = await fetch(`${apiUrl}${config.endpoint(datasetId)}`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
          'Content-Type': 'application/json',
        },
      })

      if (!res.ok) {
        const body = await res.json().catch(() => ({}))
        throw new Error(body.detail ?? `Request failed (${res.status})`)
      }

      setQueued(true)
      // Refresh the page after a short delay to show the new job
      setTimeout(() => router.refresh(), 1500)
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Failed to queue job')
    } finally {
      setLoading(false)
    }
  }

  if (queued) {
    return (
      <div className="text-yellow-400 text-xs">
        ✓ Job queued — the worker will pick it up shortly. Refresh to see progress.
      </div>
    )
  }

  return (
    <div>
      <button
        onClick={handleTrigger}
        disabled={loading || !isReady}
        className={`w-full px-4 py-2 text-sm font-medium rounded-lg transition-colors ${
          isReady
            ? 'bg-white text-black hover:bg-[#e0e0e0] cursor-pointer'
            : 'bg-[#111] text-[#444] cursor-not-allowed'
        } ${loading ? 'opacity-60' : ''}`}
      >
        {loading ? (
          <span className="flex items-center justify-center gap-2">
            <span className="w-3 h-3 border border-black border-t-transparent rounded-full animate-spin" />
            {config.runningLabel}
          </span>
        ) : (
          config.label
        )}
      </button>
      {!isReady && (
        <p className="text-[#444] text-xs mt-2">
          Dataset must be in &apos;ready&apos; state (current: {datasetStatus})
        </p>
      )}
      {error && <p className="text-red-400 text-xs mt-2">{error}</p>}
      <p className="text-[#333] text-xs mt-2">{config.description}</p>
    </div>
  )
}
