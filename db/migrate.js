import fs from 'node:fs';
import path from 'node:path';
import { root } from '../src/config.js';
import { pool } from '../src/db.js';

const sql = fs.readFileSync(path.join(root, 'db', 'schema.sql'), 'utf8');
await pool.query(sql);
console.log('schema applied');
await pool.end();
