type Level = "debug" | "info" | "warn" | "error";

function log(level: Level, message: string, data: Record<string, unknown> = {}) {
  const line = JSON.stringify({
    timestamp: new Date().toISOString(),
    level,
    service: "worker",
    message,
    ...data,
  });
  if (level === "error") console.error(line);
  else if (level === "warn") console.warn(line);
  else console.log(line);
}

export const logger = {
  debug: (message: string, data?: Record<string, unknown>) => log("debug", message, data),
  info: (message: string, data?: Record<string, unknown>) => log("info", message, data),
  warn: (message: string, data?: Record<string, unknown>) => log("warn", message, data),
  error: (message: string, data?: Record<string, unknown>) => log("error", message, data),
};
