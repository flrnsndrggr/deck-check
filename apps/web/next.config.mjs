function sanitizeApiBase(raw) {
  const trimmed = String(raw || "").trim().replace(/^[\s'"]+|[\s'"]+$/g, "");
  const match = trimmed.match(/https?:\/\/[^\s'"]+/i);
  return (match ? match[0] : trimmed).replace(/\/+$/g, "");
}

const apiProxyTarget = sanitizeApiBase(
  process.env.API_PROXY_TARGET ||
    process.env.NEXT_PUBLIC_API_BASE ||
    (process.env.NETLIFY ? "https://deck-check.onrender.com" : "http://127.0.0.1:8000"),
);

/** @type {import('next').NextConfig} */
const nextConfig = {
  experimental: {
    typedRoutes: false
  },
  async rewrites() {
    if (!apiProxyTarget) {
      return [];
    }
    return [
      {
        source: "/api/:path*",
        destination: `${apiProxyTarget}/api/:path*`,
      },
      {
        source: "/health/:path*",
        destination: `${apiProxyTarget}/health/:path*`,
      },
    ];
  },
  async headers() {
    return [
      {
        source: "/(.*)",
        headers: [
          { key: "X-Frame-Options", value: "DENY" },
          { key: "X-Content-Type-Options", value: "nosniff" },
          { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
          { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
          { key: "Cross-Origin-Opener-Policy", value: "same-origin" },
          { key: "Cross-Origin-Resource-Policy", value: "same-site" },
        ],
      },
    ];
  },
};

export default nextConfig;
