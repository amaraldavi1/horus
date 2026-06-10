import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { Pencil, Plus, RadioTower, SlidersHorizontal, Trash2 } from 'lucide-react';
import { useEffect, useState } from 'react';
import {
  api,
  type Camera,
  type CameraCreate,
  type DiscoveredCamera,
  type RecordingMode,
  type Schedule,
  type ScheduleRule,
} from '@/lib/api';
import { useCameras, useStatusMap } from '@/hooks/data';
import { useHasRole } from '@/stores/auth';
import { RECORDING_MODE_PT, WEEKDAYS_PT } from '@/lib/format';
import CameraStatusBadge from '@/components/CameraStatusBadge';
import ZoneEditor from '@/components/ZoneEditor';
import {
  btnDanger,
  btnIcon,
  btnPrimary,
  btnSecondary,
  cardCls,
  EmptyBlock,
  ErrorBlock,
  Field,
  inputCls,
  labelCls,
  LoadingBlock,
  Modal,
  selectCls,
  Toggle,
} from '@/components/ui';

// ---------------------------------------------------------------------------
// Form model
// ---------------------------------------------------------------------------

interface CameraForm {
  name: string;
  protocol: 'rtsp' | 'onvif';
  main_url: string;
  sub_url: string;
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

const DEFAULT_FORM: CameraForm = {
  name: '',
  protocol: 'rtsp',
  main_url: '',
  sub_url: '',
  ptz: false,
  enabled: true,
  recording_mode: 'motion',
  pre_buffer_s: 5,
  segment_s: 30,
  retention_days_continuous: 7,
  retention_days_event: 30,
  detect_objects: true,
  detect_fps: 5,
};

const FORM_MODES: RecordingMode[] = ['off', 'continuous', 'scheduled', 'motion', 'object'];
const RULE_MODES: RecordingMode[] = ['continuous', 'motion', 'object', 'off'];

function cameraToForm(c: Camera): CameraForm {
  return {
    name: c.name,
    protocol: c.protocol,
    main_url: c.main_url,
    sub_url: c.sub_url ?? '',
    ptz: c.ptz,
    enabled: c.enabled,
    recording_mode: c.recording_mode,
    pre_buffer_s: c.pre_buffer_s,
    segment_s: c.segment_s,
    retention_days_continuous: c.retention_days_continuous,
    retention_days_event: c.retention_days_event,
    detect_objects: c.detect_objects,
    detect_fps: c.detect_fps,
  };
}

function formToBody(f: CameraForm): Omit<CameraCreate, 'codec'> {
  return {
    name: f.name.trim(),
    protocol: f.protocol,
    main_url: f.main_url.trim(),
    sub_url: f.sub_url.trim() || null,
    ptz: f.ptz,
    enabled: f.enabled,
    recording_mode: f.recording_mode,
    pre_buffer_s: f.pre_buffer_s,
    segment_s: f.segment_s,
    retention_days_continuous: f.retention_days_continuous,
    retention_days_event: f.retention_days_event,
    detect_objects: f.detect_objects,
    detect_fps: f.detect_fps,
  };
}

type Update = (patch: Partial<CameraForm>) => void;

// ---------------------------------------------------------------------------
// Guided RTSP URL builder
// ---------------------------------------------------------------------------

interface BuilderState {
  host: string;
  port: string;
  username: string;
  password: string;
  path: string;
}

function assembleRtsp(b: BuilderState): string {
  if (!b.host.trim()) return '';
  const auth = b.username
    ? `${encodeURIComponent(b.username)}${b.password ? `:${encodeURIComponent(b.password)}` : ''}@`
    : '';
  return `rtsp://${auth}${b.host.trim()}:${b.port.trim() || '554'}/${b.path.replace(/^\/+/, '')}`;
}

function RtspBuilder({
  initialHost,
  onAssembled,
}: {
  initialHost?: string;
  onAssembled: (url: string) => void;
}) {
  const [b, setB] = useState<BuilderState>({
    host: initialHost ?? '',
    port: '554',
    username: '',
    password: '',
    path: '',
  });

  const set = (key: keyof BuilderState, value: string) => {
    const next = { ...b, [key]: value };
    setB(next);
    const url = assembleRtsp(next);
    if (url) onAssembled(url);
  };

  const preview = assembleRtsp(b);

  return (
    <fieldset className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-surface-700">
      <legend className="px-1 text-xs font-medium text-slate-500 dark:text-slate-400">
        Montar URL RTSP
      </legend>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Host / IP">
          <input
            className={inputCls}
            value={b.host}
            onChange={(e) => set('host', e.target.value)}
            placeholder="10.0.0.10"
          />
        </Field>
        <Field label="Porta">
          <input
            className={inputCls}
            type="number"
            min={1}
            max={65535}
            value={b.port}
            onChange={(e) => set('port', e.target.value)}
          />
        </Field>
        <Field label="Usuário">
          <input
            className={inputCls}
            value={b.username}
            onChange={(e) => set('username', e.target.value)}
            autoComplete="off"
          />
        </Field>
        <Field label="Senha">
          <input
            className={inputCls}
            type="password"
            value={b.password}
            onChange={(e) => set('password', e.target.value)}
            autoComplete="new-password"
          />
        </Field>
      </div>
      <Field label="Caminho" hint="Ex.: ch0, Streaming/Channels/101">
        <input
          className={inputCls}
          value={b.path}
          onChange={(e) => set('path', e.target.value)}
          placeholder="ch0"
        />
      </Field>
      <p className="break-all rounded-lg bg-slate-100 px-3 py-2 font-mono text-xs text-slate-600 dark:bg-surface-900 dark:text-slate-300">
        {preview || 'rtsp://…'}
      </p>
    </fieldset>
  );
}

// ---------------------------------------------------------------------------
// Form sections (shared between wizard and edit modal)
// ---------------------------------------------------------------------------

function ConnectionSection({
  form,
  update,
  initialHost,
}: {
  form: CameraForm;
  update: Update;
  initialHost?: string;
}) {
  const testMutation = useMutation({
    mutationFn: () => api.testCamera(form.main_url.trim(), form.protocol),
  });
  const test = testMutation.data;

  return (
    <div className="space-y-3">
      <Field label="Nome">
        <input
          className={inputCls}
          value={form.name}
          onChange={(e) => update({ name: e.target.value })}
          placeholder="Ex.: Entrada"
        />
      </Field>
      <Field label="Protocolo">
        <select
          className={selectCls}
          value={form.protocol}
          onChange={(e) => update({ protocol: e.target.value as 'rtsp' | 'onvif' })}
        >
          <option value="rtsp">RTSP</option>
          <option value="onvif">ONVIF</option>
        </select>
      </Field>

      <RtspBuilder initialHost={initialHost} onAssembled={(url) => update({ main_url: url })} />

      <Field label="URL principal" hint="Editável diretamente ou montada acima.">
        <input
          className={`${inputCls} font-mono`}
          value={form.main_url}
          onChange={(e) => update({ main_url: e.target.value })}
          placeholder="rtsp://usuario:senha@10.0.0.10:554/ch0"
        />
      </Field>
      <Field label="URL do substream (opcional)" hint="Stream de menor resolução para o mosaico.">
        <input
          className={`${inputCls} font-mono`}
          value={form.sub_url}
          onChange={(e) => update({ sub_url: e.target.value })}
          placeholder="rtsp://usuario:senha@10.0.0.10:554/ch1"
        />
      </Field>

      <div className="flex items-center gap-3">
        <Toggle
          checked={form.ptz}
          onChange={(v) => update({ ptz: v })}
          label="Câmera com PTZ"
        />
        <span className="text-sm text-slate-700 dark:text-slate-300">Câmera com PTZ</span>
      </div>
      <div className="flex items-center gap-3">
        <Toggle
          checked={form.enabled}
          onChange={(v) => update({ enabled: v })}
          label="Câmera habilitada"
        />
        <span className="text-sm text-slate-700 dark:text-slate-300">Habilitada</span>
      </div>

      <div className="flex items-center gap-3">
        <button
          type="button"
          className={btnSecondary}
          disabled={!form.main_url.trim() || testMutation.isPending}
          onClick={() => testMutation.mutate()}
        >
          <RadioTower className="h-4 w-4" aria-hidden />
          {testMutation.isPending ? 'Testando…' : 'Testar conexão'}
        </button>
        {test &&
          (test.ok ? (
            <span className="text-sm font-medium text-emerald-600 dark:text-emerald-400">
              Conexão OK
              {test.codec ? ` · ${test.codec.toUpperCase()}` : ''}
              {test.width && test.height ? ` · ${test.width}×${test.height}` : ''}
            </span>
          ) : (
            <span className="text-sm text-red-500">{test.error || 'Falha na conexão.'}</span>
          ))}
        {testMutation.isError && (
          <span className="text-sm text-red-500">
            {testMutation.error instanceof Error
              ? testMutation.error.message
              : 'Falha ao testar conexão.'}
          </span>
        )}
      </div>
    </div>
  );
}

function RecordingSection({ form, update }: { form: CameraForm; update: Update }) {
  return (
    <div className="space-y-3">
      <Field label="Modo de gravação">
        <select
          className={selectCls}
          value={form.recording_mode}
          onChange={(e) => update({ recording_mode: e.target.value as RecordingMode })}
        >
          {FORM_MODES.map((m) => (
            <option key={m} value={m}>
              {RECORDING_MODE_PT[m]}
            </option>
          ))}
        </select>
      </Field>
      <div className="grid gap-3 sm:grid-cols-2">
        <Field label="Pré-buffer (s)" hint="Segundos gravados antes do evento.">
          <input
            className={inputCls}
            type="number"
            min={0}
            max={60}
            value={form.pre_buffer_s}
            onChange={(e) => update({ pre_buffer_s: Number(e.target.value) })}
          />
        </Field>
        <Field label="Segmento (s)" hint="Duração de cada arquivo de gravação.">
          <input
            className={inputCls}
            type="number"
            min={5}
            max={600}
            value={form.segment_s}
            onChange={(e) => update({ segment_s: Number(e.target.value) })}
          />
        </Field>
        <Field label="Retenção contínua (dias)">
          <input
            className={inputCls}
            type="number"
            min={1}
            max={365}
            value={form.retention_days_continuous}
            onChange={(e) => update({ retention_days_continuous: Number(e.target.value) })}
          />
        </Field>
        <Field label="Retenção de eventos (dias)">
          <input
            className={inputCls}
            type="number"
            min={1}
            max={3650}
            value={form.retention_days_event}
            onChange={(e) => update({ retention_days_event: Number(e.target.value) })}
          />
        </Field>
      </div>
      <div className="flex items-center gap-3">
        <Toggle
          checked={form.detect_objects}
          onChange={(v) => update({ detect_objects: v })}
          label="Detecção de objetos"
        />
        <span className="text-sm text-slate-700 dark:text-slate-300">
          Detecção de objetos (pessoa, veículo, animal)
        </span>
      </div>
      {form.detect_objects && (
        <Field label="FPS de detecção" hint="Quadros por segundo enviados à inferência.">
          <input
            className={inputCls}
            type="number"
            min={1}
            max={30}
            value={form.detect_fps}
            onChange={(e) => update({ detect_fps: Number(e.target.value) })}
          />
        </Field>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Add-camera wizard
// ---------------------------------------------------------------------------

const WIZARD_STEPS = ['Método', 'Conexão', 'Gravação', 'Revisão'];

function ReviewRow({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex items-start justify-between gap-4 py-1.5">
      <span className="text-sm text-slate-500 dark:text-slate-400">{label}</span>
      <span className="break-all text-right text-sm font-medium text-slate-900 dark:text-white">
        {value}
      </span>
    </div>
  );
}

function AddCameraWizard({ onClose }: { onClose: () => void }) {
  const queryClient = useQueryClient();
  const [step, setStep] = useState(0);
  const [form, setForm] = useState<CameraForm>(DEFAULT_FORM);
  const [discoveredHost, setDiscoveredHost] = useState<string | undefined>(undefined);
  const update: Update = (patch) => setForm((f) => ({ ...f, ...patch }));

  const discoverMutation = useMutation({ mutationFn: api.discoverCameras });
  const createMutation = useMutation({
    mutationFn: () => api.createCamera({ ...formToBody(form), codec: null }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cameras'] });
      onClose();
    },
  });

  const pickDiscovered = (d: DiscoveredCamera) => {
    setDiscoveredHost(d.ip);
    update({
      name: d.name || d.manufacturer || d.ip,
      protocol: 'onvif',
      main_url: `rtsp://${d.ip}:554/`,
    });
    setStep(1);
  };

  const canAdvanceConnection = form.name.trim() !== '' && form.main_url.trim() !== '';

  return (
    <Modal title="Adicionar câmera" onClose={onClose} wide>
      {/* Stepper */}
      <ol className="mb-5 flex items-center gap-2" aria-label="Etapas do assistente">
        {WIZARD_STEPS.map((label, i) => (
          <li key={label} className="flex items-center gap-2">
            <span
              className={`flex h-6 w-6 items-center justify-center rounded-full text-xs font-semibold ${
                i === step
                  ? 'bg-blue-600 text-white'
                  : i < step
                    ? 'bg-blue-600/20 text-blue-600 dark:text-blue-400'
                    : 'bg-slate-200 text-slate-500 dark:bg-surface-700 dark:text-slate-400'
              }`}
              aria-current={i === step ? 'step' : undefined}
            >
              {i + 1}
            </span>
            <span
              className={`text-xs ${
                i === step
                  ? 'font-medium text-slate-900 dark:text-white'
                  : 'text-slate-500 dark:text-slate-400'
              }`}
            >
              {label}
            </span>
            {i < WIZARD_STEPS.length - 1 && (
              <span className="h-px w-4 bg-slate-300 dark:bg-surface-700" aria-hidden />
            )}
          </li>
        ))}
      </ol>

      {/* Step 1 — method */}
      {step === 0 && (
        <div className="space-y-4">
          <div className="grid gap-3 sm:grid-cols-2">
            <button
              type="button"
              className={`${cardCls} p-4 text-left transition hover:border-blue-400 dark:hover:border-blue-500`}
              onClick={() => discoverMutation.mutate()}
            >
              <span className="mb-1 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                <RadioTower className="h-4 w-4 text-blue-500" aria-hidden /> Descoberta ONVIF
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Procurar câmeras compatíveis na rede local.
              </span>
            </button>
            <button
              type="button"
              className={`${cardCls} p-4 text-left transition hover:border-blue-400 dark:hover:border-blue-500`}
              onClick={() => setStep(1)}
            >
              <span className="mb-1 flex items-center gap-2 text-sm font-semibold text-slate-900 dark:text-white">
                <SlidersHorizontal className="h-4 w-4 text-blue-500" aria-hidden /> Configuração
                manual
              </span>
              <span className="text-xs text-slate-500 dark:text-slate-400">
                Informar a URL RTSP/ONVIF da câmera diretamente.
              </span>
            </button>
          </div>

          {discoverMutation.isPending && <LoadingBlock label="Procurando câmeras na rede…" />}
          {discoverMutation.isError && (
            <ErrorBlock
              message="Falha na descoberta ONVIF."
              onRetry={() => discoverMutation.mutate()}
            />
          )}
          {discoverMutation.data &&
            (discoverMutation.data.length === 0 ? (
              <EmptyBlock message="Nenhuma câmera encontrada na rede." />
            ) : (
              <ul className="space-y-2">
                {discoverMutation.data.map((d) => (
                  <li key={d.xaddr || d.ip}>
                    <button
                      type="button"
                      onClick={() => pickDiscovered(d)}
                      className="flex w-full items-center justify-between rounded-lg border border-slate-200 px-3 py-2 text-left text-sm transition hover:border-blue-400 dark:border-surface-700 dark:hover:border-blue-500"
                    >
                      <span className="font-medium text-slate-900 dark:text-white">
                        {d.name || d.manufacturer || d.ip}
                      </span>
                      <span className="text-xs text-slate-500 dark:text-slate-400">
                        {d.manufacturer} · {d.ip}
                      </span>
                    </button>
                  </li>
                ))}
              </ul>
            ))}
        </div>
      )}

      {/* Step 2 — connection */}
      {step === 1 && (
        <ConnectionSection form={form} update={update} initialHost={discoveredHost} />
      )}

      {/* Step 3 — recording */}
      {step === 2 && <RecordingSection form={form} update={update} />}

      {/* Step 4 — review */}
      {step === 3 && (
        <div className="divide-y divide-slate-200 dark:divide-surface-700">
          <ReviewRow label="Nome" value={form.name} />
          <ReviewRow label="Protocolo" value={form.protocol.toUpperCase()} />
          <ReviewRow label="URL principal" value={form.main_url} />
          <ReviewRow label="Substream" value={form.sub_url || '—'} />
          <ReviewRow label="PTZ" value={form.ptz ? 'Sim' : 'Não'} />
          <ReviewRow label="Habilitada" value={form.enabled ? 'Sim' : 'Não'} />
          <ReviewRow label="Gravação" value={RECORDING_MODE_PT[form.recording_mode]} />
          <ReviewRow label="Pré-buffer" value={`${form.pre_buffer_s} s`} />
          <ReviewRow label="Segmento" value={`${form.segment_s} s`} />
          <ReviewRow
            label="Retenção"
            value={`Contínua ${form.retention_days_continuous} d · Eventos ${form.retention_days_event} d`}
          />
          <ReviewRow
            label="Detecção de objetos"
            value={form.detect_objects ? `Sim · ${form.detect_fps} fps` : 'Não'}
          />
        </div>
      )}

      {createMutation.isError && (
        <p className="mt-3 text-sm text-red-500">
          {createMutation.error instanceof Error
            ? createMutation.error.message
            : 'Falha ao criar câmera.'}
        </p>
      )}

      {/* Wizard nav */}
      {step > 0 && (
        <div className="mt-5 flex justify-between">
          <button type="button" className={btnSecondary} onClick={() => setStep((s) => s - 1)}>
            Voltar
          </button>
          {step < 3 ? (
            <button
              type="button"
              className={btnPrimary}
              disabled={step === 1 && !canAdvanceConnection}
              onClick={() => setStep((s) => s + 1)}
            >
              Avançar
            </button>
          ) : (
            <button
              type="button"
              className={btnPrimary}
              disabled={createMutation.isPending}
              onClick={() => createMutation.mutate()}
            >
              {createMutation.isPending ? 'Criando…' : 'Criar câmera'}
            </button>
          )}
        </div>
      )}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Weekly schedule editor (PUT /cameras/{id}/schedule)
// ---------------------------------------------------------------------------

const TIMEZONES = [
  'America/Sao_Paulo',
  'America/Manaus',
  'America/Cuiaba',
  'America/Fortaleza',
  'America/Recife',
  'America/Belem',
  'America/Rio_Branco',
  'America/Noronha',
  'UTC',
];

const NEW_RULE: ScheduleRule = { days: [0, 1, 2, 3, 4], start: '08:00', end: '18:00', mode: 'continuous' };

function ScheduleEditor({ cameraId }: { cameraId: number }) {
  const queryClient = useQueryClient();
  const scheduleQuery = useQuery({
    queryKey: ['schedule', cameraId],
    queryFn: () => api.getSchedule(cameraId),
  });
  const [draft, setDraft] = useState<Schedule | null>(null);

  useEffect(() => {
    const data = scheduleQuery.data;
    if (data) {
      setDraft(
        (d) =>
          d ?? {
            timezone: data.timezone || 'America/Sao_Paulo',
            rules: data.rules.map((r) => ({ ...r, days: [...r.days] })),
          },
      );
    }
  }, [scheduleQuery.data]);

  const saveMutation = useMutation({
    mutationFn: (s: Schedule) => api.putSchedule(cameraId, s),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['schedule', cameraId] }),
  });

  if (scheduleQuery.isError) {
    return (
      <ErrorBlock
        message="Falha ao carregar agendamento."
        onRetry={() => void scheduleQuery.refetch()}
      />
    );
  }
  if (scheduleQuery.isLoading || !draft) return <LoadingBlock label="Carregando agendamento…" />;

  const setRule = (idx: number, patch: Partial<ScheduleRule>) => {
    setDraft({
      ...draft,
      rules: draft.rules.map((r, i) => (i === idx ? { ...r, ...patch } : r)),
    });
  };

  const toggleDay = (idx: number, day: number) => {
    const rule = draft.rules[idx];
    const days = rule.days.includes(day)
      ? rule.days.filter((d) => d !== day)
      : [...rule.days, day].sort((a, b) => a - b);
    setRule(idx, { days });
  };

  return (
    <div className="space-y-4">
      <Field label="Fuso horário">
        <select
          className={selectCls}
          value={draft.timezone}
          onChange={(e) => setDraft({ ...draft, timezone: e.target.value })}
        >
          {TIMEZONES.map((tz) => (
            <option key={tz} value={tz}>
              {tz}
            </option>
          ))}
        </select>
      </Field>

      {draft.rules.length === 0 && (
        <p className="text-sm text-slate-500 dark:text-slate-400">
          Nenhuma regra definida — o modo de gravação padrão da câmera se aplica o tempo todo.
        </p>
      )}

      <ul className="space-y-3">
        {draft.rules.map((rule, idx) => (
          <li
            key={idx}
            className="space-y-3 rounded-lg border border-slate-200 p-3 dark:border-surface-700"
          >
            <div className="flex flex-wrap gap-3" role="group" aria-label="Dias da semana">
              {WEEKDAYS_PT.map((d, di) => (
                <label
                  key={d}
                  className="inline-flex items-center gap-1.5 text-sm text-slate-700 dark:text-slate-300"
                >
                  <input
                    type="checkbox"
                    checked={rule.days.includes(di)}
                    onChange={() => toggleDay(idx, di)}
                  />
                  {d}
                </label>
              ))}
            </div>
            <div className="flex flex-wrap items-end gap-3">
              <Field label="Início">
                <input
                  type="time"
                  className={`${inputCls} w-auto`}
                  value={rule.start}
                  onChange={(e) => setRule(idx, { start: e.target.value })}
                />
              </Field>
              <Field label="Fim">
                <input
                  type="time"
                  className={`${inputCls} w-auto`}
                  value={rule.end}
                  onChange={(e) => setRule(idx, { end: e.target.value })}
                />
              </Field>
              <Field label="Modo">
                <select
                  className={`${selectCls} w-auto`}
                  value={rule.mode}
                  onChange={(e) => setRule(idx, { mode: e.target.value as RecordingMode })}
                >
                  {RULE_MODES.map((m) => (
                    <option key={m} value={m}>
                      {RECORDING_MODE_PT[m]}
                    </option>
                  ))}
                </select>
              </Field>
              <button
                type="button"
                className={btnIcon}
                aria-label="Remover regra"
                onClick={() =>
                  setDraft({ ...draft, rules: draft.rules.filter((_, i) => i !== idx) })
                }
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </div>
          </li>
        ))}
      </ul>

      <div className="flex flex-wrap items-center gap-2">
        <button
          type="button"
          className={btnSecondary}
          onClick={() =>
            setDraft({ ...draft, rules: [...draft.rules, { ...NEW_RULE, days: [...NEW_RULE.days] }] })
          }
        >
          <Plus className="h-4 w-4" aria-hidden /> Adicionar regra
        </button>
        <button
          type="button"
          className={btnPrimary}
          disabled={saveMutation.isPending}
          onClick={() => saveMutation.mutate(draft)}
        >
          {saveMutation.isPending ? 'Salvando…' : 'Salvar agendamento'}
        </button>
        {saveMutation.isSuccess && (
          <span className="text-sm text-emerald-600 dark:text-emerald-400">
            Agendamento salvo.
          </span>
        )}
        {saveMutation.isError && (
          <span className="text-sm text-red-500">
            {saveMutation.error instanceof Error
              ? saveMutation.error.message
              : 'Falha ao salvar agendamento.'}
          </span>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Edit modal (general / zones / schedule tabs)
// ---------------------------------------------------------------------------

type EditTab = 'general' | 'zones' | 'schedule';

const EDIT_TABS: { id: EditTab; label: string }[] = [
  { id: 'general', label: 'Geral' },
  { id: 'zones', label: 'Zonas' },
  { id: 'schedule', label: 'Agendamento' },
];

function EditCameraModal({ camera, onClose }: { camera: Camera; onClose: () => void }) {
  const queryClient = useQueryClient();
  const [tab, setTab] = useState<EditTab>('general');
  const [form, setForm] = useState<CameraForm>(() => cameraToForm(camera));
  const update: Update = (patch) => setForm((f) => ({ ...f, ...patch }));

  const saveMutation = useMutation({
    mutationFn: () => api.updateCamera(camera.id, formToBody(form)),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cameras'] });
      onClose();
    },
  });

  return (
    <Modal title={`Editar câmera — ${camera.name}`} onClose={onClose} wide>
      <div
        className="mb-4 flex gap-1 border-b border-slate-200 dark:border-surface-700"
        role="tablist"
        aria-label="Seções da câmera"
      >
        {EDIT_TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px border-b-2 px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
              tab === t.id
                ? 'border-blue-600 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'general' && (
        <div className="space-y-5">
          <ConnectionSection form={form} update={update} />
          <h3 className="text-sm font-medium uppercase tracking-wide text-slate-500 dark:text-slate-400">
            Gravação
          </h3>
          <RecordingSection form={form} update={update} />
          {saveMutation.isError && (
            <p className="text-sm text-red-500">
              {saveMutation.error instanceof Error
                ? saveMutation.error.message
                : 'Falha ao salvar câmera.'}
            </p>
          )}
          <div className="flex justify-end gap-2">
            <button type="button" className={btnSecondary} onClick={onClose}>
              Cancelar
            </button>
            <button
              type="button"
              className={btnPrimary}
              disabled={saveMutation.isPending || !form.name.trim() || !form.main_url.trim()}
              onClick={() => saveMutation.mutate()}
            >
              {saveMutation.isPending ? 'Salvando…' : 'Salvar alterações'}
            </button>
          </div>
        </div>
      )}

      {tab === 'zones' && <ZoneEditor cameraId={camera.id} />}
      {tab === 'schedule' && <ScheduleEditor cameraId={camera.id} />}
    </Modal>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

export default function Cameras() {
  const camerasQuery = useCameras();
  const statusMap = useStatusMap();
  const isAdmin = useHasRole('admin');
  const queryClient = useQueryClient();

  const [adding, setAdding] = useState(false);
  const [editing, setEditing] = useState<Camera | null>(null);
  const [deleting, setDeleting] = useState<Camera | null>(null);

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteCamera(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['cameras'] });
      setDeleting(null);
    },
  });

  if (camerasQuery.isLoading) return <LoadingBlock />;
  if (camerasQuery.isError) {
    return (
      <ErrorBlock message="Falha ao carregar câmeras." onRetry={() => void camerasQuery.refetch()} />
    );
  }

  const cameras = camerasQuery.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex flex-wrap items-center justify-between gap-3">
        <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Câmeras</h1>
        {isAdmin && (
          <button type="button" className={btnPrimary} onClick={() => setAdding(true)}>
            <Plus className="h-4 w-4" aria-hidden /> Adicionar câmera
          </button>
        )}
      </div>

      {cameras.length === 0 ? (
        <EmptyBlock
          message={
            isAdmin
              ? 'Nenhuma câmera cadastrada. Use “Adicionar câmera” para começar.'
              : 'Nenhuma câmera cadastrada.'
          }
        />
      ) : (
        <div className={`${cardCls} overflow-x-auto`}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-surface-700">
                <th className={`${labelCls} px-4 py-3`}>Nome</th>
                <th className={`${labelCls} px-4 py-3`}>Status</th>
                <th className={`${labelCls} px-4 py-3`}>Protocolo</th>
                <th className={`${labelCls} px-4 py-3`}>Gravação</th>
                <th className={`${labelCls} px-4 py-3`}>Detecção</th>
                <th className={`${labelCls} px-4 py-3`}>Retenção</th>
                {isAdmin && (
                  <th className={`${labelCls} px-4 py-3 text-right`}>Ações</th>
                )}
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-surface-700/60">
              {cameras.map((cam) => (
                <tr key={cam.id}>
                  <td className="px-4 py-3 font-medium text-slate-900 dark:text-white">
                    {cam.name}
                    {!cam.enabled && (
                      <span className="ml-2 rounded bg-slate-200 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-slate-500 dark:bg-surface-700 dark:text-slate-400">
                        Desabilitada
                      </span>
                    )}
                  </td>
                  <td className="px-4 py-3">
                    <CameraStatusBadge status={statusMap[cam.id]} withLabel />
                  </td>
                  <td className="px-4 py-3 uppercase text-slate-600 dark:text-slate-400">
                    {cam.protocol}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {RECORDING_MODE_PT[cam.recording_mode]}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {cam.detect_objects ? `Objetos · ${cam.detect_fps} fps` : 'Movimento'}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {cam.retention_days_continuous} d / {cam.retention_days_event} d
                  </td>
                  {isAdmin && (
                    <td className="px-4 py-3">
                      <div className="flex justify-end gap-1">
                        <button
                          type="button"
                          className={btnIcon}
                          aria-label={`Editar ${cam.name}`}
                          onClick={() => setEditing(cam)}
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          type="button"
                          className={btnIcon}
                          aria-label={`Excluir ${cam.name}`}
                          onClick={() => setDeleting(cam)}
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {adding && isAdmin && <AddCameraWizard onClose={() => setAdding(false)} />}
      {editing && isAdmin && (
        <EditCameraModal camera={editing} onClose={() => setEditing(null)} />
      )}

      {deleting && isAdmin && (
        <Modal title="Excluir câmera" onClose={() => setDeleting(null)}>
          <div className="space-y-4">
            <p className="text-sm text-slate-700 dark:text-slate-300">
              Tem certeza que deseja excluir a câmera{' '}
              <strong>{deleting.name}</strong>? As zonas, agendamentos e configurações associadas
              serão removidos.
            </p>
            {deleteMutation.isError && (
              <p className="text-sm text-red-500">
                {deleteMutation.error instanceof Error
                  ? deleteMutation.error.message
                  : 'Falha ao excluir câmera.'}
              </p>
            )}
            <div className="flex justify-end gap-2">
              <button type="button" className={btnSecondary} onClick={() => setDeleting(null)}>
                Cancelar
              </button>
              <button
                type="button"
                className={btnDanger}
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(deleting.id)}
              >
                <Trash2 className="h-4 w-4" aria-hidden />
                {deleteMutation.isPending ? 'Excluindo…' : 'Excluir'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}
