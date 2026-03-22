'use client'

import { useEffect, useRef, useState, useCallback } from 'react'
import { createClient } from '@/lib/supabase/client'
import AiChatPanel from '@/components/ai-chat/AiChatPanel'
import ViewerToolbar from '@/components/viewer/ViewerToolbar'
import JobProgressOverlay from '@/components/viewer/JobProgressOverlay'

interface Dataset {
  id: string
  name: string
  copcUrl: string | null
  status: string
  pointCount: number | null
  crsEpsg: number | null
  boundingBox: unknown
}

interface WorkflowTool {
  id: string
  name: string
  description: string
  icon: string
  required_inputs: Record<string, unknown>
  n8n_workflow_id: string
}

interface ViewerClientProps {
  dataset: Dataset
  workflowTools: WorkflowTool[]
}

export default function ViewerClient({ dataset, workflowTools }: ViewerClientProps) {
  const viewerRef = useRef<HTMLDivElement>(null)
  const [potreeLoaded, setPotreeLoaded] = useState(false)
  const [chatOpen, setChatOpen] = useState(false)
  const [activeJob, setActiveJob] = useState<string | null>(null)
  const [viewerReady, setViewerReady] = useState(false)
  const supabase = createClient()

  // Load Potree from CDN
  useEffect(() => {
    if (typeof window === 'undefined') return

    const loadPotree = async () => {
      // Load Potree CSS
      const link = document.createElement('link')
      link.rel = 'stylesheet'
      link.href = 'https://cdn.jsdelivr.net/npm/potree-core@2.0.0/src/viewer/potree.css'
      document.head.appendChild(link)

      // Load Three.js first
      if (!(window as unknown as Record<string, unknown>).THREE) {
        await loadScript('https://cdn.jsdelivr.net/npm/three@0.137.0/build/three.min.js')
      }

      // Load Potree
      if (!(window as unknown as Record<string, unknown>).Potree) {
        await loadScript('https://cdn.jsdelivr.net/npm/potree-core@2.0.0/build/potree.js')
      }

      setPotreeLoaded(true)
    }

    loadPotree()
  }, [])

  // Initialise the viewer once Potree is loaded
  useEffect(() => {
    if (!potreeLoaded || !viewerRef.current || !dataset.copcUrl) return

    const w = window as unknown as Record<string, unknown>
    const Potree = w.Potree as {
      Viewer: new (el: HTMLElement) => {
        setEDLEnabled: (v: boolean) => void
        setBackground: (v: string) => void
        loadPointCloud: (url: string, name: string, cb: (e: { pointcloud: unknown }) => void) => void
        scene: { addPointCloud: (pc: unknown) => void; view: { position: { set: (x: number, y: number, z: number) => void }; lookAt: { set: (x: number, y: number, z: number) => void } } }
      }
    }

    if (!Potree) return

    const viewer = new Potree.Viewer(viewerRef.current)
    viewer.setEDLEnabled(true)
    viewer.setBackground('black')

    Potree.loadPointCloud(dataset.copcUrl, dataset.name, (e) => {
      viewer.scene.addPointCloud(e.pointcloud)
      setViewerReady(true)
    })

    return () => {
      // Cleanup handled by React unmount
    }
  }, [potreeLoaded, dataset.copcUrl, dataset.name])

  // Subscribe to job updates via Supabase Realtime
  useEffect(() => {
    if (!activeJob) return

    const channel = supabase
      .channel(`job-${activeJob}`)
      .on(
        'postgres_changes',
        { event: 'UPDATE', schema: 'public', table: 'processing_jobs', filter: `id=eq.${activeJob}` },
        (payload) => {
          const job = payload.new as { status: string; id: string }
          if (job.status === 'completed' || job.status === 'failed') {
            setActiveJob(null)
          }
        }
      )
      .subscribe()

    return () => { supabase.removeChannel(channel) }
  }, [activeJob, supabase])

  const handleRunTool = useCallback(async (toolId: string, inputs: Record<string, unknown>) => {
    const { data: { session } } = await supabase.auth.getSession()
    if (!session) return

    const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
    const res = await fetch(`${apiUrl}/api/v1/workflow-tools/${toolId}/run`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({ dataset_id: dataset.id, inputs }),
    })

    if (res.ok) {
      const { job_id } = await res.json()
      setActiveJob(job_id)
    }
  }, [dataset.id, supabase])

  return (
    <div className="relative w-full h-screen bg-black overflow-hidden">
      {/* Potree viewer canvas */}
      <div ref={viewerRef} className="absolute inset-0" />

      {/* Loading state */}
      {!viewerReady && (
        <div className="absolute inset-0 flex items-center justify-center bg-black z-10">
          <div className="text-center">
            <div className="w-8 h-8 border border-white border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-[#555] text-sm">
              {!dataset.copcUrl ? 'Dataset is still processing...' : 'Loading point cloud...'}
            </p>
          </div>
        </div>
      )}

      {/* Top bar */}
      <div className="absolute top-0 left-0 right-0 h-12 flex items-center justify-between px-4 bg-gradient-to-b from-black/80 to-transparent z-20 pointer-events-none">
        <div className="flex items-center gap-3 pointer-events-auto">
          <a href="/datasets" className="text-[#555] hover:text-white transition-colors text-sm">←</a>
          <span className="text-white text-sm font-medium">{dataset.name}</span>
          {dataset.pointCount && (
            <span className="text-[#444] text-xs">
              {(dataset.pointCount / 1_000_000).toFixed(1)}M pts
            </span>
          )}
        </div>
        <div className="flex items-center gap-2 pointer-events-auto">
          <button
            onClick={() => setChatOpen(v => !v)}
            className={`px-3 py-1.5 rounded-lg text-xs font-medium transition-colors ${chatOpen ? 'bg-white text-black' : 'bg-[#111] text-[#888] hover:text-white border border-[#222]'}`}
          >
            AI Assistant
          </button>
        </div>
      </div>

      {/* Workflow toolbar */}
      <ViewerToolbar
        tools={workflowTools}
        onRunTool={handleRunTool}
        activeJobId={activeJob}
      />

      {/* AI Chat panel */}
      {chatOpen && (
        <AiChatPanel
          datasetId={dataset.id}
          datasetName={dataset.name}
          onClose={() => setChatOpen(false)}
          onJobStarted={(jobId) => setActiveJob(jobId)}
        />
      )}

      {/* Job progress overlay */}
      {activeJob && (
        <JobProgressOverlay
          jobId={activeJob}
          onComplete={() => setActiveJob(null)}
        />
      )}
    </div>
  )
}

function loadScript(src: string): Promise<void> {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script')
    script.src = src
    script.onload = () => resolve()
    script.onerror = reject
    document.head.appendChild(script)
  })
}
