let currentToken=null;
let currentSlug=null;
let searchFrom=null, searchTo=null;

function qs(id){return document.getElementById(id)}

function humanError(detail, status){
  if(!detail) return "Ocurrió un error inesperado — probá de nuevo.";
  const d=String(detail).toLowerCase();
  if(status===401) return "🔒 Token requerido — recargá la página y probá de nuevo.";
  if(status===413) return "📦 Archivo muy grande (máx 20MB) — probá con un export más pequeño.";
  if(status===422 && d.includes("slug")) return "🏷️ Slug inválido — usá solo a-z, 0-9, - y _.";
  if(status===422 && (d.includes("equivalent") || d.includes("stopped before writes"))) return "♻️ Equivalente detectado — elegí Reconciliar o Permitir y confirmá de nuevo.";
  if(status===422 && d.includes("persona")) return "👤 Persona requerida — escribí el nombre como aparece en el chat.";
  if(status===404) return "🔍 No encontrado — verificá el dataset seleccionado.";
  return detail;
}
function toast(el, msg, kind){
  if(!el) return;
  el.innerHTML=`<div class="toast toast-${kind}">${msg}</div>`;
}
function showRaw(el, obj){
  if(!el) return;
  el.textContent=JSON.stringify(obj,null,2);
}
function confidenceClass(c){
  if(c>=0.75) return "conf-high";
  if(c>=0.45) return "conf-mid";
  return "conf-low";
}
let activeDatasets=[];
let activeParticipants=[];

function updateParticipantDatalist(participants){
  activeParticipants=participants||[];
  const dl=qs('ask-participants-datalist');
  if(dl){
    dl.innerHTML='';
    activeParticipants.forEach(p=>{
      const opt=document.createElement('option');
      opt.value=p;
      dl.appendChild(opt);
    });
  }
  const firstContact=activeParticipants[0]||'Alex';
  document.querySelectorAll('.ask-hint').forEach(btn=>{
    const tmpl=btn.getAttribute('data-q');
    if(tmpl && tmpl.includes('{name}')){
      btn.textContent=tmpl.replace(/{name}/g, firstContact);
    }
  });
}

function renderAskAnswer(j){
  const container=qs('ask-answer');
  if(!container) return;
  const esc=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const conf=j.confidence ?? 0;
  const citations=j.citations||[];
  const isAbstained=Boolean(j.abstained || !citations.length || conf < 0.4);

  let html='';

  if(isAbstained){
    const contactName=activeParticipants[0]||'Alex';
    const reasonText=esc(j.text || 'No encontré evidencia suficiente en las conversaciones para responder con seguridad.');
    html+=`<div class="toast toast-info" style="border-left:4px solid var(--color-brand-coral);">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
        <div>
          <strong style="display:block; margin-bottom:4px;">Sin evidencia suficiente</strong>
          <p style="margin:0 0 10px; font-size:13px;">${reasonText}</p>
        </div>
        <span class="confidence-badge conf-low">Confianza baja (${(conf*100|0)}%)</span>
      </div>
      <div style="font-size:12px; margin-top:8px; border-top:1px solid rgba(0,0,0,0.06); padding-top:8px;">
        <span style="color:var(--color-muted); display:block; margin-bottom:6px;">Probá reformular o consultar:</span>
        <div style="display:flex; gap:6px; flex-wrap:wrap;">
          <button type="button" class="btn-chip ask-chip-btn" data-q="¿Qué cosas le gustan a ${esc(contactName)}?" data-about="${esc(contactName)}" style="background:#fff; border:1px solid var(--color-hairline); border-radius:999px; padding:3px 10px; font-size:11px; cursor:pointer;">¿Qué le gusta a ${esc(contactName)}?</button>
          <button type="button" class="btn-chip ask-chip-btn" data-q="¿Qué planes pendientes tenemos?" style="background:#fff; border:1px solid var(--color-hairline); border-radius:999px; padding:3px 10px; font-size:11px; cursor:pointer;">Planes pendientes</button>
          <button type="button" class="btn-chip ask-chip-btn" data-q="¿Cómo describirías nuestra relación con ${esc(contactName)}?" data-about="${esc(contactName)}" style="background:#fff; border:1px solid var(--color-hairline); border-radius:999px; padding:3px 10px; font-size:11px; cursor:pointer;">Relación con ${esc(contactName)}</button>
        </div>
      </div>
    </div>`;
  } else {
    const badge=`<span class="confidence-badge ${confidenceClass(conf)}">Confianza: ${(conf*100|0)}%</span>`;
    html+=`<div class="card" style="padding:var(--spacing-md); background:#fff; border:1px solid var(--color-hairline);">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; margin-bottom:6px;">
        <h4 style="margin:0; font-size:12px; text-transform:uppercase; letter-spacing:.5px; color:var(--color-muted);">Respuesta</h4>
        ${badge}
      </div>
      <p style="margin:0; font-size:15px; line-height:1.5;">${esc(j.text||'')}</p>
    </div>`;

    if(j.facts && j.facts.length){
      html+=`<div class="answer-section">
        <h4>Hechos comprobados (${j.facts.length})</h4>
        <ul style="margin:0; padding-left:18px; line-height:1.5;">${j.facts.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>
      </div>`;
    }

    if(j.inferences && j.inferences.length){
      html+=`<div class="answer-section" style="border-left:3px solid var(--color-brand-lavender);">
        <h4>Interpretación / Inferencias (${j.inferences.length})</h4>
        <ul style="margin:0; padding-left:18px; line-height:1.5;">${j.inferences.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>
      </div>`;
    }

    if(j.suggestions && j.suggestions.length){
      html+=`<div class="answer-section" style="border-left:3px solid var(--color-brand-teal);">
        <h4>Sugerencias recomendadas</h4>
        <ul style="margin:0; padding-left:18px; line-height:1.5;">${j.suggestions.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>
      </div>`;
    }

    if(j.missing_information && j.missing_information.length){
      html+=`<div class="answer-section" style="border-left:3px solid var(--color-brand-ochre);">
        <h4>Información faltante o por confirmar</h4>
        <ul style="margin:0; padding-left:18px; line-height:1.5;">${j.missing_information.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>
      </div>`;
    }

    if(citations.length){
      html+=`<div class="answer-section">
        <h4>Citas verificables (${citations.length})</h4>`;
      citations.forEach(c=>{
        const cit=`[${esc(c.source_file||c.message_id)}:${esc(c.message_id)}] ${esc(c.sender||'')} · ${esc(c.timestamp||'')} (relevancia: ${(c.score||0).toFixed(3)})`;
        html+=`<div style="padding:8px 0; border-bottom:1px solid var(--color-hairline-soft);">
          <span class="citation" data-sender="${esc(c.sender||'')}" data-mid="${esc(c.message_id||'')}">🔍 ${cit}</span>
          <div style="font-size:13px; color:var(--color-ink); margin-top:4px; font-style:italic; background:var(--color-canvas); padding:6px 10px; border-radius:6px;">"${esc(c.excerpt||'')}"</div>
        </div>`;
      });
      html+=`</div>`;
    }
  }

  if(j.retrieval_summary && Object.keys(j.retrieval_summary).length){
    html+=`<details style="margin-top:12px;">
      <summary style="cursor:pointer; font-size:12px; color:var(--color-muted);">Detalles de recuperación / Debug</summary>
      <pre style="font-size:11px; background:#fff; padding:10px; border-radius:8px; border:1px solid var(--color-hairline); overflow:auto; margin-top:6px;">${esc(JSON.stringify(j.retrieval_summary,null,2))}</pre>
    </details>`;
  }

  container.innerHTML=html;

  container.querySelectorAll('.citation').forEach(el=>{
    el.addEventListener('click', ()=>{
      const sender=el.getAttribute('data-sender');
      if(qs('search-participant')) qs('search-participant').value=sender;
      if(qs('search-query')) qs('search-query').value='';
      searchFrom=null; searchTo=null;
      document.querySelector('[data-tab="search"]').click();
      doSearch(true);
    });
  });

  container.querySelectorAll('.ask-chip-btn').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const q=btn.getAttribute('data-q');
      const ab=btn.getAttribute('data-about');
      if(qs('ask-question')) qs('ask-question').value=q;
      if(qs('ask-about')) qs('ask-about').value=ab||'';
      const askForm=qs('ask-form');
      if(askForm) askForm.dispatchEvent(new Event('submit'));
    });
  });
}

async function loadDatasets(){
  try{
    const r=await fetch('/api/datasets'); const j=await r.json();
    activeDatasets=j.datasets||[];
    const sel=qs('dataset-select'); if(!sel) return;
    sel.innerHTML='';
    if(!activeDatasets.length){
      sel.innerHTML='<option>(sin datasets)</option>';
      currentSlug=null;
      updateParticipantDatalist([]);
      return;
    }
    activeDatasets.forEach(d=>{
      const o=document.createElement('option');
      o.value=d.slug;
      o.textContent=d.slug+' — '+d.name;
      sel.appendChild(o);
    });
    currentSlug=activeDatasets[0].slug;
    sel.value=currentSlug;
    updateParticipantDatalist(activeDatasets[0].participants||[]);
    loadDiagnose();
    updateTelemetryToggle();
  }catch(e){ /* offline */}
}

async function loadDiagnose(){
  if(!currentSlug) return;
  try{
    const r=await fetch('/api/diagnose?slug='+encodeURIComponent(currentSlug));
    const j=await r.json();
    const msg=j.sources ? j.sources.messages : '—';
    const profiles=j.participants ? j.participants.profiles : '—';
    const vectors=j.vectors ? j.vectors.count : '—';
    const health=j.ok ? '✅ Saludable' : (j.status||'');
    const kpiM=qs('kpi-messages'), kpiP=qs('kpi-personas'), kpiG=qs('kpi-graph');
    if(kpiM) kpiM.textContent=msg;
    if(kpiP) kpiP.textContent=profiles;
    if(kpiG) kpiG.textContent=j.graph ? (j.graph.relationships||vectors) : '—';
    const diag=qs('diagnose');
    if(diag) diag.textContent = `${health} — ${msg} mensajes, ${profiles} perfiles, ${vectors} vectores`;
    const raw=qs('diagnose-raw'); if(raw) raw.textContent=JSON.stringify(j,null,2);
    const opsOut=qs('ops-output'); if(opsOut) opsOut.textContent=JSON.stringify(j,null,2);
    const healthDetail=qs('ops-health-detail'); if(healthDetail) healthDetail.textContent=health;
  }catch(e){
    const diag=qs('diagnose'); if(diag) diag.textContent='Sin conexión o dataset no disponible';
  }
}
async function updateTelemetryToggle(){
  try{ const r=await fetch('/api/telemetry'); const j=await r.json(); const btn=qs('ops-telemetry-toggle'); if(btn) btn.textContent='Telemetría: '+(j.enabled?'on':'off'); }catch(_){}
}

if(qs('dataset-select')) qs('dataset-select').addEventListener('change', e=>{
  currentSlug=e.target.value;
  const match=activeDatasets.find(d=>d.slug===currentSlug);
  updateParticipantDatalist(match ? match.participants : []);
  loadDiagnose();
});
document.querySelectorAll('nav button').forEach(b=> b.addEventListener('click', ()=>{
  document.querySelectorAll('nav button').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));
  b.classList.add('active'); const tab=document.getElementById('tab-'+b.dataset.tab); if(tab) tab.classList.add('active');
}));

function renderImportPreview(j, target, equivOptId, equivModeName){
  const el=qs(target||'import-preview');
  if(!el) return;
  if(!j || j.detail){ el.innerHTML=`<div class="toast toast-error">${humanError(j?.detail, 0)}</div>`; return; }
  const parts=j.participants||[];
  const eq=j.equivalent_sources||[];
  let html=`<div style="font-size:14px; line-height:1.5;">`;
  html+=`<div style="margin-bottom:8px;"><strong>Formato:</strong> ${j.adapter} · <strong>${j.parsed_messages}</strong> mensajes parseados (<strong>${j.new_messages}</strong> nuevos, ${j.duplicates} duplicados, ${j.rejected_notices} avisos descartados)</div>`;
  html+=`<div style="margin-bottom:8px;"><strong>Persona focal:</strong> <span class="badge badge-pink">${j.persona}</span> · <strong>Dataset:</strong> ${j.dataset_exists?'existente ('+j.slug+')':'nuevo ('+j.slug+')'}</div>`;
  
  html+=`<div style="margin-top:10px; margin-bottom:6px;"><strong>Participantes identificados:</strong></div><div style="display:flex; flex-wrap:wrap; gap:6px;">`;
  parts.forEach(p=>{
    const isPersona = p.identity === 'persona';
    html+=`<span class="badge ${isPersona ? 'badge-pink' : 'badge-teal'}" title="${p.identity}">${p.name}: ${p.messages} msgs (${p.new_messages} nuevos)</span>`;
  });
  html+=`</div>`;

  const optEl = qs(equivOptId);
  if(eq.length){
    html+=`<div class="toast toast-warning" style="margin-top:10px;">⚠️ <strong>Fuente equivalente detectada:</strong> Se encontraron fuentes existentes con alta coincidencia (>95%). Revisá las opciones abajo antes de confirmar.</div>`;
    if(optEl) optEl.style.display = 'block';
  } else {
    if(optEl) optEl.style.display = 'none';
  }

  if(j.pii_flags && j.pii_flags.length){
    html+=`<div class="toast toast-info" style="margin-top:8px;">🔒 <strong>Datos sensibles (PII):</strong> Se detectaron patrones: ${j.pii_flags.join(', ')}. Serán resguardados localmente.</div>`;
  }
  if(j.same_source_reimport){
    html+=`<div class="toast toast-info" style="margin-top:8px;">ℹ️ <strong>Ya importado:</strong> Este archivo es idéntico a una fuente existente. No se requieren cambios.</div>`;
  }
  html+=`</div>`;
  el.innerHTML=html;
}

function setupImport(formId,fileId,personaId,previewId,applyBtnId,resultId,progressId,barId,statusId,equivOptId,equivModeName){
  const form=qs(formId);
  if(!form) return;
  form.addEventListener('submit', async e=>{
    e.preventDefault();
    const file=qs(fileId)?.files[0]; const persona=qs(personaId)?.value.trim();
    const adapter=qs('import-adapter')?.value.trim();
    if(!file||!persona){ toast(qs(previewId),'Falta archivo o persona','error'); return; }
    const fd=new FormData();
    fd.append('file', file);
    if(currentSlug) fd.set('slug', currentSlug);
    else fd.set('slug', persona.toLowerCase().replace(/[^a-z0-9_-]/g,'-'));
    fd.append('persona', persona);
    if(adapter) fd.append('adapter', adapter);

    const btn=form.querySelector('button[type=submit]');
    if(btn){ btn.disabled=true; btn.innerHTML='<span class="loading"></span> Previsualizando...'; }
    try{
      const r=await fetch('/api/import/preview', {method:'POST', body:fd});
      const j=await r.json();
      if(!r.ok){
        toast(qs(previewId), humanError(j.detail, r.status),'error');
        qs(applyBtnId).style.display='none';
        return;
      }
      renderImportPreview(j, previewId, equivOptId, equivModeName);
      currentToken=j.token;
      qs(applyBtnId).style.display='block';
      if(j.slug) currentSlug=j.slug;
      qs(resultId).textContent='';
    }catch(err){
      toast(qs(previewId), 'Error de red — probá de nuevo','error');
    }finally{
      if(btn){ btn.disabled=false; btn.textContent='Preview'; }
    }
  });

  const applyBtn=qs(applyBtnId);
  if(applyBtn){
    applyBtn.addEventListener('click', async ()=>{
      if(!currentToken) return;
      applyBtn.disabled=true;
      applyBtn.innerHTML='<span class="loading"></span> Importando...';
      const prog=qs(progressId), bar=qs(barId), statusEl=qs(statusId);
      if(prog) prog.style.display='block';
      if(bar) bar.style.width='5%';
      if(statusEl){ statusEl.style.display='block'; statusEl.textContent='Iniciando procesamiento...'; }

      const modeInput = document.querySelector(`input[name="${equivModeName}"]:checked`);
      const mode = modeInput ? modeInput.value : 'none';
      const allowEquivalent = mode === 'allow';
      const reconcileEquivalent = mode === 'reconcile';

      const payload = {
        token: currentToken,
        allow_equivalent_source: allowEquivalent,
        reconcile_equivalent_source: reconcileEquivalent
      };

      let pollInterval = setInterval(async ()=>{
        try{
          const pr = await fetch(`/api/progress/${encodeURIComponent(currentToken)}`);
          if(pr.ok){
            const pj = await pr.json();
            if(pj.pct !== undefined && bar) bar.style.width = Math.max(5, pj.pct) + '%';
            if(statusEl){
              let txt = `Procesando: ${pj.stored || 0} / ${pj.total || 0} mensajes (${pj.pct || 0}%)`;
              if(pj.eta > 0) txt += ` · ETA: ${Math.round(pj.eta)}s`;
              statusEl.textContent = txt;
            }
          }
        }catch(_){}
      }, 300);

      try{
        const r=await fetch('/api/import/apply', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body:JSON.stringify(payload)
        });
        clearInterval(pollInterval);
        const j=await r.json();
        qs(resultId).textContent=JSON.stringify(j,null,2);
        if(!r.ok){
          if(bar) bar.style.width='0%';
          if(statusEl) statusEl.textContent = '';
          toast(qs(resultId), humanError(j.detail, r.status),'error');
          // If stopped due to equivalent source, keep token and applyBtn visible so user can select reconcile/allow!
          const isEquivError = r.status === 422 && String(j.detail).toLowerCase().includes("equivalent");
          if(isEquivError){
            const optEl = qs(equivOptId);
            if(optEl) optEl.style.display = 'block';
            applyBtn.disabled = false;
            applyBtn.textContent = 'Confirmar importación';
            return;
          }
        } else {
          if(bar) bar.style.width='100%';
          if(statusEl) statusEl.textContent = '¡Completado con éxito!';
          toast(qs(resultId), j.message||'Importación completa — ✅','success');
          loadDatasets();
        }
      }catch(err){
        clearInterval(pollInterval);
        toast(qs(resultId),'Error de red durante la importación','error');
      }finally{
        if(applyBtn.disabled){
          currentToken=null;
          applyBtn.style.display='none';
          applyBtn.disabled=false;
          applyBtn.textContent='Confirmar importación';
          setTimeout(()=>{
            if(prog) prog.style.display='none';
            if(bar) bar.style.width='0%';
            if(statusEl) statusEl.style.display='none';
          }, 1500);
        }
      }
    });
  }
}
setupImport('import-form','import-file','import-persona','import-preview','import-apply','import-result','import-progress','import-progress-bar','import-progress-status','import-equivalent-options','import-equivalent-mode');
setupImport('wizard-import-form','wizard-import-file','wizard-import-persona','wizard-import-preview','wizard-import-apply','wizard-import-result','wizard-import-progress','wizard-import-progress-bar','wizard-import-progress-status','wizard-import-equivalent-options','wizard-import-equivalent-mode');

const askForm=qs('ask-form');
if(askForm) askForm.addEventListener('submit', async e=>{
  e.preventDefault();
  const question=qs('ask-question').value; const about=qs('ask-about').value.trim()||null;
  if(!question.trim()){ toast(qs('ask-answer'),'Escribí una pregunta','error'); return; }
  const payload={question, slug:currentSlug, provider:'local', limit:5, evidence_budget:2500};
  if(about) payload.about=about;
  const btn=askForm.querySelector('button[type=submit]'); if(btn){ btn.disabled=true; btn.innerHTML='<span class="loading"></span> Pensando...'; }
  try{
    const r=await fetch('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const j=await r.json();
    qs('ask-raw').textContent=JSON.stringify(j,null,2);
    if(!r.ok){ qs('ask-answer').innerHTML=`<div class="toast toast-error">${humanError(j.detail, r.status)}</div>`; }
    else { renderAskAnswer(j); }
  }catch(err){ qs('ask-answer').innerHTML='<div class="toast toast-error">Error de red</div>'; }
  finally{ if(btn){ btn.disabled=false; btn.textContent='Preguntar'; } }
});

document.querySelectorAll('.ask-hint').forEach(btn => {
  btn.addEventListener('click', e => {
    e.preventDefault();
    const tmpl = btn.getAttribute('data-q');
    const firstContact = activeParticipants[0] || 'Alex';
    const q = tmpl.replace(/{name}/g, firstContact);
    if(qs('ask-question')) qs('ask-question').value = q;
    if(tmpl.includes('{name}') && qs('ask-about')){
      qs('ask-about').value = firstContact;
    }
    if(askForm) askForm.dispatchEvent(new Event('submit'));
  });
});

let searchOffset=0, searchQuery="", searchParticipant="", searchHasMore=false;
async function doSearch(reset){
  if(!currentSlug){ toast(qs('search-results'),'Seleccioná un dataset','info'); return; }
  if(reset){ searchOffset=0; const c=qs('search-results'); if(c) c.innerHTML=''; }
  searchQuery=qs('search-query')?.value||""; searchParticipant=qs('search-participant')?.value||"";
  const params=new URLSearchParams({slug: currentSlug, query: searchQuery, limit: "10", offset: String(searchOffset)});
  if(searchParticipant) params.set('participant', searchParticipant);
  if(searchFrom) params.set('from_date', searchFrom);
  if(searchTo) params.set('to_date', searchTo);
  try{
    const r=await fetch('/api/search?'+params.toString());
    const j=await r.json();
    if(!r.ok){ toast(qs('search-results'), humanError(j.detail, r.status),'error'); return; }
    qs('search-raw').textContent=JSON.stringify(j,null,2);
    if(!j.results || !j.results.length){
      if(reset) qs('search-results').innerHTML=`<div class="toast toast-info">Sin resultados para "${searchQuery||searchParticipant||'vacío'}" — probá sin acentos o con alias.</div>`;
      qs('search-more').style.display='none'; return;
    }
    j.results.forEach(ev=>{
      const div=document.createElement('div');
      div.style.cssText='padding:8px; border-bottom:1px solid #eee';
      const safe=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      div.innerHTML=`<strong>${safe(ev.sender)}</strong> <small>${safe(ev.timestamp||'')}</small> <span class="citation">[${safe(ev.message_id)}]</span><br/>${safe(ev.excerpt||ev.content||'')}`;
      qs('search-results').appendChild(div);
    });
    searchHasMore=j.has_more; searchOffset+=j.results.length;
    qs('search-more').style.display=searchHasMore?'block':'none';
  }catch(e){ toast(qs('search-results'),'Error de red','error'); }
}
if(qs('search-form')) qs('search-form').addEventListener('submit', e=>{ e.preventDefault(); doSearch(true); });
if(qs('search-more')) qs('search-more').addEventListener('click', ()=> doSearch(false));
const tabSearch=document.querySelector('[data-tab="search"]'); if(tabSearch) tabSearch.addEventListener('click', ()=> doSearch(true));
const tabTimeline=document.querySelector('[data-tab="timeline"]');
if(tabTimeline) tabTimeline.addEventListener('click', async ()=>{
  if(!currentSlug) return;
  try{
    const r=await fetch('/api/timeline?slug='+encodeURIComponent(currentSlug)+'&granularity=day');
    const j=await r.json();
    if(!r.ok){ qs('timeline-raw').textContent=humanError(j.detail, r.status); return; }
    qs('timeline-raw').textContent=JSON.stringify(j,null,2);
    const bars=qs('timeline-bars'); if(!bars) return; bars.innerHTML='';
    if(!j.buckets || !j.buckets.length){ bars.innerHTML='<div class="toast toast-info">Sin mensajes para timeline</div>'; return; }
    const max=Math.max(...j.buckets.map(b=>b.count),1);
    j.buckets.forEach(b=>{
      const col=document.createElement('div'); col.style.cssText='flex:1; display:flex; flex-direction:column; align-items:center; gap:4px;';
      const bar=document.createElement('div');
      bar.title=`${b.date}: ${b.count} — click para filtrar`;
      bar.style.cssText=`width:100%; background:#347f78; height:${(b.count/max)*60+8}px; cursor:pointer; border-radius:6px; display:flex; align-items:end; justify-content:center; color:#fff; font-size:10px;`;
      bar.textContent=b.count;
      bar.addEventListener('click', ()=>{
        searchFrom=b.date; searchTo=b.date;
        document.querySelector('[data-tab="search"]').click();
        doSearch(true);
      });
      const label=document.createElement('div'); label.textContent=b.date.slice(5); label.style.fontSize='9px'; label.style.textAlign='center';
      col.appendChild(bar); col.appendChild(label); bars.appendChild(col);
    });
  }catch(e){ qs('timeline-raw').textContent='Error cargando timeline'; }
});
const tabGraph=document.querySelector('[data-tab="graph"]');
if(tabGraph) tabGraph.addEventListener('click', async ()=>{
  if(!currentSlug) return;
  try{
    const r=await fetch('/api/graph?slug='+encodeURIComponent(currentSlug)+'&format=json');
    const j=await r.json();
    if(!r.ok){ qs('graph-raw').textContent=humanError(j.detail, r.status); return; }
    qs('graph-raw').textContent=JSON.stringify(j,null,2);
    const container=qs('graph-container');
    if(!container) return;
    container.innerHTML='';
    if(!j.nodes.length){ container.innerHTML='<div class="toast toast-info">Sin nodos — importá un chat primero.</div>'; return; }
    if(!window.cytoscape){
      // fallback list
      container.innerHTML='<div style="padding:12px;">'+ j.nodes.map(n=>`<span class="badge">${n.label}</span>`).join(' ')+ '<div style="margin-top:8px;">'+ j.edges.map(e=>`${e.from} --${e.type}--> ${e.to}`).join('<br/>') +'</div></div>';
      return;
    }
    const cy=cytoscape({
      container: container,
      elements: [
        ...j.nodes.map(n=>({data:{id:n.id, label:n.label}})),
        ...j.edges.map(e=>({data:{source:e.from, target:e.to, label:e.type}}))
      ],
      style:[
        {selector:'node', style:{'label':'data(label)','background-color':'#347f78','color':'#fff','font-size':'10px','text-valign':'center','text-halign':'center'}},
        {selector:'edge', style:{'label':'data(label)','curve-style':'bezier','target-arrow-shape':'triangle','font-size':'8px'}}
      ],
      layout:{name:'cose', animate:false}
    });
    cy.on('tap','node', evt=>{
      const id=evt.target.id();
      qs('graph-detail').innerHTML=`<strong>${id}</strong> — cargando citas...`;
      fetch('/api/search?slug='+encodeURIComponent(currentSlug)+'&query=&participant='+encodeURIComponent(id)+'&limit=5&offset=0')
        .then(r=>r.json()).then(j=>{
          qs('graph-detail').innerHTML=`<strong>${id}</strong><br/>${(j.results||[]).map(e=>e.excerpt).join('<br/>')||'Sin citas'}`;
        });
    });
  }catch(e){ if(qs('graph-container')) qs('graph-container').innerHTML='<div class="toast toast-error">Error cargando grafo</div>'; }
});
const tabWiki=document.querySelector('[data-tab="wiki"]');
if(tabWiki) tabWiki.addEventListener('click', async ()=>{
  if(!currentSlug) return;
  try{
    const r=await fetch('/api/wiki?slug='+encodeURIComponent(currentSlug));
    const j=await r.json();
    if(!r.ok){ qs('wiki-raw').textContent=humanError(j.detail, r.status); return; }
    qs('wiki-raw').textContent=JSON.stringify(j,null,2);
    const badge=qs('wiki-lint-badge');
    if(badge && j.lint) badge.textContent=`lint: ${j.lint.issues} issues, ${j.lint.warnings} warnings`;
    if(j.pages && j.pages.length){
      const page=j.pages[0].name;
      const rp=await fetch('/api/wiki/'+encodeURIComponent(page)+'?slug='+encodeURIComponent(currentSlug));
      qs('wiki-content').innerHTML=await rp.text();
    } else {
      qs('wiki-content').innerHTML='<div class="toast toast-info">Sin wiki — ejecutá build_wiki.py o rebuild_all.</div>';
    }
  }catch(e){ qs('wiki-raw').textContent='Error cargando wiki'; }
});
if(qs('wiki-load')) qs('wiki-load').addEventListener('click', ()=> tabWiki?.click());

// Plans
if(qs('plans-load')) qs('plans-load').addEventListener('click', async ()=>{
  if(!currentSlug){qs('plans-output').textContent='Sin dataset'; return;}
  const status=qs('plans-status')?.value||''; const participant=qs('plans-participant')?.value||'';
  const params=new URLSearchParams({slug: currentSlug});
  if(status) params.set('status', status);
  if(participant) params.set('participant', participant);
  try{
    const r=await fetch('/api/plans?'+params.toString()); const j=await r.json();
    qs('plans-output').textContent=JSON.stringify(j,null,2);
    if(r.ok && j.plans){
      qs('plans-detail').innerHTML=j.plans.map(p=>`<div style="padding:8px; border:1px solid #eee; border-radius:8px; margin-top:6px;"><strong>${p.title}</strong> [${p.status}]<br/>${p.participants.join(', ')} — ${p.location||'s/lugar'}<br/><small>${p.source_ids.join(', ')}</small></div>`).join('');
    }
  }catch(e){ qs('plans-output').textContent='Error cargando planes'; }
});

// Ops
if(qs('ops-diagnose')) qs('ops-diagnose').addEventListener('click', loadDiagnose);
const opsHealth=document.querySelector('#ops-health-check');
if(opsHealth) opsHealth.addEventListener('click', loadDiagnose);
const opsUpdate=qs('ops-update-check');
if(opsUpdate) opsUpdate.addEventListener('click', async()=>{
  try{ const r=await fetch('/api/update-check'); const j=await r.json(); alert(JSON.stringify(j,null,2)); }catch(e){ alert('Sin conexión'); }
});
const opsBackup=qs('ops-backup');
if(opsBackup) opsBackup.addEventListener('click', async()=>{
  if(!currentSlug) return alert('Seleccioná dataset');
  try{
    const r=await fetch('/api/backup', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({slug: currentSlug})});
    const j=await r.json();
    qs('ops-output').textContent=JSON.stringify(j,null,2);
    if(r.ok) toast(qs('ops-output'), 'Backup ok: '+ (j.path||j.backup),'success');
    else toast(qs('ops-output'), humanError(j.detail, r.status),'error');
  }catch(e){ toast(qs('ops-output'),'Error backup','error'); }
});
const restoreFile=qs('ops-restore-file');
if(restoreFile) restoreFile.addEventListener('change', async e=>{
  const file=e.target.files[0]; if(!file) return;
  const fd=new FormData(); fd.append('file', file); fd.set('slug', currentSlug||'restored');
  // use slug from current selection
  try{
    const r=await fetch('/api/restore', {method:'POST', body: fd});
    // restore endpoint expects Form with file + slug query? Our app.py restore uses file + slug form
    const j=await r.json(); qs('ops-output').textContent=JSON.stringify(j,null,2);
    if(r.ok) { toast(qs('ops-output'),'Restore ok','success'); loadDatasets(); }
    else toast(qs('ops-output'), humanError(j.detail, r.status),'error');
  }catch(err){ toast(qs('ops-output'),'Error restore','error'); }
  e.target.value='';
});
// Fix restore: our app.py expects POST /api/restore with multipart file + slug form field, but route is POST /api/restore with file and slug as Form. Use fetch with FormData containing slug and file.
if(qs('ops-logs')) qs('ops-logs').addEventListener('click', async()=>{
  const out=qs('ops-logs-output'); if(!out) return;
  try{
    const r=await fetch('/api/logs'+(currentSlug?'?slug='+encodeURIComponent(currentSlug):'')); const j=await r.json();
    out.style.display='block'; out.textContent=JSON.stringify(j,null,2);
  }catch(e){ out.style.display='block'; out.textContent='Error logs'; }
});
if(qs('ops-telemetry-toggle')) qs('ops-telemetry-toggle').addEventListener('click', async()=>{
  try{
    const cur=await (await fetch('/api/telemetry')).json();
    const next=!cur.enabled;
    const r=await fetch('/api/telemetry', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify({enabled: next})});
    const j=await r.json(); qs('ops-telemetry-toggle').textContent='Telemetría: '+(j.enabled?'on':'off');
  }catch(e){}
});
if(qs('ops-delete')) qs('ops-delete').addEventListener('click', async()=>{
  if(!currentSlug) return;
  const confirmSlug=prompt(`Para borrar "${currentSlug}" escribí el slug para confirmar:`);
  if(confirmSlug!==currentSlug){ alert('Confirmación no coincide — cancelado'); return; }
  try{
    const r=await fetch('/api/datasets/'+encodeURIComponent(currentSlug)+'?confirm='+encodeURIComponent(currentSlug), {method:'DELETE'});
    const j=await r.json(); qs('ops-output').textContent=JSON.stringify(j,null,2);
    if(r.ok){ toast(qs('ops-output'),'Dataset borrado — movido a quarantine','success'); loadDatasets(); }
    else toast(qs('ops-output'), humanError(j.detail, r.status),'error');
  }catch(e){ toast(qs('ops-output'),'Error borrando','error'); }
});

// health check button on cream card
const healthBtn=document.querySelector('.card-cream .btn-secondary');
if(healthBtn && !healthBtn.id) healthBtn.id='ops-health-check-legacy';

loadDatasets();
