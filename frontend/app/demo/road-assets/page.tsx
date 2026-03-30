import type { Metadata } from 'next'
import RoadAssetsDemoClient from './RoadAssetsDemoClient'

export const metadata: Metadata = {
  title: 'Road Asset Detection — PointClouds Platform',
  description:
    'Live road asset extraction from LiDAR point cloud data. Detects road surfaces, centrelines, markings, kerbs, traffic signs, and drains.',
  openGraph: {
    title: 'Road Asset Detection — PointClouds',
    description:
      'See how PointClouds automatically detects road infrastructure assets from LiDAR data.',
    type: 'website',
  },
}

interface PageProps {
  searchParams: Promise<{ id?: string }>
}

/**
 * /demo/road-assets?id={datasetId}
 *
 * Passes the optional dataset ID from the query string to the client
 * component, which fetches live data from the API. Without ?id=, the
 * page renders in "no dataset" state with empty panels.
 */
export default async function RoadAssetsDemoPage({ searchParams }: PageProps) {
  const params = await searchParams
  const datasetId = params.id ?? null

  return <RoadAssetsDemoClient datasetId={datasetId} />
}
