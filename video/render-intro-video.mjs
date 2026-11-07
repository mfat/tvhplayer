// Renders video/intro.html into an mp4. The composition is a pure function of
// time, so each frame is seeked, screenshotted and piped into ffmpeg; the
// output is identical on every run and picks up the current product data.
//
// The app's windows come from video/capture_ui.py, which draws them with
// TVHplayer's own code before each render, so the video tracks the app.
import { execFileSync, spawn } from "node:child_process";
import { existsSync } from "node:fs";
import { mkdir, writeFile } from "node:fs/promises";
import { delimiter, dirname, join, resolve as resolvePath } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import puppeteer from "puppeteer-core";

const FPS = 30;
// The composition is laid out at 1080p; the device scale factor sets the output resolution.
const SIZE = { width: 1920, height: 1080 };

const videoRoot = dirname(fileURLToPath(import.meta.url));
const compositionUrl = pathToFileURL(join(videoRoot, "intro.html"));
const outputRoot = join(videoRoot, "out");

const BROWSER_ARGS = ["--allow-file-access-from-files", "--hide-scrollbars", "--force-color-profile=srgb"];

function chromeExecutable() {
  if (process.env.CHROME_BIN) return process.env.CHROME_BIN;
  const names = ["chromium", "chromium-browser", "google-chrome", "google-chrome-stable", "chrome"];
  const candidates = [
    ...String(process.env.PATH ?? "").split(delimiter).flatMap((dir) => names.map((name) => join(dir, name))),
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
    "/Applications/Chromium.app/Contents/MacOS/Chromium",
  ];
  const found = candidates.find((path) => existsSync(path));
  if (!found) throw new Error("Chrome/Chromium not found. Install it or set CHROME_BIN.");
  return found;
}

/**
 * Everything the composition needs from the product: the app's windows drawn
 * by capture_ui.py (sharper than the frame needs, as they are zoomed into),
 * where its controls are, and the recording formats from the app's code.
 * Exposed as window.INTRO_DATA.
 */
async function introData(_browser, scale) {
  const captureScale = scale * 1.5;
  const folder = `build/${captureScale}x`;
  const output = execFileSync(process.env.PYTHON ?? "python3", [join(videoRoot, "capture_ui.py"), join(videoRoot, folder), String(captureScale)], {
    cwd: videoRoot,
    encoding: "utf8",
    stdio: ["ignore", "pipe", "ignore"],
    maxBuffer: 16 * 1024 * 1024,
  });
  // The app prints its own debug lines; the manifest is the last line.
  const manifest = JSON.parse(output.trim().split("\n").at(-1));
  return { ...manifest, folder };
}

function printUsage() {
  console.log(`Usage:
  npm run video:intro                     Render video/out/intro.mp4 in 4K (3840 × 2160)
  npm run video:intro -- --hd             Render a faster 1080p draft to video/out/intro-1080p.mp4
  npm run video:intro -- --preview        Open the composition in Chrome (space pauses, slider scrubs)
  npm run video:intro -- --stills 2,8,16  Write PNG stills at those seconds to video/out/`);
}

function parseArgs() {
  const args = process.argv.slice(2).filter((arg) => arg !== "--");
  if (args.includes("--help") || args.includes("-h")) { printUsage(); process.exit(0); }
  const stillsIndex = args.indexOf("--stills");
  const stills = stillsIndex >= 0 ? (args[stillsIndex + 1] ?? "").split(",").map(Number) : null;
  if (stills?.some((t) => !Number.isFinite(t))) throw new Error("--stills expects comma-separated seconds, e.g. --stills 2,8.5,16");
  return { preview: args.includes("--preview"), stills, scale: args.includes("--hd") ? 1 : 2 };
}

async function openComposition(page, data, render) {
  const failures = [];
  page.on("pageerror", (error) => failures.push(String(error)));
  page.on("requestfailed", (request) => failures.push(`Failed to load ${request.url()}`));
  await page.evaluateOnNewDocument((injected) => { window.INTRO_DATA = injected; }, data);
  const url = new URL(compositionUrl);
  if (render) url.searchParams.set("render", "1");
  await page.goto(url.href, { waitUntil: "load", timeout: 30_000 });
  await page.evaluate(() => window.INTRO.ready());
  if (failures.length) throw new Error(failures.join("\n"));
}

async function seek(page, seconds) {
  await page.evaluate((t) => new Promise((resolve) => {
    window.INTRO.seek(t);
    requestAnimationFrame(() => requestAnimationFrame(() => resolve()));
  }), seconds);
}

async function preview() {
  const browser = await puppeteer.launch({
    executablePath: chromeExecutable(),
    headless: false,
    defaultViewport: null,
    args: [...BROWSER_ARGS, "--window-size=1600,960"],
  });
  const [page] = await browser.pages();
  await openComposition(page, await introData(browser, 1), false);
  console.log("Previewing. Close the browser window to exit.");
  await new Promise((resolve) => browser.on("disconnected", () => resolve()));
}

async function render(stills, scale) {
  await mkdir(outputRoot, { recursive: true });
  const browser = await puppeteer.launch({
    executablePath: chromeExecutable(),
    headless: true,
    args: [...BROWSER_ARGS, "--disable-dev-shm-usage"],
  });
  try {
    const data = await introData(browser, scale);
    const page = await browser.newPage();
    await page.setViewport({ ...SIZE, deviceScaleFactor: scale });
    await openComposition(page, data, true);
    const duration = await page.evaluate(() => window.INTRO.duration);

    if (stills) {
      for (const t of stills) {
        await seek(page, t);
        const path = join(outputRoot, `intro-${t.toFixed(2)}s.png`);
        await writeFile(path, await page.screenshot({ type: "png" }));
        console.log(path);
      }
      return;
    }

    const output = join(outputRoot, scale === 1 ? "intro-1080p.mp4" : "intro.mp4");
    const ffmpeg = spawn("ffmpeg", [
      "-y", "-loglevel", "error",
      "-f", "image2pipe", "-framerate", String(FPS), "-c:v", "png", "-i", "-",
      "-c:v", "libx264", "-preset", scale === 1 ? "slow" : "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart",
      output,
    ], { stdio: ["pipe", "inherit", "inherit"] });
    const finished = new Promise((resolve, reject) => {
      ffmpeg.once("error", reject);
      ffmpeg.once("close", (code) => code === 0 ? resolve() : reject(new Error(`ffmpeg exited with ${code}`)));
    });

    const frames = Math.round(duration * FPS);
    for (let frame = 0; frame < frames; frame++) {
      await seek(page, frame / FPS);
      const png = await page.screenshot({ type: "png", optimizeForSpeed: true });
      if (!ffmpeg.stdin.write(png)) await new Promise((resolve) => ffmpeg.stdin.once("drain", resolve));
      if (frame % FPS === 0) process.stdout.write(`\r  ${frame / FPS}s / ${duration}s`);
    }
    ffmpeg.stdin.end();
    await finished;
    console.log(`\nWrote ${output}`);
  } finally {
    await browser.close();
  }
}

const { preview: previewMode, stills, scale } = parseArgs();
if (previewMode) await preview();
else await render(stills, scale);
