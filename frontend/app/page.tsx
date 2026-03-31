import { createClient } from "@/lib/supabase/server"
import { redirect } from "next/navigation"
import LandingPage from "@/components/marketing/LandingPage"

export default async function RootPage() {
  const supabase = await createClient()
  const { data } = await supabase.auth.getClaims()

  // If the user is already logged in, send them straight to the app
  if (data?.claims) {
    redirect("/dashboard")
  }

  // Otherwise, show the marketing landing page
  return <LandingPage />
}
