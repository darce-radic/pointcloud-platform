import type { Metadata } from 'next'
import RoadAssetsDemoClient from './RoadAssetsDemoClient'

export const metadata: Metadata = {
  title: 'Road Asset Detection Demo — PointClouds',
  description:
    'Interactive demonstration of AI-powered road asset detection from LiDAR point clouds. Detects road surfaces, centrelines, markings, kerbs, traffic signs and drains.',
  openGraph: {
    title: 'Road Asset Detection — PointClouds',
    description:
      'See how PointClouds automatically detects road infrastructure assets from LiDAR data.',
    type: 'website',
  },
}

export default function RoadAssetsDemoPage() {
  return <RoadAssetsDemoClient />
}
