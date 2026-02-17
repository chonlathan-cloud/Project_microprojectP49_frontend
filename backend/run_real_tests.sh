#!/bin/bash

# This script runs the test suite against a real environment.
# It first checks for the required configuration files.

# Navigate to the backend directory
cd "$(dirname "$0")"

# --- Configuration Checks ---

# 1. Check for .env file
if [ ! -f .env ]; then
    echo "🔴 .env file not found."
    echo "Creating it for you from the example..."
    cp .env.example .env
    echo "✅ .env file created."
    echo "🛑 PLEASE EDIT aip-gemini-workshop-2024/backend/.env and fill in your real GCP and Firebase values."
    exit 1
fi

echo "✅ .env file found."

# 2. Check for Firebase credentials
# Assumes the path is ./firebase-adminsdk.json as per .env.example
FIREBASE_CREDS_PATH=$(grep FIREBASE_CREDENTIALS_PATH .env | cut -d '=' -f2 | tr -d '"')
if [ ! -f "$FIREBASE_CREDS_PATH" ]; then
    echo "🔴 Firebase credentials not found at '$FIREBASE_CREDS_PATH'."
    echo "🛑 PLEASE PLACE your Firebase Admin SDK JSON key file at that location."
    exit 1
fi

echo "✅ Firebase credentials found."

# --- Dependency Installation ---

echo "📦 Installing/updating Python dependencies..."
# Assumes you have a venv. If not, create one with: python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
echo "✅ Dependencies are up to date."


# --- Run Tests ---

echo "🚀 Running tests..."
PYTHONPATH=. python ../tests/test_receipts.py

echo "✅ Tests finished."

