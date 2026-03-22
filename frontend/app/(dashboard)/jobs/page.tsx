import { createClient } from '@/lib/supabase/server'

export default async function JobsPage() {
  const supabase = await createClient()

  const { data: jobs, error } = await supabase
    .from('processing_jobs')
    .select(`
      id, job_type, status, progress, error_message, created_at, completed_at,
      datasets(name)
    `)
    .order('created_at', { ascending: false })
    .limit(50)

  if (error) console.error('Error fetching jobs:', error)

  const jobTypeLabels: Record<string, string> = {
    tiling: 'COPC Tiling',
    georeferencing: 'Georeferencing',
    bim_extraction: 'BIM Extraction',
    road_assets: 'Road Assets',
    dtm_generation: 'DTM Generation',
    segmentation: 'AI Segmentation',
  }

  const durationStr = (job: { created_at: string; completed_at?: string | null }) => {
    if (!job.completed_at) return '—'
    const ms = new Date(job.completed_at).getTime() - new Date(job.created_at).getTime()
    const s = Math.round(ms / 1000)
    if (s < 60) return `${s}s`
    if (s < 3600) return `${Math.floor(s / 60)}m ${s % 60}s`
    return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`
  }

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white tracking-tight">Jobs</h1>
        <p className="text-[#555] text-sm mt-1">Processing history for your datasets</p>
      </div>

      {!jobs || jobs.length === 0 ? (
        <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl p-16 text-center">
          <p className="text-[#444] text-sm">No jobs yet. Upload a dataset to start processing.</p>
        </div>
      ) : (
        <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#1a1a1a]">
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Job</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Type</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Dataset</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Progress</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Status</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Duration</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Started</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-[#111]">
              {jobs.map(job => (
                <tr key={job.id} className="hover:bg-[#111] transition-colors">
                  <td className="px-6 py-4">
                    <span className="text-[#555] text-xs font-mono">{job.id.slice(0, 8)}...</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#888] text-sm">{jobTypeLabels[job.job_type] ?? job.job_type}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#666] text-sm">
                      {(job.datasets as { name: string } | null)?.name ?? '—'}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <div className="flex items-center gap-2">
                      <div className="w-20 h-1 bg-[#1a1a1a] rounded-full overflow-hidden">
                        <div
                          className="h-full bg-white rounded-full transition-all"
                          style={{ width: `${job.progress ?? 0}%` }}
                        />
                      </div>
                      <span className="text-[#555] text-xs">{job.progress ?? 0}%</span>
                    </div>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`text-xs px-2 py-1 rounded-md ${
                      job.status === 'completed' ? 'bg-[#111] text-[#888]' :
                      job.status === 'running' ? 'bg-[#111] text-white' :
                      job.status === 'failed' ? 'bg-[#1a0000] text-red-400' :
                      'bg-[#111] text-[#555]'
                    }`}>
                      {job.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#555] text-xs">{durationStr(job)}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#555] text-xs">
                      {new Date(job.created_at).toLocaleString()}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  )
}
