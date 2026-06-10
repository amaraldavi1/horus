// WebSocket hooks for real-time events and camera status (CONTRACTS §4).
import { useEffect, useRef } from 'react';
import { useAuthStore } from '@/stores/auth';
import type { CameraStatus, HorusEvent } from '@/lib/api';

const MIN_BACKOFF_MS = 1000;
const MAX_BACKOFF_MS = 30_000;

function wsUrl(path: string, token: string): string {
  const proto = window.location.protocol === 'https:' ? 'wss:' : 'ws:';
  return `${proto}//${window.location.host}/api/v1${path}?token=${encodeURIComponent(token)}`;
}

/**
 * Maintains a WebSocket with exponential-backoff auto-reconnect for the
 * lifetime of the component. `onMessage` receives the parsed `data` payload.
 */
function useSocket<T>(path: string, onMessage: (data: T) => void, expectType: string): void {
  const handlerRef = useRef(onMessage);
  handlerRef.current = onMessage;
  const token = useAuthStore((s) => s.token);

  useEffect(() => {
    if (!token) return;
    let ws: WebSocket | null = null;
    let closed = false;
    let backoff = MIN_BACKOFF_MS;
    let timer: ReturnType<typeof setTimeout> | undefined;

    const connect = () => {
      if (closed) return;
      try {
        ws = new WebSocket(wsUrl(path, token));
      } catch {
        scheduleReconnect();
        return;
      }
      ws.onopen = () => {
        backoff = MIN_BACKOFF_MS;
      };
      ws.onmessage = (e: MessageEvent<string>) => {
        try {
          const msg = JSON.parse(e.data) as { type?: string; data?: T };
          if (msg.type === expectType && msg.data !== undefined) {
            handlerRef.current(msg.data);
          }
        } catch {
          /* ignore malformed frames */
        }
      };
      ws.onclose = () => {
        ws = null;
        scheduleReconnect();
      };
      ws.onerror = () => {
        ws?.close();
      };
    };

    const scheduleReconnect = () => {
      if (closed) return;
      timer = setTimeout(connect, backoff + Math.random() * 500);
      backoff = Math.min(backoff * 2, MAX_BACKOFF_MS);
    };

    connect();
    return () => {
      closed = true;
      if (timer) clearTimeout(timer);
      ws?.close();
    };
  }, [path, token, expectType]);
}

/** Live detection events — `{type:"event", data:{...}}` on /ws/events. */
export function useEventSocket(onEvent: (event: HorusEvent) => void): void {
  useSocket<HorusEvent>('/ws/events', onEvent, 'event');
}

/** Camera status pushes — `{type:"status", data:{...}}` on /ws/status. */
export function useStatusSocket(onStatus: (status: CameraStatus) => void): void {
  useSocket<CameraStatus>('/ws/status', onStatus, 'status');
}
