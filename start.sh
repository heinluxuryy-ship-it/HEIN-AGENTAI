#!/bin/bash
echo "============================================"
echo "   HEIN AI AGENT - CLOUD START SEQUENCE"
echo "============================================"

# Railway provides PORT dynamically — default to 5000 if not set
export PORT=${PORT:-5000}
echo "Flask will listen on port: $PORT"
echo "Node bridge will run on port: 5001 (internal)"

# ── Start Node.js WhatsApp Bridge in the background ──
echo "[1/2] Starting Node.js WhatsApp Bridge..."
node wa_bridge.js &
BRIDGE_PID=$!
echo "[1/2] Bridge PID: $BRIDGE_PID"

# Give bridge time to initialize
sleep 4

# Check if bridge is alive
if kill -0 $BRIDGE_PID 2>/dev/null; then
    echo "[1/2] WhatsApp Bridge is running."
else
    echo "[1/2] WARNING: Bridge crashed — Python will still start (simulation mode)."
fi

# ── Start Python Flask AI Agent in the foreground ──
echo "[2/2] Starting HEIN Python AI on port $PORT..."
python app.py

# If Python exits, also kill the bridge
kill $BRIDGE_PID 2>/dev/null
