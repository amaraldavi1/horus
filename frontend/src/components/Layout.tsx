import { NavLink, Outlet, useNavigate } from 'react-router-dom';
import {
  Calendar,
  Cctv,
  Eye,
  LayoutDashboard,
  ListVideo,
  LogOut,
  Moon,
  Settings as SettingsIcon,
  Sun,
  Video,
} from 'lucide-react';
import { api } from '@/lib/api';
import { useAuthStore, useHasRole } from '@/stores/auth';
import { useThemeStore } from '@/stores/theme';

const NAV_ITEMS = [
  { to: '/', label: 'Dashboard', icon: LayoutDashboard, end: true },
  { to: '/live', label: 'Ao Vivo', icon: Video },
  { to: '/recordings', label: 'Gravações', icon: Calendar },
  { to: '/events', label: 'Eventos', icon: ListVideo },
  { to: '/cameras', label: 'Câmeras', icon: Cctv },
  { to: '/settings', label: 'Configurações', icon: SettingsIcon, admin: true },
];

const ROLE_PT: Record<string, string> = {
  admin: 'Administrador',
  operator: 'Operador',
  viewer: 'Visualizador',
};

function navCls(isActive: boolean): string {
  return `flex items-center gap-3 rounded-lg px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
    isActive
      ? 'bg-blue-600/15 text-blue-600 dark:bg-blue-500/15 dark:text-blue-400'
      : 'text-slate-600 hover:bg-slate-200/70 hover:text-slate-900 dark:text-slate-400 dark:hover:bg-surface-800 dark:hover:text-white'
  }`;
}

export default function Layout() {
  const user = useAuthStore((s) => s.user);
  const logout = useAuthStore((s) => s.logout);
  const isAdmin = useHasRole('admin');
  const { theme, toggle } = useThemeStore();
  const navigate = useNavigate();

  const items = NAV_ITEMS.filter((i) => !i.admin || isAdmin);

  const handleLogout = async () => {
    try {
      await api.logout();
    } catch {
      /* best-effort */
    }
    logout();
    navigate('/login', { replace: true });
  };

  return (
    <div className="flex min-h-screen">
      {/* Sidebar (desktop) */}
      <aside className="fixed inset-y-0 left-0 z-40 hidden w-60 flex-col border-r border-slate-200 bg-white dark:border-surface-700 dark:bg-surface-900 md:flex">
        <div className="flex items-center gap-2 px-5 py-5">
          <Eye className="h-7 w-7 text-blue-500" aria-hidden />
          <span className="text-lg font-bold tracking-tight text-slate-900 dark:text-white">
            Horus
          </span>
        </div>
        <nav className="flex-1 space-y-1 px-3" aria-label="Navegação principal">
          {items.map(({ to, label, icon: Icon, end }) => (
            <NavLink key={to} to={to} end={end} className={({ isActive }) => navCls(isActive)}>
              <Icon className="h-5 w-5 shrink-0" aria-hidden />
              {label}
            </NavLink>
          ))}
        </nav>
        <div className="border-t border-slate-200 p-3 dark:border-surface-700">
          <div className="flex items-center justify-between gap-2 px-2 py-1">
            <div className="min-w-0">
              <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
                {user?.name || user?.email}
              </p>
              <p className="text-xs text-slate-500 dark:text-slate-400">
                {user ? ROLE_PT[user.role] : ''}
              </p>
            </div>
            <div className="flex shrink-0 items-center gap-1">
              <button
                type="button"
                onClick={toggle}
                aria-label={theme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'}
                className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-slate-900 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 dark:text-slate-400 dark:hover:bg-surface-800 dark:hover:text-white"
              >
                {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
              </button>
              <button
                type="button"
                onClick={handleLogout}
                aria-label="Sair"
                className="rounded-lg p-2 text-slate-500 transition hover:bg-slate-100 hover:text-red-600 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 dark:text-slate-400 dark:hover:bg-surface-800 dark:hover:text-red-400"
              >
                <LogOut className="h-5 w-5" />
              </button>
            </div>
          </div>
        </div>
      </aside>

      {/* Top bar (mobile) */}
      <header className="fixed inset-x-0 top-0 z-40 flex items-center justify-between border-b border-slate-200 bg-white px-4 py-2.5 dark:border-surface-700 dark:bg-surface-900 md:hidden">
        <div className="flex items-center gap-2">
          <Eye className="h-6 w-6 text-blue-500" aria-hidden />
          <span className="font-bold text-slate-900 dark:text-white">Horus</span>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            onClick={toggle}
            aria-label={theme === 'dark' ? 'Mudar para tema claro' : 'Mudar para tema escuro'}
            className="rounded-lg p-2 text-slate-500 dark:text-slate-400"
          >
            {theme === 'dark' ? <Sun className="h-5 w-5" /> : <Moon className="h-5 w-5" />}
          </button>
          <button
            type="button"
            onClick={handleLogout}
            aria-label="Sair"
            className="rounded-lg p-2 text-slate-500 dark:text-slate-400"
          >
            <LogOut className="h-5 w-5" />
          </button>
        </div>
      </header>

      {/* Bottom nav (mobile) */}
      <nav
        className="fixed inset-x-0 bottom-0 z-40 flex border-t border-slate-200 bg-white dark:border-surface-700 dark:bg-surface-900 md:hidden"
        aria-label="Navegação principal"
      >
        {items.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            aria-label={label}
            className={({ isActive }) =>
              `flex flex-1 flex-col items-center gap-0.5 py-2 text-[10px] font-medium transition ${
                isActive
                  ? 'text-blue-600 dark:text-blue-400'
                  : 'text-slate-500 dark:text-slate-400'
              }`
            }
          >
            <Icon className="h-5 w-5" aria-hidden />
            <span className="truncate">{label}</span>
          </NavLink>
        ))}
      </nav>

      {/* Content */}
      <main className="min-w-0 flex-1 px-4 pb-20 pt-16 md:ml-60 md:px-8 md:pb-8 md:pt-6">
        <Outlet />
      </main>
    </div>
  );
}
