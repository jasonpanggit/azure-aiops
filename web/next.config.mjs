/** @type {import('next').NextConfig} */
const nextConfig = {
  // Emits a self-contained server bundle with only the traced production
  // dependencies, so the container image does not need to ship node_modules.
  output: "standalone",
};

export default nextConfig;
