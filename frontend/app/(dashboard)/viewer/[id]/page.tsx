import { createClient } from '@/lib/supabase/server'
import { notFound } from 'next/navigation'
import ViewerClient from '@/components/viewer/ViewerClient'

interface ViewerPageProps {
  params: Promise<{ id: string }>
}

export default async function ViewerPage({ params }: ViewerPageProps) {
  const { id } = await params
  const supabase = await createClient()

  const { data: dataset, error } = await supabase
    .from('datasets')
    .select('id, name, copc_url, road_assets_url, status, point_count, crs_epsg, bounding_box')
    .eq('id', id)
    .single()

  if (error || !dataset) {
    notFound()
  }

  // Fetch workflow tools for this dataset's toolbar
  const { data: workflowTools } = await supabase
    .from('workflow_tools')
    .select('id, name, description, icon, required_inputs, n8n_workflow_id')
    .eq('is_active', true)
    .order('sort_order', { ascending: true })

  return (
    <ViewerClient
      dataset={{
        id: dataset.id,
        name: dataset.name,
        copcUrl: dataset.copc_url,
        roadAssetsUrl: dataset.road_assets_url ?? null,
        status: dataset.status,
        pointCount: dataset.point_count,
        crsEpsg: dataset.crs_epsg,
        boundingBox: dataset.bounding_box,
      }}
      workflowTools={workflowTools ?? []}
    />
  )
}
