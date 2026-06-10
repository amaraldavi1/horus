import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ChevronLeft, ChevronRight, Cpu, HardDrive, Pencil, Plus, Trash2 } from 'lucide-react';
import { useState } from 'react';
import {
  api,
  type Camera,
  type Notification,
  type NotificationCreate,
  type Role,
  type User,
} from '@/lib/api';
import { useCameras } from '@/hooks/data';
import { fmtDateTime, formatBytes } from '@/lib/format';
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

const ROLE_PT: Record<Role, string> = {
  admin: 'Administrador',
  operator: 'Operador',
  viewer: 'Visualizador',
};

// ---------------------------------------------------------------------------
// Shared: per-camera permission / filter checklist
// ---------------------------------------------------------------------------

function CameraChecklist({
  cameras,
  selected,
  onChange,
  disabled = false,
}: {
  cameras: Camera[];
  selected: number[];
  onChange: (ids: number[]) => void;
  disabled?: boolean;
}) {
  if (cameras.length === 0) {
    return <p className="text-sm text-slate-500 dark:text-slate-400">Nenhuma câmera cadastrada.</p>;
  }
  return (
    <div className="grid max-h-44 grid-cols-2 gap-1.5 overflow-y-auto rounded-lg border border-slate-200 p-3 dark:border-surface-700">
      {cameras.map((c) => (
        <label
          key={c.id}
          className={`inline-flex items-center gap-2 text-sm ${
            disabled ? 'text-slate-400 dark:text-slate-500' : 'text-slate-700 dark:text-slate-300'
          }`}
        >
          <input
            type="checkbox"
            disabled={disabled}
            checked={selected.includes(c.id)}
            onChange={(e) =>
              onChange(
                e.target.checked ? [...selected, c.id] : selected.filter((id) => id !== c.id),
              )
            }
          />
          {c.name}
        </label>
      ))}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Usuários
// ---------------------------------------------------------------------------

interface UserForm {
  name: string;
  email: string;
  password: string;
  role: Role;
  enabled: boolean;
  camera_ids: number[];
}

function UserModal({
  user,
  cameras,
  onClose,
}: {
  user: User | null;
  cameras: Camera[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<UserForm>(() =>
    user
      ? {
          name: user.name,
          email: user.email,
          password: '',
          role: user.role,
          enabled: user.enabled,
          camera_ids: [...user.camera_ids],
        }
      : { name: '', email: '', password: '', role: 'viewer', enabled: true, camera_ids: [] },
  );

  const saveMutation = useMutation({
    mutationFn: () => {
      const body = {
        name: form.name.trim(),
        email: form.email.trim(),
        role: form.role,
        enabled: form.enabled,
        camera_ids: form.role === 'admin' ? [] : form.camera_ids,
      };
      return user
        ? api.updateUser(user.id, form.password ? { ...body, password: form.password } : body)
        : api.createUser({ ...body, password: form.password });
    },
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] });
      onClose();
    },
  });

  const valid =
    form.name.trim() !== '' && form.email.trim() !== '' && (user !== null || form.password !== '');

  return (
    <Modal title={user ? `Editar usuário — ${user.name}` : 'Novo usuário'} onClose={onClose}>
      <div className="space-y-3">
        <Field label="Nome">
          <input
            className={inputCls}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
          />
        </Field>
        <Field label="E-mail">
          <input
            className={inputCls}
            type="email"
            value={form.email}
            onChange={(e) => setForm({ ...form, email: e.target.value })}
          />
        </Field>
        <Field
          label="Senha"
          hint={user ? 'Deixe em branco para manter a senha atual.' : undefined}
        >
          <input
            className={inputCls}
            type="password"
            value={form.password}
            autoComplete="new-password"
            onChange={(e) => setForm({ ...form, password: e.target.value })}
          />
        </Field>
        <Field label="Papel">
          <select
            className={selectCls}
            value={form.role}
            onChange={(e) => setForm({ ...form, role: e.target.value as Role })}
          >
            {(Object.keys(ROLE_PT) as Role[]).map((r) => (
              <option key={r} value={r}>
                {ROLE_PT[r]}
              </option>
            ))}
          </select>
        </Field>
        <div className="flex items-center gap-3">
          <Toggle
            checked={form.enabled}
            onChange={(v) => setForm({ ...form, enabled: v })}
            label="Usuário ativo"
          />
          <span className="text-sm text-slate-700 dark:text-slate-300">Ativo</span>
        </div>
        <Field
          label="Câmeras permitidas"
          hint={
            form.role === 'admin'
              ? 'Administradores têm acesso a todas as câmeras.'
              : 'Sem seleção = nenhum acesso.'
          }
        >
          <CameraChecklist
            cameras={cameras}
            selected={form.camera_ids}
            onChange={(ids) => setForm({ ...form, camera_ids: ids })}
            disabled={form.role === 'admin'}
          />
        </Field>

        {saveMutation.isError && (
          <p className="text-sm text-red-500">
            {saveMutation.error instanceof Error
              ? saveMutation.error.message
              : 'Falha ao salvar usuário.'}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>
            Cancelar
          </button>
          <button
            type="button"
            className={btnPrimary}
            disabled={!valid || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function UsersTab({ cameras }: { cameras: Camera[] }) {
  const queryClient = useQueryClient();
  const usersQuery = useQuery({ queryKey: ['users'], queryFn: api.listUsers });
  const [modal, setModal] = useState<{ open: boolean; user: User | null }>({
    open: false,
    user: null,
  });
  const [deleting, setDeleting] = useState<User | null>(null);

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.updateUser(id, { enabled }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['users'] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteUser(id),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['users'] });
      setDeleting(null);
    },
  });

  if (usersQuery.isLoading) return <LoadingBlock label="Carregando usuários…" />;
  if (usersQuery.isError) {
    return (
      <ErrorBlock message="Falha ao carregar usuários." onRetry={() => void usersQuery.refetch()} />
    );
  }

  const users = usersQuery.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          type="button"
          className={btnPrimary}
          onClick={() => setModal({ open: true, user: null })}
        >
          <Plus className="h-4 w-4" aria-hidden /> Novo usuário
        </button>
      </div>

      {users.length === 0 ? (
        <EmptyBlock message="Nenhum usuário cadastrado." />
      ) : (
        <div className={`${cardCls} overflow-x-auto`}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-surface-700">
                <th className={`${labelCls} px-4 py-3`}>Nome</th>
                <th className={`${labelCls} px-4 py-3`}>E-mail</th>
                <th className={`${labelCls} px-4 py-3`}>Papel</th>
                <th className={`${labelCls} px-4 py-3`}>Câmeras</th>
                <th className={`${labelCls} px-4 py-3`}>Ativo</th>
                <th className={`${labelCls} px-4 py-3 text-right`}>Ações</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-surface-700/60">
              {users.map((u) => (
                <tr key={u.id}>
                  <td className="px-4 py-3 font-medium text-slate-900 dark:text-white">{u.name}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">{u.email}</td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {ROLE_PT[u.role]}
                  </td>
                  <td className="px-4 py-3 text-slate-600 dark:text-slate-400">
                    {u.role === 'admin' ? 'Todas' : u.camera_ids.length}
                  </td>
                  <td className="px-4 py-3">
                    <Toggle
                      checked={u.enabled}
                      onChange={(v) => toggleMutation.mutate({ id: u.id, enabled: v })}
                      label={`Ativar/desativar ${u.name}`}
                    />
                  </td>
                  <td className="px-4 py-3">
                    <div className="flex justify-end gap-1">
                      <button
                        type="button"
                        className={btnIcon}
                        aria-label={`Editar ${u.name}`}
                        onClick={() => setModal({ open: true, user: u })}
                      >
                        <Pencil className="h-4 w-4" />
                      </button>
                      <button
                        type="button"
                        className={btnIcon}
                        aria-label={`Excluir ${u.name}`}
                        onClick={() => setDeleting(u)}
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      {modal.open && <UserModal user={modal.user} cameras={cameras} onClose={() => setModal({ open: false, user: null })} />}

      {deleting && (
        <Modal title="Excluir usuário" onClose={() => setDeleting(null)}>
          <div className="space-y-4">
            <p className="text-sm text-slate-700 dark:text-slate-300">
              Tem certeza que deseja excluir o usuário <strong>{deleting.name}</strong> (
              {deleting.email})?
            </p>
            {deleteMutation.isError && (
              <p className="text-sm text-red-500">
                {deleteMutation.error instanceof Error
                  ? deleteMutation.error.message
                  : 'Falha ao excluir usuário.'}
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
                {deleteMutation.isPending ? 'Excluindo…' : 'Excluir'}
              </button>
            </div>
          </div>
        </Modal>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Notificações
// ---------------------------------------------------------------------------

const KIND_PT: Record<Notification['kind'], string> = {
  push: 'Push',
  email: 'E-mail',
  webhook: 'Webhook',
};

const TARGET_LABEL: Record<Notification['kind'], { label: string; placeholder: string }> = {
  push: { label: 'Token / dispositivo', placeholder: 'Token do dispositivo' },
  email: { label: 'Endereço de e-mail', placeholder: 'alguem@exemplo.com' },
  webhook: { label: 'URL do webhook', placeholder: 'https://…' },
};

const EVENT_LABEL_OPTIONS = [
  { value: 'motion', label: 'Movimento' },
  { value: 'person', label: 'Pessoa' },
  { value: 'car', label: 'Veículo' },
  { value: 'animal', label: 'Animal' },
];

function NotificationModal({
  notification,
  cameras,
  onClose,
}: {
  notification: Notification | null;
  cameras: Camera[];
  onClose: () => void;
}) {
  const queryClient = useQueryClient();
  const [form, setForm] = useState<NotificationCreate>(() =>
    notification
      ? {
          kind: notification.kind,
          name: notification.name,
          target: notification.target,
          enabled: notification.enabled,
          camera_ids: [...notification.camera_ids],
          labels: [...notification.labels],
          min_confidence: notification.min_confidence,
        }
      : {
          kind: 'push',
          name: '',
          target: '',
          enabled: true,
          camera_ids: [],
          labels: [],
          min_confidence: null,
        },
  );

  const saveMutation = useMutation({
    mutationFn: () =>
      notification
        ? api.updateNotification(notification.id, form)
        : api.createNotification(form),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ['notifications'] });
      onClose();
    },
  });

  const toggleLabel = (value: string) => {
    setForm((f) => ({
      ...f,
      labels: f.labels.includes(value)
        ? f.labels.filter((l) => l !== value)
        : [...f.labels, value],
    }));
  };

  const target = TARGET_LABEL[form.kind];
  const valid = form.name.trim() !== '' && form.target.trim() !== '';

  return (
    <Modal
      title={notification ? `Editar canal — ${notification.name}` : 'Novo canal de notificação'}
      onClose={onClose}
    >
      <div className="space-y-3">
        <Field label="Tipo">
          <select
            className={selectCls}
            value={form.kind}
            onChange={(e) => setForm({ ...form, kind: e.target.value as Notification['kind'] })}
          >
            {(Object.keys(KIND_PT) as Notification['kind'][]).map((k) => (
              <option key={k} value={k}>
                {KIND_PT[k]}
              </option>
            ))}
          </select>
        </Field>
        <Field label="Nome">
          <input
            className={inputCls}
            value={form.name}
            onChange={(e) => setForm({ ...form, name: e.target.value })}
            placeholder="Ex.: Alertas noturnos"
          />
        </Field>
        <Field label={target.label}>
          <input
            className={inputCls}
            value={form.target}
            onChange={(e) => setForm({ ...form, target: e.target.value })}
            placeholder={target.placeholder}
          />
        </Field>
        <div className="flex items-center gap-3">
          <Toggle
            checked={form.enabled}
            onChange={(v) => setForm({ ...form, enabled: v })}
            label="Canal habilitado"
          />
          <span className="text-sm text-slate-700 dark:text-slate-300">Habilitado</span>
        </div>
        <Field label="Câmeras" hint="Sem seleção = todas as câmeras.">
          <CameraChecklist
            cameras={cameras}
            selected={form.camera_ids}
            onChange={(ids) => setForm({ ...form, camera_ids: ids })}
          />
        </Field>
        <Field label="Tipos de evento" hint="Sem seleção = todos os tipos.">
          <div className="flex flex-wrap gap-3">
            {EVENT_LABEL_OPTIONS.map((opt) => (
              <label
                key={opt.value}
                className="inline-flex items-center gap-1.5 text-sm text-slate-700 dark:text-slate-300"
              >
                <input
                  type="checkbox"
                  checked={form.labels.includes(opt.value)}
                  onChange={() => toggleLabel(opt.value)}
                />
                {opt.label}
              </label>
            ))}
          </div>
        </Field>
        <Field label="Confiança mínima (%)" hint="Vazio = qualquer confiança.">
          <input
            className={inputCls}
            type="number"
            min={0}
            max={100}
            value={form.min_confidence !== null ? Math.round(form.min_confidence * 100) : ''}
            onChange={(e) =>
              setForm({
                ...form,
                min_confidence: e.target.value === '' ? null : Number(e.target.value) / 100,
              })
            }
          />
        </Field>

        {saveMutation.isError && (
          <p className="text-sm text-red-500">
            {saveMutation.error instanceof Error
              ? saveMutation.error.message
              : 'Falha ao salvar canal.'}
          </p>
        )}

        <div className="flex justify-end gap-2">
          <button type="button" className={btnSecondary} onClick={onClose}>
            Cancelar
          </button>
          <button
            type="button"
            className={btnPrimary}
            disabled={!valid || saveMutation.isPending}
            onClick={() => saveMutation.mutate()}
          >
            {saveMutation.isPending ? 'Salvando…' : 'Salvar'}
          </button>
        </div>
      </div>
    </Modal>
  );
}

function NotificationsTab({ cameras }: { cameras: Camera[] }) {
  const queryClient = useQueryClient();
  const notificationsQuery = useQuery({
    queryKey: ['notifications'],
    queryFn: api.listNotifications,
  });
  const [modal, setModal] = useState<{ open: boolean; notification: Notification | null }>({
    open: false,
    notification: null,
  });

  const toggleMutation = useMutation({
    mutationFn: ({ id, enabled }: { id: number; enabled: boolean }) =>
      api.updateNotification(id, { enabled }),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  });

  const deleteMutation = useMutation({
    mutationFn: (id: number) => api.deleteNotification(id),
    onSuccess: () => void queryClient.invalidateQueries({ queryKey: ['notifications'] }),
  });

  if (notificationsQuery.isLoading) return <LoadingBlock label="Carregando canais…" />;
  if (notificationsQuery.isError) {
    return (
      <ErrorBlock
        message="Falha ao carregar canais de notificação."
        onRetry={() => void notificationsQuery.refetch()}
      />
    );
  }

  const channels = notificationsQuery.data ?? [];

  return (
    <div className="space-y-4">
      <div className="flex justify-end">
        <button
          type="button"
          className={btnPrimary}
          onClick={() => setModal({ open: true, notification: null })}
        >
          <Plus className="h-4 w-4" aria-hidden /> Novo canal
        </button>
      </div>

      {channels.length === 0 ? (
        <EmptyBlock message="Nenhum canal de notificação configurado." />
      ) : (
        <ul className="space-y-2">
          {channels.map((n) => (
            <li key={n.id} className={`${cardCls} flex flex-wrap items-center gap-3 p-4`}>
              <span className="rounded bg-blue-600/15 px-2 py-0.5 text-xs font-semibold text-blue-600 dark:bg-blue-500/20 dark:text-blue-400">
                {KIND_PT[n.kind]}
              </span>
              <div className="min-w-0 flex-1">
                <p className="truncate text-sm font-medium text-slate-900 dark:text-white">
                  {n.name}
                </p>
                <p className="truncate text-xs text-slate-500 dark:text-slate-400">
                  {n.target} ·{' '}
                  {n.camera_ids.length === 0 ? 'Todas as câmeras' : `${n.camera_ids.length} câmeras`}{' '}
                  · {n.labels.length === 0 ? 'Todos os eventos' : n.labels.join(', ')}
                </p>
              </div>
              <Toggle
                checked={n.enabled}
                onChange={(v) => toggleMutation.mutate({ id: n.id, enabled: v })}
                label={`Habilitar/desabilitar ${n.name}`}
              />
              <button
                type="button"
                className={btnIcon}
                aria-label={`Editar ${n.name}`}
                onClick={() => setModal({ open: true, notification: n })}
              >
                <Pencil className="h-4 w-4" />
              </button>
              <button
                type="button"
                className={btnIcon}
                aria-label={`Excluir ${n.name}`}
                disabled={deleteMutation.isPending}
                onClick={() => deleteMutation.mutate(n.id)}
              >
                <Trash2 className="h-4 w-4" />
              </button>
            </li>
          ))}
        </ul>
      )}

      {modal.open && (
        <NotificationModal
          notification={modal.notification}
          cameras={cameras}
          onClose={() => setModal({ open: false, notification: null })}
        />
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sistema
// ---------------------------------------------------------------------------

function AvailabilityList({
  title,
  entries,
  selected,
}: {
  title: string;
  entries: Record<string, boolean>;
  selected: string;
}) {
  return (
    <div>
      <p className={labelCls}>{title}</p>
      <ul className="space-y-1">
        {Object.entries(entries).map(([name, ok]) => (
          <li key={name} className="flex items-center gap-2 text-sm">
            <span
              className={`h-2 w-2 rounded-full ${ok ? 'bg-emerald-500' : 'bg-slate-300 dark:bg-surface-700'}`}
              aria-hidden
            />
            <span
              className={
                ok ? 'text-slate-900 dark:text-white' : 'text-slate-400 dark:text-slate-500'
              }
            >
              {name.toUpperCase()}
            </span>
            {name === selected && (
              <span className="rounded bg-blue-600/15 px-1.5 py-0.5 text-[10px] font-semibold uppercase text-blue-600 dark:bg-blue-500/20 dark:text-blue-400">
                Em uso
              </span>
            )}
          </li>
        ))}
      </ul>
    </div>
  );
}

function SystemTab({ cameras }: { cameras: Camera[] }) {
  const hardwareQuery = useQuery({
    queryKey: ['system-hardware'],
    queryFn: api.hardware,
    staleTime: 60_000,
  });
  const storageQuery = useQuery({
    queryKey: ['system-storage'],
    queryFn: api.storage,
    staleTime: 60_000,
  });

  const hw = hardwareQuery.data;
  const storage = storageQuery.data;
  const usagePct =
    storage && storage.total_bytes > 0
      ? storage.usage_pct || (storage.used_bytes / storage.total_bytes) * 100
      : 0;
  const cameraById = new Map(cameras.map((c) => [c.id, c]));

  return (
    <div className="grid gap-4 lg:grid-cols-2">
      {/* Hardware */}
      <div className={`${cardCls} p-4`}>
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
          <Cpu className="h-4 w-4 text-blue-500" aria-hidden /> Hardware
        </div>
        {hardwareQuery.isLoading && <LoadingBlock label="Carregando hardware…" />}
        {hardwareQuery.isError && (
          <ErrorBlock
            message="Relatório de hardware indisponível."
            onRetry={() => void hardwareQuery.refetch()}
          />
        )}
        {hw && (
          <div className="space-y-4">
            <div className="grid gap-4 sm:grid-cols-2">
              <AvailabilityList
                title="Decodificação"
                entries={hw.decode}
                selected={hw.selected.decode}
              />
              <AvailabilityList
                title="Inferência"
                entries={hw.inference}
                selected={hw.selected.inference}
              />
            </div>
            {hw.gpus.length > 0 && (
              <p className="text-sm text-slate-600 dark:text-slate-400">
                GPU: {hw.gpus.join(', ')}
              </p>
            )}
            <p className="text-xs text-slate-400 dark:text-slate-500">
              Atualizado em {fmtDateTime(hw.ts)}
            </p>
          </div>
        )}
      </div>

      {/* Storage */}
      <div className={`${cardCls} p-4`}>
        <div className="mb-3 flex items-center gap-2 text-sm font-medium text-slate-700 dark:text-slate-300">
          <HardDrive className="h-4 w-4 text-blue-500" aria-hidden /> Armazenamento
        </div>
        {storageQuery.isLoading && <LoadingBlock label="Carregando armazenamento…" />}
        {storageQuery.isError && (
          <ErrorBlock
            message="Relatório de armazenamento indisponível."
            onRetry={() => void storageQuery.refetch()}
          />
        )}
        {storage && (
          <div className="space-y-4">
            <div
              className="h-2.5 w-full overflow-hidden rounded-full bg-slate-200 dark:bg-surface-700"
              role="progressbar"
              aria-label="Uso de armazenamento"
              aria-valuenow={Math.round(usagePct)}
              aria-valuemin={0}
              aria-valuemax={100}
            >
              <div
                className={`h-full rounded-full ${
                  usagePct >= 90 ? 'bg-red-500' : usagePct >= 75 ? 'bg-amber-400' : 'bg-blue-500'
                }`}
                style={{ width: `${Math.min(100, usagePct)}%` }}
              />
            </div>
            <p className="text-sm text-slate-600 dark:text-slate-400">
              {formatBytes(storage.used_bytes)} de {formatBytes(storage.total_bytes)} usados (
              {usagePct.toFixed(0)}%) · {formatBytes(storage.free_bytes)} livres
            </p>
            {(storage.recordings_bytes !== undefined ||
              storage.events_bytes !== undefined ||
              storage.snapshots_bytes !== undefined) && (
              <p className="text-xs text-slate-500 dark:text-slate-400">
                Gravações {formatBytes(storage.recordings_bytes ?? 0)} · Eventos{' '}
                {formatBytes(storage.events_bytes ?? 0)} · Snapshots{' '}
                {formatBytes(storage.snapshots_bytes ?? 0)}
              </p>
            )}
            {storage.per_camera && storage.per_camera.length > 0 && (
              <table className="w-full text-left text-sm">
                <thead>
                  <tr className="border-b border-slate-200 dark:border-surface-700">
                    <th className={`${labelCls} py-2`}>Câmera</th>
                    <th className={`${labelCls} py-2`}>Uso</th>
                    <th className={`${labelCls} py-2`}>Retenção (cont./evento)</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-slate-100 dark:divide-surface-700/60">
                  {storage.per_camera.map((pc) => {
                    const cam = cameraById.get(pc.camera_id);
                    return (
                      <tr key={pc.camera_id}>
                        <td className="py-2 text-slate-900 dark:text-white">
                          {cam?.name ?? `Câmera ${pc.camera_id}`}
                        </td>
                        <td className="py-2 text-slate-600 dark:text-slate-400">
                          {formatBytes(pc.bytes)}
                        </td>
                        <td className="py-2 text-slate-600 dark:text-slate-400">
                          {cam
                            ? `${cam.retention_days_continuous} d / ${cam.retention_days_event} d`
                            : '—'}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Auditoria
// ---------------------------------------------------------------------------

const AUDIT_PAGE_SIZE = 50;

function AuditTab() {
  const [page, setPage] = useState(1);
  const auditQuery = useQuery({
    queryKey: ['audit', page],
    queryFn: () => api.audit({ page, size: AUDIT_PAGE_SIZE }),
    placeholderData: (prev) => prev,
  });

  if (auditQuery.isLoading) return <LoadingBlock label="Carregando auditoria…" />;
  if (auditQuery.isError) {
    return (
      <ErrorBlock
        message="Falha ao carregar registros de auditoria."
        onRetry={() => void auditQuery.refetch()}
      />
    );
  }

  const data = auditQuery.data;
  const entries = data?.items ?? [];
  const totalPages = Math.max(1, Math.ceil((data?.total ?? 0) / AUDIT_PAGE_SIZE));

  return (
    <div className="space-y-4">
      {entries.length === 0 ? (
        <EmptyBlock message="Nenhum registro de auditoria." />
      ) : (
        <div className={`${cardCls} overflow-x-auto`}>
          <table className="w-full text-left text-sm">
            <thead>
              <tr className="border-b border-slate-200 dark:border-surface-700">
                <th className={`${labelCls} px-4 py-3`}>Usuário</th>
                <th className={`${labelCls} px-4 py-3`}>Ação</th>
                <th className={`${labelCls} px-4 py-3`}>Alvo</th>
                <th className={`${labelCls} px-4 py-3`}>IP</th>
                <th className={`${labelCls} px-4 py-3`}>Data</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-slate-100 dark:divide-surface-700/60">
              {entries.map((entry) => (
                <tr key={entry.id} title={entry.details ?? undefined}>
                  <td className="px-4 py-2.5 text-slate-900 dark:text-white">
                    {entry.user_email ?? 'Sistema'}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600 dark:text-slate-400">{entry.action}</td>
                  <td className="px-4 py-2.5 text-slate-600 dark:text-slate-400">
                    {entry.target ?? '—'}
                  </td>
                  <td className="px-4 py-2.5 font-mono text-xs text-slate-600 dark:text-slate-400">
                    {entry.ip ?? '—'}
                  </td>
                  <td className="px-4 py-2.5 text-slate-600 dark:text-slate-400">
                    {fmtDateTime(entry.ts)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

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
          Página {page} de {totalPages}
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
    </div>
  );
}

// ---------------------------------------------------------------------------
// Page
// ---------------------------------------------------------------------------

type Tab = 'users' | 'notifications' | 'system' | 'audit';

const TABS: { id: Tab; label: string }[] = [
  { id: 'users', label: 'Usuários' },
  { id: 'notifications', label: 'Notificações' },
  { id: 'system', label: 'Sistema' },
  { id: 'audit', label: 'Auditoria' },
];

export default function Settings() {
  const camerasQuery = useCameras();
  const [tab, setTab] = useState<Tab>('users');
  const cameras = camerasQuery.data ?? [];

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold text-slate-900 dark:text-white">Configurações</h1>

      <div
        className="flex gap-1 overflow-x-auto border-b border-slate-200 dark:border-surface-700"
        role="tablist"
        aria-label="Seções de configurações"
      >
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={`-mb-px whitespace-nowrap border-b-2 px-3 py-2 text-sm font-medium transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
              tab === t.id
                ? 'border-blue-600 text-blue-600 dark:text-blue-400'
                : 'border-transparent text-slate-500 hover:text-slate-900 dark:text-slate-400 dark:hover:text-white'
            }`}
          >
            {t.label}
          </button>
        ))}
      </div>

      {tab === 'users' && <UsersTab cameras={cameras} />}
      {tab === 'notifications' && <NotificationsTab cameras={cameras} />}
      {tab === 'system' && <SystemTab cameras={cameras} />}
      {tab === 'audit' && <AuditTab />}
    </div>
  );
}
