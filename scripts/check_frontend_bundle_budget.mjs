#!/usr/bin/env node
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import zlib from "node:zlib";

const DEFAULT_MANIFEST_PATH = path.join("frontend", "dist", ".vite", "manifest.json");
const DEFAULT_INITIAL_JS_BUDGET_KB = 200;
const DEFAULT_INITIAL_CSS_BUDGET_KB = 80;
const DEFAULT_ROUTE_CHUNK_BUDGET_KB = 100;

function parseBudget(value, fallback) {
  if (!value) {
    return fallback;
  }

  const parsed = Number(value);
  if (!Number.isFinite(parsed) || parsed <= 0) {
    return fallback;
  }
  return parsed;
}

function formatKb(bytes) {
  return `${(bytes / 1024).toFixed(2)} kB`;
}

function readManifest(manifestPath) {
  if (!fs.existsSync(manifestPath)) {
    throw new Error(
      `Bundle manifest not found at ${manifestPath}. Run \`npm --prefix frontend run build\` first.`,
    );
  }

  const raw = fs.readFileSync(manifestPath, "utf8");
  return JSON.parse(raw);
}

function gzipSize(filePath) {
  const raw = fs.readFileSync(filePath);
  return zlib.gzipSync(raw).length;
}

function collectStaticChunkKeys(manifest, chunkKey, seen = new Set()) {
  if (seen.has(chunkKey)) {
    return seen;
  }

  const chunk = manifest[chunkKey];
  if (!chunk) {
    return seen;
  }

  seen.add(chunkKey);
  for (const importedChunkKey of chunk.imports || []) {
    collectStaticChunkKeys(manifest, importedChunkKey, seen);
  }

  return seen;
}

function resolveChunkFile(distDir, relativeFile) {
  return path.resolve(distDir, relativeFile);
}

function getEntryKeys(manifest) {
  return Object.entries(manifest)
    .filter(([, chunk]) => chunk && chunk.isEntry)
    .map(([chunkKey]) => chunkKey);
}

function getInitialBundleSizes(manifest, distDir) {
  const entryKeys = getEntryKeys(manifest);
  if (entryKeys.length === 0) {
    throw new Error("No entry chunks were found in manifest.json.");
  }

  const jsFiles = new Set();
  const cssFiles = new Set();

  for (const entryKey of entryKeys) {
    const staticKeys = collectStaticChunkKeys(manifest, entryKey);
    for (const staticKey of staticKeys) {
      const chunk = manifest[staticKey];
      if (!chunk) {
        continue;
      }

      if (chunk.file && chunk.file.endsWith(".js")) {
        jsFiles.add(resolveChunkFile(distDir, chunk.file));
      }

      for (const cssFile of chunk.css || []) {
        cssFiles.add(resolveChunkFile(distDir, cssFile));
      }
    }
  }

  const initialJsGzipBytes = [...jsFiles].reduce((sum, filePath) => sum + gzipSize(filePath), 0);
  const initialCssGzipBytes = [...cssFiles].reduce((sum, filePath) => sum + gzipSize(filePath), 0);

  return {
    entryKeys,
    initialJsGzipBytes,
    initialCssGzipBytes,
  };
}

function getDynamicRouteChunks(manifest, distDir) {
  const dynamicChunks = [];

  for (const [chunkKey, chunk] of Object.entries(manifest)) {
    if (!chunk?.isDynamicEntry || !chunk.file || !chunk.file.endsWith(".js")) {
      continue;
    }

    const absolutePath = resolveChunkFile(distDir, chunk.file);
    dynamicChunks.push({
      key: chunkKey,
      file: chunk.file,
      gzipBytes: gzipSize(absolutePath),
    });
  }

  return dynamicChunks;
}

function printHeader(initialJsBudgetKb, initialCssBudgetKb, routeChunkBudgetKb) {
  console.log("Frontend bundle budget report");
  console.log(`- Initial JS gzip budget: ${initialJsBudgetKb} kB`);
  console.log(`- Initial CSS gzip budget: ${initialCssBudgetKb} kB`);
  console.log(`- Per-route chunk gzip budget: ${routeChunkBudgetKb} kB`);
}

function main() {
  const manifestPath = path.resolve(
    process.cwd(),
    process.argv[2] || process.env.FRONTEND_MANIFEST_PATH || DEFAULT_MANIFEST_PATH,
  );
  const distDir = path.resolve(path.dirname(manifestPath), "..");

  const initialJsBudgetKb = parseBudget(
    process.env.BUDGET_INITIAL_JS_GZIP_KB,
    DEFAULT_INITIAL_JS_BUDGET_KB,
  );
  const initialCssBudgetKb = parseBudget(
    process.env.BUDGET_INITIAL_CSS_GZIP_KB,
    DEFAULT_INITIAL_CSS_BUDGET_KB,
  );
  const routeChunkBudgetKb = parseBudget(
    process.env.BUDGET_ROUTE_CHUNK_GZIP_KB,
    DEFAULT_ROUTE_CHUNK_BUDGET_KB,
  );

  const initialJsBudgetBytes = Math.round(initialJsBudgetKb * 1024);
  const initialCssBudgetBytes = Math.round(initialCssBudgetKb * 1024);
  const routeChunkBudgetBytes = Math.round(routeChunkBudgetKb * 1024);

  const manifest = readManifest(manifestPath);
  const { entryKeys, initialJsGzipBytes, initialCssGzipBytes } = getInitialBundleSizes(
    manifest,
    distDir,
  );
  const dynamicRouteChunks = getDynamicRouteChunks(manifest, distDir);

  printHeader(initialJsBudgetKb, initialCssBudgetKb, routeChunkBudgetKb);
  console.log(`- Manifest: ${manifestPath}`);
  console.log(`- Entry chunks: ${entryKeys.join(", ")}`);
  console.log(`- Initial JS gzip size: ${formatKb(initialJsGzipBytes)}`);
  console.log(`- Initial CSS gzip size: ${formatKb(initialCssGzipBytes)}`);

  let hasFailure = false;

  if (initialJsGzipBytes > initialJsBudgetBytes) {
    hasFailure = true;
    console.error(
      `FAIL: Initial JS gzip size ${formatKb(initialJsGzipBytes)} exceeds ${initialJsBudgetKb} kB.`,
    );
  } else {
    console.log("PASS: Initial JS budget.");
  }

  if (initialCssGzipBytes > initialCssBudgetBytes) {
    hasFailure = true;
    console.error(
      `FAIL: Initial CSS gzip size ${formatKb(initialCssGzipBytes)} exceeds ${initialCssBudgetKb} kB.`,
    );
  } else {
    console.log("PASS: Initial CSS budget.");
  }

  if (dynamicRouteChunks.length === 0) {
    console.log("INFO: No dynamic route chunks found; per-route budget check skipped.");
  } else {
    console.log("Dynamic route chunks (gzip):");
    for (const chunk of dynamicRouteChunks) {
      console.log(`- ${chunk.file} (${chunk.key}): ${formatKb(chunk.gzipBytes)}`);
      if (chunk.gzipBytes > routeChunkBudgetBytes) {
        hasFailure = true;
        console.error(
          `FAIL: Route chunk ${chunk.file} is ${formatKb(chunk.gzipBytes)} and exceeds ${routeChunkBudgetKb} kB.`,
        );
      }
    }

    if (!hasFailure) {
      console.log("PASS: Per-route chunk budget.");
    }
  }

  if (hasFailure) {
    process.exit(1);
  }

  console.log("Bundle budget check passed.");
}

try {
  main();
} catch (error) {
  console.error("Bundle budget check failed:", error instanceof Error ? error.message : error);
  process.exit(1);
}
