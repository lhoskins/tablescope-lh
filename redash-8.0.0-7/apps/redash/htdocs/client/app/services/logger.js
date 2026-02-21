// services/logger.js

const logger = {
  log: (message, ...args) => {
    console.log(`[LOG]: ${message}`, ...args);
    // Add logic to send logs to an external service if needed
  },
  error: (message, ...args) => {
    console.error(`[ERROR]: ${message}`, ...args);
    // Add logic to send errors to an external service if needed
  },
  warn: (message, ...args) => {
    console.warn(`[WARNING]: ${message}`, ...args);
    // Add logic to send warnings to an external service if needed
  },
};

export default logger;
