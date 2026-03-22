import { createClient } from '@/lib/supabase/server'
import Link from 'next/link'
import UploadDatasetButton from '@/components/dashboard/UploadDatasetButton'

export default async function DatasetsPage() {
  const supabase = await createClient()

  const { data: datasets, error } = await supabase
    .from('datasets')
    .select('id, name, format, status, point_count, file_size_bytes, created_at, copc_url')
    .order('created_at', { ascending: false })

  if (error) {
    console.error('Error fetching datasets:', error)
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

  return (
    <div className="p-8">
      <div className="flex items-center justify-between mb-8">
        <div>
          <h1 className="text-2xl font-semibold text-white tracking-tight">Datasets</h1>
          <p className="text-[#555] text-sm mt-1">{datasets?.length ?? 0} datasets in your workspace</p>
        </div>
        <UploadDatasetButton />
      </div>

      {!datasets || datasets.length === 0 ? (
        <div className="bg-[#0a0a0a] border border-[#1a1a1a] border-dashed rounded-xl p-16 text-center">
          <div className="w-12 h-12 bg-[#111] rounded-xl flex items-center justify-center mx-auto mb-4">
            <span className="text-2xl">◈</span>
          </div>
          <h3 className="text-white text-sm font-medium mb-2">No datasets yet</h3>
          <p className="text-[#444] text-sm mb-6">Upload your first LAS, LAZ, or E57 point cloud file</p>
          <UploadDatasetButton />
        </div>
      ) : (
        <div className="bg-[#0a0a0a] border border-[#1a1a1a] rounded-xl overflow-hidden">
          <table className="w-full">
            <thead>
              <tr className="border-b border-[#1a1a1a]">
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Name</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Format</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Points</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Size</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Status</th>
                <th className="text-left px-6 py-3 text-[#444] text-xs font-medium">Uploaded</th>
                <th className="px-6 py-3" />
              </tr>
            </thead>
            <tbody className="divide-y divide-[#111]">
              {datasets.map(dataset => (
                <tr key={dataset.id} className="hover:bg-[#111] transition-colors group">
                  <td className="px-6 py-4">
                    <Link href={`/datasets/${dataset.id}`} className="text-white text-sm hover:underline">
                      {dataset.name}
                    </Link>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#555] text-xs font-mono uppercase">{dataset.format ?? '—'}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#888] text-sm">{formatPoints(dataset.point_count)}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#888] text-sm">{formatBytes(dataset.file_size_bytes)}</span>
                  </td>
                  <td className="px-6 py-4">
                    <span className={`text-xs px-2 py-1 rounded-md ${
                      dataset.status === 'ready' ? 'bg-[#111] text-[#888]' :
                      dataset.status === 'processing' ? 'bg-[#111] text-white' :
                      dataset.status === 'failed' ? 'bg-[#1a0000] text-red-400' :
                      'bg-[#111] text-[#555]'
                    }`}>
                      {dataset.status}
                    </span>
                  </td>
                  <td className="px-6 py-4">
                    <span className="text-[#555] text-xs">
                      {new Date(dataset.created_at).toLocaleDateString()}
                    </span>
                  </td>
                  <td className="px-6 py-4 text-right">
                    {dataset.copc_url && (
                      <Link
                        href={`/viewer/${dataset.id}`}
                        className="text-[#555] text-xs hover:text-white transition-colors opacity-0 group-hover:opacity-100"
                      >
                        View →
                      </Link>
                    )}
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
