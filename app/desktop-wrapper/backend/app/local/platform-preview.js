/* Experimental desktop workbench: completely absent until SIMKO_PLATFORM_UI=1. */
(async () => {
  const config = await fetch('/api/platform/config').then(r => r.json()).catch(() => null);
  if (!config?.flags?.platform_ui) return;
  document.getElementById('labDisabled')?.remove();
  const root = document.createElement('section');
  root.id = 'platformPreview';
  root.innerHTML = `<style>
    #platformPreview{position:relative;z-index:10;box-sizing:border-box;background:#092936;color:#ecfbff;border:1px solid #58a6b8;border-radius:18px;padding:20px;margin:18px auto;width:min(1120px,94vw);font:15px system-ui;overflow-wrap:anywhere}
    #platformPreview *{box-sizing:border-box} #platformPreview h2{margin:0 0 8px} #platformPreview button,#platformPreview input,#platformPreview textarea{font:inherit;border-radius:8px;padding:10px;border:1px solid #69a8ba;max-width:100%}
    #platformPreview button{background:#b6edf5;color:#102c37;cursor:pointer;margin:4px} #platformPreview textarea,#platformPreview input{background:#123b4a;color:white;width:100%;margin:6px 0} #platformPreview pre{white-space:pre-wrap;max-height:400px;overflow:auto}
    #platformPreview .panes{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(260px,100%),1fr));gap:12px} #platformPreview article{background:#16404d;padding:14px;border-radius:12px;min-width:0}
    #platformPreview summary{cursor:pointer;padding:10px 0} #platformPreview .badge{color:#a8dde5;font-size:13px}
  </style><h2>Simko SI · Desktop lab</h2><div class="badge">Preview • Windows / Mac / Linux • New integrations are off by default</div>
  <p>No Grok video. Wan stays on a rented GPU. Nothing sends, buys, or calls automatically.</p>
  <div id="platformIdentity"></div>
  <details open><summary>Agents working side by side</summary><label>Shared task<textarea id="platformTask" placeholder="Give Researcher and Reviewer a task"></textarea></label><button data-action="agents">Start 2 agents (paid API)</button><div class="panes" id="platformPanes"><article><b>Researcher</b><p>Waiting for your task</p></article><article><b>Reviewer</b><p>Peer notes shared through a message bus</p></article></div></details>
  <details><summary>Live search & prompt images</summary><input id="platformPrompt" placeholder="A search query or an image prompt"><button data-action="search">Search with sources (paid API)</button><button data-action="image">Generate image (paid API)</button></details>
  <details><summary>Safe browser reader</summary><p>Allowlisted HTTPS pages only. No logins, scripts, forms, or writes.</p><input id="platformUrl" placeholder="https://allowlisted.example/page"><button data-action="browser">Read page</button></details>
  <details><summary>Memory, notifications & exports</summary><button data-action="sync">Sync memory</button><button data-action="notify">Test desktop notification</button><button data-action="usage">Usage</button><button data-action="report">Export report HTML</button><a href="https://simkosi.com/checkout" target="_blank" rel="noopener noreferrer">Web checkout</a><p>Checkout and entitlement verification must be configured on simkosi.com before paid plans can activate.</p></details>
  <details><summary>Connectors, templates & family team</summary><button data-action="connectors">Connector status</button><label>Connector<select id="platformConnector"><option value="drive">Google Drive (read-only)</option><option value="github">GitHub public repos (read-only)</option></select></label><label>Vault passphrase (or leave blank for native keychain)<input type="password" id="platformPassphrase" autocomplete="off"></label><button data-action="connect">Authorize in system browser</button><button data-action="connectorRead">Read connector metadata</button><button data-action="keychain">Remember passphrase in native keychain</button><button data-action="template">Export agent template</button><label>Import template file<input id="platformTemplateFile" type="file" accept=".json"></label><button data-action="importTemplate">Import template</button><label>Family name<input id="platformFamily" placeholder="My family"></label><button data-action="createTeam">Create local family</button><label>Team ID<input id="platformTeamId"></label><label>Existing local account ID<input id="platformMember"></label><label>Role<select id="platformRole"><option value="child">Child (read)</option><option value="adult">Adult (read/use)</option></select></label><button data-action="addMember">Add family member</button><button data-action="teamMembers">List family roles</button><p>Google Drive read-only and GitHub. Tokens stay in the vault. Family roles: owner, adult, child.</p></details>
  <details><summary>Phone calls</summary><p>Disabled. A provider account, per-minute budget, and your approval are required. No calls have been placed.</p></details><pre id="platformResult" role="status"></pre>`;
  document.body.append(root);
  const result = root.querySelector('#platformResult');
  const text = () => root.querySelector('#platformPrompt').value;
  async function request(action, data={}) {
    const token = typeof authToken !== 'undefined' ? authToken : (sessionStorage.getItem('podcoderToken') || '');
    const response = await fetch('/api/platform/'+action,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({...data,token})});
    const value = await response.json();
    result.textContent = JSON.stringify(value,null,2);
    return value;
  }
  const identity = root.querySelector('#platformIdentity');
  for (const [provider, settings] of Object.entries(config.providers)) {
    if (!settings.enabled) continue;
    const button = document.createElement('button');
    button.textContent = 'Sign in with '+provider;
    button.onclick = async () => {
      const auth = await request('oauth/begin',{provider});
      if (!auth.ok) return;
      if (!auth.browser_opened) window.open(auth.url,'_blank','noopener,noreferrer');
      const timer = setInterval(async()=>{
        const value = await request('oauth/poll',{ticket:auth.ticket});
        if (!value.pending) {
          clearInterval(timer);
          if (value.token) {
            sessionStorage.setItem('podcoderToken',value.token);
            if (typeof authToken !== 'undefined') authToken = value.token;
            result.textContent = 'Signed in. Return to chat to refresh your account.';
          }
        }
      },1500);
      setTimeout(()=>clearInterval(timer),180000);
    };
    identity.append(button);
  }
  root.addEventListener('click',async event=>{
    const action = event.target.dataset.action;
    if (!action) return;
    const connector = root.querySelector('#platformConnector').value;
    const password = () => root.querySelector('#platformPassphrase').value;
    if (['connect','connectorRead','keychain'].includes(action)) {
      const passphrase = password();
      root.querySelector('#platformPassphrase').value='';
      if (action === 'keychain') {await request('vault/keychain',{passphrase});return;}
      if (action === 'connectorRead') {await request('connectors/read',{name:connector,passphrase});return;}
      const auth = await request('connectors/begin',{name:connector,passphrase});
      if (!auth.ok) return;
      if (!auth.browser_opened) window.open(auth.url,'_blank','noopener,noreferrer');
      const timer=setInterval(async()=>{
        const value=await request('connectors/poll',{ticket:auth.ticket});
        if (!value.pending) clearInterval(timer);
      },1500);
      setTimeout(()=>clearInterval(timer),180000);return;
    }
    if (action === 'importTemplate') {
      const file=root.querySelector('#platformTemplateFile').files[0];
      if (!file || file.size>100000) {result.textContent='Choose a template JSON file under 100 KB.';return;}
      await request('templates/import',{content:await file.text()});return;
    }
    const team = root.querySelector('#platformTeamId').value;
    if (action === 'createTeam') {
      const value=await request('team/create',{name:root.querySelector('#platformFamily').value});
      if(value.ok)root.querySelector('#platformTeamId').value=value.id;return;
    }
    if (action === 'addMember') {await request('team/member',{team,member:root.querySelector('#platformMember').value,role:root.querySelector('#platformRole').value});return;}
    if (action === 'teamMembers') {await request('team/members',{team});return;}
    if (['agents','search','image'].includes(action) && !confirm('This uses the configured paid xAI API. Approve this action? Agents make up to 4 model requests.')) return;
    if (action === 'agents') {
      const group = await request('agents/start',{names:['Researcher','Reviewer'],task:root.querySelector('#platformTask').value,approve_paid:true});
      if (!group.ok) return;
      const timer = setInterval(async()=>{
        const value = await request('agents/status',{id:group.id});
        const panes = root.querySelector('#platformPanes');
        if (value.panes) {
          panes.replaceChildren();
          for (const [name,pane] of Object.entries(value.panes)) {
            const article = document.createElement('article'), title=document.createElement('b'), content=document.createElement('pre');
            title.textContent = name+' · '+pane.status; content.textContent=pane.text || 'Working…'; article.append(title,content);panes.append(article);
          }
        }
        if (!value.ok || value.status !== 'running') clearInterval(timer);
      },1000);
      setTimeout(()=>clearInterval(timer),300000);
    }
    const routes = {search:['search',{query:text(),approve_paid:true}],image:['image',{prompt:text(),approve_paid:true}],browser:['browser/read',{url:root.querySelector('#platformUrl').value}],sync:['sync',{}],notify:['notify/test',{}],usage:['usage',{}],report:['report',{title:'Simko SI report',text:result.textContent}],connectors:['connectors',{}],template:['templates/export',{name:'Research pair',agents:[{name:'Researcher',instructions:'Research the task'},{name:'Reviewer',instructions:'Review critically'}]}]};
    if (routes[action]) {
      const value = await request(...routes[action]);
      if (value.ok && value.content && value.filename) {
        const link=document.createElement('a');
        link.href=URL.createObjectURL(new Blob([value.content],{type:action === 'report' ? 'text/html' : 'application/json'}));
        link.download=value.filename;link.textContent='Save '+value.filename;
        result.replaceChildren(link);
      }
    }
  });
})();
