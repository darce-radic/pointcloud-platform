'use client'

import Link from 'next/link'
import { usePathname } from 'next/navigation'
import { createClient } from '@/lib/supabase/client'
import { useRouter } from 'next/navigation'

interface SidebarProps {
  user: { email: string; id: string }
  organization: { id: string; name: string; slug: string } | null
}

const navItems = [
  { href: '/dashboard', label: 'Overview', icon: '▦' },
  { href: '/datasets', label: 'Datasets', icon: '◈' },
  { href: '/projects', label: 'Projects', icon: '◉' },
  { href: '/jobs', label: 'Jobs', icon: '◎' },
  { href: '/workflows', label: 'Workflows', icon: '⬡' },
  { href: '/billing', label: 'Billing', icon: '◇' },
  { href: '/settings', label: 'Settings', icon: '◌' },
]

export default function Sidebar({ user, organization }: SidebarProps) {
  const pathname = usePathname()
  const router = useRouter()
  const supabase = createClient()

  const handleSignOut = async () => {
    await supabase.auth.signOut()
    router.push('/auth/login')
    router.refresh()
  }

  return (
    <aside className="w-56 flex flex-col border-r border-[#1a1a1a] bg-black shrink-0">
      {/* Logo */}
      <div className="px-5 py-5 border-b border-[#1a1a1a]">
        <div className="flex items-center gap-2.5">
          <div className="w-6 h-6 bg-white rounded-sm flex items-center justify-center shrink-0">
            <div className="w-3 h-3 bg-black rounded-sm" />
          </div>
          <span className="text-white text-sm font-semibold tracking-tight truncate">
            {organization?.name ?? 'PointCloud'}
          </span>
        </div>
      </div>

      {/* Navigation */}
      <nav className="flex-1 px-3 py-4 space-y-0.5">
        {navItems.map(item => {
          const isActive = pathname === item.href || pathname.startsWith(item.href + '/')
          return (
            <Link
              key={item.href}
              href={item.href}
              className={`flex items-center gap-3 px-3 py-2 rounded-md text-sm transition-colors ${
                isActive
                  ? 'bg-[#1a1a1a] text-white'
                  : 'text-[#666] hover:text-[#aaa] hover:bg-[#111]'
              }`}
            >
              <span className="text-base leading-none">{item.icon}</span>
              {item.label}
            </Link>
          )
        })}
      </nav>

      {/* User */}
      <div className="px-3 py-4 border-t border-[#1a1a1a]">
        <div className="flex items-center gap-3 px-3 py-2">
          <div className="w-7 h-7 rounded-full bg-[#222] flex items-center justify-center shrink-0">
            <span className="text-[#888] text-xs font-medium">
              {user.email[0].toUpperCase()}
            </span>
          </div>
          <div className="flex-1 min-w-0">
            <p className="text-[#888] text-xs truncate">{user.email}</p>
          </div>
          <button
            onClick={handleSignOut}
            className="text-[#444] hover:text-[#888] transition-colors text-xs"
            title="Sign out"
          >
            ⏻
          </button>
        </div>
      </div>
    </aside>
  )
}
