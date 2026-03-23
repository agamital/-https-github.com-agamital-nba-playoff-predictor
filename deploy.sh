#!/bin/bash
set -e

echo "Deploying NBA Playoff Predictor..."

echo ""
echo "Step 1: Building frontend..."
cd frontend
npm run build
echo "Build successful."

echo ""
echo "Step 2: Deploying frontend to Vercel..."
vercel --prod
echo "Frontend deployed."

echo ""
echo "Backend (Railway) deploys automatically on git push."
echo "If not using git, go to railway.app and redeploy manually."

echo ""
echo "Done! Check Vercel dashboard for your live URL."
