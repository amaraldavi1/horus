import { format, formatDistanceToNow, parseISO } from 'date-fns';
import { ptBR } from 'date-fns/locale';
import type { EventLabel, EventType, RecordingMode } from '@/lib/api';

export function formatBytes(bytes: number): string {
  if (!Number.isFinite(bytes) || bytes < 0) return '—';
  const units = ['B', 'KB', 'MB', 'GB', 'TB'];
  let v = bytes;
  let i = 0;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v >= 100 || i === 0 ? 0 : 1)} ${units[i]}`;
}

export function fmtDateTime(iso: string): string {
  try {
    return format(parseISO(iso), "dd/MM/yyyy 'às' HH:mm:ss", { locale: ptBR });
  } catch {
    return iso;
  }
}

export function fmtTime(iso: string): string {
  try {
    return format(parseISO(iso), 'HH:mm:ss', { locale: ptBR });
  } catch {
    return iso;
  }
}

export function fmtRelative(iso: string): string {
  try {
    return formatDistanceToNow(parseISO(iso), { addSuffix: true, locale: ptBR });
  } catch {
    return iso;
  }
}

export function labelPt(label: EventLabel, type: EventType): string {
  if (label === 'person') return 'Pessoa';
  if (label === 'car') return 'Veículo';
  if (label === 'animal') return 'Animal';
  return type === 'motion' ? 'Movimento' : 'Objeto';
}

export const RECORDING_MODE_PT: Record<RecordingMode, string> = {
  continuous: 'Contínua',
  motion: 'Por movimento',
  event: 'Por evento',
  off: 'Desligada',
};

export const WEEKDAYS_PT = ['Seg', 'Ter', 'Qua', 'Qui', 'Sex', 'Sáb', 'Dom'];

export function fmtDuration(seconds: number | null): string {
  if (seconds === null || !Number.isFinite(seconds)) return '—';
  if (seconds < 60) return `${Math.round(seconds)}s`;
  const m = Math.floor(seconds / 60);
  const s = Math.round(seconds % 60);
  return `${m}m ${s}s`;
}
