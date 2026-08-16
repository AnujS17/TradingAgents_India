import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  /* config options here */
  // The E2E suite (web/app/tests/e2e) drives the dev server via
  // 127.0.0.1, while `next dev` binds to `localhost` by default. Next.js
  // treats these as distinct origins and blocks dev-asset/HMR requests
  // from ones not on this list, which silently breaks hydration (see
  // node_modules/next/dist/docs/.../allowedDevOrigins.md).
  allowedDevOrigins: ['127.0.0.1', 'localhost'],
};

export default nextConfig;
