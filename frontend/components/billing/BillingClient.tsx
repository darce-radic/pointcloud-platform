'use client'

import { useState } from 'react'

interface Plan {
  name: string
  price_usd: number
  features: string[]
  storage_gb: number
  max_projects: number | null
}

interface Subscription {
  plan: string
  plan_name: string
  status: string
  storage_used_bytes: number
  storage_limit_bytes: number
  features: string[]
}

interface BillingClientProps {
  subscription: Subscription | null
  plans: Record<string, Plan> | null
  accessToken: string
}

const PLAN_ORDER = ['starter', 'pro', 'enterprise']
const HIGHLIGHTED_PLAN = 'pro'

const STATUS_LABELS: Record<string, { label: string; color: string }> = {
  active: { label: 'Active', color: 'text-green-400' },
  trialing: { label: 'Trial', color: 'text-blue-400' },
  past_due: { label: 'Past Due', color: 'text-yellow-400' },
  canceled: { label: 'Cancelled', color: 'text-red-400' },
  inactive: { label: 'Inactive', color: 'text-[#555]' },
}

function formatBytes(bytes: number): string {
  if (bytes >= 1024 ** 4) return `${(bytes / 1024 ** 4).toFixed(1)} TB`
  if (bytes >= 1024 ** 3) return `${(bytes / 1024 ** 3).toFixed(0)} GB`
  if (bytes >= 1024 ** 2) return `${(bytes / 1024 ** 2).toFixed(0)} MB`
  return `${bytes} B`
}

export default function BillingClient({ subscription, plans, accessToken }: BillingClientProps) {
  const [loading, setLoading] = useState<string | null>(null)
  const [error, setError] = useState<string | null>(null)

  const apiUrl = process.env.NEXT_PUBLIC_API_URL ?? 'http://localhost:8000'

  const handleSubscribe = async (planKey: string) => {
    setLoading(planKey)
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/v1/billing/checkout`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({
          plan: planKey,
          success_url: `${window.location.origin}/billing?success=1`,
          cancel_url: `${window.location.origin}/billing?cancelled=1`,
        }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail ?? 'Failed to create checkout session')
      }
      const { checkout_url } = await res.json()
      window.location.href = checkout_url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
      setLoading(null)
    }
  }

  const handleManage = async () => {
    setLoading('portal')
    setError(null)
    try {
      const res = await fetch(`${apiUrl}/api/v1/billing/portal`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json',
          Authorization: `Bearer ${accessToken}`,
        },
        body: JSON.stringify({ return_url: window.location.href }),
      })
      if (!res.ok) {
        const err = await res.json()
        throw new Error(err.detail ?? 'Failed to open billing portal')
      }
      const { portal_url } = await res.json()
      window.location.href = portal_url
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Something went wrong')
      setLoading(null)
    }
  }

  const currentPlan = subscription?.plan ?? null
  const subStatus = subscription?.status ?? null
  const isActive = subStatus === 'active' || subStatus === 'trialing'

  const storageUsed = subscription?.storage_used_bytes ?? 0
  const storageLimit = subscription?.storage_limit_bytes ?? 0
  const storagePercent = storageLimit > 0 ? Math.min(100, (storageUsed / storageLimit) * 100) : 0

  return (
    <div className="min-h-screen bg-black text-white px-6 py-12 max-w-5xl mx-auto">
      {/* Header */}
      <div className="mb-12">
        <h1 className="text-2xl font-semibold tracking-tight mb-1">Billing</h1>
        <p className="text-[#555] text-sm">Manage your subscription and storage.</p>
      </div>

      {/* Current subscription card */}
      {subscription && isActive && (
        <div className="mb-12 border border-[#1a1a1a] rounded-2xl p-6 bg-[#0a0a0a]">
          <div className="flex items-start justify-between mb-6">
            <div>
              <p className="text-xs text-[#555] uppercase tracking-widest mb-1">Current Plan</p>
              <p className="text-xl font-semibold">{subscription.plan_name}</p>
            </div>
            <div className="flex items-center gap-3">
              <span className={`text-xs font-medium ${STATUS_LABELS[subStatus ?? 'inactive']?.color ?? 'text-[#555]'}`}>
                {STATUS_LABELS[subStatus ?? 'inactive']?.label ?? 'Unknown'}
              </span>
              <button
                onClick={handleManage}
                disabled={loading === 'portal'}
                className="px-4 py-2 rounded-lg text-xs font-medium bg-[#111] border border-[#222] text-[#888] hover:text-white hover:border-[#333] transition-colors disabled:opacity-50"
              >
                {loading === 'portal' ? 'Opening...' : 'Manage Subscription'}
              </button>
            </div>
          </div>

          {/* Storage bar */}
          <div>
            <div className="flex items-center justify-between mb-2">
              <p className="text-xs text-[#555]">Storage</p>
              <p className="text-xs text-[#555]">
                {formatBytes(storageUsed)} / {formatBytes(storageLimit)}
              </p>
            </div>
            <div className="h-1.5 bg-[#111] rounded-full overflow-hidden">
              <div
                className="h-full bg-white rounded-full transition-all"
                style={{ width: `${storagePercent}%` }}
              />
            </div>
          </div>
        </div>
      )}

      {/* Error banner */}
      {error && (
        <div className="mb-8 px-4 py-3 rounded-xl bg-red-950/40 border border-red-900/50 text-red-400 text-sm">
          {error}
        </div>
      )}

      {/* Pricing grid */}
      <div>
        <h2 className="text-sm font-medium text-[#555] uppercase tracking-widest mb-6">
          {isActive ? 'Change Plan' : 'Choose a Plan'}
        </h2>

        {plans ? (
          <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
            {PLAN_ORDER.map((planKey) => {
              const plan = plans[planKey]
              if (!plan) return null

              const isCurrent = currentPlan === planKey && isActive
              const isHighlighted = planKey === HIGHLIGHTED_PLAN

              return (
                <div
                  key={planKey}
                  className={`relative rounded-2xl p-6 border transition-all ${
                    isHighlighted
                      ? 'border-white/20 bg-[#0d0d0d]'
                      : 'border-[#1a1a1a] bg-[#0a0a0a]'
                  }`}
                >
                  {isHighlighted && (
                    <div className="absolute -top-px left-6 right-6 h-px bg-gradient-to-r from-transparent via-white/40 to-transparent" />
                  )}

                  {isCurrent && (
                    <div className="absolute top-4 right-4 px-2 py-0.5 rounded-full bg-white/10 text-white text-[10px] font-medium">
                      Current
                    </div>
                  )}

                  <div className="mb-6">
                    <p className="text-xs text-[#555] uppercase tracking-widest mb-2">{plan.name}</p>
                    <div className="flex items-baseline gap-1">
                      <span className="text-3xl font-semibold">${plan.price_usd}</span>
                      <span className="text-[#444] text-sm">/mo</span>
                    </div>
                  </div>

                  <ul className="space-y-2.5 mb-8">
                    {plan.features.map((feature, i) => (
                      <li key={i} className="flex items-start gap-2.5 text-sm text-[#888]">
                        <span className="text-white mt-0.5 shrink-0">—</span>
                        {feature}
                      </li>
                    ))}
                  </ul>

                  <button
                    onClick={() => !isCurrent && handleSubscribe(planKey)}
                    disabled={isCurrent || loading === planKey}
                    className={`w-full py-2.5 rounded-xl text-sm font-medium transition-all ${
                      isCurrent
                        ? 'bg-[#111] text-[#333] border border-[#1a1a1a] cursor-default'
                        : isHighlighted
                        ? 'bg-white text-black hover:bg-white/90 active:scale-[0.98]'
                        : 'bg-[#111] text-[#888] border border-[#222] hover:text-white hover:border-[#333]'
                    } disabled:opacity-50`}
                  >
                    {loading === planKey
                      ? 'Redirecting...'
                      : isCurrent
                      ? 'Current plan'
                      : isActive
                      ? 'Switch plan'
                      : 'Subscribe'}
                  </button>
                </div>
              )
            })}
          </div>
        ) : (
          <div className="text-[#555] text-sm">
            Billing is not yet configured. Please contact support.
          </div>
        )}
      </div>

      {/* Footer note */}
      <p className="mt-12 text-xs text-[#333] text-center">
        All plans are billed monthly. Cancel anytime via the billing portal. Prices in USD.
      </p>
    </div>
  )
}
