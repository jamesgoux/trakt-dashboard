#!/usr/bin/env python3
"""Apply carousel patch to dashboard.html and verify braces."""
import re

with open('templates/dashboard.html', 'r', encoding='utf-8') as f:
    html = f.read()

# 1. Add carousel CSS
old_css = '.un-detail{background:var(--sf);border-radius:12px;border:1px solid rgba(255,255,255,.08);padding:20px;max-width:500px;margin:20px auto}'
new_css = """.un-detail{background:var(--sf);border-radius:12px;border:1px solid rgba(255,255,255,.08);padding:20px;max-width:500px;margin:0 auto}
.un-carousel-wrap{overflow:hidden;max-width:500px;margin:20px auto}
.un-carousel{display:flex;width:300%;transform:translateX(-33.333%);will-change:transform}
.un-carousel.snap{transition:transform .3s ease}
.un-carousel-panel{width:33.333%;flex-shrink:0;padding:0 8px;box-sizing:border-box}"""

if old_css in html:
    html = html.replace(old_css, new_css)
    print("CSS replaced")
else:
    print("CSS not found - checking if already applied")

# 2. Find and replace _unRenderDetail + _unSlideNav
# Find the exact boundaries
start_marker = "function _unRenderDetail(allShows,idx){"
end_marker = "function markWatchedAt("

start_idx = html.find(start_marker)
end_idx = html.find(end_marker)

if start_idx < 0 or end_idx < 0:
    print(f"ERROR: Could not find function boundaries. start={start_idx}, end={end_idx}")
    exit(1)

new_code = r"""function _unBuildPanel(show){
  var slug2=show.slug.replace(/'/g,"\\'");
  var h='<div class="un-detail">';
  h+='<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">';
  h+='<button onclick="openUpNext()" style="background:var(--sf);border:1px solid rgba(255,255,255,.1);color:var(--tx);border-radius:8px;padding:10px 16px;font-size:14px;cursor:pointer">← Back</button>';
  h+='<div style="display:flex;gap:8px">';
  if(show.episode>1)h+='<button onclick="_crNav(-1)" style="background:var(--sf);border:1px solid rgba(255,255,255,.1);color:var(--tx);border-radius:8px;padding:10px 16px;font-size:16px;cursor:pointer;min-width:48px">◀</button>';
  h+='<button onclick="_crNav(1)" style="background:var(--sf);border:1px solid rgba(255,255,255,.1);color:var(--tx);border-radius:8px;padding:10px 16px;font-size:16px;cursor:pointer;min-width:48px">▶</button>';
  h+='</div></div>';
  if(show.ep_still)h+='<img src="'+show.ep_still+'" alt="" style="width:100%;border-radius:10px;margin-bottom:14px;max-height:280px;object-fit:cover">';
  h+='<div style="font-size:20px;font-weight:700;margin-bottom:4px">'+show.show+'</div>';
  h+='<div style="font-size:14px;color:var(--t2);margin-bottom:4px">S'+String(show.season).padStart(2,'0')+'E'+String(show.episode).padStart(2,'0');
  if(show.ep_title)h+=' — '+show.ep_title;
  h+='</div>';
  if(show.ep_aired)h+='<div style="font-size:12px;color:var(--t2);margin-bottom:8px">📅 '+show.ep_aired+'</div>';
  if(show.stream&&show.stream.length){h+='<div style="display:flex;gap:8px;margin-bottom:12px">';show.stream.forEach(function(st){h+='<img src="'+st.i+'" title="'+st.n+'" style="width:28px;height:28px;border-radius:6px">'});h+='</div>'}
  if(show.ep_runtime)h+='<div style="font-size:12px;color:var(--t2);margin-bottom:8px">⏱ '+_unFmtMin(show.ep_runtime)+'</div>';
  if(show.ep_overview)h+='<p style="font-size:13px;color:var(--t2);line-height:1.5;margin-bottom:16px">'+show.ep_overview+'</p>';
  h+='<div style="display:flex;gap:8px;margin-bottom:8px">';
  h+='<button onclick="markWatchedAt(\''+slug2+'\','+show.season+','+show.episode+','+(show.ep_trakt_id||0)+',\'now\')" style="flex:1;padding:14px;background:var(--tv);color:#fff;border:none;border-radius:10px;font-size:14px;cursor:pointer;font-weight:600">✓ Watched Now</button>';
  if(show.ep_aired)h+='<button onclick="markWatchedAt(\''+slug2+'\','+show.season+','+show.episode+','+(show.ep_trakt_id||0)+',\''+show.ep_aired+'\')" style="flex:1;padding:14px;background:var(--sf);color:var(--tx);border:1px solid rgba(255,255,255,.1);border-radius:10px;font-size:14px;cursor:pointer">📅 Watched at Air</button>';
  h+='</div>';
  h+='<div style="display:flex;gap:8px"><input type="datetime-local" id="un-custom-date" style="flex:1;padding:12px;background:var(--bg);border:1px solid rgba(255,255,255,.15);border-radius:10px;color:var(--tx);font-size:13px"><button onclick="markWatchedAt(\''+slug2+'\','+show.season+','+show.episode+','+(show.ep_trakt_id||0)+',document.getElementById(\'un-custom-date\').value)" style="padding:12px 16px;background:var(--sf);color:var(--tx);border:1px solid rgba(255,255,255,.1);border-radius:10px;font-size:13px;cursor:pointer">Set</button></div>';
  h+='</div>';
  return h;
}

var _crBase=null,_crEp=0,_crAll=null,_crIdx=0;

function _unMakeEp(base,epNum){
  if(epNum<1)return Object.assign({},base,{episode:0,ep_title:'',ep_overview:'',ep_still:'',ep_aired:''});
  var k=_epCacheKey(base.tmdb_id,base.season,epNum);
  var c=_epCache[k];
  var ns=JSON.parse(JSON.stringify(base));
  ns.episode=epNum;
  if(c){ns.ep_title=c.ep_title;ns.ep_overview=c.ep_overview;ns.ep_still=c.ep_still;ns.ep_aired=c.ep_aired;ns.ep_runtime=c.ep_runtime}
  else{ns.ep_title='';ns.ep_overview='';ns.ep_still='';ns.ep_aired=''}
  return ns;
}

function _unRenderDetail(allShows,idx){
  var show=allShows[idx];
  _crBase=show;_crEp=show.episode;_crAll=allShows;_crIdx=idx;
  window._unAllShows=allShows;window._unIdx=idx;
  var el=document.getElementById('un-content');
  var prev=_unMakeEp(show,show.episode-1);
  var next=_unMakeEp(show,show.episode+1);
  var h='<div class="un-carousel-wrap"><div class="un-carousel" id="un-car">';
  h+='<div class="un-carousel-panel">'+_unBuildPanel(prev)+'</div>';
  h+='<div class="un-carousel-panel">'+_unBuildPanel(show)+'</div>';
  h+='<div class="un-carousel-panel">'+_unBuildPanel(next)+'</div>';
  h+='</div></div>';
  el.innerHTML=h;
  var car=document.getElementById('un-car');
  var w=car.parentElement.offsetWidth;
  var sx=0,cx=0,drag=false;
  car.ontouchstart=function(ev){sx=ev.touches[0].clientX;cx=sx;drag=true;car.classList.remove('snap')};
  car.ontouchmove=function(ev){if(!drag)return;cx=ev.touches[0].clientX;var dx=cx-sx;var pct=-33.333+(dx/w)*33.333;car.style.transform='translateX('+pct+'%)'};
  car.ontouchend=function(){
    if(!drag)return;drag=false;var dx=cx-sx;
    car.classList.add('snap');
    if(dx>w*0.2&&_crEp>1){car.style.transform='translateX(0%)';setTimeout(function(){_crNav(-1)},320)}
    else if(dx<-w*0.2){car.style.transform='translateX(-66.666%)';setTimeout(function(){_crNav(1)},320)}
    else{car.style.transform='translateX(-33.333%)'}
  };
  document.getElementById('un-overlay').scrollTop=0;
  _unPrefetch(show,show.episode-1);
  _unPrefetch(show,show.episode+1);
}

function _crNav(dir){
  var newEp=_crEp+dir;
  if(newEp<1)return;
  var k=_epCacheKey(_crBase.tmdb_id,_crBase.season,newEp);
  var c=_epCache[k];
  var ns=JSON.parse(JSON.stringify(_crBase));
  ns.episode=newEp;
  if(c){ns.ep_title=c.ep_title;ns.ep_overview=c.ep_overview;ns.ep_still=c.ep_still;ns.ep_aired=c.ep_aired;ns.ep_runtime=c.ep_runtime}
  else{ns.ep_title='';ns.ep_overview='';ns.ep_still='';ns.ep_aired=''}
  _crEp=newEp;
  var ts=_crAll.slice();ts[_crIdx]=ns;
  _unRenderDetail(ts,_crIdx);
  if(!c){
    var tk=(D.un||{}).tmdb_key||'';
    if(tk){
      fetch('https://api.themoviedb.org/3/tv/'+_crBase.tmdb_id+'/season/'+_crBase.season+'/episode/'+newEp+'?api_key='+tk)
        .then(function(r){return r.json()})
        .then(function(d){
          if(d.status_code)return;
          _epCache[k]={ep_title:d.name||'',ep_overview:(d.overview||'').substring(0,200),ep_still:d.still_path?'https://image.tmdb.org/t/p/w780'+d.still_path:'',ep_aired:d.air_date||'',ep_runtime:d.runtime||_crBase.ep_runtime};
          ns.ep_title=_epCache[k].ep_title;ns.ep_overview=_epCache[k].ep_overview;ns.ep_still=_epCache[k].ep_still;ns.ep_aired=_epCache[k].ep_aired;ns.ep_runtime=_epCache[k].ep_runtime;
          var ts2=_crAll.slice();ts2[_crIdx]=ns;
          _unRenderDetail(ts2,_crIdx);
        }).catch(function(){});
    }
  }
}

"""

# Replace the old code
html = html[:start_idx] + new_code + html[end_idx:]

# Remove old _unSlideNav if it exists
html = html.replace("""function _unSlideNav(base,epNum,allShows,origIdx,dir){
  _unCarouselNav(dir==='left'?1:-1);
}

""", "")

# Verify braces
script_idx = html.find('<script>')
js = html[script_idx+8:]
end_js = js.find('</script>')
js = js[:end_js]
opens = js.count('{')
closes = js.count('}')
print(f"Braces: {opens} / {closes}, diff={opens-closes}")

depth = 0
for i, line in enumerate(js.split('\n')):
    for ch in line:
        if ch == '{': depth += 1
        elif ch == '}': depth -= 1
    if depth < 0:
        print(f"NEGATIVE at line {i+1}: {line[:80]}")
        exit(1)

print(f"No negative depth. Final: {depth}")

if opens != closes or depth != 0:
    print("BRACE MISMATCH - NOT SAVING")
    exit(1)

with open('templates/dashboard.html', 'w', encoding='utf-8') as f:
    f.write(html)
print("Saved successfully")
