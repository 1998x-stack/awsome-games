'use strict';
(() => {
  const $ = (id) => document.getElementById(id);
  const state = { all: [], visible: [], limit: 36, page: 1, data: null };
  const grid = $('project-grid');
  const escapeHtml = (s='') => String(s).replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
  const safeUrl = (url) => { try { const u = new URL(url); return ['https:','http:'].includes(u.protocol) ? u.href : ''; } catch { return ''; } };
  // Always load published assets from the Pages site, never jsDelivr (which
  // serves HTML as text/plain), and keep the iframe in an opaque origin.
  const gameUrl = (path) => {
    if (typeof path !== 'string' || !/^games\/_repos\/[A-Za-z0-9_.-]+\/.+\.html?$/.test(path)) return '';
    const parts = path.split('/');
    if (parts.some(p => p === '..' || p === '.' || p === '' || /[\\?#%]/.test(p))) return '';
    return './' + parts.map(encodeURIComponent).join('/');
  };
  function allText(p) {
    return [p.title,p.description,p.creator,p.model_claim,p.model_version,p.content_type,
      ...(p.categories||[]).map(c=>c.name),...(p.repositories||[]).map(r=>r.full_name),
      ...(p.links||[]).map(l=>l.url)].join(' ').toLocaleLowerCase();
  }
  function populateFilters() {
    const types = [...new Set(state.all.map(p=>p.content_type).filter(Boolean))].sort();
    const typeNames = {game:'游戏',interactive_experience:'互动体验',interactive_art:'互动艺术',generative_art:'生成艺术',visual_experiment:'视觉实验',animation:'动画',web_tool:'网页工具',music_audio:'音乐与声音',data_visualization:'数据可视化',video_demo:'视频演示',creative_coding:'创意编程'};
    $('type-filter').innerHTML += types.map(t=>`<option value="${escapeHtml(t)}">${escapeHtml(typeNames[t]||t)}</option>`).join('');
    const cats = new Map(); state.all.flatMap(p=>p.categories||[]).forEach(c=>cats.set(c.id,c.name));
    $('category-filter').innerHTML += [...cats].sort((a,b)=>a[1].localeCompare(b[1],'zh-CN')).map(([id,name])=>`<option value="${escapeHtml(id)}">${escapeHtml(name)}</option>`).join('');
  }
  function matches(p) {
    const term=$('search').value.trim().toLocaleLowerCase();
    const model=$('model-filter').value, type=$('type-filter').value, category=$('category-filter').value, source=$('source-filter').value;
    if (term && !allText(p).includes(term)) return false;
    if (model && (model==='unknown' ? p.model_version!=='unknown' : p.model_version!==model)) return false;
    if (type && p.content_type!==type) return false;
    if (category && !(p.categories||[]).some(c=>c.id===category)) return false;
    const hasRepo=(p.repositories||[]).length>0, hasEntry=!!p.published_game_path, hasDemo=(p.demos||[]).length>0;
    if (source==='repo'&&!hasRepo) return false;
    if (source==='cloned'&&!p.repositories.some(r=>r.clone_status==='cloned')) return false;
    if (source==='entry'&&!hasEntry) return false;
    if (source==='demo'&&(!hasDemo||hasRepo)) return false;
    return true;
  }
  function card(p) {
    const categories=(p.categories||[]).slice(0,3).map(c=>`<span class="chip">${escapeHtml(c.name)}</span>`).join('');
    const hasRepo=(p.repositories||[]).length>0, hasEntry=!!p.published_game_path, hasDemo=(p.demos||[]).length>0;
    const repo=p.repositories?.[0]?.html_url || '';
    const demo=p.demos?.[0] || '';
    const badge=hasEntry?'<span class="chip status-entry">HTML 入口已发现</span>':hasRepo?'<span class="chip status-repo">有源码仓库</span>':hasDemo?'<span class="chip status-demo">在线演示</span>':'<span class="chip">未找到源码</span>';
    const model=p.model_version==='unknown'?'模型未标注':`Fable ${escapeHtml(p.model_version)}`;
    return `<article class="project-card">
      <div class="card-top"><span class="card-id">${escapeHtml(p.id)}</span><span class="model-tag">${model}</span></div>
      <h3>${escapeHtml(p.title)}</h3>
      <p class="card-desc">${escapeHtml(p.description||'暂无简介。可以从作品仓库、演示链接或原作者资料继续了解。')}</p>
      <div class="chips">${categories}${badge}</div>
      <div class="card-foot"><span class="creator">${escapeHtml(p.creator||'作者未标注')}</span><div class="card-actions">
        ${hasEntry?`<button class="play-button" data-play="${escapeHtml(p.slug)}">尝试试玩 ↗</button>`:demo?`<a href="${escapeHtml(safeUrl(demo))}" target="_blank" rel="noopener noreferrer">在线演示 ↗</a>`:''}
        ${repo?`<a href="${escapeHtml(safeUrl(repo))}" target="_blank" rel="noopener noreferrer">源码 ↗</a>`:''}
      </div></div>
    </article>`;
  }
  function render() {
    state.visible=state.all.filter(matches); state.page=1;
    $('result-count').textContent=`显示 ${Math.min(state.limit,state.visible.length)} / ${state.visible.length} 个作品`;
    $('catalog-caption').textContent=`当前目录 ${state.all.length} 个作品 · 分类、源码、演示与作者信息按证据分别记录`;
    $('empty-state').hidden=state.visible.length!==0;
    $('load-more').hidden=state.visible.length<=state.limit;
    paint();
  }
  function paint() {
    const end=state.page*state.limit, rows=state.visible.slice(0,end);
    grid.innerHTML=rows.map(card).join('') || '';
    $('result-count').textContent=`显示 ${rows.length} / ${state.visible.length} 个作品`;
    $('load-more').hidden=rows.length>=state.visible.length;
    grid.querySelectorAll('[data-play]').forEach(btn=>btn.addEventListener('click',()=>play(btn.dataset.play)));
  }
  function play(slug) {
    const p=state.all.find(x=>x.slug===slug); if(!p||!p.published_game_path)return;
    const url=gameUrl(p.published_game_path);
    if (!url) return;
    const dialog=$('play-dialog'), frame=$('game-frame');
    $('play-title').textContent=p.title;
    const external = safeUrl(p.demos?.[0] || '');
    $('open-game').hidden=!external;
    if (external) $('open-game').href=external;
    $('player-notice').textContent='在沙箱化 iframe 中加载本仓库经授权发布的静态源码副本；已发现入口不等于实际试玩通过。部分游戏可能因浏览器跨域限制无法运行。';
    frame.src=url;
    if(typeof dialog.showModal==='function') dialog.showModal();
  }
  function exportCsv() {
    const rows=state.visible, cols=['id','slug','title','model_version','content_type','categories','creator','source_status','playable_status','repositories','demos'];
    const quote=x=>'"'+String(x??'').replaceAll('"','""')+'"';
    const lines=[cols,...rows.map(p=>[p.id,p.slug,p.title,p.model_version,p.content_type,(p.categories||[]).map(c=>c.name).join('; '),p.creator,p.source_status,p.playable_status,(p.repositories||[]).map(r=>r.full_name).join('; '),(p.demos||[]).join('; ')])];
    const blob=new Blob(['\ufeff'+lines.map(r=>r.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});
    const a=document.createElement('a');a.href=URL.createObjectURL(blob);a.download='awsome-games-filtered.csv';a.click();URL.revokeObjectURL(a.href);
  }
  async function init() {
    try {
      const response=await fetch('./data/catalog.json',{cache:'no-store'}); if(!response.ok) throw new Error(`catalog.json HTTP ${response.status}`);
      state.data=await response.json(); state.all=state.data.projects||[];
      const s=state.data.summary||{};
      $('stat-projects').textContent=s.projects??state.all.length;
      $('stat-repos').textContent=s.repositories??'—';
      $('stat-demos').textContent=s.projects_with_demo??'—';
      $('stat-entrypoints').textContent=s.projects_published_for_play??'0';
      populateFilters();
      ['search','model-filter','type-filter','category-filter','source-filter'].forEach(id=>$(id).addEventListener(id==='search'?'input':'change',render));
      $('load-more').addEventListener('click',()=>{state.page++;paint()});
      $('export-csv').addEventListener('click',exportCsv);
      $('close-player').addEventListener('click',()=>{$('game-frame').src='about:blank';$('play-dialog').close()});
      $('play-dialog').addEventListener('click',e=>{if(e.target===$('play-dialog')){$('game-frame').src='about:blank';$('play-dialog').close()}});
      render();
    } catch(err) {
      grid.innerHTML=`<div class="loading">目录加载失败：${escapeHtml(err.message)}<br>请通过本地 HTTP 服务打开页面，而不是直接使用 file://。</div>`;
    }
  }
  init();
})();
