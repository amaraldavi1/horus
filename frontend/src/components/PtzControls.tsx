// PTZ overlay — shown only for PTZ cameras when role >= operator.
import {
  ChevronDown,
  ChevronLeft,
  ChevronRight,
  ChevronUp,
  Minus,
  Plus,
  Square,
} from 'lucide-react';
import { useMutation } from '@tanstack/react-query';
import { api, type PtzCommand } from '@/lib/api';
import { useHasRole } from '@/stores/auth';

interface Props {
  cameraId: number;
  /** camera.ptz flag */
  ptz: boolean;
}

const STEP = 0.5;

export default function PtzControls({ cameraId, ptz }: Props) {
  const allowed = useHasRole('operator');

  const mutation = useMutation({
    mutationFn: (cmd: PtzCommand) => api.ptz(cameraId, cmd),
  });

  if (!ptz || !allowed) return null;

  const move = (pan: number, tilt: number, zoom = 0) =>
    mutation.mutate({ action: 'move', pan, tilt, zoom });
  const stop = () => mutation.mutate({ action: 'stop' });

  const btn =
    'flex h-9 w-9 items-center justify-center rounded-lg bg-black/50 text-white backdrop-blur transition hover:bg-black/70 focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 active:bg-blue-600/70';

  // press-and-hold: move on pointerdown, stop on pointerup/leave
  const hold = (pan: number, tilt: number, zoom = 0) => ({
    onPointerDown: () => move(pan, tilt, zoom),
    onPointerUp: stop,
    onPointerLeave: stop,
  });

  return (
    <div className="pointer-events-auto select-none" aria-label="Controles PTZ" role="group">
      <div className="grid grid-cols-3 gap-1">
        <span />
        <button type="button" className={btn} aria-label="Mover para cima" {...hold(0, STEP)}>
          <ChevronUp className="h-5 w-5" aria-hidden />
        </button>
        <span />
        <button type="button" className={btn} aria-label="Mover para a esquerda" {...hold(-STEP, 0)}>
          <ChevronLeft className="h-5 w-5" aria-hidden />
        </button>
        <button type="button" className={btn} aria-label="Parar movimento" onClick={stop}>
          <Square className="h-4 w-4" aria-hidden />
        </button>
        <button type="button" className={btn} aria-label="Mover para a direita" {...hold(STEP, 0)}>
          <ChevronRight className="h-5 w-5" aria-hidden />
        </button>
        <button type="button" className={btn} aria-label="Aproximar zoom" {...hold(0, 0, STEP)}>
          <Plus className="h-5 w-5" aria-hidden />
        </button>
        <button type="button" className={btn} aria-label="Mover para baixo" {...hold(0, -STEP)}>
          <ChevronDown className="h-5 w-5" aria-hidden />
        </button>
        <button type="button" className={btn} aria-label="Afastar zoom" {...hold(0, 0, -STEP)}>
          <Minus className="h-5 w-5" aria-hidden />
        </button>
      </div>
    </div>
  );
}
