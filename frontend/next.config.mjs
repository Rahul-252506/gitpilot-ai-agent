/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Same-origin proxy for the GitPilot backend.
  //
  // The frontend calls its own origin (/api/health, /api/analyses, …) and this
  // rewrite forwards the request to the FastAPI backend on Render. The browser
  // therefore never makes a cross-origin request, which removes CORS as a
  // failure mode on localhost, on every Vercel preview URL, and on the
  // production alias alike.
  //
  // Baked in at build time from:
  //   - API_PROXY_TARGET (preferred, server-side only)
  //   - NEXT_PUBLIC_API_BASE_URL (same value the client used before)
  async rewrites() {
    const target = (
      process.env.API_PROXY_TARGET ||
      process.env.NEXT_PUBLIC_API_BASE_URL ||
      ""
    ).replace(/\/$/, "");
    if (!target) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${target}/api/:path*`,
      },
    ];
  },
};

export default nextConfig;
