import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { signIn } from 'next-auth/react';

vi.mock('next-auth/react', () => ({
  signIn: vi.fn(),
  useSession: () => ({ data: null, status: 'unauthenticated' }),
}));

import LoginPage from '@/app/login/page';

describe('LoginPage', () => {
  it('signs in with Google when the button is clicked', async () => {
    render(<LoginPage />);

    await userEvent.click(screen.getByRole('button', { name: /sign in with google/i }));

    expect(signIn).toHaveBeenCalledWith('google', { callbackUrl: '/' });
  });
});
