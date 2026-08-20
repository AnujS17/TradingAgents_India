import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { LiveStream } from '@/components/research/LiveStream';

describe('LiveStream', () => {
  it('renders nothing when eventsByNode is empty', () => {
    const { container } = render(<LiveStream eventsByNode={{}} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('renders one card per team, and streamed text under the agent that spoke', () => {
    render(<LiveStream eventsByNode={{ 'Bull Researcher': 'Bull case building...' }} />);

    // All five teams are shown, not just the one with activity.
    expect(screen.getByText('Analysts')).toBeInTheDocument();
    expect(screen.getByText('Research')).toBeInTheDocument();
    // 'Trader' is both the team name and its lone agent's name, so it
    // legitimately appears twice (team header + agent row).
    expect(screen.getAllByText('Trader')).toHaveLength(2);
    expect(screen.getByText('Risk panel')).toBeInTheDocument();
    expect(screen.getByText('Portfolio')).toBeInTheDocument();

    expect(screen.getByText('Bull case building...')).toBeInTheDocument();
  });

  it('marks a team Speaking only when one of its own agents has content', () => {
    render(<LiveStream eventsByNode={{ 'Bull Researcher': 'Bull case building...' }} />);

    expect(screen.getAllByText('Speaking')).toHaveLength(1); // only Research
    expect(screen.getAllByText('Waiting')).toHaveLength(4); // the other four teams
  });
});
