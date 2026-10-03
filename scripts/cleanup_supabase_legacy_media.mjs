import process from 'node:process';
import { createClient } from '@supabase/supabase-js';

const url = process.env.SUPABASE_URL;
const key = process.env.SUPABASE_SERVICE_ROLE_KEY;
if (!url || !key) throw new Error('Missing Supabase environment');

const supabase = createClient(url, key, { auth: { persistSession: false, autoRefreshToken: false } });

async function walk(prefix = '') {
  const { data, error } = await supabase.storage.from('video-outputs').list(prefix, {
    limit: 1000,
    offset: 0,
    sortBy: { column: 'name', order: 'asc' }
  });
  if (error) throw error;
  const files = [];
  for (const item of data || []) {
    const path = prefix ? prefix + '/' + item.name : item.name;
    if (item.id) files.push(path);
    else files.push(...await walk(path));
  }
  return files;
}

const files = await walk('');
console.log('Legacy Supabase media files found:', files.length);

for (let i = 0; i < files.length; i += 1000) {
  const batch = files.slice(i, i + 1000);
  if (!batch.length) continue;
  const { error } = await supabase.storage.from('video-outputs').remove(batch);
  if (error) throw error;
  console.log('Deleted batch:', i + 1, '-', i + batch.length);
}
