import { useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Download } from 'lucide-react';
import { useCallback, useMemo, useState } from 'react';
import { api, apiDownload, mediaSrc, type HorusEvent, type Paginated } from '@/lib/api';
import { useCameras } from '@/hooks/data';
import { useEventSocket } from '@/lib/ws';
import { useHasRole } from '@/stores/auth';
import { fmtDateTime, fmtDuration, labelPt } from '@/lib/format';
import EventCard, { EventSnapshot } from '@/components/EventCard';
import {
  btnSecondary,
  EmptyBlock,
  ErrorBlock,
  inputCls,
  labelCls,
  LoadingBlock,
  Modal,
  selectCls,
} from '@/components/ui';

const PAGE_SIZE = 24;

function MetaItem({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className={labelCls}>{label}</dt>
      <dd className="text-sm text-slate-900 dark:text-white">{value}</dd>
    </div>
  );
}

export default function Events() {
  const camerasQuery = useCameras();
  const canExport = useHasRole('operator');
  const queryClient = useQueryClient();

  // filters
  const [cameraId, setCameraId] = useState('');
  const [type, setType] = useState('');
  const [label, setLabel] = useState('');
  const [from, setFrom] = useState('');
  const [to, setTo] = useState('');
  const [page, setPage] = useState(1);

  const [selected, setSelected] = useState<HorusEvent | null>(null);
  const [exporting, setExporting] = useState(false);
  const [exportError, setExportError] = useState<string | null>(null);

  const params = useMemo(
    () => ({
      camera_id: cameraId ? Number(cameraId) : undefined,
      type: type || undefined,
      label: label || undefined,
      from: from ? new Date(`${from}T00:00:00`).toISOString() : undefined,
      to: to ? new Date(`${to}T23:59:59.999`).toISOString() : undefined,
      page,
      size: PAGE_SIZE,
    }),
    [cameraId, type, label, from, to, page],
  );

  const eventsQuery = useQuery({
    queryKey: ['events', params],
    queryFn: () => api.listEvents(params),
    placeholderData: (prev) => prev,
    staleTime: 15_000,
  });

  const matchesFilters = useCallback(
    (e: HorusEvent): boolean => {
      if (cameraId && e.camera_id !== Number(cameraId)) return false;
      if (type && e.type !== type) return false;
      if (label && e.label !== label) return false;
      const started = new Date(e.started_at).getTime();
      if (from && started < new Date(`${from}T00:00:00`).getTime()) return false;
      if (to && started > new Date(`${to}T23:59:59.999`).getTime()) return false;
      return true;
    },
    [cameraId, type, label, from, to],
  );

  // live prepend / in-place update of new events via WebSocket
  useEventSocket(
    useCallback(
      (event: HorusEvent) => {
        setSelected((s) => (s && s.id === event.id ? { ...s, ...event } : s));
        if (page !== 1 || !matchesFilters(event)) return;
        queryClient.setQueryData<Paginated<HorusEvent>>(['events', params], (old) => {
          if (!old) return old;
          const idx = old.items.findIndex((i) => i.id === event.id);
          if (idx >= 0) {
            const items = [...old.items];
            items[idx] = { ...items[idx], ...event };
            return { ...old, items };
          }
          return {
            ...old,
            items: [event, ...old.items].slice(0, PAGE_SIZE),
            total: old.total + 1,
          };
        });
      },
      [page, params, matchesFilters, queryClient],
    ),
  );

  const cameras = camerasQuery.data ?? [];
  const cameraName = useMemo(() => {
    const m = new Map<number, string>();
    for (const c of cameras) m.set(c.id, c.name);
    return m;
  }, [cameras]);

  const resetPage = () => setPage(1);

  const handleExport = async (event: HorusEvent) => {
    setExporting(true);
    setExportError(null);
    try {
      await apiDownload(`/events/${event.id}/clip`, `evento-cam${event.camera_id}-${event.id}.mp4`);
    } catch (e) {
      setExportError(e instanceof Error ? e.message : 'Falha ao baixar o clipe.');
    } finally {
      setExporting(false);
    }
  };

  const data = eventsQuery.data;
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / PAGE_SIZE));

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Eventos</h1>

      {/* Filter bar */}
      <div className="flex flex-wrap items-end gap-2">
        <label className="block">
          <span className={labelCls}>Câmera</span>
          <select
            className={`${selectCls} w-auto`}
            value={cameraId}
            onChange={(e) => {
              setCameraId(e.target.value);
              resetPage();
            }}
          >
            <option value="">Todas</option>
            {cameras.map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className={labelCls}>Tipo</span>
          <select
            className={`${selectCls} w-auto`}
            value={type}
            onChange={(e) => {
              setType(e.target.value);
              resetPage();
            }}
          >
            <option value="">Todos</option>
            <option value="motion">Movimento</option>
            <option value="object">Objeto</option>
          </select>
        </label>
        <label className="block">
          <span className={labelCls}>Rótulo</span>
          <select
            className={`${selectCls} w-auto`}
            value={label}
            onChange={(e) => {
              setLabel(e.target.value);
              resetPage();
            }}
          >
            <option value="">Todos</option>
            <option value="person">Pessoa</option>
            <option value="car">Veículo</option>
            <option value="animal">Animal</option>
          </select>
        </label>
        <label className="block">
          <span className={labelCls}>De</span>
          <input
            type="date"
            className={`${inputCls} w-auto`}
            value={from}
            onChange={(e) => {
              setFrom(e.target.value);
              resetPage();
            }}
          />
        </label>
        <label className="block">
          <span className={labelCls}>Até</span>
          <input
            type="date"
            className={`${inputCls} w-auto`}
            value={to}
            onChange={(e) => {
              setTo(e.target.value);
              resetPage();
            }}
          />
        </label>
      </div>

      {/* Grid */}
      {eventsQuery.isLoading ? (
        <LoadingBlock label="Carregando eventos…" />
      ) : eventsQuery.isError ? (
        <ErrorBlock
          message="Falha ao carregar eventos."
          onRetry={() => void eventsQuery.refetch()}
        />
      ) : (data?.items.length ?? 0) === 0 ? (
        <EmptyBlock message="Nenhum evento encontrado com os filtros atuais." />
      ) : (
        <>
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
            {data?.items.map((event) => (
              <EventCard
                key={event.id}
                event={event}
                cameraName={cameraName.get(event.camera_id)}
                onClick={() => setSelected(event)}
              />
            ))}
          </div>

          {/* Pagination */}
          <div className="flex items-center justify-center gap-3">
            <button
              type="button"
              className={btnSecondary}
              disabled={page <= 1}
              onClick={() => setPage((p) => Math.max(1, p - 1))}
            >
              <ChevronLeft className="h-4 w-4" aria-hidden /> Anterior
            </button>
            <span className="text-sm text-slate-500 dark:text-slate-400">
              Página {page} de {totalPages} · {data?.total ?? 0} eventos
            </span>
            <button
              type="button"
              className={btnSecondary}
              disabled={page >= totalPages}
              onClick={() => setPage((p) => Math.min(totalPages, p + 1))}
            >
              Próxima <ChevronRight className="h-4 w-4" aria-hidden />
            </button>
          </div>
        </>
      )}

      {/* Detail modal */}
      {selected && (
        <Modal
          title={`${labelPt(selected.label, selected.type)} · ${
            cameraName.get(selected.camera_id) ?? `Câmera ${selected.camera_id}`
          }`}
          onClose={() => setSelected(null)}
          wide
        >
          <div className="space-y-4">
            {selected.ended_at ? (
              <video
                src={mediaSrc(`/events/${selected.id}/clip`)}
                controls
                autoPlay
                className="aspect-video w-full rounded-lg bg-black"
              />
            ) : (
              <EventSnapshot
                eventId={selected.id}
                alt={labelPt(selected.label, selected.type)}
                className="aspect-video w-full rounded-lg"
              />
            )}

            <dl className="grid grid-cols-2 gap-3 sm:grid-cols-3">
              <MetaItem
                label="Câmera"
                value={cameraName.get(selected.camera_id) ?? `Câmera ${selected.camera_id}`}
              />
              <MetaItem label="Tipo" value={selected.type === 'motion' ? 'Movimento' : 'Objeto'} />
              <MetaItem label="Rótulo" value={labelPt(selected.label, selected.type)} />
              <MetaItem
                label="Confiança"
                value={
                  selected.confidence !== null
                    ? `${Math.round(selected.confidence * 100)}%`
                    : '—'
                }
              />
              <MetaItem label="Início" value={fmtDateTime(selected.started_at)} />
              <MetaItem
                label="Fim"
                value={selected.ended_at ? fmtDateTime(selected.ended_at) : 'Em andamento'}
              />
              <MetaItem label="Duração" value={fmtDuration(selected.duration_s)} />
              <MetaItem
                label="Zona"
                value={selected.zone_id !== null ? `Zona ${selected.zone_id}` : '—'}
              />
            </dl>

            {exportError && <p className="text-sm text-red-500">{exportError}</p>}

            <div className="flex justify-end gap-2">
              {canExport && selected.ended_at && (
                <button
                  type="button"
                  className={btnSecondary}
                  disabled={exporting}
                  onClick={() => void handleExport(selected)}
                >
                  <Download className="h-4 w-4" aria-hidden />
                  {exporting ? 'Exportando…' : 'Baixar clipe'}
                </button>
              )}
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
