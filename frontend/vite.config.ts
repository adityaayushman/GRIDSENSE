import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: { port: 5173 },
  build: {
    // Vendor libraries change far less often than the app. Giving them their own chunks
    // means a code change re-downloads tens of kilobytes, not the charting library, and
    // the browser can fetch and parse the chunks in parallel.
    rollupOptions: {
      output: {
        manualChunks(id: string) {
          if (!id.includes("node_modules")) return undefined;
          if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return "react";
          if (/[\\/]node_modules[\\/](recharts|recharts-scale|d3-[^\\/]+|victory-vendor|internmap|decimal\.js-light|fast-equals|lodash|react-smooth|react-transition-group|clsx|tiny-invariant|eventemitter3)[\\/]/.test(id)) return "charts";
          if (/[\\/]node_modules[\\/]lucide-react[\\/]/.test(id)) return "icons";
          return undefined;
        },
      },
    },
    chunkSizeWarningLimit: 450,
  },
});
