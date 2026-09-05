function cleanToken(v){return String(v||'').replace(/[^A-Za-z0-9]/g,'').trim();}
function words(v){return String(v||'').toLowerCase().match(/[a-z0-9]+/g)||[];}
const STOP=new Set(['this','that','with','from','have','will','your','they','them','then','into','about','while','where','when','what','video','chapter','episode','story','original','rolixa','the','and','for','are','but','not','you','was','were','has','had','its','our','their']);
function titleCase(s){return String(s||'').split(/\s+/).filter(Boolean).map(x=>x[0]?.toUpperCase()+x.slice(1).toLowerCase()).join('');}
function add(arr,value){const t=cleanToken(value);if(t.length>=3&&!arr.some(x=>x.toLowerCase()===t.toLowerCase()))arr.push(t);}
function generateHashtags(project,max=55){
  const out=[]; const text=[project.title,project.topic,project.style,project.format,project.hook,project.script].filter(Boolean).join(' ');
  add(out,'Rolixa'); add(out,'RolixaOriginal');
  const title=String(project.title||''); const series=title.split(/[—:-]/)[0].trim(); if(series&&series.length<40){add(out,titleCase(series));add(out,titleCase(series)+'Series');}
  const ep=title.match(/(?:episode|chapter)\s*(\d+)/i); if(ep){add(out,'Episode'+ep[1]);add(out,'Chapter'+ep[1]);}
  const format=cleanToken(project.format); const style=cleanToken(project.style); if(format)add(out,format); if(style)add(out,style);
  const freq=new Map(); for(const w of words(text)){if(w.length<4||STOP.has(w))continue;freq.set(w,(freq.get(w)||0)+1);}
  const ranked=[...freq.entries()].sort((a,b)=>b[1]-a[1]||b[0].length-a[0].length).map(x=>x[0]);
  for(const w of ranked.slice(0,30))add(out,titleCase(w));
  for(let i=0;i<ranked.length;i++)for(let j=i+1;j<Math.min(ranked.length,i+5);j++){const a=ranked[i],b=ranked[j];if(a!==b)add(out,titleCase(a)+titleCase(b));if(out.length>=max-8)break;} 
  const low=text.toLowerCase();
  const groups=[
    [['short','shorts'],'YouTubeShorts'],[['animation','animated','cartoon'],'Animation'],[['nature','wildlife','animal','ocean','forest'],'Nature'],[['science','space','planet','technology'],'Science'],[['history','historic','ancient'],'History'],[['mystery','clue','secret'],'Mystery'],[['business','money','entrepreneur'],'Business'],[['gaming','game','gamer'],'Gaming'],[['sports','football','basketball','soccer'],'Sports'],[['movie','film','cinema'],'Movies']
  ];
  for(const [terms,tag] of groups)if(terms.some(x=>low.includes(x)))add(out,tag);
  return out.slice(0,Math.min(55,max)).map(x=>'#'+x);
}
function appendHashtags(description,project,max=55){const tags=generateHashtags(project,max);const base=String(description||project.topic||'Original Rolixa video').trim();const room=Math.max(0,5000-base.length-2);let line='';for(const t of tags){const next=(line?line+' ':'')+t;if(next.length>room)break;line=next;}return {description:(base+(line?'\n\n'+line:'')).slice(0,5000),hashtags:tags};}
module.exports={generateHashtags,appendHashtags};
