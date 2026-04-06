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

app.listen(PORT, () => {
    console.log(`Servidor web en puerto ${PORT}`);
    console.log(`QR disponible en: http://localhost:${PORT}/qr`);
});

// ── Cliente WhatsApp ──────────────────────────────────────────────────────────
const client = new Client({
    authStrategy: new LocalAuth({ clientId: 'arabot', dataPath: SESSION_DIR }),
    puppeteer: {
        headless: true,
        executablePath: process.env.CHROMIUM_PATH || '/usr/bin/chromium',
        args: [
            '--no-sandbox',
            '--disable-setuid-sandbox',
            '--disable-dev-shm-usage',
            '--disable-gpu',
            '--no-first-run',
            '--no-zygote',
            '--single-process',
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
    botEstado = 'error_auth';
    console.error('Error de autenticacion:', msg);
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
    if (message.type !== 'chat') return;

    const phone = message.from.replace('@c.us', '');
    const texto = message.body.trim();

    console.log(`[${phone}]: ${texto}`);

    try {
        const resp = await axios.post(ENDPOINT, { phone, message: texto }, { timeout: 30000 });
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

console.log('Iniciando AraBot...');
client.initialize();
