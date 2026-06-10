import { Car, Cat, PersonStanding, Waves } from 'lucide-react';
import { useEffect, useState } from 'react';
import { apiBlobUrl, type HorusEvent } from '@/lib/api';
import { fmtDuration, fmtRelative, fmtTime, labelPt } from '@/lib/format';

export function EventIcon({
  label,
  type,
  className = 'h-4 w-4',
}: {
  label: HorusEvent['label'];
  type: HorusEvent['type'];
  className?: string;
}) {
  if (label === 'person') return <PersonStanding className={className} aria-hidden />;
  if (label === 'car') return <Car className={className} aria-hidden />;
  if (label === 'animal') return <Cat className={className} aria-hidden />;
  return <Waves className={className} aria-hidden />;
}

/** Loads a protected snapshot (Authorization header) into an <img>. */
export function EventSnapshot({
  eventId,
  alt,
  className = '',
}: {
  eventId: string;
  alt: string;
  className?: string;
}) {
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    let active = true;
    let objectUrl: string | null = null;
    setUrl(null);
    setFailed(false);
    apiBlobUrl(`/events/${eventId}/snapshot`)
      .then((u) => {
        objectUrl = u;
        if (active) setUrl(u);
      })
      .catch(() => {
        if (active) setFailed(true);
      });
    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [eventId]);

  if (failed) {
    return (
      <div
        className={`flex items-center justify-center bg-slate-200 text-xs text-slate-500 dark:bg-surface-900 dark:text-slate-500 ${className}`}
      >
        Sem imagem
      </div>
    );
  }
  if (!url) {
    return <div className={`animate-pulse bg-slate-200 dark:bg-surface-900 ${className}`} />;
  }
  return <img src={url} alt={alt} className={`object-cover ${className}`} />;
}

interface Props {
  event: HorusEvent;
  cameraName?: string;
  onClick?: () => void;
}

export default function EventCard({ event, cameraName, onClick }: Props) {
  const label = labelPt(event.label, event.type);
  return (
    <button
      type="button"
      onClick={onClick}
      className="group overflow-hidden rounded-xl border border-slate-200 bg-white text-left shadow-sm transition hover:border-blue-400 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 dark:border-surface-700 dark:bg-surface-800 dark:hover:border-blue-500"
      aria-label={`Evento: ${label} ${cameraName ? `na câmera ${cameraName}` : ''} ${fmtRelative(event.started_at)}`}
    >
      <div className="relative aspect-video w-full overflow-hidden">
        <EventSnapshot eventId={event.id} alt={label} className="h-full w-full" />
        {event.confidence !== null && event.confidence > 0 && (
          <span className="absolute right-1.5 top-1.5 rounded bg-black/60 px-1.5 py-0.5 text-[10px] font-semibold text-white">
            {Math.round(event.confidence * 100)}%
          </span>
        )}
        {!event.ended_at && (
          <span className="absolute left-1.5 top-1.5 flex items-center gap-1 rounded bg-red-600/90 px-1.5 py-0.5 text-[10px] font-semibold text-white">
            <span className="h-1.5 w-1.5 animate-pulse rounded-full bg-white" />
            AO VIVO
          </span>
        )}
      </div>
      <div className="flex items-center gap-2 px-3 py-2">
        <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-blue-600/15 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400">
          <EventIcon label={event.label} type={event.type} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
            {label}
            {cameraName ? ` · ${cameraName}` : ''}
          </p>
          <p className="text-xs text-slate-500 dark:text-slate-400">
            {fmtTime(event.started_at)} · {fmtDuration(event.duration_s)}
          </p>
        </div>
      </div>
    </button>
  );
}
