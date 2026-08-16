import '@testing-library/jest-dom/vitest';
import { afterEach } from 'vitest';
import { cleanup } from '@testing-library/react';

// vitest.config.ts does not set test.globals, so @testing-library/react's
// built-in auto-cleanup (which only fires if `afterEach` is already a
// global) never registers. Without this, DOM from one `it()` block leaks
// into the next within the same file. Wire cleanup explicitly instead of
// turning on globals repo-wide.
afterEach(() => cleanup());
