import React from 'react';

interface State {
  error: Error | null;
}

/** Last-resort boundary: a render crash shows a recoverable message instead
 *  of unmounting the entire app into a blank page. */
export class ErrorBoundary extends React.Component<React.PropsWithChildren, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  render() {
    if (this.state.error) {
      return (
        <div className="flex min-h-screen flex-col items-center justify-center gap-4 bg-neutral-50 p-6 text-center dark:bg-neutral-950">
          <h1 className="text-lg font-semibold text-neutral-900 dark:text-neutral-100">
            Algo deu errado
          </h1>
          <p className="max-w-md text-sm text-neutral-600 dark:text-neutral-400">
            Ocorreu um erro inesperado na interface. Recarregue a página; se o
            problema persistir, verifique o console do navegador.
          </p>
          <pre className="max-w-full overflow-auto rounded bg-neutral-100 p-3 text-left text-xs text-red-600 dark:bg-neutral-900 dark:text-red-400">
            {this.state.error.message}
          </pre>
          <button
            onClick={() => window.location.reload()}
            className="rounded-lg bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Recarregar
          </button>
        </div>
      );
    }
    return this.props.children;
  }
}
