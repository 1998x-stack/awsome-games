'use strict';
(() => {
  const $ = id => document.getElementById(id);
  const state={data:null,kind:'works',filtered:[],shown:48,term:'',filter:''};
  const sections=['works','posts','repositories','claims'];
  const labels={works:'已映射工程作品',posts:'原帖实体线索',repositories:'候选源码仓库',claims:'归属冲突与反证'};
  const statusLabel=s=>String(s||'尚未核验').replaceAll('_',' ');
  const safeUrl=value=>{
    try {
      const u=new URL(String(value||''));
      return (u.protocol==='http:'||u.protocol==='https:')&&!u.username&&!u.password?u.href:'';
    } catch{return '';}
  };
  const nonempty=v=>v!==undefined&&v!==null&&v!=='';
  const text=(tag,value,cls)=>{
    const node=document.createElement(tag);
    node.textContent=String(value??'');
    if(cls)node.className=cls;
    return node;
  };
  function link(url,label){
    const href=safeUrl(url);if(!href)return text('span',label||url);
    const a=document.createElement('a');a.href=href;a.textContent=label||href;
    a.target='_blank';a.rel='noopener noreferrer';a.referrerPolicy='no-referrer';return a;
  }
  function info(kind,item){
    if(kind==='works'){
      return {title:item.title,id:item.work_id,description:item.rendering_stack||'等待代码级核验',
        status:item.entry_status,tags:[item.artifact_kind,item.repository_model_evidence,item.prompt_status],
        link:item.source_url||'',links:[
          ['作品编号',item.work_id],['GitHub仓库',item.repository_full_name?'https://github.com/'+item.repository_full_name:null],
          ['README / PR 证据',item.readme_url],['演示/原始发布',item.demo_url],
          ['源码入口（文件树）',item.entry_path||'未确认'],['入口确认状态',item.entry_status],
          ['渲染技术（社区来源）',item.rendering_stack],['源码构建方法（社区来源）',item.build_method],
          ['交付/发布产物（社区来源）',item.artifact_kind],
          ['外部资源和运行条件',item.external_dependencies],
          ['提示词公开状态',item.prompt_status],['原始提示词',item.prompt_evidence_url],
          ['人工参与信息（仅作者自述）',item.human_contribution],
          ['人工参与验证状态',item.human_status],
          ['模型归属（原仓库）',item.repository_model_evidence],['仓库关系',item.repository_relation],
          ['开源授权标记',item.license_state],['README核验等级',item.evidence_level],
          ['人工审核结论状态',item.review_status],['人工审核证据URL',item.review_evidence_url],['人工审核日期',item.reviewed_at],
          ['浏览器加载报告',item.latest_browser_evidence?.report_status||'NOT_TESTED'],
          ['浏览器报告 ID',item.latest_browser_evidence?.evidence_id],
          ['测试 Git commit',item.latest_browser_evidence?.repo_commit_sha],
          ['入口 SHA-256',item.latest_browser_evidence?.entry_sha256],
          ['测试时间',item.latest_browser_evidence?.tested_at],
          ['实际游戏交互验证',item.execution_verified?'GAMEPLAY_VERIFIED':'NOT_VERIFIED / 无交互认证'],
          ['证据/来源仓库',item.source_url]
        ]};
    }
    if(kind==='posts'){
      return {title:item.title||item.post_key,id:item.post_key,description:item.creator||item.category||'来源帖子',
        status:item.entity_status,tags:[item.kind_signal,item.confidence,item.model_claim],
        link:item.post_url,links:[
          ['原始 X 帖子',item.post_url],['归并实体ID',item.entity_id],
          ['作品主表ID',item.work_id],['作者/账号',item.creator],['内容类型',item.category],
          ['来源重叠',item.sources],['匹配规则',item.match_status],
          ['证据置信度',item.confidence],['模型说法（未经校验）',item.model_claim],
          ['提示词在来源中的公开状态',item.prompt_availability],
          ['所有试玩链接',item.play_urls],['源码仓库候选链接',item.repo_urls],
          ['审核结论状态',item.review_status],['审核依据',item.review_evidence_url],
          ['归并状态',item.entity_status]
        ]};
    }
    if(kind==='repositories'){
      return {title:item.display_title||item.full_name,id:item.full_name,description:item.tech||'待人工代码级审查',
        status:item.model_evidence,tags:[item.relation,item.browser_hint,item.license_state],
        link:'https://github.com/'+item.full_name,links:[
          ['GitHub仓库','https://github.com/'+item.full_name],['归属来源',item.source_channel],
          ['仓库角色',item.relation],['可浏览器运行的静态线索',item.browser_hint],
          ['技术形态（文件树扫描）',item.tech],['代码许可证元数据',item.license_state],
          ['具体模型证据',item.model_evidence],['审阅层级',item.review_level],
          ['README与来源',item.readme_url],['原索引与项目链接',item.evidence_url],
          ['是否已测试源码运行',item.browser_status],['来源说明',item.source_note]
        ]};
    }
    return {title:item.item||item.claim_id,id:item.claim_id,description:item.proposition||'待核验证据',
      status:item.status,tags:[item.status],link:item.primary_url,
      links:[['待验证论断',item.proposition],['证据状态',item.status],
        ['推荐模型标注',item.model_recommendation],['仓库/作品关系建议',item.relation_recommendation],
        ['直接证据',item.primary_url],['原帖/反证',item.counter_url],['未解决问题',item.limitation]]};
  }
  function tag(label,warn=false){
    if(!nonempty(label))return null;
    return text('span',statusLabel(label),'lab-tag'+(warn?' warn':''));
  }
  function card(kind,item){
    const v=info(kind,item),node=document.createElement('article');node.className='lab-card';
    const top=document.createElement('div');top.className='lab-card-top';
    top.append(text('span',v.id),text('span',statusLabel(v.status)));
    const title=text('h3',v.title),desc=text('p',v.description,'lab-desc');
    const tags=document.createElement('div');tags.className='lab-tags';
    v.tags.filter(nonempty).slice(0,4).forEach((s,i)=>tags.append(tag(s,i===0&&/UNVERIFIED|NOT_TESTED|DISPUTED|REFUTED/.test(String(s)))));
    const foot=document.createElement('div');foot.className='lab-card-foot';
    foot.append(link(v.link,'来源 ↗'));
    const btn=text('button','查看工程证据 →');btn.type='button';btn.addEventListener('click',()=>detail(kind,item));
    foot.append(btn);node.append(top,title,desc,tags,foot);return node;
  }
  function detail(kind,item){
    const v=info(kind,item),target=$('lab-detail-body');target.replaceChildren();
    target.append(text('h2',v.title,'lab-detail-title'),text('p',String(v.id)+'  ·  '+labels[kind],'lab-detail-sub'));
    const dl=document.createElement('dl');dl.className='lab-dl';
    for(const [label,value] of v.links){
      if(!nonempty(value))continue;
      dl.append(text('dt',label));
      const dd=document.createElement('dd');
      if(Array.isArray(value)){
        value.forEach((u,i)=>{if(i)dd.append('  ·  ');dd.append(safeUrl(u)?link(u):text('span',u));});
      }else if(safeUrl(value))dd.append(link(value));
      else dd.textContent=String(value);
      dl.append(dd);
    }
    target.append(dl,text('p','模型声明可能是作者或社区自报。入口路径只经文件树审阅，未执行即不得标记为可玩。','lab-download-note'));
    const dialog=$('lab-detail');if(!dialog.open)dialog.showModal();
  }
  function matchingItem(item){
    const s=JSON.stringify(item).toLocaleLowerCase();
    return (!state.term||s.includes(state.term))&&(!state.filter||info(state.kind,item).status===state.filter);
  }
  function filterOptions(){
    const sel=$('lab-filter');sel.replaceChildren(new Option('全部证据状态',''));
    const vals=[...new Set((state.data[state.kind]||[]).map(item=>info(state.kind,item).status).filter(Boolean))].sort();
    for(const v of vals)sel.add(new Option(statusLabel(v),v));
  }
  function render(reset=true){
    if(!state.data)return;
    if(reset)state.shown=48;
    state.filtered=(state.data[state.kind]||[]).filter(matchingItem);
    const showing=state.filtered.slice(0,state.shown);
    const container=$('lab-results');container.replaceChildren();
    if(!showing.length)container.append(text('p','没有匹配的记录。请选择更宽松的筛选条件。','lab-loading'));
    else{const frag=document.createDocumentFragment();showing.forEach(x=>frag.append(card(state.kind,x)));container.append(frag);}
    $('lab-status').textContent=labels[state.kind]+'：显示 '+showing.length+' / '+state.filtered.length+' 条。归并状态与源码运行状态需分开理解。';
    $('lab-caption').textContent='采集于 '+state.data.captured_at+' · 原始来源记录不等于独立游戏。';
    $('lab-more').hidden=state.shown>=state.filtered.length;
  }
  function select(kind){
    if(!sections.includes(kind))return;
    state.kind=kind;state.filter='';$('lab-filter').value='';
    document.querySelectorAll('[data-kind]').forEach(x=>x.setAttribute('aria-current',x.dataset.kind===kind?'page':'false'));
    filterOptions();render();
  }
  function exportCsv(){
    const rows=state.filtered;
    const quote=x=>{
      let s=typeof x==='object'?JSON.stringify(x):String(x??'');
      if(/^[=+\-@\t\r]/.test(s))s="'"+s; // prevent spreadsheet formula evaluation
      return '"'+s.replaceAll('"','""')+'"';
    };
    const file=[['kind','id','title','status','evidence_url'],...rows.map(x=>{
      const v=info(state.kind,x);return[state.kind,v.id,v.title,v.status,v.link]})];
    const blob=new Blob(['\ufeff'+file.map(r=>r.map(quote).join(',')).join('\r\n')],{type:'text/csv;charset=utf-8'});
    const url=URL.createObjectURL(blob);const a=document.createElement('a');a.href=url;a.download='awsome-games-evidence-'+state.kind+'.csv';a.click();
    setTimeout(()=>URL.revokeObjectURL(url),1000);
  }
  async function init(){
    try{
      const response=await fetch('./data/research.json',{cache:'no-store'});
      if(!response.ok)throw Error('HTTP '+response.status);
      const data=await response.json();
      if(data.schema_version!==1||!Array.isArray(data.works)||!Array.isArray(data.posts))throw Error('格式不支持');
      state.data=data;
      for(const kind of sections)$('count-'+kind).textContent=data[kind]?.length||0;
      $('n-source').textContent=data.stats.source_records.toLocaleString();
      $('n-posts').textContent=data.stats.posts.toLocaleString();
      $('n-works').textContent=data.stats.works.toLocaleString();
      $('n-repos').textContent=data.stats.repositories.toLocaleString();
      $('n-claims').textContent=data.stats.claims.toLocaleString();
      document.querySelectorAll('[data-kind]').forEach(x=>x.addEventListener('click',()=>select(x.dataset.kind)));
      $('lab-search').addEventListener('input',e=>{state.term=e.target.value.toLocaleLowerCase().trim();render();});
      $('lab-filter').addEventListener('change',e=>{state.filter=e.target.value;render();});
      $('lab-more').addEventListener('click',()=>{state.shown+=48;render(false);});
      $('lab-export').addEventListener('click',exportCsv);
      $('lab-close').addEventListener('click',()=>$('lab-detail').close());
      $('lab-detail').addEventListener('click',e=>{if(e.target===$('lab-detail'))e.target.close()});
      const params=new URLSearchParams(location.search);
      const requestedKind=params.get('kind');
      select(sections.includes(requestedKind)?requestedKind:'works');
      const itemId=params.get('id')||params.get('work');
      if(itemId){
        const item=(data[state.kind]||[]).find(x=>(x.work_id||x.post_key||x.full_name||x.claim_id)===itemId);
        if(item)detail(state.kind,item);
      }
    }catch(err){$('lab-results').replaceChildren(text('p','研究索引加载失败：'+err.message+'。请运行 scripts/build_catalog.py 和 scripts/build_site.py，并通过 HTTP 服务访问。','lab-loading'));}
  }
  init();
})();
