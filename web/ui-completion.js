/* ui-completion.js — page renderers and feature views; no chat send/render implementation. */
(() => {
  'use strict';
  const $=(id)=>document.getElementById(id); const esc=(value)=>window.escapeHtml(value); const attr=(value)=>window.attr(value); const st=()=>window.state; const api=(...args)=>window.api(...args); const send=(...args)=>window.send(...args); const setView=(...args)=>window.setView(...args); const modal=(...args)=>window.modal(...args); const closeModal=(...args)=>window.closeModal(...args); const patch=(...args)=>window.patch(...args); const toast=(message)=>window.showError(new Error(message));

  function renderAccountDock(){const sidebar=$('sidebar');if(!sidebar)return;let dock=sidebar.querySelector('.account-dock');if(!dock){dock=document.createElement('button');dock.type='button';dock.className='account-dock';dock.onclick=()=>{setView('settings');renderSettingsPage();};sidebar.appendChild(dock);}const user=st().user;const name=user?.display_name||user?.email||'Account';const initials=name.split(/\s+/).filter(Boolean).slice(0,2).map((part)=>part[0]).join('').toUpperCase()||'?';dock.innerHTML=`<span class="account-avatar">${esc(initials)}</span><span class="account-name">${esc(name)}</span>`;}
  function renderProjectsPage(projects){$('page-view').innerHTML=`<div class="page"><div class="page-head"><div><div class="eyebrow">Workspace</div><h1 class="page-title">Projects</h1><p class="page-subtitle">Keep chats, files, calculations, simulations, and engineering evidence together.</p></div><button id="create-project-page" class="primary-button">New project</button></div><div class="card-grid">${projects.map((project)=>`<button type="button" class="page-card" data-open-project="${project.id}"><h3>${esc(project.name)}</h3><p>${esc(project.description||'No description yet')}</p><span class="muted">Created ${esc(project.created_at||'')}</span></button>`).join('')||'<div class="empty-state">No projects yet. Create one to start a workspace.</div>'}</div></div>`;}
  function renderProjectFilesPage(title){const s=st();$('project-files-panel').hidden=false;$('project-files-panel').innerHTML=`<div class="sidebar-heading"><span>${esc(title)}</span><button id="close-files-panel" class="quiet-icon" type="button" aria-label="Close files panel">×</button></div><div class="file-actions"><button class="quiet-button" id="project-new-folder">New folder</button><button class="quiet-button" id="project-new-note">New note</button><button class="quiet-button" id="project-upload">Upload</button></div><div class="file-tools"><label>Sort <select id="project-sort">${['none','a_z','z_a','recent_old','old_recent','last_modified_new_old','last_modified_old_new'].map((value)=>`<option value="${value}" ${s.sort===value?'selected':''}>${esc(({none:'None',a_z:'A–Z',z_a:'Z–A',recent_old:'Recent → old',old_recent:'Old → recent',last_modified_new_old:'Modified → old',last_modified_old_new:'Old → modified'})[value])}</option>`).join('')}</select></label><span id="selection-count" class="muted"></span></div><div id="bulk-actions" class="bulk-actions" hidden><button class="quiet-button" data-bulk="archive">Archive</button><button class="quiet-button" data-bulk="invalidate">Invalidate</button><button class="quiet-button" data-bulk="copy">Copy</button><button class="quiet-button" data-bulk="paste">Paste</button><button class="danger-button" data-bulk="delete">Delete</button></div><div id="file-list" class="file-grid">${s.items.length?s.items.map(itemRow).join(''):'<div class="empty-state">This location is empty.</div>'}</div>`;$('bulk-actions').querySelectorAll('[data-bulk]').forEach((button)=>button.onclick=()=>window.bulkAction(button.dataset.bulk));window.updateSelectionCount?.();}
  function itemRow(item){const s=st();const lifecycle=item.metadata?.lifecycle_status&&item.metadata.lifecycle_status!=='Active'?` · ${esc(item.metadata.lifecycle_status)}`:'';const icon=item.kind==='folder'?'▰':item.kind==='note'?'▤':(item.mime_type||'').startsWith('image/')?'▧':'□';return `<div class="file-row" draggable="true" data-kind="${attr(item.kind)}" data-id="${item.id}" data-name="${attr(item.name)}"><input class="item-check" type="checkbox" ${s.selected.has(`${item.kind}:${item.id}`)?'checked':''} aria-label="Select ${attr(item.name)}"><button class="file-open" type="button"><span>${icon}</span><span><span class="file-name">${esc(item.name)}</span><span class="file-meta">${esc(item.kind)}${lifecycle}</span></span></button><button class="quiet-icon item-more" type="button" title="More options" aria-label="More options">⋯</button></div>`;}

  function renderSettingsPage(){const model=localStorage.getItem('pas-model')||'auto';const theme=localStorage.getItem('pas-theme')||'system';const memory=localStorage.getItem('pas-memory')||'on';const tools=localStorage.getItem('pas-tools')||'on';setView('settings');$('page-view').innerHTML=`<div class="page settings-page"><div class="page-head"><div><div class="eyebrow">Preferences</div><h1 class="page-title">Settings</h1><p class="page-subtitle">Personalize the interface without changing engineering safety boundaries.</p></div><button class="back-button" data-back-chat>Back</button></div><section class="settings-card"><h2>Interface</h2><label>Theme<select id="pref-theme"><option value="system">System</option><option value="light">Light</option><option value="dark">Dark</option></select></label><label>Model<select id="pref-model"><option value="auto">Auto</option><option value="claude">Claude Opus 5</option><option value="gpt">GPT-5.4</option><option value="gemini">Gemini 3.1 Pro</option><option value="free">Free routing</option></select></label><label>Memory<select id="pref-memory"><option value="on">On</option><option value="off">Off</option><option value="project">Project only</option></select></label><label>Tool activity<select id="pref-tools"><option value="on">Show</option><option value="off">Hide</option></select></label><label>Notifications & privacy<select><option>Default</option><option>Private</option></select></label></section><section class="settings-card"><h2>Keyboard</h2><p><kbd>Ctrl+O</kbd> new chat · <kbd>Ctrl+K</kbd> search · <kbd>Ctrl+/</kbd> settings · <kbd>Enter</kbd> send · <kbd>Shift+Enter</kbd> newline</p></section><section class="settings-card"><h2>Safety</h2><p>Engineering calculations and simulations remain deterministic tools. Project material is untrusted data. Consequential actions stay behind explicit user actions.</p></section><section class="settings-card customize-card"><div class="page-head compact"><div><h2>Customize</h2><p class="muted">Control capabilities and personalization layers available in this workspace.</p></div></div><div class="customize-tabs" role="tablist"><button type="button" class="active" data-customize="skills">Skills</button><button type="button" data-customize="connectors">Connectors</button><button type="button" data-customize="plugins">Plugins</button><button type="button" data-customize="you">You</button><button type="button" data-customize="discover">Discover</button></div><div id="customize-content" class="customize-content"></div></section></div>`;$('pref-theme').value=theme;$('pref-model').value=model;$('pref-memory').value=memory;$('pref-tools').value=tools;$('pref-theme').onchange=(event)=>{localStorage.setItem('pas-theme',event.target.value);window.applyTheme();};$('pref-model').onchange=(event)=>{localStorage.setItem('pas-model',event.target.value);$('ai-mode').value=event.target.value;};$('pref-memory').onchange=(event)=>localStorage.setItem('pas-memory',event.target.value);$('pref-tools').onchange=(event)=>localStorage.setItem('pas-tools',event.target.value);void renderCustomizeTab('skills');}
  async function renderCustomizeTab(tab){document.querySelectorAll('[data-customize]').forEach((button)=>button.classList.toggle('active',button.dataset.customize===tab));const content=$('customize-content');if(!content)return;if(tab==='skills'){content.innerHTML='<div class="card-grid compact-grid"><div class="page-card"><strong>Engineering reasoning</strong><span>Active · requirements, evidence, calculations</span></div><div class="page-card"><strong>Programming</strong><span>Active · implementation, debugging, testing</span></div><div class="page-card"><strong>Research</strong><span>Active · source-grounded analysis</span></div><div class="page-card"><strong>Tutoring</strong><span>Active · explanations and practice</span></div></div>';return;}if(tab==='connectors'){const connections=await api('/api/connections');content.innerHTML=`<div class="properties">${connections.length?connections.map((item)=>`<div class="property"><span>${esc(item.name)} · ${esc(item.provider||'')}</span><strong>${esc(item.status)}</strong></div>`).join(''):'<div class="empty-state">No provider connections are registered.</div>'}</div>`;return;}if(tab==='plugins'){const plugins=await api('/api/plugins');content.innerHTML=`<div class="properties">${plugins.length?plugins.map((item)=>`<div class="property"><span>${esc(item.name)} · ${esc(item.version)}</span><strong>${item.enabled?'Enabled':'Disabled'}</strong></div>`).join(''):'<div class="empty-state">No plugins are registered yet.</div>'}</div>`;return;}if(tab==='you'){const user=st().user;content.innerHTML=`<div class="properties"><div class="property"><span>Display name</span><strong>${esc(user?.display_name||'Not signed in')}</strong></div><div class="property"><span>Email</span><strong>${esc(user?.email||'Local-only session')}</strong></div><div class="property"><span>Model preference</span><strong>${esc(localStorage.getItem('pas-model')||'auto')}</strong></div><div class="property"><span>Theme</span><strong>${esc(localStorage.getItem('pas-theme')||'system')}</strong></div></div>`;return;}const catalog=await api('/api/calculations/catalog');const simulations=await api('/api/simulations');content.innerHTML=`<div class="card-grid compact-grid"><div class="page-card"><strong>${catalog.length} calculators</strong><span>Deterministic engineering calculation library</span></div><div class="page-card"><strong>${simulations.length} simulations</strong><span>Deterministic models with explicit assumptions and limitations</span></div><div class="page-card"><strong>6 engineering groups</strong><span>Cross-major calculator navigation</span></div></div>`;}
  function renderEducationPage(){$('page-view').innerHTML=`<div class="page"><div class="page-head"><div><div class="eyebrow">Learning</div><h1 class="page-title">Education</h1><p class="page-subtitle">Study plans, explanations, exercises, programming, and project-linked learning.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid"><button type="button" class="page-card" data-prompt-card="Explain this like a tutor, then give me progressively harder practice problems."><h3>Tutor mode</h3><p>Concept explanation, derivation, examples, and practice.</p></button><button type="button" class="page-card" data-prompt-card="Create a study plan for my next exam with active recall, spaced repetition, and progressively harder problems."><h3>Study planner</h3><p>Turn a target into a practical study sequence.</p></button><button type="button" class="page-card" data-prompt-card="Give me a programming problem at my level, test my solution, and then help me improve it."><h3>Programming</h3><p>Interactive exercises and code review.</p></button><button type="button" class="page-card" data-prompt-card="Help me design a weekly schedule that balances school, engineering projects, exercise, and recovery."><h3>Scheduling</h3><p>Plan work blocks without losing the bigger picture.</p></button></div></div>`;}

  async function openSimulationsView(){setView('simulations');const simulations=await api('/api/simulations');$('page-view').innerHTML=`<div class="page"><div class="page-head"><div><div class="eyebrow">Engineering tools</div><h1 class="page-title">Simulations</h1><p class="page-subtitle">Deterministic engineering models with explicit inputs, steps, assumptions, and limitations.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid">${simulations.map((simulation)=>`<article class="page-card simulation-card" data-simulation-key="${attr(simulation.key)}"><div class="eyebrow">${esc(simulation.discipline)}</div><h3>${esc(simulation.name)}</h3><p>${esc(simulation.description)}</p><div class="simulation-parameters">${(simulation.parameters||[]).map((name)=>`<label>${esc(name)}<input data-sim-input="${attr(name)}" type="number" step="any" placeholder="value"></label>`).join('')}</div><button type="button" class="primary-button" data-run-simulation>Run simulation</button><div class="simulation-result" data-sim-result></div></article>`).join('')||'<div class="empty-state">No simulations registered.</div>'}</div></div>`;document.querySelectorAll('[data-run-simulation]').forEach((button)=>button.onclick=async()=>{const card=button.closest('[data-simulation-key]');const inputs=Object.fromEntries([...card.querySelectorAll('[data-sim-input]')].filter((input)=>input.value.trim()!=='').map((input)=>[input.dataset.simInput,Number(input.value)]));try{const result=await send('/api/simulations/run',{simulation_key:card.dataset.simulationKey,inputs});card.querySelector('[data-sim-result]').innerHTML=`<div class="trace"><strong>${esc(result.result??result.value??'')}</strong><h4>Outputs</h4><pre class="text-preview">${esc(JSON.stringify(result,null,2))}</pre></div>`;}catch(error){toast(error.message);}});}

  async function openConnectionsView(){setView('connections');const [connections,plugins]=await Promise.all([api('/api/connections'),api('/api/plugins')]);$('page-view').innerHTML=`<div class="page"><div class="page-head"><div><div class="eyebrow">Integrations</div><h1 class="page-title">Connections & plugins</h1><p class="page-subtitle">External capabilities remain explicit, inspectable, and user-controlled.</p></div><button class="back-button" data-back-chat>Back</button></div><div class="card-grid"><section class="page-card"><div class="page-card-head"><h3>Information digestion</h3><button type="button" class="outline-button" data-connection-action="digest">Digest text</button></div><p>Turn supplied text into qualified claims and verification questions.</p></section><section class="page-card"><div class="page-card-head"><h3>Connections</h3><button type="button" class="quiet-button" data-connection-action="add">Add</button></div><div class="properties">${connections.length?connections.map((item)=>`<div class="property"><span>${esc(item.name)} · ${esc(item.provider||'')}</span><strong>${esc(item.status)}</strong><small>${esc((item.capabilities||[]).join(', '))}</small></div>`).join(''):'<div class="empty-state">No connections registered.</div>'}</div></section><section class="page-card"><div class="page-card-head"><h3>Plugins</h3><button type="button" class="quiet-button" data-plugin-action="add">Register</button></div><div class="properties">${plugins.length?plugins.map((item)=>`<div class="property"><span>${esc(item.name)} · ${esc(item.version)}</span><strong>${item.enabled?'Enabled':'Disabled'} <button type="button" class="quiet-button" data-toggle-plugin="${item.id}">${item.enabled?'Disable':'Enable'}</button></strong><small>${esc((item.capabilities||[]).join(', '))}</small></div>`).join(''):'<div class="empty-state">No plugins registered.</div>'}</div></section></div></div>`;}
  function connectionAction(action){if(action==='digest')return digestForm();if(action!=='add')return;modal('Add connection','<form id="connection-form" class="form-stack"><label>Name<input name="name" required></label><label>Provider<input name="provider" required placeholder="openrouter"></label><label>Capabilities<input name="capabilities" placeholder="chat, embeddings"></label><div class="form-actions"><button type="button" class="outline-button" id="connection-cancel">Cancel</button><button class="primary-button">Save</button></div></form>');$('connection-cancel').onclick=closeModal;$('connection-form').onsubmit=async(event)=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));values.capabilities=values.capabilities?String(values.capabilities).split(',').map((value)=>value.trim()).filter(Boolean):[];try{await send('/api/connections',values);closeModal();await openConnectionsView();}catch(error){$('connection-form').insertAdjacentHTML('afterend',`<div class="error">${esc(error.message)}</div>`);}};}
  async function togglePlugin(id,enabled){await send(`/api/plugins/${id}/enabled`,{enabled});await openConnectionsView();}
  function pluginAction(action){if(action!=='add')return;modal('Register plugin','<form id="plugin-form" class="form-stack"><label>Name<input name="name" required></label><label>Version<input name="version" value="0.1.0"></label><label>Description<input name="description"></label><label>Entrypoint<input name="entrypoint" required placeholder="package.module:main"></label><label>Capabilities<input name="capabilities" placeholder="tool, search"></label><div class="form-actions"><button type="button" class="outline-button" id="plugin-cancel">Cancel</button><button class="primary-button">Register</button></div></form>');$('plugin-cancel').onclick=closeModal;$('plugin-form').onsubmit=async(event)=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));values.capabilities=values.capabilities?String(values.capabilities).split(',').map((value)=>value.trim()).filter(Boolean):[];try{await send('/api/plugins',values);closeModal();await openConnectionsView();}catch(error){$('plugin-form').insertAdjacentHTML('afterend',`<div class="error">${esc(error.message)}</div>`);}};}
  function digestForm(){modal('Digest information','<form id="digest-form" class="form-stack"><label>Text<textarea id="digest-input" placeholder="Paste an article, notes, specifications, or source excerpt…" required></textarea></label><div class="form-actions"><button class="primary-button">Digest</button></div></form>');$('digest-form').onsubmit=async(event)=>{event.preventDefault();try{const result=await send('/api/digest',{text:$('digest-input').value});$('modal-body').innerHTML=`<div class="properties"><div class="property"><span>Summary</span><strong>${esc(result.summary)}</strong></div><div class="property"><span>Key points</span><strong>${result.key_points.map(esc).join(' ')}</strong></div><div class="property"><span>Claims</span><strong>${result.claims.map(esc).join(' ')||'None extracted.'}</strong></div><div class="property"><span>Uncertain or qualified</span><strong>${result.uncertain_or_qualified.map(esc).join(' ')||'None extracted.'}</strong></div><div class="property"><span>Open questions</span><strong>${result.open_questions.map(esc).join(' ')||'None identified.'}</strong></div></div>`;}catch(error){$('modal-body').insertAdjacentHTML('beforeend',`<div class="error">${esc(error.message)}</div>`);}};}

  function renderCalculationMenu(){const menu=$('calculation-categories');const catalog=st().calculationCatalog||[];const categories=[...new Set(catalog.flatMap((item)=>item.categories||[]))];if(!menu)return;menu.innerHTML=categories.map((category)=>{const items=catalog.filter((item)=>(item.categories||[]).includes(category));const groups=[...new Set(items.flatMap((item)=>item.subcategories||[]))];return `<div class="calc-nav-section"><button class="calc-nav-item" type="button" data-calculation-category="${attr(category)}" aria-expanded="false"><span class="calc-nav-icon">Σ</span><span class="calc-nav-label">${esc(category)}</span><span class="calc-nav-count">${items.length}</span><span class="calc-nav-arrow">›</span></button><div class="calc-nav-subnav" hidden>${groups.map((group)=>`<button type="button" class="calc-nav-group" data-open-calculation-subgroup="${attr(category)}" data-calculation-subgroup="${attr(group)}"><span>${esc(group)}</span><span>${items.filter((item)=>(item.subcategories||[]).includes(group)).length}</span></button>`).join('')}<button class="calc-nav-all" type="button" data-open-calculation-group="${attr(category)}">View all in ${esc(category)} →</button></div></div>`;}).join('');}
  async function loadCalculationCatalog(){if(!st().calculationCatalog?.length){st().calculationCatalog=await api('/api/calculations/catalog');renderCalculationMenu();}return st().calculationCatalog;}
  window.toggleCalculationsMenu=async()=>{const menu=$('calculation-categories');if(!menu)return;if(menu.hidden){try{await loadCalculationCatalog();menu.hidden=false;}catch(error){toast(error.message);}}else menu.hidden=true;};
  const calculationCard=(item)=>`<button type="button" class="calculation-card" data-open-calculation="${attr(item.key)}"><span class="calculation-card-top"><span class="calculation-card-icon">Σ</span><span class="calculation-card-domain">${esc(item.domain||'Engineering')}</span></span><strong>${esc(item.name)}</strong><span class="calculation-card-equation">${esc(item.equation||'Deterministic model')}</span><span class="calculation-card-meta">${esc((item.subcategories||[])[0]||'Calculation')} · ${esc(item.result_unit||'Result')}</span></button>`;
  async function openCalculationsView(majorName=null){const catalog=await loadCalculationCatalog();const categories=[...new Set(catalog.flatMap((item)=>item.categories||[]))];setView('calculations');const chosen=majorName||st().calcMajor;if(!chosen){$('page-view').innerHTML=`<div class="page calculation-page"><div class="page-head"><div><div class="eyebrow">Engineering tools</div><h1 class="page-title">Calculations</h1><p class="page-subtitle">Choose a discipline, narrow to a group, then open the deterministic calculator.</p></div></div><div class="calculation-category-grid">${categories.map((category)=>`<button class="page-card" data-open-calculation-group="${attr(category)}"><h3>${esc(category)}</h3><p>${catalog.filter((item)=>(item.categories||[]).includes(category)).length} calculators</p></button>`).join('')}</div></div>`;return;}st().calcMajor=chosen;await openCalculationGroupView(chosen);}
  async function openCalculationGroupView(category){const catalog=await loadCalculationCatalog();const items=catalog.filter((item)=>(item.categories||[]).includes(category));const groups=[...new Set(items.flatMap((item)=>item.subcategories||[]))];st().calcMajor=category;setView('calculations');$('page-view').innerHTML=`<div class="page calculation-page"><div class="calculation-breadcrumb"><button class="breadcrumb-button" data-back-calculations>Calculations</button><span>›</span><strong>${esc(category)}</strong></div><div class="page-head"><div><div class="eyebrow">Calculation discipline</div><h1 class="page-title">${esc(category)}</h1><p class="page-subtitle">Choose a calculation group.</p></div><label class="calculation-search"><span>⌕</span><input id="calculation-group-search" type="search" placeholder="Search this discipline…"></label></div><div class="calculation-group-card-grid">${groups.map((group)=>`<button class="calculation-group-card" type="button" data-open-calculation-subgroup="${attr(category)}" data-calculation-subgroup="${attr(group)}"><span class="calculation-group-card-icon">Σ</span><span><strong>${esc(group)}</strong><small>${items.filter((item)=>(item.subcategories||[]).includes(group)).length} calculators</small></span><span>→</span></button>`).join('')}</div></div>`;$('calculation-group-search').oninput=(event)=>{const q=event.target.value.toLowerCase().trim();document.querySelectorAll('.calculation-group-card').forEach((card)=>{card.hidden=!!q&&!card.textContent.toLowerCase().includes(q);});};}
  async function openCalculationSubgroupView(category,group){const catalog=await loadCalculationCatalog();const items=catalog.filter((item)=>(item.categories||[]).includes(category)&&(item.subcategories||[]).includes(group));st().calcMajor=category;setView('calculations');$('page-view').innerHTML=`<div class="page calculation-page"><div class="calculation-breadcrumb"><button class="breadcrumb-button" data-back-major="${attr(category)}">${esc(category)}</button><span>›</span><strong>${esc(group)}</strong></div><div class="page-head"><div><div class="eyebrow">Calculation group</div><h1 class="page-title">${esc(group)}</h1><p class="page-subtitle">${items.length} deterministic calculators.</p></div><label class="calculation-search"><span>⌕</span><input id="calculation-search" type="search" placeholder="Search this group…"></label></div><div id="calculation-items" class="calculation-card-grid">${items.map(calculationCard).join('')}</div></div>`;$('calculation-search').oninput=(event)=>{const q=event.target.value.toLowerCase().trim();$('calculation-items').innerHTML=items.filter((item)=>`${item.name} ${item.key} ${item.domain} ${(item.use_cases||[]).join(' ')}`.toLowerCase().includes(q)).map(calculationCard).join('')||'<div class="empty-state">No matching calculators.</div>';};}
  async function openCalculationDetailView(key){const detail=await api(`/api/calculations/${encodeURIComponent(key)}`);st().calcKey=key;setView('calculations');$('page-view').innerHTML=`<div class="page"><div class="calculation-breadcrumb"><button class="breadcrumb-button" data-back-major="${attr(st().calcMajor||'')}">${esc(st().calcMajor||'Calculations')}</button><span>›</span><strong>${esc(detail.model.name)}</strong></div><div class="eyebrow">${esc(detail.model.domain)}</div><h1 class="page-title">${esc(detail.model.name)}</h1><code class="calc-equation">${esc(detail.method.equation)}</code><p class="page-subtitle">${esc(detail.model.description)}</p><form id="calc-form" class="calc-form"><input type="hidden" name="_calculation" value="${attr(key)}">${detail.parameters.map((parameter)=>`<label>${esc(parameter.name)}${parameter.required?'':' (optional)'}<input name="${attr(parameter.name)}" type="number" step="any" ${parameter.required?'required':''} placeholder="${attr(parameter.default_unit||'value')}"><span>${esc(parameter.description)}</span></label>`).join('')}<div class="form-actions"><button type="submit" class="primary-button">Calculate</button><button type="button" class="outline-button" id="save-calc">Calculate & save</button></div></form><div id="calc-result"></div></div>`;$('calc-form').onsubmit=async(event)=>{event.preventDefault();await runCalculation('/api/calculations/run',event,key);};$('save-calc').onclick=async()=>await runCalculation('/api/calculations/run/save',{target:$('calc-form')},key);}
  async function runCalculation(path,event,key){const inputs=Object.fromEntries([...new FormData(event.target)].filter(([name,value])=>name!=='_calculation'&&String(value).trim()!=='').map(([name,value])=>[name,Number(value)]));const buttons=event.target.querySelectorAll('button');buttons.forEach((button)=>button.disabled=true);try{const result=await send(path,{model_key:key,inputs});$('calc-result').innerHTML=`<div class="trace">${result.record_id?`<div class="trace-status">Saved as calculation record #${esc(result.record_id)}</div>`:''}<strong>${esc(result.result)} ${esc(result.result_unit||'')}</strong><ol>${(result.steps||[]).map((step)=>`<li>${esc(step)}</li>`).join('')}</ol><h3>Assumptions</h3><ul>${(result.assumptions||[]).map((item)=>`<li>${esc(item)}</li>`).join('')}</ul><h3>Limitations</h3><ul>${(result.limitations||[]).map((item)=>`<li>${esc(item)}</li>`).join('')}</ul></div>`;}catch(error){$('calc-result').innerHTML=`<div class="error">${esc(error.message)}</div>`;}finally{buttons.forEach((button)=>button.disabled=false);}}

      function engineeringTestPlanForRequirement(requirement){
        const description=String(requirement.description||requirement.title||'');
        const value=description.toLowerCase();
        const method=/(measure|temperature|pressure|voltage|current|flow)/.test(value)?'measurement':/(inspect|dimension|material|assembly)/.test(value)?'inspection':/(calculate|equation|analytical|stress|torque)/.test(value)?'analysis/calculation':/(simulate|model|dynamic|thermal|fluid)/.test(value)?'simulation':'demonstration';
        const evidenceMap={measurement:'test_result',inspection:'test_result','analysis/calculation':'calculation',simulation:'simulation_run',demonstration:'test_result'};
        return {verification_method:method,acceptance_criteria:requirement.acceptance_criteria||'Define explicit acceptance criteria before verification.',evidence_types:[evidenceMap[method]]};
      }

      function engineeringRequirementEditForm(requirement){
        const body=\`<form id="engineering-requirement-edit-form" class="form-stack">
          <label>Identifier<input name="identifier" value="\${attr(requirement.identifier||\`REQ-\${requirement.id}\`)}"></label>
          <label>Title<input name="title" value="\${attr(requirement.title||'')}"></label>
          <label>Acceptance criteria<textarea name="acceptance_criteria">\${esc(requirement.acceptance_criteria||'')}</textarea></label>
          <label>Priority<input name="priority" value="\${attr(requirement.priority||'')}"></label>
          <label>Status<select name="status"><option>Unverified</option><option>Verified</option><option>At risk</option><option>Failed</option></select></label>
          <div class="form-actions"><button type="button" class="outline-button" id="engineering-requirement-edit-cancel">Cancel</button><button class="primary-button">Save requirement</button></div>
        </form>\`;
        modal(\`Edit REQ-\${requirement.id}\`,body);
        const select=document.querySelector('#engineering-requirement-edit-form [name="status"]');
        if(select) select.value=requirement.status||'Unverified';
        $('engineering-requirement-edit-cancel').onclick=closeModal;
        $('engineering-requirement-edit-form').onsubmit=async(event)=>{
          event.preventDefault();
          try{
            await patch(\`/api/engineering/projects/\${st().projectId}/requirements/\${requirement.id}\`,Object.fromEntries(new FormData(event.target)));
            closeModal();
            await openProjectEngineeringView();
          }catch(error){event.target.insertAdjacentHTML('beforeend',\`<div class="error">\${esc(error.message)}</div>\`);}
        };
      }

  async function openProjectEngineeringView(){
    const s=st();
    if(!s.projectId){toast('Select a project first.');return;}
    try{
      const [requirements,sources,decisions]=await Promise.all([
        api(\`/api/engineering/projects/\${s.projectId}/requirements\`),
        api(\`/api/engineering/projects/\${s.projectId}/sources\`),
        api(\`/api/engineering/projects/\${s.projectId}/decisions\`)
      ]);
      setView('engineering');
      const evidenceByRequirement = new Map();
      for(const requirement of requirements){
        evidenceByRequirement.set(requirement.id, await api(\`/api/engineering/projects/\${s.projectId}/requirements/\${requirement.id}/evidence\`));
      }

      const verified=requirements.filter((item)=>String(item.status||'').toLowerCase().includes('verif')).length;
      const atRisk=requirements.filter((item)=>/risk|fail|unclear/i.test(String(item.status||''))).length;
      const evidenceCount=[...evidenceByRequirement.values()].reduce((sum,items)=>sum+items.length,0);
      const covered=requirements.filter((item)=>(evidenceByRequirement.get(item.id)||[]).length>0).length;
      const coverage=requirements.length?Math.round(covered/requirements.length*100):0;
      const health=atRisk? 'AT RISK' : requirements.length && coverage<100 ? 'NEEDS EVIDENCE' : 'NOMINAL';

      $('page-view').innerHTML=\`<div class="page engineering-control-center">
        <header class="engineering-hero">
          <div class="engineering-hero-copy">
            <div class="engineering-kicker">ENGINEERING / \${esc(s.project?.name||'PROJECT')}</div>
            <h1 class="page-title">Engineering control center</h1>
            <p class="page-subtitle">Trace requirements to sources, decisions, verification, and evidence without leaving the project.</p>
          </div>
          <div class="engineering-hero-actions">
            <button class="outline-button" data-back-chat>Back to chat</button>
            <button class="outline-button" data-engineering-action="report">Weekly report</button>
            <button class="primary-button" data-engineering-action="requirement">Add requirement</button>
          </div>
        </header>

        <section class="engineering-health-strip">
          <div class="engineering-health-state \${health==='NOMINAL'?'nominal':health==='AT RISK'?'risk':'attention'}">
            <span></span><div><strong>\${health}</strong><small>traceability state</small></div>
          </div>
          <div class="engineering-metric"><strong>\${requirements.length}</strong><span>Requirements</span></div>
          <div class="engineering-metric"><strong>\${coverage}%</strong><span>Evidence coverage</span></div>
          <div class="engineering-metric"><strong>\${evidenceCount}</strong><span>Evidence records</span></div>
          <div class="engineering-metric"><strong>\${sources.length}</strong><span>Sources</span></div>
          <div class="engineering-metric"><strong>\${decisions.length}</strong><span>Decisions</span></div>
        </section>

        <div class="engineering-work-grid">
          <main class="engineering-main-column">
            <section class="engineering-panel engineering-requirements-panel">
              <div class="engineering-panel-head">
                <div><span class="engineering-kicker">TRACEABILITY</span><h2>Requirements</h2></div>
                <div class="engineering-panel-actions">
                  <label class="engineering-inline-search"><span>⌕</span><input id="engineering-requirement-search" type="search" placeholder="Filter requirements…"></label>
                  <select id="engineering-requirement-filter" class="engineering-select">
                    <option value="all">All</option><option value="verified">Verified</option><option value="open">Open</option><option value="risk">At risk</option>
                  </select>
                </div>
              </div>
              <div id="engineering-requirement-list" class="engineering-requirement-list">
                \${requirements.length ? requirements.map((item,index)=>{
                  const evidence=evidenceByRequirement.get(item.id)||[];
                  const status=String(item.status||'Open');
                  const statusClass=/verif/i.test(status)?'verified':/risk|fail|unclear/i.test(status)?'risk':'open';
                  return \`<article class="engineering-requirement" data-requirement-card data-requirement-id="\${item.id}" data-status="\${statusClass}" data-search="\${attr([item.title,item.description,status].join(' '))}">
                    <div class="engineering-requirement-index">\${String(index+1).padStart(2,'0')}</div>
                    <div class="engineering-requirement-body">
                      <div class="engineering-requirement-line"><span class="engineering-id">REQ-\${item.id}</span><span class="engineering-status \${statusClass}">\${esc(status)}</span></div>
                      <h3>\${esc(item.title||item.description||'Untitled requirement')}</h3>
                      <p>\${esc(item.description||'No description recorded.')}</p>
                      <div class="engineering-requirement-meta"><span>\${evidence.length} evidence record\${evidence.length===1?'':'s'}</span><span>\${evidence.length?'Traceable':'Needs evidence'}</span></div>
                    </div>
                    <div class="engineering-requirement-actions">
                      <button type="button" class="quiet-button" data-engineering-action="evidence" data-id="\${item.id}">+ Evidence</button>
                      <button type="button" class="outline-button" data-engineering-requirement-detail="\${item.id}">Open</button>
                    </div>
                  </article>\`;
                }).join('') : '<div class="engineering-empty"><strong>No requirements yet.</strong><span>Start the project specification here.</span><button class="primary-button" data-engineering-action="requirement">Add requirement</button></div>'}
              </div>
            </section>

            <section class="engineering-panel">
              <div class="engineering-panel-head">
                <div><span class="engineering-kicker">KNOWLEDGE BASE</span><h2>Sources</h2></div>
                <div class="engineering-panel-actions">
                  <button class="quiet-button" data-engineering-action="search-sources">Search sources</button>
                  <button class="outline-button" data-engineering-action="source">Add source</button>
                  <button class="outline-button" data-engineering-action="ingest-source">Ingest</button>
                </div>
              </div>
              <div class="engineering-source-grid">
                \${sources.length ? sources.slice(0,8).map((item)=>\`<button type="button" class="engineering-source-card" data-engineering-source-detail="\${attr(item.id)}">
                  <span class="engineering-source-icon">▧</span><div><strong>\${esc(item.title)}</strong><span>\${esc(item.source_type||'document')} · \${esc(item.version||'unversioned')}</span></div><b>›</b>
                </button>\`).join('') : '<div class="engineering-empty"><strong>No sources ingested.</strong><span>Add a source or import a public GitHub file.</span><button class="outline-button" data-engineering-action="github-source">Import GitHub</button></div>'}
              </div>
              \${sources.length>8?'<div class="engineering-more">Showing 8 of '+sources.length+' sources</div>':''}
            </section>
          </main>

          <aside class="engineering-side-column">
            <section class="engineering-panel engineering-coverage-panel">
              <div class="engineering-panel-head"><div><span class="engineering-kicker">EVIDENCE</span><h2>Coverage</h2></div><span class="engineering-score">\${coverage}%</span></div>
              <div class="engineering-coverage-ring" style="--coverage:\${coverage}%"><div><strong>\${coverage}%</strong><span>covered</span></div></div>
              <div class="engineering-coverage-list">
                <div><span class="dot verified"></span><strong>\${verified}</strong><small>verified</small></div>
                <div><span class="dot open"></span><strong>\${requirements.length-covered}</strong><small>open / untraced</small></div>
                <div><span class="dot risk"></span><strong>\${atRisk}</strong><small>risk flags</small></div>
              </div>
              <button class="outline-button full-width" data-engineering-action="test-plan">Generate verification plan</button>
            </section>

            <section class="engineering-panel engineering-decisions-panel">
              <div class="engineering-panel-head"><div><span class="engineering-kicker">DECISIONS</span><h2>Recent decisions</h2></div><button class="quiet-button" data-engineering-action="decision">+ Add</button></div>
              <div class="engineering-decision-list">
                \${decisions.length?decisions.slice(0,5).map((item)=>\`<article class="engineering-decision-card"><span class="engineering-decision-mark">◆</span><div><strong>\${esc(item.title)}</strong><p>\${esc(item.decision||item.rationale||'No decision text recorded.')}</p></div></article>\`).join(''):'<div class="engineering-empty compact"><strong>No decisions yet.</strong><span>Record design and implementation decisions here.</span></div>'}
              </div>
            </section>

            <section class="engineering-panel engineering-actions-panel">
              <div><span class="engineering-kicker">QUICK ACTIONS</span><h2>Project tools</h2></div>
              <button type="button" class="engineering-action-row" data-engineering-action="test-plan"><span>✓</span><div><strong>Build verification plan</strong><small>Map requirements to checks</small></div><b>→</b></button>
              <button type="button" class="engineering-action-row" data-engineering-action="report"><span>▤</span><div><strong>Generate weekly report</strong><small>Status, evidence, decisions</small></div><b>→</b></button>
              <button type="button" class="engineering-action-row" data-engineering-action="search-sources"><span>⌕</span><div><strong>Search source corpus</strong><small>Find qualified project evidence</small></div><b>→</b></button>
            </section>
          </aside>
        </div>

        <footer class="engineering-footer">
          <span>Project engineering boundary · evidence is inspectable and inert</span>
          <span>Requirements \${requirements.length} · Sources \${sources.length} · Decisions \${decisions.length}</span>
        </footer>
      </div>\`;

      const reqSearch=$('engineering-requirement-search');
      const reqFilter=$('engineering-requirement-filter');
      const applyRequirementFilters=()=>{
        const query=String(reqSearch?.value||'').trim().toLowerCase();
        const filter=reqFilter?.value||'all';
        document.querySelectorAll('[data-requirement-card]').forEach((card)=>{
          const status=card.dataset.status;
          const matchesStatus=filter==='all'||(filter==='verified'&&status==='verified')||(filter==='open'&&status==='open')||(filter==='risk'&&status==='risk');
          card.hidden=!(matchesStatus&&(!query||card.dataset.search.toLowerCase().includes(query)));
        });
      };
      reqSearch?.addEventListener('input',applyRequirementFilters);
      reqFilter?.addEventListener('change',applyRequirementFilters);

      document.querySelectorAll('[data-engineering-requirement-detail]').forEach((button)=>{
        button.onclick=()=>{
          const requirement=requirements.find((item)=>String(item.id)===String(button.dataset.engineeringRequirementDetail));
          if(!requirement)return;
          const evidence=evidenceByRequirement.get(requirement.id)||[];
          const linkedDecisions=decisions.filter((item)=>String(item.requirement_id||'')===String(requirement.id));
          const status=String(requirement.status||'Unverified');
          const statusClass=/verif/i.test(status)?'verified':/risk|fail/i.test(status)?'risk':'open';
          const activeEvidence=evidence.filter((item)=>String(item.lifecycle_status||'Active')==='Active');
          const invalidEvidence=evidence.filter((item)=>String(item.lifecycle_status||'Active')!=='Active');
          const linkedSourceIds=new Set(activeEvidence.map((item)=>item.source_id).filter((id)=>id!=null).map(String));
          const linkedSources=sources.filter((item)=>linkedSourceIds.has(String(item.id)));
          const plan=engineeringTestPlanForRequirement(requirement);

          $('page-view').innerHTML=\`<div class="page engineering-requirement-detail">
            <header class="engineering-detail-header">
              <div class="engineering-detail-header-copy">
                <button type="button" class="engineering-back-link" data-engineering-detail-back>← Requirements</button>
                <div class="engineering-kicker">TRACEABILITY / REQ-\${esc(requirement.id)}</div>
                <div class="engineering-detail-title-row">
                  <div><h1 class="page-title">\${esc(requirement.title||'Untitled requirement')}</h1><p class="page-subtitle">\${esc(requirement.description||'No requirement description recorded.')}</p></div>
                  <span class="engineering-status engineering-status-large \${statusClass}">\${esc(status)}</span>
                </div>
              </div>
              <div class="engineering-detail-actions">
                <button type="button" class="outline-button" data-engineering-detail-back>Back</button>
                <button type="button" class="outline-button" data-engineering-action="evidence" data-id="\${attr(requirement.id)}">+ Evidence</button>
                <button type="button" class="primary-button" data-engineering-detail-edit>Edit requirement</button>
              </div>
            </header>

            <section class="engineering-detail-health">
              <div class="engineering-detail-health-main">
                <span class="engineering-health-icon \${statusClass}">\${statusClass==='verified'?'✓':statusClass==='risk'?'!':'○'}</span>
                <div><span class="engineering-kicker">VERIFICATION STATE</span><strong>\${esc(status)}</strong><p>\${activeEvidence.length ? activeEvidence.length+' active evidence record'+(activeEvidence.length===1?'':'s')+' support this requirement.' : 'No active evidence is currently linked to this requirement.'}</p></div>
              </div>
              <div class="engineering-detail-stat"><strong>\${activeEvidence.length}</strong><span>Active evidence</span></div>
              <div class="engineering-detail-stat"><strong>\${invalidEvidence.length}</strong><span>Invalidated</span></div>
              <div class="engineering-detail-stat"><strong>\${linkedDecisions.length}</strong><span>Linked decisions</span></div>
              <div class="engineering-detail-stat"><strong>\${linkedSources.length}</strong><span>Traceable sources</span></div>
            </section>

            <div class="engineering-detail-grid">
              <main class="engineering-detail-main">
                <section class="engineering-panel">
                  <div class="engineering-panel-head">
                    <div><span class="engineering-kicker">VERIFICATION</span><h2>Acceptance & verification</h2></div>
                    <span class="engineering-detail-method">\${esc(plan.verification_method)}</span>
                  </div>
                  <div class="engineering-detail-section-body">
                    <div class="engineering-verification-block">
                      <span class="engineering-detail-label">Acceptance criteria</span>
                      <div class="engineering-acceptance-text">\${esc(plan.acceptance_criteria||'Define explicit acceptance criteria before verification.')}</div>
                    </div>
                    <div class="engineering-verification-checks">
                      <div class="engineering-check-row \${activeEvidence.length?'met':''}"><span>\${activeEvidence.length?'✓':'○'}</span><div><strong>Evidence coverage</strong><small>\${activeEvidence.length ? 'At least one active evidence record is attached.' : 'Attach active evidence to support verification.'}</small></div></div>
                      <div class="engineering-check-row \${/verif/i.test(status)?'met':''}"><span>\${/verif/i.test(status)?'✓':'○'}</span><div><strong>Requirement status</strong><small>\${/verif/i.test(status)?'Requirement is marked verified.':'Requirement is not currently marked verified.'}</small></div></div>
                      <div class="engineering-check-row \${plan.evidence_types?.length?'met':''}"><span>•</span><div><strong>Expected evidence</strong><small>\${esc((plan.evidence_types||[]).join(' · ')||'No evidence type specified')}</small></div></div>
                    </div>
                  </div>
                </section>

                <section class="engineering-panel">
                  <div class="engineering-panel-head"><div><span class="engineering-kicker">EVIDENCE CHAIN</span><h2>Evidence</h2></div><span class="engineering-panel-count">\${evidence.length} records</span></div>
                  <div class="engineering-detail-evidence-list">
                    \${evidence.length ? evidence.map((item,index)=>{
                      const lifecycle=String(item.lifecycle_status||'Active');
                      const invalid=lifecycle!=='Active';
                      const source= item.source_id!=null ? sources.find((src)=>String(src.id)===String(item.source_id)) : null;
                      const evidenceStatus=String(item.supports_status||'Unverified');
                      const evidenceClass=/verif/i.test(evidenceStatus)?'verified':/fail|risk/i.test(evidenceStatus)?'risk':'open';
                      return \`<article class="engineering-evidence-card \${invalid?'invalid':''}">
                        <div class="engineering-evidence-index">\${String(index+1).padStart(2,'0')}</div>
                        <div class="engineering-evidence-body">
                          <div class="engineering-evidence-top"><span class="engineering-status \${evidenceClass}">\${esc(evidenceStatus)}</span><span class="engineering-evidence-type">\${esc(item.evidence_type||'evidence')}</span>\${invalid?'<span class="engineering-invalid-tag">Invalidated</span>':''}</div>
                          <strong>\${esc(item.result||'No result recorded.')}</strong>
                          <p>\${esc(item.description||'No evidence description recorded.')}</p>
                          <div class="engineering-evidence-meta">
                            <span>\${esc(item.created_at||'Recorded')}</span>
                            \${item.location?\`<span>⌖ \${esc(item.location)}</span>\`:''}
                            \${item.calculation_record_id?\`<span>Σ record #\${esc(item.calculation_record_id)}</span>\`:''}
                          </div>
                          <div class="engineering-source-trace">
                            <span class="engineering-detail-label">SOURCE TRACE</span>
                            \${source ? \`<button type="button" class="engineering-source-trace-card" data-engineering-source-detail="\${attr(source.id)}"><span>▧</span><div><strong>\${esc(source.title)}</strong><small>\${esc(source.source_type||'document')} · \${esc(source.version||'unversioned')}</small></div><b>›</b></button>\` : item.source ? \`<div class="engineering-source-trace-card static"><span>▧</span><div><strong>\${esc(item.source)}</strong><small>External reference</small></div></div>\` : '<span class="muted">No source linked</span>'}
                          </div>
                          \${invalid && item.invalidation_reason?\`<div class="engineering-invalid-reason">Invalidation: \${esc(item.invalidation_reason)}</div>\`:''}
                        </div>
                        <div class="engineering-evidence-actions">\${invalid?'':\`<button type="button" class="quiet-button" data-evidence-action="invalidate" data-id="\${attr(item.id)}">Invalidate</button>\`}</div>
                      </article>\`;
                    }).join('') : '<div class="engineering-empty"><strong>No evidence linked.</strong><span>Add a result, source, measurement, calculation, or verification artifact.</span><button class="primary-button" data-engineering-action="evidence" data-id="\${attr(requirement.id)}">Add evidence</button></div>'}
                  </div>
                </section>

                <section class="engineering-panel">
                  <div class="engineering-panel-head"><div><span class="engineering-kicker">DECISION CONTEXT</span><h2>Linked decisions</h2></div><button class="quiet-button" data-engineering-action="decision">+ Add decision</button></div>
                  <div class="engineering-linked-decisions">
                    \${linkedDecisions.length ? linkedDecisions.map((item,index)=>\`<article class="engineering-linked-decision"><div class="engineering-decision-number">\${String(index+1).padStart(2,'0')}</div><div><div class="engineering-decision-heading"><strong>\${esc(item.title)}</strong><span class="engineering-decision-status">\${esc(item.status||'Proposed')}</span></div><p>\${esc(item.decision||'No decision statement recorded.')}</p>\${item.rationale?\`<small>Rationale · \${esc(item.rationale)}</small>\`:''}<time>\${esc(item.updated_at||item.created_at||'')}</time></div></article>\`).join('') : '<div class="engineering-empty compact"><strong>No decisions are linked.</strong><span>Capture why the requirement is shaped this way.</span><button class="outline-button" data-engineering-action="decision">Add linked decision</button></div>'}
                  </div>
                </section>
              </main>

              <aside class="engineering-detail-side">
                <section class="engineering-panel">
                  <div class="engineering-panel-head"><div><span class="engineering-kicker">IDENTITY</span><h2>Requirement record</h2></div></div>
                  <div class="engineering-detail-properties">
                    <div><span>Identifier</span><strong>\${esc(requirement.identifier||\`REQ-\${requirement.id}\`)}</strong></div>
                    <div><span>Priority</span><strong>\${esc(requirement.priority||'Not set')}</strong></div>
                    <div><span>Status</span><strong>\${esc(status)}</strong></div>
                    <div><span>Created</span><strong>\${esc(requirement.created_at||'—')}</strong></div>
                    <div><span>Updated</span><strong>\${esc(requirement.updated_at||'—')}</strong></div>
                  </div>
                </section>

                <section class="engineering-panel">
                  <div class="engineering-panel-head"><div><span class="engineering-kicker">SOURCE TRACEABILITY</span><h2>Referenced sources</h2></div><span class="engineering-panel-count">\${linkedSources.length}</span></div>
                  <div class="engineering-trace-list">
                    \${linkedSources.length ? linkedSources.map((source,index)=>\`<button type="button" class="engineering-trace-row" data-engineering-source-detail="\${attr(source.id)}"><span class="engineering-trace-number">\${String(index+1).padStart(2,'0')}</span><span class="engineering-source-icon">▧</span><div><strong>\${esc(source.title)}</strong><small>\${esc(source.source_type||'document')} · \${esc(source.version||'unversioned')}</small></div><b>›</b></button>\`).join('') : '<div class="engineering-empty compact"><strong>No linked sources.</strong><span>Evidence can point directly to a project source.</span></div>'}
                  </div>
                </section>

                <section class="engineering-panel">
                  <div class="engineering-panel-head"><div><span class="engineering-kicker">ACTIVITY</span><h2>Verification history</h2></div></div>
                  <div class="engineering-timeline">
                    \${[...evidence].sort((a,b)=>String(a.created_at||'').localeCompare(String(b.created_at||''))).slice(-8).reverse().map((item,index)=>\`<div class="engineering-timeline-item"><span class="engineering-timeline-dot \${String(item.lifecycle_status||'Active')==='Active'?'active':'invalid'}"></span><div><strong>\${esc(item.supports_status||'Evidence recorded')}</strong><small>\${esc(item.created_at||'Recorded')}</small><p>\${esc(item.result||item.description||'Evidence updated.')}</p></div></div>\`).join('') || '<div class="engineering-empty compact"><strong>No verification activity.</strong><span>The history will populate as evidence is recorded.</span></div>'}
                  </div>
                </section>
              </aside>
            </div>

            <footer class="engineering-footer"><span>Requirement traceability boundary · source evidence remains inspectable and inert</span><span>REQ-\${esc(requirement.id)} · \${esc(requirement.status||'Unverified')}</span></footer>
          </div>\`;

          document.querySelectorAll('[data-engineering-detail-back]').forEach((back)=>back.onclick=()=>openProjectEngineeringView());
          document.querySelectorAll('[data-engineering-detail-edit]').forEach((edit)=>edit.onclick=()=>engineeringRequirementEditForm(requirement));
        };
      });
      document.querySelectorAll('[data-engineering-source-detail]').forEach((button)=>{
        button.onclick=()=>{
          const source=sources.find((item)=>String(item.id)===String(button.dataset.engineeringSourceDetail));
          if(source) modal(source.title,\`<div class="properties"><div class="property"><span>Type</span><strong>\${esc(source.source_type||'document')}</strong></div><div class="property"><span>Version</span><strong>\${esc(source.version||'Unversioned')}</strong></div><div class="property"><span>Author</span><strong>\${esc(source.author||'—')}</strong></div><div class="property"><span>Publisher</span><strong>\${esc(source.publisher||'—')}</strong></div><div class="property"><span>URL</span><strong>\${esc(source.url||'—')}</strong></div></div>\`);
        };
      });
    }catch(error){toast(error.message);}}
  window.engineeringAction=async(action,id)=>{const projectId=st().projectId;if(!projectId)return;if(['requirement','source','decision','evidence'].includes(action))return engineeringForm(action,id);if(action==='ingest-source')return sourceIngestForm();if(action==='github-source')return githubSourceForm();if(action==='pdf-source')return pdfSourceForm();if(action==='search-sources')return sourceSearchForm();if(action==='test-plan'){const plan=await api(`/api/engineering/projects/${projectId}/requirements/test-plan`);return modal('Engineering test plan',`<div class="properties">${plan.map((item)=>`<div class="property"><span>${esc(item.identifier||`Requirement #${item.requirement_id}`)}</span><strong>${esc(item.title)}</strong><div>${esc(item.verification_method)} · ${esc(item.acceptance_criteria)}</div></div>`).join('')||'<div class="empty-state">No requirements yet.</div>'}</div>`);}if(action==='report'){const report=await api(`/api/engineering/projects/${projectId}/report`);return modal('Weekly engineering report',`<div class="properties"><div class="property"><span>Summary</span><strong>${esc(report.summary)}</strong></div><div class="property"><span>Sources</span><strong>${esc(report.sources)}</strong></div><div class="property"><span>Decisions</span><strong>${esc(report.decisions)}</strong></div><div class="property"><span>Unclear statuses</span><strong>${report.unclear_statuses?.length||0}</strong></div>${(report.unclear_statuses||[]).map((item)=>`<div class="property"><span>Requirement #${item.requirement_id}</span><strong>${esc(item.reason)}</strong></div>`).join('')}</div>`);};};
  async function engineeringForm(kind,requirementId=null){const body={requirement:'<label>Description<textarea name="description" required></textarea></label><label>Title<input name="title"></label>',source:'<label>Title<input name="title" required></label><label>Source type<input name="source_type" value="document"></label><label>Author<input name="author"></label><label>Publisher<input name="publisher"></label><label>URL<input name="url"></label>',decision:'<label>Title<input name="title" required></label><label>Decision<textarea name="decision" required></textarea></label><label>Rationale<textarea name="rationale"></textarea></label>',evidence:'<label>Result<textarea name="result" required></textarea></label><label>Status<select name="supports_status"><option>Verified</option><option>At risk</option><option>Failed</option><option>Unverified</option></select></label><label>Source<textarea name="source" required></textarea></label><label>Description<textarea name="description"></textarea></label>'}[kind];modal(`New ${kind}`,`<form id="engineering-form" class="form-stack">${body}<div class="form-actions"><button type="button" class="outline-button" id="engineering-cancel">Cancel</button><button class="primary-button">Save</button></div></form>`);$('engineering-cancel').onclick=closeModal;$('engineering-form').onsubmit=async(event)=>{event.preventDefault();const values=Object.fromEntries(new FormData(event.target));try{if(kind==='requirement')await send(`/api/engineering/projects/${st().projectId}/requirements`,values);if(kind==='source')await send(`/api/engineering/projects/${st().projectId}/sources`,values);if(kind==='decision'){if(requirementId)values.requirement_id=Number(requirementId);await send(`/api/engineering/projects/${st().projectId}/decisions`,values);}if(kind==='evidence')await send(`/api/engineering/projects/${st().projectId}/requirements/${requirementId}/evidence`,values);closeModal();await openProjectEngineeringView();}catch(error){$('engineering-form').insertAdjacentHTML('afterend',`<div class="error">${esc(error.message)}</div>`);}};}
  function sourceIngestForm(){modal('Ingest engineering source','<form id="source-ingest-form" class="form-stack"><p class="muted">Paste text or Markdown. It is stored as source data with a checksum and searchable chunks; it is never executed.</p><label>Title<input name="title" required placeholder="requirements.md"></label><label>Version<input name="version"></label><label>Source type<input name="source_type" value="text"></label><label>URL<input name="url" placeholder="optional"></label><label>Content<textarea name="content" required></textarea></label><div class="form-actions"><button type="button" class="outline-button" id="source-ingest-cancel">Cancel</button><button class="primary-button">Ingest</button></div></form>');$('source-ingest-cancel').onclick=closeModal;$('source-ingest-form').onsubmit=async(event)=>{event.preventDefault();try{await send(`/api/engineering/projects/${st().projectId}/sources/ingest`,Object.fromEntries(new FormData(event.target)));closeModal();await openProjectEngineeringView();}catch(error){$('source-ingest-form').insertAdjacentHTML('afterend',`<div class="error">${esc(error.message)}</div>`);}};}
  function githubSourceForm(){modal('Import GitHub file','<form id="github-source-form" class="form-stack"><p class="muted">Import a public GitHub file as inert project evidence.</p><label>GitHub file URL<input name="url" type="url" required placeholder="https://github.com/owner/repo/blob/main/README.md"></label><div class="form-actions"><button type="button" class="outline-button" id="github-cancel">Cancel</button><button class="primary-button">Import</button></div></form>');$('github-cancel').onclick=closeModal;$('github-source-form').onsubmit=async(event)=>{event.preventDefault();try{await send(`/api/engineering/projects/${st().projectId}/sources/github`,Object.fromEntries(new FormData(event.target)));closeModal();await openProjectEngineeringView();}catch(error){$('github-source-form').insertAdjacentHTML('afterend',`<div class="error">${esc(error.message)}</div>`);}};}
  function pdfSourceForm(){modal('Import PDF source','<form id="pdf-source-form" class="form-stack"><p class="muted">Upload a text-based PDF. Scanned PDFs are not OCR’d by this shell.</p><label>Title<input name="title" required></label><label>Version<input name="version"></label><input id="pdf-source-file" type="file" accept="application/pdf" required><div class="form-actions"><button type="button" class="outline-button" id="pdf-cancel">Cancel</button><button class="primary-button">Ingest PDF</button></div></form>');$('pdf-cancel').onclick=closeModal;$('pdf-source-form').onsubmit=async(event)=>{event.preventDefault();const file=$('pdf-source-file').files?.[0];if(!file)return;if(file.size>4*1024*1024)return $('pdf-source-form').insertAdjacentHTML('afterend','<div class="error">PDF must be 4 MB or smaller.</div>');try{const reader=new FileReader();reader.onload=async()=>{try{await send(`/api/engineering/projects/${st().projectId}/sources/pdf`,{title:$('pdf-source-form').querySelector('[name="title"]').value||file.name,version:$('pdf-source-form').querySelector('[name="version"]').value||'',data_base64:String(reader.result).split(',',2)[1]});closeModal();await openProjectEngineeringView();}catch(error){$('pdf-source-form').insertAdjacentHTML('afterend',`<div class="error">${esc(error.message)}</div>`);}};reader.readAsDataURL(file);}catch(error){$('pdf-source-form').insertAdjacentHTML('afterend',`<div class="error">${esc(error.message)}</div>`);}};}
  function sourceSearchForm(){modal('Search project sources','<form id="source-search-form" class="form-stack"><label>Search<input name="q" required placeholder="pressure drop, material, requirement…"></label><div class="form-actions"><button type="button" class="outline-button" id="source-search-cancel">Cancel</button><button class="primary-button">Search</button></div><div id="source-search-results" class="source-search-results"></div></form>');$('source-search-cancel').onclick=closeModal;$('source-search-form').onsubmit=async(event)=>{event.preventDefault();const query=String(new FormData(event.target).get('q')||'').trim();if(!query)return;try{const results=await api(`/api/engineering/projects/${st().projectId}/sources/search?q=${encodeURIComponent(query)}&limit=20`);$('source-search-results').innerHTML=results.length?results.map((result)=>`<article class="source-search-result"><strong>${esc(result.source)}</strong><span>${esc(result.location)}</span><p>${esc(result.content)}</p></article>`).join(''):'<div class="empty-state">No matching source chunks were found.</div>';}catch(error){$('source-search-results').innerHTML=`<div class="error">${esc(error.message)}</div>`;}};}
  window.evidenceAction=async(action,id)=>{const projectId=st().projectId;if(action==='add')return engineeringForm('evidence',Number(id));if(action==='invalidate'){const reason=prompt('Why is this evidence being invalidated?');if(!reason?.trim())return;await send(`/api/engineering/projects/${projectId}/evidence/invalidate`,{id:Number(id),reason:reason.trim()});await openProjectEngineeringView();}};

  async function renderSearchResults(result){document.querySelector('.global-search-results')?.remove();const hits=[...(result.chats||[]).map((item)=>({kind:'chat',id:item.id,title:item.title,meta:item.pinned?'Pinned':''})),...(result.projects||[]).map((item)=>({kind:'project',id:item.id,title:item.name,meta:item.description||''})),...(result.notes||[]).map((item)=>({kind:'note',id:item.id,projectId:item.project_id,title:item.title,meta:String(item.content||'').slice(0,120)})),...(result.calculations||[]).map((item)=>({kind:'calculation',id:item.key,title:item.name,meta:item.domain||''}))];const panel=document.createElement('div');panel.className='global-search-results';panel.innerHTML=hits.length?hits.slice(0,24).map((item)=>`<button type="button" data-search-${item.kind}="${attr(item.id)}" ${item.projectId?`data-search-project="${item.projectId}"`:''}><span class="search-kind">${esc(item.kind)}</span><strong>${esc(item.title)}</strong><small>${esc(item.meta)}</small></button>`).join(''):'<div class="empty-state">No matches.</div>';$('global-search').parentElement.appendChild(panel);}

  function hydrateUI(){renderAccountDock();$('calculations-toggle')?.setAttribute('aria-controls','calculation-categories');const line=document.querySelector('.chat-title-line');if(line&&!line.querySelector('.chat-title-menu')){const button=document.createElement('button');button.type='button';button.className='icon-button chat-title-menu';button.textContent='⋯';button.title='Chat actions';button.setAttribute('aria-label','Chat actions');line.appendChild(button);}}
  window.renderAccountDock=renderAccountDock;window.hydrateUI=hydrateUI;window.renderProjectsPage=renderProjectsPage;window.renderProjectFilesPage=renderProjectFilesPage;window.renderSettingsPage=renderSettingsPage;window.renderCustomizeTab=renderCustomizeTab;window.renderEducationPage=renderEducationPage;window.openSimulationsView=openSimulationsView;window.openConnectionsView=openConnectionsView;window.connectionAction=connectionAction;window.pluginAction=pluginAction;window.togglePlugin=togglePlugin;window.openCalculationsView=openCalculationsView;window.openCalculationGroupView=openCalculationGroupView;window.openCalculationSubgroupView=openCalculationSubgroupView;window.openCalculationDetailView=openCalculationDetailView;window.openProjectEngineeringView=openProjectEngineeringView;window.engineeringAction=window.engineeringAction;window.renderSearchResults=renderSearchResults;window.fetchToolSource=async(button)=>{let sources=[];try{sources=JSON.parse(button.dataset.toolFetch||'[]');}catch{return;}const source=sources[0];if(!source)return;if(!st().projectId||!source.chunk_id)return modal('Source','<div class="empty-state">Source metadata is available, but no project chunk ID was returned.</div>');const chunk=await api(`/api/engineering/projects/${st().projectId}/sources/chunks/${source.chunk_id}`);modal(chunk.source||'Source',`<div class="source-detail"><div class="property"><span>Location</span><strong>${esc(chunk.location)}</strong></div><div class="property"><span>Version</span><strong>${esc(chunk.version||'Unversioned')}</strong></div><div class="property"><span>Checksum</span><code>${esc(chunk.checksum)}</code></div><pre class="text-preview">${esc(chunk.content)}</pre></div>`);};
})();
