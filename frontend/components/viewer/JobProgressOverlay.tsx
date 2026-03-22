'use client'

import { useEffect, useState } from 'react'
import { createClient } from '@/lib/supabase/client'

interface JobProgressOverlayProps {
  jobId: string
  onComplete: () => void
}

interface JobState {
  status: string
  progress: number
  job_type: string
  error_message: string | null
}

export default function JobProgressOverlay({ jobId, onComplete }: JobProgressOverlayProps) {
  const [job, setJob] = useState<JobState | null>(null)
  const supabase = createClient()

  useEffect(() => {
    // Fetch initial state
    supabase
      .from('processing_jobs')
      .select('status, progress, job_type, error_message')
      .eq('id', jobId)
      .single()
      .then(({ data }) => { if (data) setJob(data as JobState) })

    // Subscribe to real-time updates
    const channel = supabase
      .channel(`job-overlay-${jobId}`)
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'processing_jobs', filter: `id=eq.${jobId}` },
        (payload) => {
          const updated = payload.new as JobState
          setJob(updated)
          if (updated.status === 'completed' || updated.status === 'failed') {
            setTimeout(onComplete, 2000)
          }
        }
      )
      .subscribe()

    return () => { supabase.removeChannel(channel) }
  }, [jobId, supabase, onComplete])

  if (!job) return null

  const jobTypeLabels: Record<string, string> = {
    tiling: 'COPC Tiling',
    georeferencing: 'Georeferencing',
    bim_extraction: 'BIM Extraction',
    road_assets: 'Road Asset Detection',
    dtm_generation: 'DTM Generation',
    segmentation: 'AI Segmentation',
  }

  return (
    <div className="absolute bottom-6 left-1/2 -translate-x-1/2 z-30 w-80 bg-black/90 border border-[#222] rounded-xl p-4 backdrop-blur-sm">
      <div className="flex items-center justify-between mb-3">
        <span className="text-white text-sm font-medium">
          {jobTypeLabels[job.job_type] ?? job.job_type}
        </span>
        <span className={`text-xs px-2 py-0.5 rounded-md ${
          job.status === 'completed' ? 'bg-[#111] text-[#888]' :
          job.status === 'running' ? 'bg-[#111] text-white' :
          job.status === 'failed' ? 'bg-[#1a0000] text-red-400' :
          'bg-[#111] text-[#555]'
        }`}>
          {job.status}
        </span>
      </div>

      <div className="w-full h-1 bg-[#1a1a1a] rounded-full overflow-hidden mb-2">
        <div
          className={`h-full rounded-full transition-all duration-500 ${job.status === 'failed' ? 'bg-red-800' : 'bg-white'}`}
          style={{ width: `${job.progress ?? 0}%` }}
        />
      </div>

      <div className="flex items-center justify-between">
        <span className="text-[#555] text-xs">{job.progress ?? 0}% complete</span>
        {job.status === 'running' && (
          <span className="w-3 h-3 border border-white border-t-transparent rounded-full animate-spin" />
        )}
      </div>

      {job.error_message && (
        <p className="text-red-400 text-xs mt-2 border-t border-[#1a1a1a] pt-2">{job.error_message}</p>
      )}
    </div>
  )
}
