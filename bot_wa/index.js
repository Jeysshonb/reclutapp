/**
 * AraBot — WhatsApp Web bot para reclutamiento Tiendas Ara
 * Conecta con whatsapp-web.js (QR) y pasa mensajes al backend Python
 */

const { Client, LocalAuth } = require('whatsapp-web.js');
const qrcode = require('qrcode-terminal');
const axios = require('axios');
const puppeteer = require('puppeteer');
const path = require('path');
const os = require('os');

// URL del backend Python (local o Azure)
const BACKEND = process.env.BACKEND_URL || 'https://reclutapp-prod-dkhggmfdgrckdkeq.westeurope-01.azurewebsites.net';
const ENDPOINT = `${BACKEND}/api/webhook/whatsapp/json`;

// ── Cliente WhatsApp ──────────────────────────────────────────────────────────
// Sesión fuera de OneDrive para evitar bloqueos
const SESSION_DIR = path.join(os.homedir(), '.arabot_session');

const client = new Client({
    authStrategy: new LocalAuth({ clientId: 'arabot', dataPath: SESSION_DIR }),
    puppeteer: {
        headless: true,
        executablePath: puppeteer.executablePath(),
        args: ['--no-sandbox', '--disable-setuid-sandbox', '--disable-dev-shm-usage'],
    }
});

// ── QR Code ───────────────────────────────────────────────────────────────────
client.on('qr', (qr) => {
    console.log('\n======================================');
    console.log('  Escanea este QR con WhatsApp:');
    console.log('======================================\n');
    qrcode.generate(qr, { small: true });
    console.log('\nAbre WhatsApp > Dispositivos vinculados > Vincular dispositivo\n');
});

client.on('authenticated', () => {
    console.log('✅ Autenticado correctamente');
});

client.on('auth_failure', (msg) => {
    console.error('❌ Error de autenticacion:', msg);
});

client.on('ready', () => {
    console.log('🚀 AraBot listo y escuchando mensajes...');
    console.log(`   Backend: ${BACKEND}`);
});

// ── Procesar mensajes entrantes ───────────────────────────────────────────────
client.on('message', async (message) => {
    // Ignorar mensajes de grupos, estados y del bot mismo
    if (message.from === 'status@broadcast') return;
    if (message.fromMe) return;
    if (message.from.includes('@g.us')) return;  // grupos
    if (message.type !== 'chat') return;          // solo texto

    const phone = message.from.replace('@c.us', ''); // ej: 573133828176
    const texto = message.body.trim();

    console.log(`📩 [${phone}]: ${texto}`);

    try {
        const resp = await axios.post(ENDPOINT, {
            phone: phone,
            message: texto,
        }, { timeout: 30000 });

        const respuesta = resp.data?.response || 'Hubo un error. Intenta de nuevo.';
        console.log(`🤖 AraBot → [${phone}]: ${respuesta.substring(0, 80)}...`);

        await message.reply(respuesta);

    } catch (err) {
        console.error(`❌ Error llamando al backend: ${err.message}`);
        await message.reply('Lo siento, tuve un problema técnico. Por favor intenta en un momento.');
    }
});

client.on('disconnected', (reason) => {
    console.log('⚠️  Desconectado:', reason);
    console.log('   Reinicia con: npm start');
});

// ── Iniciar ───────────────────────────────────────────────────────────────────
console.log('Iniciando AraBot...');
client.initialize();
