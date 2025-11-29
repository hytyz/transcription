type LogLevel = "debug" | "info" | "warn" | "error";

interface LogEntry {
  timestamp: string;
  level: LogLevel;
  service: string;
  message: string;
  [key: string]: unknown;
}

const SERVICE_NAME = "s3";

function formatLog(level: LogLevel, message: string, meta: Record<string, unknown> = {}): string {
  const entry: LogEntry = {
    timestamp: new Date().toISOString(),
    level,
    service: SERVICE_NAME,
    message,
    ...meta,
  };
  return JSON.stringify(entry);
}

export const logger = {
  debug(message: string, meta?: Record<string, unknown>) {
    if (process.env.LOG_LEVEL === "debug") {
      console.log(formatLog("debug", message, meta));
    }
  },

  info(message: string, meta?: Record<string, unknown>) {
    console.log(formatLog("info", message, meta));
  },

  warn(message: string, meta?: Record<string, unknown>) {
    console.warn(formatLog("warn", message, meta));
  },

  error(message: string, meta?: Record<string, unknown>) {
    console.error(formatLog("error", message, meta));
  },

  request(method: string, path: string, meta?: Record<string, unknown>) {
    this.info("incoming request", { method, path, ...meta });
  },

  response(method: string, path: string, status: number, durationMs: number, meta?: Record<string, unknown>) {
    const level = status >= 500 ? "error" : status >= 400 ? "warn" : "info";
    this[level]("response sent", { method, path, status, durationMs, ...meta });
  },

  s3Operation(operation: string, key: string, meta?: Record<string, unknown>) {
    this.info("s3 operation", { operation, key, ...meta });
  },
};
