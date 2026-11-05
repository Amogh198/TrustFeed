import { Component, type ErrorInfo, type ReactNode } from 'react';

/** One broken view shouldn't blank the page in front of an audience. Changing page clears it. */
export default class ErrorBoundary extends Component<{ children: ReactNode; resetKey: string }, { failed: boolean }> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('A view failed to render', error, info.componentStack);
  }

  componentDidUpdate(previous: { resetKey: string }) {
    if (this.state.failed && previous.resetKey !== this.props.resetKey) this.setState({ failed: false });
  }

  render() {
    if (!this.state.failed) return this.props.children;
    return (
      <div className="page">
        <div className="unknown">
          <strong>This view couldn't be shown</strong>
          <div>
            <p>The saved case isn't affected. Reload the page, or go to <a href="#/cases">saved cases</a>.</p>
            <p><button type="button" className="button" onClick={() => window.location.reload()}>Reload the page</button></p>
          </div>
        </div>
      </div>
    );
  }
}
