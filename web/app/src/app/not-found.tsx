import Link from 'next/link';

export default function NotFound() {
  return (
    <main>
      <h1>Run not found.</h1>
      <p>
        This analysis doesn&apos;t exist — the link may be mistyped, or it may point at a run from
        a database that has since been reset.
      </p>
      <Link href="/">Back to search</Link>
    </main>
  );
}
