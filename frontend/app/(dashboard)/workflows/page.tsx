import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import WorkflowGeneratorClient from '@/components/workflows/WorkflowGeneratorClient'

/**
 * Workflows page — chat-driven n8n workflow generator.
 *
 * Fetches the user's organization_id server-side (needed by the agent
 * to scope workflow creation) and passes it to the client component.
 */
export default async function WorkflowsPage() {
  const supabase = await createClient()
  const { data: authData } = await supabase.auth.getClaims()
  if (!authData?.claims) {
    redirect('/auth/login')
  }

  const { data: orgMember } = await supabase
    .from('organization_members')
    .select('organization_id')
    .eq('user_id', authData.claims.sub)
    .single()

  const organizationId = orgMember?.organization_id ?? ''

  return (
    <div className="h-full flex flex-col">
      <WorkflowGeneratorClient organizationId={organizationId} />
    </div>
  )
}
