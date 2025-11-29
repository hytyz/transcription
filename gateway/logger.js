const LOG_LEVEL = process.env.LOG_LEVEL || 'info';
const LEVELS = { debug: 0, info: 1, warn: 2, error: 3 };
const currentLevel = LEVELS[LOG_LEVEL] ?? LEVELS.info;

function shouldLog(level) {
    return LEVELS[level] >= currentLevel;
}

function formatLog(level, message, meta = {}) {
    return JSON.stringify({
        timestamp: new Date().toISOString(),
        level,
        service: 'gateway',
        message,
        ...meta
    });
}

export const logger = {
    debug(message, meta) {
        if (shouldLog('debug')) console.log(formatLog('debug', message, meta));
    },
    info(message, meta) {
        if (shouldLog('info')) console.log(formatLog('info', message, meta));
    },
    warn(message, meta) {
        if (shouldLog('warn')) console.warn(formatLog('warn', message, meta));
    },
    error(message, meta) {
        if (shouldLog('error')) console.error(formatLog('error', message, meta));
    },
    
    /**
     * log incoming request
     */
    request(req, prefix) {
        if (shouldLog('info')) {
            console.log(formatLog('info', 'incoming request', {
                method: req.method,
                path: req.path,
                prefix,
                ip: req.ip || req.connection?.remoteAddress,
                userAgent: req.get('user-agent')
            }));
        }
    },
    
    /**
     * log proxy event
     */
    proxy(prefix, target, path, durationMs) {
        if (shouldLog('info')) {
            console.log(formatLog('info', 'proxy request', {
                prefix,
                target,
                path,
                durationMs
            }));
        }
    },
    
    /**
     * log proxy error
     */
    proxyError(prefix, target, error) {
        console.error(formatLog('error', 'proxy error', {
            prefix,
            target,
            error: error.message || String(error),
            code: error.code
        }));
    },
    
    /**
     * log ws upgrade
     */
    wsUpgrade(prefix, target, path) {
        if (shouldLog('info')) {
            console.log(formatLog('info', 'websocket upgrade', {
                prefix,
                target,
                path
            }));
        }
    }
};
