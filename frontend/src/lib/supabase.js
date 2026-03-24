import { createClient } from '@supabase/supabase-js'

const SUPABASE_URL = import.meta.env.VITE_SUPABASE_URL || 'https://nvfmfbedpbulynqmbdqt.supabase.co'
const SUPABASE_ANON_KEY = import.meta.env.VITE_SUPABASE_ANON_KEY || ''

// Treat the placeholder value (committed to .env.production) as unconfigured
const isRealKey = SUPABASE_ANON_KEY && SUPABASE_ANON_KEY !== 'REPLACE_WITH_SUPABASE_ANON_KEY'

if (!isRealKey) {
  console.warn('[Supabase] VITE_SUPABASE_ANON_KEY is not set — Google login will be disabled. Add it in Vercel → Settings → Environment Variables.')
}

export const supabase = isRealKey
  ? createClient(SUPABASE_URL, SUPABASE_ANON_KEY)
  : null
