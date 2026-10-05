import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import test from 'node:test';

const script = fileURLToPath(new URL('./strengthen_npm_lock_integrity.mjs', import.meta.url));
const source =
  'https://ms-feed-25.pkgs.visualstudio.com/1es-public/_packaging/npm-public/npm/registry/test/-/test-1.0.0.tgz';
const archive = 'fixture package archive';
const sha1 = `sha1-${createHash('sha1').update(archive).digest('base64')}`;
const sha512 = `sha512-${createHash('sha512').update(archive).digest('base64')}`;

function fixture(t, { integrity = sha1, resolved = source, mode = 'success' } = {}) {
  const directory = mkdtempSync(join(tmpdir(), 'archmorph-lock-integrity-'));
  t.after(() => rmSync(directory, { recursive: true, force: true }));
  const path = join(directory, 'package-lock.json');
  const mockPath = join(directory, 'mock-fetch.mjs');
  const lock = {
    lockfileVersion: 3,
    packages: { 'node_modules/test': { version: '1.0.0', integrity, resolved } },
  };
  const original = `${JSON.stringify(lock, null, 2)}\n`;
  writeFileSync(path, original);
  writeFileSync(mockPath, `
    import { writeFileSync } from 'node:fs';
    import fsPromises from 'node:fs/promises';
    import { syncBuiltinESMExports } from 'node:module';
    const originalWriteFile = fsPromises.writeFile;
    fsPromises.writeFile = async (...args) => {
      if (${JSON.stringify(mode)} === 'late-concurrent-change') {
        writeFileSync(${JSON.stringify(path)}, 'concurrent edit');
      }
      return originalWriteFile(...args);
    };
    syncBuiltinESMExports();
    globalThis.fetch = async () => {
      if (${JSON.stringify(mode)} === 'download-error') return { ok: false, status: 503 };
      if (${JSON.stringify(mode)} === 'concurrent-change') {
        writeFileSync(${JSON.stringify(path)}, 'concurrent edit');
      }
      return {
        ok: true,
        arrayBuffer: async () => new TextEncoder().encode(${JSON.stringify(archive)}).buffer,
      };
    };
  `);
  const run = () => spawnSync(process.execPath, ['--import', mockPath, script, path], {
    encoding: 'utf8',
    timeout: 5000,
  });
  return { path, original, lock, run };
}

test('prepares verified archive pins without changing the input or package identity', (t) => {
  const { path, original, lock, run } = fixture(t);
  const result = run();
  assert.equal(result.status, 0, result.stderr);
  lock.packages['node_modules/test'].integrity = sha512;
  assert.deepEqual(JSON.parse(readFileSync(`${path}.sha512`, 'utf8')), lock);
  assert.equal(readFileSync(path, 'utf8'), original);
});

test('refuses to overwrite an existing candidate on repeated invocation', (t) => {
  const { path, original, run } = fixture(t);
  assert.equal(run().status, 0);
  const candidate = readFileSync(`${path}.sha512`, 'utf8');
  const repeated = run();
  assert.equal(repeated.status, 1);
  assert.match(repeated.stderr, /EEXIST/);
  assert.equal(readFileSync(`${path}.sha512`, 'utf8'), candidate);
  assert.equal(readFileSync(path, 'utf8'), original);
});

test('leaves already strengthened lockfiles unchanged without creating output', (t) => {
  const { path, original, run } = fixture(t, { integrity: sha512 });
  for (let attempt = 0; attempt < 2; attempt += 1) {
    const result = run();
    assert.equal(result.status, 0, result.stderr);
    assert.match(result.stdout, /No SHA-1 archive pins/);
    assert.equal(readFileSync(path, 'utf8'), original);
    assert.equal(existsSync(`${path}.sha512`), false);
  }
});

for (const [name, options, error] of [
  ['checksum mismatch', { integrity: 'sha1-invalid' }, /Existing integrity mismatch/],
  ['unapproved source', { resolved: 'https://example.invalid/package.tgz' }, /Unapproved source/],
  ['download failure', { mode: 'download-error' }, /Download failed.*503/],
]) {
  test(`rejects ${name} without rewriting the lockfile`, (t) => {
    const { path, original, run } = fixture(t, options);
    const result = run();
    assert.equal(result.status, 1);
    assert.match(result.stderr, error);
    assert.equal(readFileSync(path, 'utf8'), original);
  });
}

test('preserves a concurrent writer instead of overwriting its lockfile', (t) => {
  const { path, run } = fixture(t, { mode: 'concurrent-change' });
  const result = run();
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Lockfile changed during verification/);
  assert.equal(readFileSync(path, 'utf8'), 'concurrent edit');
});

test('requires explicit lockfile paths', () => {
  const result = spawnSync(process.execPath, [script], { encoding: 'utf8', timeout: 5000 });
  assert.equal(result.status, 1);
  assert.match(result.stderr, /Pass the lockfiles/);
});

test('preserves edits arriving after the final read and immediately before publication', (t) => {
  const { path, run } = fixture(t, { mode: 'late-concurrent-change' });
  const result = run();
  assert.equal(result.status, 0, result.stderr);
  assert.equal(readFileSync(path, 'utf8'), 'concurrent edit');
  assert.equal(
    JSON.parse(readFileSync(`${path}.sha512`, 'utf8')).packages['node_modules/test'].integrity,
    sha512,
  );
});
