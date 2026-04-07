/**
 * AraBot — WhatsApp Web bot para reclutamiento Tiendas Ara
 * Corre en Azure App Service (Node.js 20 Linux)
 * GET /       → status del bot
 * GET /qr     → página para escanear el QR con WhatsApp
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const QRCode = require('qrcode');
const axios = require('axios');
const express = require('express');
const path = require('path');
const fs = require('fs');

const PORT = process.env.PORT || 3000;
const BACKEND = process.env.BACKEND_URL || 'https://reclutapp-prod-dkhggmfdgrckdkeq.westeurope-01.azurewebsites.net';
const ENDPOINT = `${BACKEND}/api/webhook/whatsapp/json`;
const SESSION_DIR = process.env.SESSION_DIR || path.join(require('os').homedir(), '.arabot_session');

// ── Estado global ─────────────────────────────────────────────────────────────
let qrImageData = null;   // QR como imagen base64
let botListo = false;
let botEstado = 'iniciando';

// ── Express (servidor web) ────────────────────────────────────────────────────
const app = express();

app.get('/', (req, res) => {
    res.json({
        estado: botEstado,
        listo: botListo,
        backend: BACKEND,
        mensaje: botListo ? 'AraBot activo y recibiendo mensajes' : 'Esperando vinculacion — ve a /qr'
    });
});

app.get('/qr', async (req, res) => {
    if (botListo) {
        return res.send('<h2 style="font-family:sans-serif;color:green">✅ AraBot ya está conectado y activo</h2>');
    }
    if (!qrImageData) {
        return res.send('<h2 style="font-family:sans-serif">⏳ Generando QR... recarga en 5 segundos</h2><meta http-equiv="refresh" content="5">');
    }
    res.send(`
        <!DOCTYPE html>
        <html>
        <head>
            <title>AraBot — Vincular WhatsApp</title>
            <meta http-equiv="refresh" content="30">
            <style>
                body { font-family: sans-serif; text-align: center; padding: 40px; background: #f0f0f0; }
                img { border: 4px solid #25D366; border-radius: 12px; padding: 10px; background: white; }
                h2 { color: #128C7E; }
                p { color: #666; }
            </style>
        </head>
        <body>
            <h2>Escanea este QR con WhatsApp Business</h2>
            <p>Abre WhatsApp → Dispositivos vinculados → Vincular dispositivo</p>
            <img src="${qrImageData}" width="300" height="300" /><br><br>
            <p><small>El QR se renueva cada 30 segundos — esta página se actualiza automáticamente</small></p>
        </body>
        </html>
    `);
});

app.get('/reset', (req, res) => {
    console.log('Reset manual solicitado — limpiando sesion y reiniciando...');
    botListo = false;
    botEstado = 'reiniciando';
    qrImageData = null;
    try { execSync('pkill -f chromium 2>/dev/null'); } catch(e) {}
    try { execSync(`rm -rf ${SESSION_DIR} 2>/dev/null`); } catch(e) {}
    setTimeout(() => {
        client.initialize().catch(e => console.error('Error tras reset:', e.message));
    }, 3000);
    res.send('<h2 style="font-family:sans-serif;color:orange">🔄 Reiniciando AraBot... ve a <a href="/qr">/qr</a> en 30 segundos</h2>');
});

app.listen(PORT, () => {
    console.log(`Servidor web en puerto ${PORT}`);
    console.log(`QR disponible en: http://localhost:${PORT}/qr`);
    console.log(`Reset disponible en: http://localhost:${PORT}/reset`);
});

// ── Cliente WhatsApp ──────────────────────────────────────────────────────────
const client = new Client({
    authStrategy: new LocalAuth({ clientId: 'arabot', dataPath: SESSION_DIR }),
    puppeteer: {
        headless: true,
        executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
        timeout: 120000,
        protocolTimeout: 120000,
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-first-run',
            '--no-zygote',
            '--disable-extensions',
            '--disable-background-networking',
            '--disable-default-apps',
            '--disable-sync',
        ],
    }
});

client.on('qr', async (qr) => {
    botEstado = 'esperando_qr';
    qrcode.generate(qr, { small: true });
    try {
        qrImageData = await QRCode.toDataURL(qr);
        console.log('QR generado — abre /qr en el navegador para escanearlo');
    } catch (e) {
        console.error('Error generando QR imagen:', e.message);
    }
});

client.on('authenticated', () => {
    botEstado = 'autenticado';
    qrImageData = null;
    console.log('Autenticado correctamente');
});

client.on('auth_failure', (msg) => {
    limpiarYSalir('Auth failure: ' + msg);
});

function limpiarYSalir(motivo) {
    console.error(`${motivo} — limpiando y saliendo para que Azure reinicie el contenedor...`);
    try { execSync('pkill -f chromium 2>/dev/null'); } catch(e) {}
    try { execSync(`rm -rf ${SESSION_DIR} 2>/dev/null`); } catch(e) {}
    setTimeout(() => process.exit(1), 2000);
}

process.on('unhandledRejection', (reason) => {
    const msg = String(reason);
    console.error('Error no manejado:', reason);
    if (msg.includes('auth timeout') || msg.includes('auth_timeout') ||
        msg.includes('protocolTimeout') || msg.includes('Protocol timeout') ||
        msg.includes('callFunctionOn timed out') || msg.includes('already running') ||
        msg.includes('Target closed')) {
        limpiarYSalir('Timeout/conflicto Chrome');
    }
});

client.on('ready', () => {
    botListo = true;
    botEstado = 'activo';
    qrImageData = null;
    console.log('AraBot listo y escuchando mensajes');
    console.log(`Backend: ${BACKEND}`);
});

// ── Procesar mensajes ─────────────────────────────────────────────────────────
client.on('message', async (message) => {
    if (message.from === 'status@broadcast') return;
    if (message.fromMe) return;
    if (message.from.includes('@g.us')) return;

    const esTexto    = message.type === 'chat';
    const esImagen   = message.type === 'image';
    const esAudio    = message.type === 'ptt' || message.type === 'audio';
    const esDocumento = message.type === 'document';
    if (!esTexto && !esImagen && !esAudio && !esDocumento) return;

    const phone = message.from.replace('@c.us', '');
    const contact = await message.getContact();
    const nombre = contact.pushname || contact.name || null;

    let payload = { phone, nombre };

    if (esImagen) {
        try {
            const media = await message.downloadMedia();
            if (media && media.data) {
                payload.message = '[foto_cedula]';
                payload.imagen_base64 = media.data;
                payload.imagen_mimetype = media.mimetype || 'image/jpeg';
                console.log(`[${phone}] ${nombre || ''}: [imagen recibida, ${Math.round(media.data.length * 0.75 / 1024)}KB]`);
            } else { return; }
        } catch (err) {
            console.error(`Error descargando imagen: ${err.message}`);
            await message.reply('No pude procesar la imagen. Por favor intentalo de nuevo.');
            return;
        }
    } else if (esAudio) {
        try {
            const media = await message.downloadMedia();
            if (media && media.data) {
                payload.message = '[audio]';
                payload.audio_base64 = media.data;
                payload.audio_mimetype = media.mimetype || 'audio/ogg';
                console.log(`[${phone}] ${nombre || ''}: [audio recibido]`);
            } else { return; }
        } catch (err) {
            console.error(`Error descargando audio: ${err.message}`);
            await message.reply('No pude procesar el audio. Por favor escribe tu respuesta.');
            return;
        }
    } else if (esDocumento) {
        try {
            const media = await message.downloadMedia();
            if (media && media.data) {
                payload.message = '[documento]';
                payload.documento_base64 = media.data;
                payload.documento_mimetype = media.mimetype || 'application/octet-stream';
                payload.documento_nombre = message.filename || 'documento';
                console.log(`[${phone}] ${nombre || ''}: [documento: ${message.filename || 'sin nombre'}]`);
            } else { return; }
        } catch (err) {
            console.error(`Error descargando documento: ${err.message}`);
            await message.reply('No pude procesar el documento. Por favor intenta de nuevo.');
            return;
        }
    } else {
        const texto = message.body.trim();
        if (!texto) return;
        payload.message = texto;
        console.log(`[${phone}] ${nombre || ''}: ${texto}`);
    }

    try {
        const resp = await axios.post(ENDPOINT, payload, { timeout: 45000 });
        const respuesta = resp.data?.response || 'Hubo un error. Intenta de nuevo.';
        console.log(`AraBot → [${phone}]: ${respuesta.substring(0, 80)}`);
        await message.reply(respuesta);
    } catch (err) {
        console.error(`Error llamando backend: ${err.message}`);
        await message.reply('Lo siento, tuve un problema tecnico. Por favor intenta en un momento.');
    }
});

client.on('disconnected', (reason) => {
    botListo = false;
    botEstado = 'desconectado';
    console.log('Desconectado:', reason);
});

const { execSync } = require('child_process');
try { execSync('find /home -name "SingletonLock" -delete 2>/dev/null'); } catch(e) {}
try { execSync('find /home -name "SingletonCookie" -delete 2>/dev/null'); } catch(e) {}
try { execSync('find /tmp -name ".org.chromium*" -delete 2>/dev/null'); } catch(e) {}

console.log('Iniciando AraBot...');
console.log('Chrome:', process.env.PUPPETEER_EXECUTABLE_PATH || 'auto');
client.initialize().catch((err) => {
    console.error('Error iniciando cliente WhatsApp:', err.message);
    limpiarYSalir('Error en initialize inicial');
});

