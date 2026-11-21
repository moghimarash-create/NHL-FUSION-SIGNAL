import { defineConfig, type Plugin } from "vite";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import path from "path";
import fs from "fs";
import zlib from "zlib";
import { spawn } from "child_process";
import net from "net";

function ensureApiServerRunning() {
  const check = () => {
    const sock = new net.Socket();
    sock.setTimeout(1000);
    sock.once("connect", () => {
      sock.destroy();
    });
    const startIt = () => {
      sock.destroy();
      const apiDir = path.resolve(import.meta.dirname, "..", "api-server");
      const child = spawn("node", ["--enable-source-maps", "./dist/index.mjs"], {
        cwd: apiDir,
        env: { ...process.env, PORT: "8080", NODE_ENV: "development" },
        stdio: "ignore",
        detached: true,
      });
      child.unref();
    };
    sock.once("error", startIt);
    sock.once("timeout", startIt);
    sock.connect(8080, "127.0.0.1");
  };
  check();
  setInterval(check, 5000).unref();
}

const rawPort = process.env.PORT || "8081";
const port = Number(rawPort);

if (Number.isNaN(port) || port <= 0) {
  throw new Error(`Invalid PORT value: "${rawPort}"`);
}

const basePath = process.env.BASE_PATH || "./";

const iframeAndGzipPlugin = (): Plugin => {
  const publicDir = path.resolve(import.meta.dirname, "public");
  const distPublicDir = path.resolve(import.meta.dirname, "dist/public");
  const gzipCache = new Map<string, { mtimeMs: number; buf: Buffer }>();

  const getMimeType = (p: string): string => {
    if (p.endsWith(".html")) return "text/html; charset=utf-8";
    if (p.endsWith(".svg")) return "image/svg+xml";
    if (p.endsWith(".json")) return "application/json; charset=utf-8";
    if (p.endsWith(".js") || p.endsWith(".mjs")) return "application/javascript; charset=utf-8";
    if (p.endsWith(".css")) return "text/css; charset=utf-8";
    return "application/octet-stream";
  };

  const attachMiddleware = (middlewares: any) => {
    middlewares.use((req: any, res: any, next: any) => {
      res.removeHeader("X-Frame-Options");
      res.setHeader("Content-Security-Policy", "frame-ancestors *");
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Methods", "GET, POST, PUT, DELETE, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "*");

      if (req.method === "OPTIONS") {
        res.statusCode = 204;
        res.end();
        return;
      }

      const rawPath = (req.url || "/").split("?")[0];
      const urlPath = rawPath === "/" || rawPath === "" ? "/index.html" : rawPath;
      const acceptEncoding = String(req.headers["accept-encoding"] || "");

      if (
        (req.method === "GET" || req.method === "HEAD") &&
        (urlPath === "/index.html" ||
          urlPath.startsWith("/assets/") ||
          urlPath.endsWith(".json") ||
          urlPath.endsWith(".svg")) &&
        !urlPath.startsWith("/api/") &&
        !urlPath.startsWith("/fusion-rpc/")
      ) {
        const cleanRel = urlPath.replace(/^\/+/, "");
        for (const baseDir of [distPublicDir, publicDir]) {
          const filePath = path.join(baseDir, cleanRel);
          if (filePath.startsWith(baseDir) && fs.existsSync(filePath)) {
            try {
              const st = fs.statSync(filePath);
              if (st.isFile()) {
                const useGzip =
                  acceptEncoding.includes("gzip") &&
                  (urlPath.endsWith(".json") || urlPath.endsWith(".js") || urlPath.endsWith(".css"));
                res.statusCode = 200;
                res.setHeader("Content-Type", getMimeType(urlPath));
                if (useGzip) {
                  let cached = gzipCache.get(filePath);
                  if (!cached || cached.mtimeMs !== st.mtimeMs) {
                    const rawBuf = fs.readFileSync(filePath);
                    cached = { mtimeMs: st.mtimeMs, buf: zlib.gzipSync(rawBuf, { level: 1 }) };
                    gzipCache.set(filePath, cached);
                  }
                  res.setHeader("Content-Encoding", "gzip");
                  res.setHeader("Vary", "Accept-Encoding");
                  res.setHeader("Content-Length", String(cached.buf.length));
                  if (req.method === "HEAD") {
                    res.end();
                  } else {
                    res.end(cached.buf);
                  }
                } else {
                  const rawBuf = fs.readFileSync(filePath);
                  res.setHeader("Content-Length", String(rawBuf.length));
                  if (req.method === "HEAD") {
                    res.end();
                  } else {
                    res.end(rawBuf);
                  }
                }
                return;
              }
            } catch {
              // fall through
            }
          }
        }
      }

      next();
    });
  };

  return {
    name: "iframe-and-gzip-support",
    configureServer(server) {
      ensureApiServerRunning();
      attachMiddleware(server.middlewares);
    },
    configurePreviewServer(server) {
      ensureApiServerRunning();
      attachMiddleware(server.middlewares);
    },
  };
};

const sharedHeaders = {
  "Access-Control-Allow-Origin": "*",
  "Content-Security-Policy": "frame-ancestors *",
};

const sharedProxy = {
  "/fusion-rpc": {
    target: "http://127.0.0.1:8080",
    changeOrigin: true,
    rewrite: (p: string) => p.replace(/^\/fusion-rpc/, "/api"),
  },
  "/api": {
    target: "http://127.0.0.1:8080",
    changeOrigin: true,
  },
};

export default defineConfig({
  base: basePath,
  plugins: [
    iframeAndGzipPlugin(),
    react(),
    tailwindcss(),
  ],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
      "@assets": path.resolve(import.meta.dirname, "..", "..", "attached_assets"),
    },
    dedupe: ["react", "react-dom"],
  },
  root: path.resolve(import.meta.dirname),
  build: {
    outDir: path.resolve(import.meta.dirname, "dist/public"),
    emptyOutDir: true,
  },
  server: {
    port,
    strictPort: true,
    host: "0.0.0.0",
    allowedHosts: true,
    headers: sharedHeaders,
    watch: { ignored: ["**/public/fusion_nhl_master.json"] },
    proxy: sharedProxy,
    fs: {
      strict: true,
    },
  },
  preview: {
    port,
    strictPort: true,
    host: "0.0.0.0",
    allowedHosts: true,
    headers: sharedHeaders,
    proxy: sharedProxy,
  },
});
