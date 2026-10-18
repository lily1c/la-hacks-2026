import { mkdir, writeFile, chmod, mkdtemp, copyFile, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { resolve, join } from 'node:path';
import { execFileSync } from 'node:child_process';
import { createHash } from 'node:crypto';

const version = 'v1.21.2';
const platform = { darwin: 'darwin', linux: 'linux' }[process.platform];
const arch = { arm64: 'arm64', x64: 'amd64' }[process.arch];
if (!platform || !arch) throw new Error('Use macOS or Linux on arm64 or x64.');
const filename = `mediamtx_${version}_${platform}_${arch}.tar.gz`;
const headers = { 'User-Agent': 'FireSight-local-setup' };
const metadata = await fetch(`https://api.github.com/repos/bluenviron/mediamtx/releases/tags/${version}`, { headers, signal: AbortSignal.timeout(30000) });
if (!metadata.ok) throw new Error(`Release lookup failed: HTTP ${metadata.status}`);
const release = await metadata.json();
const asset = release.assets.find(a => a.name === filename);
if (!asset?.digest?.startsWith('sha256:')) throw new Error('Release asset or SHA-256 digest missing.');
console.log(`Downloading official MediaMTX ${version} for ${platform}/${arch}…`);
const download = await fetch(asset.browser_download_url, { headers, signal: AbortSignal.timeout(120000) });
if (!download.ok) throw new Error(`Download failed: HTTP ${download.status}`);
const bytes = Buffer.from(await download.arrayBuffer());
if (`sha256:${createHash('sha256').update(bytes).digest('hex')}` !== asset.digest) throw new Error('Checksum mismatch.');
const temporary = await mkdtemp(join(tmpdir(), 'firesight-install-'));
try {
  const archive = join(temporary, 'release.tar.gz');
  await writeFile(archive, bytes);
  execFileSync('tar', ['-xzf', archive, '-C', temporary, 'mediamtx']);
  const destination = resolve('.runtime');
  await mkdir(destination, { recursive: true, mode: 0o700 });
  await copyFile(join(temporary, 'mediamtx'), join(destination, 'mediamtx'));
  await chmod(join(destination, 'mediamtx'), 0o755);
  console.log(`Installed and checksum-verified: ${join(destination, 'mediamtx')}`);
} finally {
  await rm(temporary, { recursive: true, force: true });
}
