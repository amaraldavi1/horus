// Horizontal day timeline: recording segments as bars, events as markers.
import { ChevronFirst, ChevronLast, ZoomIn, ZoomOut } from 'lucide-react';
import { useMemo, useState } from 'react';
import type { HorusEvent, Recording } from '@/lib/api';
import { fmtTime, labelPt } from '@/lib/format';
import { btnIcon } from '@/components/ui';

interface TimelineProps {
  /** start of the displayed day (local midnight) */
  dayStart: Date;
  segments: Recording[];
  events: HorusEvent[];
  /** current playhead position (ms epoch) or null */
  playhead: number | null;
  onSeek: (msEpoch: number) => void;
}

const DAY_MS = 24 * 3600 * 1000;
const MIN_WINDOW_MS = 10 * 60 * 1000; // 10 min max zoom

function eventColor(e: HorusEvent): string {
  if (e.label === 'person') return 'bg-amber-400';
  if (e.label === 'car') return 'bg-purple-400';
  if (e.label === 'animal') return 'bg-teal-400';
  return 'bg-sky-400';
}

export default function Timeline({ dayStart, segments, events, playhead, onSeek }: TimelineProps) {
  const day0 = dayStart.getTime();
  const [win, setWin] = useState<{ start: number; end: number }>({ start: 0, end: DAY_MS });

  const winLen = win.end - win.start;
  const pct = (ms: number) => ((ms - day0 - win.start) / winLen) * 100;

  const zoom = (factor: number) => {
    const centerRel = playhead !== null ? playhead - day0 : win.start + winLen / 2;
    let len = Math.min(DAY_MS, Math.max(MIN_WINDOW_MS, winLen * factor));
    let start = centerRel - len / 2;
    start = Math.max(0, Math.min(DAY_MS - len, start));
    setWin({ start, end: start + len });
  };

  const sortedEvents = useMemo(
    () => [...events].sort((a, b) => a.started_at.localeCompare(b.started_at)),
    [events],
  );

  const jumpEvent = (dir: -1 | 1) => {
    if (sortedEvents.length === 0) return;
    const cur = playhead ?? day0;
    const target =
      dir === 1
        ? sortedEvents.find((e) => new Date(e.started_at).getTime() > cur + 500)
        : [...sortedEvents].reverse().find((e) => new Date(e.started_at).getTime() < cur - 500);
    if (target) onSeek(new Date(target.started_at).getTime());
  };

  const handleClick = (e: React.MouseEvent<HTMLDivElement>) => {
    const rect = e.currentTarget.getBoundingClientRect();
    const frac = (e.clientX - rect.left) / rect.width;
    onSeek(day0 + win.start + frac * winLen);
  };

  // hour ticks adapted to zoom level
  const ticks = useMemo(() => {
    const hourMs = 3600 * 1000;
    let step = hourMs * 3;
    if (winLen <= 2 * hourMs) step = 15 * 60 * 1000;
    else if (winLen <= 6 * hourMs) step = 30 * 60 * 1000;
    else if (winLen <= 12 * hourMs) step = hourMs;
    const out: { rel: number; label: string }[] = [];
    for (let t = Math.ceil(win.start / step) * step; t <= win.end; t += step) {
      const d = new Date(day0 + t);
      out.push({
        rel: t,
        label: `${String(d.getHours()).padStart(2, '0')}:${String(d.getMinutes()).padStart(2, '0')}`,
      });
    }
    return out;
  }, [win.start, win.end, winLen, day0]);

  return (
    <div>
      <div className="mb-1 flex items-center justify-between">
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={btnIcon}
            onClick={() => jumpEvent(-1)}
            aria-label="Evento anterior"
            disabled={sortedEvents.length === 0}
          >
            <ChevronFirst className="h-4 w-4" />
          </button>
          <button
            type="button"
            className={btnIcon}
            onClick={() => jumpEvent(1)}
            aria-label="Próximo evento"
            disabled={sortedEvents.length === 0}
          >
            <ChevronLast className="h-4 w-4" />
          </button>
        </div>
        <div className="flex items-center gap-1">
          <button
            type="button"
            className={btnIcon}
            onClick={() => zoom(0.5)}
            aria-label="Aproximar linha do tempo"
          >
            <ZoomIn className="h-4 w-4" />
          </button>
          <button
            type="button"
            className={btnIcon}
            onClick={() => zoom(2)}
            aria-label="Afastar linha do tempo"
          >
            <ZoomOut className="h-4 w-4" />
          </button>
        </div>
      </div>

      {/* Track */}
      <div
        className="relative h-16 w-full cursor-pointer select-none overflow-hidden rounded-lg border border-slate-200 bg-slate-50 dark:border-surface-700 dark:bg-surface-900"
        onClick={handleClick}
        role="slider"
        aria-label="Linha do tempo do dia — clique para buscar"
        aria-valuemin={0}
        aria-valuemax={DAY_MS}
        aria-valuenow={playhead !== null ? Math.round(playhead - day0) : 0}
        tabIndex={0}
        onKeyDown={(e) => {
          if (e.key === 'ArrowRight') jumpEvent(1);
          if (e.key === 'ArrowLeft') jumpEvent(-1);
        }}
      >
        {/* hour ticks */}
        {ticks.map((t) => (
          <div
            key={t.rel}
            className="absolute inset-y-0 border-l border-slate-200 dark:border-surface-700"
            style={{ left: `${((t.rel - win.start) / winLen) * 100}%` }}
          >
            <span className="absolute bottom-0.5 left-1 text-[9px] text-slate-400 dark:text-slate-500">
              {t.label}
            </span>
          </div>
        ))}

        {/* recording segments */}
        {segments.map((s) => {
          const a = new Date(s.started_at).getTime();
          const b = new Date(s.ended_at).getTime();
          const left = pct(a);
          const width = Math.max(0.08, ((b - a) / winLen) * 100);
          if (left > 100 || left + width < 0) return null;
          return (
            <div
              key={s.id}
              className={`absolute top-2 h-5 rounded-sm ${
                s.kind === 'event' ? 'bg-blue-500/80' : 'bg-blue-500/40'
              }`}
              style={{ left: `${left}%`, width: `${width}%` }}
              title={`${fmtTime(s.started_at)} – ${fmtTime(s.ended_at)} (${s.kind === 'event' ? 'evento' : 'contínua'})`}
            />
          );
        })}

        {/* event markers */}
        {sortedEvents.map((e) => {
          const left = pct(new Date(e.started_at).getTime());
          if (left < 0 || left > 100) return null;
          return (
            <div
              key={e.id}
              className={`absolute top-9 h-3.5 w-1 rounded-full ${eventColor(e)}`}
              style={{ left: `${left}%` }}
              title={`${labelPt(e.label, e.type)} · ${fmtTime(e.started_at)}`}
            />
          );
        })}

        {/* playhead */}
        {playhead !== null && pct(playhead) >= 0 && pct(playhead) <= 100 && (
          <div
            className="absolute inset-y-0 w-0.5 bg-red-500"
            style={{ left: `${pct(playhead)}%` }}
          >
            <div className="absolute -left-1 top-0 h-2 w-2.5 rounded-b-sm bg-red-500" />
          </div>
        )}
      </div>

      <div className="mt-1.5 flex flex-wrap items-center gap-x-4 gap-y-1 text-[10px] text-slate-500 dark:text-slate-400">
        <span className="flex items-center gap-1">
          <span className="h-2 w-3 rounded-sm bg-blue-500/40" /> Gravação contínua
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-3 rounded-sm bg-blue-500/80" /> Gravação de evento
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-1 rounded-full bg-amber-400" /> Pessoa
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-1 rounded-full bg-purple-400" /> Veículo
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-1 rounded-full bg-teal-400" /> Animal
        </span>
        <span className="flex items-center gap-1">
          <span className="h-2 w-1 rounded-full bg-sky-400" /> Movimento
        </span>
      </div>
    </div>
  );
}
