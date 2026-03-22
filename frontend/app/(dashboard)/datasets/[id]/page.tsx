import { createClient } from '@/lib/supabase/server'
import Link from 'next/link'
import { notFound } from 'next/navigation'
import DatasetActions from '@/components/dashboard/DatasetActions'

interface PageProps {
  params: Promise<{ id: string }>
}

export default async function DatasetDetailPage({ params }: PageProps) {
  const { id } = await params
  const supabase = await createClient()

  const { data: dataset, error } = await supabase
    .from('datasets')
    .select(`
      id, name, format, status, point_count, file_size_bytes, created_at,
      copc_url, ifc_url, dxf_url, segments_url, road_assets_url,
      bim_stats, road_asset_stats,
      processing_jobs (
        id, job_type, status, progress_pct, error_message, created_at, completed_at
      )
    `)
    .eq('id', id)
    .order('created_at', { referencedTable: 'processing_jobs', ascending: false })
    .maybeSingle()

  if (error || !dataset) {
    notFound()
  }

  const formatBytes = (bytes: number) => {
    if (!bytes) return '—'
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    if (bytes < 1024 * 1024 * 1024) return `${(bytes / (1024 * 1024)).toFixed(1)} MB`
    return `${(bytes / (1024 * 1024 * 1024)).toFixed(2)} GB`
  }

  const formatPoints = (count: number) => {
    if (!count) return '—'
    if (count >= 1_000_000) return `${(count / 1_000_000).toFixed(1)}M`
    if (count >= 1_000) return `${(count / 1_000).toFixed(0)}K`
    return count.toString()
  }

  const jobs = Array.isArray(dataset.processing_jobs) ? dataset.processing_jobs : []
  const latestJob = jobs[0] ?? null

  const statusColour = (s: string) => {
    if (s === 'ready' || s === 'completed') return 'bg-[#0a1a0a] text-green-400'
    if (s === 'processing' || s === 'queued') return 'bg-[#111] text-yellow-400'
    if (s === 'failed') return 'bg-[#1a0000] text-red-400'
    return 'bg-[#111] text-[#555]'
  }

  return (
    <div className="p-8 max-w-5xl mx-auto">
      {/* Breadcrumb */}
      <div className="flex items-center gap-2 text-[#444] text-sm mb-6">
        <Link href="/datasets" className="hover:text-white transition-colors">Datasets</Link>
        <span>/</span>
        <span className="text-white truncate max-w-xs">{dataset.name}</span>
      </div>

      {/* Header */}
      <div className="flex items-start justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-white tracking-tight">{dataset.name}</h1>
          <div className="flex items-center gap-3 mt-2">
            <span className={`text-xs px-2 py-1 rounded-md ${statusColour(dataset.status)}`}>
              {dataset.status}
            </span>
            <span className="text-[#444] text-xs">{dataset.format?.toUpperCase() ?? '—'}</span>
            <span className="text-[#444] text-xs">{formatPoints(dataset.point_count)} pts</span>
            <span className="text-[#444] text-xs">{formatBytes(dataset.file_size_bytes)}</span>
          </div>
        </div>
        {dataset.copc_url && (
          <Link
            href={`/viewer/${dataset.id}`}
            className="inline-flex items-center gap-2 px-4 py-2 bg-white text-black text-sm font-medium rounded-lg hover:bg-[#e0e0e0] transition-colors"
          >
            Open Viewer →
          </Link>
        )}
      </div>

      {/* Processing jobs history */}
      {jobs.length > 0 && (
        <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl mb-6 overflow-hidden">
          <div className="px-6 py-4 border-b border-[#1a1a1a]">
            <h2 className="text-white text-sm font-medium">Processing Jobs</h2>
          </div>
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#111]">
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Type</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Status</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Progress</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Started</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Completed</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#111]">
              {jobs.map((job: {
                id: string
                job_type: string
                status: string
                progress_pct: number
                error_message?: string
                created_at: string
                completed_at?: string
              }) => (
                <tr key={job.id}>
                  <td className="px-6 py-3">
                    <span className="text-[#888] text-xs font-mono">{job.job_type}</span>
                  </td>
                  <td className="px-6 py-3">
                    <span className={`text-xs px-2 py-1 rounded-md ${statusColour(job.status)}`}>
                      {job.status}
                    </span>
                    {job.error_message && (
                      <p className="text-red-400 text-xs mt-1 max-w-xs truncate">{job.error_message}</p>
                    )}
                  </td>
                  <td className="px-6 py-3">
                    <div className="flex items-center gap-2">
                      <div className="w-24 h-1.5 bg-[#1a1a1a] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-white rounded-full transition-all"
                          style={{ width: `${job.progress_pct ?? 0}%` }}
                        />
                      </div>
                      <span className="text-[#555] text-xs">{job.progress_pct ?? 0}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-3">
                    <span className="text-[#555] text-xs">
                      {new Date(job.created_at).toLocaleString()}
                    </span>
                  </td>
                  <td className="px-6 py-3">
                    <span className="text-[#555] text-xs">
                      {job.completed_at ? new Date(job.completed_at).toLocaleString() : '—'}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {/* Analysis tools */}
      <div className="grid grid-cols-1 md:grid-cols-2 gap-4 mb-6">
        {/* BIM Extraction card */}
        <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl p-6">
          <div className="flex items-start gap-3 mb-4">
            <div className="w-9 h-9 bg-[#111] rounded-lg flex items-center justify-center text-lg flex-shrink-0">
              ⬡
            </div>
            <div>
              <h3 className="text-white text-sm font-medium">BIM Extraction</h3>
              <p className="text-[#444] text-xs mt-1">
                Generate an IFC 4 model and DXF floor plan from the point cloud using
                Cloud2BIM segmentation. Detects walls, slabs, doors, windows, and rooms.
              </p>
            </div>
          </div>
          {dataset.ifc_url ? (
            <div className="space-y-2">
              <p className="text-green-400 text-xs mb-3">
                ✓ Extraction complete
                {dataset.bim_stats && (
                  <span className="text-[#555] ml-2">
                    {(dataset.bim_stats as Record<string, number>).wall_count ?? 0} walls ·{' '}
                    {(dataset.bim_stats as Record<string, number>).room_count ?? 0} rooms ·{' '}
                    {(dataset.bim_stats as Record<string, number>).opening_count ?? 0} openings
                  </span>
                )}
              </p>
              <div className="flex gap-2">
                <a
                  href={dataset.ifc_url}
                  download
                  className="flex-1 text-center px-3 py-2 bg-[#111] text-white text-xs rounded-lg hover:bg-[#1a1a1a] transition-colors"
                >
                  ↓ Download IFC
                </a>
                <a
                  href={dataset.dxf_url ?? '#'}
                  download
                  className="flex-1 text-center px-3 py-2 bg-[#111] text-white text-xs rounded-lg hover:bg-[#1a1a1a] transition-colors"
                >
                  ↓ Download DXF
                </a>
              </div>
            </div>
          ) : (
            <DatasetActions
              datasetId={dataset.id}
              datasetStatus={dataset.status}
              actionType="bim"
            />
          )}
        </div>

        {/* Road Asset Detection card */}
        <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl p-6">
          <div className="flex items-start gap-3 mb-4">
            <div className="w-9 h-9 bg-[#111] rounded-lg flex items-center justify-center text-lg flex-shrink-0">
              ⬡
            </div>
            <div>
              <h3 className="text-white text-sm font-medium">Road Asset Detection</h3>
              <p className="text-[#444] text-xs mt-1">
                Automatically detect and classify road infrastructure: lane markings,
                traffic signs, drains, and manholes. Outputs a GeoJSON FeatureCollection.
              </p>
            </div>
          </div>
          {dataset.road_assets_url ? (
            <div className="space-y-2">
              <p className="text-green-400 text-xs mb-3">
                ✓ Detection complete
                {dataset.road_asset_stats && (
                  <span className="text-[#555] ml-2">
                    {(dataset.road_asset_stats as Record<string, number>).total_features ?? 0} features detected
                  </span>
                )}
              </p>
              <a
                href={dataset.road_assets_url}
                download
                className="block text-center px-3 py-2 bg-[#111] text-white text-xs rounded-lg hover:bg-[#1a1a1a] transition-colors"
              >
                ↓ Download GeoJSON
              </a>
            </div>
          ) : (
            <DatasetActions
              datasetId={dataset.id}
              datasetStatus={dataset.status}
              actionType="road-assets"
            />
          )}
        </div>
      </div>

      {/* Metadata */}
      <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl p-6">
        <h2 className="text-white text-sm font-medium mb-4">Metadata</h2>
        <dl className="grid grid-cols-2 gap-x-8 gap-y-3">
          <div>
            <dt className="text-[#444] text-xs">Dataset ID</dt>
            <dd className="text-[#888] text-xs font-mono mt-0.5">{dataset.id}</dd>
          </div>
          <div>
            <dt className="text-[#444] text-xs">Created</dt>
            <dd className="text-[#888] text-xs mt-0.5">{new Date(dataset.created_at).toLocaleString()}</dd>
          </div>
          <div>
            <dt className="text-[#444] text-xs">Format</dt>
            <dd className="text-[#888] text-xs mt-0.5">{dataset.format?.toUpperCase() ?? '—'}</dd>
          </div>
          <div>
            <dt className="text-[#444] text-xs">Point Count</dt>
            <dd className="text-[#888] text-xs mt-0.5">{formatPoints(dataset.point_count)}</dd>
          </div>
          <div>
            <dt className="text-[#444] text-xs">File Size</dt>
            <dd className="text-[#888] text-xs mt-0.5">{formatBytes(dataset.file_size_bytes)}</dd>
          </div>
          <div>
            <dt className="text-[#444] text-xs">Status</dt>
            <dd className="mt-0.5">
              <span className={`text-xs px-2 py-0.5 rounded ${statusColour(dataset.status)}`}>
                {dataset.status}
              </span>
            </dd>
          </div>
        </dl>
      </div>
    </div>
  )
}
