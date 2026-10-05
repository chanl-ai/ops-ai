/**
 * Client-side logger utility
 *
 * ALL logging is disabled in production - no console output whatsoever.
 * Allows console.log-style debugging in development while passing ESLint rules.
 *
 * Usage:
 *   import { logger } from '@/lib/utils/logger';
 *   logger.log('Debug message', { data });
 *   logger.debug('Verbose debug');
 *   logger.info('Info message');
 *   logger.warn('Warning message');
 *   logger.error('Error message', error);
 */

// eslint-disable-next-line no-restricted-properties -- NODE_ENV is available client-side in Next.js
const isDevelopment = process.env.NODE_ENV === 'development';

export const logger = {
  /**
   * Log debug messages (development only)
   * Replaces console.log for debugging
   */
  log: (...args: any[]) => {
    if (isDevelopment) {
      // eslint-disable-next-line no-console
      console.log(...args);
    }
  },

  /**
   * Verbose debug messages (development only)
   * Replaces console.debug for detailed debugging
   */
  debug: (...args: any[]) => {
    if (isDevelopment) {
      // eslint-disable-next-line no-console
      console.debug(...args);
    }
  },

  /**
   * Info messages (development only)
   * Replaces console.info for informational messages
   */
  info: (...args: any[]) => {
    if (isDevelopment) {
      // eslint-disable-next-line no-console
      console.info(...args);
    }
  },

  /**
   * Warning messages (development only)
   * Uses console.warn (allowed by ESLint)
   */
  warn: (...args: any[]) => {
    if (isDevelopment) {
      // eslint-disable-next-line no-console
      console.warn(...args);
    }
  },

  /**
   * Error messages (development only)
   * Uses console.error (allowed by ESLint)
   */
  error: (...args: any[]) => {
    if (isDevelopment) {
      // eslint-disable-next-line no-console
      console.error(...args);
    }
  },
};
