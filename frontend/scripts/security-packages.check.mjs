import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';

import * as braceExpansion from 'brace-expansion';
import yaml from 'js-yaml';
import { customAlphabet, nanoid as nonSecureNanoid } from 'nanoid/non-secure';
import { parse } from 'postcss';

const require = createRequire(import.meta.url);
const braceExpand = require('brace-expansion');

test('brace-expansion preserves legacy CommonJS and modern ESM APIs', () => {
  assert.equal(typeof braceExpand, 'function');
  assert.equal(braceExpand.expand, braceExpand);
  assert.equal(braceExpand.EXPANSION_MAX_LENGTH, 4_000_000);
  assert.equal(typeof braceExpansion.expand, 'function');
  assert.equal(braceExpansion.EXPANSION_MAX_LENGTH, 4_000_000);
  assert.deepEqual(braceExpand('file-{a,b}.txt'), ['file-a.txt', 'file-b.txt']);
  assert.deepEqual(braceExpansion.expand('file-{a,b}.txt'), ['file-a.txt', 'file-b.txt']);
});

test('brace-expansion retains the reviewed aggregate output bound', () => {
  const result = braceExpand('{a,b}'.repeat(1500));
  const totalLength = result.reduce((sum, value) => sum + value.length, 0);
  assert.ok(totalLength <= braceExpand.EXPANSION_MAX_LENGTH);
});

test('js-yaml enforces its total merge-key limit', () => {
  const document = 'base: &base\n  one: 1\n  two: 2\nmerged:\n  <<: *base\n';
  assert.throws(
    () => yaml.load(document, { maxTotalMergeKeys: 1 }),
    /merge keys exceeded maxTotalMergeKeys \(1\)/,
  );
});

test('Nano ID non-secure APIs terminate for negative sizes', () => {
  assert.equal(nonSecureNanoid(-1), '');
  assert.equal(nonSecureNanoid(-100), '');
  assert.equal(customAlphabet('abcdef')(-1), '');
  assert.equal(customAlphabet('abcdef', -5)(), '');
});

test('PostCSS blocks source-map traversal unless explicitly trusted', () => {
  const root = mkdtempSync(join(tmpdir(), 'archmorph-postcss-'));
  const subdirectory = join(root, 'subdirectory');
  const map = JSON.stringify({
    version: 3,
    sources: ['source.css'],
    names: [],
    mappings: 'AAAA',
  });

  try {
    mkdirSync(subdirectory);
    writeFileSync(join(root, 'outside.map'), map);
    const css = 'a{}\n/*# sourceMappingURL=../outside.map */';
    const from = join(subdirectory, 'input.css');

    assert.equal(parse(css, { from }).source?.input.map, undefined);
    assert.equal(parse(css, { from, unsafeMap: true }).source?.input.map?.text, map);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});