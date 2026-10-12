/** The sign-in seam. Hooks import from here; the adapter itself is chosen in `@/lib/api`, the only file that reads env. */
export { authProvider } from '@/lib/api';
export * from './provider';
