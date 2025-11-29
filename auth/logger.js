/**
 * Structured logger for Node.js services.
 * Outputs JSON logs for easy parsing by log aggregators.
 */

/**
 * @typedef {'debug' | 'info' | 'warn' | 'error'} LogLevel
 */

/**
 * Creates a structured logger for a service
 * @param {string} serviceName - Name of the service for log entries
 * @returns {object} Logger instance
 */
export function createLogger(serviceName) {
    /**
     * Formats a log entry as JSON
     * @param {LogLevel} level
     * @param {string} message
     * @param {object} [meta={}]
     * @returns {string}
     */
    function formatLog(level, message, meta = {}) {
        const entry = {
            timestamp: new Date().toISOString(),
            level,
            service: serviceName,
            message,
            ...meta,
        };
        return JSON.stringify(entry);
    }

    return {
        debug(message, meta) {
            if (process.env.LOG_LEVEL === 'debug') {
                console.log(formatLog('debug', message, meta));
            }
        },

        info(message, meta) {
            console.log(formatLog('info', message, meta));
        },

        warn(message, meta) {
            console.warn(formatLog('warn', message, meta));
        },

        error(message, meta) {
            console.error(formatLog('error', message, meta));
        },

        /** Log an incoming HTTP request */
        request(req, meta = {}) {
            this.info('incoming request', {
                method: req.method,
                path: req.path || req.url,
                ip: req.ip || req.connection?.remoteAddress,
                userAgent: req.get?.('user-agent'),
                ...meta,
            });
        },

        /** Log a response */
        response(req, statusCode, durationMs, meta = {}) {
            const level = statusCode >= 500 ? 'error' : statusCode >= 400 ? 'warn' : 'info';
            this[level]('response sent', {
                method: req.method,
                path: req.path || req.url,
                status: statusCode,
                durationMs,
                ...meta,
            });
        },

        /** Log authentication events */
        auth(event, email, meta = {}) {
            this.info('auth event', { event, email, ...meta });
        },

        /** Log database operations */
        db(operation, meta = {}) {
            this.debug('db operation', { operation, ...meta });
        },
    };
}
