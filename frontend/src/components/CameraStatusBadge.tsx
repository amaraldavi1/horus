import type { CameraStatus } from '@/lib/api';

interface Props {
  status: CameraStatus | undefined;
  /** show textual label next to the dots */
  withLabel?: boolean;
}

const STATE_PT: Record<CameraStatus['state'], string> = {
  online: 'Online',
  offline: 'Offline',
  connecting: 'Conectando',
  error: 'Erro',
};

const STATE_COLOR: Record<CameraStatus['state'], string> = {
  online: 'bg-emerald-500',
  offline: 'bg-slate-400 dark:bg-slate-600',
  connecting: 'bg-amber-400 animate-pulse',
  error: 'bg-red-500',
};

export default function CameraStatusBadge({ status, withLabel = false }: Props) {
  const state = status?.state ?? 'offline';
  const label = status ? STATE_PT[state] : 'Desconhecido';

  return (
    <span className="inline-flex items-center gap-1.5" title={status?.error ?? label}>
      <span
        className={`h-2.5 w-2.5 rounded-full ${STATE_COLOR[state]}`}
        role="img"
        aria-label={`Estado: ${label}`}
      />
      {status?.recording && (
        <span
          className="h-2.5 w-2.5 animate-pulse rounded-full bg-red-500"
          role="img"
          aria-label="Gravando"
          title="Gravando"
        />
      )}
      {status?.in_event && (
        <span
          className="h-2.5 w-2.5 rounded-full bg-blue-500"
          role="img"
          aria-label="Evento em andamento"
          title="Evento em andamento"
        />
      )}
      {withLabel && (
        <span className="text-xs text-slate-500 dark:text-slate-400">
          {label}
          {status?.state === 'online' && status.fps > 0 ? ` · ${status.fps.toFixed(0)} fps` : ''}
        </span>
      )}
    </span>
  );
}
