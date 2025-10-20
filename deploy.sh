#!/bin/bash
# Deployment script for UAE-Sale System
# Usage: ./deploy.sh

git add -A
git commit -m "update"
git push origin HEAD

echo "✓ Deployed"

