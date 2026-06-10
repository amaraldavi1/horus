// Polygon zone editor over a live camera frame (SVG, normalized 0..1 coords).
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Plus, Trash2 } from 'lucide-react';
import { useCallback, useRef, useState } from 'react';
import { api, type Zone, type ZoneCreate } from '@/lib/api';
import {
  btnDanger,
  btnPrimary,
  btnSecondary,
  ErrorBlock,
  Field,
  inputCls,
  LoadingBlock,
  selectCls,
} from '@/components/ui';

type Point = [number, number];

interface Draft {
  id: number | null;
  name: string;
  kind: 'include' | 'exclude';
  polygon: Point[];
  sensitivity: number;
  min_area: number;
  dwell_ms: number;
}

const EMPTY_DRAFT: Draft = {
  id: null,
  name: '',
  kind: 'include',
  polygon: [],
  sensitivity: 25,
  min_area: 0.005,
  dwell_ms: 500,
};

function zoneColor(kind: 'include' | 'exclude', active: boolean): { stroke: string; fill: string } {
  if (kind === 'include') {
    return { stroke: '#22c55e', fill: active ? 'rgba(34,197,94,0.25)' : 'rgba(34,197,94,0.12)' };
  }
  return { stroke: '#ef4444', fill: active ? 'rgba(239,68,68,0.25)' : 'rgba(239,68,68,0.12)' };
}

export default function ZoneEditor({ cameraId }: { cameraId: number }) {
  const queryClient = useQueryClient();
  const svgRef = useRef<SVGSVGElement>(null);
  const [draft, setDraft] = useState<Draft | null>(null);
  const [dragIndex, setDragIndex] = useState<number | null>(null);
  const [frameError, setFrameError] = useState(false);

  const zonesQuery = useQuery({
    queryKey: ['zones', cameraId],
    queryFn: () => api.listZones(cameraId),
  });

  const invalidate = () => queryClient.invalidateQueries({ queryKey: ['zones', cameraId] });

  const saveMutation = useMutation({
    mutationFn: (d: Draft) => {
      const body: ZoneCreate = {
        name: d.name || undefined,
        kind: d.kind,
        polygon: d.polygon,
        sensitivity: d.sensitivity,
        min_area: d.min_area,
        dwell_ms: d.dwell_ms,
      };
      return d.id === null
        ? api.createZone(cameraId, body)
        : api.updateZone(cameraId, d.id, body);
    },
    onSuccess: () => {
      setDraft(null);
      void invalidate();
    },
  });

  const deleteMutation = useMutation({
    mutationFn: (zoneId: number) => api.deleteZone(cameraId, zoneId),
    onSuccess: () => {
      setDraft(null);
      void invalidate();
    },
  });

  const toNormalized = useCallback((e: { clientX: number; clientY: number }): Point | null => {
    const svg = svgRef.current;
    if (!svg) return null;
    const rect = svg.getBoundingClientRect();
    const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width));
    const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height));
    return [Number(x.toFixed(4)), Number(y.toFixed(4))];
  }, []);

  const handleCanvasClick = (e: React.MouseEvent) => {
    if (!draft || dragIndex !== null) return;
    const p = toNormalized(e);
    if (p) setDraft({ ...draft, polygon: [...draft.polygon, p] });
  };

  const handlePointerMove = (e: React.PointerEvent) => {
    if (dragIndex === null || !draft) return;
    const p = toNormalized(e);
    if (!p) return;
    const polygon = draft.polygon.map((pt, i) => (i === dragIndex ? p : pt));
    setDraft({ ...draft, polygon });
  };

  const startEdit = (zone: Zone) => {
    setDraft({
      id: zone.id,
      name: zone.name ?? '',
      kind: zone.kind,
      polygon: zone.polygon.map((p) => [p[0], p[1]] as Point),
      sensitivity: zone.sensitivity,
      min_area: zone.min_area,
      dwell_ms: zone.dwell_ms,
    });
  };

  if (zonesQuery.isLoading) return <LoadingBlock label="Carregando zonas…" />;
  if (zonesQuery.isError) {
    return <ErrorBlock message="Falha ao carregar zonas." onRetry={() => void zonesQuery.refetch()} />;
  }

  const zones = zonesQuery.data ?? [];

  return (
    <div className="grid gap-4 lg:grid-cols-[2fr_1fr]">
      {/* Canvas */}
      <div className="relative aspect-video w-full overflow-hidden rounded-xl bg-black">
        {!frameError ? (
          <img
            src={`/go2rtc/api/frame.jpeg?src=cam${cameraId}`}
            alt="Quadro atual da câmera"
            className="absolute inset-0 h-full w-full object-fill opacity-80"
            onError={() => setFrameError(true)}
          />
        ) : (
          <div className="absolute inset-0 flex items-center justify-center text-sm text-slate-500">
            Sem imagem da câmera — desenhe sobre a área vazia
          </div>
        )}
        <svg
          ref={svgRef}
          viewBox="0 0 1 1"
          preserveAspectRatio="none"
          className={`absolute inset-0 h-full w-full ${draft ? 'cursor-crosshair' : ''}`}
          onClick={handleCanvasClick}
          onPointerMove={handlePointerMove}
          onPointerUp={() => setDragIndex(null)}
          onPointerLeave={() => setDragIndex(null)}
          role="application"
          aria-label="Editor de zonas: clique para adicionar vértices"
        >
          {zones
            .filter((z) => z.id !== draft?.id)
            .map((z) => {
              const c = zoneColor(z.kind, false);
              return (
                <polygon
                  key={z.id}
                  points={z.polygon.map((p) => `${p[0]},${p[1]}`).join(' ')}
                  fill={c.fill}
                  stroke={c.stroke}
                  strokeWidth={0.004}
                  vectorEffect="non-scaling-stroke"
                />
              );
            })}
          {draft && draft.polygon.length > 0 && (
            <>
              <polygon
                points={draft.polygon.map((p) => `${p[0]},${p[1]}`).join(' ')}
                fill={zoneColor(draft.kind, true).fill}
                stroke={zoneColor(draft.kind, true).stroke}
                strokeWidth={0.005}
              />
              {draft.polygon.map((p, i) => (
                <circle
                  key={i}
                  cx={p[0]}
                  cy={p[1]}
                  r={0.012}
                  fill="#ffffff"
                  stroke={zoneColor(draft.kind, true).stroke}
                  strokeWidth={0.005}
                  className="cursor-grab"
                  onPointerDown={(e) => {
                    e.stopPropagation();
                    setDragIndex(i);
                  }}
                  onClick={(e) => e.stopPropagation()}
                />
              ))}
            </>
          )}
        </svg>
      </div>

      {/* Side panel */}
      <div className="space-y-3">
        {!draft && (
          <>
            <button type="button" className={btnPrimary} onClick={() => setDraft(EMPTY_DRAFT)}>
              <Plus className="h-4 w-4" aria-hidden /> Nova zona
            </button>
            {zones.length === 0 ? (
              <p className="text-sm text-slate-500 dark:text-slate-400">
                Nenhuma zona definida — toda a imagem é monitorada.
              </p>
            ) : (
              <ul className="space-y-2">
                {zones.map((z) => (
                  <li key={z.id}>
                    <button
                      type="button"
                      onClick={() => startEdit(z)}
                      className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-left text-sm transition hover:border-blue-400 dark:border-surface-700 dark:hover:border-blue-500"
                    >
                      <span className="flex items-center gap-2 text-slate-800 dark:text-slate-200">
                        <span
                          className={`h-3 w-3 rounded-sm ${
                            z.kind === 'include' ? 'bg-emerald-500' : 'bg-red-500'
                          }`}
                        />
                        {z.name || `Zona ${z.id}`}
                      </span>
                      <span className="text-xs text-slate-500">
                        {z.kind === 'include' ? 'Incluir' : 'Excluir'}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </>
        )}

        {draft && (
          <div className="space-y-3">
            <p className="text-xs text-slate-500 dark:text-slate-400">
              Clique na imagem para adicionar vértices; arraste-os para ajustar. Mínimo de 3
              pontos.
            </p>
            <Field label="Nome">
              <input
                className={inputCls}
                value={draft.name}
                onChange={(e) => setDraft({ ...draft, name: e.target.value })}
                placeholder="Ex.: Portão"
              />
            </Field>
            <Field label="Tipo">
              <select
                className={selectCls}
                value={draft.kind}
                onChange={(e) =>
                  setDraft({ ...draft, kind: e.target.value as 'include' | 'exclude' })
                }
              >
                <option value="include">Incluir (verde) — detectar nesta área</option>
                <option value="exclude">Excluir (vermelho) — ignorar esta área</option>
              </select>
            </Field>
            <Field label={`Sensibilidade: ${draft.sensitivity}`}>
              <input
                type="range"
                min={1}
                max={100}
                value={draft.sensitivity}
                onChange={(e) => setDraft({ ...draft, sensitivity: Number(e.target.value) })}
              />
            </Field>
            <Field label={`Área mínima: ${(draft.min_area * 100).toFixed(1)}% do quadro`}>
              <input
                type="range"
                min={0.001}
                max={0.1}
                step={0.001}
                value={draft.min_area}
                onChange={(e) => setDraft({ ...draft, min_area: Number(e.target.value) })}
              />
            </Field>
            <Field label={`Permanência: ${draft.dwell_ms} ms`}>
              <input
                type="range"
                min={0}
                max={5000}
                step={100}
                value={draft.dwell_ms}
                onChange={(e) => setDraft({ ...draft, dwell_ms: Number(e.target.value) })}
              />
            </Field>

            {saveMutation.isError && (
              <p className="text-sm text-red-500">
                {saveMutation.error instanceof Error
                  ? saveMutation.error.message
                  : 'Falha ao salvar zona.'}
              </p>
            )}

            <div className="flex flex-wrap gap-2">
              <button
                type="button"
                className={btnPrimary}
                disabled={draft.polygon.length < 3 || saveMutation.isPending}
                onClick={() => saveMutation.mutate(draft)}
              >
                Salvar
              </button>
              {draft.polygon.length > 0 && (
                <button
                  type="button"
                  className={btnSecondary}
                  onClick={() => setDraft({ ...draft, polygon: [] })}
                >
                  Limpar pontos
                </button>
              )}
              <button type="button" className={btnSecondary} onClick={() => setDraft(null)}>
                Cancelar
              </button>
              {draft.id !== null && (
                <button
                  type="button"
                  className={btnDanger}
                  disabled={deleteMutation.isPending}
                  onClick={() => deleteMutation.mutate(draft.id as number)}
                >
                  <Trash2 className="h-4 w-4" aria-hidden /> Excluir
                </button>
              )}
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
