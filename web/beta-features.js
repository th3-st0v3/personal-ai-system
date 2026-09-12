(() => {
  window.openCalculations = async function openCalculationsFixed(majorName=null) {
    setView("calculations");
    try {
      const majors = await api("/api/calculations/majors");
      if (!majorName) {
        $("page-view").innerHTML = `<div class="page"><div class="page-head"><div><h1 class="page-title">Engineering calculators</h1><p class="page-subtitle">Choose an engineering major. Calculators remain shared canonical tools and can appear under multiple majors without duplicated implementations.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid">${majors.map(major => `<button class="page-card" data-major-page="${attr(major.name)}"><h3>${esc(major.name)}</h3><p>${esc(major.description)}</p><span class="muted">${major.calculations.length} calculators</span></button>`).join("")}</div></div>`;
        return;
      }
      const major=await api(`/api/calculations/majors/${encodeURIComponent(majorName)}`);
      state.calcCategory=majorName;
      const catalog=await api("/api/calculations/catalog");
      const keys=new Set(major.calculations);
      const items=catalog.filter(item=>keys.has(item.key));
      $("page-view").innerHTML=`<div class="page"><div class="page-head"><div><div class="eyebrow">Engineering calculators</div><h1 class="page-title">${esc(major.name)}</h1><p class="page-subtitle">${esc(major.description)}</p></div><button class="back-button" id="back-majors">Back to majors</button></div><div class="calculator-layout"><div class="calc-list">${items.map(item=>`<button class="calc-row" data-calc-page="${attr(item.key)}"><strong>${esc(item.name)}</strong><span>${esc(item.subcategories.join(" · "))}</span><span class="calc-equation">${esc(item.equation)}</span></button>`).join("")}</div><div id="calc-detail" class="calc-detail"><div class="empty-state">Select a calculator to open its inputs, calculation trace, assumptions, and limitations.</div></div></div></div>`;
      $("back-majors").onclick=()=>openCalculations();
    } catch(error) { showError(error); }
  };

  const originalOpenCalculation=window.openCalculation;
  window.openCalculation=async function openCalculationFixed(key){
    const d=await api(`/api/calculations/${key}`);
    const page=$("calc-detail");
    if(!page)return originalOpenCalculation(key);
    page.innerHTML=`<button class="back-button" id="back-calculators">Back to ${esc(state.calcCategory||"calculators")}</button><div class="eyebrow">${esc(d.model.domain)}</div><h2>${esc(d.model.name)}</h2><code class="calc-equation">${esc(d.method.equation)}</code><p>${esc(d.model.description)}</p><form id="calc-form" class="calc-form">${d.parameters.map(p=>`<label>${esc(p.name)}${p.required?"":" (optional)"}<input name="${attr(p.name)}" type="number" step="any" ${p.required?"required":""} placeholder="${attr(p.default_unit||"value")}"><span>${esc(p.description)}</span></label>`).join("")}<button class="primary-button">Calculate</button></form><div id="calc-result"></div>`;
    $("back-calculators").onclick=()=>openCalculations(state.calcCategory===key?null:state.calcCategory);
    $("calc-form").onsubmit=async e=>{e.preventDefault();try{const inputs=Object.fromEntries([...new FormData(e.target)].filter(([,v])=>v.trim()!=="").map(([k,v])=>[k,Number(v)]));const t=await send("/api/calculations/run",{model_key:key,inputs});$("calc-result").innerHTML=`<div class="trace"><strong>${esc(t.result)} ${esc(t.result_unit)}</strong><ol>${t.steps.map(s=>`<li>${esc(s)}</li>`).join("")}</ol><h3>Assumptions</h3><ul>${t.assumptions.map(x=>`<li>${esc(x)}</li>`).join("")}</ul><h3>Limitations</h3><ul>${t.limitations.map(x=>`<li>${esc(x)}</li>`).join("")}</ul></div>`}catch(error){$("calc-result").innerHTML=`<div class="error">${esc(error.message)}</div>`}};
  };

  const originalConnections=window.openConnections;
  window.openConnections=async function openConnectionsFixed(){
    setView("connections");
    try{const [connections,plugins]=await Promise.all([api("/api/connections"),api("/api/plugins")]);$("page-view").innerHTML=`<div class="page"><div class="page-head"><div><h1 class="page-title">Connections & plugins</h1><p class="page-subtitle">Explicit provider connections and tool plugins live behind a capability boundary.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid"><div class="page-card"><h3>Information digestion</h3><p>Turn supplied text into key points, claims, qualified statements, and verification questions.</p><button id="open-digest" class="outline-button">Digest text</button></div><div class="page-card"><h3>Connections</h3><p>${connections.length?connections.map(c=>`${esc(c.name)} · ${esc(c.status)}`).join("<br>"):"No provider connections registered."}</p></div><div class="page-card"><h3>Plugins</h3><p>${plugins.length?plugins.map(p=>`${esc(p.name)} ${esc(p.version)} · ${p.enabled?"enabled":"disabled"}`).join("<br>"):"No plugins registered."}</p></div></div></div>`;$("open-digest").onclick=openDigest}catch(error){showError(error)}
  };

  async function openDigest(){modal("Digest information",`<form id="digest-form" class="form-stack"><label>Text<textarea id="digest-input" placeholder="Paste an article, notes, specifications, or source excerpt…" required></textarea></label><div class="form-actions"><button class="primary-button">Digest</button></div></form>`);$("digest-form").onsubmit=async event=>{event.preventDefault();try{const r=await send("/api/digest",{text:$("digest-input").value});$("modal-body").innerHTML=`<div class="properties"><div class="property"><span>Summary</span><strong>${esc(r.summary)}</strong></div><div class="property"><span>Key points</span><strong>${r.key_points.map(esc).join(" ")}</strong></div><div class="property"><span>Claims</span><strong>${r.claims.map(esc).join(" ")||"None extracted."}</strong></div><div class="property"><span>Uncertain or qualified</span><strong>${r.uncertain_or_qualified.map(esc).join(" ")||"None extracted."}</strong></div><div class="property"><span>Open questions</span><strong>${r.open_questions.map(esc).join(" ")||"None identified."}</strong></div></div>`}catch(error){$("modal-body").insertAdjacentHTML("beforeend",`<div class="error">${esc(error.message)}</div>`)}}}

  document.addEventListener("click",event=>{const major=event.target.closest("[data-major-page]");if(major)openCalculations(major.dataset.majorPage)});
})();
