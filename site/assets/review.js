'use strict';
(() => {
  const $=id=>document.getElementById(id);
  const state={data:null,kind:'repositories',term:'',route:'',shown:48};
  const kinds=['repositories','posts','works','alias_candidates'];
  const label={repositories:'仓库候选',posts:'原帖线索',works:'工程作品',alias_candidates:'别名候选'};
  const elt=(tag,txt,cls)=>{const n=document.createElement(tag);n.textContent=String(txt??'');if(cls)n.className=cls;return n};
  // Resolve against the current document so same-origin cross-navigation (the
  // Evidence Lab link) actually renders as an anchor, while still rejecting
  // javascript:/data:, embedded credentials and other unsafe schemes.
  const safeUrl=value=>{
    try{
      const url=new URL(String(value??''),document.baseURI);
      if(!['https:','http:'].includes(url.protocol)||url.username||url.password)return '';
      if(url.origin!==location.origin)return url.href;
      // Keep same-origin targets relative so GitHub project Pages subpaths
      // (https://<user>.github.io/<repo>/) keep working.
      const base=location.pathname.replace(/[^/]*$/,'');
      const rest=base&&url.pathname.startsWith(base)?'./'+url.pathname.slice(base.length):url.pathname;
      return rest+url.search;
    }catch{return ''}
  };
  const rowInfo=(kind,r)=>{
    if(kind==='repositories')return {id:r.full_name,title:r.display_title||r.full_name,
      status:r.queue_kind,detail:r.tech||'无技术信息',action:r.next_action,
      origin:'https://github.com/'+r.full_name,lab:'./research.html?kind=repositories&id='+encodeURIComponent(r.full_name)};
    if(kind==='posts')return {id:r.post_key,title:r.title||r.post_key,status:r.match_status,
      detail:r.creator||r.kind_signal||'',action:r.next_action,origin:r.post_url,
      lab:'./research.html?kind=posts&id='+encodeURIComponent(r.post_key)};
    if(kind==='works')return {id:r.work_id,title:r.title||r.work_id,status:r.entry_status,
      detail:r.repository_full_name||'',action:r.next_action,
      origin:r.repository_full_name?'https://github.com/'+r.repository_full_name:'',
      lab:'./research.html?kind=works&id='+encodeURIComponent(r.work_id)};
    return {id:r.work_id,title:r.catalog_title+' / '+r.source_title,status:r.status,
      detail:r.repository_full_name,action:r.note||'Requires direct evidence',
      origin:r.evidence_url,lab:'./research.html?kind=works&id='+encodeURIComponent(r.work_id)};
  };
  function makeLink(url,label){
    const href=safeUrl(url),a=elt(href?'a':'span',label);
    if(href){a.href=href;a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer'}
    return a;
  }
  function card(r){
    const v=rowInfo(state.kind,r),article=elt('article','','lab-card');
    const top=elt('div','','lab-card-top');top.append(elt('span',v.id),elt('span',v.status));
    const tags=elt('div','','lab-tags');tags.append(elt('span',r.review_status||'CANDIDATE','lab-tag warn'));
    const footer=elt('div','','lab-card-foot');footer.append(makeLink(v.origin,'原始证据 ↗'),makeLink(v.lab,'关联研究记录 ↗'));
    article.append(top,elt('h3',v.title),elt('p',v.detail,'lab-desc'),tags,elt('p',v.action,'lab-desc'),footer);
    return article;
  }
  function routes(){
    const select=$('queue-filter');select.replaceChildren(new Option('全部审核路由',''));
    const values=[...new Set((state.data[state.kind]||[]).map(r=>rowInfo(state.kind,r).status).filter(Boolean))].sort();
    for(const v of values)select.add(new Option(v,v));
  }
  function render(reset=true){
    if(!state.data)return;
    if(reset)state.shown=48;
    const rows=(state.data[state.kind]||[]).filter(r=>{
      const v=rowInfo(state.kind,r);
      return (!state.route||v.status===state.route)&&(!state.term||JSON.stringify(r).toLocaleLowerCase().includes(state.term));
    });
    const out=$('queue-results');out.replaceChildren();
    const subset=rows.slice(0,state.shown);
    if(!subset.length)out.append(elt('p','没有匹配记录。','lab-loading'));
    else {const f=document.createDocumentFragment();for(const x of subset)f.append(card(x));out.append(f)}
    $('queue-status').textContent=label[state.kind]+'：显示 '+subset.length+' / '+rows.length+' 条。此页面不代表已核验或批准。';
    $('queue-more').hidden=state.shown>=rows.length;
  }
  function select(kind){
    if(!kinds.includes(kind))return;
    state.kind=kind;state.route='';$('queue-filter').value='';
    document.querySelectorAll('[data-queue]').forEach(n=>n.setAttribute('aria-current',n.dataset.queue===kind?'page':'false'));
    routes();render();
  }
  async function init(){
    try{
      const res=await fetch('./data/review-queue.json',{cache:'no-store'});
      if(!res.ok)throw Error('HTTP '+res.status);
      const data=await res.json();
      if(data.schema_version!==1||!Array.isArray(data.repositories)||!Array.isArray(data.posts))throw Error('数据格式不兼容');
      state.data=data;
      $('q-posts').textContent=data.stats.post_review_queue.toLocaleString();
      $('q-works').textContent=data.stats.work_review_queue.toLocaleString();
      $('q-repos').textContent=data.stats.repository_review_queue.toLocaleString();
      $('q-new').textContent=data.stats.research_only_repository_candidates.toLocaleString();
      $('q-aliases').textContent=data.stats.alias_candidates.toLocaleString();
      document.querySelectorAll('[data-queue]').forEach(n=>n.addEventListener('click',()=>select(n.dataset.queue)));
      $('queue-search').addEventListener('input',e=>{state.term=e.target.value.trim().toLocaleLowerCase();render()});
      $('queue-filter').addEventListener('change',e=>{state.route=e.target.value;render()});
      $('queue-more').addEventListener('click',()=>{state.shown+=48;render(false)});
      const wanted=new URLSearchParams(location.search).get('kind');
      select(kinds.includes(wanted)?wanted:'repositories');
    }catch(e){$('queue-results').replaceChildren(elt('p','审核队列加载失败：'+e.message+'。请先运行站点构建命令。','lab-loading'))}
  }
  init();
})();
