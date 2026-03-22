import { createClient } from '@/lib/supabase/server'
import BillingClient from '@/components/billing/BillingClient'
import { redirect } from 'next/navigation'

export const metadata = { title: 'Billing — PointCloud Platform' }

export default async function BillingPage() {
  const supabase = await createClient()
  const { data: { user } } = await supabase.auth.getUser()
  if (!user) redirect('/auth/login')

  // Fetch current subscription from API
  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'
  const { data: { session } } = await supabase.auth.getSession()

  let subscription = null
  if (session?.access_token) {
    try {
      const res = await fetch(`${apiUrl}/api/v1/billing/subscription`, {
        headers: { Authorization: `Bearer ${session.access_token}` },
        cache: 'no-store',
      })
      if (res.ok) subscription = await res.json()
    } catch {
      // Billing not yet configured — show plans only
    }
  }

  // Fetch available plans
  let plans = null
  try {
    const res = await fetch(`${apiUrl}/api/v1/billing/plans`, { cache: 'no-store' })
    if (res.ok) plans = await res.json()
  } catch {
    // API unavailable
  }

  return (
    <BillingClient
      subscription={subscription}
      plans={plans}
      accessToken={session?.access_token ?? ''}
    />
  )
}
