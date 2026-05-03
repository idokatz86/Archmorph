#!/usr/bin/env node

import { mkdirSync, readFileSync, writeFileSync } from 'node:fs';
import { dirname, resolve } from 'node:path';

const [, , inputArg = '../backend/openapi.json', outputArg = 'src/generated/api-paths.js'] = process.argv;
const inputPath = resolve(process.cwd(), inputArg);
const outputPath = resolve(process.cwd(), outputArg);

const schema = JSON.parse(readFileSync(inputPath, 'utf8'));
const paths = Object.keys(schema.paths ?? {}).sort();

if (paths.length === 0) {
  throw new Error(`No OpenAPI paths found in ${inputPath}`);
}

const usedKeys = new Map();
const entries = paths.map((path) => [uniqueKey(path, usedKeys), path]);
const templateLines = entries.map(([key, path]) => `  ${key}: ${JSON.stringify(path)},`);

const output = `/**
 * API route templates generated from the backend OpenAPI schema.
 * Do not edit manually. Run: npm run generate:api-schema
 */

export const API_PATH_TEMPLATES = Object.freeze({
${templateLines.join('\n')}
});

export const OPENAPI_PATHS = Object.freeze(Object.values(API_PATH_TEMPLATES));

export function buildApiPath(template, params = {}) {
  return template.replace(/\\{([^}]+)\\}/g, (_, name) => {
    if (!Object.prototype.hasOwnProperty.call(params, name) || params[name] == null) {
      throw new Error(\`Missing value for OpenAPI path parameter: \${name}\`);
    }

    return encodeURIComponent(String(params[name]));
  });
}
`;

mkdirSync(dirname(outputPath), { recursive: true });
writeFileSync(outputPath, output, 'utf8');

function uniqueKey(path, usedKeys) {
  const baseKey = path
    .replace(/^\/+/, '')
    .replace(/[{}]/g, '')
    .split(/[^A-Za-z0-9]+/)
    .filter(Boolean)
    .map((part) => part.replace(/([a-z0-9])([A-Z])/g, '$1_$2').toUpperCase())
    .join('_') || 'ROOT';

  const currentCount = usedKeys.get(baseKey) ?? 0;
  usedKeys.set(baseKey, currentCount + 1);

  return currentCount === 0 ? baseKey : `${baseKey}_${currentCount + 1}`;
}