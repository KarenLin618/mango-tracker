"""從 index.html 產生靜態展示版 demo.html：同一套 UI，改用內建示範資料、不接後端。"""

html = open("index.html", encoding="utf-8").read()

# 1) 首頁的「看操作說明」連結導向 /guide
html = html.replace('href="/demo" style="font-size:13px', 'href="/guide" style="font-size:13px')

# 2) 加入示範橫幅樣式
ribbon_css = """
  /* 示範橫幅 */
  .demo-ribbon{background:var(--mango);color:#fff;border-radius:12px;padding:10px 14px;font-size:13px;
    font-weight:500;margin-bottom:16px;display:flex;flex-wrap:wrap;gap:4px 10px;align-items:center}
  .demo-ribbon b{font-weight:700}
  .demo-ribbon a{color:#fff;text-decoration:underline;font-weight:700}
</style>"""
html = html.replace("</style>", ribbon_css, 1)

# 3) 在 #app 內最前面插入橫幅
banner = ('<div id="app" class="wrap">\n\n'
          '  <div class="demo-ribbon"><b>示範畫面</b>　這是用假資料呈現的實際介面，可以隨意點按試玩，'
          '但<b>不會儲存</b>。　<a href="/guide">看操作說明</a>　·　<a href="/">開啟正式版 →</a></div>')
html = html.replace('<div id="app" class="wrap">', banner, 1)

# 4) 置換整段 Vue app JS：改成內建示範資料、方法只改記憶體不打 API
demo_js = r"""const { createApp } = Vue;

// 示範用固定「今天」，讓畫面永遠呈現合理的熟成狀態
function todayISO(){ return '2026-07-12'; }
function parse(iso){ if(!iso) return null; const [y,m,d]=iso.split('-').map(Number); return new Date(y,m-1,d); }
function addDays(iso,n){ const d=parse(iso); if(!d) return null; d.setDate(d.getDate()+n);
  return `${d.getFullYear()}-${String(d.getMonth()+1).padStart(2,'0')}-${String(d.getDate()).padStart(2,'0')}`; }
function diffDays(aIso,bIso){ const a=parse(aIso),b=parse(bIso); if(!a||!b) return null;
  return Math.round((b-a)/86400000); }

// 內嵌一張示範芒果圖（SVG data URL，不需外部檔案）
const SAMPLE_PHOTO = 'data:image/svg+xml;utf8,' + encodeURIComponent(
  '<svg xmlns="http://www.w3.org/2000/svg" width="300" height="200">' +
  '<defs><linearGradient id="g" x1="0" y1="0" x2="1" y2="1">' +
  '<stop offset="0" stop-color="#F6B24A"/><stop offset="1" stop-color="#E8582C"/></linearGradient></defs>' +
  '<rect width="300" height="200" fill="url(#g)"/>' +
  '<text x="150" y="128" font-size="96" text-anchor="middle">\U0001F96D</text></svg>');

function seedStore(){
  return {
    plans:[
      {id:1,name:'7月愛文一箱',mango_total:6,eaten:1},
    ],
    states:{
      1:{plan:{id:1,name:'7月愛文一箱',received_date:'2026-07-02',target_date:'2026-07-17',count:6,
               fridge_life_days:6,room_ripe_life_days:2,frozen_life_days:60,variety:'愛文'},
         mangoes:[
           {id:101,seq:1,status:'ripe',        ripe_date:'2026-07-11',fridge_date:'',          note:'',                has_photo:true, _photoData:SAMPLE_PHOTO,_pv:0,_busy:false},
           {id:102,seq:2,status:'refrigerated',ripe_date:'2026-07-10',fridge_date:'2026-07-10',note:'',                has_photo:false,_photoData:'',         _pv:0,_busy:false},
           {id:103,seq:3,status:'hard',        ripe_date:'',          fridge_date:'',          note:'',                has_photo:false,_photoData:'',         _pv:0,_busy:false},
           {id:104,seq:4,status:'hard',        ripe_date:'',          fridge_date:'',          note:'蒂頭開始有香味',    has_photo:false,_photoData:'',         _pv:0,_busy:false},
           {id:105,seq:5,status:'eaten',       ripe_date:'2026-07-08',fridge_date:'2026-07-08',note:'',                has_photo:false,_photoData:'',         _pv:0,_busy:false},
           {id:106,seq:6,status:'frozen',      ripe_date:'2026-07-05',fridge_date:'2026-07-05',note:'太早熟，冷凍留著打冰沙',has_photo:false,_photoData:'',    _pv:0,_busy:false},
         ]},
    },
    nextPlanId:2, nextMangoId:300,
  };
}

createApp({
  data(){
    return {
      store: seedStore(),
      cfg:{name:'',received_date:'',target_date:'',count:0,fridge_life_days:6,room_ripe_life_days:2,frozen_life_days:60,variety:'愛文'},
      mangoes:[], plans:[], currentPlanId:null,
      showNewModal:false,
      newForm:{name:'',received_date:'',target_date:'',count:0,variety:'愛文'},
      today: todayISO(), showSaved:false, savedTimer:null, lightbox:null,
    };
  },
  computed:{
    counts(){ const c={hard:0,ripe:0,refrigerated:0,frozen:0,eaten:0};
      this.mangoes.forEach(m=>{ if(c[m.status]!==undefined) c[m.status]++; }); return c; },
    orderedPlan(){ return this.mangoes.filter(m=>m.status!=='eaten'&&m.status!=='hard'&&this.bestEatBy(m))
      .sort((a,b)=>this.bestEatBy(a).localeCompare(this.bestEatBy(b))); },
    urgent(){ return this.orderedPlan.filter(m=>{ const r=this.remainDays(m); return r!==null&&r<=2; }); },
    readyByTarget(){ if(!this.cfg.target_date) return []; return this.mangoes.filter(m=>{
      if(m.status==='eaten') return false; const be=this.bestEatBy(m); if(!be) return false;
      return be.localeCompare(this.cfg.target_date)>=0; }); },
    mustEatByTarget(){ if(!this.cfg.target_date) return []; return this.mangoes.filter(m=>{
      if(m.status==='eaten'||m.status==='hard') return false; const be=this.bestEatBy(m);
      return be&&be.localeCompare(this.cfg.target_date)<=0; }); },
  },
  methods:{
    // ---- 純計算（與正式版相同）----
    statusLabel(s){ return {hard:'硬',ripe:'熟',refrigerated:'已冷藏',frozen:'已冷凍',eaten:'已吃'}[s]||s; },
    dayIndex(iso){ if(!this.cfg.received_date||!iso) return '?'; const d=diffDays(this.cfg.received_date,iso); return d===null?'?':d+1; },
    bestEatBy(m){ const base=(d)=>d||this.today;
      if(m.status==='ripe')         return addDays(base(m.ripe_date),this.cfg.room_ripe_life_days);
      if(m.status==='refrigerated') return addDays(base(m.fridge_date),this.cfg.fridge_life_days);
      if(m.status==='frozen')       return addDays(base(m.fridge_date),this.cfg.frozen_life_days);
      return null; },
    remainDays(m){ const be=this.bestEatBy(m); if(!be) return null; return diffDays(this.today,be); },
    remainText(m){ const r=this.remainDays(m); if(r===null) return '';
      if(r<0) return `已過期 ${-r} 天`; if(r===0) return '今天到期'; return `還剩 ${r} 天`; },
    isAlert(m){ const r=this.remainDays(m); return r!==null&&r<=2&&(m.status==='ripe'||m.status==='refrigerated'); },
    countdownClass(m){ const r=this.remainDays(m); if(r===null) return 'neutral'; if(r<=2) return 'warn'; return 'ok'; },
    onStatusChange(m){
      if(m.status==='ripe'&&!m.ripe_date) m.ripe_date=this.today;
      if((m.status==='refrigerated'||m.status==='frozen')){ if(!m.ripe_date) m.ripe_date=this.today; if(!m.fridge_date) m.fridge_date=this.today; }
      this.saveMango(m);
    },
    flashSaved(){ this.showSaved=true; clearTimeout(this.savedTimer); this.savedTimer=setTimeout(()=>this.showSaved=false,1500); },

    // ---- 資料存取（示範模式：只改記憶體，不打 API）----
    blankMango(seq){ return {id:this.store.nextMangoId++,seq,status:'hard',ripe_date:'',fridge_date:'',note:'',has_photo:false,_photoData:'',_pv:0,_busy:false}; },
    loadPlans(preferId){
      this.plans = this.store.plans;
      if(!this.plans.length){ this.currentPlanId=null; this.mangoes=[]; return; }
      let pick = preferId; if(!this.plans.some(p=>p.id===pick)) pick=this.plans[0].id;
      this.loadPlan(pick);
    },
    loadPlan(id){
      const st=this.store.states[id]; if(!st) return;
      this.currentPlanId=id;
      for(const k in this.cfg){ if(st.plan[k]!==null&&st.plan[k]!==undefined) this.cfg[k]=st.plan[k]; }
      this.mangoes = st.mangoes;   // 同一參照，編輯即時反映到示範資料
    },
    switchPlan(){ if(this.currentPlanId) this.loadPlan(this.currentPlanId); },
    saveConfig(){
      const st=this.store.states[this.currentPlanId]; if(!st) return;
      Object.assign(st.plan, this.cfg, {id:this.currentPlanId});
      const cur=st.mangoes.length, want=this.cfg.count||0;
      if(want>cur){ for(let s=cur+1;s<=want;s++) st.mangoes.push(this.blankMango(s)); }
      else if(want<cur){ st.mangoes.splice(want); }
      const p=this.plans.find(x=>x.id===this.currentPlanId);
      if(p){ p.name=this.cfg.name; p.mango_total=st.mangoes.length; }
      this.flashSaved();
    },
    saveMango(m){
      const p=this.plans.find(x=>x.id===this.currentPlanId);
      if(p) p.eaten=this.mangoes.filter(x=>x.status==='eaten').length;
      this.flashSaved();
    },
    reset(){
      if(!confirm('確定把這個計畫的所有芒果重設為「硬」？（示範模式，僅影響目前畫面）')) return;
      this.mangoes.forEach(m=>{ m.status='hard'; m.ripe_date=''; m.fridge_date=''; m.note=''; m.has_photo=false; m._photoData=''; });
      const p=this.plans.find(x=>x.id===this.currentPlanId); if(p) p.eaten=0;
      this.flashSaved();
    },
    openNewPlan(){ this.newForm={name:'',received_date:this.today,target_date:'',count:0,variety:'愛文'}; this.showNewModal=true; },
    createPlan(){
      const id=this.store.nextPlanId++; const count=this.newForm.count||0;
      const mangoes=[]; for(let s=1;s<=count;s++) mangoes.push(this.blankMango(s));
      const plan={id,name:(this.newForm.name||'').trim()||'未命名計畫',received_date:this.newForm.received_date||'',
                  target_date:this.newForm.target_date||'',count,fridge_life_days:6,room_ripe_life_days:2,
                  frozen_life_days:60,variety:this.newForm.variety||'愛文'};
      this.store.states[id]={plan,mangoes};
      this.store.plans.push({id,name:plan.name,mango_total:count,eaten:0});
      this.showNewModal=false; this.loadPlan(id); this.flashSaved();
    },
    deletePlan(){
      const p=this.plans.find(x=>x.id===this.currentPlanId); if(!p) return;
      if(!confirm(`刪除計畫「${p.name}」？（示範模式）`)) return;
      delete this.store.states[this.currentPlanId];
      const i=this.store.plans.findIndex(x=>x.id===this.currentPlanId);
      if(i>=0) this.store.plans.splice(i,1);
      this.currentPlanId=null; this.loadPlans(); this.flashSaved();
    },

    // ---- 照片（示範模式：讀進記憶體，不上傳）----
    photoUrl(m){ return m._photoData||''; },
    viewPhoto(m){ this.lightbox=this.photoUrl(m); },
    async compressImage(file, maxDim=900, quality=0.7){
      let bitmap;
      try{ bitmap = await createImageBitmap(file, {imageOrientation:'from-image'}); }
      catch(e){ bitmap = await new Promise((res,rej)=>{ const img=new Image();
        img.onload=()=>res(img); img.onerror=rej; img.src=URL.createObjectURL(file); }); }
      let w=bitmap.width,h=bitmap.height;
      if(w>h&&w>maxDim){ h=Math.round(h*maxDim/w); w=maxDim; }
      else if(h>=w&&h>maxDim){ w=Math.round(w*maxDim/h); h=maxDim; }
      const canvas=document.createElement('canvas'); canvas.width=w; canvas.height=h;
      canvas.getContext('2d').drawImage(bitmap,0,0,w,h);
      return canvas.toDataURL('image/jpeg', quality);
    },
    async onPhotoSelect(m, ev){
      const file=ev.target.files&&ev.target.files[0]; ev.target.value=''; if(!file) return;
      m._busy=true;
      try{ m._photoData=await this.compressImage(file); m.has_photo=true; this.flashSaved(); }
      catch(e){ console.error(e); alert('讀取照片失敗，請再試一次'); }
      finally{ m._busy=false; }
    },
    removePhoto(m){ if(!confirm('移除這顆芒果的照片？（示範模式）')) return; m._photoData=''; m.has_photo=false; this.flashSaved(); },
  },
  mounted(){ this.loadPlans(1); }
}).mount('#app');"""

start = html.index("const { createApp } = Vue;")
end = html.index("}).mount('#app');") + len("}).mount('#app');")
html = html[:start] + demo_js + html[end:]

open("demo.html", "w", encoding="utf-8").write(html)
print("demo.html 產生完成，長度", len(html))
