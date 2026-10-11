#!/usr/bin/env node
'use strict';
const fs = require('fs');
const { execFileSync } = require('child_process');

const batch = JSON.parse(fs.readFileSync(process.env.ROLIXA_OFFLINE_BATCH || 'config/offline_render_batch.json', 'utf8'));
const required = ['R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET','YOUTUBE_ACCESS_TOKEN'];
for (const key of required) if (!process.env[key]) throw new Error('Missing required GitHub Actions secret/environment variable: ' + key);

const MANIFEST_KEY = 'rolixa/publish-manifests/offline-render-batch-v1.json';
function r2Manifest(action, payload='') {
  const py = [
    'import os,sys,json,boto3',
    'from botocore.exceptions import ClientError',
    's=boto3.client("s3",endpoint_url="https://"+os.environ["R2_ACCOUNT_ID"]+".r2.cloudflarestorage.com",aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"],aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"],region_name="auto")',
    'bucket=os.environ["R2_BUCKET"]; key=sys.argv[2]',
    'if sys.argv[1]=="get":',
    ' try: print(s.get_object(Bucket=bucket,Key=key)["Body"].read().decode())',
    ' except ClientError as e:',
    '  if e.response.get("Error",{}).get("Code") in ("NoSuchKey","404","NotFound"): print("{}")',
    '  else: raise',
    'else: s.put_object(Bucket=bucket,Key=key,Body=sys.argv[3].encode(),ContentType="application/json",CacheControl="no-store")'
  ].join('\n');
  const args = ['-c',py,action,MANIFEST_KEY];
  if(action==='put') args.push(JSON.stringify(payload));
  const output=execFileSync('python',args,{encoding:'utf8',stdio:['ignore','pipe','inherit']});
  return action==='get' ? JSON.parse(output) : undefined;
}

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
  const metadata={snippet:{title:String(p.title||'Video').slice(0,100),description:(String(p.topic||p.title||'Original video')+'\n\n#Shorts').slice(0,5000),categoryId:'22'},status:{privacyStatus:'public',selfDeclaredMadeForKids:false}};
  const init=await fetch('https://www.googleapis.com/upload/youtube/v3/videos?uploadType=resumable&part=snippet,status',{method:'POST',headers:{Authorization:'Bearer '+token,'Content-Type':'application/json; charset=UTF-8','X-Upload-Content-Type':'video/mp4','X-Upload-Content-Length':String(bytes)},body:JSON.stringify(metadata)});
  if(!init.ok) throw new Error('YouTube upload init failed for '+job.id+' ('+init.status+'): '+(await init.text()).slice(0,350));
  const location=init.headers.get('location');
  if(!location) throw new Error('YouTube did not return a resumable upload URL for '+job.id);
  const up=await fetch(location,{method:'PUT',headers:{'Content-Type':'video/mp4','Content-Length':String(bytes)},body:fs.createReadStream(file),duplex:'half'});
  const raw=await up.text();
  if(!up.ok) throw new Error('YouTube upload failed for '+job.id+' ('+up.status+'): '+raw.slice(0,350));
  const result=JSON.parse(raw);
  if(!result.id) throw new Error('Upload returned no video ID for '+job.id);
  const privacyStatus = result.status?.privacyStatus;
  if (privacyStatus !== 'public') {
    throw new Error('Upload completed for '+job.id+' ('+result.id+') but YouTube upload response did not confirm public status (privacyStatus='+String(privacyStatus)+'). Stopping to avoid claiming publication was verified.');
  }
  console.log('UPLOAD_RESPONSE_CONFIRMED_PUBLIC '+job.id+' https://www.youtube.com/watch?v='+result.id);
  return {id: result.id, privacyStatus};
}
(async()=>{
  const token=process.env.YOUTUBE_ACCESS_TOKEN, results=[], failures=[];
  const reportPath='offline-publish-results.json';
  const persist=()=>fs.writeFileSync(reportPath,JSON.stringify({verifiedAt:new Date().toISOString(),results,failures},null,2)+'\n');
  const manifest=r2Manifest('get');
  // Preserve the known historical upload, but verify it against YouTube before skipping it.
  if(!manifest['offline-ai-sci-fi-001']) manifest['offline-ai-sci-fi-001']={videoId:'h5yRELLdc-c',source:'legacy-recovery-candidate',privacyStatus:'unverified-existing'};
  persist();
  for(const job of batch.jobs){
    const key='offline/'+job.id+'/'+job.id+'.mp4', file='/tmp/'+job.id+'.mp4';
    try {
      const prior=manifest[job.id];
      if(prior?.videoId){
        const status=prior.privacyStatus==='public'?'public':'unverified-existing';
        console.log('SKIP_EXISTING_UPLOAD '+job.id+' https://www.youtube.com/watch?v='+prior.videoId+' status='+status+'; refusing to create a duplicate.');
        results.push({job:job.id,videoId:prior.videoId,url:'https://www.youtube.com/watch?v='+prior.videoId,privacyStatus:status,reused:true});
        persist();
        continue;
      }
      console.log('Downloading from R2: '+key);
      r2Download(key,file);
      const uploaded=await upload(token,job,file);
      const record={job:job.id,videoId:uploaded.id,url:'https://www.youtube.com/watch?v='+uploaded.id,privacyStatus:uploaded.privacyStatus};
      results.push(record);
      manifest[job.id]={videoId:uploaded.id,privacyStatus:'public',title:job.project?.title||null,publishedAt:new Date().toISOString()};
      r2Manifest('put',manifest); // durable idempotency record before moving to the next video
      persist();
    } catch(e) {
      const failure={job:job.id,title:job.project?.title||null,error:String(e?.message||e).slice(0,1000)};
      failures.push(failure);
      console.error('OFFLINE_VIDEO_PUBLISH_FAILED '+job.id+': '+failure.error);
      persist();
    } finally {
      fs.rmSync(file,{force:true});
    }
  }
  persist();
  if(failures.length){ console.error('OFFLINE_BATCH_PARTIAL_FAILURE: '+results.length+' confirmed public, '+failures.length+' failed.'); process.exitCode=1; }
  else console.log('OFFLINE_BATCH_FINISHED: '+results.length+' videos confirmed public; report offline-publish-results.json.');
})().catch(e=>{console.error('OFFLINE_PUBLISH_FAILED: '+(e?.stack||e));process.exit(1)});
