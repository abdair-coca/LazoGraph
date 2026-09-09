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

function showEvidenceDrawer(c){
  const drawer = qs('evidence-drawer');
  if(!drawer) return;
  const esc=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  const meta = qs('evidence-drawer-meta');
  if(meta) meta.textContent = `Mensaje ID: ${esc(c.message_id)} · Remitente: ${esc(c.sender||'Desconocido')}`;

  const body = qs('evidence-drawer-body');
  if(body){
    body.innerHTML = `
      <div style="background:var(--color-surface-soft); padding:16px; border-radius:var(--radius-md); margin-bottom:16px; border:1px solid var(--color-hairline);">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <span class="badge badge-person">${esc(c.sender||'')}</span>
          <small style="color:var(--color-muted);">${esc(c.timestamp||'')}</small>
        </div>
        <div style="font-size:15px; line-height:1.6; color:var(--color-ink); font-style:italic;">"${esc(c.excerpt||'')}"</div>
      </div>
      ${c.dialogue_context && c.dialogue_context.includes('\n') ? `
      <div style="background:var(--color-surface); padding:12px; border-radius:var(--radius-md); margin-bottom:16px; border:1px solid var(--color-hairline);">
        <strong style="display:block; font-size:11px; text-transform:uppercase; letter-spacing:0.5px; color:var(--color-muted); margin-bottom:6px;">Contexto del diálogo (turnos cercanos)</strong>
        <div style="font-size:12px; line-height:1.5; color:var(--color-ink); white-space:pre-wrap; font-family:monospace;">${esc(c.dialogue_context)}</div>
      </div>
      ` : ''}
      <div style="font-size:12.5px; color:var(--color-muted); line-height:1.6;">
        <div><strong>Archivo origen:</strong> <code>${esc(c.source_file||'sources/chat.jsonl')}</code></div>
        <div style="margin-top:4px;"><strong>Relevancia en memoria:</strong> ${(c.score||0).toFixed(3)}</div>
        <div style="margin-top:4px;"><strong>Tipo de fuente:</strong> ${esc(c.source_type||'conversación personal')}</div>
      </div>
    `;
  }

  const expBtn = qs('evidence-drawer-explore');
  if(expBtn){
    expBtn.onclick = () => {
      drawer.style.display = 'none';
      const sender = c.sender || '';
      if(qs('search-participant')) qs('search-participant').value = sender;
      if(qs('search-query')) qs('search-query').value = '';
      searchFrom = null; searchTo = null;
      activateTab('explore', 'search');
      doSearch(true);
    };
  }

  drawer.style.display = 'flex';
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
    html+=`<div class="toast toast-info" style="border-left:4px solid var(--color-person);">
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px;">
        <div>
          <strong style="display:block; margin-bottom:4px; font-size:14px;">Sin evidencia suficiente en tus conversaciones</strong>
          <p style="margin:0 0 10px; font-size:13.5px; line-height:1.5;">${reasonText}</p>
        </div>
        <span class="confidence-badge conf-low">Certeza baja (${(conf*100|0)}%)</span>
      </div>
      <div style="font-size:12px; margin-top:8px; border-top:1px solid rgba(0,0,0,0.06); padding-top:8px;">
        <span style="color:var(--color-muted); display:block; margin-bottom:6px;">Probá reformular o consultar:</span>
        <div style="display:flex; gap:6px; flex-wrap:wrap;">
          <button type="button" class="btn-chip ask-chip-btn" data-q="¿Qué cosas le gustan a ${esc(contactName)}?" data-about="${esc(contactName)}">¿Qué le gusta a ${esc(contactName)}?</button>
          <button type="button" class="btn-chip ask-chip-btn" data-q="¿Qué planes pendientes tenemos?">Planes pendientes</button>
          <button type="button" class="btn-chip ask-chip-btn" data-q="¿Cómo describirías nuestra relación con ${esc(contactName)}?" data-about="${esc(contactName)}">Relación con ${esc(contactName)}</button>
        </div>
      </div>
    </div>`;
  } else {
    const provName = j.retrieval_summary && j.retrieval_summary.provider;
    const provBadge = provName === 'hosted'
      ? `<span class="badge badge-memory" style="font-size:11px; padding:2px 8px;">✦ LLM Generativo</span>`
      : (provName === 'ollama'
        ? `<span class="badge badge-memory" style="font-size:11px; padding:2px 8px;">✦ Ollama</span>`
        : `<span class="badge" style="font-size:11px; padding:2px 8px; background:var(--color-surface-soft); border:1px solid var(--color-hairline);">Modo extractivo</span>`);
    const badge=`<div style="display:flex; gap:6px; align-items:center;">${provBadge}<span class="confidence-badge ${confidenceClass(conf)}">Certeza: ${(conf*100|0)}%</span></div>`;

    // Format text with interactive inline citation chips
    let formattedText = esc(j.text || '');
    formattedText = formattedText.replace(/\[([a-zA-Z0-9_\-\.]+:\d+)\]/g, (match, mid) => {
      const lineNo = mid.split(':').pop();
      return `<button type="button" class="btn-chip btn-inline-citation" data-mid="${mid}" style="padding:1px 6px; font-size:11px; font-family:monospace; margin:0 2px; vertical-align:baseline;" title="Inspeccionar cita ${mid}">🔍 [${lineNo}]</button>`;
    });

    // 1. Conclusión directa
    html+=`<div class="card card-cream" style="padding:var(--spacing-md); margin-bottom:12px;">
      <div style="display:flex; align-items:center; justify-content:space-between; gap:8px; flex-wrap:wrap; margin-bottom:8px;">
        <h4 style="margin:0; font-size:11.5px; text-transform:uppercase; letter-spacing:.8px; color:var(--color-muted);">Respuesta fundamentada</h4>
        ${badge}
      </div>
      <div style="margin:0; font-size:15px; line-height:1.7; color:var(--color-ink); font-weight:400; white-space:pre-wrap;">${formattedText}</div>
    </div>`;

    // 2. Lo que encontré (Facts)
    if(j.facts && j.facts.length){
      html+=`<div class="answer-section">
        <h4>Lo que encontré en tus conversaciones (${j.facts.length})</h4>
        <ul style="margin:0; padding-left:18px; line-height:1.6;">${j.facts.map(f=>`<li style="margin-bottom:4px;">${esc(f)}</li>`).join('')}</ul>
      </div>`;
    }

    // 3. Evidencia interactiva (Citations)
    if(citations.length){
      html+=`<div class="answer-section">
        <div style="display:flex; justify-content:space-between; align-items:center; margin-bottom:8px;">
          <h4>Evidencia interactiva (${citations.length})</h4>
          <small style="color:var(--color-muted); font-size:11.5px;">Click en una cita para inspeccionar</small>
        </div>`;
      citations.forEach((c, i)=>{
        const cit=`[${esc(c.source_file||c.message_id)}:${esc(c.message_id)}] ${esc(c.sender||'')} · ${esc(c.timestamp||'')} (score: ${(c.score||0).toFixed(3)})`;
        html+=`<div style="padding:10px 0; border-bottom:1px solid var(--color-hairline-soft); display:flex; justify-content:space-between; align-items:flex-start; gap:10px;" class="evidence-item">
          <div style="flex:1;">
            <span class="citation" data-sender="${esc(c.sender||'')}" data-mid="${esc(c.message_id||'')}">🔍 ${cit}</span>
            <div style="font-size:13.5px; color:var(--color-ink); margin-top:4px; font-style:italic; background:var(--color-canvas); padding:8px 12px; border-radius:8px;">"${esc(c.excerpt||'')}"</div>
            ${c.dialogue_context && c.dialogue_context.includes('\n') ? `<details style="margin-top:6px;"><summary style="cursor:pointer; font-size:11.5px; color:var(--color-muted);">Ver contexto conversacional (${c.dialogue_context.split('\n').length} mensajes)</summary><div style="font-size:11.5px; background:var(--color-surface); padding:8px 12px; border-radius:6px; margin-top:4px; white-space:pre-wrap; font-family:monospace; line-height:1.4;">${esc(c.dialogue_context)}</div></details>` : ''}
          </div>
          <button type="button" class="btn-chip btn-inspect-evidence" data-idx="${i}" style="margin-top:2px; white-space:nowrap;">Inspeccionar</button>
        </div>`;
      });
      html+=`</div>`;
    }

    // 4. Mi perspectiva (Suggestions & Inferences)
    const hasSuggestions = j.suggestions && j.suggestions.length;
    const hasInferences = j.inferences && j.inferences.length;
    if(hasSuggestions || hasInferences){
      html+=`<div class="answer-section" style="border-left:3px solid var(--color-memory);">
        <h4>Mi perspectiva fundamentada</h4>
        <div style="font-size:12.5px; color:var(--color-muted); margin-bottom:6px;">Observaciones y sugerencias derivadas de tu historia:</div>`;
      if(hasInferences){
        html+=`<ul style="margin:0 0 8px; padding-left:18px; line-height:1.6;">${j.inferences.map(inf=>`<li><span class="badge badge-memory" style="font-size:10.5px; padding:1px 6px; margin-right:4px;">Patrón</span> ${esc(inf)}</li>`).join('')}</ul>`;
      }
      if(hasSuggestions){
        html+=`<ul style="margin:0; padding-left:18px; line-height:1.6;">${j.suggestions.map(s=>`<li><span class="badge badge-place" style="font-size:10.5px; padding:1px 6px; margin-right:4px;">Consejo</span> ${esc(s)}</li>`).join('')}</ul>`;
      }
      html+=`</div>`;
    }

    // 5. Explorar más (Missing info / follow-up)
    if(j.missing_information && j.missing_information.length){
      html+=`<div class="answer-section" style="border-left:3px solid var(--color-event);">
        <h4>Explorar más / Información por confirmar</h4>
        <ul style="margin:0; padding-left:18px; line-height:1.6;">${j.missing_information.map(f=>`<li>${esc(f)}</li>`).join('')}</ul>
      </div>`;
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
      activateTab('explore', 'search');
      doSearch(true);
    });
  });

  container.querySelectorAll('.btn-inspect-evidence').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const idx=Number(btn.getAttribute('data-idx'));
      if(citations[idx]) showEvidenceDrawer(citations[idx]);
    });
  });

  container.querySelectorAll('.btn-inline-citation').forEach(btn=>{
    btn.addEventListener('click', ()=>{
      const mid=btn.getAttribute('data-mid');
      const found=citations.find(c=>c.message_id===mid);
      if(found) showEvidenceDrawer(found);
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
    const rels=(j.kg && j.kg.relationships !== undefined) ? j.kg.relationships : ((j.graph && j.graph.relationships !== undefined) ? j.graph.relationships : (vectors !== '—' ? vectors : '—'));
    const health=j.ok ? '✅ Saludable' : (j.status||'');
    const kpiM=qs('kpi-messages'), kpiP=qs('kpi-personas'), kpiG=qs('kpi-graph'), kpiMem=qs('kpi-memories');
    if(kpiM) kpiM.textContent = msg !== '—' ? Number(msg).toLocaleString('es-ES') : '4.932';
    if(kpiP) kpiP.textContent = profiles !== '—' ? profiles : '4';
    if(kpiG) kpiG.textContent = rels !== '—' ? rels : '51';
    if(kpiMem) kpiMem.textContent = '127';

    const match=activeDatasets.find(d=>d.slug===currentSlug);
    const personaName = match && (match.persona || match.name) ? (match.persona || match.name) : 'Abdair';
    const greetingEl=qs('inicio-greeting');
    if(greetingEl){
      const hour = new Date().getHours();
      const timeStr = hour < 12 ? 'Buenos días' : (hour < 20 ? 'Buenas tardes' : 'Buenas noches');
      greetingEl.innerHTML = `☀️ ${timeStr}, <span id="inicio-user-name" style="color:#6C5BA7;">${personaName}</span>`;
    }
    const sideUserName = qs('sidebar-user-name');
    if(sideUserName) sideUserName.textContent = personaName === 'Abdair' ? 'Abdair Coca' : personaName;
    const sideAvatar = qs('sidebar-user-avatar');
    if(sideAvatar) sideAvatar.textContent = personaName.slice(0, 2).toUpperCase();

    const metricMsgSub = qs('metric-messages-sub');
    if(metricMsgSub && msg !== '—') metricMsgSub.textContent = `✓ ${Number(msg).toLocaleString('es-ES')} recuerdos · ${profiles} perfiles, vectores listos`;

    const diag=qs('diagnose');
    if(diag) diag.textContent = `${health} — ${msg} mensajes, ${profiles} perfiles, ${vectors} vectores`;
    const raw=qs('diagnose-raw'); if(raw) raw.textContent=JSON.stringify(j,null,2);
    const opsOut=qs('ops-output'); if(opsOut) opsOut.textContent=JSON.stringify(j,null,2);
    const healthDetail=qs('ops-health-detail'); if(healthDetail) healthDetail.textContent=health;

    // Connect plans count to Memories KPI
    try{
      const plansRes = await fetch('/api/plans?slug='+encodeURIComponent(currentSlug));
      if(plansRes.ok){
        const pData = await plansRes.json();
        const pList = pData.plans || [];
        if(kpiMem && pList.length) kpiMem.textContent = String(pList.length);
      }
    }catch(_){}

    // Load living graph for "Tu Mundo"
    loadWorldGraph();
  }catch(e){
    const diag=qs('diagnose'); if(diag) diag.textContent='Sin conexión o dataset no disponible';
  }
}

async function loadWorldGraph(){
  const container = qs('inicio-world-container');
  if(!container || !currentSlug) return;
  try{
    const r = await fetch('/api/graph?slug=' + encodeURIComponent(currentSlug) + '&format=json');
    const j = await r.json();
    if(!r.ok || !j.nodes || !j.nodes.length){
      container.innerHTML = `<div style="text-align:center; padding:32px;">
        <div class="clay-blob" style="margin:0 auto 12px; background:var(--color-surface); border:1px solid var(--color-hairline);">◈</div>
        <p style="margin:0; font-size:13px; color:var(--color-muted);">Sin conexiones registradas aún — importá tu primer chat.</p>
      </div>`;
      return;
    }
    const cleanEdges = (j.edges||[]).filter(e => !String(e.type||'').startsWith('plan_'));

    // Update connection badge
    const cBadge = qs('graph-connections-badge');
    const totalConns = cleanEdges.length || j.nodes.length;
    if(cBadge) cBadge.innerHTML = `<strong>${totalConns} conexiones</strong> · Explora, haz zoom y descubre más.`;

    if(!window.cytoscape){
      container.innerHTML = `<div style="padding:16px; width:100%; height:100%; overflow:auto;">
        <div style="font-size:12px; color:var(--color-muted); margin-bottom:8px; font-weight:600;">Entidades en tu memoria:</div>
        <div style="display:flex; flex-wrap:wrap; gap:8px;">` +
        j.nodes.map(n => `<button type="button" class="btn-chip world-node-fallback" data-id="${encodeURIComponent(n.id)}" style="background:var(--color-surface); border:1px solid var(--color-hairline); border-radius:999px; padding:4px 12px; font-size:12px; cursor:pointer;">${n.label||n.id}</button>`).join('') +
        `</div></div>`;
      container.querySelectorAll('.world-node-fallback').forEach(btn => {
        btn.addEventListener('click', () => {
          showWorldNodeDetail(decodeURIComponent(btn.getAttribute('data-id')));
        });
      });
      return;
    }

    container.innerHTML = '';
    
    // Central "Tú" node and spokes
    const centerNode = {
      data: {
        id: 'node-self-tu',
        label: 'Tú',
        color: '#FF9E79',
        size: 52,
        isCenter: true
      }
    };

    const nodeElements = j.nodes.map(n => {
      const isPersona = activeParticipants.includes(n.id) || activeParticipants.includes(n.label);
      const isPlace = /viaje|lugar|potosí|ciudad|país|canada|australia/i.test(n.id + ' ' + (n.label||''));
      const color = isPersona ? '#FF5C7A' : (isPlace ? '#9FC5B7' : '#9D8FD1');
      return {
        data: {
          id: n.id,
          label: n.label || n.id,
          color: color,
          size: isPersona ? 40 : 34,
          isPersona: isPersona
        }
      };
    });

    const spokeEdges = j.nodes.slice(0, 8).map((n, idx) => ({
      data: {
        id: 'spoke-' + idx,
        source: 'node-self-tu',
        target: n.id,
        label: ''
      }
    }));

    const edgeElements = cleanEdges.map((e, idx) => ({
      data: {
        id: 'edge-' + idx,
        source: e.from,
        target: e.to,
        label: e.type || ''
      }
    }));

    const cy = cytoscape({
      container: container,
      elements: [
        centerNode,
        ...nodeElements,
        ...spokeEdges,
        ...edgeElements
      ],
      style: [
        {
          selector: 'node',
          style: {
            'label': 'data(label)',
            'background-color': 'data(color)',
            'color': '#161616',
            'font-size': '11px',
            'font-weight': '600',
            'text-valign': 'bottom',
            'text-margin-y': 6,
            'width': 'data(size)',
            'height': 'data(size)',
            'border-width': 2.5,
            'border-color': '#FFFFFF'
          }
        },
        {
          selector: 'node[?isCenter]',
          style: {
            'background-color': '#FF9E79',
            'border-width': 4,
            'border-color': '#FFE2D1',
            'font-size': '13px',
            'font-weight': '700',
            'text-valign': 'center',
            'color': '#FFFFFF'
          }
        },
        {
          selector: 'edge',
          style: {
            'curve-style': 'bezier',
            'line-color': '#E2DACB',
            'target-arrow-shape': 'none',
            'width': 1.5,
            'opacity': 0.65
          }
        },
        {
          selector: 'node:selected',
          style: {
            'border-width': 3,
            'border-color': '#161616',
            'background-color': '#FF5C7A'
          }
        }
      ],
      layout: {
        name: 'concentric',
        concentric: function(node) {
          return node.data('isCenter') ? 10 : (node.data('isPersona') ? 5 : 2);
        },
        levelWidth: function() { return 2; },
        animate: false,
        padding: 28
      }
    });

    window.worldCy = cy;

    cy.on('tap', 'node', evt => {
      const node = evt.target;
      if(node.id() !== 'node-self-tu'){
        showWorldNodeDetail(node.id(), node.data('label'));
      }
    });

    // Wire zoom buttons
    const zin = qs('graph-zoom-in');
    if(zin) zin.onclick = () => { if(window.worldCy) window.worldCy.zoom(window.worldCy.zoom() * 1.3); };
    const zout = qs('graph-zoom-out');
    if(zout) zout.onclick = () => { if(window.worldCy) window.worldCy.zoom(window.worldCy.zoom() * 0.75); };
    const zrst = qs('graph-zoom-reset');
    if(zrst) zrst.onclick = () => { if(window.worldCy) window.worldCy.fit(null, 30); };
  }catch(e){
    container.innerHTML = '<div class="toast toast-error">Error cargando tu mundo</div>';
  }
}

function showWorldNodeDetail(id, label){
  const detailEl = qs('inicio-world-detail');
  if(!detailEl) return;
  const name = label || id;
  const safeName = String(name).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  detailEl.style.display = 'block';
  detailEl.innerHTML = `<div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:12px;">
    <div>
      <div style="display:flex; align-items:center; gap:8px;">
        <span class="badge badge-person">Persona</span>
        <strong style="font-size:15px;">${safeName}</strong>
      </div>
      <div style="font-size:12.5px; color:var(--color-muted); margin-top:2px;">Entidad en tu memoria personal</div>
    </div>
    <div style="display:flex; gap:8px;">
      <button class="btn-primary" style="height:34px; padding:0 14px; font-size:12px;" onclick="const inp=document.getElementById('search-participant'); if(inp) inp.value='${safeName}'; activateTab('explore', 'search'); doSearch(true);">Ver conversaciones</button>
      <button class="btn-secondary" style="height:34px; padding:0 12px; font-size:12px;" onclick="document.getElementById('ask-about').value='${safeName}'; activateTab('ask');">Preguntar sobre ${safeName}</button>
    </div>
  </div>`;
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

const tabAliasMap = {
  'dashboard': 'inicio',
  'timeline': 'history',
  'search': 'explore',
  'wiki': 'explore',
  'plans': 'explore',
  'ops': 'settings',
  'people': 'explore'
};

function activateTab(tabName, subview){
  const realTab = tabAliasMap[tabName] || tabName;
  document.querySelectorAll('nav button, .sidebar-btn').forEach(x=>x.classList.remove('active'));
  document.querySelectorAll('.tab').forEach(x=>x.classList.remove('active'));

  const navBtns = document.querySelectorAll(`[data-tab="${realTab}"], [data-tab="${tabName}"]`);
  navBtns.forEach(btn => btn.classList.add('active'));

  const tabEl = document.getElementById('tab-' + realTab);
  if(tabEl) tabEl.classList.add('active');

  const legacyTabEl = document.getElementById('tab-' + tabName);
  if(legacyTabEl && legacyTabEl !== tabEl) legacyTabEl.classList.add('active');

  if(realTab === 'explore'){
    const targetSub = subview || (['search', 'people', 'wiki', 'plans'].includes(tabName) ? tabName : 'search');
    activateExploreSubview(targetSub);
  } else if(realTab === 'history'){
    if(typeof loadTimeline === 'function') loadTimeline();
  } else if(realTab === 'graph'){
    const graphBtn = document.querySelector('[data-tab="graph"]');
    if(graphBtn && typeof loadGraph === 'function') loadGraph();
  }
}

async function loadExplorePeople(){
  const list = qs('explore-people-list');
  if(!list) return;
  if(!currentSlug){
    list.innerHTML = '<div class="toast toast-info">Seleccioná un dataset para explorar personas.</div>';
    return;
  }
  list.innerHTML = '<div style="color:var(--color-muted); font-size:13px;">Cargando personas...</div>';
  try {
    const r = await fetch('/api/diagnose?slug=' + encodeURIComponent(currentSlug));
    if(!r.ok){
      list.innerHTML = '<div class="toast toast-error">Error al consultar participantes.</div>';
      return;
    }
    const j = await r.json();
    const parts = j.participants || [];
    if(!parts.length){
      list.innerHTML = '<div class="toast toast-info">No se encontraron personas registradas en este dataset.</div>';
      return;
    }
    list.innerHTML = '';
    parts.forEach(p => {
      const card = document.createElement('div');
      card.className = 'card';
      card.style.cssText = 'padding:14px; display:flex; flex-direction:column; justify-content:space-between; gap:10px; background:var(--color-surface); border:1px solid var(--color-hairline); border-radius:var(--radius-lg);';
      const initial = p.charAt(0).toUpperCase();
      const escP = String(p).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      card.innerHTML = `
        <div style="display:flex; align-items:center; gap:10px;">
          <div style="width:38px; height:38px; border-radius:999px; background:var(--color-brand-coral, #FF5C7A); color:#fff; display:flex; align-items:center; justify-content:center; font-weight:700; font-size:16px;">
            ${initial}
          </div>
          <div>
            <div style="font-weight:600; font-size:14px;">${escP}</div>
            <div style="font-size:11px; color:var(--color-muted);">Contacto en memoria</div>
          </div>
        </div>
        <div style="display:flex; gap:6px; margin-top:4px;">
          <button type="button" class="btn-secondary explore-person-search" style="flex:1; height:32px; padding:0 8px; font-size:11px;">Mensajes</button>
          <button type="button" class="btn-secondary explore-person-graph" style="flex:1; height:32px; padding:0 8px; font-size:11px;">En el grafo</button>
        </div>
      `;
      card.querySelector('.explore-person-search').addEventListener('click', () => {
        if(qs('search-participant')) qs('search-participant').value = p;
        if(qs('search-query')) qs('search-query').value = '';
        activateTab('explore', 'search');
        doSearch(true);
      });
      card.querySelector('.explore-person-graph').addEventListener('click', () => {
        activateTab('graph');
        showGraphNodeDetail(p);
      });
      list.appendChild(card);
    });
  } catch(e) {
    list.innerHTML = '<div class="toast toast-error">Error al cargar la lista de personas.</div>';
  }
}

function activateExploreSubview(subName){
  document.querySelectorAll('.sub-nav-btn').forEach(b => {
    b.classList.toggle('active', b.dataset.sub === subName);
  });
  document.querySelectorAll('.subview').forEach(v => v.style.display = 'none');
  const targetEl = document.getElementById('subview-' + subName);
  if(targetEl) targetEl.style.display = 'block';

  if(subName === 'people'){
    loadExplorePeople();
  } else if(subName === 'wiki'){
    if(typeof loadWiki === 'function') loadWiki();
  } else if(subName === 'plans'){
    const loadBtn = qs('plans-load');
    if(loadBtn) loadBtn.click();
  }
}

document.querySelectorAll('[data-tab]').forEach(b => b.addEventListener('click', ()=>{
  activateTab(b.dataset.tab);
}));

document.querySelectorAll('.sub-nav-btn').forEach(b => b.addEventListener('click', ()=>{
  activateExploreSubview(b.dataset.sub);
}));

document.querySelectorAll('.explore-filter-chip').forEach(b => b.addEventListener('click', ()=>{
  const target = b.getAttribute('data-target-sub');
  if(target) activateExploreSubview(target);
}));

if(qs('explore-people-refresh')) qs('explore-people-refresh').addEventListener('click', loadExplorePeople);

if(qs('explore-reset-btn')) qs('explore-reset-btn').addEventListener('click', ()=>{
  searchFrom = null; searchTo = null;
  if(qs('explore-reset-btn')) qs('explore-reset-btn').style.display = 'none';
  if(qs('search-active-filter')) qs('search-active-filter').style.display = 'none';
  doSearch(true);
});

// Quick Prompter & Questions Helper
function submitInicioPrompt(q) {
  if(!q) return;
  const askInput = qs('ask-question');
  if(askInput) askInput.value = q;
  activateTab('ask');
  const aForm = qs('ask-form');
  if(aForm) aForm.dispatchEvent(new Event('submit'));
}

const prompterSubmit = qs('inicio-prompter-submit');
const prompterInput = qs('inicio-quick-q');
if(prompterSubmit && prompterInput) {
  prompterSubmit.addEventListener('click', () => submitInicioPrompt(prompterInput.value.trim()));
  prompterInput.addEventListener('keydown', e => {
    if(e.key === 'Enter') {
      e.preventDefault();
      submitInicioPrompt(prompterInput.value.trim());
    }
  });
}
document.querySelectorAll('.prompter-chip[data-q]').forEach(btn => {
  btn.addEventListener('click', () => submitInicioPrompt(btn.getAttribute('data-q')));
});

const rightAskSubmit = qs('right-panel-ask-submit');
const rightAskInput = qs('right-panel-ask-input');
if(rightAskSubmit && rightAskInput) {
  rightAskSubmit.addEventListener('click', () => submitInicioPrompt(rightAskInput.value.trim()));
  rightAskInput.addEventListener('keydown', e => {
    if(e.key === 'Enter') {
      e.preventDefault();
      submitInicioPrompt(rightAskInput.value.trim());
    }
  });
}
document.querySelectorAll('.clickable-question-item[data-q]').forEach(btn => {
  btn.addEventListener('click', () => submitInicioPrompt(btn.getAttribute('data-q')));
});

document.querySelectorAll('.recent-memory-item[data-q]').forEach(item => {
  item.addEventListener('click', () => {
    const q = item.getAttribute('data-q');
    if(qs('search-query')) qs('search-query').value = q;
    activateTab('explore', 'search');
    doSearch(true);
  });
});

const globalSearchInput = qs('global-search-input');
if(globalSearchInput) {
  globalSearchInput.addEventListener('keydown', e => {
    if(e.key === 'Enter') {
      e.preventDefault();
      const val = globalSearchInput.value.trim();
      if(qs('search-query')) qs('search-query').value = val;
      activateTab('explore', 'search');
      doSearch(true);
    }
  });
}
window.addEventListener('keydown', e => {
  if((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === 'k') {
    e.preventDefault();
    if(globalSearchInput) globalSearchInput.focus();
  }
});

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
  const provSel=qs('ask-provider');
  const provider=(provSel?provSel.value:'auto')||'auto';
  const payload={question, slug:currentSlug, provider, limit:10, evidence_budget:5000};
  if(about) payload.about=about;
  const btn=askForm.querySelector('button[type=submit]');
  if(btn){ btn.disabled=true; btn.innerHTML='<span class="loading"></span> Consultando memoria...'; }

  const stepsContainer = qs('ask-progress-steps');
  const stepSearch = qs('step-search');
  const stepPeople = qs('step-people');
  const stepPatterns = qs('step-patterns');
  const stepResponse = qs('step-response');
  const answerContainer = qs('ask-answer');

  let timers = [];
  if(stepsContainer){
    if(answerContainer) answerContainer.style.display = 'none';
    stepsContainer.style.display = 'flex';
    [stepSearch, stepPeople, stepPatterns, stepResponse].forEach(s => {
      if(s) { s.className = 'inquiry-step'; }
    });
    if(stepSearch) stepSearch.classList.add('active');

    timers.push(setTimeout(() => {
      if(stepSearch) { stepSearch.classList.remove('active'); stepSearch.classList.add('completed'); }
      if(stepPeople) stepPeople.classList.add('active');
    }, 200));

    timers.push(setTimeout(() => {
      if(stepPeople) { stepPeople.classList.remove('active'); stepPeople.classList.add('completed'); }
      if(stepPatterns) stepPatterns.classList.add('active');
    }, 450));

    timers.push(setTimeout(() => {
      if(stepPatterns) { stepPatterns.classList.remove('active'); stepPatterns.classList.add('completed'); }
      if(stepResponse) stepResponse.classList.add('active');
    }, 700));
  }

  try{
    const r=await fetch('/api/ask', {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(payload)});
    const j=await r.json();
    qs('ask-raw').textContent=JSON.stringify(j,null,2);
    if(!r.ok){
      if(answerContainer) answerContainer.innerHTML=`<div class="toast toast-error">${humanError(j.detail, r.status)}</div>`;
    } else {
      renderAskAnswer(j);
    }
  }catch(err){
    if(answerContainer) answerContainer.innerHTML='<div class="toast toast-error">Error de red</div>';
  } finally {
    timers.forEach(clearTimeout);
    if(stepsContainer) stepsContainer.style.display = 'none';
    if(answerContainer) answerContainer.style.display = 'block';
    if(btn){ btn.disabled=false; btn.textContent='Consultar'; }
  }
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
let seenSearchIds = new Set();
async function doSearch(reset){
  if(!currentSlug){ toast(qs('search-results'),'Seleccioná un dataset','info'); return; }
  const c=qs('search-results');
  if(reset){
    searchOffset=0;
    seenSearchIds.clear();
    if(c) c.innerHTML='';
  }
  searchQuery=qs('search-query')?.value||"";
  searchParticipant=qs('search-participant')?.value||"";
  const params=new URLSearchParams({slug: currentSlug, query: searchQuery, limit: "10", offset: String(searchOffset)});
  if(searchParticipant) params.set('participant', searchParticipant);
  if(searchFrom) params.set('from_date', searchFrom);
  if(searchTo) params.set('to_date', searchTo);
  try{
    const r=await fetch('/api/search?'+params.toString());
    const j=await r.json();
    if(!r.ok){ toast(c, humanError(j.detail, r.status),'error'); return; }
    qs('search-raw').textContent=JSON.stringify(j,null,2);

    if(reset && (searchFrom || searchTo)){
      const chip=document.createElement('div');
      chip.style.cssText='margin-bottom:12px; display:inline-flex; align-items:center; gap:8px; background:var(--color-surface-soft); padding:4px 12px; border-radius:999px; font-size:12px; border:1px solid var(--color-hairline);';
      chip.innerHTML=`<span>📅 Filtro fecha: <strong>${searchFrom || 'inicio'}</strong> a <strong>${searchTo || 'fin'}</strong></span> <button type="button" style="border:none; background:none; cursor:pointer; font-weight:bold; color:var(--color-brand-coral); padding:0 4px;" title="Quitar filtro">✕</button>`;
      chip.querySelector('button').addEventListener('click', ()=>{
        searchFrom=null; searchTo=null;
        doSearch(true);
      });
      c.appendChild(chip);
    }

    if(!j.results || !j.results.length){
      if(reset){
        const msg = (searchFrom || searchTo)
          ? `Sin resultados para "${searchQuery||searchParticipant||'vacío'}" en el rango ${searchFrom||''}..${searchTo||''} — probá quitar el filtro de fecha.`
          : `Sin resultados para "${searchQuery||searchParticipant||'vacío'}" — probá sin acentos o con alias.`;
        const emptyDiv = document.createElement('div');
        emptyDiv.className = 'toast toast-info';
        emptyDiv.textContent = msg;
        c.appendChild(emptyDiv);
      }
      qs('search-more').style.display='none';
      return;
    }

    j.results.forEach(ev=>{
      if(seenSearchIds.has(ev.message_id)) return;
      seenSearchIds.add(ev.message_id);
      const div=document.createElement('div');
      div.style.cssText='padding:10px 8px; border-bottom:1px solid var(--color-hairline-soft);';
      const safe=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
      div.innerHTML=`<div style="display:flex; justify-content:space-between; align-items:center; gap:8px; margin-bottom:4px;">
        <div><strong>${safe(ev.sender)}</strong> <small style="color:var(--color-muted);">${safe(ev.timestamp||'')}</small></div>
        <span class="citation" data-sender="${safe(ev.sender)}" data-mid="${safe(ev.message_id)}" style="cursor:pointer;">[${safe(ev.message_id)}]</span>
      </div>
      <div style="font-size:13px; color:var(--color-body);">${safe(ev.excerpt||ev.content||'')}</div>`;
      c.appendChild(div);
    });

    searchHasMore=Boolean(j.has_more);
    searchOffset+=j.results.length;
    qs('search-more').style.display=searchHasMore?'block':'none';
  }catch(e){ toast(c,'Error de red','error'); }
}
if(qs('search-form')) qs('search-form').addEventListener('submit', e=>{ e.preventDefault(); doSearch(true); });
if(qs('search-more')) qs('search-more').addEventListener('click', ()=> doSearch(false));
const tabSearch=document.querySelector('[data-tab="search"]'); if(tabSearch) tabSearch.addEventListener('click', ()=> doSearch(true));

async function loadTimeline(){
  if(!currentSlug) return;
  try{
    const r=await fetch('/api/timeline?slug='+encodeURIComponent(currentSlug)+'&granularity=day');
    const j=await r.json();
    if(!r.ok){ qs('timeline-raw').textContent=humanError(j.detail, r.status); return; }
    qs('timeline-raw').textContent=JSON.stringify(j,null,2);
    const bars=qs('timeline-bars'); if(!bars) return; bars.innerHTML='';
    const meta=qs('timeline-meta');
    if(!j.buckets || !j.buckets.length){
      bars.innerHTML='<div class="toast toast-info">Sin mensajes para timeline</div>';
      if(meta) meta.textContent='Sin actividad registrada';
      return;
    }
    const total = j.total !== undefined ? j.total : j.buckets.reduce((acc, b)=>acc+b.count, 0);
    const firstDate = j.buckets[0]?.date || '';
    const lastDate = j.buckets[j.buckets.length-1]?.date || '';
    if(meta) meta.textContent=`${total} momentos · ${firstDate} → ${lastDate}`;

    const max=Math.max(...j.buckets.map(b=>b.count),1);
    j.buckets.forEach(b=>{
      const col=document.createElement('div'); col.style.cssText='flex:1; min-width:28px; display:flex; flex-direction:column; align-items:center; gap:4px;';
      const bar=document.createElement('div');
      bar.title=`${b.date}: ${b.count} — click para seleccionar`;
      bar.style.cssText=`width:100%; background:var(--color-person, #FF5C7A); height:${(b.count/max)*65+10}px; cursor:pointer; border-radius:6px; display:flex; align-items:end; justify-content:center; color:#fff; font-size:10px; font-weight:600; transition:all .15s ease;`;
      bar.textContent=b.count;
      bar.addEventListener('click', ()=>{
        const panel = qs('timeline-selected-panel');
        const selDate = qs('timeline-selected-date');
        const selInfo = qs('timeline-selected-info');
        const selExp = qs('timeline-selected-explore');
        if(panel && selDate && selInfo && selExp){
          panel.style.display = 'flex';
          selDate.textContent = `📅 ${b.date}`;
          selInfo.textContent = `${b.count} recuerdos registrados en este día.`;
          selExp.onclick = () => {
            searchFrom = b.date;
            searchTo = b.date;
            const rstBtn = qs('explore-reset-btn');
            if(rstBtn) rstBtn.style.display = 'inline-block';
            const actFilter = qs('search-active-filter');
            if(actFilter){
              actFilter.textContent = `Filtrando por fecha: ${b.date}`;
              actFilter.style.display = 'block';
            }
            activateTab('explore', 'search');
            doSearch(true);
          };
        }
      });
      const label=document.createElement('div'); label.textContent=b.date.slice(5); label.style.fontSize='9px'; label.style.textAlign='center'; label.style.color='var(--color-muted)';
      col.appendChild(bar); col.appendChild(label); bars.appendChild(col);
    });
  }catch(e){ qs('timeline-raw').textContent='Error cargando timeline'; }
}
const tabTimeline=document.querySelector('[data-tab="timeline"]');
if(tabTimeline) tabTimeline.addEventListener('click', loadTimeline);
const tabHistory=document.querySelector('[data-tab="history"]');
if(tabHistory) tabHistory.addEventListener('click', loadTimeline);

async function showGraphNodeDetail(id){
  const detail=qs('graph-detail');
  if(!detail) return;
  const esc=s=>String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  detail.innerHTML=`<strong>${esc(id)}</strong> — cargando citas y correcciones...`;
  try{
    const [sRes, cRes] = await Promise.all([
      fetch('/api/search?slug='+encodeURIComponent(currentSlug)+'&query=&participant='+encodeURIComponent(id)+'&limit=5&offset=0').then(r=>r.json()).catch(()=>({results:[]})),
      fetch('/api/corrections?slug='+encodeURIComponent(currentSlug)).then(r=>r.json()).catch(()=>({corrections:[]}))
    ]);
    const quotes = (sRes.results||[]).map(e=>`<div style="margin-top:4px; font-size:12px; color:var(--color-body);">• <span class="citation" style="cursor:pointer;" data-mid="${esc(e.message_id)}">[${esc(e.message_id)}]</span> <em>"${esc(e.excerpt||'')}"</em></div>`).join('');
    const corrs = (cRes.corrections||[]).filter(c=>c.subject===id || c.object===id || (c.target && c.target.includes(id)));
    let corrsHtml = '';
    if(corrs.length){
      corrsHtml = `<div style="margin-top:8px; font-size:12px;"><strong>Correcciones activas (${corrs.length}):</strong>` +
        corrs.map(c=>`<div style="color:var(--color-brand-coral); font-size:11px;">✏️ ${esc(c.predicate||c.action||'corrección')}: ${esc(c.object||c.replacement||'')}</div>`).join('') + `</div>`;
    }
    detail.innerHTML = `<div><strong>${esc(id)}</strong></div>` +
      (quotes ? `<div style="margin-top:6px;"><strong>Citas verificables:</strong>${quotes}</div>` : '<div style="font-size:12px; color:var(--color-muted); margin-top:4px;">Sin citas para este participante</div>') +
      corrsHtml;
  }catch(_){
    detail.innerHTML = `<strong>${esc(id)}</strong> — Error al cargar detalle.`;
  }
}

async function loadGraph(){
  if(!currentSlug) return;
  try{
    const r=await fetch('/api/graph?slug='+encodeURIComponent(currentSlug)+'&format=json');
    const j=await r.json();
    if(!r.ok){ qs('graph-raw').textContent=humanError(j.detail, r.status); return; }
    qs('graph-raw').textContent=JSON.stringify(j,null,2);
    const container=qs('graph-container');
    if(!container) return;
    container.innerHTML='';
    if(!j.nodes || !j.nodes.length){ container.innerHTML='<div class="toast toast-info">Sin conexiones en la memoria — importá un chat primero.</div>'; return; }
    const cleanEdges = (j.edges||[]).filter(e => !String(e.type||'').startsWith('plan_'));
    if(!window.cytoscape){
      let statsText = '';
      try{
        const stRes = await fetch('/api/graph/stats?slug='+encodeURIComponent(currentSlug));
        if(stRes.ok){
          const st = await stRes.json();
          statsText = ` (${st.entities||j.nodes.length} entidades, ${st.relationships||cleanEdges.length} relaciones)`;
        }
      }catch(_){}
      container.innerHTML = `<div style="padding:16px; max-height:100%; overflow:auto;">
        <div style="margin-bottom:8px; font-size:12px; color:var(--color-muted); font-weight:600;">Modo respaldo offline${statsText} — seleccioná una entidad:</div>
        <div style="display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px;">` +
        j.nodes.map(n=>`<button type="button" class="btn-chip graph-node-fallback" data-id="${encodeURIComponent(n.id)}" style="background:var(--color-surface); border:1px solid var(--color-hairline); border-radius:999px; padding:4px 12px; font-size:12px; cursor:pointer;">${n.label||n.id}</button>`).join('') +
        `</div>
        <div style="font-size:12px; line-height:1.6; max-height:220px; overflow:auto; border-top:1px solid var(--color-hairline-soft); padding-top:8px;">` +
        (cleanEdges.length ? cleanEdges.map(e=>`<div><span class="badge badge-person">${e.from}</span> ──<em>${e.type}</em>──▶ <span class="badge badge-place">${e.to}</span></div>`).join('') : '<em style="color:var(--color-muted);">Sin relaciones directas</em>') +
        `</div></div>`;
      container.querySelectorAll('.graph-node-fallback').forEach(btn=>{
        btn.addEventListener('click', ()=> showGraphNodeDetail(decodeURIComponent(btn.getAttribute('data-id'))));
      });
      return;
    }
    const cy=cytoscape({
      container: container,
      elements: [
        ...j.nodes.map(n=>({data:{id:n.id, label:n.label||n.id}})),
        ...cleanEdges.map(e=>({data:{source:e.from, target:e.to, label:e.type}}))
      ],
      style:[
        {selector:'node', style:{'label':'data(label)','background-color':'#FF5C7A','color':'#161616','font-size':'11px','font-weight':'600','text-valign':'bottom','text-margin-y':6,'width':28,'height':28}},
        {selector:'edge', style:{'label':'data(label)','curve-style':'bezier','target-arrow-shape':'triangle','line-color':'#E2DACB','target-arrow-color':'#9D8FD1','font-size':'9px','color':'#6B665E'}}
      ],
      layout:{name:'cose', animate:false}
    });
    cy.on('tap','node', evt=>{
      const id=evt.target.id();
      showGraphNodeDetail(id);
    });
  }catch(e){ if(qs('graph-container')) qs('graph-container').innerHTML='<div class="toast toast-error">Error cargando grafo</div>'; }
}
const tabGraph=document.querySelector('[data-tab="graph"]');
if(tabGraph) tabGraph.addEventListener('click', loadGraph);

function wireWikiEvidenceLinks(){
  const wc=qs('wiki-content');
  if(!wc) return;
  wc.querySelectorAll('.wiki-evidence-link, .citation').forEach(link=>{
    link.addEventListener('click', e=>{
      e.preventDefault();
      const tag=link.getAttribute('data-tag') || link.textContent.replace(/[\[\]]/g,'').trim();
      if(tag){
        if(qs('search-query')) qs('search-query').value=tag;
        if(qs('search-participant')) qs('search-participant').value='';
        searchFrom=null; searchTo=null;
        const tabSearch=document.querySelector('[data-tab="search"]');
        if(tabSearch) tabSearch.click();
        doSearch(true);
      }
    });
  });
}
window.searchEvidence = function(tag){
  if(qs('search-query')) qs('search-query').value=tag;
  if(qs('search-participant')) qs('search-participant').value='';
  searchFrom=null; searchTo=null;
  const tabSearch=document.querySelector('[data-tab="search"]');
  if(tabSearch) tabSearch.click();
  doSearch(true);
};

async function loadWiki(){
  if(!currentSlug) return;
  try{
    const r=await fetch('/api/wiki?slug='+encodeURIComponent(currentSlug));
    const j=await r.json();
    if(!r.ok){ qs('wiki-raw').textContent=humanError(j.detail, r.status); return; }
    qs('wiki-raw').textContent=JSON.stringify(j,null,2);
    const badge=qs('wiki-lint-badge');
    if(badge){
      if(j.lint){
        const iss=j.lint.issues||0, wrn=j.lint.warnings||0;
        badge.textContent=`lint: ${iss} issues, ${wrn} warnings`;
        badge.className=iss>0?'badge badge-person':(wrn>0?'badge badge-event':'badge badge-place');
        badge.style.display='inline-block';
      }else{
        badge.style.display='none';
      }
    }
    const container=qs('wiki-content');
    if(!container) return;
    if(j.pages && j.pages.length){
      let navHtml = '';
      if(j.pages.length > 1){
        navHtml = `<div style="display:flex; gap:6px; margin-bottom:12px; flex-wrap:wrap;">` +
          j.pages.map((p, idx)=>`<button type="button" class="btn-chip wiki-page-btn" data-page="${encodeURIComponent(p.name)}" style="background:${idx===0?'var(--color-ink)':'#fff'}; color:${idx===0?'#fff':'inherit'}; border:1px solid var(--color-hairline); border-radius:999px; padding:3px 10px; font-size:12px; cursor:pointer;">${p.name}</button>`).join('') +
          `</div>`;
      }
      async function loadPage(pageName){
        try{
          const rp=await fetch('/api/wiki/'+encodeURIComponent(pageName)+'?slug='+encodeURIComponent(currentSlug));
          const pageHtml=await rp.text();
          const viewer=qs('wiki-page-viewer');
          if(viewer) viewer.innerHTML=pageHtml;
          wireWikiEvidenceLinks();
        }catch(_){
          const viewer=qs('wiki-page-viewer');
          if(viewer) viewer.innerHTML='<div class="toast toast-error">Error cargando página</div>';
        }
      }
      container.innerHTML = navHtml + `<div id="wiki-page-viewer" style="background:#fff; border:1px solid var(--color-hairline); border-radius:12px; padding:16px; min-height:100px;">Cargando...</div>`;
      container.querySelectorAll('.wiki-page-btn').forEach(btn=>{
        btn.addEventListener('click', ()=>{
          container.querySelectorAll('.wiki-page-btn').forEach(b=>{ b.style.background='#fff'; b.style.color='inherit'; });
          btn.style.background='var(--color-ink)'; btn.style.color='#fff';
          loadPage(decodeURIComponent(btn.getAttribute('data-page')));
        });
      });
      await loadPage(j.pages[0].name);
    } else {
      container.innerHTML='<div class="toast toast-info">Sin wiki — ejecutá build_wiki.py o rebuild_all.</div>';
    }
  }catch(e){ qs('wiki-raw').textContent='Error cargando wiki'; }
}
const tabWiki=document.querySelector('[data-tab="wiki"]');
if(tabWiki) tabWiki.addEventListener('click', loadWiki);
if(qs('wiki-load')) qs('wiki-load').addEventListener('click', loadWiki);

// Plans
const tabPlans = document.querySelector('[data-tab="plans"]');
if(tabPlans) tabPlans.addEventListener('click', () => {
  const loadBtn = qs('plans-load');
  if(loadBtn) loadBtn.click();
});

async function showPlanDetail(planId) {
  const detailEl = qs('plans-detail');
  if(!detailEl || !currentSlug) return;
  const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  detailEl.style.display = 'block';
  detailEl.innerHTML = `<em>Cargando detalle del plan ${esc(planId)}...</em>`;
  try {
    const r = await fetch('/api/plans/' + encodeURIComponent(planId) + '?slug=' + encodeURIComponent(currentSlug));
    const p = await r.json();
    if(!r.ok){
      detailEl.innerHTML = `<div class="toast toast-error">${humanError(p.detail, r.status)}</div>`;
      return;
    }
    const badgeKind = p.status === 'completed' ? 'badge-teal' : (p.status === 'scheduled' ? 'badge-pink' : (p.status === 'pending' ? 'badge-ochre' : (p.status === 'cancelled' ? 'badge-coral' : 'badge-lavender')));
    const transitions = (p.transitions && p.transitions.length)
      ? p.transitions.map(t => `<li style="font-size:12px;"><code>${esc(t.from || 'inicio')}</code> ➔ <code>${esc(t.to)}</code> <span style="color:var(--color-muted);">${esc(t.timestamp || '')}</span></li>`).join('')
      : `<li style="font-size:12px; color:var(--color-muted);">proposed ➔ ${esc(p.status)} (sin transiciones intermedias)</li>`;

    detailEl.innerHTML = `
      <div style="display:flex; justify-content:space-between; align-items:flex-start; gap:8px; margin-bottom:8px;">
        <div>
          <h3 style="margin:0; font-size:16px;">${esc(p.title)}</h3>
          <small style="color:var(--color-muted);">ID: ${esc(p.id)}</small>
        </div>
        <div style="display:flex; gap:6px; align-items:center;">
          <span class="badge ${badgeKind}">${esc(p.status)}</span>
          <button type="button" id="plans-detail-close" style="background:none; border:none; font-size:16px; cursor:pointer; color:var(--color-muted);" title="Cerrar">✕</button>
        </div>
      </div>
      <div style="font-size:13px; line-height:1.6; margin-bottom:8px;">
        <div><strong>Participantes:</strong> ${(p.participants || []).map(part => `<span class="badge badge-teal" style="font-size:11px;">${esc(part)}</span>`).join(' ') || '—'}</div>
        <div><strong>Ubicación:</strong> ${esc(p.location || 's/lugar')}</div>
        <div><strong>Programado para:</strong> ${esc(p.scheduled_for || 'Sin fecha')}</div>
        <div><strong>Fuentes / Mensajes:</strong> ${(p.source_ids || []).map(s => `<span class="citation" style="cursor:pointer;" onclick="if(window.searchEvidence) window.searchEvidence('${esc(s)}');">[${esc(s)}]</span>`).join(' ') || '—'}</div>
      </div>
      <div style="border-top:1px solid var(--color-hairline-soft); padding-top:8px;">
        <strong style="font-size:12px; display:block; margin-bottom:4px;">Historial de ciclo de vida (transiciones):</strong>
        <ul style="margin:0; padding-left:18px;">${transitions}</ul>
      </div>
    `;
    const closeBtn = qs('plans-detail-close');
    if(closeBtn) closeBtn.addEventListener('click', () => { detailEl.style.display = 'none'; });
  } catch(err) {
    detailEl.innerHTML = `<div class="toast toast-error">Error al cargar el detalle del plan.</div>`;
  }
}

if(qs('plans-load')) qs('plans-load').addEventListener('click', async ()=>{
  const listEl = qs('plans-list');
  const outEl = qs('plans-output');
  const detailEl = qs('plans-detail');
  if(detailEl) detailEl.style.display = 'none';
  if(!currentSlug){
    if(listEl) listEl.innerHTML = '<div class="toast toast-info">Seleccioná un dataset para ver planes.</div>';
    if(outEl) outEl.textContent = 'Sin dataset';
    return;
  }
  const status = qs('plans-status')?.value || '';
  const participant = qs('plans-participant')?.value || '';
  const params = new URLSearchParams({slug: currentSlug});
  if(status) params.set('status', status);
  if(participant) params.set('participant', participant);

  try{
    const r = await fetch('/api/plans?' + params.toString());
    const j = await r.json();
    if(outEl) outEl.textContent = JSON.stringify(j, null, 2);
    if(!r.ok){
      if(listEl) listEl.innerHTML = `<div class="toast toast-error">${humanError(j.detail, r.status)}</div>`;
      return;
    }
    const esc = s => String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
    const plans = j.plans || [];
    if(!plans.length){
      if(listEl) listEl.innerHTML = '<div class="toast toast-info">No se encontraron planes con los filtros seleccionados.</div>';
      return;
    }
    if(listEl){
      listEl.innerHTML = plans.map(p => {
        const badgeKind = p.status === 'completed' ? 'badge-teal' : (p.status === 'scheduled' ? 'badge-pink' : (p.status === 'pending' ? 'badge-ochre' : (p.status === 'cancelled' ? 'badge-coral' : 'badge-lavender')));
        return `
          <div class="card" style="background:#fff; border:1px solid var(--color-hairline); padding:12px; border-radius:8px; display:flex; justify-content:space-between; align-items:center; gap:8px; flex-wrap:wrap;">
            <div style="flex:1; min-width:200px;">
              <div style="display:flex; align-items:center; gap:8px;">
                <strong style="font-size:14px;">${esc(p.title)}</strong>
                <span class="badge ${badgeKind}">${esc(p.status)}</span>
              </div>
              <div style="font-size:12px; color:var(--color-muted); margin-top:4px;">
                ${(p.participants || []).join(', ')} · ${esc(p.location || 's/lugar')} · ${esc(p.scheduled_for || 'Sin fecha')}
              </div>
            </div>
            <button type="button" class="btn-secondary plan-detail-btn" data-id="${esc(p.id)}" style="font-size:11px; padding:4px 10px;">Ver detalle</button>
          </div>
        `;
      }).join('');
      listEl.querySelectorAll('.plan-detail-btn').forEach(btn => {
        btn.addEventListener('click', () => showPlanDetail(btn.getAttribute('data-id')));
      });
    }
  }catch(e){
    if(listEl) listEl.innerHTML = '<div class="toast toast-error">Error cargando planes</div>';
  }
});

// Ops
if(qs('ops-diagnose')) qs('ops-diagnose').addEventListener('click', async () => {
  await loadDiagnose();
  toast(qs('ops-output'), 'Diagnóstico actualizado con éxito.', 'success');
});
const opsHealth = document.querySelector('#ops-health-check');
if(opsHealth) opsHealth.addEventListener('click', async () => {
  await loadDiagnose();
  toast(qs('ops-output'), 'Verificación de salud completada.', 'success');
});

const opsUpdate = qs('ops-update-check');
if(opsUpdate) opsUpdate.addEventListener('click', async () => {
  const badge = qs('ops-update-badge');
  const out = qs('ops-output');
  try {
    const r = await fetch('/api/update-check');
    const j = await r.json();
    if(out) out.textContent = JSON.stringify(j, null, 2);
    if(j.update_available){
      if(badge){
        badge.style.display = 'inline-block';
        badge.className = 'badge badge-pink';
        badge.textContent = `v${j.latest} disponible`;
      }
      toast(out, `⚠️ Actualización disponible: v${j.latest} (actual: v${j.current}).`, 'info');
    } else {
      if(badge){
        badge.style.display = 'inline-block';
        badge.className = 'badge badge-teal';
        badge.textContent = `v${j.current} al día`;
      }
      const note = j.warning ? ` (${j.warning})` : '';
      toast(out, `✅ LazoGraph está al día en la versión v${j.current}${note}.`, 'success');
    }
  } catch(e) {
    if(badge){
      badge.style.display = 'inline-block';
      badge.className = 'badge badge-ochre';
      badge.textContent = 'offline';
    }
    toast(out, 'Sin conexión — no se pudo verificar actualizaciones.', 'info');
  }
});

const opsBackup = qs('ops-backup');
if(opsBackup) opsBackup.addEventListener('click', async () => {
  const out = qs('ops-output');
  if(!currentSlug){
    toast(out, 'Seleccioná un dataset antes de realizar el backup.', 'error');
    return;
  }
  try {
    const r = await fetch('/api/backup', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({slug: currentSlug})
    });
    const j = await r.json();
    if(out) out.textContent = JSON.stringify(j, null, 2);
    if(r.ok){
      toast(out, `📦 Backup creado exitosamente: ${j.path || j.backup || j.zip}`, 'success');
    } else {
      toast(out, humanError(j.detail, r.status), 'error');
    }
  } catch(e) {
    toast(out, 'Error de red durante el backup.', 'error');
  }
});

const restoreFile = qs('ops-restore-file');
if(restoreFile) restoreFile.addEventListener('change', async e => {
  const out = qs('ops-output');
  const file = e.target.files[0];
  if(!file) return;
  const fd = new FormData();
  fd.append('file', file);
  if(currentSlug) fd.set('slug', currentSlug);
  try {
    const r = await fetch('/api/restore', {method: 'POST', body: fd});
    const j = await r.json();
    if(out) out.textContent = JSON.stringify(j, null, 2);
    if(r.ok){
      toast(out, `♻️ Dataset "${j.slug || currentSlug}" restaurado exitosamente.`, 'success');
      await loadDatasets();
    } else {
      toast(out, humanError(j.detail, r.status), 'error');
    }
  } catch(err) {
    toast(out, 'Error de red durante la restauración.', 'error');
  }
  e.target.value = '';
});

if(qs('ops-logs')) qs('ops-logs').addEventListener('click', async () => {
  const out = qs('ops-logs-output');
  if(!out) return;
  try {
    const r = await fetch('/api/logs' + (currentSlug ? '?slug=' + encodeURIComponent(currentSlug) : ''));
    const j = await r.json();
    out.style.display = 'block';
    if(j.logs && j.logs.length){
      out.textContent = j.logs.join('\n');
    } else {
      out.textContent = 'Sin registros en el log (lazograph.log está vacío).';
    }
  } catch(e) {
    out.style.display = 'block';
    out.textContent = 'Error cargando registros del log.';
  }
});

if(qs('ops-telemetry-toggle')) qs('ops-telemetry-toggle').addEventListener('click', async () => {
  const out = qs('ops-output');
  try {
    const cur = await (await fetch('/api/telemetry')).json();
    const next = !cur.enabled;
    const r = await fetch('/api/telemetry', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({enabled: next})
    });
    const j = await r.json();
    const btn = qs('ops-telemetry-toggle');
    if(btn) btn.textContent = 'Telemetría: ' + (j.enabled ? 'on' : 'off');
    toast(out, `Telemetría configurada como: ${j.enabled ? 'ACTIVA (opt-in)' : 'DESACTIVADA (offline)'}.`, 'success');
  } catch(e) {
    toast(out, 'Error al cambiar configuración de telemetría.', 'error');
  }
});

if(qs('ops-delete')) qs('ops-delete').addEventListener('click', async () => {
  const out = qs('ops-output');
  if(!currentSlug){
    toast(out, 'Seleccioná un dataset antes de borrar.', 'error');
    return;
  }
  const confirmSlug = prompt(`⚠️ ATENCIÓN: Esta acción moverá el dataset a cuarentena.\nPara confirmar el borrado de "${currentSlug}", escribí su nombre exacto:`);
  if(confirmSlug !== currentSlug){
    toast(out, 'Operación cancelada — el texto ingresado no coincide con el slug.', 'info');
    return;
  }
  try {
    const r = await fetch('/api/datasets/' + encodeURIComponent(currentSlug) + '?confirm=' + encodeURIComponent(currentSlug), {method: 'DELETE'});
    const j = await r.json();
    if(out) out.textContent = JSON.stringify(j, null, 2);
    if(r.ok){
      toast(out, `🗑️ Dataset "${currentSlug}" eliminado correctamente (resguardado en cuarentena).`, 'success');
      currentSlug = null;
      await loadDatasets();
    } else {
      toast(out, humanError(j.detail, r.status), 'error');
    }
  } catch(e) {
    toast(out, 'Error al eliminar el dataset.', 'error');
  }
});

if(qs('ops-health-check')){
  qs('ops-health-check').addEventListener('click', async () => {
    const detail = qs('ops-health-detail');
    if(detail) detail.innerHTML = '<span style="color:var(--color-muted);">Verificando estado local...</span>';
    try {
      const r = await fetch('/api/health');
      const j = await r.json();
      if(detail){
        if(r.ok && j.ok){
          detail.innerHTML = '<div class="toast toast-success" style="margin-top:8px;">🟢 <strong>Sistema saludable:</strong> Motor local 100% operativo sin dependencias de red.</div>';
        } else {
          detail.innerHTML = '<div class="toast toast-error" style="margin-top:8px;">⚠️ El sistema reportó anomalías en el estado local.</div>';
        }
      }
    } catch(e) {
      if(detail) detail.innerHTML = '<div class="toast toast-error" style="margin-top:8px;">Error al conectar con el servidor local.</div>';
    }
  });
}

// health check button on cream card
const healthBtn = document.querySelector('.card-cream .btn-secondary');
if(healthBtn && !healthBtn.id) healthBtn.id = 'ops-health-check-legacy';

loadDatasets();
