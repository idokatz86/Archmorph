import { createHash } from 'node:crypto';
import { readFile, writeFile } from 'node:fs/promises';

const approvedSource =
  'https://ms-feed-25.pkgs.visualstudio.com/1es-public/_packaging/npm-public/npm/registry/';
const digests = new Map();
const updates = [];

if (process.argv.length < 3) {
  throw new Error('Pass the lockfiles whose approved-feed SHA-1 pins need strengthening');
}

for (const path of process.argv.slice(2)) {
  const original = await readFile(path, 'utf8');
  const lock = JSON.parse(original);
  if (lock.lockfileVersion !== 3 || !lock.packages) {
    throw new Error(`Unsupported lockfile: ${path}`);
  }
  let count = 0;
  for (const [name, entry] of Object.entries(lock.packages)) {
    if (!entry.integrity?.startsWith('sha1-')) continue;
    if (!entry.resolved?.startsWith(approvedSource)) {
      throw new Error(`Unapproved source for ${name}`);
    }
    if (!digests.has(entry.resolved)) {
      const response = await fetch(entry.resolved, {
        signal: AbortSignal.timeout(30_000),
      });
      if (!response.ok) throw new Error(`Download failed for ${name}: ${response.status}`);
      const bytes = new Uint8Array(await response.arrayBuffer());
      digests.set(entry.resolved, {
        sha1: `sha1-${createHash('sha1').update(bytes).digest('base64')}`,
        sha512: `sha512-${createHash('sha512').update(bytes).digest('base64')}`,
      });
    }
    const digest = digests.get(entry.resolved);
    // Verify the existing archive pin before replacing it with a stronger digest.
    if (entry.integrity !== digest.sha1) {
      throw new Error(`Existing integrity mismatch for ${name}`);
    }
    entry.integrity = digest.sha512;
    count += 1;
  }
  updates.push({ path, original, lock, count });
}

for (const { path, original, lock, count } of updates) {
  if (await readFile(path, 'utf8') !== original) {
    throw new Error(`Lockfile changed during verification: ${path}`);
  }
  if (count === 0) {
    console.log(`No SHA-1 archive pins to strengthen: ${path}`);
    continue;
  }
  const output = `${path}.sha512`;
  await writeFile(output, `${JSON.stringify(lock, null, 2)}\n`, { flag: 'wx' });
  console.log(`Prepared ${count} verified SHA-512 pins in ${output}; review and apply with other writers stopped. Original lockfile unchanged.`);
}
