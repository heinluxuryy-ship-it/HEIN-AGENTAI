const express = require('express');
const { default: makeWASocket, DisconnectReason, useMultiFileAuthState, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const qrcode = require('qrcode');
const axios = require('axios');
const pino = require('pino');

const app = express();
app.use(express.json());

let currentQrDataUrl = null;
let clientReady = false;
let sock = null;

// Python webhook on the same container
const pyPort = process.env.PORT || 5000;
const PYTHON_WEBHOOK_URL = `http://127.0.0.1:${pyPort}/webhook/wa_bridge`;

console.log(`[BRIDGE] Target Python webhook: ${PYTHON_WEBHOOK_URL}`);

async function startWhatsApp() {
    try {
        console.log('[BRIDGE] Loading auth state...');
        const { state, saveCreds } = await useMultiFileAuthState('auth_info_baileys');

        const { version } = await fetchLatestBaileysVersion();
        console.log(`[BRIDGE] Creating WhatsApp socket (NO Chromium needed, Web Version: ${version.join('.')})...`);
        sock = makeWASocket({
            version,
            auth: state,
            logger: pino({ level: 'warn' }),
            printQRInTerminal: false,
            browser: ['HEIN AI Agent', 'Chrome', '120.0.0'],
            connectTimeoutMs: 60000,
            defaultQueryTimeoutMs: 0,
            keepAliveIntervalMs: 25000
        });

        // Save credentials whenever they update
        sock.ev.on('creds.update', saveCreds);

        // ===== CONNECTION STATE =====
        sock.ev.on('connection.update', async (update) => {
            const { connection, lastDisconnect, qr } = update;

            if (qr) {
                console.log('[BRIDGE] 📱 QR code generated — scan with WhatsApp!');
                try {
                    currentQrDataUrl = await qrcode.toDataURL(qr);
                } catch (e) {
                    console.error('[BRIDGE] QR encode error:', e.message);
                }
                clientReady = false;
            }

            if (connection === 'close') {
                const statusCode = lastDisconnect?.error?.output?.statusCode;
                const shouldReconnect = statusCode !== DisconnectReason.loggedOut;
                console.log(`[BRIDGE] ⚠️ Connection closed (code=${statusCode}). Reconnect: ${shouldReconnect}`);
                clientReady = false;
                currentQrDataUrl = null;

                if (shouldReconnect) {
                    console.log('[BRIDGE] Reconnecting in 3 seconds...');
                    setTimeout(() => startWhatsApp(), 3000);
                } else {
                    console.log('[BRIDGE] Logged out — delete auth and restart to get new QR.');
                }
            }

            if (connection === 'open') {
                console.log('[BRIDGE] ✅✅✅ WhatsApp CONNECTED and READY! ✅✅✅');
                currentQrDataUrl = null;
                clientReady = true;
            }
        });

        // ===== INCOMING MESSAGES =====
        sock.ev.on('messages.upsert', async ({ messages, type }) => {
            if (type !== 'notify') return;

            for (const msg of messages) {
                // Skip our own messages
                if (msg.key.fromMe) continue;
                if (!msg.message) continue;

                // Skip status broadcasts
                const jid = msg.key.remoteJid || '';
                if (jid === 'status@broadcast') continue;

                // Extract sender phone number
                const sender = jid.replace('@s.whatsapp.net', '').replace('@g.us', '');

                // Extract text from different message types
                const text = msg.message.conversation ||
                             msg.message.extendedTextMessage?.text ||
                             msg.message.imageMessage?.caption ||
                             msg.message.videoMessage?.caption ||
                             '';

                if (!text) {
                    console.log(`[BRIDGE] Non-text message from ${sender}, skipping for now.`);
                    continue;
                }

                console.log(`[BRIDGE] 📩 INCOMING from ${sender}: "${text.substring(0, 80)}"`);

                // Forward to Python
                const payload = {
                    sender: sender,
                    text: text,
                    timestamp: Math.floor(Date.now() / 1000)
                };

                try {
                    console.log(`[BRIDGE] Forwarding to Python...`);
                    const response = await axios.post(PYTHON_WEBHOOK_URL, payload, {
                        timeout: 90000, // 90 second timeout for AI generation
                        headers: { 'Content-Type': 'application/json' }
                    });
                    console.log(`[BRIDGE] ✅ Python responded: ${JSON.stringify(response.data)}`);
                } catch (err) {
                    console.error(`[BRIDGE] ❌ Relay to Python FAILED: ${err.message}`);
                    if (err.response) {
                        console.error(`[BRIDGE] Python status ${err.response.status}: ${JSON.stringify(err.response.data)}`);
                    }

                    // Send fallback reply directly
                    try {
                        await sock.sendMessage(jid, {
                            text: 'Thank you for your message. Our team will respond shortly.'
                        });
                        console.log('[BRIDGE] Sent fallback message.');
                    } catch (fbErr) {
                        console.error('[BRIDGE] Fallback send also failed:', fbErr.message);
                    }
                }
            }
        });

        console.log('[BRIDGE] WhatsApp event handlers registered. Waiting for QR or auto-auth...');

    } catch (err) {
        console.error('[BRIDGE] FATAL startup error:', err);
        console.log('[BRIDGE] Retrying in 10 seconds...');
        setTimeout(() => startWhatsApp(), 10000);
    }
}

// ===== EXPRESS API ENDPOINTS (same as before for Python compatibility) =====

app.get('/status', (req, res) => {
    res.json({
        ready: clientReady,
        qr: currentQrDataUrl
    });
});

app.post('/send', async (req, res) => {
    const { to, message } = req.body;
    console.log(`[BRIDGE] 📤 Send request: to=${to}, msg="${(message || '').substring(0, 60)}..."`);

    if (!clientReady || !sock) {
        console.error('[BRIDGE] ❌ Cannot send — client not ready!');
        return res.status(400).json({ error: 'Client not ready', ready: false });
    }

    // Baileys uses @s.whatsapp.net format
    const jid = to.includes('@') ? to : `${to}@s.whatsapp.net`;

    try {
        await sock.sendMessage(jid, { text: message });
        console.log(`[BRIDGE] ✅ Message SENT to ${jid}`);
        res.json({ status: 'sent', to: jid });
    } catch (err) {
        console.error(`[BRIDGE] ❌ Send FAILED to ${jid}: ${err.message}`);
        res.status(500).json({ error: err.message });
    }
});

app.get('/health', (req, res) => {
    res.json({
        alive: true,
        ready: clientReady,
        hasQR: !!currentQrDataUrl,
        uptime: process.uptime()
    });
});

// ===== START =====
const BRIDGE_PORT = 5001;
app.listen(BRIDGE_PORT, '127.0.0.1', () => {
    console.log(`[BRIDGE] Express API on 127.0.0.1:${BRIDGE_PORT}`);
    console.log('[BRIDGE] Starting Baileys WhatsApp (NO Chromium, pure WebSocket)...');
    startWhatsApp();
});
