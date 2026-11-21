import path from "path"
import react from "@vitejs/plugin-react"
import { defineConfig } from "vite"
import { VitePWA } from "vite-plugin-pwa"
import { inspectAttr } from 'kimi-plugin-inspect-react'

// https://vite.dev/config/
export default defineConfig({
  base: './',
  plugins: [
    inspectAttr(),
    react(),
    VitePWA({
      registerType: "autoUpdate",
      includeAssets: ["icons/icon-192.png", "icons/icon-512.png"],
      manifest: {
        name: "NSE Paper Trading Desk",
        short_name: "Paper Desk",
        description:
          "Unified NSE paper-trading automation: dynamic token resolution, candle building, per-stock paper capital and continuous strategy evaluation.",
        theme_color: "#0b0e16",
        background_color: "#0b0e16",
        display: "standalone",
        icons: [
          { src: "icons/icon-192.png", sizes: "192x192", type: "image/png" },
          { src: "icons/icon-512.png", sizes: "512x512", type: "image/png" },
          {
            src: "icons/icon-512.png",
            sizes: "512x512",
            type: "image/png",
            purpose: "maskable",
          },
        ],
      },
      workbox: {
        // Network-first for the app shell and API-shaped requests so a
        // saved/republished version never serves stale HTML or fake data.
        navigateFallback: null,
        runtimeCaching: [
          {
            urlPattern: /\/api\/.*/i,
            handler: "NetworkOnly",
          },
          {
            urlPattern: /\.(?:js|css|png|woff2?)$/i,
            handler: "StaleWhileRevalidate",
            options: { cacheName: "desk-assets" },
          },
        ],
      },
    }),
  ],
  server: {
    port: 3000,
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
