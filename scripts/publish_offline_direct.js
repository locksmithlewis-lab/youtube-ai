#!/usr/bin/env node
'use strict';
const fs = require('fs');
const { execFileSync } = require('child_process');

const batch = JSON.parse(fs.readFileSync(process.env.ROLIXA_OFFLINE_BATCH || 'config/offline_render_batch.json', 'utf8'));
const required = ['R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET','YOUTUBE_ACCESS_TOKEN'];
for (const key of required) if (!process.env[key]) throw new Error('Missing required GitHub Actions secret/environment variable: ' + key);

function r2Download(key, dest) {
  const py = [
    'import os,sys,boto3',
    's3=boto3.client("s3", endpoint_url="https://"+os.environ["R2_ACCOUNT_ID"]+".r2.cloudflarestorage.com", aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")',
    's3.download_file(os.environ["R2_BUCKET"],sys.argv[1],sys.argv[2])'
  ].join(';');
  execFileSync('python', ['-c',py,key,dest], {stdio:'inherit'});
}
async function upload(token, job, file) {
  const p=job.project, bytes=fs.statSync(file).size;
  if (!bytes) throw new Error('Empty rendered MP4 for '+job.id);
  const metadata={snippet:{title:String(p.title||'Video').slice(0,100),description:(String(p.topic||p.title||'Original video')+'\\n\\n#Shorts').slice(0,5000),categoryId:'22'},status:{privacyStatus:'public',selfDeclaredMadeForKids:false}};
  const init=await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':String(bytes)},body:JSON.stringify(metadata)});
  if(!init.ok) throw new Error('YouTube upload init failed for '+job.id+' ('+init.status+'): '+(await init.text()).slice(0,350));
  const location=init.headers.get('location');
  if(!location) throw new Error('YouTube did not return a resumable upload URL for '+job.id);
  const up=await fetch(location,{method:'PUT',headers:{'Content-Type':'video/mp4','Content-Length':String(bytes)},body:fs.createReadStream(file),duplex:'half'});
  const raw=await up.text();
  if(!up.ok) throw new Error('YouTube upload failed for '+job.id+' ('+up.status+'): '+raw.slice(0,350));
  const result=JSON.parse(raw);
  if(!result.id) throw new Error('Upload returned no video ID for '+job.id);
  const verify=await fetch('https://www.googleapis.com/youtube/v3/videos?part=status&id='+encodeURIComponent(result.id),{headers:{Authorization:'Bearer '+token}});
  const vd=await verify.json(), status=vd?.items?.[0]?.status?.privacyStatus;
  if(!verify.ok||status!=='public') throw new Error('Video '+result.id+' uploaded but is not verified public (privacy='+String(status)+').');
  console.log('VERIFIED_PUBLIC '+job.id+' https://www.youtube.com/watch?v='+result.id);
  return result.id;
}
(async()=>{
  const token=process.env.YOUTUBE_ACCESS_TOKEN, results=[];
  for(const job of batch.jobs){
    const key='offline/'+job.id+'/'+job.id+'.mp4', file='/tmp/'+job.id+'.mp4';
    console.log('Downloading from R2: '+key); r2Download(key,file);
    const id=await upload(token,job,file);
    results.push({job:job.id,videoId:id,url:'https://www.youtube.com/watch?v='+id,privacyStatus:'public'});
    fs.rmSync(file,{force:true});
  }
  fs.writeFileSync('offline-publish-results.json',JSON.stringify({verifiedAt:new Date().toISOString(),results},null,2)+'\\n');
  console.log('ALL_OFFLINE_VIDEOS_VERIFIED_PUBLIC');
})().catch(e=>{console.error('OFFLINE_PUBLISH_FAILED: '+(e?.stack||e));process.exit(1)});
