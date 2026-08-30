import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { signIn } from 'next-auth/react';

vi.mock('next-auth/react', () => ({
  signIn: vi.fn(),
  useSession: () => ({ data: null, status: 'unauthenticated' }),
}));

import LoginPage from '@/app/login/page';

describe('LoginPage', () => {
  beforeEach(() => {
    vi.mocked(signIn).mockReset();
    vi.stubGlobal(
      'fetch',
      vi.fn(async () => new Response(null, { status: 201 })),
    );
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it('signs in with Google when "Login with Google" is clicked', async () => {
    render(<LoginPage />);

    await userEvent.click(screen.getByRole('button', { name: /login with google/i }));

    expect(signIn).toHaveBeenCalledWith('google', { callbackUrl: '/' });
  });

  it('signs in with credentials when the sign-in form is submitted', async () => {
    vi.mocked(signIn).mockResolvedValue({ error: null, status: 200, ok: true, url: '/' } as never);
    render(<LoginPage />);

    await userEvent.type(screen.getByPlaceholderText('Email'), 'a@x.com');
    await userEvent.type(screen.getByPlaceholderText('Password'), 'correct-horse-battery');
    await userEvent.click(screen.getByRole('button', { name: /^sign in$/i }));

    expect(signIn).toHaveBeenCalledWith('credentials', {
      email: 'a@x.com',
      password: 'correct-horse-battery',
      redirect: false,
      callbackUrl: '/',
    });
  });

  it('registers then signs in when the sign-up form is submitted', async () => {
    vi.mocked(signIn).mockResolvedValue({ error: null, status: 200, ok: true, url: '/' } as never);
    render(<LoginPage />);

    await userEvent.click(screen.getByRole('tab', { name: /sign up/i }));
    await userEvent.type(screen.getByPlaceholderText('Email'), 'new@x.com');
    await userEvent.type(screen.getByPlaceholderText('Password'), 'correct-horse-battery');
    await userEvent.click(screen.getByRole('button', { name: /create account/i }));

    expect(fetch).toHaveBeenCalledWith(
      expect.stringContaining('/auth/register'),
      expect.objectContaining({ method: 'POST' }),
    );
    expect(signIn).toHaveBeenCalledWith('credentials', {
      email: 'new@x.com',
      password: 'correct-horse-battery',
      redirect: false,
      callbackUrl: '/',
    });
  });

  it('shows an error and does not sign in when credentials are rejected', async () => {
    vi.mocked(signIn).mockResolvedValue({ error: 'CredentialsSignin', status: 401, ok: false, url: null } as never);
    render(<LoginPage />);

    await userEvent.type(screen.getByPlaceholderText('Email'), 'a@x.com');
    await userEvent.type(screen.getByPlaceholderText('Password'), 'wrong-password');
    await userEvent.click(screen.getByRole('button', { name: /^sign in$/i }));

    expect(await screen.findByRole('alert')).toHaveTextContent(/incorrect email or password/i);
  });
});
