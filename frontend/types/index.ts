// ============================================================
// Core domain types — mirror the Supabase database schema
// ============================================================

export type OrganizationRole = 'owner' | 'admin' | 'member' | 'viewer'

export interface Organization {
  id: string
  name: string
  slug: string
  created_at: string
}

export interface OrganizationMember {
  id: string
  organization_id: string
  user_id: string
  role: OrganizationRole
  created_at: string
}

export type DatasetStatus = 'uploading' | 'uploaded' | 'processing' | 'ready' | 'failed'
export type DatasetFormat = 'las' | 'laz' | 'e57' | 'ply' | 'xyz' | 'pts'

export interface Dataset {
  id: string
  organization_id: string
  project_id: string | null
  name: string
  description: string | null
  format: DatasetFormat | null
  status: DatasetStatus
  point_count: number | null
  file_size_bytes: number | null
  crs_epsg: number | null
  bounding_box: BoundingBox | null
  raw_s3_key: string | null
  copc_url: string | null
  dtm_url: string | null
  created_at: string
  updated_at: string
}

export interface BoundingBox {
  min_x: number
  min_y: number
  min_z: number
  max_x: number
  max_y: number
  max_z: number
}

export type JobType =
  | 'tiling'
  | 'georeferencing'
  | 'bim_extraction'
  | 'road_assets'
  | 'dtm_generation'
  | 'segmentation'

export type JobStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface ProcessingJob {
  id: string
  organization_id: string
  dataset_id: string
  job_type: JobType
  status: JobStatus
  progress: number
  parameters: Record<string, unknown>
  result_urls: Record<string, string> | null
  error_message: string | null
  worker_id: string | null
  created_at: string
  started_at: string | null
  completed_at: string | null
}

export interface Project {
  id: string
  organization_id: string
  name: string
  description: string | null
  created_at: string
  updated_at: string
}

export interface WorkflowTool {
  id: string
  organization_id: string | null
  name: string
  description: string
  icon: string
  n8n_workflow_id: string
  required_inputs: Record<string, WorkflowInputSpec>
  is_active: boolean
  is_system: boolean
  sort_order: number
  created_at: string
}

export interface WorkflowInputSpec {
  type: 'string' | 'number' | 'boolean' | 'select' | 'spatial_polygon'
  label: string
  default?: unknown
  options?: string[]
  required?: boolean
}

export interface Conversation {
  id: string
  organization_id: string
  dataset_id: string | null
  title: string | null
  created_at: string
}

export interface ConversationMessage {
  id: string
  conversation_id: string
  role: 'user' | 'assistant' | 'tool'
  content: string
  metadata: Record<string, unknown> | null
  created_at: string
}

// ============================================================
// API request/response types
// ============================================================

export interface UploadUrlRequest {
  filename: string
  file_size: number
  content_type: string
}

export interface UploadUrlResponse {
  upload_url: string
  dataset_id: string
  expires_in: number
}

export interface StreamChatRequest {
  message: string
  dataset_id?: string
  conversation_id?: string
}

export interface SSEEvent {
  type: 'token' | 'conversation_id' | 'job_started' | 'workflow_deployed' | 'error' | 'done'
  content?: string
  conversation_id?: string
  job_id?: string
  workflow_id?: string
  message?: string
}
