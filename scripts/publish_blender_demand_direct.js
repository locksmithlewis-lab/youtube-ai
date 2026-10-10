#!/usr/bin/env node
'use strict';
const fs = require('fs');
const { execFileSync } = require('child_process');
const batch = JSON.parse(fs.readFileSync(process.env.ROLIXA_OFFLINE_BATCH || 'config/blender_demand_batch.json', 'utf8'));
const required = ['R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET','YOUTUBE_ACCESS_TOKEN'];
for (const key of required) if (!process.env[key]) throw new Error('Missing required GitHub Actions secret/environment variable: ' + key);

function r2Download(key, dest) {
  const py = [
    'import os,sys,boto3',
    's3=boto3.client("s3", endpoint_url="https://"+os.environ["R2_ACCOUNT_ID"]+".r2.cloudflarestorage.com", aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")',
    's3.download_file(os.environ["R2_BUCKET"],sys.argv[1],sys.argv[2])'
  ].join(';');
  execFileSync('python', ['-c', py, key, dest], {stdio:'inherit'});
}

async function upload(token, job, file) {
  const bytes = fs.statSync(file).size;
  if (!bytes) throw new Error('Empty Blender render: ' + job.project_id);
  const p = job.project || {};
  const tags = (job.hashtags || p.hashtags || ['#AI','#Technology','#Gaming','#Rolixa'])
    .map(x => String(x).replace(/^#/, '').replace(/[^A-Za-z0-9_-]/g, '')).filter(Boolean).slice(0, 25);
  const hashtags = (job.hashtags || p.hashtags || ['#AI','#Technology','#Gaming','#Rolixa']).join(' ');
  const description = [
    String(p.topic || p.title || 'Technology and gaming explained.'),
    '',
    'Rolixa breaks down the technology behind the headlines with clear, visual explanations.',
    '',
    'If you enjoyed this video, like and subscribe for more.',
    '',
    hashtags,
    '',
    'Chapters and sources may be added in a future update.'
  ].join('\n').slice(0, 4900);
  const metadata = {
    snippet: {title: String(p.title || 'Rolixa video').slice(0,100), description, tags, categoryId:'28'},
    status: {privacyStatus:'public', selfDeclaredMadeForKids:false}
  };
  const init = await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status', {
    method:'POST',
    headers:{Authorization:'Bearer '+token,'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':String(bytes)},
    body:JSON.stringify(metadata)
  });
  if (!init.ok) throw new Error('YouTube upload init failed for '+job.project_id+' ('+init.status+'): '+(await init.text()).slice(0,500));
  const location = init.headers.get('location');
  if (!location) throw new Error('YouTube did not return a resumable upload URL for '+job.project_id);
  const up = await fetch(location,{method:'PUT',headers:{'Content-Type':'video/mp4','Content-Length':String(bytes)},body:fs.createReadStream(file),duplex:'half'});
  const raw = await up.text();
  if (!up.ok) throw new Error('YouTube upload failed for '+job.project_id+' ('+up.status+'): '+raw.slice(0,500));
  const result = JSON.parse(raw);
  if (!result.id) throw new Error('YouTube upload returned no ID for '+job.project_id);
  if (result.status?.privacyStatus !== 'public') throw new Error('Upload '+result.id+' did not confirm public status.');
  console.log('BLENDER_UPLOAD_CONFIRMED_PUBLIC '+job.project_id+' https://www.youtube.com/watch?v='+result.id);
  return {job:job.project_id,videoId:result.id,url:'https://www.youtube.com/watch?v='+result.id,privacyStatus:result.status.privacyStatus,title:p.title};
}

(async()=>{
  const results=[];
  for (const job of batch.jobs) {
    const p=job.project||{};
    const key=String(job.user_id||'offline')+'/'+job.project_id+'/'+job.id+'.mp4';
    const file='/tmp/'+job.project_id+'.mp4';
    console.log('Downloading Blender render from R2: '+key);
    r2Download(key,file);
    try { results.push(await upload(process.env.YOUTUBE_ACCESS_TOKEN,job,file)); }
    finally { fs.rmSync(file,{force:true}); }
  }
  fs.writeFileSync('blender-publish-results.json',JSON.stringify({publishedAt:new Date().toISOString(),results},null,2)+'\n');
  console.log('BLENDER_BATCH_PUBLISHED: all five upload responses confirmed public. See blender-publish-results.json.');
})().catch(e=>{console.error('BLENDER_BATCH_PUBLISH_FAILED: '+(e?.stack||e));process.exit(1);});
