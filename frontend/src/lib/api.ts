// Typed fetch client for the Horus REST API (see docs/CONTRACTS.md §4).
import { useAuthStore } from '@/stores/auth';

export const API_BASE = '/api/v1';

// ---------------------------------------------------------------------------
// Domain types (per CONTRACTS.md)
// ---------------------------------------------------------------------------

export type Role = 'admin' | 'operator' | 'viewer';

export interface User {
  id: number;
  email: string;
  name: string;
  role: Role;
  enabled: boolean;
  /** ids of cameras the user may access (empty = none; admin sees all) */
  camera_ids: number[];
  created_at?: string;
}

export type RecordingMode = 'continuous' | 'scheduled' | 'motion' | 'object' | 'event' | 'off';

export interface Camera {
  id: number;
  name: string;
  protocol: 'rtsp' | 'onvif';
  main_url: string;
  sub_url: string | null;
  codec: string | null;
  ptz: boolean;
  enabled: boolean;
  recording_mode: RecordingMode;
  pre_buffer_s: number;
  segment_s: number;
  retention_days_continuous: number;
  retention_days_event: number;
  detect_objects: boolean;
  detect_fps: number;
}

export type CameraCreate = Omit<Camera, 'id'>;

export interface Zone {
  id: number;
  camera_id?: number;
  name?: string;
  kind: 'include' | 'exclude';
  /** normalized 0..1 vertices */
  polygon: [number, number][];
  sensitivity: number;
  min_area: number;
  dwell_ms: number;
}

export type ZoneCreate = Omit<Zone, 'id'>;

export interface ScheduleRule {
  /** 0=Mon .. 6=Sun (per CONTRACTS §2 example) */
  days: number[];
  start: string; // "HH:MM"
  end: string; // "HH:MM"
  mode: RecordingMode;
}

export interface Schedule {
  timezone: string;
  rules: ScheduleRule[];
}

export type EventType = 'motion' | 'object';
export type EventLabel = 'person' | 'car' | 'animal' | null;

export interface HorusEvent {
  id: string;
  camera_id: number;
  type: EventType;
  label: EventLabel;
  confidence: number | null;
  zone_id: number | null;
  started_at: string;
  ended_at: string | null;
  duration_s: number | null;
  phase?: 'start' | 'update' | 'end';
  snapshot_path?: string | null;
  clip_path?: string | null;
}

export interface Recording {
  id: number;
  camera_id: number;
  started_at: string;
  ended_at: string;
  codec: string;
  size_bytes: number;
  kind: 'continuous' | 'event';
}

export interface Notification {
  id: number;
  kind: 'push' | 'email' | 'webhook';
  name: string;
  target: string;
  enabled: boolean;
  camera_ids: number[];
  labels: string[];
  min_confidence: number | null;
}

export type NotificationCreate = Omit<Notification, 'id'>;

export interface HardwareReport {
  decode: Record<string, boolean>;
  inference: Record<string, boolean>;
  selected: { decode: string; inference: string };
  gpus: string[];
  ts: string;
}

export interface StorageCameraUsage {
  camera_id: number;
  bytes: number;
}

export interface StorageReport {
  total_bytes: number;
  used_bytes: number;
  free_bytes: number;
  usage_pct: number;
  recordings_bytes?: number;
  events_bytes?: number;
  snapshots_bytes?: number;
  per_camera?: StorageCameraUsage[];
}

export interface CameraStatus {
  camera_id: number;
  state: 'online' | 'offline' | 'connecting' | 'error';
  recording: boolean;
  in_event: boolean;
  fps: number;
  decode_path: string;
  detect_path: string;
  error: string | null;
  ts: string;
}

export interface StreamUrls {
  webrtc_url: string;
  hls_url: string;
  sub_webrtc_url: string | null;
  sub_hls_url: string | null;
}

export interface DiscoveredCamera {
  ip: string;
  name: string;
  xaddr: string;
  manufacturer: string;
}

export interface CameraTestResult {
  ok: boolean;
  codec: string | null;
  width: number | null;
  height: number | null;
  error: string | null;
}

export interface AuditEntry {
  id: number;
  user_id: number | null;
  user_email: string | null;
  action: string;
  target: string | null;
  details: string | null;
  ip?: string | null;
  ts: string;
}

export interface Paginated<T> {
  items: T[];
  total: number;
  page: number;
  size: number;
}

export interface LoginResponse {
  access_token: string;
  refresh_token: string;
  user: User;
}

export interface PtzCommand {
  action: 'move' | 'stop' | 'preset';
  pan?: number;
  tilt?: number;
  zoom?: number;
  preset?: number;
}

// ---------------------------------------------------------------------------
// Fetch client with bearer token + auto refresh-once on 401
// ---------------------------------------------------------------------------

export class ApiError extends Error {
  status: number;
  constructor(status: number, detail: string) {
    super(detail);
    this.name = 'ApiError';
    this.status = status;
  }
}

type Query = Record<string, string | number | boolean | null | undefined>;

export function buildQuery(params?: Query): string {
  if (!params) return '';
  const sp = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== '') sp.set(k, String(v));
  }
  const s = sp.toString();
  return s ? `?${s}` : '';
}

let refreshInflight: Promise<boolean> | null = null;

async function refreshToken(): Promise<boolean> {
  if (!refreshInflight) {
    refreshInflight = (async () => {
      const { refreshToken: rt, setTokens, logout } = useAuthStore.getState();
      try {
        const res = await fetch(`${API_BASE}/auth/refresh`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          credentials: 'include',
          body: JSON.stringify(rt ? { refresh_token: rt } : {}),
        });
        if (!res.ok) {
          logout();
          return false;
        }
        const data = (await res.json()) as Partial<LoginResponse>;
        if (!data.access_token) {
          logout();
          return false;
        }
        setTokens(data.access_token, data.refresh_token ?? rt, data.user);
        return true;
      } catch {
        logout();
        return false;
      } finally {
        // allow future refreshes
        setTimeout(() => {
          refreshInflight = null;
        }, 0);
      }
    })();
  }
  return refreshInflight;
}

async function parseError(res: Response): Promise<ApiError> {
  let detail = `Erro ${res.status}`;
  try {
    const body = (await res.json()) as { detail?: unknown };
    if (typeof body.detail === 'string') detail = body.detail;
  } catch {
    /* non-JSON body */
  }
  return new ApiError(res.status, detail);
}

export interface RequestOptions {
  method?: 'GET' | 'POST' | 'PUT' | 'DELETE' | 'PATCH';
  body?: unknown;
  query?: Query;
  signal?: AbortSignal;
}

async function rawRequest(path: string, opts: RequestOptions, retried: boolean): Promise<Response> {
  const token = useAuthStore.getState().token;
  const headers: Record<string, string> = {};
  if (token) headers.Authorization = `Bearer ${token}`;
  if (opts.body !== undefined) headers['Content-Type'] = 'application/json';

  const res = await fetch(`${API_BASE}${path}${buildQuery(opts.query)}`, {
    method: opts.method ?? 'GET',
    headers,
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
    signal: opts.signal,
    credentials: 'include',
  });

  if (res.status === 401 && !retried && !path.startsWith('/auth/')) {
    const ok = await refreshToken();
    if (ok) return rawRequest(path, opts, true);
  }
  return res;
}

export async function apiFetch<T>(path: string, opts: RequestOptions = {}): Promise<T> {
  const res = await rawRequest(path, opts, false);
  if (!res.ok) throw await parseError(res);
  if (res.status === 204) return undefined as T;
  const text = await res.text();
  return (text ? JSON.parse(text) : undefined) as T;
}

/** Fetch a protected binary resource (snapshot/clip/export) as an object URL. */
export async function apiBlobUrl(path: string, signal?: AbortSignal): Promise<string> {
  const res = await rawRequest(path, { signal }, false);
  if (!res.ok) throw await parseError(res);
  return URL.createObjectURL(await res.blob());
}

/** Trigger a browser download of a protected resource. */
export async function apiDownload(path: string, filename: string): Promise<void> {
  const url = await apiBlobUrl(path);
  const a = document.createElement('a');
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

/**
 * URL usable directly in <video>/<img> src for protected media. The backend
 * accepts the access token via query string on media endpoints (browsers
 * cannot attach Authorization headers to media element requests).
 */
export function mediaSrc(path: string): string {
  const token = useAuthStore.getState().token;
  return `${API_BASE}${path}${path.includes('?') ? '&' : '?'}token=${encodeURIComponent(token ?? '')}`;
}

// ---------------------------------------------------------------------------
// Endpoint helpers
// ---------------------------------------------------------------------------

export const api = {
  // auth
  login: (email: string, password: string) =>
    apiFetch<LoginResponse>('/auth/login', { method: 'POST', body: { email, password } }),
  logout: () => apiFetch<void>('/auth/logout', { method: 'POST' }),

  // cameras
  listCameras: () => apiFetch<Camera[]>('/cameras'),
  getCamera: (id: number) => apiFetch<Camera>(`/cameras/${id}`),
  createCamera: (body: CameraCreate) => apiFetch<Camera>('/cameras', { method: 'POST', body }),
  updateCamera: (id: number, body: Partial<CameraCreate>) =>
    apiFetch<Camera>(`/cameras/${id}`, { method: 'PUT', body }),
  deleteCamera: (id: number) => apiFetch<void>(`/cameras/${id}`, { method: 'DELETE' }),
  discoverCameras: () => apiFetch<DiscoveredCamera[]>('/cameras/discover', { method: 'POST' }),
  testCamera: (url: string, protocol: string) =>
    apiFetch<CameraTestResult>('/cameras/test', { method: 'POST', body: { url, protocol } }),
  ptz: (id: number, cmd: PtzCommand) =>
    apiFetch<void>(`/cameras/${id}/ptz`, { method: 'POST', body: cmd }),
  getStreamUrls: (id: number) => apiFetch<StreamUrls>(`/cameras/${id}/stream`),

  // zones
  listZones: (cameraId: number) => apiFetch<Zone[]>(`/cameras/${cameraId}/zones`),
  createZone: (cameraId: number, body: ZoneCreate) =>
    apiFetch<Zone>(`/cameras/${cameraId}/zones`, { method: 'POST', body }),
  updateZone: (cameraId: number, zoneId: number, body: ZoneCreate) =>
    apiFetch<Zone>(`/cameras/${cameraId}/zones/${zoneId}`, { method: 'PUT', body }),
  deleteZone: (cameraId: number, zoneId: number) =>
    apiFetch<void>(`/cameras/${cameraId}/zones/${zoneId}`, { method: 'DELETE' }),

  // schedule
  getSchedule: (cameraId: number) => apiFetch<Schedule>(`/cameras/${cameraId}/schedule`),
  putSchedule: (cameraId: number, body: Schedule) =>
    apiFetch<Schedule>(`/cameras/${cameraId}/schedule`, { method: 'PUT', body }),

  // recordings
  listRecordings: (params: { camera_id: number; from: string; to: string; kind?: string }) =>
    apiFetch<Recording[]>('/recordings', { query: params }),

  // events
  listEvents: (params: {
    camera_id?: number;
    type?: string;
    label?: string;
    zone_id?: number;
    from?: string;
    to?: string;
    page?: number;
    size?: number;
  }) => apiFetch<Paginated<HorusEvent>>('/events', { query: params }),
  getEvent: (id: string) => apiFetch<HorusEvent>(`/events/${id}`),

  // notifications
  listNotifications: () => apiFetch<Notification[]>('/notifications'),
  createNotification: (body: NotificationCreate) =>
    apiFetch<Notification>('/notifications', { method: 'POST', body }),
  updateNotification: (id: number, body: Partial<NotificationCreate>) =>
    apiFetch<Notification>(`/notifications/${id}`, { method: 'PUT', body }),
  deleteNotification: (id: number) => apiFetch<void>(`/notifications/${id}`, { method: 'DELETE' }),

  // users (admin)
  listUsers: () => apiFetch<User[]>('/users'),
  createUser: (body: Partial<User> & { password: string }) =>
    apiFetch<User>('/users', { method: 'POST', body }),
  updateUser: (id: number, body: Partial<User> & { password?: string }) =>
    apiFetch<User>(`/users/${id}`, { method: 'PUT', body }),
  deleteUser: (id: number) => apiFetch<void>(`/users/${id}`, { method: 'DELETE' }),

  // system
  hardware: () => apiFetch<HardwareReport>('/system/hardware'),
  storage: () => apiFetch<StorageReport>('/system/storage'),

  // audit (admin)
  audit: (params?: { page?: number; size?: number }) =>
    apiFetch<Paginated<AuditEntry>>('/audit', { query: params }),
};
