/** Catches render-time errors anywhere below and shows a friendly fallback
 *  instead of letting React unmount the whole app (which would dump the user
 *  back to the home/picker view). */
import { Component, type ReactNode } from 'react';

interface Props {
  children: ReactNode;
  fallback?: (err: Error, reset: () => void) => ReactNode;
}

interface State {
  err: Error | null;
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { err: null };

  static getDerivedStateFromError(err: Error): State {
    return { err };
  }

  componentDidCatch(err: Error, info: unknown) {
    // eslint-disable-next-line no-console
    console.error('ErrorBoundary caught:', err, info);
  }

  reset = () => this.setState({ err: null });

  render() {
    if (this.state.err) {
      if (this.props.fallback) return this.props.fallback(this.state.err, this.reset);
      return (
        <div className="failure-block">
          <strong>Something broke.</strong>{' '}
          <code>{this.state.err.message || String(this.state.err)}</code>
          <div style={{ marginTop: 8 }}>
            <button onClick={this.reset}>Try again</button>
          </div>
        </div>
      );
    }
    return this.props.children;
  }
}
