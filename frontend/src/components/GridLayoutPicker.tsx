import { Grid2x2, Grid3x3, LayoutGrid, Square } from 'lucide-react';
import { useEffect, useState } from 'react';
import { useAuthStore } from '@/stores/auth';

export interface GridLayout {
  cols: number;
  rows: number;
}

const PRESETS: { layout: GridLayout; label: string; icon: typeof Square }[] = [
  { layout: { cols: 1, rows: 1 }, label: '1×1', icon: Square },
  { layout: { cols: 2, rows: 2 }, label: '2×2', icon: Grid2x2 },
  { layout: { cols: 3, rows: 3 }, label: '3×3', icon: Grid3x3 },
  { layout: { cols: 4, rows: 4 }, label: '4×4', icon: LayoutGrid },
];

function storageKey(userId: number | undefined): string {
  return `horus-grid-layout:${userId ?? 'anon'}`;
}

export function useGridLayout(): [GridLayout, (l: GridLayout) => void] {
  const userId = useAuthStore((s) => s.user?.id);
  const [layout, setLayoutState] = useState<GridLayout>(() => {
    try {
      const raw = localStorage.getItem(storageKey(userId));
      if (raw) {
        const parsed = JSON.parse(raw) as GridLayout;
        if (parsed.cols >= 1 && parsed.rows >= 1) return parsed;
      }
    } catch {
      /* ignore */
    }
    return { cols: 2, rows: 2 };
  });

  useEffect(() => {
    localStorage.setItem(storageKey(userId), JSON.stringify(layout));
  }, [layout, userId]);

  return [layout, setLayoutState];
}

interface Props {
  value: GridLayout;
  onChange: (layout: GridLayout) => void;
}

export default function GridLayoutPicker({ value, onChange }: Props) {
  const isPreset = PRESETS.some(
    (p) => p.layout.cols === value.cols && p.layout.rows === value.rows,
  );

  return (
    <div className="flex items-center gap-1" role="group" aria-label="Layout da grade">
      {PRESETS.map(({ layout, label, icon: Icon }) => {
        const active = layout.cols === value.cols && layout.rows === value.rows;
        return (
          <button
            key={label}
            type="button"
            aria-label={`Grade ${label}`}
            aria-pressed={active}
            onClick={() => onChange(layout)}
            className={`rounded-lg p-2 transition focus:outline-none focus-visible:ring-2 focus-visible:ring-blue-400 ${
              active
                ? 'bg-blue-600/15 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400'
                : 'text-slate-500 hover:bg-slate-200/70 dark:text-slate-400 dark:hover:bg-surface-700'
            }`}
          >
            <Icon className="h-5 w-5" aria-hidden />
          </button>
        );
      })}
      {/* custom layout: cols × rows selectors */}
      <div
        className={`ml-1 flex items-center gap-1 rounded-lg px-2 py-1 text-xs ${
          !isPreset
            ? 'bg-blue-600/15 text-blue-600 dark:bg-blue-500/20 dark:text-blue-400'
            : 'text-slate-500 dark:text-slate-400'
        }`}
      >
        <label className="sr-only" htmlFor="grid-cols">
          Colunas
        </label>
        <select
          id="grid-cols"
          value={value.cols}
          onChange={(e) => onChange({ ...value, cols: Number(e.target.value) })}
          className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs dark:border-surface-700 dark:bg-surface-900 dark:text-slate-200"
        >
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
        ×
        <label className="sr-only" htmlFor="grid-rows">
          Linhas
        </label>
        <select
          id="grid-rows"
          value={value.rows}
          onChange={(e) => onChange({ ...value, rows: Number(e.target.value) })}
          className="rounded border border-slate-300 bg-white px-1 py-0.5 text-xs dark:border-surface-700 dark:bg-surface-900 dark:text-slate-200"
        >
          {[1, 2, 3, 4, 5, 6].map((n) => (
            <option key={n} value={n}>
              {n}
            </option>
          ))}
        </select>
      </div>
    </div>
  );
}
