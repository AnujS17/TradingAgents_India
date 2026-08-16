import { formatPrice } from '@/lib/format';
import type { Verdict } from '@/lib/api-client/client';

export function VerdictSummary({ verdict }: { verdict: Verdict | null }) {
  if (!verdict) return null;
  // `levels = {}` is a compile-time-only safety net, not a real runtime case.
  // The backend's `Verdict.levels` uses `Field(default_factory=TradeLevels)`
  // (api/schemas.py), and Pydantic leaves default-factory fields out of the
  // JSON Schema `required` array — so the generated types mark it optional
  // even though every actual API response populates it.
  const { rating, price_target, time_horizon, levels = {} } = verdict;

  return (
    <section aria-label="Verdict summary">
      <dl>
        <div>
          <dt>Rating</dt>
          <dd>{rating ?? 'Not set'}</dd>
        </div>
        <div>
          <dt>Action</dt>
          <dd>{levels.action ?? 'Not set'}</dd>
        </div>
        <div>
          <dt>Price target</dt>
          <dd>{formatPrice(price_target)}</dd>
        </div>
        <div>
          <dt>Time horizon</dt>
          <dd>{time_horizon ?? 'Not set'}</dd>
        </div>
        <div>
          <dt>Entry price</dt>
          <dd>{formatPrice(levels.entry_price)}</dd>
        </div>
        <div>
          <dt>Stop loss</dt>
          <dd>{formatPrice(levels.stop_loss)}</dd>
        </div>
        <div>
          <dt>Position sizing</dt>
          <dd>{levels.position_sizing ?? 'Not set'}</dd>
        </div>
      </dl>
      <p>
        Rating and action are independent: a Hold action under an Underweight
        rating means trim, not exit.
      </p>
    </section>
  );
}
