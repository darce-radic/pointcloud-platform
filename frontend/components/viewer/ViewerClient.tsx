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
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  required_inputs: Record<string, any>
  n8n_workflow_id: string
}

interface ViewerClientProps {
  dataset: Dataset
  workflowTools: WorkflowTool[]
}

export default function ViewerClient({ dataset, workflowTools }: ViewerClientProps) {
  const canvasRef = useRef<HTMLCanvasElement>(null)
  const containerRef = useRef<HTMLDivElement>(null)
  const [viewerReady, setViewerReady] = useState(false)
  const [loadingStatus, setLoadingStatus] = useState('Initialising viewer...')
  const [chatOpen, setChatOpen] = useState(false)
  const [activeJob, setActiveJob] = useState<string | null>(null)
  const supabase = createClient()

  // Load and render the COPC point cloud using Three.js + copc library
  useEffect(() => {
    if (typeof window === 'undefined') return
    if (!canvasRef.current || !containerRef.current) return
    if (!dataset.copcUrl) {
      setLoadingStatus('Dataset is still processing...')
      return
    }

    let animationId: number
    let destroyed = false

    const init = async () => {
      try {
        setLoadingStatus('Loading Three.js...')

        // Dynamically import Three.js (installed as npm package)
        const THREE = await import('three')

        if (destroyed) return

        setLoadingStatus('Reading COPC header...')

        // Dynamically import copc library
        const { Copc } = await import('copc')

        if (destroyed) return

        // Load COPC file metadata
        const copc = await Copc.create(dataset.copcUrl!)
        const { header, info } = copc

        if (destroyed) return

        setLoadingStatus(`Loading ${(header.pointCount / 1_000_000).toFixed(1)}M points...`)

        // Read the root node (LOD 0) for initial display
        const nodes = await Copc.loadHierarchyPage(dataset.copcUrl!, info.rootHierarchyPage)
        const rootKey = '0-0-0-0'
        const rootNode = nodes.nodes[rootKey]

        let positions: Float32Array
        let colors: Float32Array | null = null

        if (rootNode) {
          const view = await Copc.loadPointDataView(dataset.copcUrl!, copc, rootNode)
          const count = view.pointCount

        const getX = view.getter('X')
        const getY = view.getter('Y')
        const getZ = view.getter('Z')

        // Check if colour dimensions are available in this file
        const hasColor = 'Red' in view.dimensions && 'Green' in view.dimensions && 'Blue' in view.dimensions
        const getRed = hasColor ? view.getter('Red') : null
        const getGreen = hasColor ? view.getter('Green') : null
        const getBlue = hasColor ? view.getter('Blue') : null

        positions = new Float32Array(count * 3)
        if (hasColor) {
          colors = new Float32Array(count * 3)
        }

          // Compute centroid for centering
          let cx = 0, cy = 0, cz = 0
          for (let i = 0; i < count; i++) {
            cx += getX(i) as number
            cy += getY(i) as number
            cz += getZ(i) as number
          }
          cx /= count; cy /= count; cz /= count

          for (let i = 0; i < count; i++) {
            positions[i * 3] = (getX(i) as number) - cx
            positions[i * 3 + 1] = (getY(i) as number) - cy
            positions[i * 3 + 2] = (getZ(i) as number) - cz

            if (colors && getRed && getGreen && getBlue) {
              // COPC stores 16-bit colours, normalise to 0-1
              colors[i * 3] = (getRed(i) as number) / 65535
              colors[i * 3 + 1] = (getGreen(i) as number) / 65535
              colors[i * 3 + 2] = (getBlue(i) as number) / 65535
            } else if (colors) {
              colors[i * 3] = 0.5
              colors[i * 3 + 1] = 0.7
              colors[i * 3 + 2] = 1.0
            }
          }
        } else {
          // Fallback: empty geometry
          positions = new Float32Array(0)
        }

        if (destroyed) return

        setLoadingStatus('Rendering...')

        // --- Three.js scene setup ---
        const canvas = canvasRef.current!
        const container = containerRef.current!
        const width = container.clientWidth
        const height = container.clientHeight

        const renderer = new THREE.WebGLRenderer({ canvas, antialias: false })
        renderer.setSize(width, height)
        renderer.setPixelRatio(Math.min(window.devicePixelRatio, 2))
        renderer.setClearColor(0x000000)

        const scene = new THREE.Scene()

        const camera = new THREE.PerspectiveCamera(60, width / height, 0.1, 100000)
        const bbox = header.min && header.max
          ? Math.max(
              header.max[0] - header.min[0],
              header.max[1] - header.min[1],
              header.max[2] - header.min[2]
            )
          : 1000
        camera.position.set(0, -bbox * 0.8, bbox * 0.5)
        camera.lookAt(0, 0, 0)

        // Point cloud geometry
        const geometry = new THREE.BufferGeometry()
        geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3))
        if (colors) {
          geometry.setAttribute('color', new THREE.BufferAttribute(colors, 3))
        }

        const material = new THREE.PointsMaterial({
          size: 2,
          sizeAttenuation: false,
          vertexColors: !!colors,
          color: colors ? 0xffffff : 0x88aaff,
        })

        const pointCloud = new THREE.Points(geometry, material)
        scene.add(pointCloud)

        // Simple orbit controls (mouse drag to rotate)
        let isDragging = false
        let prevMouse = { x: 0, y: 0 }
        let spherical = { theta: 0, phi: Math.PI / 3, radius: bbox * 1.2 }

        const updateCamera = () => {
          camera.position.set(
            spherical.radius * Math.sin(spherical.phi) * Math.sin(spherical.theta),
            -spherical.radius * Math.sin(spherical.phi) * Math.cos(spherical.theta),
            spherical.radius * Math.cos(spherical.phi)
          )
          camera.lookAt(0, 0, 0)
        }
        updateCamera()

        canvas.addEventListener('mousedown', (e) => { isDragging = true; prevMouse = { x: e.clientX, y: e.clientY } })
        canvas.addEventListener('mouseup', () => { isDragging = false })
        canvas.addEventListener('mousemove', (e) => {
          if (!isDragging) return
          const dx = (e.clientX - prevMouse.x) * 0.005
          const dy = (e.clientY - prevMouse.y) * 0.005
          spherical.theta -= dx
          spherical.phi = Math.max(0.1, Math.min(Math.PI - 0.1, spherical.phi + dy))
          prevMouse = { x: e.clientX, y: e.clientY }
          updateCamera()
        })
        canvas.addEventListener('wheel', (e) => {
          spherical.radius *= e.deltaY > 0 ? 1.1 : 0.9
          spherical.radius = Math.max(1, spherical.radius)
          updateCamera()
        }, { passive: true })

        // Handle resize
        const onResize = () => {
          const w = container.clientWidth
          const h = container.clientHeight
          renderer.setSize(w, h)
          camera.aspect = w / h
          camera.updateProjectionMatrix()
        }
        window.addEventListener('resize', onResize)

        // Render loop
        const animate = () => {
          if (destroyed) return
          animationId = requestAnimationFrame(animate)
          renderer.render(scene, camera)
        }
        animate()

        setViewerReady(true)

        return () => {
          window.removeEventListener('resize', onResize)
          renderer.dispose()
          geometry.dispose()
          material.dispose()
        }
      } catch (err) {
        console.error('Viewer error:', err)
        setLoadingStatus('Failed to load point cloud. Please try again.')
      }
    }

    init()

    return () => {
      destroyed = true
      if (animationId) cancelAnimationFrame(animationId)
    }
  }, [dataset.copcUrl, dataset.name])

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
    <div ref={containerRef} className="relative w-full h-screen bg-black overflow-hidden">
      {/* Three.js canvas */}
      <canvas ref={canvasRef} className="absolute inset-0 w-full h-full" />

      {/* Loading overlay */}
      {!viewerReady && (
        <div className="absolute inset-0 flex items-center justify-center bg-black z-10">
          <div className="text-center">
            <div className="w-8 h-8 border border-white border-t-transparent rounded-full animate-spin mx-auto mb-4" />
            <p className="text-[#555] text-sm">{loadingStatus}</p>
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

      {/* Controls hint */}
      {viewerReady && (
        <div className="absolute bottom-4 left-4 z-20 text-[#333] text-xs space-y-0.5">
          <p>Drag to rotate · Scroll to zoom</p>
        </div>
      )}

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
