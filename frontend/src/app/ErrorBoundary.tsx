import { Component, type ErrorInfo, type ReactNode } from "react";

import { Button, Callout } from "@/components/ui";

type State = { error: Error | null };

/** Keeps one broken view from blanking the whole app; the rail stays usable. The Layout keys it by pathname, so
 *  moving to another view also clears the error. */
export class ErrorBoundary extends Component<{ children: ReactNode }, State> {
  state: State = { error: null };

  static getDerivedStateFromError(error: Error): State {
    return { error };
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error("view crashed", error, info.componentStack);
  }

  render() {
    if (!this.state.error) return this.props.children;
    return (
      <Callout tone="red" role="alert">
        <p>
          <b>This view hit an error:</b> {this.state.error.message}
        </p>
        <p className="small muted">Nothing was saved by the failure. Other views keep working.</p>
        <Button size="sm" onClick={() => this.setState({ error: null })}>
          Try again
        </Button>
      </Callout>
    );
  }
}
