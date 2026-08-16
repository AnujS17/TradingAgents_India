'use client'; // Error boundaries must be Client Components.

export default function Error({
  error,
  retry,
}: {
  error: Error & { digest?: string };
  retry: () => void;
}) {
  return (
    <main>
      <h1>Something went wrong loading this page.</h1>
      <p>
        The most likely cause is that the analysis service isn&apos;t running. It needs two
        processes up — the API (<code>uvicorn api.main:app --reload</code>) and the worker
        (<code>python -m api.worker</code>). Start them, then try again.
      </p>
      <p>Existing analyses are read-only and come back as soon as the API is reachable.</p>
      <button type="button" onClick={() => retry()}>
        Try again
      </button>
      {error.digest && <p>Error reference: {error.digest}</p>}
    </main>
  );
}
