import { create } from 'zustand';
import { persist } from 'zustand/middleware';
import type { Role, User } from '@/lib/api';

interface AuthState {
  token: string | null;
  refreshToken: string | null;
  user: User | null;
  setSession: (token: string, refreshToken: string, user: User) => void;
  setTokens: (token: string, refreshToken: string | null, user?: User) => void;
  logout: () => void;
}

export const useAuthStore = create<AuthState>()(
  persist(
    (set, get) => ({
      token: null,
      refreshToken: null,
      user: null,
      setSession: (token, refreshToken, user) => set({ token, refreshToken, user }),
      setTokens: (token, refreshToken, user) =>
        set({ token, refreshToken, user: user ?? get().user }),
      logout: () => set({ token: null, refreshToken: null, user: null }),
    }),
    { name: 'horus-auth' },
  ),
);

const ROLE_LEVEL: Record<Role, number> = { viewer: 0, operator: 1, admin: 2 };

export function roleAtLeast(role: Role | undefined | null, min: Role): boolean {
  if (!role) return false;
  return ROLE_LEVEL[role] >= ROLE_LEVEL[min];
}

/** Convenience selector hooks */
export const useUser = () => useAuthStore((s) => s.user);
export const useIsAuthenticated = () => useAuthStore((s) => s.token !== null);
export const useHasRole = (min: Role) => useAuthStore((s) => roleAtLeast(s.user?.role, min));
