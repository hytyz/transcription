import 'dotenv/config';
import { readFileSync } from 'fs';
import { createSign, createVerify, randomBytes, pbkdf2, timingSafeEqual } from 'crypto';
import express from 'express';
const sqlite3 = require('sqlite3').verbose();
import cookieParser from 'cookie-parser';
import { json } from 'body-parser';
import { createLogger } from './logger.js';

const logger = createLogger('auth');

const app = express();
app.use(json());
app.use(cookieParser());

app.set('trust proxy', true); // need to try fly proxy for cookies

const PORT = process.env.PORT || 3000;
const DB_PATH = process.env.DB_PATH;
const PRIVATE_KEY_PATH = process.env.PRIVATE_KEY_PATH;
const PUBLIC_KEY_PATH = process.env.PUBLIC_KEY_PATH;
const JWT_EXP_SECONDS = parseInt(process.env.JWT_EXP_SECONDS, 10);

logger.info('loading rsa keys', { privatePath: PRIVATE_KEY_PATH, publicPath: PUBLIC_KEY_PATH });
const PRIVATE_KEY = readFileSync(PRIVATE_KEY_PATH, 'utf8');
const PUBLIC_KEY = readFileSync(PUBLIC_KEY_PATH, 'utf8');
logger.info('rsa keys loaded successfully');

/**
 * seeds some test accounts if they're not already present
 * reads from SEED_USERS env var (format: "email:password,email:password")
 * then checks for each sample email and derives a password hash with a salt
 * then inserts the user row. errors are swallowed per user
 */
async function seedSampleUsers() {
    const seedUsersEnv = process.env.SEED_USERS || '';
    const samples = seedUsersEnv
        .split(',')
        .map(pair => pair.trim())
        .filter(pair => pair.includes(':'))
        .map(pair => {
            const [email, password] = pair.split(':');
            return { email: email.trim(), password: password.trim() };
        });

    if (samples.length === 0) {
        logger.info('no seed users configured');
        return;
    }

    logger.info('seeding sample users', { count: samples.length });

    for (const u of samples) {
        await new Promise(resolve => {
            db.get(`SELECT email FROM users WHERE email = ?`, [u.email], async (err, row) => {
                if (err) {
                    logger.error('error checking if user exists', { email: u.email, error: err.message });
                    return resolve();
                }
                if (row) {
                    logger.debug('seed user already exists', { email: u.email });
                    return resolve();
                }

                const salt = genSalt();
                const hash = await hashPassword(u.password, salt);

                const stmt = db.prepare(
                    `INSERT INTO users(email, password_hash, salt, api_usage)
                     VALUES(?,?,?,0)`
                );

                stmt.run(u.email, hash, salt, err => {
                    if (err) {
                        logger.error('error seeding user', { email: u.email, error: err.message });
                    } else {
                        logger.info('seeded sample user', { email: u.email });
                    }
                    resolve();
                });

                stmt.finalize();
            });
        });
    }
}

const db = new sqlite3.Database(DB_PATH);
logger.info('database connection opened', { path: DB_PATH });

db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    api_usage INTEGER NOT NULL DEFAULT 0
  );`);
    logger.db('ensured users table exists');

    // transcriptions table
    db.run(`CREATE TABLE IF NOT EXISTS transcriptions (
        jobid TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        filename TEXT,
        FOREIGN KEY(email) REFERENCES users(email) ON DELETE CASCADE
    );`);
    logger.db('ensured transcriptions table exists');

    // look at this absolutely professional use of .then and .catch
    seedSampleUsers().then(() => {
        logger.info("sample users seeding complete");
    }).catch(err => {
        logger.error("error seeding sample users", { error: err.message });
    });

});

/**
 * base64-url encodes a utf8 string without padding
 * this is used for jwt header and payload
 * @param {string} input 
 * @returns {string}
 */
function base64url(input) {
    return Buffer.from(input).toString('base64')
        .replace(/=/g, '')
        .replace(/\+/g, '-')
        .replace(/\//g, '_');
}

/** same as above but encodes a node.js buffer */
function base64urlFromBuffer(buf) { return buf.toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_'); }

/**
 * decodes a base64 url back to a buffer, adds padding if necessary
 * @param {string} str 
 * @returns {Buffer}
 */
function base64urlDecodeToBuffer(str) {
    str = str.replace(/-/g, '+').replace(/_/g, '/');
    while (str.length % 4) str += '=';
    return Buffer.from(str, 'base64');
}

/**
 * creates a jwt signed with rs256
 * builds a protected header, merges claims like iat and exp
 * and signs header.payload with the rsa private key
 * @param {object} payloadObj jwt claims 
 * @param {{kid?: string, expSeconds?: number}} opts 
 * @returns {string} a jwt
 */
function signJwt(payloadObj, opts = {}) {
    const header = { alg: 'RS256', typ: 'JWT' };
    if (opts.kid) header.kid = opts.kid;

    const headerB64 = base64url(JSON.stringify(header));
    const now = Math.floor(Date.now() / 1000);
    const payload = Object.assign({}, payloadObj);
    if (!payload.iat) payload.iat = now;
    if (opts.expSeconds) payload.exp = now + opts.expSeconds;
    const payloadB64 = base64url(JSON.stringify(payload));

    const signingInput = `${headerB64}.${payloadB64}`;
    const signer = createSign('RSA-SHA256');
    signer.update(signingInput);
    signer.end();
    const signature = signer.sign(PRIVATE_KEY);
    const sigB64 = base64urlFromBuffer(signature);
    return `${signingInput}.${sigB64}`;
}

/**
 * verifies an rs256 jwt and returns either the parsed payload or an error
 * verifies structure, signature, and exp claim
 * @param {string} token 
 * @returns {{valid: try, payload: any} | {valid: false, error: string}}
 */
function verifyJwt(token) {
    try {
        const parts = token.split('.');
        if (parts.length !== 3) throw new Error('invalid token structure');
        const [headerB64, payloadB64, sigB64] = parts;

        const signingInput = `${headerB64}.${payloadB64}`;
        const signature = base64urlDecodeToBuffer(sigB64);

        const verifier = createVerify('RSA-SHA256');
        verifier.update(signingInput);
        verifier.end();
        const ok = verifier.verify(PUBLIC_KEY, signature);
        if (!ok) throw new Error('signature verification failed');

        const payloadJson = Buffer.from(payloadB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
        const payload = JSON.parse(payloadJson);

        if (payload.exp && Math.floor(Date.now() / 1000) > payload.exp) throw new Error('token expired');

        return { valid: true, payload };
    } catch (err) { return { valid: false, error: err.message || String(err) }; }
}

/** generates a random hex salt */
function genSalt(len = 16) { return randomBytes(len).toString('hex'); }

/**
 * derives a password hash using pbkdf2 with the passed in salt
 * @param {string} password 
 * @param {string} salt 
 * @param {number} iterations 
 * @param {number} keylen 
 * @param {string} digest 
 * @returns {Promise<string>} hex encoded derived key
 */
function hashPassword(password, salt, iterations = 100_000, keylen = 64, digest = 'sha512') {
    return new Promise((resolve, reject) => {
        pbkdf2(password, salt, iterations, keylen, digest, (err, derivedKey) => {
            if (err) return reject(err);
            resolve(derivedKey.toString('hex'));
        });
    });
}

// cors from env
const ALLOWED_ORIGINS = (process.env.CORS_ORIGINS || '')
    .split(',')
    .map(o => o.trim())
    .filter(Boolean);

app.use((req, res, next) => {
    const origin = req.headers.origin;

    if (origin && ALLOWED_ORIGINS.includes(origin)) {
        res.setHeader("Access-Control-Allow-Origin", origin);
        res.setHeader("Access-Control-Allow-Credentials", "true");
    }
    
    res.setHeader("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Cookie, Set-Cookie");
    res.setHeader("Vary", "Origin");

    if (req.method === "OPTIONS") { return res.sendStatus(200); }
    next();
});


/**
 * validates email format
 * @param {string} email
 * @returns {boolean}
 */
function isValidEmail(email) {
    const emailRegex = /^[^\s@]+@[^\s@]+\.[^\s@]+$/;
    return emailRegex.test(email);
}

/**
 * validates password strength
 * requires: min 8 chars
 * @param {string} password
 * @returns {{valid: boolean, reason?: string}}
 */
function validatePassword(password) {
    if (password.length < 8) {
        return { valid: false, reason: 'password must be at least 8 characters' };
    }
    return { valid: true };
}

import rateLimit from 'express-rate-limit';
const authLimiter = rateLimit({
    windowMs: 15 * 60 * 1000, // 15 minutes
    max: 5,
    message: { error: 'too many attempts, please try again later' }
});

/**
 * csrf middleware with custom header verification
 * afaik browsers prevent cross-origin js from setting custom headers,
 * so requiring x-requested-with would prove request came from my frontend
 * this only applies to POST, PUT, and DELETE
 */
function csrfProtection(req, res, next) {
    const safeMethods = ['GET', 'HEAD', 'OPTIONS'];
    if (safeMethods.includes(req.method)) {
        return next();
    }
    
    if (req.header('X-API-Key')) {
        return next();
    }
    
    const xRequestedWith = req.header('X-Requested-With');
    if (xRequestedWith !== 'XMLHttpRequest') {
        return res.status(403).json({ error: 'csrf validation failed: missing x-requested-with header' });
    }
    
    next();
}

app.use(csrfProtection);

app.use((req, res, next) => {
    req.startTime = Date.now();
    logger.request(req);
    
    res.on('finish', () => {
        const duration = Date.now() - req.startTime;
        logger.response(req, res.statusCode, duration);
    });
    
    next();
});

app.post('/create', authLimiter, async (req, res) => {
    const { email, password } = req.body || {};
    if (!email || !password) { 
        logger.warn('registration failed: missing credentials');
        return res.status(400).json({ error: 'email and password required' }); 
    }

    if (!isValidEmail(email)) {
        logger.warn('registration failed: invalid email', { email });
        return res.status(400).json({ error: 'invalid email format' });
    }

    const passwordCheck = validatePassword(password);
    if (!passwordCheck.valid) {
        logger.warn('registration failed: weak password', { email });
        return res.status(400).json({ error: passwordCheck.reason });
    }

    const salt = genSalt();
    let password_hash;
    try { password_hash = await hashPassword(password, salt); }
    catch (err) { 
        logger.error('registration failed: hashing error', { email, error: err.message });
        return res.status(500).json({ error: 'hashing failure' }); 
    }
    
    db.run(
        'INSERT INTO users(email, password_hash, salt, api_usage) VALUES(?,?,?,0)',
        [email, password_hash, salt],
        function (err) {
            if (err) {
                if (err.message && err.message.includes('UNIQUE')) { 
                    logger.warn('registration failed: user exists', { email });
                    return res.status(409).json({ error: 'user already exists' }); 
                }
                logger.error('registration failed: db error', { email, error: err.message });
                return res.status(500).json({ error: 'db error', details: err.message });
            }
            const token = signJwt({ email }, { expSeconds: JWT_EXP_SECONDS });

            res.cookie('token', token, {
                httpOnly: true,
                secure: process.env.COOKIE_SECURE === 'true',
                sameSite: 'none',
                maxAge: JWT_EXP_SECONDS * 1000,
                path: '/'
            });
            logger.auth('user registered', email);
            return res.json({ ok: true });
        }
    );
});

app.post('/login', authLimiter, async (req, res) => {
    if (!req.is('application/json')) {
        logger.warn('login failed: wrong content-type', { contentType: req.get('content-type') });
        return res.status(415).json({ error: 'content-type must be application/json' });
    }

    const { email, password } = req.body;

    if (!email || !password) {
        logger.warn('login failed: missing credentials');
        return res.status(400).json({ error: 'email and password required' });
    }

    db.get('SELECT email, password_hash, salt FROM users WHERE email = ?', [email], async (err, row) => {
        if (err) {
            logger.error('login failed: db error', { email, error: err.message });
            return res.status(500).json({ error: 'db error' });
        }
        if (!row) {
            logger.warn('login failed: user not found', { email });
            return res.status(401).json({ error: 'invalid credentials' });
        }

        let computed;
        try { computed = await hashPassword(password, row.salt); } catch (e) {
            logger.error('login failed: hashing error', { email, error: e.message });
            return res.status(500).json({ error: 'hashing failure' });
        }
        // constant-time comparison to avoid timing side channels on invalid credentials
        const match = timingSafeEqual(Buffer.from(computed, 'hex'), Buffer.from(row.password_hash, 'hex'));
        if (!match) {
            logger.warn('login failed: invalid password', { email });
            return res.status(401).json({ error: 'invalid credentials' });
        }

        const token = signJwt({ email }, { expSeconds: JWT_EXP_SECONDS });

        res.cookie('token', token, {
            httpOnly: true,
            secure: process.env.COOKIE_SECURE === 'true',
            sameSite: 'none', // default in chrome is now lax
            maxAge: JWT_EXP_SECONDS * 1000,
            path: '/'
        });
        logger.auth('user logged in', email);
        return res.json({ ok: true });
    });
});

app.post('/logout', (req, res) => {
    res.clearCookie('token', {
        httpOnly: true,
        secure: process.env.COOKIE_SECURE === 'true',
        sameSite: 'none',
        path: '/'
    });
    logger.auth('user logged out');
    return res.json({ ok: true });
});

app.get('/me', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) {
        logger.warn('auth check failed: no token');
        return res.status(401).json({ error: 'no token' });
    }
    const validity = verifyJwt(token);
    if (!validity.valid) {
        logger.warn('auth check failed: invalid token', { error: validity.error });
        return res.status(401).json({ error: 'invalid token', details: validity.error });
    }
    return res.json({ payload: validity.payload });
});

app.post('/increment', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) {
        logger.warn('increment failed: no token');
        return res.status(401).json({ error: 'no token' });
    }
    const validity = verifyJwt(token);
    if (!validity.valid) {
        logger.warn('increment failed: invalid token', { error: validity.error });
        return res.status(401).json({ error: 'invalid token', details: validity.error });
    }
    const email = validity.payload.email;
    if (!email) {
        logger.warn('increment failed: no email in token');
        return res.status(400).json({ error: 'email required' });
    }

    db.run(
        'UPDATE users SET api_usage = api_usage + 1 WHERE email = ?',
        [email],
        function (err) {
            if (err) {
                logger.error('increment failed: db error', { email, error: err.message });
                return res.status(500).json({ error: 'db error' });
            }
            if (this.changes === 0) {
                logger.warn('increment failed: user not found', { email });
                return res.status(404).json({ error: 'user not found' });
            }
            logger.db('api usage incremented', { email });
            return res.json({ ok: true, email });
        }
    );
});

app.get('/usage', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) {
        logger.warn('usage check failed: no token');
        return res.status(401).json({ error: 'no token' });
    }
    const validity = verifyJwt(token);
    if (!validity.valid) {
        logger.warn('usage check failed: invalid token', { error: validity.error });
        return res.status(401).json({ error: 'invalid token', details: validity.error });
    }

    const adminEmail = process.env.ADMIN_EMAIL;
    if (!adminEmail || validity.payload.email !== adminEmail) {
        logger.warn('usage check failed: forbidden', { email: validity.payload.email });
        return res.status(403).json({ error: 'forbidden' });
    }

    db.all('SELECT email, api_usage FROM users ORDER BY email', [], (err, rows) => {
        if (err) {
            logger.error('usage check failed: db error', { error: err.message });
            return res.status(500).json({ error: 'db error' });
        }
        logger.db('admin usage query', { rowCount: rows.length });
        return res.json({ users: rows });
    });
});

app.get('/myusage', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) {
        logger.warn('myusage check failed: no token');
        return res.status(401).json({ error: 'no token' });
    }
    const validity = verifyJwt(token);
    if (!validity.valid) {
        logger.warn('myusage check failed: invalid token', { error: validity.error });
        return res.status(401).json({ error: 'invalid token', details: validity.error });
    }
    const email = validity.payload.email;

    db.get('SELECT api_usage FROM users WHERE email = ?', [email], (err, row) => {
        if (err) {
            logger.error('myusage check failed: db error', { email, error: err.message });
            return res.status(500).json({ error: 'db error' });
        }
        if (!row) {
            logger.warn('myusage check failed: user not found', { email });
            return res.status(404).json({ error: 'user not found' });
        }
        return res.json({ email, usage: row.api_usage });
    });
});

app.post('/transcriptions/add', (req, res) => {
    const apiKey = req.header('X-API-Key');
    const expectedApiKey = process.env.INTERNAL_TOKEN;
    
    if (!expectedApiKey) {
        logger.error('transcription add failed: INTERNAL_TOKEN not configured');
        return res.status(500).json({ error: 'server misconfiguration' });
    }
    
    if (!apiKey || apiKey !== expectedApiKey) {
        logger.warn('transcription add failed: invalid api key');
        return res.status(401).json({ error: 'unauthorized: invalid or missing API key' });
    }

    const { email, jobid, filename } = req.body || {};
    if (!email || !jobid || !filename) {
        logger.warn('transcription add failed: missing fields', { email, jobid, filename: !!filename });
        return res.status(400).json({ error: "email, jobid, and filename required" });
    }

    const createdAt = Math.floor(Date.now() / 1000);

    db.run(
        'INSERT INTO transcriptions(jobid, email, created_at, filename) VALUES(?,?,?,?)',
        [jobid, email, createdAt, filename],
        function (err) {
            if (err) {
                if (err.message.includes('UNIQUE')) {
                    logger.warn('transcription add failed: duplicate jobid', { jobid, email });
                    return res.status(409).json({ error: 'jobid already exists' });
                }
                logger.error('transcription add failed: db error', { jobid, email, error: err.message });
                return res.status(500).json({ error: 'db error', details: err.message });
            }

            db.run(
                'UPDATE users SET api_usage = api_usage + 1 WHERE email = ?',
                [email],
                function (err) {
                    if (err) {
                        logger.error('transcription add: usage increment failed', { email, error: err.message });
                        return res.status(500).json({ error: 'db error (usage increment)' });
                    }

                    if (this.changes === 0) {
                        logger.warn('transcription add: user not found for increment', { email });
                        return res.status(404).json({ error: 'user not found' });
                    }

                    logger.db('transcription added', { jobid, email, filename });
                    return res.status(201).json({
                        ok: true,
                        jobid,
                        email,
                        incremented: true
                    });
                }
            );
        }
    );
});

app.delete('/transcriptions/delete', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) {
        logger.warn('transcription delete failed: no token');
        return res.status(401).json({ error: 'no token' });
    }
    const validity = verifyJwt(token);
    if (!validity.valid) {
        logger.warn('transcription delete failed: invalid token', { error: validity.error });
        return res.status(401).json({ error: 'invalid token', details: validity.error });
    }
    const email = validity.payload.email;

    const { jobid } = req.body || {};
    if (!jobid) {
        logger.warn('transcription delete failed: missing jobid', { email });
        return res.status(400).json({ error: 'jobid required' });
    }

    db.run(
        'DELETE FROM transcriptions WHERE jobid = ? AND email = ?',
        [jobid, email],
        function (err) {
            if (err) {
                logger.error('transcription delete failed: db error', { jobid, email, error: err.message });
                return res.status(500).json({ error: 'db error' });
            }
            if (this.changes === 0) {
                logger.warn('transcription delete failed: not found', { jobid, email });
                return res.status(404).json({ error: 'transcription not found' });
            }
            logger.db('transcription deleted', { jobid, email });
            return res.json({ ok: true, jobid });
        }
    );
});

app.put('/transcriptions/rename', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) {
        logger.warn('transcription rename failed: no token');
        return res.status(401).json({ error: 'no token' });
    }
    const validity = verifyJwt(token);
    if (!validity.valid) {
        logger.warn('transcription rename failed: invalid token', { error: validity.error });
        return res.status(401).json({ error: 'invalid token', details: validity.error });
    }
    const email = validity.payload.email;

    const { jobid, filename } = req.body || {};
    if (!jobid || !filename) {
        logger.warn('transcription rename failed: missing fields', { email, jobid: !!jobid, filename: !!filename });
        return res.status(400).json({ error: 'jobid and filename required' });
    }

    db.run(
        'UPDATE transcriptions SET filename = ? WHERE jobid = ? AND email = ?',
        [filename, jobid, email],
        function (err) {
            if (err) {
                logger.error('transcription rename failed: db error', { jobid, email, error: err.message });
                return res.status(500).json({ error: 'db error' });
            }
            if (this.changes === 0) {
                logger.warn('transcription rename failed: not found', { jobid, email });
                return res.status(404).json({ error: 'transcription not found' });
            }
            logger.db('transcription renamed', { jobid, email, filename });
            return res.json({ ok: true, jobid, filename });
        }
    );
});


app.get('/transcriptions/', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) {
        logger.warn('transcriptions list failed: no token');
        return res.status(401).json({ error: 'no token' });
    }
    const validity = verifyJwt(token);
    if (!validity.valid) {
        logger.warn('transcriptions list failed: invalid token', { error: validity.error });
        return res.status(401).json({ error: 'invalid token', details: validity.error });
    }
    const email = validity.payload.email;

    db.all(
        'SELECT jobid, created_at, filename FROM transcriptions WHERE email = ? ORDER BY created_at DESC',
        [email],
        (err, rows) => {
            if (err) {
                logger.error('transcriptions list failed: db error', { email, error: err.message });
                return res.status(500).json({ error: 'db error' });
            }
            logger.db('transcriptions listed', { email, count: rows.length });
            return res.json({ email, transcriptions: rows });
        }
    );
});


app.get('/health', (req, res) => res.json({ ok: true }));

const server = app.listen(PORT, host = '0.0.0.0', () => { 
    logger.info('auth service started', { port: PORT, host: '0.0.0.0' });
});

function shutdown(signal) {
    logger.info('shutdown initiated', { signal });
    server.close(() => {
        db.close((err) => {
            if (err) {
                logger.error('error closing database', { error: err.message });
            } else {
                logger.info('database connection closed');
            }
            process.exit(0);
        });
    });
}

process.on('SIGINT', () => shutdown('SIGINT'));
process.on('SIGTERM', () => shutdown('SIGTERM'));
