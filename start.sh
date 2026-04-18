#!/bin/bash
echo "=== HEIN AI START SEQUENCE ==="
echo "PORT env var: $PORT"

# Start Node.js WhatsApp Bridge in the background
echo "[1/2] Starting Node.js WhatsApp Bridge on port 5001..."
node wa_bridge.js &
BRIDGE_PID=$!
echo "[1/2] Bridge started with PID: $BRIDGE_PID"

# Give the bridge a moment to initialize
sleep 3

# Check if bridge is still running
if kill -0 $BRIDGE_PID 2>/dev/null; then
    echo "[1/2] ✅ Bridge is running."
else
    echo "[1/2] ❌ Bridge crashed on startup!"
fi

# Start the Python AI API in the foreground
echo "[2/2] Starting Python HEIN Orchestrator on port $PORT..."
python app.py
