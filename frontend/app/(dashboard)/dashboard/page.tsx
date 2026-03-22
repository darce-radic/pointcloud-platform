import { createClient } from '@/lib/supabase/server'

export default async function DashboardPage() {
  const supabase = await createClient()

  // Fetch real stats from Supabase
  const [datasetsResult, jobsResult, projectsResult] = await Promise.all([
    supabase.from('datasets').select('id, status, created_at', { count: 'exact' }),
    supabase.from('processing_jobs').select('id, status, created_at', { count: 'exact' }).order('created_at', { ascending: false }).limit(5),
    supabase.from('projects').select('id, name, created_at', { count: 'exact' }),
  ])

  const datasets = datasetsResult.data ?? []
  const recentJobs = jobsResult.data ?? []
  const totalDatasets = datasetsResult.count ?? 0
  const totalProjects = projectsResult.count ?? 0
  const runningJobs = recentJobs.filter(j => j.status === 'running').length

  const stats = [
    { label: 'Total Datasets', value: totalDatasets },
    { label: 'Projects', value: totalProjects },
    { label: 'Running Jobs', value: runningJobs },
  ]

  return (
    <div className="p-8">
      <div className="mb-8">
        <h1 className="text-2xl font-semibold text-white tracking-tight">Overview</h1>
        <p className="text-[#555] text-sm mt-1">Your point cloud workspace</p>
      </div>

      {/* Stats */}
      <div className="grid grid-cols-3 gap-4 mb-8">
        {stats.map(stat => (
          <div key={stat.label} className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl p-6">
            <p className="text-[#555] text-xs mb-2">{stat.label}</p>
            <p className="text-white text-3xl font-semibold">{stat.value}</p>
          </div>
        ))}
      </div>

      {/* Recent Jobs */}
      <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl">
        <div className="px-6 py-4 border-b border-[#1a1a1a] flex items-center justify-between">
          <h2 className="text-white text-sm font-medium">Recent Jobs</h2>
          <a href="/jobs" className="text-[#555] text-xs hover:text-white transition-colors">View all →</a>
        </div>
        {recentJobs.length === 0 ? (
          <div className="px-6 py-12 text-center">
            <p className="text-[#444] text-sm">No jobs yet. Upload a dataset to get started.</p>
            <a
              href="/datasets"
              className="inline-block mt-4 px-4 py-2 bg-white text-black text-xs font-medium rounded-lg hover:bg-[#e0e0e0] transition-colors"
            >
              Upload Dataset
            </a>
          </div>
        ) : (
          <div className="divide-y divide-[#111]">
            {recentJobs.map(job => (
              <div key={job.id} className="px-6 py-4 flex items-center justify-between">
                <div className="flex items-center gap-3">
                  <div className={`w-2 h-2 rounded-full ${
                    job.status === 'completed' ? 'bg-white' :
                    job.status === 'running' ? 'bg-[#888] animate-pulse' :
                    job.status === 'failed' ? 'bg-[#555]' : 'bg-[#333]'
                  }`} />
                  <span className="text-[#888] text-sm font-mono">{job.id.slice(0, 8)}...</span>
                </div>
                <span className={`text-xs px-2 py-1 rounded-md ${
                  job.status === 'completed' ? 'bg-[#111] text-[#888]' :
                  job.status === 'running' ? 'bg-[#111] text-white' :
                  job.status === 'failed' ? 'bg-[#1a0000] text-red-400' : 'bg-[#111] text-[#555]'
                }`}>
                  {job.status}
                </span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  )
}
