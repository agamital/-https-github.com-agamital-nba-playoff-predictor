/**
 * Vercel Serverless Function — /api/cron-reminders
 *
 * Called daily at 10:00 AM IDT (07:00 UTC) by the Vercel Cron scheduler.
 * Forwards the request to the Railway backend which runs the Resend email job.
 *
 * Environment variables required in Vercel project settings:
 *   CRON_SECRET          — shared secret (same value set in Railway)
 *   RAILWAY_BACKEND_URL  — e.g. https://nba-playoff-predictor-production.up.railway.app
 */

const BACKEND_URL =
  process.env.RAILWAY_BACKEND_URL ||
  'https://nba-playoff-predictor-production.up.railway.app';

const CRON_SECRET = process.env.CRON_SECRET || '';

export default async function handler(req, res) {
  // Vercel Cron signs the request with Authorization: Bearer <CRON_SECRET>.
  // Reject anything that doesn't carry the right secret.
  if (CRON_SECRET) {
    const authHeader = req.headers['authorization'] || '';
    if (authHeader !== `Bearer ${CRON_SECRET}`) {
      return res.status(401).json({ error: 'Unauthorized' });
    }
  }

  // Only allow GET (Vercel Cron) or POST (manual curl test)
  if (req.method !== 'GET' && req.method !== 'POST') {
    return res.status(405).json({ error: 'Method not allowed' });
  }

  try {
    const response = await fetch(`${BACKEND_URL}/api/admin/trigger-reminder`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...(CRON_SECRET ? { Authorization: `Bearer ${CRON_SECRET}` } : {}),
      },
    });

    const data = await response.json();
    console.log('[cron-reminders] Backend response:', data);
    return res.status(response.ok ? 200 : 502).json(data);
  } catch (err) {
    console.error('[cron-reminders] Error calling backend:', err);
    return res.status(500).json({ error: err.message });
  }
}
