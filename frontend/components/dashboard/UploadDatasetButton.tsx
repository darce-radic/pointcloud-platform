'use client'

import { useState, useRef } from 'react'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

export default function UploadDatasetButton() {
  const [uploading, setUploading] = useState(false)
  const [progress, setProgress] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const fileRef = useRef<HTMLInputElement>(null)
  const router = useRouter()
  const supabase = createClient()

  const handleFileChange = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setUploading(true)
    setError(null)
    setProgress(0)

    try {
      // Get the session token
      const { data: { session } } = await supabase.auth.getSession()
      if (!session) throw new Error('Not authenticated')

      const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

      // Step 1: Request a presigned upload URL from the FastAPI backend
      const initRes = await fetch(`${apiUrl}/api/v1/datasets/upload-url`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          'Authorization': `Bearer ${session.access_token}`,
        },
        body: JSON.stringify({
          filename: file.name,
          file_size: file.size,
          content_type: file.type || 'application/octet-stream',
        }),
      })

      if (!initRes.ok) {
        const err = await initRes.json()
        throw new Error(err.detail ?? 'Failed to get upload URL')
      }

      const { upload_url, dataset_id } = await initRes.json()

      // Step 2: Upload directly to S3 using the presigned URL
      await new Promise<void>((resolve, reject) => {
        const xhr = new XMLHttpRequest()
        xhr.upload.addEventListener('progress', (event) => {
          if (event.lengthComputable) {
            setProgress(Math.round((event.loaded / event.total) * 100))
          }
        })
        xhr.addEventListener('load', () => {
          if (xhr.status >= 200 && xhr.status < 300) resolve()
          else reject(new Error(`Upload failed: ${xhr.status}`))
        })
        xhr.addEventListener('error', () => reject(new Error('Upload failed')))
        xhr.open('PUT', upload_url)
        xhr.setRequestHeader('Content-Type', file.type || 'application/octet-stream')
        xhr.send(file)
      })

      // Step 3: Notify the backend that the upload is complete (triggers processing)
      const completeRes = await fetch(`${apiUrl}/api/v1/datasets/${dataset_id}/complete-upload`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${session.access_token}` },
      })

      if (!completeRes.ok) {
        throw new Error('Failed to trigger processing')
      }

      router.refresh()
    } catch (err: unknown) {
      setError(err instanceof Error ? err.message : 'Upload failed')
    } finally {
      setUploading(false)
      setProgress(0)
      if (fileRef.current) fileRef.current.value = ''
    }
  }

  return (
    <div>
      <input
        ref={fileRef}
        type="file"
        accept=".las,.laz,.e57,.ply,.xyz,.pts"
        onChange={handleFileChange}
        className="hidden"
        id="dataset-upload"
      />
      <label
        htmlFor="dataset-upload"
        className={`inline-flex items-center gap-2 px-4 py-2 bg-white text-black text-sm font-medium rounded-lg cursor-pointer hover:bg-[#e0e0e0] transition-colors ${uploading ? 'opacity-50 pointer-events-none' : ''}`}
      >
        {uploading ? (
          <>
            <span className="w-3 h-3 border border-black border-t-transparent rounded-full animate-spin" />
            {progress > 0 ? `${progress}%` : 'Preparing...'}
          </>
        ) : (
          <>
            <span>↑</span>
            Upload Dataset
          </>
        )}
      </label>
      {error && (
        <p className="text-red-400 text-xs mt-2">{error}</p>
      )}
    </div>
  )
}
