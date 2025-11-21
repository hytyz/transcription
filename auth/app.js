require('dotenv').config();
const fs = require('fs');
const crypto = require('crypto');
const express = require('express');
const sqlite3 = require('sqlite3').verbose();
const cookieParser = require('cookie-parser');
const bodyParser = require('body-parser');
// const path = require('path');

const app = express();
app.use(bodyParser.json());
app.use(cookieParser());

app.set('trust proxy', true); // need to try fly proxy for cookies

const PORT = process.env.PORT || 3000;
const DB_PATH = process.env.DB_PATH;
const PRIVATE_KEY_PATH = process.env.PRIVATE_KEY_PATH;
const PUBLIC_KEY_PATH = process.env.PUBLIC_KEY_PATH;
const JWT_EXP_SECONDS = parseInt(process.env.JWT_EXP_SECONDS, 10);
// const INTERNAL_TOKEN = process.env.INTERNAL_TOKEN;

const PRIVATE_KEY = fs.readFileSync(PRIVATE_KEY_PATH, 'utf8');
const PUBLIC_KEY = fs.readFileSync(PUBLIC_KEY_PATH, 'utf8');

async function seedSampleUsers() {
    const samples = [
        { email: "admin@admin.com", password: "111" },
        { email: "alice@example.com", password: "123" }
    ];

    for (const u of samples) {
        await new Promise(resolve => {
            db.get(`SELECT email FROM users WHERE email = ?`, [u.email], async (err, row) => {
                if (err) return resolve(); // skip if we error or the user already exists
                if (row) return resolve();

                const salt = genSalt();
                const hash = await hashPassword(u.password, salt);

                const stmt = db.prepare(
                    `INSERT INTO users(email, password_hash, salt, api_usage)
                     VALUES(?,?,?,0)`
                );

                stmt.run(u.email, hash, salt, err => {
                    if (!err) {
                        console.log(`Seeded sample user: ${u.email}`);
                    }
                    resolve();
                });

                stmt.finalize();
            });
        });
    }
}

const db = new sqlite3.Database(DB_PATH);
db.serialize(() => {
    db.run(`CREATE TABLE IF NOT EXISTS users (
    email TEXT PRIMARY KEY,
    password_hash TEXT NOT NULL,
    salt TEXT NOT NULL,
    api_usage INTEGER NOT NULL DEFAULT 0
  );`);

    // transcriptions table
    db.run(`CREATE TABLE IF NOT EXISTS transcriptions (
        jobid TEXT PRIMARY KEY,
        email TEXT NOT NULL,
        created_at INTEGER NOT NULL,
        filename TEXT,
        FOREIGN KEY(email) REFERENCES users(email) ON DELETE CASCADE
    );`);

    // look at this absolutely professional use of .then and .catch
    seedSampleUsers().then(() => {
        console.log("Sample users seeding complete.");
    }).catch(err => {
        console.error("Error seeding sample users:", err);
    });

});


function base64url(input) {
    return Buffer.from(input).toString('base64')
        .replace(/=/g, '')
        .replace(/\+/g, '-')
        .replace(/\//g, '_');
}

function base64urlFromBuffer(buf) { return buf.toString('base64').replace(/=/g, '').replace(/\+/g, '-').replace(/\//g, '_'); }

function base64urlDecodeToBuffer(str) {
    str = str.replace(/-/g, '+').replace(/_/g, '/');
    while (str.length % 4) str += '=';
    return Buffer.from(str, 'base64');
}

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
    const signer = crypto.createSign('RSA-SHA256');
    signer.update(signingInput);
    signer.end();
    const signature = signer.sign(PRIVATE_KEY);
    const sigB64 = base64urlFromBuffer(signature);
    return `${signingInput}.${sigB64}`;
}

function verifyJwt(token) {
    try {
        const parts = token.split('.');
        if (parts.length !== 3) throw new Error('invalid token structure');
        const [headerB64, payloadB64, sigB64] = parts;

        const signingInput = `${headerB64}.${payloadB64}`;
        const signature = base64urlDecodeToBuffer(sigB64);

        const verifier = crypto.createVerify('RSA-SHA256');
        verifier.update(signingInput);
        verifier.end();
        const ok = verifier.verify(PUBLIC_KEY, signature);
        if (!ok) throw new Error('signature verification failed');

        const payloadJson = Buffer.from(payloadB64.replace(/-/g, '+').replace(/_/g, '/'), 'base64').toString('utf8');
        const payload = JSON.parse(payloadJson);

        if (payload.exp && Math.floor(Date.now() / 1000) > payload.exp) throw new Error('token expired');

        return { valid: true, payload };
    } catch (err) {
        return { valid: false, error: err.message || String(err) };
    }
}

function genSalt(len = 16) { return crypto.randomBytes(len).toString('hex'); }

function hashPassword(password, salt, iterations = 100_000, keylen = 64, digest = 'sha512') {
    return new Promise((resolve, reject) => {
        crypto.pbkdf2(password, salt, iterations, keylen, digest, (err, derivedKey) => {
            if (err) return reject(err);
            resolve(derivedKey.toString('hex'));
        });
    });
}

// cors - allow all for now:
app.use((req, res, next) => {
    let requestOrigin = req.headers.origin || "*";
    res.setHeader("Access-Control-Allow-Origin", requestOrigin);
    res.setHeader("Access-Control-Allow-Methods", "GET,POST,PUT,DELETE,OPTIONS");
    res.setHeader("Access-Control-Allow-Headers", "Content-Type, Authorization, Cookie, Set-Cookie");
    res.setHeader("Access-Control-Allow-Credentials", "true");

    if (req.method === "OPTIONS") { return res.sendStatus(200); }
    next();
});

// // TODO deprecate
// function requireInternalToken(req, res, next) {
//     const token = req.header('x-internal-token') || req.query.token;
//     const responseMessage = 'Unauthorized (internal)' + INTERNAL_TOKEN;
//     if (!token || token !== INTERNAL_TOKEN) return res.status(401).json({ error: responseMessage });
//     next();
// }

// app.post('/create', async (req, res) => {
//     const { email, password } = req.body || {};
//     if (!email || !password) return res.status(400).json({ error: 'email and password required' });

//     const salt = genSalt();
//     let password_hash;
//     try { password_hash = await hashPassword(password, salt); } catch (err) {
//         return res.status(500).json({ error: 'hashing failure' });
//     }

//     const stmt = db.prepare('INSERT INTO users(email, password_hash, salt, api_usage) VALUES(?,?,?,0)');
//     stmt.run(email, password_hash, salt, function (err) {
//         if (err) {
//             if (err.message && err.message.includes('UNIQUE')) { return res.status(409).json({ error: 'user already exists' }); }
//             return res.status(500).json({ error: 'db error', details: err.message });
//         }
//         return res.status(201).json({ ok: true, email });
//     });
//     stmt.finalize();
// });

app.post('/create', async (req, res) => {
    const { email, password } = req.body || {};
    if (!email || !password) {return res.status(400).json({ error: 'email and password required' });}

    const salt = genSalt();
    let password_hash;
    try {password_hash = await hashPassword(password, salt);} 
    catch (err) {return res.status(500).json({ error: 'hashing failure' });}
    const stmt = db.prepare(
        'INSERT INTO users(email, password_hash, salt, api_usage) VALUES(?,?,?,0)'
    );
    stmt.run(email, password_hash, salt, function (err) {
        if (err) {
            if (err.message && err.message.includes('UNIQUE')) {return res.status(409).json({ error: 'user already exists' });}
            return res.status(500).json({ error: 'db error', details: err.message });
        }
        // ---- AUTO LOGIN HERE ----
        const token = signJwt({ email }, { expSeconds: JWT_EXP_SECONDS });

        res.cookie('token', token, {
            httpOnly: true,
            secure: process.env.COOKIE_SECURE === 'true',
            sameSite: 'none',
            maxAge: JWT_EXP_SECONDS * 1000,
            path: '/'
        });
        // return res.status(200).json({ ok: true, email, autoLogin: true });
        return res.json({ ok: true });

    });
    stmt.finalize();
});


app.post('/login', async (req, res) => {
    if (!req.is('application/json')) {
        return res.status(415).json({ error: 'content-type must be application/json' });
    }
    // console.log(req.body);
    const { email, password } = req.body; //|| {};
    // onsole.log(email, password);

    if (!email || !password) return res.status(400).json({ error: 'email and password required' });
    // console.log("got to the third console log");

    db.get('SELECT email, password_hash, salt FROM users WHERE email = ?', [email], async (err, row) => {
        if (err) return res.status(500).json({ error: 'db error' });
        if (!row) return res.status(401).json({ error: 'invalid credentials' });

        let computed;
        try { computed = await hashPassword(password, row.salt); } catch (e) {
            return res.status(500).json({ error: 'hashing failure' });
        }
        const match = crypto.timingSafeEqual(Buffer.from(computed, 'hex'), Buffer.from(row.password_hash, 'hex'));
        if (!match) return res.status(401).json({ error: 'invalid credentials' });

        const token = signJwt({ email }, { expSeconds: JWT_EXP_SECONDS });

        res.cookie('token', token, {
            httpOnly: true,
            secure: process.env.COOKIE_SECURE === 'true',
            sameSite: 'none', // default in chrome is now lax
            maxAge: JWT_EXP_SECONDS * 1000,
            path: '/'
        });

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

    return res.json({ ok: true });
});

app.get('/me', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) return res.status(401).json({ error: 'no token' });
    const validity = verifyJwt(token);
    if (!validity.valid) return res.status(401).json({ error: 'invalid token', details: validity.error });
    return res.json({ payload: validity.payload });
});

app.post('/increment', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) return res.status(401).json({ error: 'no token' });
    const validity = verifyJwt(token);
    if (!validity.valid) return res.status(401).json({ error: 'invalid token', details: validity.error });
    const email = validity.payload.email;
    if (!email) return res.status(400).json({ error: 'email required' });

    const stmt = db.prepare('UPDATE users SET api_usage = api_usage + 1 WHERE email = ?');
    stmt.run(email, function (err) {
        if (err) return res.status(500).json({ error: 'db error' });
        if (this.changes === 0) return res.status(404).json({ error: 'user not found' });
        return res.json({ ok: true, email });
    });
    stmt.finalize();
});

app.get('/usage', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) return res.status(401).json({ error: 'no token' });
    const validity = verifyJwt(token);
    if (!validity.valid) return res.status(401).json({ error: 'invalid token', details: validity.error });
    
    // check if user is admin@admin.com
    if (validity.payload.email !== 'admin@admin.com') {
        return res.status(403).json({ error: 'forbidden' });
    }
    
    db.all('SELECT email, api_usage FROM users ORDER BY email', [], (err, rows) => {
        if (err) return res.status(500).json({ error: 'db error' });
        return res.json({ users: rows });
    });
});

app.get('/myusage', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) return res.status(401).json({ error: 'no token' });
    const validity = verifyJwt(token);
    if (!validity.valid) return res.status(401).json({ error: 'invalid token', details: validity.error });
    const email = validity.payload.email;

    db.get('SELECT api_usage FROM users WHERE email = ?', [email], (err, row) => {
        if (err) return res.status(500).json({ error: 'db error' });
        if (!row) return res.status(404).json({ error: 'user not found' });
        return res.json({ email, usage: row.api_usage });
    });
});

app.post('/transcriptions/add', (req, res) => {
    const { email, jobid, filename } = req.body || {};
    if (!email || !jobid || !filename) {
        return res.status(400).json({ error: "email, jobid, and filename required" });
    }

    const createdAt = Math.floor(Date.now() / 1000);

    db.serialize(() => {
        //insert transcription record
        const stmt1 = db.prepare(
            'INSERT INTO transcriptions(jobid, email, created_at, filename) VALUES(?,?,?,?)'
        );
        stmt1.run(jobid, email, createdAt, filename, function (err) {
            if (err) {
                if (err.message.includes('UNIQUE')) {
                    return res.status(409).json({ error: 'jobid already exists' });
                }
                return res.status(500).json({ error: 'db error', details: err.message });
            }

            //increment usage when a new transcription is added
            const stmt2 = db.prepare(
                'UPDATE users SET api_usage = api_usage + 1 WHERE email = ?'
            );
            stmt2.run(email, function (err) {
                if (err) {
                    return res.status(500).json({ error: 'db error (usage increment)' });
                }

                if (this.changes === 0) {
                    return res.status(404).json({ error: 'user not found' });
                }

                return res.status(201).json({
                    ok: true,
                    jobid,
                    email,
                    incremented: true
                });
            });
            stmt2.finalize();
        });
        stmt1.finalize();
    });
});

app.delete('/transcriptions/delete', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) return res.status(401).json({ error: 'no token' });
    const validity = verifyJwt(token);
    if (!validity.valid) return res.status(401).json({ error: 'invalid token', details: validity.error });
    const email = validity.payload.email;

    const { jobid } = req.body || {};
    if (!jobid) return res.status(400).json({ error: 'jobid required' });

    const stmt = db.prepare('DELETE FROM transcriptions WHERE jobid = ? AND email = ?');
    stmt.run(jobid, email, function (err) {
      if (err) return res.status(500).json({ error: 'db error' });
      if (this.changes === 0) return res.status(404).json({ error: 'transcription not found' });
      return res.json({ ok: true, jobid });
    });
    stmt.finalize();
});


app.get('/transcriptions/', (req, res) => {
    const token = req.cookies.token || req.header('authorization')?.replace('Bearer ', '');
    if (!token) return res.status(401).json({ error: 'no token' });
    const validity = verifyJwt(token);
    if (!validity.valid) return res.status(401).json({ error: 'invalid token', details: validity.error });
    const email = validity.payload.email;

    db.all(
        'SELECT jobid, created_at, filename FROM transcriptions WHERE email = ? ORDER BY created_at DESC',
        [email],
        (err, rows) => {
            if (err) return res.status(500).json({ error: 'db error' });
            return res.json({ email, transcriptions: rows });
        }
    );
});


app.get('/health', (req, res) => res.json({ ok: true })); // deprecate when fully self hosted

app.listen(PORT, host = '0.0.0.0', () => { console.log(`auth service running on port ${PORT}`); });

