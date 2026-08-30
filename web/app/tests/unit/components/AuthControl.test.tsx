import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { signOut, useSession } from 'next-auth/react';

vi.mock('next-auth/react', () => ({
  signOut: vi.fn(),
  useSession: vi.fn(),
}));

import { AuthControl } from '@/components/AuthControl';

describe('AuthControl', () => {
  it('shows a distinct Sign in / Sign up link to the login page when signed out', () => {
    vi.mocked(useSession).mockReturnValue({ data: null, status: 'unauthenticated' } as never);
    render(<AuthControl />);

    const link = screen.getByRole('link', { name: /sign in \/ sign up/i });
    expect(link).toHaveAttribute('href', '/login');
  });

  it('renders nothing while the session is loading', () => {
    vi.mocked(useSession).mockReturnValue({ data: null, status: 'loading' } as never);
    const { container } = render(<AuthControl />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows the account avatar image, not a Sign out link, when signed in', () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: 'A User', email: 'a@x.com', image: 'https://example.com/pic.jpg' }, expires: '' },
      status: 'authenticated',
    } as never);
    render(<AuthControl />);

    const img = screen.getByRole('img');
    expect(img).toHaveAttribute('src', 'https://example.com/pic.jpg');
    expect(screen.queryByRole('link', { name: /sign in/i })).not.toBeInTheDocument();
  });

  it('falls back to an initial when the account has no avatar image', () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: 'Zed', email: 'z@x.com', image: null }, expires: '' },
      status: 'authenticated',
    } as never);
    render(<AuthControl />);

    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByText('Z')).toBeInTheDocument();
  });

  it('signs out when the avatar menu\'s Sign out item is activated', async () => {
    vi.mocked(useSession).mockReturnValue({
      data: { user: { name: 'A User', email: 'a@x.com', image: null }, expires: '' },
      status: 'authenticated',
    } as never);
    render(<AuthControl />);

    await userEvent.click(screen.getByRole('menuitem', { name: /sign out/i }));

    expect(signOut).toHaveBeenCalled();
  });
});
