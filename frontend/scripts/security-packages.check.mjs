import assert from 'node:assert/strict';
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';
import test from 'node:test';
import { createRequire } from 'node:module';
import { spawnSync } from 'node:child_process';

import * as braceExpansion from 'brace-expansion';
import yaml from 'js-yaml';
import { customAlphabet as secureCustomAlphabet } from 'nanoid';
import { customAlphabet, nanoid as nonSecureNanoid } from 'nanoid/non-secure';
import { parse } from 'postcss';
import { SourceMapConsumer } from 'source-map-js';

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

test('Nano ID custom generators terminate for zero sizes', () => {
  for (const createGenerator of [customAlphabet, secureCustomAlphabet]) {
    assert.equal(createGenerator('abcdef')(0), '');
    assert.equal(createGenerator('abcdef', 0)(), '');
  }
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
    const absoluteMapCss = `a{}\n/*# sourceMappingURL=${join(root, 'outside.map')} */`;
    assert.equal(parse(absoluteMapCss).source?.input.map, undefined);
  } finally {
    rmSync(root, { recursive: true, force: true });
  }
});

test('indexed source maps reject invalid or excessive section offsets', () => {
  const map = (line, column = 0) => ({
    version: 3,
    sections: [{
      offset: { line, column },
      map: { version: 3, sources: ['input.js'], names: [], mappings: 'AAAA' },
    }],
  });
  assert.equal(new SourceMapConsumer(map(0)).sources[0], 'input.js');
  for (const invalid of [-1, 0.5, Infinity, Number.MAX_SAFE_INTEGER + 1, '1', null]) {
    assert.throws(() => new SourceMapConsumer(map(invalid)), Error);
    assert.throws(() => new SourceMapConsumer(map(0, invalid)), Error);
  }
  assert.throws(() => new SourceMapConsumer(map(10_000_001)), /must not exceed/);
});

test('source-map conversion stays bounded for large offsets and nested maps', () => {
  const result = spawnSync(process.execPath, ['-e', `
    const { SourceMapConsumer, SourceNode } = require('source-map-js');
    const source = {version: 3, sources: ['input.js'], sourcesContent: ['x'], names: [], mappings: 'AAAA'};
    const distant = {version: 3, sections: [{offset: {line: 10000000, column: 0}, map: source}]};
    const converted = SourceNode.fromStringWithSourceMap('x\\n', new SourceMapConsumer(distant));
    let nested = source;
    for (let i = 0; i < 40; i++) nested = {version: 3, sections: [{offset: {line: 0, column: 0}, map: nested}]};
    const nestedResult = SourceNode.fromStringWithSourceMap('x\\n', new SourceMapConsumer(nested));
    console.log(JSON.stringify({text: converted.toString(), children: converted.children.length, nested: nestedResult.toString()}));
  `], { cwd: new URL('..', import.meta.url), encoding: 'utf8', timeout: 5000 });
  assert.equal(result.status, 0, result.error?.message || result.stderr);
  const output = JSON.parse(result.stdout);
  assert.equal(output.text, 'x\n');
  assert.equal(output.nested, 'x\n');
  assert.ok(output.children < 10);
});