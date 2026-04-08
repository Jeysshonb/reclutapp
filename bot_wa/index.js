/**
 * AraBot — WhatsApp bot para reclutamiento Tiendas Ara
 * Usa @whiskeysockets/baileys (sin Chrome/Puppeteer)
 * GET /    → status
 * GET /qr  → escanear QR
 * GET /reset      → reiniciar proceso (mantiene sesion)
 * GET /reset-full → borrar sesion completa (necesita nuevo QR)
 */

const { default: makeWASocket, useMultiFileAuthState, DisconnectReason,
        downloadMediaMessage, isJidGroup, fetchLatestBaileysVersion } = require('@whiskeysockets/baileys');
const { Boom } = require('@hapi/boom');
const QRCode = require('qrcode');
const axios  = require('axios');
const express = require('express');
const path   = require('path');
const fs     = require('fs');
const pino   = require('pino');

const PORT        = process.env.PORT || 3000;
const BACKEND     = process.env.BACKEND_URL || 'https://reclutapp-prod-dkhggmfdgrckdkeq.westeurope-01.azurewebsites.net';
const ENDPOINT    = `${BACKEND}/api/webhook/whatsapp/json`;
const SESSION_DIR = process.env.SESSION_DIR || path.join(require('os').homedir(), '.arabot_session');

const silentLogger = pino({ level: 'silent' });

// Mapa LID → número real de teléfono
const lidToPhone = new Map();

// ── Estado global ──────────────────────────────────────────────────────────────
let qrImageData = null;
let botListo    = false;
let botEstado   = 'iniciando';
let sock        = null;

// ── Express ────────────────────────────────────────────────────────────────────
const app = express();

app.get('/', (req, res) => {
    res.json({
        estado: botEstado,
        listo: botListo,
        backend: BACKEND,
        mensaje: botListo ? 'AraBot activo y recibiendo mensajes' : 'Esperando vinculacion — ve a /qr'
    });
});

app.get('/qr', (req, res) => {
    if (botListo) {
        return res.send('<h2 style="font-family:sans-serif;color:green">✅ AraBot ya está conectado y activo</h2>');
    }
    if (!qrImageData) {
        return res.send('<h2 style="font-family:sans-serif">⏳ Generando QR... recarga en 5 segundos</h2><meta http-equiv="refresh" content="5">');
    }
    res.send(`<!DOCTYPE html><html>
    <head><title>AraBot — Vincular WhatsApp</title><meta http-equiv="refresh" content="30">
    <style>body{font-family:sans-serif;text-align:center;padding:40px;background:#f0f0f0}
    img{border:4px solid #25D366;border-radius:12px;padding:10px;background:white}
    h2{color:#128C7E}p{color:#666}</style></head>
    <body><h2>Escanea este QR con WhatsApp Business</h2>
    <p>Abre WhatsApp → Dispositivos vinculados → Vincular dispositivo</p>
    <img src="${qrImageData}" width="300" height="300"/><br><br>
    <p><small>El QR se renueva cada 30 segundos — esta página se actualiza automáticamente</small></p>
    </body></html>`);
});

app.get('/reset', (req, res) => {
    console.log('Reset solicitado — reiniciando proceso...');
    res.send('<h2 style="font-family:sans-serif;color:orange">🔄 Reiniciando... ve a <a href="/qr">/qr</a> en 10 segundos</h2>');
    setTimeout(() => process.exit(0), 1000);
});

app.get('/reset-full', (req, res) => {
    console.log('Reset COMPLETO — borrando sesion...');
    res.send('<h2 style="font-family:sans-serif;color:red">⚠️ Sesion borrada — ve a <a href="/qr">/qr</a> en 10s para escanear QR nuevo</h2>');
    try { fs.rmSync(SESSION_DIR, { recursive: true, force: true }); } catch(e) {}
    setTimeout(() => process.exit(0), 1000);
});

app.listen(PORT, () => {
    console.log(`Servidor web en puerto ${PORT}`);
    console.log(`QR: http://localhost:${PORT}/qr | Reset: http://localhost:${PORT}/reset`);
});

// ── Resolver LID → número real ─────────────────────────────────────────────────
function resolverPhone(rawJid) {
    if (!rawJid.endsWith('@lid')) {
        return rawJid.replace('@s.whatsapp.net', '');
    }
    const lid = rawJid.replace('@lid', '');
    return lidToPhone.has(lid) ? lidToPhone.get(lid) : null;
}

// Cuando contacts.upsert resuelve un LID que ya estaba guardado como teléfono en el backend,
// actualizar la sesión en el backend para que las reclutadoras vean el número real.
async function actualizarPhoneEnBackend(lidNumerico, phoneReal) {
    try {
        await axios.post(`${BACKEND}/api/webhook/whatsapp/fix-lid`,
            { lid: lidNumerico, phone: phoneReal },
            { timeout: 10000 });
        console.log(`LID actualizado en backend: ${lidNumerico} → ${phoneReal}`);
    } catch(e) {
        // No crítico — el backend puede no tener este endpoint aún
    }
}

// ── Conexión WhatsApp (Baileys — sin Chrome) ───────────────────────────────────
async function conectar() {
    const { state, saveCreds } = await useMultiFileAuthState(SESSION_DIR);
    const { version } = await fetchLatestBaileysVersion();
    console.log(`Usando WhatsApp versión: ${version.join('.')}`);

    sock = makeWASocket({
        version,
        auth: state,
        logger: silentLogger,
        browser: ['AraBot', 'Chrome', '1.0.0'],
        connectTimeoutMs: 60000,
        keepAliveIntervalMs: 30000,
    });

    sock.ev.on('creds.update', saveCreds);

    // Mapear LID → número real cuando llegan contactos
    const procesarContactos = (contacts) => {
        for (const c of contacts) {
            if (c.id && c.lid) {
                const phone = c.id.replace('@s.whatsapp.net', '');
                const lid   = c.lid.replace('@lid', '');
                if (!lidToPhone.has(lid)) {
                    lidToPhone.set(lid, phone);
                    // Si este LID ya fue procesado como teléfono, actualizar backend
                    actualizarPhoneEnBackend(lid, phone);
                }
            }
        }
    };

    sock.ev.on('contacts.upsert', procesarContactos);
    sock.ev.on('contacts.update', procesarContactos);

    sock.ev.on('connection.update', async ({ connection, lastDisconnect, qr }) => {
        if (qr) {
            botEstado = 'esperando_qr';
            try {
                qrImageData = await QRCode.toDataURL(qr);
                console.log('QR generado — abre /qr para escanearlo');
            } catch(e) { console.error('Error generando QR imagen:', e.message); }
        }

        if (connection === 'open') {
            botListo    = true;
            botEstado   = 'activo';
            qrImageData = null;
            console.log('AraBot listo y escuchando mensajes');
            console.log(`Backend: ${BACKEND}`);
        }

        if (connection === 'close') {
            botListo  = false;
            botEstado = 'desconectado';
            const statusCode = (lastDisconnect?.error instanceof Boom)
                ? lastDisconnect.error.output.statusCode : 0;
            console.log(`Desconectado — codigo: ${statusCode}`);

            if (statusCode === DisconnectReason.loggedOut) {
                console.log('Sesion cerrada por WhatsApp — borrando credenciales...');
                try { fs.rmSync(SESSION_DIR, { recursive: true, force: true }); } catch(e) {}
                process.exit(0);
            } else {
                console.log('Reconectando en 5s...');
                botEstado = 'reconectando';
                setTimeout(conectar, 5000);
            }
        }
    });

    // ── Procesar mensajes ────────────────────────────────────────────────────────
    sock.ev.on('messages.upsert', async ({ messages, type }) => {
        if (type !== 'notify') return;

        for (const message of messages) {
            try {
                if (!message.message) continue;
                if (message.key.fromMe) continue;
                if (isJidGroup(message.key.remoteJid)) continue;

                const rawJid = message.key.remoteJid;
                let phone = resolverPhone(rawJid);
                if (phone === null) {
                    phone = rawJid.replace('@lid', '');
                }

                const pushName  = message.pushName || null;
                const msgContent = message.message;
                const msgType    = Object.keys(msgContent)[0];

                let payload = { phone, nombre: pushName, message: '' };

                if (msgType === 'conversation' || msgType === 'extendedTextMessage') {
                    const texto = msgContent.conversation || msgContent.extendedTextMessage?.text || '';
                    if (!texto.trim()) continue;
                    payload.message = texto.trim();
                    console.log(`[${phone}] ${pushName || ''}: ${texto.trim().substring(0, 60)}`);

                } else if (msgType === 'imageMessage') {
                    const buffer = await downloadMediaMessage(message, 'buffer', {}, { logger: silentLogger, reuploadRequest: sock.updateMediaMessage });
                    if (!buffer || buffer.length === 0) {
                        console.warn(`[${phone}] imagen vacía — descarga fallida`);
                        payload.message = '[foto_cedula]';
                    } else {
                        payload.message         = '[foto_cedula]';
                        payload.imagen_base64   = buffer.toString('base64');
                        payload.imagen_mimetype = msgContent.imageMessage.mimetype || 'image/jpeg';
                        console.log(`[${phone}] ${pushName || ''}: [imagen ${Math.round(buffer.length/1024)}KB]`);
                    }

                } else if (msgType === 'audioMessage' || msgType === 'pttMessage') {
                    const buffer = await downloadMediaMessage(message, 'buffer', {});
                    payload.message        = '[audio]';
                    payload.audio_base64   = buffer.toString('base64');
                    payload.audio_mimetype = msgContent[msgType]?.mimetype || 'audio/ogg; codecs=opus';
                    console.log(`[${phone}] ${pushName || ''}: [audio ${Math.round(buffer.length/1024)}KB]`);

                } else if (msgType === 'documentMessage' || msgType === 'documentWithCaptionMessage') {
                    const doc = msgContent.documentMessage || msgContent.documentWithCaptionMessage?.message?.documentMessage;
                    if (!doc) continue;
                    const buffer = await downloadMediaMessage(message, 'buffer', {});
                    payload.message            = '[documento]';
                    payload.documento_base64   = buffer.toString('base64');
                    payload.documento_mimetype = doc.mimetype || 'application/octet-stream';
                    payload.documento_nombre   = doc.fileName || 'documento';
                    console.log(`[${phone}] ${pushName || ''}: [doc: ${doc.fileName || 'sin nombre'}]`);

                } else {
                    continue;
                }

                const resp = await axios.post(ENDPOINT, payload, { timeout: 45000 });
                const respuesta = resp.data?.response || 'Hubo un error. Intenta de nuevo.';
                console.log(`AraBot → [${phone}]: ${respuesta.substring(0, 80)}`);
                await sock.sendMessage(rawJid, { text: respuesta });

            } catch(err) {
                console.error(`Error procesando mensaje: ${err.message}`);
                try {
                    // Si es timeout (ECONNABORTED / timeout) el servidor está despertando — pedir reenvío
                    const esTimeout = err.code === 'ECONNABORTED' || err.message?.includes('timeout') || err.response?.status >= 500;
                    const msgError = esTimeout
                        ? '⏳ Un momento, estoy cargando... Por favor envía tu mensaje de nuevo 😊'
                        : 'Ocurrió un error. Por favor intenta de nuevo.';
                    await sock.sendMessage(message.key.remoteJid, { text: msgError });
                } catch(e) {}
            }
        }
    });
}

console.log('Iniciando AraBot (Baileys — sin Chrome)...');
conectar().catch(e => {
    console.error('Error fatal al conectar:', e.message);
    process.exit(1);
});
