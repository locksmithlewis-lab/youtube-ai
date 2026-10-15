#!/usr/bin/env node
'use strict';
const fs = require('fs');
const { execFileSync } = require('child_process');
const batch = JSON.parse(fs.readFileSync(process.env.ROLIXA_OFFLINE_BATCH || 'config/blender_demand_batch.json', 'utf8'));
const required = ['R2_ACCOUNT_ID','R2_ACCESS_KEY_ID','R2_SECRET_ACCESS_KEY','R2_BUCKET','YOUTUBE_ACCESS_TOKEN'];
for (const key of required) if (!process.env[key]) throw new Error('Missing required GitHub Actions secret/environment variable: ' + key);

const MANIFEST_KEY = 'rolixa/publish-manifests/blender-demand-batch-v1.json';
function r2Manifest(action, payload='') {
  const py = [
    'import os,sys,boto3',
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
  const args=['-c',py,action,MANIFEST_KEY];
  if(action==='put') args.push(JSON.stringify(payload));
  const output=execFileSync('python',args,{encoding:'utf8',stdio:['ignore','pipe','inherit']});
  return action==='get'?JSON.parse(output):undefined;
}

function r2Download(key, dest) {
  const py = [
    'import os,sys,boto3',
    's3=boto3.client("s3", endpoint_url="https://"+os.environ["R2_ACCOUNT_ID"]+".r2.cloudflarestorage.com", aws_access_key_id=os.environ["R2_ACCESS_KEY_ID"], aws_secret_access_key=os.environ["R2_SECRET_ACCESS_KEY"], region_name="auto")',
    's3.download_file(os.environ["R2_BUCKET"],sys.argv[1],sys.argv[2])'
  ].join(';');
  execFileSync('python', ['-c', py, key, dest], {stdio:'inherit'});
}

async function verifyPublicVideo(token, videoId) {
  const response = await fetch('https://www.googleapis.com/youtube/v3/videos?part=status,snippet&id=' + encodeURIComponent(videoId), {
    headers: {Authorization: 'Bearer ' + token}
  });
  if (!response.ok) throw new Error('YouTube publication verification failed for ' + videoId + ' (' + response.status + '): ' + (await response.text()).slice(0, 400));
  const data = await response.json();
  const video = data.items?.[0];
  if (!video) return {exists:false, privacyStatus:null};
  return {exists:true, privacyStatus:video.status?.privacyStatus || 'unknown', title:video.snippet?.title || ''};
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
  const verification = await verifyPublicVideo(token, result.id);
  if (!verification.exists || verification.privacyStatus !== 'public') throw new Error('YouTube API did not independently confirm '+result.id+' is public (status='+verification.privacyStatus+').');
  console.log('BLENDER_UPLOAD_CONFIRMED_PUBLIC '+job.project_id+' https://www.youtube.com/watch?v='+result.id+' title='+verification.title);
  return {job:job.project_id,videoId:result.id,url:'https://www.youtube.com/watch?v='+result.id,privacyStatus:result.status.privacyStatus,title:p.title};
}

(async()=>{
  const results=[], failures=[];
  const reportPath='blender-publish-results.json';
  const persist=()=>fs.writeFileSync(reportPath,JSON.stringify({publishedAt:new Date().toISOString(),results,failures},null,2)+'\n');
  const manifest=r2Manifest('get');
  persist();
  for(const job of batch.jobs){
    const p=job.project||{};
    const key=String(job.user_id||'offline')+'/'+job.project_id+'/'+job.id+'.mp4';
    const file='/tmp/'+job.project_id+'.mp4';
    try {
      const prior=manifest[job.project_id];
      if(prior?.videoId){
        const verification = await verifyPublicVideo(process.env.YOUTUBE_ACCESS_TOKEN, prior.videoId);
        if (verification.exists && verification.privacyStatus === 'public') {
          console.log('SKIP_ALREADY_PUBLISHED_AND_VERIFIED_PUBLIC '+job.project_id+' https://www.youtube.com/watch?v='+prior.videoId);
          results.push({job:job.project_id,videoId:prior.videoId,url:'https://www.youtube.com/watch?v='+prior.videoId,privacyStatus:'public',title:verification.title||p.title,reused:true,verifiedAt:new Date().toISOString()});
          persist();
          continue;
        }
        console.warn('EXISTING_VIDEO_NOT_PUBLIC_OR_MISSING '+job.project_id+' oldVideoId='+prior.videoId+' status='+verification.privacyStatus+'; uploading replacement instead.');
        delete manifest[job.project_id];
        r2Manifest('put',manifest);
      }
      console.log('Downloading Blender render from R2: '+key);
      r2Download(key,file);
      const result=await upload(process.env.YOUTUBE_ACCESS_TOKEN,job,file);
      results.push(result);
      manifest[job.project_id]={videoId:result.videoId,privacyStatus:'public',title:p.title||null,publishedAt:new Date().toISOString()};
      r2Manifest('put',manifest);
      persist();
    } catch(e) {
      const failure={job:job.project_id,title:p.title||null,error:String(e?.message||e).slice(0,1200)};
      failures.push(failure);
      console.error('BLENDER_VIDEO_PUBLISH_FAILED '+job.project_id+': '+failure.error);
      persist();
    } finally {
      fs.rmSync(file,{force:true});
    }
  }
  persist();
  if(failures.length){console.error('BLENDER_BATCH_PARTIAL_FAILURE: '+results.length+' confirmed public, '+failures.length+' failed. See blender-publish-results.json.');process.exitCode=1;}
  else console.log('BLENDER_BATCH_PUBLISHED: all '+results.length+' videos confirmed public. See blender-publish-results.json.');
})().catch(e=>{console.error('BLENDER_BATCH_PUBLISH_FAILED: '+(e?.stack||e));process.exit(1);});
