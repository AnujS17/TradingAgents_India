'use client';

import { useEffect, useRef } from 'react';

/**
 * Progressive-enhancement scroll reveal. The element is visible by default
 * (no inline opacity:0) — this hook adds `anim-ready` once mounted, which is
 * what actually arms the CSS hidden start state (see .u-reveal in
 * globals.css). If this hook never runs (JS disabled), the element stays at
 * its visible resting state. DESIGN.md §4 rule 1.
 */
export function useScrollReveal<T extends HTMLElement>() {
  const ref = useRef<T | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;

    el.classList.add('anim-ready');

    const observer = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (entry.isIntersecting) {
            entry.target.classList.add('is-in');
            observer.unobserve(entry.target);
          }
        }
      },
      { threshold: 0.15 },
    );
    observer.observe(el);

    return () => observer.disconnect();
  }, []);

  return ref;
}
