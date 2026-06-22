/**
 * conversations.js  — Save / Open / Save-As for dbadeeds.ai
 * Used by: AI Assistant, SQL Editor, AI Agents
 *
 * Usage:
 *   Convs.init({ module, getDataFn, loadDataFn, onNew, titleElId })
 *   Convs.saveNow()   Convs.saveAs()   Convs.openPanel()   Convs.newSession()
 */
(function (W) {
  'use strict';

  /* ── state ─────────────────────────────────────────────────────────── */
  let _mod = '', _curId = null, _getD, _loadD, _onNew, _titleEl, _panel;

  /* ── util ──────────────────────────────────────────────────────────── */
  function esc(s){ return String(s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;'); }
  function fmtDate(iso){
    if(!iso) return '';
    try{ return new Date(iso).toLocaleString(undefined,{month:'short',day:'numeric',hour:'2-digit',minute:'2-digit'}); }
    catch{ return iso; }
  }
  function moduleLabel(m){ return {ai_assistant:'AI Assistant',sql_editor:'SQL Editor',ai_agents:'AI Agents'}[m]||m; }
  async function apiFetch(path, opts={}){
    try{
      const r = await fetch(path,{credentials:'include',headers:{'Content-Type':'application/json'},...opts});
      if(r.status===401){ toast('Session expired — please log in again','error'); return null; }
      return await r.json().catch(()=>({}));
    } catch(e){ toast('Network error: '+e.message,'error'); return null; }
  }
  function toast(msg, type='success'){
    if(typeof window.showToast==='function'){ window.showToast(msg, type==='error'?'danger':type==='info'?'info':'success'); return; }
    const el=document.createElement('div');
    el.style.cssText='position:fixed;bottom:20px;right:20px;z-index:99999;padding:10px 16px;border-radius:8px;font-size:13px;font-weight:500;color:#fff;box-shadow:0 4px 12px rgba(0,0,0,.2);max-width:320px;';
    el.style.background=type==='error'?'#DC2626':type==='info'?'#1D4ED8':'#16A34A';
    el.textContent=msg; document.body.appendChild(el);
    setTimeout(()=>el.remove(),3500);
  }

  /* ── init ──────────────────────────────────────────────────────────── */
  function init(opts={}){
    _mod   = opts.module||'';
    _getD  = opts.getDataFn||(()=>({}));
    _loadD = opts.loadDataFn||(()=>{});
    _onNew = opts.onNew||(()=>{});
    _titleEl = opts.titleElId ? document.getElementById(opts.titleElId) : null;
    _injectStyles();
    _buildPanel();
    _setTitle(null);
  }

  /* ── public API ────────────────────────────────────────────────────── */
  async function saveNow(customTitle){
    const data = _getD();
    const body = {module:_mod, data, db_type:data.db_type||'', project:data.project||'', title:customTitle||''};
    if(_curId) body.id = _curId;
    const res = await apiFetch('/api/conversations/save',{method:'POST',body:JSON.stringify(body)});
    if(!res){ return; }
    if(res.ok){ _curId=res.id; _setTitle(res.title); toast('💾 Saved: '+res.title); if(_panel&&_panel.open) _loadList(); }
    else { toast('Save failed: '+(res.error||'unknown'),'error'); }
  }

  async function saveAs(){
    const t = prompt('Save as:', _curTitle()||'');
    if(t===null) return;
    _curId = null;
    await saveNow(t.trim()||undefined);
  }

  function openPanel(){
    if(!_panel) return;
    _panel.open = !_panel.open;
    document.getElementById('_convPanel').style.right = _panel.open ? '0' : '-380px';
    if(_panel.open) _loadList();
  }

  async function newSession(){
    if(!confirm('Start a new session? Unsaved work will be lost.')) return;
    _curId = null; _setTitle(null); _onNew();
    toast('✨ New session started','info');
  }

  /* ── panel ─────────────────────────────────────────────────────────── */
  async function _loadList(q=''){
    const listEl = document.getElementById('_convList');
    if(!listEl) return;
    listEl.innerHTML='<div style="padding:20px;text-align:center;color:#94A3B8;font-size:12px">Loading…</div>';
    const qs = `module=${_mod}${q?'&q='+encodeURIComponent(q):''}`;
    const d  = await apiFetch(`/api/conversations/list?${qs}`);
    if(!d){ listEl.innerHTML='<div style="padding:20px;color:#EF4444;font-size:12px">Failed to load</div>'; return; }
    const convs = d.conversations||[];
    if(!convs.length){
      listEl.innerHTML=`<div style="padding:24px;text-align:center;color:#94A3B8;font-size:12px;line-height:1.7">No saved ${moduleLabel(_mod)} sessions yet.<br>Use <strong>Save</strong> to keep your work.</div>`;
      return;
    }
    listEl.innerHTML = convs.map(c=>`
      <div class="_convItem${c.id===_curId?' _convActive':''}" data-id="${esc(c.id)}">
        <div style="flex:1;min-width:0;cursor:pointer" onclick="Convs._open('${esc(c.id)}')">
          <div style="font-size:12.5px;font-weight:600;color:#1E293B;overflow:hidden;text-overflow:ellipsis;white-space:nowrap">${esc(c.title)}</div>
          <div style="display:flex;gap:6px;align-items:center;margin-top:3px;flex-wrap:wrap">
            ${c.project?`<span style="font-size:10px;padding:1px 5px;border-radius:4px;background:#EFF6FF;color:#1D4ED8;font-weight:600">${esc(c.project)}</span>`:''}
            ${c.db_type?`<span style="font-size:10px;padding:1px 5px;border-radius:4px;background:#F0FDF4;color:#166534;font-weight:600">${esc(c.db_type)}</span>`:''}
            <span style="font-size:10px;color:#94A3B8">${fmtDate(c.updated_at)}</span>
            ${c.msg_count?`<span style="font-size:10px;color:#94A3B8">${c.msg_count} msg${c.msg_count!==1?'s':''}</span>`:''}
          </div>
        </div>
        <div class="_convActions">
          <button title="Rename" onclick="Convs._rename('${esc(c.id)}','${esc(c.title).replace(/'/g,"\\'")}')">✏️</button>
          <button title="Export" onclick="Convs._export('${esc(c.id)}')">⬇️</button>
          <button title="Delete" style="color:#EF4444" onclick="Convs._del('${esc(c.id)}')">🗑️</button>
        </div>
      </div>`).join('');
  }

  async function _open(id){
    const d = await apiFetch(`/api/conversations/${id}`);
    if(!d||d.error){ toast('Failed to load','error'); return; }
    _curId=id; _setTitle(d.title); _loadD(d.data||{});
    document.getElementById('_convPanel').style.right='-380px'; _panel.open=false;
    toast('Opened: '+d.title,'info'); _loadList();
  }

  async function _rename(id, cur){
    const t = prompt('Rename to:', cur);
    if(!t||t===cur) return;
    const d = await apiFetch(`/api/conversations/${id}/rename`,{method:'PUT',body:JSON.stringify({title:t})});
    if(d&&d.ok){ if(_curId===id) _setTitle(d.title); _loadList(); toast('Renamed'); }
    else toast('Rename failed','error');
  }

  async function _del(id){
    if(!confirm('Delete this conversation? Cannot be undone.')) return;
    const d = await apiFetch(`/api/conversations/${id}`,{method:'DELETE'});
    if(d&&d.ok){ if(_curId===id){_curId=null;_setTitle(null);} _loadList(); toast('Deleted'); }
    else toast('Delete failed','error');
  }

  function _export(id){ window.open(`/api/conversations/export/${id}`,'_blank'); }

  /* ── DOM helpers ────────────────────────────────────────────────────── */
  function _curTitle(){ return _titleEl?_titleEl.textContent.replace('● ','').trim():''; }

  function _setTitle(t){
    if(!_titleEl) return;
    _titleEl.textContent = t||'Unsaved';
    _titleEl.title       = t||'Not saved yet';
  }

  function _buildPanel(){
    if(document.getElementById('_convPanel')) return;
    const el = document.createElement('div');
    el.id = '_convPanel';
    el.innerHTML=`
      <div style="display:flex;align-items:center;justify-content:space-between;padding:14px 16px;background:#1E293B;color:#fff;flex-shrink:0">
        <span style="font-size:14px;font-weight:600">💾 Saved Sessions</span>
        <button onclick="Convs.openPanel()" style="background:none;border:none;color:#94A3B8;font-size:16px;cursor:pointer;line-height:1">✕</button>
      </div>
      <div style="padding:10px 12px;border-bottom:1px solid #F1F5F9;flex-shrink:0">
        <input id="_convSearch" type="text" placeholder="Search…" oninput="Convs._loadList(this.value)"
          style="width:100%;box-sizing:border-box;padding:7px 10px;border:1px solid #E5E7EB;border-radius:7px;font-size:12.5px;outline:none">
      </div>
      <div id="_convList" style="flex:1;overflow-y:auto;padding:6px"></div>`;
    document.body.appendChild(el);
    document.addEventListener('click', e=>{
      if(_panel&&_panel.open&&!el.contains(e.target)&&!e.target.closest('[data-conv-open]'))
        { el.style.right='-380px'; _panel.open=false; }
    });
    _panel = el; _panel.open = false;
  }

  function _injectStyles(){
    if(document.getElementById('_convStyles')) return;
    const s=document.createElement('style'); s.id='_convStyles';
    s.textContent=`
      #_convPanel{position:fixed;top:0;right:-380px;width:360px;height:100vh;background:#fff;
        border-left:1px solid #E5E7EB;box-shadow:-4px 0 16px rgba(0,0,0,.08);z-index:9999;
        display:flex;flex-direction:column;overflow:hidden;transition:right .25s ease}
      ._convItem{display:flex;align-items:flex-start;gap:6px;padding:8px 10px;border-radius:8px;
        margin-bottom:3px;border:1px solid transparent;transition:background .1s}
      ._convItem:hover{background:#F8FAFC;border-color:#E5E7EB}
      ._convActive{background:#EFF6FF!important;border-color:#BFDBFE!important}
      ._convActions{display:flex;gap:2px;flex-shrink:0;opacity:0;transition:opacity .15s}
      ._convItem:hover ._convActions{opacity:1}
      ._convActions button{background:none;border:none;font-size:13px;cursor:pointer;padding:2px 4px;border-radius:4px;line-height:1}
      ._convActions button:hover{background:#E5E7EB}
      .conv-bar{display:flex;align-items:center;gap:6px;padding:5px 10px;background:#F8FAFC;
        border-bottom:1px solid #E5E7EB;font-size:12px;flex-shrink:0}
      .conv-title{font-size:12px;color:#374151;font-weight:600;max-width:200px;overflow:hidden;
        text-overflow:ellipsis;white-space:nowrap}
      .conv-btn{padding:4px 10px;border:1px solid #D1D5DB;border-radius:6px;background:#fff;
        color:#374151;font-size:11.5px;font-weight:500;cursor:pointer;white-space:nowrap;
        display:inline-flex;align-items:center;gap:4px;transition:background .1s}
      .conv-btn:hover{background:#F3F4F6}
      .conv-btn.green{background:#16A34A;border-color:#16A34A;color:#fff}
      .conv-btn.green:hover{background:#15803D}`;
    document.head.appendChild(s);
  }

  W.Convs = { init, saveNow, saveAs, openPanel, newSession,
              _open, _rename, _del, _export, _loadList };
})(window);
