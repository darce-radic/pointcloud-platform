import { createClient } from '@/lib/supabase/server'
import { redirect } from 'next/navigation'
import LoginForm from '@/components/auth/LoginForm'

export default async function LoginPage() {
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()

  if (data?.claims) {
    redirect('/dashboard')
  }

  return (
    <div className="min-h-screen bg-black flex items-center justify-center">
      <div className="w-full max-w-md px-8">
        {/* Logo */}
        <div className="mb-10 text-center">
          <div className="inline-flex items-center gap-3 mb-2">
            <div className="w-8 h-8 bg-white rounded-sm flex items-center justify-center">
              <div className="w-4 h-4 bg-black rounded-sm" />
            </div>
            <span className="text-white text-xl font-semibold tracking-tight">PointCloud Platform</span>
          </div>
          <p className="text-[#666] text-sm mt-3">Sign in to your workspace</p>
        </div>

        <LoginForm />

        <p className="text-center text-[#444] text-xs mt-8">
          By signing in, you agree to our{' '}
          <a href="#" className="text-[#666] hover:text-white transition-colors">Terms of Service</a>
          {' '}and{' '}
          <a href="#" className="text-[#666] hover:text-white transition-colors">Privacy Policy</a>
        </p>
      </div>
    </div>
  )
}
