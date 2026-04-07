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

app.listen(PORT, () => {
    console.log(`Servidor web en puerto ${PORT}`);
    console.log(`QR disponible en: http://localhost:${PORT}/qr`);
});

// ── Cliente WhatsApp ──────────────────────────────────────────────────────────
const client = new Client({
    authStrategy: new LocalAuth({ clientId: 'arabot', dataPath: SESSION_DIR }),
    puppeteer: {
        headless: true,
        executablePath: process.env.PUPPETEER_EXECUTABLE_PATH || undefined,
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
    botEstado = 'esperando_qr';
    console.error('Error de autenticacion:', msg, '— reiniciando...');
    setTimeout(() => client.initialize(), 5000);
});

process.on('unhandledRejection', (reason) => {
    console.error('Error no manejado:', reason);
    if (String(reason).includes('auth timeout') || String(reason).includes('auth_timeout')) {
        botEstado = 'esperando_qr';
        console.log('Auth timeout — reiniciando cliente en 5s...');
        setTimeout(() => client.initialize(), 5000);
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

    const esTexto = message.type === 'chat';
    const esImagen = message.type === 'image';
    if (!esTexto && !esImagen) return;

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
            } else {
                return;
            }
        } catch (err) {
            console.error(`Error descargando imagen: ${err.message}`);
            await message.reply('No pude procesar la imagen. Por favor intentalo de nuevo.');
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

console.log('Iniciando AraBot...');
console.log('Chrome:', process.env.PUPPETEER_EXECUTABLE_PATH || 'auto');
client.initialize().catch((err) => {
    console.error('Error iniciando cliente WhatsApp:', err.message);
    console.log('Reintentando en 10s...');
    setTimeout(() => client.initialize().catch(e => console.error('Reintento fallido:', e.message)), 10000);
});

