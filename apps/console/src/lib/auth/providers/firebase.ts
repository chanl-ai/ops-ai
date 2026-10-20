import type { AuthProvider } from '../provider';
import { unconfigured } from './unconfigured';

/** Firebase Authentication, optional. Its SDK is imported only inside this file once it is wired. */
export const createFirebaseProvider = (): AuthProvider => unconfigured('firebase', 'NEXT_PUBLIC_FIREBASE_API_KEY and NEXT_PUBLIC_FIREBASE_AUTH_DOMAIN');
