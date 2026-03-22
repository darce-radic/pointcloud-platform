import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import Sidebar from '@/components/dashboard/Sidebar'

export default async function DashboardLayout({
  children,
}: {
  children: React.ReactNode
}) {
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()

  if (!data?.claims) {
    redirect('/auth/login')
  }

  // Fetch user's organization
  const { data: orgMember } = await supabase
    .from('organization_members')
    .select('organization_id, role, organizations(id, name, slug)')
    .eq('user_id', data.claims.sub)
    .single()

  return (
    <div className="flex h-screen bg-black text-white overflow-hidden">
      <Sidebar
        user={{ email: data.claims.email as string, id: data.claims.sub }}
        organization={orgMember?.organizations as unknown as { id: string; name: string; slug: string } | null}
      />
      <main className="flex-1 overflow-auto">
        {children}
      </main>
    </div>
  )
}
