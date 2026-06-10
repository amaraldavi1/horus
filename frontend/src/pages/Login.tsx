import { Eye } from 'lucide-react';
import { useState } from 'react';
import { Navigate, useNavigate } from 'react-router-dom';
import { api, ApiError } from '@/lib/api';
import { useAuthStore, useIsAuthenticated } from '@/stores/auth';
import { btnPrimary, Field, inputCls, Spinner } from '@/components/ui';

export default function Login() {
  const navigate = useNavigate();
  const authed = useIsAuthenticated();
  const setSession = useAuthStore((s) => s.setSession);
  const [email, setEmail] = useState('');
  const [password, setPassword] = useState('');
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  if (authed) return <Navigate to="/" replace />;

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);
    setBusy(true);
    try {
      const res = await api.login(email, password);
      setSession(res.access_token, res.refresh_token, res.user);
      navigate('/', { replace: true });
    } catch (err) {
      if (err instanceof ApiError && err.status === 401) {
        setError('E-mail ou senha inválidos.');
      } else {
        setError(err instanceof Error ? err.message : 'Falha ao entrar. Tente novamente.');
      }
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen items-center justify-center bg-slate-100 px-4 dark:bg-surface-950">
      <div className="w-full max-w-sm">
        <div className="mb-8 flex flex-col items-center gap-2">
          <Eye className="h-12 w-12 text-blue-500" aria-hidden />
          <h1 className="text-2xl font-bold tracking-tight text-slate-900 dark:text-white">
            Horus
          </h1>
          <p className="text-sm text-slate-500 dark:text-slate-400">
            Sistema de monitoramento de vídeo
          </p>
        </div>

        <form
          onSubmit={submit}
          className="space-y-4 rounded-xl border border-slate-200 bg-white p-6 shadow-sm dark:border-surface-700 dark:bg-surface-800"
        >
          <Field label="E-mail">
            <input
              type="email"
              className={inputCls}
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              autoComplete="username"
              required
              autoFocus
            />
          </Field>
          <Field label="Senha">
            <input
              type="password"
              className={inputCls}
              value={password}
              onChange={(e) => setPassword(e.target.value)}
              autoComplete="current-password"
              required
            />
          </Field>

          {error && (
            <p role="alert" className="text-sm text-red-500 dark:text-red-400">
              {error}
            </p>
          )}

          <button type="submit" className={`${btnPrimary} w-full`} disabled={busy}>
            {busy ? <Spinner className="h-4 w-4" /> : 'Entrar'}
          </button>
        </form>
      </div>
    </div>
  );
}
