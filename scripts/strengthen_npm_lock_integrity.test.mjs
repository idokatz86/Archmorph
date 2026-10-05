import assert from 'node:assert/strict';
import { createHash } from 'node:crypto';
import { mkdtempSync, readFileSync, rmSync, writeFileSync } from 'node:fs';
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

test('strengthens verified archive pins without changing package identity and is idempotent', (t) => {
  const { path, lock, run } = fixture(t);
  const result = run();
  assert.equal(result.status, 0, result.stderr);
  lock.packages['node_modules/test'].integrity = sha512;
  assert.deepEqual(JSON.parse(readFileSync(path, 'utf8')), lock);
  const strengthened = readFileSync(path, 'utf8');
  const repeated = run();
  assert.equal(repeated.status, 0, repeated.stderr);
  assert.match(repeated.stdout, /strengthened 0 entries/);
  assert.equal(readFileSync(path, 'utf8'), strengthened);
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
