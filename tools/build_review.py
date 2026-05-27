#!/usr/bin/env python3
"""Build paperdoctor.html from check_*.json + quote_positions.json.

Usage:
    python tools/build_review.py papers/showui
"""

import argparse
import json
import re
import html as html_mod
from pathlib import Path

# file:line[-end] tokens (e.g. "configs/train.yaml:14-22"). Used twice — once
# to set data-code-ref on a card, once to slice CODE_SNIPPETS. The data
# migration parks the locator at the start of `quote` for code findings, so
# we anchor with `\s*` and use re.match.
CODE_REF_RX = re.compile(r'\s*([\w/._-]+\.\w+):(\d+)(?:-(\d+))?')

# ────────────────────────────────────────────────────────────────────
# Human annotation editor (injected before </body>).
#
# Always-on inline editing — no mode toggle, no header buttons. Click the
# field you want to change; it becomes editable in place. Silent auto-save
# to localStorage (per paper slug). The AI-generated check_*.json is never
# overwritten — human edits live in a separate state object.
# ────────────────────────────────────────────────────────────────────
EDITOR_BLOCK_TEMPLATE = r"""
<style>
/* ── Inline-editing affordances on finding cards ─────────────────── */
.finding-card { position:relative; }

/* Clickable status badge — acts as its own "edit me" affordance */
.finding-status { cursor:pointer; position:relative; }
.finding-status:hover::after { content:"▾"; margin-left:4px; font-size:9px; }

/* Inline status dropdown (replaces the badge while open) */
.status-picker { position:absolute; background:#fff; border:1px solid #d1d5db; border-radius:4px; box-shadow:0 4px 12px rgba(0,0,0,0.15); z-index:50; min-width:140px; padding:4px; }
.status-picker button { display:block; width:100%; text-align:left; font-family:inherit; font-size:12px; padding:5px 8px; border:none; background:none; cursor:pointer; border-radius:2px; color:#111; }
.status-picker button:hover { background:#f3f4f6; }
.status-picker button.current { font-weight:700; color:#4f46e5; }
.status-picker .sep { border-top:1px solid #e5e7eb; margin:4px 0; }
.status-picker .reset { color:#6b7280; font-style:italic; font-size:11px; }

/* Override state styling */
.finding-card.human-override { border-left:4px solid #4f46e5 !important; }

/* Small inline status pill next to the AI one (used by human-added cards + status override) */
.human-tag { display:inline-block; margin-left:6px; font-size:10px; padding:1px 7px; border-radius:10px; font-weight:700; color:#fff; vertical-align:middle; letter-spacing:.3px; }
.human-tag.h-pass { background:#065f46; }
.human-tag.h-warning { background:#92400e; }
.human-tag.h-error { background:#991b1b; }

/* Inline-editable fields — any AI text can be overridden in place.
   span.editable-field gets inline-block so the absolute-positioned ✓✗? buttons
   anchor to the span's full multi-line bounding box (inline spans anchor to
   the first line box, which makes the buttons drift to weird positions). */
.editable-field { cursor:text; position:relative; border-radius:2px; padding:1px 3px; margin:-1px -3px; }
span.editable-field { display:inline-block; max-width:100%; vertical-align:top; }
/* During edit mode the span must expand to the row width so the textarea
   doesn't shrink to the natural (pre-edit) text width. */
.editable-field:has(> .inline-edit) { display:block; width:100%; max-width:100%; }
.editable-field:hover { background:rgba(79,70,229,0.06); }
.editable-field.human-edited { background:rgba(79,70,229,0.08); border-left:3px solid #4f46e5; padding-left:7px; }
.inline-edit { display:block; width:100%; min-height:40px; padding:4px 6px; border:1px solid #4f46e5; border-radius:3px; font-family:inherit; font-size:inherit; color:inherit; background:#fff; resize:vertical; box-sizing:border-box; line-height:inherit; }

/* Per-field 3-button overlay at top-right OUTSIDE the field box (top:-10px).
   Colored by default (green ✓, red ✗, yellow ?). Hidden until the field is
   hovered. Moving the mouse from the text up to the buttons crosses a gap
   where neither element is hovered, so we use `visibility + transition-delay`
   to keep them interactive for 0.25s after hover ends — if the cursor reaches
   the buttons in that window, .field-btns:hover takes over and holds them. */
.field-btns { position:absolute; top:-10px; right:4px; display:inline-flex; gap:2px; z-index:4; user-select:none;
              opacity:0; visibility:hidden;
              transition: opacity 0.12s 0.25s, visibility 0s 0.25s; }
.editable-field:hover .field-btns, .field-btns:hover {
    opacity:1; visibility:visible;
    transition: opacity 0.12s 0s, visibility 0s 0s;
}
/* Reset every inheritable font property so the ✓ / ✗ / ? symbols render in
   the SAME font across ALL fields (some fields inherit monospace + italic
   from .detail-quote, which would otherwise make the button text italic
   monospace on those fields only). */
.field-btns button { width:20px; height:20px; padding:0; line-height:18px; cursor:pointer; border:1.5px solid; border-radius:50%; background:#fff; box-shadow:0 1px 2px rgba(0,0,0,0.08);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI Symbol", "Helvetica Neue", Arial, sans-serif !important;
  font-size: 12px !important;
  font-weight: 700 !important;
  font-style: normal !important;
  font-variant-emoji: text;
  text-transform: none;
  letter-spacing: normal; }
.field-btns button.fb-ok    { color:#10b981; border-color:#10b981; }
.field-btns button.fb-bad   { color:#ef4444; border-color:#ef4444; }
.field-btns button.fb-doubt { color:#f59e0b; border-color:#f59e0b; }
.field-btns button.fb-ok.on    { background:#10b981; color:#fff; }
.field-btns button.fb-bad.on   { background:#ef4444; color:#fff; }
.field-btns button.fb-doubt.on { background:#f59e0b; color:#fff; }

/* Field mark states — colored left border so the verdict stays visible after hover ends */
.editable-field.field-ok    { box-shadow: inset 3px 0 0 #10b981; background:rgba(16,185,129,0.06); }
.editable-field.field-bad   { box-shadow: inset 3px 0 0 #ef4444; background:rgba(239,68,68,0.06); }
.editable-field.field-doubt { box-shadow: inset 3px 0 0 #f59e0b; background:rgba(245,158,11,0.06); }

/* ── PDF: Shift+drag to highlight ────────────────────────────────── */
.pdf-hint { position:absolute; top:4px; right:4px; background:rgba(0,0,0,.65); color:#fff; font-size:10px; padding:2px 6px; border-radius:3px; pointer-events:none; opacity:0; transition:opacity .15s; z-index:3; }
.pdf-page:hover .pdf-hint { opacity:1; }
.pdf-page.drawing, body.drawing .pdf-page { cursor:crosshair; }
.draw-box { position:absolute; border:2px solid #4f46e5; background:rgba(79,70,229,0.1); pointer-events:none; z-index:7; }

.pdf-hl.human-hl { border-style:dashed !important; border-width:2px !important; }
.pdf-hl.human-hl .hh-mark { position:absolute; top:-9px; right:-9px; width:18px; height:18px; background:#4f46e5; color:#fff; font-size:10px; font-weight:800; display:flex; align-items:center; justify-content:center; border-radius:50%; border:2px solid #fff; pointer-events:none; }

/* Highlight-creation popup */
.new-hl-popup { position:fixed; background:#fff; border:1px solid #d1d5db; border-radius:6px; padding:10px; box-shadow:0 4px 12px rgba(0,0,0,0.2); z-index:300; min-width:260px; }
.new-hl-popup h4 { font-size:12px; margin-bottom:8px; color:#111; font-weight:700; }
.new-hl-popup .color-row { display:flex; gap:4px; margin-bottom:8px; }
.new-hl-popup .color-row button { flex:1; font-size:11px; padding:5px 8px; border:2px solid transparent; border-radius:3px; cursor:pointer; color:#fff; font-weight:700; }
.new-hl-popup .color-row button.h-pass { background:#10b981; }
.new-hl-popup .color-row button.h-warning { background:#f59e0b; }
.new-hl-popup .color-row button.h-error { background:#ef4444; }
.new-hl-popup .color-row button.selected { border-color:#111; }
.new-hl-popup textarea { width:100%; min-height:50px; padding:6px; border:1px solid #d1d5db; border-radius:3px; font-family:inherit; font-size:12px; resize:vertical; }
.new-hl-popup .actions { margin-top:8px; display:flex; gap:6px; justify-content:flex-end; }
.new-hl-popup .actions button { font-size:11px; padding:4px 10px; border:1px solid #d1d5db; border-radius:3px; cursor:pointer; background:#fff; color:#111; }
.new-hl-popup .actions .save { background:#4f46e5; color:#fff; border-color:#4f46e5; }

.toast { position:fixed; top:56px; left:50%; transform:translateX(-50%); background:#111827; color:#fff; padding:8px 18px; border-radius:20px; font-size:12px; opacity:0; transition:opacity .3s; pointer-events:none; z-index:500; max-width:80vw; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.toast.show { opacity:0.95; }

/* ── Per-block verdict buttons (in Where/Why/How block headers) ── */
.kb-verdict { display:inline-flex; gap:3px; margin-left:auto; }
.kb-verdict button { width:24px; height:24px; padding:0; line-height:22px; cursor:pointer; border:1.5px solid #d1d5db; border-radius:50%; background:#fff; font-size:13px; font-weight:700; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI Symbol",sans-serif; display:inline-flex; align-items:center; justify-content:center; }
.kb-verdict .cv-ok    { color:#10b981; }
.kb-verdict .cv-bad   { color:#ef4444; }
.kb-verdict .cv-doubt { color:#f59e0b; }
.kb-verdict .cv-ok:hover    { border-color:#10b981; }
.kb-verdict .cv-bad:hover   { border-color:#ef4444; }
.kb-verdict .cv-doubt:hover { border-color:#f59e0b; }
.kb-verdict .cv-ok.on    { background:#10b981; color:#fff; border-color:#10b981; }
.kb-verdict .cv-bad.on   { background:#ef4444; color:#fff; border-color:#ef4444; }
.kb-verdict .cv-doubt.on { background:#f59e0b; color:#fff; border-color:#f59e0b; }

/* ── Static L1/L2/L3 tier badge (auto-derived from report type) ──
   Colors match the paper's pipeline figure (fig-banana/pipeline.png):
   L1=#b7e8d3 mint, L2=#c7d6f3 periwinkle, L3=#87adea blue. */
.tier-badge { display:inline-block; font-size:10px; font-weight:800; padding:1px 6px; border-radius:3px; margin-right:5px; vertical-align:middle; letter-spacing:.3px; }
.tier-l1 { background:#b7e8d3; color:#065f46; }
.tier-l2 { background:#c7d6f3; color:#1e3a8a; }
.tier-l3 { background:#87adea; color:#0c2456; }
/* Pull section tier badge before the ::before disclosure triangle in flex order. */
details.report-section > summary > .tier-badge { order:-1; }

/* ── Save controls in header ── */
.save-indicator { font-size:11px; color:#6b7280; margin-left:auto; display:flex; align-items:center; gap:6px; }
.save-indicator .status-text { white-space:nowrap; margin-right:2px; }
.save-indicator button { background:none; border:1px solid #d1d5db; color:#374151; font-size:11px; padding:3px 10px; border-radius:3px; cursor:pointer; font-family:inherit; }
.save-indicator button:hover { background:#f3f4f6; }

/* ── Dark-mode toggle button (top-right of header) ── */
.theme-toggle { background:transparent; border:1px solid #d1d5db; color:#374151; font-size:14px; width:28px; height:26px; padding:0; border-radius:50%; cursor:pointer; font-family:inherit; line-height:1; margin-left:10px; display:inline-flex; align-items:center; justify-content:center; transition:background-color .15s, color .15s, border-color .15s; }
.theme-toggle:hover { background:#f3f4f6; }
body.dark .theme-toggle { color:#e5e7eb; border-color:#3a3a40; }
body.dark .theme-toggle:hover { background:#2a2a30; }

/* ── Dark mode (toggle adds .dark on <body>). Left + middle panels are
   already dark; these rules flip the header, right panel, popovers, and
   every text color that defaults to a near-black/dark-gray on a light
   surface. Status / tier / writing-diff accent colors stay the same — only
   neutral surfaces invert. ── */
body.dark { background:#0f0f12; color:#e5e7eb; }
/* Header */
body.dark .header { background:#1a1a1d; border-bottom-color:#2a2a30; color:#e5e7eb; }
body.dark .header-brand { color:#e5e7eb; }
/* Right panel */
body.dark .panel-right { background:#0f0f12; }
body.dark .right-content { color:#d1d5db; }
body.dark .paper-title { color:#f3f4f6; border-bottom-color:#2a2a30; }
body.dark .section-title { color:#e5e7eb; }
body.dark .section-divider, body.dark hr.section-divider { border-top-color:#2a2a30; }
body.dark .summary-text { color:#d1d5db; }
/* Donut chart */
body.dark .donut-center .num { color:#e5e7eb; }
body.dark .donut-center .label { color:#9ca3af; }
body.dark .tier-bar { background:#2a2a30; }
body.dark .tier-meta .cnt { color:#9ca3af; }
body.dark .legend { color:#d1d5db; }
/* Section bars (the L1/L2/L3 summary header) */
body.dark details.report-section > summary { background:#1a1a1d; border-color:#2a2a30; color:#e5e7eb; }
body.dark details.report-section > summary::before { color:#9ca3af; }
/* Finding cards */
body.dark .finding-card { background:#1a1a1d; border-color:#2a2a30; color:#d1d5db; }
body.dark .finding-source { color:#9ca3af; }
body.dark .finding-source strong { color:#cbd5e1; }
body.dark .detail-body { background:#111114; border-color:#2a2a30; color:#d1d5db; }
body.dark .detail-label { color:#9ca3af; }
body.dark .detail-quote { color:#9ca3af; }
/* Save indicator + theme toggle (header buttons) */
body.dark .save-indicator { color:#9ca3af; }
body.dark .save-indicator button { color:#e5e7eb; border-color:#3a3a40; }
body.dark .save-indicator button:hover { background:#2a2a30; }
/* Filter bar */
body.dark .filter-bar button { background:#1a1a1d; color:#d1d5db; border-color:#3a3a40; }
body.dark .filter-bar button.on { background:#374151; color:#fff; border-color:#4b5563; }
body.dark .filter-bar label { color:#d1d5db; border-color:#3a3a40; }
body.dark .filter-bar label:hover { background:#2a2a30; }
/* Reproduction table */
body.dark .repro-table th { color:#9ca3af; }
body.dark .repro-table td, body.dark .repro-table th { border-color:#2a2a30; }
/* Writing-diff inline pills (red→addition, green→deletion). Tone the
   pastel light backgrounds down to deep counterparts that retain meaning. */
body.dark .writing-before { background:#3a1414; color:#fca5a5; }
body.dark .writing-after { background:#0a2e16; color:#86efac; }
body.dark .writing-arrow { color:#6b7280; }
/* Inline editor (when editing a field via contenteditable/textarea) */
body.dark .inline-edit { background:#0f0f12; color:#e5e7eb; border-color:#4f46e5; }
/* Status picker dropdown */
body.dark .status-picker { background:#1a1a1d; border-color:#2a2a30; box-shadow:0 4px 12px rgba(0,0,0,.5); }
body.dark .status-picker button { color:#e5e7eb; }
body.dark .status-picker button:hover { background:#2a2a30; }
body.dark .status-picker .reset { color:#9ca3af; }
/* Per-card verdict and per-field ✓✗? buttons */
body.dark .kb-verdict button { background:#1a1a1d; border-color:#3a3a40; }
body.dark .field-btns button { background:#1a1a1d; }
/* New-highlight modal popup (PDF Shift+drag) */
body.dark .new-hl-popup { background:#1a1a1d; border-color:#2a2a30; }
body.dark .new-hl-popup h4 { color:#f3f4f6; }
body.dark .new-hl-popup .color-row button.selected { border-color:#f3f4f6; }
body.dark .new-hl-popup .actions button { background:#1a1a1d; color:#e5e7eb; border-color:#3a3a40; }
/* PDF in-page popover */
body.dark .pdf-popover { background:#1a1a1d; color:#e5e7eb; border-color:#2a2a30; }
body.dark .pdf-popover button { color:#e5e7eb; }
body.dark .pdf-popover button:hover { background:#2a2a30; color:#93c5fd; }
body.dark .pdf-popover-parent { background:#1e1b3a; color:#c4b5fd; }
</style>

<div class="toast" id="toast"></div>

<script>
(function(){
  var PAPER_SLUG = '__PAPER_SLUG__';
  var STORAGE_KEY = 'paperdr_annotations_' + PAPER_SLUG;

  var state = {
    version: 1,
    paper: PAPER_SLUG,
    updated_at: '',
    // cardId -> {status?, fields?: {summary?, quote?, claim?, ...}, marks?: {summary?: 'ok'|'bad'|'doubt', ...}}
    overrides: {},
    new_highlights: [],   // {id, page, box_pct, color, comment}
    new_findings: []      // {id, status, source, quote, comment, page}
  };

  // Editable fields: match a .detail-row whose .detail-label text equals this (case-insensitive).
  var FIELD_DEFS = [
    {key:'quote',   label:'quote'},
    {key:'claim',   label:'claim'},
    {key:'reason',  label:'reason'},
    {key:'suggest', label:'suggestion'},
  ];

  // Per-field verdict buttons (green check / red cross / yellow doubt).
  // \uFE0E (VS15) forces text-style presentation so emoji-capable
  // platforms render ✓/✗ in the same font as ?, not as colored emoji.
  var FIELD_BTNS = [
    {mark:'ok',    symbol:'\u2713\uFE0E', title:'Mark correct'},
    {mark:'bad',   symbol:'\u2717\uFE0E', title:'Mark wrong'},
    {mark:'doubt', symbol:'?', title:'Mark uncertain'},
  ];

  function esc(s){ return (s||'').replace(/[&<>"]/g, function(c){ return {'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]; }); }
  function cap(s){ return s.charAt(0).toUpperCase() + s.slice(1); }
  function toast(msg, duration){
    var t = document.getElementById('toast');
    if(!t) return;
    t.textContent = msg; t.classList.add('show');
    clearTimeout(toast._t);
    toast._t = setTimeout(function(){ t.classList.remove('show'); }, duration || 2000);
  }

  var _jsonFilename = PAPER_SLUG + '_annotations.json';
  var _hasUnexported = false;
  var _boundDirHandle = null;
  var _saveTimer = null;
  var _saveInFlight = null;
  var HANDLE_DB_NAME = 'paperdr_review_handles';
  var HANDLE_STORE_NAME = 'handles';
  var HANDLE_KEY = 'dir::' + window.location.href.split('#')[0].split('?')[0];

  function defaultState(obj){
    return Object.assign({version:1, paper:PAPER_SLUG, overrides:{}, new_highlights:[], new_findings:[]}, obj || {});
  }
  function parseUpdatedAt(obj){
    var t = Date.parse((obj && obj.updated_at) || '');
    return isNaN(t) ? 0 : t;
  }
  function pickNewerState(a, b){
    if(!a) return defaultState(b);
    if(!b) return defaultState(a);
    return parseUpdatedAt(b) >= parseUpdatedAt(a) ? defaultState(b) : defaultState(a);
  }

  function save(){
    state.updated_at = new Date().toISOString();
    try { localStorage.setItem(STORAGE_KEY, JSON.stringify(state)); } catch(e){}
  }

  function markDirty(){
    save();
    toast('已暂存于浏览器', 1200);
    _hasUnexported = true;
    updateSaveUi();
    scheduleAutoPersist();
    renderTierBars();
  }

  function scheduleAutoPersist(){
    clearTimeout(_saveTimer);
    if(!_boundDirHandle) return;
    _saveTimer = setTimeout(function(){ persistAnnotations(false); }, 700);
  }

  function updateSaveUi(){
    var btnSave = document.getElementById('btnSave');
    var btnFolderSetup = document.getElementById('btnFolderSetup');
    var status = document.getElementById('saveStatusText');
    var canBindFolder = !!window.showDirectoryPicker;
    var secure = window.isSecureContext !== false;
    if(btnSave){
      btnSave.textContent = _hasUnexported ? 'Save *' : 'Save';
      btnSave.style.background = _hasUnexported ? '#f59e0b' : '';
      btnSave.style.color = _hasUnexported ? '#fff' : '';
      btnSave.style.borderColor = _hasUnexported ? '#f59e0b' : '';
    }
    if(btnFolderSetup){
      btnFolderSetup.textContent = _boundDirHandle ? 'Change Folder' : 'Choose Folder';
      btnFolderSetup.style.display = canBindFolder ? '' : 'none';
    }
    if(status){
      if(_boundDirHandle){
        status.textContent = _hasUnexported ? 'Folder bound · autosave pending' : 'Folder bound · saved';
      } else if(!secure){
        status.textContent = 'Direct save blocked in this tab by browser security policy';
      } else if(canBindFolder){
        status.textContent = _hasUnexported ? 'Browser cache only · choose folder once for autosave' : 'Choose folder once for autosave';
      } else {
        status.textContent = _hasUnexported ? 'Browser cache only · open in Chromium for direct save' : 'Direct save requires Chromium';
      }
    }
  }

  window.exportAnnotations = function(){
    var blob = new Blob([JSON.stringify(state, null, 2)], {type:'application/json'});
    var a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = _jsonFilename;
    document.body.appendChild(a);
    a.click();
    setTimeout(function(){ document.body.removeChild(a); URL.revokeObjectURL(a.href); }, 100);
    _hasUnexported = false;
    updateSaveUi();
    toast('已导出: ' + _jsonFilename, 2500);
  };

  function withHandleStore(mode, fn){
    return new Promise(function(resolve){
      if(!window.indexedDB) return resolve(null);
      var req = indexedDB.open(HANDLE_DB_NAME, 1);
      req.onupgradeneeded = function(){
        var db = req.result;
        if(!db.objectStoreNames.contains(HANDLE_STORE_NAME)){
          db.createObjectStore(HANDLE_STORE_NAME);
        }
      };
      req.onerror = function(){ resolve(null); };
      req.onsuccess = function(){
        var db = req.result;
        var tx = db.transaction(HANDLE_STORE_NAME, mode);
        var store = tx.objectStore(HANDLE_STORE_NAME);
        var inner = null;
        try {
          inner = fn(store);
        } catch(e) {
          db.close();
          return resolve(null);
        }
        tx.oncomplete = function(){
          db.close();
          resolve(inner ? inner.result : null);
        };
        tx.onerror = function(){
          db.close();
          resolve(null);
        };
      };
    });
  }

  function loadStoredDirHandle(){
    return withHandleStore('readonly', function(store){ return store.get(HANDLE_KEY); });
  }
  function saveStoredDirHandle(handle){
    return withHandleStore('readwrite', function(store){ return store.put(handle, HANDLE_KEY); });
  }
  function clearStoredDirHandle(){
    return withHandleStore('readwrite', function(store){ return store.delete(HANDLE_KEY); });
  }

  async function queryHandlePermission(handle, write){
    if(!handle || !handle.queryPermission) return 'prompt';
    try {
      return await handle.queryPermission({mode: write ? 'readwrite' : 'read'});
    } catch(e){
      return 'prompt';
    }
  }
  async function requestHandlePermission(handle, write){
    if(!handle || !handle.requestPermission) return false;
    try {
      return (await handle.requestPermission({mode: write ? 'readwrite' : 'read'})) === 'granted';
    } catch(e){
      return false;
    }
  }
  async function ensureDirAccess(prompt){
    if(!_boundDirHandle) return false;
    var perm = await queryHandlePermission(_boundDirHandle, true);
    if(perm === 'granted') return true;
    if(!prompt) return false;
    return await requestHandlePermission(_boundDirHandle, true);
  }
  async function chooseAnnotationFolder(){
    if(!window.showDirectoryPicker){
      toast('This browser does not support direct folder save', 3000);
      return false;
    }
    try {
      _boundDirHandle = await window.showDirectoryPicker();
      await saveStoredDirHandle(_boundDirHandle);
      updateSaveUi();
      return true;
    } catch(err){
      if(err && err.name === 'AbortError'){
        return false;
      }
      if(err && err.name === 'SecurityError'){
        toast('Choose Folder was blocked by the browser in this tab.', 4200);
        return false;
      }
      if(err){
        toast('Choose Folder failed: ' + (err.name || 'UnknownError'), 4200);
      }
      return false;
    }
  }

  async function loadAnnotationsFromBoundFolder(){
    if(!_boundDirHandle) return null;
    if(await queryHandlePermission(_boundDirHandle, false) !== 'granted'){
      return null;
    }
    try {
      var fileHandle = await _boundDirHandle.getFileHandle(_jsonFilename);
      var file = await fileHandle.getFile();
      return defaultState(JSON.parse(await file.text()));
    } catch(err){
      return null;
    }
  }
  async function persistAnnotations(manual){
    if(_saveInFlight) return _saveInFlight;
    _saveInFlight = (async function(){
      if(!_boundDirHandle){
        if(!manual) return false;
        if(!await chooseAnnotationFolder()) return false;
      }
      if(!await ensureDirAccess(manual)) return false;
      try {
        var fileHandle = await _boundDirHandle.getFileHandle(_jsonFilename, {create:true});
        var writable = await fileHandle.createWritable();
        await writable.write(JSON.stringify(state, null, 2));
        await writable.close();
        _hasUnexported = false;
        updateSaveUi();
        if(manual) toast('已保存到当前目录: ' + _jsonFilename, 2500);
        return true;
      } catch(err){
        if(err && (err.name === 'NotFoundError' || err.name === 'InvalidStateError')){
          _boundDirHandle = null;
          await clearStoredDirHandle();
          updateSaveUi();
        }
        if(manual){
          toast('保存失败，改动仍保留在浏览器缓存中', 3200);
        }
        return false;
      }
    })();
    try {
      return await _saveInFlight;
    } finally {
      _saveInFlight = null;
    }
  }

  window.bindAnnotationFolder = async function(){
    if(!await chooseAnnotationFolder()) return false;
    toast('Folder selected. Future edits will save to ' + _jsonFilename, 2500);
    if(_hasUnexported){
      await persistAnnotations(true);
    }
    return true;
  };
  window.saveAnnotations = async function(){
    if(!_boundDirHandle && window.showDirectoryPicker){
      toast('Choose Folder first, then Save will write there', 3200);
      return;
    }
    if(await persistAnnotations(true)) return;
    if(!window.showDirectoryPicker){
      exportAnnotations();
    }
  };

  window.importAnnotations = function(){
    var inp = document.createElement('input');
    inp.type = 'file';
    inp.accept = '.json';
    inp.onchange = function(){
      if(!inp.files[0]) return;
      var reader = new FileReader();
      reader.onload = function(e){
        try {
          var imported = JSON.parse(e.target.result);
          state = defaultState(imported);
          save();
          _hasUnexported = true;
          updateSaveUi();
          applyAll();
          scheduleAutoPersist();
          toast('已导入: ' + inp.files[0].name, 2500);
        } catch(err){ toast('JSON 文件无效', 2500); }
      };
      reader.readAsText(inp.files[0]);
    };
    inp.click();
  };

  window.addEventListener('beforeunload', function(e){
    if(_hasUnexported){
      e.preventDefault();
      e.returnValue = '';
    }
  });

  function getCard(id){ return document.querySelector('.finding-card[data-highlight-id="' + id + '"]'); }
  function writeOverride(id, ov){
    if(!ov || Object.keys(ov).length === 0) delete state.overrides[id];
    else state.overrides[id] = ov;
  }

  // ── One-time per-card init: cache field elements + wire editors ──
  function initCard(card){
    if(card._inited) return; card._inited = true;
    var hlId = card.getAttribute('data-highlight-id') || '';
    var isClaim = hlId.indexOf('claim-') === 0;
    resolveFieldEls(card);
    Object.keys(card._fieldEls).forEach(function(key){
      var el = card._fieldEls[key];
      if(!el.hasAttribute('data-orig-text')) el.setAttribute('data-orig-text', el.textContent);
      if(!isClaim) wireFieldEditor(card, key, el);
    });
    attachTierBadge(card);
    if(!isClaim) wireStatusPickerTrigger(card);
    wireKindBlockVerdicts(card);
  }

  // ── Single source of truth: read/write a kind's verdict+comment in overrides ──
  // Single source of truth for writing a kind's verdict to overrides.
  function setKindVerdict(id, kind, mark){
    var ov = Object.assign({}, state.overrides[id] || {});
    var v = Object.assign({}, ov.verdicts || {});
    if(mark === null) delete v[kind];
    else v[kind] = mark;
    if(Object.keys(v).length) ov.verdicts = v; else delete ov.verdicts;
    writeOverride(id, ov);
  }

  function applyKindVerdict(block, verdict){
    var wrap = block.querySelector('.kb-verdict');
    if(!wrap) return;
    wrap.querySelectorAll('button').forEach(function(b){
      b.classList.toggle('on', b.getAttribute('data-v') === verdict);
    });
  }

  // ── Per-block verdict buttons inside Where/Why/How block headers ──
  function wireKindBlockVerdicts(card){
    var id = card.getAttribute('data-highlight-id');
    card.querySelectorAll('.kind-block[data-kind]').forEach(function(block){
      if(block._verdictWired) return;
      block._verdictWired = true;
      var kind = block.getAttribute('data-kind');
      var wrap = block.querySelector('.kb-verdict');
      if(!wrap) return;
      wrap.addEventListener('mousedown', function(e){ e.stopPropagation(); });
      wrap.addEventListener('click', function(e){
        e.stopPropagation(); e.preventDefault();
        var btn = e.target.closest('button'); if(!btn) return;
        var mark = btn.getAttribute('data-v');
        var current = ((state.overrides[id] || {}).verdicts || {})[kind] || null;
        var next = current === mark ? null : mark;
        setKindVerdict(id, kind, next);
        applyKindVerdict(block, next);
        if(next) card._hadVerdicts = true;
        markDirty();
      });
    });
  }

  function applyAllKindVerdicts(card, ov){
    var hasV = ov && ov.verdicts && Object.keys(ov.verdicts).length;
    if(!hasV && !card._hadVerdicts) return;
    card._hadVerdicts = !!hasV;
    card.querySelectorAll('.kind-block[data-kind]').forEach(function(block){
      var kind = block.getAttribute('data-kind');
      var v = (ov && ov.verdicts && ov.verdicts[kind]) || null;
      applyKindVerdict(block, v);
    });
  }

  // ── Auto L1/L2/L3 badge (derived from highlight-id prefix) ──
  var TIER_MAP = {txt:'L1', vis:'L1', ref:'L1', claim:'L1',
                  code:'L2', theory:'L2', prior:'L2', exp:'L2',
                  plan:'L3'};
  function attachTierBadge(card){
    if(card.querySelector('.tier-badge')) return;
    var id = card.getAttribute('data-highlight-id') || '';
    var prefix = id.split('-')[0];
    var tier = TIER_MAP[prefix];
    if(!tier) return;
    var span = document.createElement('span');
    span.className = 'tier-badge tier-' + tier.toLowerCase();
    span.textContent = tier;
    var status = card.querySelector('.finding-status');
    if(status) card.insertBefore(span, status);
    else card.insertBefore(span, card.firstChild);
  }

  function applyAll(){
    document.querySelectorAll('.finding-card[data-highlight-id]').forEach(applyCard);
    document.querySelectorAll('.pdf-hl.human-hl').forEach(function(el){ el.remove(); });
    state.new_highlights.forEach(placeHumanHighlight);
    document.querySelectorAll('textarea.card-comment-input[data-comment-key]').forEach(applyCardComment);
    renderTierBars();
  }

  // ── L1/L2/L3 human-verdict bars (3 horizontal bars; hidden when zero verdicts) ──
  function tierFromCardId(id){
    var prefix = (id || '').split('-')[0];
    return TIER_MAP[prefix] || null;
  }
  function renderTierBars(){
    var box = document.getElementById('tierVerdictChart');
    var body = document.getElementById('tierVerdictBody');
    if(!box || !body) return;
    var counts = {L1:{ok:0,doubt:0,bad:0}, L2:{ok:0,doubt:0,bad:0}, L3:{ok:0,doubt:0,bad:0}};
    var total = 0;
    Object.keys(state.overrides || {}).forEach(function(id){
      var tier = tierFromCardId(id);
      if(!tier) return;
      var verdicts = (state.overrides[id] || {}).verdicts || {};
      Object.keys(verdicts).forEach(function(kind){
        var v = verdicts[kind];
        if(v === 'ok' || v === 'doubt' || v === 'bad'){
          counts[tier][v] += 1;
          total += 1;
        }
      });
    });
    if(total === 0){ box.hidden = true; return; }
    box.hidden = false;
    var SEG_COLORS = {ok:'#10b981', doubt:'#f59e0b', bad:'#ef4444'};
    body.innerHTML = ['L1','L2','L3'].map(function(t){
      var c = counts[t];
      var sum = c.ok + c.doubt + c.bad;
      var badge = '<span class="tier-badge tier-' + t.toLowerCase() + '">' + t + '</span>';
      var segs = '';
      if(sum > 0){
        var p = function(n){ return (n/sum*100).toFixed(2) + '%'; };
        if(c.ok)    segs += '<div class="seg seg-ok"    style="width:'+p(c.ok)+'"></div>';
        if(c.doubt) segs += '<div class="seg seg-doubt" style="width:'+p(c.doubt)+'"></div>';
        if(c.bad)   segs += '<div class="seg seg-bad"   style="width:'+p(c.bad)+'"></div>';
      }
      var metaParts = ['ok','doubt','bad'].map(function(v){
        var n = c[v];
        var zeroCls = n === 0 ? ' cnt-zero' : '';
        return '<span class="cnt' + zeroCls + '"><span class="legend-dot" style="background:'
          + SEG_COLORS[v] + '"></span>' + n + '</span>';
      }).join('');
      return '<div class="tier-block">'
        + '<div class="tier-bar">' + segs + '</div>'
        + '<div class="tier-meta">' + badge + metaParts + '</div>'
        + '</div>';
    }).join('');
  }

  // ── Card-level free-form notes textarea ──
  function applyCardComment(ta){
    var key = ta.getAttribute('data-comment-key') || '';
    if(!key) return;
    var saved = ((state.overrides[key] || {}).comment) || '';
    if(ta.value !== saved) ta.value = saved;
    if(ta._wired) return;
    ta._wired = true;
    ta.addEventListener('input', function(){
      var ov = Object.assign({}, state.overrides[key] || {});
      var v = (ta.value || '');
      if(v.trim() === '') delete ov.comment; else ov.comment = v;
      writeOverride(key, ov);
      markDirty();
    });
    ta.addEventListener('mousedown', function(e){ e.stopPropagation(); });
    ta.addEventListener('click',     function(e){ e.stopPropagation(); });
  }

  // Field-content helpers that ignore the absolutely-positioned .field-btns child,
  // so setting/reading a field's text never wipes or includes the ✓✗? buttons.
  function _fieldOwnText(el){
    var t = '';
    Array.from(el.childNodes).forEach(function(n){
      if(n.nodeType === 1 && n.classList && n.classList.contains('field-btns')) return;
      t += (n.nodeType === 1 && n.tagName === 'BR') ? '\n' : (n.textContent || '');
    });
    return t;
  }
  function _setFieldOwnText(el, text){
    var btns = el.querySelector(':scope > .field-btns');
    Array.from(el.childNodes).forEach(function(n){ if(n !== btns) n.remove(); });
    if(text !== ''){
      var tn = document.createTextNode(text);
      if(btns) el.insertBefore(tn, btns); else el.appendChild(tn);
    }
  }

  function applyCard(card){
    if(typeof card === 'string') card = getCard(card);
    if(!card) return;
    initCard(card);
    var id = card.getAttribute('data-highlight-id');
    var ov = state.overrides[id] || {};
    resetCardVisuals(card);
    if(ov.status) applyStatusOverride(card, ov.status);
    applyFieldOverrides(card, ov.fields || {}, ov.marks || {});
    applyAllKindVerdicts(card, ov);
    var hasVerdict = ov.verdicts && Object.keys(ov.verdicts).length > 0;
    if(ov.status || ov.comment || (ov.fields && Object.keys(ov.fields).length) || (ov.marks && Object.keys(ov.marks).length) || hasVerdict){
      card.classList.add('human-override');
    }
  }

  function resetCardVisuals(card){
    card.classList.remove('human-override');
    card.querySelectorAll('.human-tag').forEach(function(el){ el.remove(); });
    var orig = card.getAttribute('data-original-status');
    if(orig) setStatusClass(card, orig);
    Object.keys(card._fieldEls).forEach(function(key){
      var el = card._fieldEls[key];
      el.classList.remove('human-edited','field-ok','field-bad','field-doubt');
      var t = el.getAttribute('data-orig-text');
      if(t !== null && _fieldOwnText(el) !== t) _setFieldOwnText(el, t);
    });
  }

  var CANONICAL_STATUS = __CANONICAL_STATUS__;
  var _CANONICAL_SET = Object.fromEntries(CANONICAL_STATUS.map(function(s){ return [s,1]; }));
  function canonStatus(s){ return _CANONICAL_SET[s] ? s : 'blocked'; }
  function setStatusClass(card, status){
    var st = canonStatus(status);
    CANONICAL_STATUS.forEach(function(c){ card.classList.remove('status-' + c); });
    card.classList.add('status-' + st);
    var sEl = card.querySelector('.finding-status');
    if(sEl){ sEl.className = 'finding-status ' + st; sEl.textContent = cap(st); }
  }

  function applyStatusOverride(card, newStatus){
    if(!card.getAttribute('data-original-status')){
      var m = (card.className.match(/status-(\w+)/) || [])[1];
      if(m) card.setAttribute('data-original-status', m);
    }
    setStatusClass(card, newStatus);
    card.classList.add('human-override');
    addTag(card, newStatus, 'HUMAN: ' + newStatus.toUpperCase());
  }

  function addTag(card, kind, text){
    var tag = document.createElement('span');
    tag.className = 'human-tag h-' + kind;
    tag.textContent = text;
    var anchor = card.querySelector('.finding-status') || card.firstChild;
    if(anchor && anchor.nextSibling) card.insertBefore(tag, anchor.nextSibling);
    else card.appendChild(tag);
  }

  // ── State mutators ────────────────────────────────────────────────
  function setStatus(id, newStatus){
    var ov = Object.assign({}, state.overrides[id] || {});
    if(newStatus) ov.status = newStatus; else delete ov.status;
    writeOverride(id, ov);
    applyCard(id);
    markDirty();
  }
  function setFieldMark(id, field, mark){
    var ov = Object.assign({}, state.overrides[id] || {});
    var marks = Object.assign({}, ov.marks || {});
    if(mark) marks[field] = mark; else delete marks[field];
    if(Object.keys(marks).length === 0) delete ov.marks; else ov.marks = marks;
    writeOverride(id, ov);
    applyCard(id);
    markDirty();
  }
  function setFieldValue(id, field, value){
    var ov = Object.assign({}, state.overrides[id] || {});
    var fields = Object.assign({}, ov.fields || {});
    if(value == null || value === '') delete fields[field];
    else fields[field] = value;
    if(Object.keys(fields).length === 0) delete ov.fields;
    else ov.fields = fields;
    writeOverride(id, ov);
    applyCard(id);
    markDirty();
  }

  // ── Status picker ─────────────────────────────────────────────────
  function wireStatusPickerTrigger(card){
    var sEl = card.querySelector('.finding-status');
    if(!sEl) return;
    sEl.title = 'Click to change status';
    sEl.addEventListener('click', function(e){
      e.stopPropagation();
      openStatusPicker(sEl, card.getAttribute('data-highlight-id'));
    });
  }
  function openStatusPicker(anchor, id){
    closeAllPickers();
    var current = (state.overrides[id] || {}).status || null;
    var pp = document.createElement('div');
    pp.className = 'status-picker';
    pp.innerHTML =
      CANONICAL_STATUS.map(function(s){
        return '<button data-s="'+s+'" class="'+(current===s?'current':'')+'">'+cap(s)+'</button>';
      }).join('') +
      '<div class="sep"></div>' +
      '<button class="reset" data-s="">Reset to AI default</button>';
    document.body.appendChild(pp);
    var r = anchor.getBoundingClientRect();
    pp.style.left = r.left + 'px';
    pp.style.top  = (r.bottom + 2) + 'px';
    function close(){ pp.remove(); document.removeEventListener('mousedown', onOutside, true); }
    function onOutside(ev){ if(!pp.contains(ev.target) && ev.target !== anchor) close(); }
    pp.addEventListener('click', function(e){
      var btn = e.target.closest('button'); if(!btn) return;
      setStatus(id, btn.getAttribute('data-s') || null);
      close();
    });
    setTimeout(function(){ document.addEventListener('mousedown', onOutside, true); }, 0);
  }
  function closeAllPickers(){
    document.querySelectorAll('.status-picker').forEach(function(el){ el.remove(); });
  }

  // ── Per-field verdict buttons (✓ / ✗ / ?) ────────────────────────
  function attachFieldButtons(card, field, el, currentMark){
    var wrap = el.querySelector(':scope > .field-btns');
    if(!wrap){
      wrap = document.createElement('span');
      wrap.className = 'field-btns';
      wrap.innerHTML = FIELD_BTNS.map(function(b){
        return '<button type="button" class="fb-'+b.mark+'" data-mark="'+b.mark+'" title="'+b.title+'">'+b.symbol+'</button>';
      }).join('');
      // Swallow mouse events so the parent field-editor click handler doesn't fire
      wrap.addEventListener('mousedown', function(e){ e.stopPropagation(); e.preventDefault(); });
      wrap.addEventListener('click', function(e){
        var btn = e.target.closest('button'); if(!btn) return;
        e.stopPropagation(); e.preventDefault();
        var id = card.getAttribute('data-highlight-id');
        var mark = btn.getAttribute('data-mark');
        var cur = ((state.overrides[id] || {}).marks || {})[field];
        setFieldMark(id, field, cur === mark ? null : mark);
      });
      el.appendChild(wrap);
    }
    wrap.querySelectorAll('button').forEach(function(b){
      b.classList.toggle('on', b.getAttribute('data-mark') === currentMark);
    });
  }

  // ── Field element resolution (cached per card) ───────────────────
  function resolveFieldEls(card){
    if(card._fieldEls) return card._fieldEls;
    var out = {};
    FIELD_DEFS.forEach(function(def){
      var el = findOrWrapDetailValue(card, def.label);
      if(el) out[def.key] = el;
    });
    card._fieldEls = out;
    return out;
  }
  function findOrWrapDetailValue(card, labelText){
    var rows = card.querySelectorAll('.detail-row');
    for(var i = 0; i < rows.length; i++){
      var labelEl = rows[i].querySelector('.detail-label');
      if(!labelEl) continue;
      // Match the trailing word so emoji-prefixed labels (e.g. "📍 Quote") still resolve.
      var t = labelEl.textContent.trim().toLowerCase();
      if(t !== labelText && !t.endsWith(' ' + labelText)) continue;
      var valEl = rows[i].querySelector('.detail-val');
      if(valEl) return valEl;
      valEl = document.createElement('span');
      valEl.className = 'detail-val';
      var quoteInside = rows[i].querySelector('.detail-quote');
      if(quoteInside){
        // Preserve the quote styling so edits still look quoted
        valEl.className += ' detail-quote';
        valEl.textContent = quoteInside.textContent;
        quoteInside.remove();
      } else {
        // Collapse remaining inline content (text nodes + <br>) into one text span
        var text = '';
        Array.from(rows[i].childNodes).forEach(function(n){
          if(n === labelEl) return;
          text += (n.nodeType === 1 && n.tagName === 'BR') ? '\n' : (n.textContent || '');
          if(n !== labelEl) n.remove();
        });
        valEl.textContent = text.trim();
      }
      rows[i].appendChild(valEl);
      return valEl;
    }
    return null;
  }

  function applyFieldOverrides(card, fields, marks){
    marks = marks || {};
    Object.keys(card._fieldEls).forEach(function(key){
      var el = card._fieldEls[key];
      if(fields && (key in fields)){
        _setFieldOwnText(el, fields[key]);
        el.classList.add('human-edited');
      } else {
        el.classList.remove('human-edited');
      }
      var m = marks[key] || null;
      if(m) el.classList.add('field-' + m);
    });
  }

  function wireFieldEditor(card, field, el){
    el.classList.add('editable-field');
    el.setAttribute('data-field', field);
    el.setAttribute('title', 'Click to edit');
    el.addEventListener('click', function(e){
      if(e.target.closest('.field-btns')) return;
      if(el.querySelector('textarea')) return;
      e.stopPropagation(); e.preventDefault();
      startFieldEdit(card, field, el);
    });
  }

  function startFieldEdit(card, field, el){
    var id = card.getAttribute('data-highlight-id');
    var current = _fieldOwnText(el);
    var orig = el.getAttribute('data-orig-text') || '';
    var ta = document.createElement('textarea');
    ta.className = 'inline-edit';
    ta.value = current;
    _setFieldOwnText(el, '');  // clears non-button children, preserves .field-btns
    el.appendChild(ta);
    ta.focus();
    ta.setSelectionRange(ta.value.length, ta.value.length);
    ta.style.height = Math.max(40, ta.scrollHeight) + 'px';
    ta.addEventListener('input', function(){
      ta.style.height = 'auto';
      ta.style.height = ta.scrollHeight + 'px';
    });
    var committed = false;
    function commit(){
      if(committed) return; committed = true;
      var val = ta.value;
      setFieldValue(id, field, (val === orig || val.trim() === '') ? null : val);
    }
    ta.addEventListener('blur', commit);
    ta.addEventListener('keydown', function(e){
      if(e.key === 'Escape'){ e.preventDefault(); committed = true; applyCard(id); }
      if((e.ctrlKey || e.metaKey) && e.key === 'Enter'){ e.preventDefault(); ta.blur(); }
    });
  }

  function placeHumanHighlight(h){
    var page = document.querySelector('.pdf-page[data-page="' + h.page + '"]');
    if(!page) return;
    var el = document.createElement('div');
    el.className = 'pdf-hl human-hl hl-' + h.color;
    el.setAttribute('data-human-hl-id', h.id);
    el.style.left   = (h.box_pct[0] * 100) + '%';
    el.style.top    = (h.box_pct[1] * 100) + '%';
    el.style.width  = ((h.box_pct[2] - h.box_pct[0]) * 100) + '%';
    el.style.height = ((h.box_pct[3] - h.box_pct[1]) * 100) + '%';
    el.innerHTML = '<div class="hh-mark">H</div><div class="pdf-hl-tooltip">' + esc(h.comment || 'human') + '</div>';
    el.addEventListener('click', function(e){
      e.stopPropagation();
      if(confirm('Delete this human highlight?\n\n' + (h.comment || '(no comment)'))){
        state.new_highlights = state.new_highlights.filter(function(x){ return x.id !== h.id; });
        el.remove();
        markDirty();
      }
    });
    page.appendChild(el);
  }

  function installPdfHint(){
    document.querySelectorAll('.pdf-page').forEach(function(p){
      if(p.querySelector('.pdf-hint')) return;
      var hint = document.createElement('div');
      hint.className = 'pdf-hint';
      hint.textContent = 'Shift+drag to highlight';
      p.appendChild(hint);
    });
  }
  var drawStart = null, drawEl = null;
  document.addEventListener('mousedown', function(e){
    if(!e.shiftKey) return;
    var page = e.target.closest && e.target.closest('.pdf-page');
    if(!page) return;
    if(e.target.closest('.pdf-hl') || e.target.closest('.new-hl-popup')) return;
    var rect = page.getBoundingClientRect();
    drawStart = { page:page, x0:e.clientX - rect.left, y0:e.clientY - rect.top };
    drawEl = document.createElement('div');
    drawEl.className = 'draw-box';
    drawEl.style.left = drawStart.x0 + 'px';
    drawEl.style.top = drawStart.y0 + 'px';
    page.appendChild(drawEl);
    document.body.classList.add('drawing');
    e.preventDefault();
  });
  document.addEventListener('mousemove', function(e){
    if(!drawStart || !drawEl) return;
    var rect = drawStart.page.getBoundingClientRect();
    var x = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    var y = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
    drawEl.style.left = Math.min(drawStart.x0, x) + 'px';
    drawEl.style.top = Math.min(drawStart.y0, y) + 'px';
    drawEl.style.width = Math.abs(x - drawStart.x0) + 'px';
    drawEl.style.height = Math.abs(y - drawStart.y0) + 'px';
  });
  document.addEventListener('mouseup', function(e){
    if(!drawStart || !drawEl) return;
    var rect = drawStart.page.getBoundingClientRect();
    var x1 = Math.max(0, Math.min(rect.width, e.clientX - rect.left));
    var y1 = Math.max(0, Math.min(rect.height, e.clientY - rect.top));
    var x0 = drawStart.x0, y0 = drawStart.y0;
    var w = Math.abs(x1 - x0), h = Math.abs(y1 - y0);
    var page = drawStart.page;
    var pageNum = parseInt(page.getAttribute('data-page'));
    drawEl.remove(); drawEl = null;
    drawStart = null;
    document.body.classList.remove('drawing');
    if(w < 5 || h < 5) return;
    var box_pct = [
      Math.min(x0, x1) / rect.width,
      Math.min(y0, y1) / rect.height,
      Math.max(x0, x1) / rect.width,
      Math.max(y0, y1) / rect.height
    ];
    showNewHighlightPopup(e.clientX, e.clientY, pageNum, box_pct);
  });

  function showNewHighlightPopup(mx, my, page, box_pct){
    var color = 'warning';
    var pop = document.createElement('div');
    pop.className = 'new-hl-popup';
    pop.style.left = Math.min(mx, window.innerWidth - 280) + 'px';
    pop.style.top = Math.min(my, window.innerHeight - 220) + 'px';
    pop.innerHTML =
      '<h4>Page ' + page + ' highlight</h4>' +
      '<div class="color-row">' +
        '<button class="h-pass">pass</button>' +
        '<button class="h-warning selected">warning</button>' +
        '<button class="h-error">error</button>' +
      '</div>' +
      '<textarea placeholder="comment (optional)"></textarea>' +
      '<div class="actions">' +
        '<button class="cancel">Cancel</button>' +
        '<button class="save">Save</button>' +
      '</div>';
    pop.addEventListener('click', function(e){ e.stopPropagation(); });
    pop.querySelectorAll('.color-row button').forEach(function(b){
      b.onclick = function(){
        pop.querySelectorAll('.color-row button').forEach(function(x){ x.classList.remove('selected'); });
        b.classList.add('selected');
        color = b.classList.contains('h-pass') ? 'pass' : b.classList.contains('h-error') ? 'error' : 'warning';
      };
    });
    function close(){ pop.remove(); document.removeEventListener('mousedown', onOutside, true); }
    function onOutside(ev){ if(!pop.contains(ev.target)) close(); }
    pop.querySelector('.cancel').onclick = close;
    pop.querySelector('.save').onclick = function(){
      state.new_highlights.push({
        id: 'h-' + Date.now(), page: page, box_pct: box_pct,
        color: color, comment: pop.querySelector('textarea').value
      });
      close();
      applyAll();
      markDirty();
    };
    document.body.appendChild(pop);
    setTimeout(function(){ document.addEventListener('mousedown', onOutside, true); }, 0);
  }

  async function install(){
    document.addEventListener('keydown', function(e){
      if(e.key === 'Escape'){
        closeAllPickers();
      }
    });
    state = defaultState(state);
    try {
      var cached = localStorage.getItem(STORAGE_KEY);
      if(cached){
        state = defaultState(JSON.parse(cached));
      }
    } catch(e){}
    try {
      var storedHandle = await loadStoredDirHandle();
      if(storedHandle && storedHandle.kind === 'directory'){
        _boundDirHandle = storedHandle;
      }
    } catch(e){}
    state = pickNewerState(state, await loadAnnotationsFromBoundFolder());
    save();
    installPdfHint();
    applyAll();
    updateSaveUi();
  }
  function ready(tries){
    tries = tries || 0;
    if(document.querySelectorAll('.pdf-page').length === 0){
      if(tries > 60) return;
      return setTimeout(function(){ ready(tries + 1); }, 50);
    }
    install();
  }
  if(document.readyState === 'loading') document.addEventListener('DOMContentLoaded', ready);
  else ready();
})();
</script>
"""

_ARGPARSER = argparse.ArgumentParser(description="Generate vis-preview paperdoctor.html")
_ARGPARSER.add_argument("paper_dir", help="Path to paper directory (e.g. papers/showui)")
_ARGPARSER.add_argument("--pdf", default=None,
                        help="Path to the main PDF (defaults to first *.pdf in paper_dir)")

def resolve_pdf(paper_dir, override):
    if override:
        p = Path(override)
        if not p.is_absolute() and not p.exists():
            p = paper_dir / p
        p = p.resolve()
        if not p.exists():
            _ARGPARSER.error(f"--pdf path not found: {override}")
        return p
    pdfs = sorted(paper_dir.glob("*.pdf"))
    if not pdfs:
        _ARGPARSER.error(f"No PDF found in {paper_dir} (pass --pdf to override)")
    return pdfs[0]

def detect_title(pdf_path, fallback):
    """Read the title from PDF metadata; fall back to the first large-font line on page 1."""
    try:
        import fitz
        doc = fitz.open(str(pdf_path))
        meta = doc.metadata
        if meta and meta.get("title") and len(meta["title"].strip()) > 3:
            title = meta["title"].strip()
            doc.close()
            return title
        page = doc[0]
        blocks = page.get_text("dict")["blocks"]
        best, best_size = "", 0
        skip_patterns = ["arxiv:", "preprint", "[cs.", "[stat.", "[math.", "[eess."]
        for b in blocks:
            for line in b.get("lines", []):
                spans = line.get("spans", [])
                if not spans:
                    continue
                max_size = max(s["size"] for s in spans)
                full_text = "".join(s["text"] for s in spans).strip()
                if len(full_text) < 5 or any(p in full_text.lower() for p in skip_patterns):
                    continue
                if max_size > best_size:
                    best_size, best = max_size, full_text
        doc.close()
        if best:
            return best
    except Exception:
        pass
    return fallback

def render_pages(pdf_path, pages_dir, dpi=150):
    """Render PDF pages via tools.pdf_render. No-op if pages-NNN.png already exist."""
    if next(pages_dir.glob("page-*.png"), None):
        return
    import importlib.util
    spec = importlib.util.spec_from_file_location("pdf_render", Path(__file__).parent / "pdf_render.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    mod.render_pdf_pages(pdf_path, pages_dir, dpi=dpi)

args = _ARGPARSER.parse_args()
PAPER_DIR = Path(args.paper_dir)
REPORTS = PAPER_DIR / "reports"
DISPLAY = PAPER_DIR / "display"
PDF_PATH = resolve_pdf(PAPER_DIR, args.pdf)
render_pages(PDF_PATH, DISPLAY / "pages")

def load_json(path):
    if path.exists():
        return json.loads(path.read_text())
    return None

# ── Load all data ──
check_claim = load_json(REPORTS / "check_claim.json")
check_txt = load_json(REPORTS / "check_txt.json")
check_vis = load_json(REPORTS / "check_vis.json")
check_bib = load_json(REPORTS / "check_bib.json")
check_code = load_json(REPORTS / "check_code.json")
check_theory = load_json(REPORTS / "check_theory.json")
check_exp = load_json(REPORTS / "check_exp.json")
check_prior = load_json(REPORTS / "check_prior.json")

# ── Auto-generate quote positions from ALL findings ──
def build_all_quotes():
    """Collect quotes from all reports for PDF search."""
    queries = []
    # claims — all extracted claims
    if check_claim:
        for r in check_claim.get("results", []):
            queries.append({"id": f"claim-{r.get('id','')}", "quote": r.get("quote",""), "status": "info"})
    # txt — writing issues (vis-like format, has page field)
    if check_txt:
        for i, r in enumerate(check_txt.get("results", [])):
            queries.append({"id": f"txt-{i}", "quote": r.get("quote",""), "status": r.get("status","warning")})
    # vis — index-based id (multiple issues can share a page)
    if check_vis:
        for i, r in enumerate(check_vis.get("results", [])):
            queries.append({"id": f"vis-{i}", "quote": r.get("quote",""), "status": r.get("status","warning")})
    # bib (warnings/errors only — too many pass items)
    if check_bib:
        for r in check_bib.get("results", []):
            if r.get("status") in ("warning", "error"):
                queries.append({"id": r.get("id",""), "quote": r.get("raw_text","")[:80], "status": r.get("status","warning")})
    # code, theory, exp, prior — ALL items (pass included)
    for report, prefix in [(check_code,"code"), (check_theory,"theory"), (check_exp,"exp"), (check_prior,"prior")]:
        if report:
            for r in report.get("results", []):
                queries.append({"id": f"{prefix}-{r.get('id','')}", "quote": r.get("quote",""), "status": r.get("status","pass")})
    return queries

def run_pdf_search(queries):
    """Run pdf_search on the paper PDF and return results."""
    if not queries:
        return []
    try:
        import sys, importlib.util
        # Import pdf_search from tools/
        tools_dir = Path(__file__).parent
        spec = importlib.util.spec_from_file_location("pdf_search", tools_dir / "pdf_search.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        results = mod.search_pdf(str(PDF_PATH), queries)
        # Save for caching
        out = REPORTS / "quote_positions.json"
        out.write_text(json.dumps(results, indent=2, ensure_ascii=False))
        return results
    except Exception as e:
        print(f"Warning: pdf_search failed: {e}", __import__('sys').stderr)
        # Fallback to cached file
        cached = load_json(REPORTS / "quote_positions.json")
        return cached or []

all_queries = build_all_quotes()
quote_pos_raw = run_pdf_search(all_queries)

# Build quote_pos lookup: id -> {page, bbox, status}
quote_pos = {}
for q in quote_pos_raw:
    if q["matches"]:
        m = q["matches"][0]
        quote_pos[q["id"]] = {
            "page": m["page"],
            "bbox": m["bbox"],
            "status": q.get("status", "warning"),
            "page_width": m.get("page_width"),
            "page_height": m.get("page_height"),
        }
    else:
        quote_pos[q["id"]] = {
            "page": None,
            "bbox": None,
            "status": q.get("status", "warning"),
            "page_width": None,
            "page_height": None,
        }

# Backfill vis items: they always have a known page even if quote search fails
if check_vis:
    for i, r in enumerate(check_vis.get("results", [])):
        hlid = f"vis-{i}"
        if hlid in quote_pos and quote_pos[hlid]["page"] is None:
            quote_pos[hlid]["page"] = r.get("page")

# Backfill txt (writing) items: they have page field like vis
if check_txt:
    for i, r in enumerate(check_txt.get("results", [])):
        hlid = f"txt-{i}"
        if hlid in quote_pos and quote_pos[hlid]["page"] is None and r.get("page"):
            quote_pos[hlid]["page"] = r.get("page")

# ── Canonical status set & normalizer (single source of truth) ──
CANONICAL_STATUS = ("pass", "warning", "error", "blocked")

def normalize_status(s):
    """Any non-canonical status is coerced to 'blocked' (matches the JSON migration)."""
    return s if s in CANONICAL_STATUS else "blocked"

# ── Count statuses across all reports ──
status_counts = {"pass": 0, "warning": 0, "error": 0, "blocked": 0}

def count_report(report, prefix):
    """Extract items with status from a report, return list of (id_str, item_dict)."""
    items = []
    if not report:
        return items
    for r in report.get("results", []):
        st = r.get("status")
        if st is not None:
            status_counts[normalize_status(st)] += 1
        rid = r.get("id", "")
        items.append((f"{prefix}-{rid}", r))
    return items

# Count bib — ids already prefixed as "ref-001", don't add prefix
bib_items = []
if check_bib:
    for r in check_bib.get("results", []):
        st = r.get("status")
        if st is not None:
            status_counts[normalize_status(st)] += 1
        bib_items.append((r.get("id", ""), r))
# Count code
code_items = count_report(check_code, "code")
# Count theory
theory_items = count_report(check_theory, "theory")
# Count exp results
exp_items = count_report(check_exp, "exp")
# Count prior
prior_items = count_report(check_prior, "prior")
# Count vis (these don't have standard status field mapping, handle manually)
vis_items = []
if check_vis:
    for i, r in enumerate(check_vis.get("results", [])):
        st = r.get("status", "warning")
        if st in status_counts:
            status_counts[st] += 1
        vis_items.append((f"vis-{i}", r))

# Count txt (writing issues — same vis-like format with page field)
txt_items = []
if check_txt:
    for i, r in enumerate(check_txt.get("results", [])):
        st = r.get("status", "warning")
        if st in status_counts:
            status_counts[st] += 1
        txt_items.append((f"txt-{i}", r))

total_findings = sum(status_counts.values())

# Filter pass items from verification sections (only show problematic ones).
# L2 sections (code/theory/exp/prior) additionally drop status=blocked: per the
# paper, "blocked" is an L3 reproduction lifecycle state, not an L2 verdict.
# Donut counts (status_counts) above are unchanged — they reflect raw data.
def _filter_displayable(items, drop=("pass",)):
    return [(hid, item) for hid, item in items if item.get("status") not in drop]

_L2_DROP = ("pass", "blocked")
code_items = _filter_displayable(code_items, _L2_DROP)
theory_items = _filter_displayable(theory_items, _L2_DROP)
exp_items = _filter_displayable(exp_items, _L2_DROP)
prior_items = _filter_displayable(prior_items, _L2_DROP)
vis_items = _filter_displayable(vis_items)
txt_items = _filter_displayable(txt_items)

def _bbox_area(b):
    if not b:
        return 0.0
    return max(0.0, float(b[2]) - float(b[0])) * max(0.0, float(b[3]) - float(b[1]))

def _bbox_overlap_ratio(a, b):
    """Intersection divided by the smaller bbox area."""
    if not a or not b:
        return 0.0
    x0 = max(float(a[0]), float(b[0]))
    y0 = max(float(a[1]), float(b[1]))
    x1 = min(float(a[2]), float(b[2]))
    y1 = min(float(a[3]), float(b[3]))
    inter = max(0.0, x1 - x0) * max(0.0, y1 - y0)
    denom = min(_bbox_area(a), _bbox_area(b))
    return inter / denom if denom > 0 else 0.0

def _claim_id_from_child(hl_id):
    """Exact claim parent for id-preserving checks: exp-12 -> claim-12."""
    if "-" not in hl_id:
        return ""
    prefix, suffix = hl_id.split("-", 1)
    if prefix in {"exp", "code", "theory", "prior"} and suffix:
        return f"claim-{suffix}"
    return ""

claim_ids = {f"claim-{r.get('id','')}" for r in check_claim.get("results", [])} if check_claim else set()

visible_child_ids = []
for _items in (txt_items, vis_items, theory_items, prior_items, code_items, exp_items):
    for _hid, _ in _items:
        _q = quote_pos.get(_hid, {})
        if _q.get("page") and _q.get("bbox"):
            visible_child_ids.append(_hid)
for _hid, _item in bib_items:
    if _item.get("status") in ("warning", "error"):
        _q = quote_pos.get(_hid, {})
        if _q.get("page") and _q.get("bbox"):
            visible_child_ids.append(_hid)

claim_parent_by_child = {}
for _child_id in visible_child_ids:
    _parent = _claim_id_from_child(_child_id)
    if _parent in claim_ids:
        claim_parent_by_child[_child_id] = _parent

# Vis/txt findings are index-based rather than claim-id based. Attach them to
# a candidate claim only when their PDF boxes clearly overlap on the same page.
for _child_id in [hid for hid, _ in txt_items + vis_items]:
    if _child_id in claim_parent_by_child:
        continue
    _cq = quote_pos.get(_child_id, {})
    if not (_cq.get("page") and _cq.get("bbox")):
        continue
    _best_parent = ""
    _best_score = 0.0
    for _claim_id in claim_ids:
        _pq = quote_pos.get(_claim_id, {})
        if _pq.get("page") != _cq.get("page") or not _pq.get("bbox"):
            continue
        _score = _bbox_overlap_ratio(_cq["bbox"], _pq["bbox"])
        if _score > _best_score:
            _best_parent = _claim_id
            _best_score = _score
    if _best_parent and _best_score >= 0.35:
        claim_parent_by_child[_child_id] = _best_parent

claim_children = {}
for _child_id, _parent_id in claim_parent_by_child.items():
    claim_children.setdefault(_parent_id, []).append(_child_id)

# Candidate claims covered by more specific visible findings become parent
# anchors only: they stay in HIGHLIGHTS for right-panel navigation, but they do
# not get their own PDF badge/overlay by default.
covered_claim_ids = set(claim_children)

# ── Collect highlights for permanent display on PDF.
#
# Verification passes are omitted to keep the PDF readable. Candidate claims
# that have visible child checks are also omitted from the PDF overlay so the
# actionable child finding owns the click target.
all_highlights = []
for qid, qdata in quote_pos.items():
    if qid in covered_claim_ids:
        continue
    if qdata["page"] and qdata["bbox"] and qdata["status"] != "pass":
        all_highlights.append({
            "id": qid,
            "page": qdata["page"],
            "bbox": qdata["bbox"],
            "status": qdata["status"],
            "page_width": qdata.get("page_width"),
            "page_height": qdata.get("page_height"),
        })

# Group by page
highlights_by_page = {}
for h in all_highlights:
    highlights_by_page.setdefault(h["page"], []).append(h)

# Sequential display numbers, one per finding card AND matching PDF highlight.
# We only number cards that actually get rendered as a PDF highlight (page +
# bbox known, status != "pass") so the right-panel `#NN` pills correspond
# 1:1 with the badges on the left-hand PDF — no orphan numbers.
_highlighted_ids = {h["id"] for h in all_highlights}

hl_numbers = {}

def _assign(hl_id):
    if hl_id in _highlighted_ids and hl_id not in hl_numbers:
        hl_numbers[hl_id] = len(hl_numbers) + 1

if check_claim:
    for _r in check_claim.get("results", []):
        _assign(f"claim-{_r.get('id','')}")
for _hid, _ in txt_items:
    _assign(_hid)
for _hid, _ in vis_items:
    _assign(_hid)
for _hid, _ in theory_items:
    _assign(_hid)
for _hid, _ in prior_items:
    _assign(_hid)
for _hid, _ in code_items:
    _assign(_hid)
for _hid, _ in exp_items:
    _assign(_hid)
for _hid, _item in bib_items:
    if _item.get("status") in ("warning", "error"):
        _assign(_hid)

# ── Helper functions ──
E = html_mod.escape

def seq_pill(hl_id, extra_cls=""):
    """Sequential `#NN` pill matching the PDF badge. Trailing space baked in
    so callers can concatenate without juggling whitespace."""
    n = hl_numbers.get(hl_id)
    if not n:
        return ''
    cls = f'finding-id {extra_cls}'.rstrip()
    return f'<span class="{cls}">#{n}</span> '

def render_detail_row(label, value):
    if not value:
        return ""
    if isinstance(value, list):
        if all(isinstance(v, str) and v.startswith("http") for v in value):
            links = " ".join(f'<a href="{E(v)}" target="_blank" style="color:#3b82f6;word-break:break-all;">{E(v)}</a>' for v in value)
            return f'<div class="detail-row"><span class="detail-label">{E(label)}</span>{links}</div>'
        value = ", ".join(str(v) for v in value)
    if isinstance(value, str) and value.startswith("http"):
        return f'<div class="detail-row"><span class="detail-label">{E(label)}</span><a href="{E(value)}" target="_blank" style="color:#3b82f6;word-break:break-all;">{E(value)}</a></div>'
    return f'<div class="detail-row"><span class="detail-label">{E(label)}</span>{E(str(value))}</div>'

# Single source of truth for the 3 finding-triple labels (with emoji).
LABEL = {"quote": "📍 Quote", "reason": "🔍 Reason", "suggest": "✏️ Suggestion"}

def render_quote_row(value):
    if not value:
        return ""
    return f'<div class="detail-row"><span class="detail-label">{LABEL["quote"]}</span><span class="detail-quote">{E(str(value))}</span></div>'

def render_card_comment(key):
    """Free-form per-card note textarea, persisted to state.overrides[key].comment."""
    return (
        f'<div class="card-comment">'
        f'<label class="card-comment-label">Your comments</label>'
        f'<textarea class="card-comment-input" data-comment-key="{E(key)}" '
        f'placeholder="Add your comments here..." spellcheck="false"></textarea>'
        f'</div>'
    )

def section_pill(source):
    if not source:
        return ""
    return f' <span class="finding-source"><strong>Section:</strong> {E(source)}</span>'

_KIND_VERDICT_BTNS = (
    '<span class="kb-verdict">'
    '<button type="button" class="cv-ok" data-v="ok" title="Correct">&#10003;&#xFE0E;</button>'
    '<button type="button" class="cv-bad" data-v="bad" title="Wrong">&#10007;&#xFE0E;</button>'
    '<button type="button" class="cv-doubt" data-v="doubt" title="Uncertain">?</button>'
    '</span>'
)

def render_kind_block(kind, rows):
    """Wrap rows into a labeled Where/Why/How block. Why/How get verdict buttons;
    Where is just an evidence pointer and not a judgment surface."""
    if not rows:
        return ""
    label = {"where": "Where", "why": "Why", "how": "How"}[kind]
    inner = "\n".join(rows)
    btns = _KIND_VERDICT_BTNS if kind in ("why", "how") else ""
    return (
        f'<div class="kind-block kb-{kind}" data-kind="{kind}">'
        f'<div class="kb-header"><span class="kb-label">{label}</span>{btns}</div>'
        f'<div class="kb-body">{inner}</div>'
        f'</div>'
    )

def render_detail_blocks(context=(), where=(), why=(), how=()):
    return (
        "\n".join(context)
        + render_kind_block("where", list(where))
        + render_kind_block("why", list(why))
        + render_kind_block("how", list(how))
    )




def render_finding_card(hl_id, item, report_type):
    """Render a single finding card with full expandable detail."""
    st = normalize_status(item.get("status", "warning"))
    quote = item.get("quote", item.get("raw_text", ""))
    source = item.get("source", "")
    claim = item.get("claim", "")
    reason = item.get("reason", "")
    evidence_type = item.get("evidence_type", "")
    suggest = item.get("suggest", "")
    raw_text = item.get("raw_text", "")
    page = item.get("page", "")

    code_ref_attr = ""
    if report_type == "code" and isinstance(quote, str):
        m = CODE_REF_RX.match(quote)
        if m:
            code_ref_attr = f' data-code-ref="{E(m.group(0).lstrip())}"'

    if report_type == "bib":
        tail = f'<strong>{E(str(item.get("id","")))}</strong>'
    elif report_type == "vis":
        tail = f'<strong>Page {page}</strong>'
    elif report_type == "txt":
        tail = ''
    else:
        # theory / code / exp / prior verify a source claim — the parent
        # .finding-card carries .status-{st}, so the inner pill picks up the
        # status color automatically.
        cid = item.get("id", "")
        tail = f'<span class="finding-id">Claim {E(str(cid))}</span>' if cid else ''
        tail += section_pill(source)
    title = seq_pill(hl_id) + tail

    # Quote display
    if isinstance(quote, list):
        quote_str = ", ".join(quote)
    else:
        quote_str = str(quote)

    context_rows, where_rows, why_rows, how_rows = [], [], [], []
    if report_type == "bib" and raw_text:
        context_rows.append(render_detail_row("Citation", raw_text))
    if claim and report_type != "vis":
        context_rows.append(render_detail_row("Claim", claim))
    if evidence_type:
        context_rows.append(render_detail_row("Evidence type", evidence_type))
    if report_type != "bib" and quote_str:
        where_rows.append(render_quote_row(quote_str))
    if reason:
        why_rows.append(render_detail_row(LABEL["reason"], reason))
    if suggest:
        how_rows.append(render_detail_row(LABEL["suggest"], suggest))
    details_html = render_detail_blocks(context_rows, where_rows, why_rows, how_rows)

    return f'''<div class="finding-card status-{st}" data-highlight-id="{E(hl_id)}"{code_ref_attr}>
  <span class="finding-status {st}">{E(st.capitalize())}</span>
  {title}
  <div class="detail-body">
    {details_html}
    {render_card_comment(hl_id)}
  </div>
</div>'''


# ── Build the donut chart SVG ──
import math
circumference = 2 * math.pi * 60  # r=60

def donut_segments():
    segments = []
    order = ["pass", "warning", "error", "blocked"]
    colors = {"pass":"#10b981","warning":"#f59e0b","error":"#ef4444","blocked":"#3b82f6"}
    offset = 0
    for key in order:
        count = status_counts[key]
        if count == 0:
            continue
        arc = (count / total_findings) * circumference
        gap = circumference - arc
        segments.append(f'''<circle cx="80" cy="80" r="60" fill="none" stroke="{colors[key]}" stroke-width="22"
  stroke-dasharray="{arc:.2f} {gap:.2f}" stroke-dashoffset="{-offset:.2f}" transform="rotate(-90 80 80)" />''')
        offset += arc
    return "\n".join(segments)

legend_items = []
for key, color in [("pass","#10b981"),("warning","#f59e0b"),("error","#ef4444"),("blocked","#3b82f6")]:
    if status_counts[key] > 0:
        legend_items.append(f'<div class="legend-item"><div class="legend-dot" style="background:{color}"></div> {E(key.title())} <strong>{status_counts[key]}</strong></div>')


# ── Build code tree HTML ──
code_index = load_json(PAPER_DIR / "metadata" / "code" / "index.json")
total_files = code_index.get("total_files", 0) if code_index else 0

# ── Auto-detect paper title and page count ──
paper_title = detect_title(PDF_PATH, fallback=PAPER_DIR.name)
num_pages = len(list((DISPLAY / "pages").glob("page-*.png"))) if (DISPLAY / "pages").exists() else 0

# ── Build code tree data from index.json ──
def build_tree_js(code_index):
    """Convert index.json files list into a nested JS tree structure."""
    if not code_index or "files" not in code_index:
        return "[]"
    # Build tree from flat file list. Leaves carry the full path so the JS
    # click handler can look the content up in CODE_FILES at runtime.
    tree = {}
    for f in code_index["files"]:
        parts = f["file_path"].split("/")
        node = tree
        for part in parts[:-1]:
            node = node.setdefault(part + "/", {})
        fname = parts[-1]
        meta = ""
        loc = f.get("lines_of_code", 0)
        if loc > 100:
            meta = f"{loc} lines"
        node[fname] = {"path": f["file_path"], "meta": meta}

    def to_node(name, val):
        if isinstance(val, dict) and "path" not in val:
            children = [to_node(k, v) for k, v in sorted(val.items(), key=lambda x: (not x[0].endswith("/"), x[0]))]
            return {"name": name, "type": "dir", "children": children}
        return {"name": name, "type": "file", "path": val["path"], **({"meta": val["meta"]} if val["meta"] else {})}

    roots = [to_node(k, v) for k, v in sorted(tree.items(), key=lambda x: (not x[0].endswith("/"), x[0]))]
    return json.dumps(roots, ensure_ascii=False)

code_tree_js = build_tree_js(code_index)

CODE_ROOT = PAPER_DIR / "code"

# ── Single source of truth: file extension → hljs language ──
# Driven from one dict so the Python "what to inline" filter and the JS
# "highlight as which language" lookup never drift apart.
EXT_LANG = {
    ".py":"python", ".sh":"bash", ".bash":"bash",
    ".json":"json", ".yaml":"yaml", ".yml":"yaml",
    ".md":"markdown", ".js":"javascript", ".ts":"typescript",
    ".css":"css", ".html":"xml", ".xml":"xml",
    ".toml":"ini", ".cfg":"ini", ".ini":"ini", ".conf":"ini",
    ".cu":"cpp", ".h":"cpp", ".hpp":"cpp", ".c":"c", ".cpp":"cpp",
    ".txt":"plaintext", ".rst":"plaintext", ".tex":"plaintext",
    ".bib":"plaintext", ".csv":"plaintext", ".tsv":"plaintext",
    ".lock":"plaintext",
}
MAX_INLINE_SIZE = 1_000_000  # 1 MB per file safety cap

# Inline all text-file contents so tree clicks work on file:// too.
code_files = {}
if code_index and "files" in code_index and CODE_ROOT.exists():
    for f in code_index["files"]:
        if f.get("file_type", "") not in EXT_LANG:
            continue
        full = CODE_ROOT / f["file_path"]
        try:
            if full.stat().st_size > MAX_INLINE_SIZE:
                continue
            code_files[f["file_path"]] = full.read_text(errors="replace")
        except OSError:
            pass

# Escape `</` to neutralize </script> inside any source file that would
# otherwise break the inline <script> tag the JSON gets dropped into.
code_files_js = json.dumps(code_files, ensure_ascii=False).replace("</", "<\\/")
ext_lang_js = json.dumps(EXT_LANG)

# ── Reproduction plan ──
def render_plan_card(item):
    """Render a reproduction plan item as a detailed card."""
    priority = item.get("priority", "low")
    feasibility = item.get("feasibility", "blocked")
    pcls = f"priority-{priority}"
    fcls = "repro-ready" if feasibility == "ready" else "repro-blocked"
    quote = item.get("quote", "")
    claim = item.get("claim", "")
    source = item.get("source", "")
    mode = item.get("mode", "")
    command = item.get("command", "")
    goal = item.get("goal", {})

    cid = item.get("id", "")
    claim_pill = f'<span class="finding-id">Claim {cid}</span>' if cid else ''
    title = seq_pill(f"plan-{cid}") + claim_pill + section_pill(source)

    context_rows, where_rows, why_rows, how_rows = [], [], [], []
    if claim:
        context_rows.append(render_detail_row("Claim", claim))
    if quote:
        where_rows.append(render_quote_row(quote))
    why_rows.append(
        f'<div class="detail-row">'
        f'<span class="detail-label">Priority</span>'
        f'<span class="{pcls}">{E(priority.title())}</span></div>'
    )
    why_rows.append(
        f'<div class="detail-row">'
        f'<span class="detail-label">Feasibility</span>'
        f'<span class="{fcls}">{E(feasibility.title())}</span></div>'
    )
    if mode:
        how_rows.append(render_detail_row("Mode", mode))
    if command:
        how_rows.append(
            f'<div class="detail-row">'
            f'<span class="detail-label">Command</span>'
            f'<code style="font-size:11px;white-space:pre-wrap;">{E(command)}</code></div>'
        )
    if goal:
        goal_str = ", ".join(f"{k}: {v}" for k, v in goal.items()) if isinstance(goal, dict) else str(goal)
        how_rows.append(render_detail_row("Goal", goal_str))
    details_html = render_detail_blocks(context_rows, where_rows, why_rows, how_rows)

    border_colors = {"high": "#fca5a5", "medium": "#fde68a", "low": "#a7f3d0"}
    bg_colors = {"high": "#ef4444", "medium": "#f59e0b", "low": "#10b981"}
    border_color = border_colors.get(priority, "#d1d5db")
    bg_color = bg_colors.get(priority, "#6b7280")
    return f'''<div class="finding-card" style="border:2px solid {border_color}; box-shadow:4px 4px 0px #d1d5db;">
  <span class="finding-status" style="background:{bg_color}">{E(priority)}</span>
  {title}
  <div class="detail-body">
    {details_html}
    {render_card_comment(f"plan-{cid}")}
  </div>
</div>'''

# ── Build code snippets for code findings ──
code_snippets = {}  # "file:start-end" -> {file, start, end, content}
if check_code and CODE_ROOT.exists():
    for r in check_code.get("results", []):
        ref = r.get("quote", "")
        if not isinstance(ref, str):
            continue
        for m in CODE_REF_RX.finditer(ref):
            fpath = m.group(1)
            start = int(m.group(2))
            end = int(m.group(3)) if m.group(3) else start
            key = m.group(0)
            if key in code_snippets:
                continue
            full_path = CODE_ROOT / fpath
            if not full_path.exists():
                continue
            try:
                lines = full_path.read_text(errors='replace').splitlines()
                # Show context: 5 lines before, the range, 5 lines after
                ctx_start = max(0, start - 6)
                ctx_end = min(len(lines), end + 5)
                snippet_lines = []
                for i in range(ctx_start, ctx_end):
                    snippet_lines.append(lines[i])
                code_snippets[key] = {
                    "file": fpath,
                    "start": start,
                    "end": end,
                    "ctx_start": ctx_start + 1,  # 1-indexed
                    "content": "\n".join(snippet_lines),
                }
            except Exception:
                pass

code_snippets_js = json.dumps(code_snippets, ensure_ascii=False)


# ── L1/L2/L3 tier mapping for section bars ──
SECTION_TIER = {
    "txt": "L1", "vis": "L1", "bib": "L1", "claim": "L1",
    "theory": "L2", "prior": "L2", "code": "L2", "exp": "L2",
    "repro": "L3",
}

def tier_badge(section_id):
    tier = SECTION_TIER.get(section_id)
    if not tier:
        return ""
    return f'<span class="tier-badge tier-{tier.lower()}">{tier}</span>'


repro_plan = ""
if check_exp and "plan" in check_exp:
    plan_items = check_exp["plan"]
    plan_cards = "\n".join(render_plan_card(p) for p in plan_items)
    ready_count = sum(1 for p in plan_items if p.get("feasibility") == "ready")
    blocked_count = sum(1 for p in plan_items if p.get("feasibility") != "ready")
    plan_badges = ""
    if ready_count:
        plan_badges += f'<span class="badge badge-pass">{ready_count} ready</span> '
    if blocked_count:
        plan_badges += f'<span class="badge badge-blocked">{blocked_count} TBD</span> '
    repro_plan = f'''<details class="report-section" data-section="repro" open>
<summary>{tier_badge("repro")}Experiment Reproduction ({len(plan_items)} claims) {plan_badges}</summary>
{plan_cards}
</details>'''


# ── Render section findings ──
def render_section(title, filename, items, report_type, default_open=False):
    """Render a report section with badge counts."""
    counts = {}
    for _, item in items:
        st = item.get("status", "info")
        counts[st] = counts.get(st, 0) + 1

    badges = ""
    for key in ["pass","warning","error","blocked"]:
        if counts.get(key, 0) > 0:
            badges += f'<span class="badge badge-{key}">{counts[key]}</span> '

    cards = "\n".join(render_finding_card(hl_id, item, report_type) for hl_id, item in items)

    extra = ""

    open_attr = " open" if default_open else ""
    section_id = report_type
    return f'''<details class="report-section" data-section="{section_id}"{open_attr}>
<summary>{tier_badge(section_id)}{E(title)} ({E(filename)}) {badges}</summary>
{cards}
{extra}
</details>'''


# ── Build highlights JS data ──
# HIGHLIGHTS includes ALL items with a page (for scroll-to-page), bbox may be null
all_with_page = {}
for qid, qdata in quote_pos.items():
    if qdata["page"]:
        all_with_page[qid] = {
            "page": qdata["page"],
            "bbox": qdata["bbox"],
            "status": qdata["status"],
            "page_width": qdata.get("page_width"),
            "page_height": qdata.get("page_height"),
        }
# Augment with a fallback page for cards whose quote was not located in the PDF.
# Walking in render order, every card without its own page inherits the most
# recent preceding card's page — clicking any card always scrolls the PDF to
# roughly the right region instead of doing nothing.
_last_page = None
for hid in hl_numbers:
    if hid in all_with_page:
        _last_page = all_with_page[hid]["page"]
    elif _last_page:
        all_with_page[hid] = {"page": _last_page, "bbox": None, "status": "info", "page_width": None, "page_height": None}
highlights_js = json.dumps(all_with_page, indent=2)

# Also need ALL highlights for permanent rendering
permanent_hl_js = json.dumps(highlights_by_page)
claim_parent_by_child_js = json.dumps(claim_parent_by_child)
claim_children_js = json.dumps(claim_children)


# ── Candidate Claims section (from check_claim.json) ──
claim_section = ""
if check_claim:
    s = check_claim.get("summary", {})
    by_type = s.get("by_evidence_type", {})
    total_claims = s.get("total_claims", 0)

    type_badges = ""
    for etype in ["experiment","related_work","theoretical","code"]:
        cnt = by_type.get(etype, 0)
        if cnt > 0:
            type_badges += f'<span class="badge badge-info">{etype}: {cnt}</span> '

    claim_cards = ""
    for r in check_claim.get("results", []):
        hl_id = f"claim-{r.get('id','')}"
        etypes = ", ".join(r.get("evidence_type", []))
        implicit_reason = r.get("implicit_reason", "")
        source = r.get("source", "")

        # Claim cards have no status; color the id pills by the first evidence type.
        etype_first = (r.get("evidence_type") or ["theoretical"])[0]
        etype_cls = f"etype-{etype_first}"
        title = seq_pill(hl_id, etype_cls) + f'<span class="finding-id {etype_cls}">Claim {r.get("id","")}</span>' + section_pill(source)

        # Claim cards have only Where (Quote); Why/How filled in by L2 verifiers.
        context_rows, where_rows = [], []
        quote = r.get("quote", "")
        if quote:
            where_rows.append(render_quote_row(quote))
        claim = r.get("claim", "")
        if claim:
            context_rows.append(render_detail_row("Claim", claim))
        if etypes:
            context_rows.append(render_detail_row("Evidence type", etypes))
        if implicit_reason:
            context_rows.append(render_detail_row("Note", implicit_reason))
        details_html = render_detail_blocks(context_rows, where=where_rows)

        etype_list = r.get("evidence_type", [])
        if "experiment" in etype_list:
            border = "#fde68a"
        elif "code" in etype_list:
            border = "#93c5fd"
        elif "related_work" in etype_list:
            border = "#c4b5fd"
        elif "theoretical" in etype_list:
            border = "#a7f3d0"
        else:
            border = "#d1d5db"

        claim_cards += f'''<div class="finding-card" data-highlight-id="{E(hl_id)}" style="border:2px solid {border}; box-shadow:4px 4px 0px #d1d5db;">
  <span class="finding-status" style="background:#7c3aed">{E(etypes.split(",")[0].strip()) if etypes else "claim"}</span>
  {title}
  <div class="detail-body">
    {details_html}
    {render_card_comment(hl_id)}
  </div>
</div>\n'''

    claim_section = f'''<details class="report-section" data-section="claim">
<summary>{tier_badge("claim")}Candidate Claims (check_claim.json) <span class="badge badge-info">{total_claims} claims</span> {type_badges}</summary>
{claim_cards}
</details>'''

hl_numbers_js = json.dumps(hl_numbers)


# ── Assemble HTML ──
HTML = f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>PaperDoctor — {E(paper_title)} Review</title>
<link rel="stylesheet" href="github-dark.min.css">
<style>
*,*::before,*::after {{ margin:0; padding:0; box-sizing:border-box; }}
html, body {{ height:100%; overflow:hidden; font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,Helvetica,Arial,sans-serif; font-size:14px; color:#1f2937; }}

.header {{ display:flex; align-items:center; justify-content:center; height:48px; background:#fff; color:#111; padding:0 16px; flex-shrink:0; z-index:100; border-bottom:1px solid #e5e7eb; }}
.header-inner {{ display:flex; align-items:center; gap:8px; }}
.header-inner img {{ height:32px; border-radius:4px; }}
.header-brand {{ font-weight:700; font-size:17px; letter-spacing:.3px; color:#111; }}

.container {{ display:flex; height:calc(100vh - 48px); }}
.panel {{ overflow-y:auto; flex-shrink:0; flex-grow:0; transition:flex-basis .3s cubic-bezier(.4,0,.2,1); }}
.panel-left   {{ flex-basis:33%; background:#1a1a1a; border-right:1px solid #2a2a2a; }}
.panel-middle {{ flex-basis:34%; background:#1e1e1e; border-right:1px solid #2a2a2a; position:relative; overflow-x:hidden; }}
.panel-right  {{ flex-basis:33%; background:#ffffff; }}

/* Collapsible middle column. flex-basis is the only animated property — width:auto / flex:1 cannot be transitioned. */
.container.mid-collapsed .panel-left   {{ flex-basis:calc(50% - 18px); }}
.container.mid-collapsed .panel-middle {{ flex-basis:36px; }}
.container.mid-collapsed .panel-right  {{ flex-basis:calc(50% - 18px); }}
/* Inner content fades to invisible (keeps layout intact, no reflow jitter). */
.panel-middle .mid-header > button:not(.mid-toggle),
.panel-middle > .code-tree,
.panel-middle > .code-viewer {{ transition:opacity .2s ease; }}
.container.mid-collapsed .panel-middle .mid-header > button:not(.mid-toggle),
.container.mid-collapsed .panel-middle > .code-tree,
.container.mid-collapsed .panel-middle > .code-viewer {{ opacity:0; pointer-events:none; }}
/* Toggle button: absolutely positioned so it stays put while siblings fade.
   When collapsed, recenter horizontally so the narrow column doesn't clip it. */
.mid-toggle {{ position:absolute; top:8px; right:8px; z-index:11; background:#252530; border:1px solid #444; color:#ccc; font-size:12px; padding:4px 9px; border-radius:3px; cursor:pointer; font-family:inherit; line-height:1; }}
.mid-toggle:hover {{ background:#4f8fff; border-color:#4f8fff; color:#fff; }}
.container.mid-collapsed .mid-toggle {{ right:auto; left:50%; transform:translateX(-50%); }}

.panel::-webkit-scrollbar {{ width:6px; }}
.panel::-webkit-scrollbar-track {{ background:transparent; }}
.panel::-webkit-scrollbar-thumb {{ background:#444; border-radius:3px; }}
.panel-right::-webkit-scrollbar-thumb {{ background:#ccc; }}

.pdf-pages {{ padding:12px; display:flex; flex-direction:column; gap:8px; }}
.pdf-page {{ position:relative; cursor:pointer; border:2px solid transparent; border-radius:4px; transition:border-color .15s; }}
.pdf-page:hover {{ border-color:#4f8fff; }}
.pdf-page.active {{ border-color:#4f8fff; }}
.pdf-page img {{ width:100%; display:block; border-radius:2px; }}
.pdf-page-num {{ position:absolute; top:4px; left:4px; background:rgba(0,0,0,.7); color:#fff; font-size:10px; padding:2px 6px; border-radius:3px; font-weight:600; }}

/* Permanent highlights on PDF. Element opacity removed so the number badge
   stays fully opaque (CSS opacity is inherited by all children). Border/bg
   alpha is encoded in rgba() instead. */
.pdf-hl {{ position:absolute; border:1.5px solid rgba(var(--hlc),var(--hlbo)); background:rgba(var(--hlc),var(--hlbg)); border-radius:2px; pointer-events:none; transition:transform .15s, background-color .15s; }}
.pdf-hl:hover {{ background:rgba(var(--hlc),var(--hlbg)); border-color:rgba(var(--hlc),var(--hlbo)); transform:none; z-index:5; }}
.pdf-hl:hover .pdf-hl-num {{ opacity:0; transition:opacity .2s; }}
.pdf-hl:hover .pdf-hl-tooltip {{ display:none; }}
.pdf-hl.focus-hl {{ background:rgba(var(--hlc),var(--hlbgh)); border-color:rgba(var(--hlc),.95); z-index:6; }}
.pdf-hl.hl-pass         {{ --hlc:16,185,129;  --hlbo:.65; --hlbg:.10; --hlbgh:.22; }}
.pdf-hl.hl-warning      {{ --hlc:245,158,11;  --hlbo:.70; --hlbg:.13; --hlbgh:.26; }}
.pdf-hl.hl-error        {{ --hlc:239,68,68;   --hlbo:.75; --hlbg:.16; --hlbgh:.30; }}
.pdf-hl.hl-info         {{ --hlc:124,58,237;  --hlbo:.62; --hlbg:.10; --hlbgh:.22; }}
.pdf-hl.hl-blocked      {{ --hlc:59,130,246;  --hlbo:.65; --hlbg:.10; --hlbgh:.22; }}
.pdf-hl-tooltip {{ display:none; position:absolute; bottom:calc(100% + 4px); left:50%; transform:translateX(-50%); background:#1f2937; color:#fff; font-size:10px; padding:3px 7px; border-radius:3px; white-space:nowrap; pointer-events:none; z-index:10; }}
/* Numbered badge that maps a PDF highlight to its right-panel finding card.
   --si is the parent's stack index for overlapping bboxes (set in JS); each
   stack level shifts the badge 26px to the right so all numbers stay visible. */
.pdf-hl-num {{ position:absolute; top:-10px; left:calc(-10px + var(--si,0) * 26px); min-width:22px; height:22px; padding:0 6px; background:#1f2937; color:#fff; font-size:12px; font-weight:800; border:2px solid #fff; border-radius:11px; display:flex; align-items:center; justify-content:center; box-shadow:0 2px 6px rgba(0,0,0,0.55), 0 0 0 1px rgba(0,0,0,0.15); pointer-events:none; font-family:-apple-system,sans-serif; line-height:1; z-index:6; font-variant-numeric:tabular-nums; }}
.pdf-hl.hl-pass .pdf-hl-num    {{ background:#047857; }}
.pdf-hl.hl-warning .pdf-hl-num {{ background:#b45309; }}
.pdf-hl.hl-error .pdf-hl-num   {{ background:#b91c1c; }}
.pdf-hl.hl-info .pdf-hl-num {{ background:#6d28d9; }}
.pdf-hl.hl-blocked .pdf-hl-num {{ background:#2563eb; }}
.pdf-hit {{ position:absolute; min-width:34px; min-height:34px; transform:translate(-50%,-50%); border-radius:6px; cursor:pointer; z-index:7; background:rgba(255,255,255,0); }}
.pdf-badge {{ position:absolute; transform:translate(-35%,-55%); min-width:24px; height:24px; padding:0 7px; background:#1f2937; color:#fff; font-size:12px; font-weight:800; border:2px solid #fff; border-radius:12px; display:flex; align-items:center; justify-content:center; box-shadow:0 2px 7px rgba(0,0,0,0.58), 0 0 0 1px rgba(0,0,0,0.15); cursor:pointer; z-index:9; font-family:-apple-system,sans-serif; line-height:1; font-variant-numeric:tabular-nums; transition:transform .12s, opacity .12s; user-select:none; }}
.pdf-badge:hover {{ opacity:0; }}
.pdf-badge.cluster {{ background:#111827; }}
.pdf-badge.hl-pass    {{ background:#047857; }}
.pdf-badge.hl-warning {{ background:#b45309; }}
.pdf-badge.hl-error   {{ background:#b91c1c; }}
.pdf-badge.hl-info {{ background:#6d28d9; }}
.pdf-badge.hl-blocked {{ background:#2563eb; }}
.pdf-popover {{ position:absolute; min-width:148px; max-width:220px; background:#fff; color:#111827; border:1px solid #d1d5db; border-radius:6px; box-shadow:0 8px 24px rgba(0,0,0,.25); padding:5px; z-index:30; font-size:12px; }}
.pdf-popover-parent {{ width:100%; border:0; background:#f5f3ff; color:#5b21b6; text-align:left; padding:6px 8px; border-radius:4px; font-family:inherit; font-size:12px; font-weight:800; cursor:pointer; margin:2px 0; }}
.pdf-popover-parent:hover {{ background:#ede9fe; }}
.pdf-popover button {{ display:block; width:100%; border:0; background:transparent; color:#111827; text-align:left; padding:6px 8px; border-radius:4px; cursor:pointer; font-family:inherit; font-size:12px; }}
.pdf-popover button.child {{ padding-left:18px; }}
.pdf-popover button:hover {{ background:#eef2ff; color:#1d4ed8; }}

/* iOS-style attention shake. Triggered on click navigation (always, even if
   the target is already in view, so the user gets visible feedback). */
@keyframes pdr-shake {{
  0%   {{ transform:translateX(0)    scale(1); }}
  12%  {{ transform:translateX(-5px) scale(1.10); }}
  24%  {{ transform:translateX( 5px) scale(1.10); }}
  36%  {{ transform:translateX(-4px) scale(1.10); }}
  48%  {{ transform:translateX( 4px) scale(1.10); }}
  60%  {{ transform:translateX(-3px) scale(1.08); }}
  72%  {{ transform:translateX( 2px) scale(1.06); }}
  84%  {{ transform:translateX(-1px) scale(1.03); }}
  100% {{ transform:translateX(0)    scale(1); }}
}}
.pdf-hl.shake {{ animation:pdr-shake .65s cubic-bezier(.36,.07,.19,.97); z-index:8; }}

/* Page-level wobble + ripple for cards whose quote was not located in the PDF —
   no specific bbox to shake, so we ping the page wrapper instead. */
@keyframes pdr-flash {{
  0%   {{ transform:translateX(0);    box-shadow:0 0 0 0 rgba(79,143,255,0),    0 0 0 0 rgba(79,143,255,0); }}
  15%  {{ transform:translateX(-4px); box-shadow:0 0 0 6px rgba(79,143,255,0.5), 0 0 0 12px rgba(79,143,255,0.25); }}
  30%  {{ transform:translateX( 4px); box-shadow:0 0 0 8px rgba(79,143,255,0.6), 0 0 0 16px rgba(79,143,255,0.30); }}
  45%  {{ transform:translateX(-3px); box-shadow:0 0 0 10px rgba(79,143,255,0.55), 0 0 0 20px rgba(79,143,255,0.22); }}
  60%  {{ transform:translateX( 2px); box-shadow:0 0 0 12px rgba(79,143,255,0.4),  0 0 0 24px rgba(79,143,255,0.16); }}
  75%  {{ transform:translateX(-1px); box-shadow:0 0 0 14px rgba(79,143,255,0.25), 0 0 0 28px rgba(79,143,255,0.10); }}
  100% {{ transform:translateX(0);    box-shadow:0 0 0 16px rgba(79,143,255,0),    0 0 0 32px rgba(79,143,255,0); }}
}}
.pdf-page.flash {{ animation:pdr-flash .75s cubic-bezier(.36,.07,.19,.97); z-index:8; }}

.mid-header {{ display:flex; align-items:center; height:40px; padding:0 14px; background:#252530; border-bottom:1px solid #333; color:#aaa; font-size:12px; font-weight:600; text-transform:uppercase; letter-spacing:.6px; gap:10px; position:sticky; top:0; z-index:10; }}
.mid-header button {{ background:none; border:1px solid #444; color:#ccc; font-size:11px; padding:3px 10px; border-radius:3px; cursor:pointer; font-family:inherit; }}
.mid-header button:hover, .mid-header button.active {{ background:#4f8fff; border-color:#4f8fff; color:#fff; }}

.code-tree {{ padding:10px 6px 20px 6px; color:#c9d1d9; font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12.5px; line-height:1.7; }}
.tree-root-label {{ color:#58a6ff; font-weight:700; margin-bottom:2px; padding:3px 6px; }}
.tree-item {{ display:flex; align-items:center; padding:2px 6px; border-radius:3px; cursor:pointer; white-space:nowrap; }}
.tree-item:hover {{ background:#2a2a3a; }}
.tree-item .icon {{ width:16px; text-align:center; margin-right:4px; flex-shrink:0; }}
.tree-dir > .icon {{ color:#f59e0b; }}
.tree-file > .icon {{ color:#6b7280; }}
.tree-file .fname {{ color:#c9d1d9; }}
.tree-file .fmeta {{ color:#6b7280; font-size:11px; margin-left:6px; }}
.tree-children {{ padding-left:18px; }}
.tree-toggle {{ user-select:none; }}
.tree-children.collapsed {{ display:none; }}

.code-viewer {{ display:none; padding:14px; color:#c9d1d9; }}
.code-viewer pre {{ background:#161b22; padding:14px; border-radius:6px; overflow-x:auto; font-size:12px; line-height:1.6; white-space:pre; }}
.code-file-header {{ display:block; margin-bottom:8px; padding:4px 8px; background:#2d333b; border-radius:4px; font-size:11px; font-weight:600; color:#58a6ff; font-family:"SF Mono",Menlo,Consolas,monospace; }}
.code-ln {{ display:inline-block; width:40px; text-align:right; margin-right:12px; color:#484f58; user-select:none; font-size:11px; }}
.code-ln-hl {{ color:#f59e0b; }}
.code-line-hl {{ background:rgba(245,158,11,0.12); }}

.right-content {{ padding:16px 14px 40px; }}
.section-title {{ font-size:15px; font-weight:700; margin-bottom:12px; color:#111827; }}
.paper-title {{ font-size:17px; font-weight:800; color:#111827; line-height:1.4; margin-bottom:16px; padding-bottom:12px; border-bottom:2px solid #e5e7eb; }}

.chart-wrap {{ display:flex; flex-direction:row; flex-wrap:wrap; align-items:center; justify-content:center; gap:16px 22px; padding:18px 0 8px; }}
.chart-col {{ display:flex; flex-direction:column; align-items:center; }}
.donut-container {{ position:relative; width:160px; height:160px; }}
.donut-center {{ position:absolute; top:50%; left:50%; transform:translate(-50%,-50%); text-align:center; }}
.donut-center .num {{ font-size:28px; font-weight:800; color:#111; }}
.donut-center .label {{ font-size:10px; color:#6b7280; text-transform:uppercase; letter-spacing:.5px; }}
.legend {{ display:flex; flex-wrap:wrap; justify-content:center; gap:6px 14px; margin-top:12px; font-size:12px; max-width:200px; }}
.legend-item {{ display:flex; align-items:center; gap:5px; }}
.legend-dot {{ width:10px; height:10px; border-radius:50%; flex-shrink:0; }}
.tier-bars-col {{ width:200px; align-items:stretch; }}
.tier-bars-body {{ display:flex; flex-direction:column; gap:10px; }}
.tier-block {{ display:flex; flex-direction:column; gap:4px; }}
.tier-bar {{ width:100%; height:14px; display:flex; border-radius:7px; overflow:hidden; background:#e5e7eb; }}
.tier-bar .seg {{ height:100%; }}
.tier-bar .seg-ok {{ background:#10b981; }}
.tier-bar .seg-doubt {{ background:#f59e0b; }}
.tier-bar .seg-bad {{ background:#ef4444; }}
.tier-meta {{ display:grid; grid-template-columns:auto 1fr 1fr 1fr; align-items:center; gap:6px; font-size:11px; font-variant-numeric:tabular-nums; }}
.tier-meta .tier-badge {{ margin-right:0; }}
.tier-meta .cnt {{ display:inline-flex; align-items:center; gap:4px; color:#6b7280; justify-self:start; }}
.tier-meta .cnt .legend-dot {{ width:8px; height:8px; }}
.tier-meta .cnt.cnt-zero {{ opacity:.4; }}

details.report-section {{ margin-bottom:12px; }}
details.report-section > .finding-card {{ margin-left:14px; }}
details.report-section > summary {{ cursor:pointer; font-weight:700; font-size:13.5px; padding:8px 10px; background:#f3f4f6; border-radius:5px; border:1px solid #e5e7eb; list-style:none; display:flex; align-items:center; gap:8px; user-select:none; flex-wrap:wrap; position:sticky; top:0; z-index:5; }}
details.report-section > summary::-webkit-details-marker {{ display:none; }}
details.report-section > summary::before {{ content:"\\25B8"; font-size:12px; color:#6b7280; transition:transform .15s; display:inline-block; }}
details.report-section[open] > summary::before {{ transform:rotate(90deg); }}
details.report-section > summary .badge {{ font-size:11px; font-weight:600; padding:1px 7px; border-radius:10px; color:#fff; }}
.badge-pass    {{ background:#10b981; }}
.badge-warning {{ background:#f59e0b; }}
.badge-error   {{ background:#ef4444; }}
.badge-blocked {{ background:#3b82f6; }}
.badge-info    {{ background:#7c3aed; }}

.finding-card {{ background:#f9fafb; border-radius:5px; padding:10px 12px; margin:8px 0; font-size:12.5px; line-height:1.55; cursor:pointer; transition:transform .1s, box-shadow .1s; }}
.finding-card:hover {{ transform:translateX(2px); }}
.finding-card.active-card {{ outline:2px solid #4f8fff; outline-offset:1px; }}
.finding-card.status-pass       {{ border:2px solid #a7f3d0; box-shadow:4px 4px 0px #d1d5db; }}
.finding-card.status-warning    {{ border:2px solid #fde68a; box-shadow:4px 4px 0px #d1d5db; }}
.finding-card.status-error      {{ border:2px solid #fca5a5; box-shadow:4px 4px 0px #d1d5db; }}
.finding-card.status-blocked    {{ border:2px solid #c7d2fe; box-shadow:4px 4px 0px #d1d5db; }}

.finding-status {{ display:inline-block; font-size:11px; font-weight:700; text-transform:uppercase; padding:1px 7px; border-radius:3px; color:#fff; margin-right:6px; vertical-align:middle; }}
.finding-status.pass       {{ background:#10b981; }}
.finding-status.warning    {{ background:#f59e0b; }}
.finding-status.error      {{ background:#ef4444; }}
.finding-status.blocked    {{ background:#6366f1; }}

.finding-card code {{ font-family:"SF Mono",Menlo,Consolas,monospace; font-size:11.5px; background:#e5e7eb; padding:1px 5px; border-radius:3px; }}
.writing-before {{ font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; background:#fef2f2; color:#991b1b; padding:2px 5px; border-radius:3px; }}
.writing-arrow {{ margin:0 6px; color:#9ca3af; font-size:14px; }}
.writing-after {{ font-family:"SF Mono",Menlo,Consolas,monospace; font-size:12px; background:#f0fdf4; color:#166534; padding:2px 5px; border-radius:3px; }}
.finding-source {{ display:inline-block; font-size:11px; color:#6b7280; margin-left:4px; }}
.finding-source strong {{ color:#4b5563; font-weight:600; }}
/* Category-colored ID pill (replaces the bold "Claim N" text in the title).
   Verification cards inherit color from .finding-card.status-* (parent);
   claim cards have no status, so the pill carries an .etype-* class itself. */
.finding-id {{ display:inline-block; padding:1px 8px; background:#1f2937; color:#fff; font-size:11px; font-weight:700; border-radius:10px; margin-right:6px; vertical-align:middle; }}
.finding-card.status-pass .finding-id    {{ background:#047857; }}
.finding-card.status-warning .finding-id {{ background:#b45309; }}
.finding-card.status-error .finding-id   {{ background:#b91c1c; }}
.finding-card.status-blocked .finding-id {{ background:#4338ca; }}
.finding-id.etype-theoretical  {{ background:#047857; }}
.finding-id.etype-experiment   {{ background:#b45309; }}
.finding-id.etype-code         {{ background:#1d4ed8; }}
.finding-id.etype-related_work {{ background:#6d28d9; }}

/* Expandable detail inside card */
.detail-body {{ margin-top:6px; padding:8px 10px; background:#fff; border:1px solid #e5e7eb; border-radius:4px; font-size:12px; line-height:1.6; }}
.detail-row {{ margin-bottom:6px; }}
.detail-label {{ display:inline-block; min-width:90px; font-weight:700; color:#6b7280; font-size:11px; text-transform:uppercase; vertical-align:top; margin-right:6px; }}
.detail-quote {{ font-style:italic; color:#4b5563; font-family:"SF Mono",Menlo,Consolas,monospace; font-size:11.5px; }}
/* Where / Why / How — three labeled blocks inside details */
.kind-block {{ margin-top:8px; padding:6px 10px 8px; border-radius:5px; border-left:3px solid; }}
.kind-block .kb-header {{ display:flex; align-items:center; font-size:10px; font-weight:800; letter-spacing:1.4px; text-transform:uppercase; margin-bottom:4px; }}
.kind-block .kb-header .kb-label {{ flex:1 1 auto; }}
.kind-block .kb-body .detail-row {{ margin-bottom:4px; }}
.kind-block .kb-body .detail-row:last-child {{ margin-bottom:0; }}
.kb-where {{ background:#eff6ff; border-left-color:#3b82f6; }}
.kb-where .kb-header {{ color:#1d4ed8; }}
.kb-why   {{ background:#fffbeb; border-left-color:#f59e0b; }}
.kb-why   .kb-header {{ color:#92400e; }}
.kb-how   {{ background:#ecfdf5; border-left-color:#10b981; }}
.kb-how   .kb-header {{ color:#065f46; }}
body.dark .kb-where {{ background:#172a4a; border-left-color:#3b82f6; }}
body.dark .kb-where .kb-header {{ color:#93c5fd; }}
body.dark .kb-why {{ background:#3a2a0c; border-left-color:#f59e0b; }}
body.dark .kb-why .kb-header {{ color:#fcd34d; }}
body.dark .kb-how {{ background:#0e2e22; border-left-color:#10b981; }}
body.dark .kb-how .kb-header {{ color:#6ee7b7; }}

/* Card-level free-form notes textarea (sits at the bottom of every card) */
.card-comment {{ margin-top:10px; padding-top:8px; border-top:1px dashed #e5e7eb; }}
.card-comment-label {{ display:block; font-size:11px; font-weight:700; color:#6b7280; text-transform:uppercase; letter-spacing:.4px; margin-bottom:4px; }}
.card-comment-input {{ width:100%; box-sizing:border-box; min-height:44px; padding:5px 7px; font-family:inherit; font-size:12px; line-height:1.5; border:1px solid #e5e7eb; border-radius:3px; resize:vertical; background:#fff; color:#1f2937; }}
.card-comment-input:focus {{ outline:none; border-color:#4f46e5; box-shadow:0 0 0 2px rgba(79,70,229,.15); }}
body.dark .card-comment {{ border-top-color:#2a2a30; }}
body.dark .card-comment-label {{ color:#9ca3af; }}
body.dark .card-comment-input {{ background:#0f0f12; color:#e5e7eb; border-color:#2a2a30; }}

.repro-table {{ width:100%; border-collapse:collapse; font-size:12px; margin-top:6px; }}
.repro-table th, .repro-table td {{ text-align:left; padding:5px 8px; border-bottom:1px solid #e5e7eb; }}
.repro-table th {{ font-weight:600; color:#6b7280; font-size:11px; text-transform:uppercase; }}
.priority-high   {{ color:#ef4444; font-weight:600; }}
.priority-medium {{ color:#f59e0b; font-weight:600; }}
.priority-low    {{ color:#10b981; font-weight:600; }}
.repro-ready   {{ color:#10b981; }}
.repro-blocked {{ color:#3b82f6; }}

/* ── Filter bar ── */
.filter-bar {{ display:flex; flex-wrap:wrap; gap:6px; margin-bottom:12px; }}
.filter-bar label {{ display:flex; align-items:center; gap:4px; font-size:12px; color:#374151; cursor:pointer; padding:3px 8px; border:1px solid #e5e7eb; border-radius:4px; user-select:none; transition:background .1s; }}
.filter-bar label:hover {{ background:#f3f4f6; }}
.filter-bar input[type=checkbox] {{ accent-color:#4f8fff; }}

.section-divider {{ border:none; border-top:1px solid #e5e7eb; margin:18px 0 14px; }}
.summary-text {{ font-size:12.5px; color:#374151; line-height:1.6; padding:8px 0 2px; }}
</style>
</head>
<body>

<div class="header" style="position:relative;">
  <div class="header-inner" style="position:absolute; left:50%; top:50%; transform:translate(-50%,-50%);">
    <img src="logo.png" alt="PaperDoctor">
    <span class="header-brand">PaperDoctor</span>
  </div>
  <div class="save-indicator" id="saveIndicator">
    <span class="status-text" id="saveStatusText">Choose folder once for autosave</span>
    <button onclick="importAnnotations()">Import</button>
    <button id="btnFolderSetup" onclick="bindAnnotationFolder()">Choose Folder</button>
    <button id="btnSave" onclick="saveAnnotations()">Save</button>
  </div>
  <button class="theme-toggle" id="btnTheme" onclick="paperdrToggleTheme()" title="Toggle dark mode" aria-label="Toggle dark mode">☾</button>
</div>

<script>
(function(){{
  var KEY = 'paperdr_theme';
  function setIcon(){{
    var btn = document.getElementById('btnTheme');
    if(btn) btn.textContent = document.body.classList.contains('dark') ? '☀︎' : '☾︎';
  }}
  window.paperdrToggleTheme = function(){{
    var dark = document.body.classList.toggle('dark');
    try {{ localStorage.setItem(KEY, dark ? 'dark' : 'light'); }} catch(e) {{}}
    setIcon();
  }};
  try {{
    if(localStorage.getItem(KEY) === 'dark') document.body.classList.add('dark');
  }} catch(e) {{}}
  setIcon();
}})();
</script>

<div class="container">

  <div class="panel panel-left">
    <div class="pdf-pages" id="pdfPages"></div>
  </div>

  <div class="panel panel-middle">
    <div class="mid-header">
      <button id="btnTree" class="active" onclick="showMidView('tree')">Code Tree</button>
      <button id="btnViewer" onclick="showMidView('viewer')">Code Viewer</button>
      <button id="btnMidToggle" class="mid-toggle" onclick="toggleMidPanel()" title="Hide / show code column">«</button>
    </div>
    <div id="codeTreeView" class="code-tree">
      <div class="tree-root-label">{E(PAPER_DIR.name)}/ <span style="color:#6b7280;font-weight:400">({total_files} files)</span></div>
      <div id="treeRoot"></div>
    </div>
    <div id="codeViewerView" class="code-viewer">
      <p style="color:#6b7280;margin-bottom:12px;">Select a file from the code tree to view its contents.</p>
      <pre><code id="codeBlock" class="language-python"></code></pre>
    </div>
  </div>

  <div class="panel panel-right">
    <div class="right-content">

      <div class="paper-title">{E(paper_title)}</div>

      <div class="section-title">Summary</div>
      <div class="chart-wrap">
        <div class="chart-col">
          <div class="donut-container">
            <svg viewBox="0 0 160 160" width="160" height="160">
              {donut_segments()}
            </svg>
            <div class="donut-center">
              <div class="num">{total_findings}</div>
              <div class="label">Findings</div>
            </div>
          </div>
          <div class="legend">
            {"".join(legend_items)}
          </div>
        </div>
        <div class="chart-col tier-bars-col" id="tierVerdictChart" hidden>
          <div class="tier-bars-body" id="tierVerdictBody"></div>
        </div>
      </div>

      <hr class="section-divider">

      <div class="section-title">Findings by PaperDoctor</div>

      <div class="filter-bar" id="filterBar"></div>

      {claim_section}

      {render_section("Writing Issues", "check_txt.json", txt_items, "txt", False)}

      {render_section("Visual Issues", "check_vis.json", vis_items, "vis", True)}

      {render_section("Bibliography", "check_bib.json", bib_items, "bib", False)}

      {render_section("Theory Verification", "check_theory.json", theory_items, "theory", False)}

      {render_section("Prior Work", "check_prior.json", prior_items, "prior", False)}

      {render_section("Code Verification", "check_code.json", code_items, "code", True)}

      {render_section("Experiment Review", "check_exp.json", exp_items, "exp", True)}

      {repro_plan}

    </div>
  </div>

</div>

<script src="highlight.min.js"></script>
<script src="python.min.js"></script>

<script>
(function(){{

  /* Highlight positions: id -> {{page, bbox:[x0,y0,x1,y1], status}} */
  var HIGHLIGHTS = {highlights_js};

  /* Code snippets: "file:start-end" -> {{file, start, end, ctx_start, content}} */
  var CODE_SNIPPETS = {code_snippets_js};

  /* Highlights grouped by page */
  var HL_BY_PAGE = {permanent_hl_js};

  var HL_NUMBERS = {hl_numbers_js};

  var CLAIM_PARENT_BY_CHILD = {claim_parent_by_child_js};

  var CLAIM_CHILDREN = {claim_children_js};

  /* ── Build PDF pages with permanent highlights ── */
  var pdfContainer = document.getElementById('pdfPages');
  for(var i = 1; i <= {num_pages}; i++){{
    var num = String(i).padStart(3, '0');
    var div = document.createElement('div');
    div.className = 'pdf-page';
    div.setAttribute('data-page', i);
    div.innerHTML = '<img src="pages/page-' + num + '.png" alt="Page ' + i + '" loading="lazy"><div class="pdf-page-num">' + i + '</div>';
    pdfContainer.appendChild(div);
  }}

  /* Place permanent highlights once. Positions are percentages so they auto-scale
     with the image when the column resizes — no re-placement needed. */
  var _hlPlaced = false;
  function placeHighlights(){{
    if(_hlPlaced) return;
    _hlPlaced = true;
    document.querySelectorAll('.pdf-page').forEach(function(pageEl){{
      var pageNum = parseInt(pageEl.getAttribute('data-page'));
      var hls = HL_BY_PAGE[pageNum];
      if(!hls) return;
      placeHLOnPage(pageEl, pageNum, hls);
    }});
    applyPdfOverlayFilters();
  }}

  function sectionKeyForHlId(hlId){{
    var prefix = (hlId || '').split('-')[0];
    var map = {{claim:'claim', txt:'txt', vis:'vis', ref:'bib', code:'code', theory:'theory', exp:'exp', prior:'prior'}};
    return map[prefix] || '';
  }}

  function setOverlayKeys(el, ids){{
    var keys = {{}};
    ids.forEach(function(id){{
      var k = sectionKeyForHlId(id);
      if(k) keys[k] = true;
    }});
    el.setAttribute('data-section-keys', Object.keys(keys).join(','));
  }}

  function rectForHighlight(h){{
    var b = h.bbox;
    var pageW = h.page_width || 612;
    var pageH = h.page_height || 792;
    return {{
      x0:b[0], y0:b[1], x1:b[2], y1:b[3],
      pageW:pageW, pageH:pageH,
      cx:(b[0] + b[2]) / 2, cy:(b[1] + b[3]) / 2,
      w:Math.max(1, b[2] - b[0]), h:Math.max(1, b[3] - b[1])
    }};
  }}

  function rectsTouch(a, b, margin){{
    return !(a.x1 + margin < b.x0 || b.x1 + margin < a.x0 || a.y1 + margin < b.y0 || b.y1 + margin < a.y0);
  }}

  function expandRect(r, minW, minH, pad){{
    var out = {{
      x0:r.x0 - pad, y0:r.y0 - pad, x1:r.x1 + pad, y1:r.y1 + pad,
      pageW:r.pageW, pageH:r.pageH
    }};
    var w = out.x1 - out.x0;
    var h = out.y1 - out.y0;
    if(w < minW){{
      var dx = (minW - w) / 2;
      out.x0 -= dx; out.x1 += dx;
    }}
    if(h < minH){{
      var dy = (minH - h) / 2;
      out.y0 -= dy; out.y1 += dy;
    }}
    out.x0 = Math.max(0, out.x0);
    out.y0 = Math.max(0, out.y0);
    out.x1 = Math.min(r.pageW, out.x1);
    out.y1 = Math.min(r.pageH, out.y1);
    out.cx = (out.x0 + out.x1) / 2;
    out.cy = (out.y0 + out.y1) / 2;
    out.w = Math.max(1, out.x1 - out.x0);
    out.h = Math.max(1, out.y1 - out.y0);
    return out;
  }}

  function badgeRectForHighlight(r){{
    // Approximate the badge/hit target in PDF points. This intentionally
    // overestimates a little so clusters appear whenever the UI would be fiddly.
    var x0 = r.x0 - 24;
    var y0 = r.y0 - 22;
    var x1 = r.x0 + 48;
    var y1 = r.y0 + 14;
    return {{
      x0:Math.max(0, x0), y0:Math.max(0, y0),
      x1:Math.min(r.pageW, x1), y1:Math.min(r.pageH, y1),
      pageW:r.pageW, pageH:r.pageH
    }};
  }}

  function columnIdForRect(r){{
    if(r.x0 < r.pageW * 0.42 && r.x1 > r.pageW * 0.58) return 'full';
    return ((r.x0 + r.x1) / 2) < (r.pageW / 2) ? 'left' : 'right';
  }}

  function sameColumn(a, b){{
    var ca = columnIdForRect(a._rect);
    var cb = columnIdForRect(b._rect);
    return ca === 'full' || cb === 'full' || ca === cb;
  }}

  function prepareInteractionRects(h){{
    h._hitRect = expandRect(h._rect, 56, 38, 8);
    h._badgeRect = badgeRectForHighlight(h._rect);
  }}

  function shouldCluster(a, b){{
    // Cluster if the visual highlights overlap, if their enlarged click
    // targets collide, or if the badges would land on top of each other.
    if(!sameColumn(a, b)) return false;
    if(rectsTouch(a._rect, b._rect, 8)) return true;
    if(rectsTouch(a._hitRect, b._hitRect, 6)) return true;
    if(rectsTouch(a._badgeRect, b._badgeRect, 4)) return true;
    return false;
  }}

  function clusterHighlights(items){{
    var clusters = [];
    items.forEach(function(h){{
      var joined = null;
      for(var i = 0; i < clusters.length; i++){{
        if(clusters[i].some(function(other){{ return shouldCluster(h, other); }})){{
          joined = clusters[i];
          break;
        }}
      }}
      if(joined) joined.push(h);
      else clusters.push([h]);
    }});

    // A newly appended item can bridge two earlier clusters; merge until stable.
    var changed = true;
    while(changed){{
      changed = false;
      outer: for(var a = 0; a < clusters.length; a++){{
        for(var b = a + 1; b < clusters.length; b++){{
          var touch = clusters[a].some(function(x){{
            return clusters[b].some(function(y){{ return shouldCluster(x, y); }});
          }});
          if(touch){{
            clusters[a] = clusters[a].concat(clusters[b]);
            clusters.splice(b, 1);
            changed = true;
            break outer;
          }}
        }}
      }}
    }}
    return clusters;
  }}

  function unionRect(cluster){{
    var r = {{
      x0:Infinity, y0:Infinity, x1:-Infinity, y1:-Infinity,
      pageW:cluster[0]._rect.pageW, pageH:cluster[0]._rect.pageH
    }};
    cluster.forEach(function(h){{
      var b = h._rect;
      r.x0 = Math.min(r.x0, b.x0); r.y0 = Math.min(r.y0, b.y0);
      r.x1 = Math.max(r.x1, b.x1); r.y1 = Math.max(r.y1, b.y1);
    }});
    r.cx = (r.x0 + r.x1) / 2; r.cy = (r.y0 + r.y1) / 2;
    r.w = Math.max(1, r.x1 - r.x0); r.h = Math.max(1, r.y1 - r.y0);
    return r;
  }}

  function focusHighlight(hlId, on){{
    var el = document.querySelector('.pdf-hl[data-hl-id="' + hlId + '"]');
    if(el) el.classList.toggle('focus-hl', !!on);
  }}

  function focusCluster(cluster, on){{
    cluster.forEach(function(h){{ focusHighlight(h.id, on); }});
  }}

  function closeHighlightMenu(){{
    document.querySelectorAll('.pdf-popover').forEach(function(el){{ el.remove(); }});
    document.querySelectorAll('.pdf-hl.focus-hl').forEach(function(el){{ el.classList.remove('focus-hl'); }});
  }}

  function openHighlightMenu(pageEl, cluster, anchor){{
    closeHighlightMenu();
    var pop = document.createElement('div');
    pop.className = 'pdf-popover';
    pop.style.left = (anchor.x0 / anchor.pageW * 100) + '%';
    pop.style.top = (Math.min(anchor.y1 + 8, anchor.pageH - 12) / anchor.pageH * 100) + '%';
    var sorted = cluster.slice().sort(function(a, b){{ return (HL_NUMBERS[a.id] || 9999) - (HL_NUMBERS[b.id] || 9999); }});
    var renderedParents = {{}};
    sorted.forEach(function(h){{
      var parentId = CLAIM_PARENT_BY_CHILD[h.id] || '';
      if(parentId && !renderedParents[parentId]){{
        renderedParents[parentId] = true;
        var parentBtn = document.createElement('button');
        parentBtn.className = 'pdf-popover-parent';
        parentBtn.textContent = parentId.replace('claim-', 'Claim ') + ' (candidate)';
        parentBtn.addEventListener('click', function(e){{
          e.stopPropagation();
          scrollToFinding(parentId);
        }});
        pop.appendChild(parentBtn);
      }}
      var btn = document.createElement('button');
      var n = HL_NUMBERS[h.id];
      btn.textContent = (n ? '#' + n : h.id) + ' · ' + h.id;
      if(parentId) btn.className = 'child';
      btn.addEventListener('mouseenter', function(){{ focusHighlight(h.id, true); }});
      btn.addEventListener('mouseleave', function(){{ focusHighlight(h.id, false); }});
      btn.addEventListener('click', function(e){{
        e.stopPropagation();
        scrollToFinding(h.id);
      }});
      pop.appendChild(btn);
    }});
    pop.addEventListener('click', function(e){{ e.stopPropagation(); }});
    pageEl.appendChild(pop);
  }}

  function placeClusterControl(pageEl, cluster){{
    var r = unionRect(cluster);
    var ids = cluster.map(function(h){{ return h.id; }});
    var isCluster = cluster.length > 1;

    var hit = document.createElement('div');
    hit.className = 'pdf-hit';
    hit.setAttribute('data-hl-ids', ids.join(' '));
    setOverlayKeys(hit, ids);
    var hitRect = expandRect(r, 56, 38, 8);
    hit.style.left = (hitRect.cx / hitRect.pageW * 100) + '%';
    hit.style.top = (hitRect.cy / hitRect.pageH * 100) + '%';
    hit.style.width = (hitRect.w / hitRect.pageW * 100) + '%';
    hit.style.height = (hitRect.h / hitRect.pageH * 100) + '%';

    var badge = document.createElement('div');
    var first = cluster.slice().sort(function(a, b){{ return (HL_NUMBERS[a.id] || 9999) - (HL_NUMBERS[b.id] || 9999); }})[0];
    badge.className = 'pdf-badge ' + (isCluster ? 'cluster' : ('hl-' + (first.status || 'info')));
    badge.setAttribute('data-hl-ids', ids.join(' '));
    setOverlayKeys(badge, ids);
    badge.style.left = (r.x0 / r.pageW * 100) + '%';
    badge.style.top = (r.y0 / r.pageH * 100) + '%';
    badge.textContent = isCluster ? ('#' + HL_NUMBERS[first.id] + ' +' + (cluster.length - 1)) : ('#' + HL_NUMBERS[first.id]);

    function activate(e){{
      e.stopPropagation();
      if(isCluster) openHighlightMenu(pageEl, cluster, r);
      else scrollToFinding(first.id);
    }}
    function enter(){{ focusCluster(cluster, true); }}
    function leave(){{ if(!document.querySelector('.pdf-popover')) focusCluster(cluster, false); }}
    hit.addEventListener('click', activate);
    badge.addEventListener('click', activate);
    hit.addEventListener('mouseenter', enter);
    badge.addEventListener('mouseenter', enter);
    hit.addEventListener('mouseleave', leave);
    badge.addEventListener('mouseleave', leave);

    pageEl.appendChild(hit);
    pageEl.appendChild(badge);
  }}

  function placeHLOnPage(pageEl, pageNum, hls){{
    var numbered = [];
    hls.forEach(function(h){{
      h._rect = rectForHighlight(h);
      prepareInteractionRects(h);
      var b = h.bbox;
      var pageW = h.page_width || 612;
      var pageH = h.page_height || 792;
      var el = document.createElement('div');
      el.className = 'pdf-hl hl-' + (h.status || 'info');
      el.setAttribute('data-hl-id', h.id);
      setOverlayKeys(el, [h.id]);
      el.style.left   = (b[0] / pageW * 100) + '%';
      el.style.top    = (b[1] / pageH * 100) + '%';
      el.style.width  = ((b[2] - b[0]) / pageW * 100) + '%';
      el.style.height = ((b[3] - b[1]) / pageH * 100) + '%';
      var num = HL_NUMBERS[h.id];
      var tooltipText = num ? 'Where: #' + num + ' · ' + h.id : 'Where: ' + h.id;
      el.innerHTML = '<div class="pdf-hl-tooltip">' + tooltipText + '</div>';
      el.addEventListener('click', function(e){{
        e.stopPropagation();
        scrollToFinding(this.getAttribute('data-hl-id'));
      }});
      pageEl.appendChild(el);
      if(num) numbered.push(h);
    }});
    clusterHighlights(numbered).forEach(function(cluster){{
      placeClusterControl(pageEl, cluster);
    }});
  }}

  /* ── Scroll helper: scroll element into view within its scrollable panel ── */
  function scrollInPanel(el, panel){{
    if(!el || !panel) return;
    var elRect = el.getBoundingClientRect();
    var panelRect = panel.getBoundingClientRect();
    var offset = elRect.top - panelRect.top - (panelRect.height / 2) + (elRect.height / 2);
    panel.scrollBy({{top: offset, behavior: 'smooth'}});
  }}

  var leftPanel = document.querySelector('.panel-left');
  var rightPanel = document.querySelector('.panel-right');

  /* Re-trigger a CSS animation by toggling the class with a forced reflow in
     between. Without this, clicking the same target twice in a row would not
     replay the animation. */
  function pingClass(el, cls, ms){{
    if(!el) return;
    el.classList.remove(cls);
    void el.offsetWidth;
    el.classList.add(cls);
    setTimeout(function(){{ el.classList.remove(cls); }}, ms);
  }}

  /* ── Click PDF highlight -> scroll right panel to finding ── */
  /* Sync the middle code viewer to a finding's code reference if any. */
  function syncCodeViewer(card){{
    var ref = card && card.getAttribute('data-code-ref');
    if(ref) showCodeSnippet(ref);
  }}

  function scrollToFinding(hlId){{
    clearActive();
    var card = document.querySelector('.finding-card[data-highlight-id="' + hlId + '"]');
    if(!card) return;
    var parentDetails = card.closest('details.report-section');
    if(parentDetails && !parentDetails.open) parentDetails.open = true;
    card.classList.add('active-card');
    requestAnimationFrame(function(){{ scrollInPanel(card, rightPanel); }});
    pingClass(document.querySelector('.pdf-hl[data-hl-id="' + hlId + '"]'), 'shake', 700);
    syncCodeViewer(card);
  }}

  /* ── Click finding card -> scroll left panel to PDF page ── */
  function scrollToPDF(hlId){{
    clearActive();
    var card = document.querySelector('.finding-card[data-highlight-id="' + hlId + '"]');
    if(card) card.classList.add('active-card');

    var h = HIGHLIGHTS[hlId];
    if(!h || !h.page) return;
    var pageEl = document.querySelector('.pdf-page[data-page="' + h.page + '"]');
    if(!pageEl) return;

    pageEl.classList.add('active');
    // Center the highlight bbox itself when available — for tall pages the
    // bbox can sit well outside the page-centered viewport otherwise.
    var pdfHl = pageEl.querySelector('.pdf-hl[data-hl-id="' + hlId + '"]');
    scrollInPanel(pdfHl || pageEl, leftPanel);
    pingClass(pdfHl || pageEl, pdfHl ? 'shake' : 'flash', 750);
  }}

  function clearActive(){{
    closeHighlightMenu();
    document.querySelectorAll('.active-card,.pdf-page.active,.pdf-hl.shake,.pdf-page.flash').forEach(function(el){{
      el.classList.remove('active-card','active','shake','flash','focus-hl');
    }});
  }}

  /* ── Code-viewer helpers (shared by snippet view and tree-click view) ── */
  var EXT_LANG = {ext_lang_js};
  function pathToLang(path){{
    var i = path.lastIndexOf('.');
    return i < 0 ? 'plaintext' : (EXT_LANG[path.slice(i)] || 'plaintext');
  }}
  function _escHtml(s){{
    return (s||'').replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;');
  }}
  function highlightContent(content, lang){{
    if(typeof hljs !== 'undefined' && hljs.getLanguage && hljs.getLanguage(lang)){{
      try {{ return hljs.highlight(content, {{language: lang, ignoreIllegals: true}}).value; }}
      catch(e) {{ /* fall through to plain escape */ }}
    }}
    return _escHtml(content);
  }}
  // Render an array of highlighted-HTML lines as a numbered code block.
  // hlRange = [start, end] (1-indexed, inclusive) to amber-highlight a span.
  function renderNumberedLines(headerText, lines, startLine, hlRange){{
    var html = '<div class="code-file-header">' + _escHtml(headerText) + '</div>';
    for(var i = 0; i < lines.length; i++){{
      var ln = startLine + i;
      var isHL = hlRange && ln >= hlRange[0] && ln <= hlRange[1];
      html += '<span class="code-ln' + (isHL ? ' code-ln-hl' : '') + '">' + String(ln).padStart(4) + '</span>' +
              '<span' + (isHL ? ' class="code-line-hl"' : '') + '>' + lines[i] + '</span>\\n';
    }}
    return html;
  }}

  /* ── Show code snippet in middle panel ── */
  var _SNIPPET_HTML = {{}};
  function showCodeSnippet(ref){{
    var snippet = CODE_SNIPPETS[ref];
    if(!snippet) return;
    showMidView('viewer');
    var block = document.getElementById('codeBlock');
    if(!_SNIPPET_HTML[ref]){{
      var lines = highlightContent(snippet.content, pathToLang(snippet.file)).split('\\n');
      _SNIPPET_HTML[ref] = renderNumberedLines(
        snippet.file + ':' + snippet.start + '-' + snippet.end,
        lines, snippet.ctx_start, [snippet.start, snippet.end]);
    }}
    block.innerHTML = _SNIPPET_HTML[ref];
  }}

  /* Bind click on finding cards */
  document.querySelectorAll('.finding-card[data-highlight-id]').forEach(function(card){{
    card.addEventListener('click', function(e){{
      if(e.target.closest('.detail-body') || e.target.tagName === 'A') return;
      syncCodeViewer(this);
      scrollToPDF(this.getAttribute('data-highlight-id'));
    }});

    /* Where block: clicking anywhere except the editable value (or buttons /
       chips inside it) jumps the same way the card click does. */
    var whereBlock = card.querySelector('.kind-block.kb-where');
    if(whereBlock){{
      whereBlock.addEventListener('click', function(e){{
        if(e.target.closest('.detail-quote, .detail-val, .kb-verdict, a, button, textarea')) return;
        e.stopPropagation();
        syncCodeViewer(card);
        scrollToPDF(card.getAttribute('data-highlight-id'));
      }});
      whereBlock.style.cursor = 'pointer';
    }}
  }});

  window.addEventListener('load', placeHighlights);
  document.addEventListener('click', function(e){{
    if(e.target.closest('.pdf-popover') || e.target.closest('.pdf-badge') || e.target.closest('.pdf-hit')) return;
    closeHighlightMenu();
  }});

  /* ── Section filter checkboxes ── */
  var SECTION_LABELS = {{
    claim: 'Candidate Claims',
    txt: 'Writing Issues',
    vis: 'Visual Issues',
    bib: 'Bibliography',
    code: 'Code Verification',
    theory: 'Theory Verification',
    exp: 'Experiment Review',
    prior: 'Prior Work',
    repro: 'Experiment Reproduction'
  }};
  function overlayVisibleForCurrentFilters(el){{
    var raw = el.getAttribute('data-section-keys') || '';
    var keys = raw.split(',').filter(Boolean);
    if(keys.length === 0) return true;
    return keys.some(function(key){{
      var cb = document.querySelector('#filterBar input[data-filter="' + key + '"]');
      return !cb || cb.checked;
    }});
  }}
  function applyPdfOverlayFilters(){{
    closeHighlightMenu();
    document.querySelectorAll('.pdf-hl,.pdf-hit,.pdf-badge').forEach(function(el){{
      el.style.display = overlayVisibleForCurrentFilters(el) ? '' : 'none';
    }});
  }}
  // Sections that start unchecked. Candidate Claims are inputs to L2 verifiers
  // and clutter the default view; user can opt back in via the filter bar.
  var FILTER_DEFAULT_OFF = {{claim: true}};
  (function buildFilters(){{
    var bar = document.getElementById('filterBar');
    if(!bar) return;
    var sections = document.querySelectorAll('.report-section[data-section]');
    var seen = {{}};
    sections.forEach(function(sec){{
      var key = sec.getAttribute('data-section');
      if(seen[key]) return;
      seen[key] = true;
      var label = document.createElement('label');
      var cb = document.createElement('input');
      cb.type = 'checkbox';
      cb.checked = !FILTER_DEFAULT_OFF[key];
      cb.setAttribute('data-filter', key);
      cb.addEventListener('change', function(){{
        document.querySelectorAll('.report-section[data-section="' + key + '"]').forEach(function(el){{
          el.style.display = cb.checked ? '' : 'none';
        }});
        applyPdfOverlayFilters();
      }});
      label.appendChild(cb);
      label.appendChild(document.createTextNode(' ' + (SECTION_LABELS[key] || key)));
      bar.appendChild(label);
      if(!cb.checked){{
        document.querySelectorAll('.report-section[data-section="' + key + '"]').forEach(function(el){{
          el.style.display = 'none';
        }});
      }}
    }});
    applyPdfOverlayFilters();
  }})();

  /* ── Code Tree (auto-generated from index.json) ── */
  var treeData = {code_tree_js};
  var CODE_FILES = {code_files_js};

  var _FILE_HTML = {{}};
  function showCodeFile(path){{
    showMidView('viewer');
    var block = document.getElementById('codeBlock');
    var content = CODE_FILES[path];
    if(content == null){{
      block.textContent = '# ' + path + '\\n# (binary or excluded from inline; not available)';
      return;
    }}
    if(!_FILE_HTML[path]){{
      var lines = highlightContent(content, pathToLang(path)).split('\\n');
      _FILE_HTML[path] = renderNumberedLines(path, lines, 1, null);
    }}
    block.innerHTML = _FILE_HTML[path];
  }}

  function buildTree(items, container){{
    items.forEach(function(item){{
      if(item.type === 'dir'){{
        var wrap = document.createElement('div');
        var row = document.createElement('div');
        row.className = 'tree-item tree-dir tree-toggle';
        row.innerHTML = '<span class="icon">\\u25BC</span><span class="fname" style="color:#58a6ff;font-weight:600;">' + item.name + '</span>';
        var children = document.createElement('div');
        children.className = 'tree-children';
        row.addEventListener('click', function(){{
          children.classList.toggle('collapsed');
          var icon = row.querySelector('.icon');
          icon.textContent = children.classList.contains('collapsed') ? '\\u25B6' : '\\u25BC';
        }});
        wrap.appendChild(row);
        buildTree(item.children, children);
        wrap.appendChild(children);
        container.appendChild(wrap);
      }} else {{
        var row = document.createElement('div');
        row.className = 'tree-item tree-file';
        var meta = item.meta ? ' <span class="fmeta">(' + item.meta + ')</span>' : '';
        row.innerHTML = '<span class="icon">\\uD83D\\uDCC4</span><span class="fname">' + item.name + '</span>' + meta;
        row.addEventListener('click', (function(path){{
          return function(){{ showCodeFile(path); }};
        }})(item.path));
        container.appendChild(row);
      }}
    }});
  }}
  buildTree(treeData, document.getElementById('treeRoot'));

  window.showMidView = function(view){{
    var treeEl = document.getElementById('codeTreeView');
    var viewerEl = document.getElementById('codeViewerView');
    var btnTree = document.getElementById('btnTree');
    var btnViewer = document.getElementById('btnViewer');
    if(view === 'tree'){{
      treeEl.style.display = 'block'; viewerEl.style.display = 'none';
      btnTree.classList.add('active'); btnViewer.classList.remove('active');
    }} else {{
      treeEl.style.display = 'none'; viewerEl.style.display = 'block';
      btnViewer.classList.add('active'); btnTree.classList.remove('active');
    }}
  }};

  window.toggleMidPanel = function(){{
    var container = document.querySelector('.container');
    var btn = document.getElementById('btnMidToggle');
    var collapsed = container.classList.toggle('mid-collapsed');
    btn.textContent = collapsed ? '»' : '«';
    btn.title = collapsed ? 'Show code column' : 'Hide code column';
    try {{ localStorage.setItem('paperdr_mid_collapsed', collapsed ? '1' : '0'); }} catch(e){{}}
  }};

  /* Restore prior collapse state */
  try {{
    if(localStorage.getItem('paperdr_mid_collapsed') === '1'){{
      document.querySelector('.container').classList.add('mid-collapsed');
      var btn0 = document.getElementById('btnMidToggle');
      if(btn0){{ btn0.textContent = '»'; btn0.title = 'Show code column'; }}
    }}
  }} catch(e){{}}

  if(typeof hljs !== 'undefined'){{ hljs.highlightAll(); }}
}})();
</script>
</body>
</html>'''

editor_block = (EDITOR_BLOCK_TEMPLATE
    .replace('__PAPER_SLUG__', PAPER_DIR.name)
    .replace('__CANONICAL_STATUS__', json.dumps(list(CANONICAL_STATUS))))
HTML = HTML.replace('</body>', editor_block + '\n</body>')

(DISPLAY / "paperdoctor.html").write_text(HTML)
print(f"Generated paperdoctor.html ({len(HTML):,} bytes)")
print(f"Status counts: {status_counts}")
print(f"Total findings: {total_findings}")
print(f"Permanent highlights: {len(all_highlights)} on {len(highlights_by_page)} pages")
if check_claim:
    _claim_total = len(check_claim.get("results", []))
    _claim_hl = sum(1 for r in check_claim.get("results", []) if f"claim-{r.get('id','')}" in _highlighted_ids)
    print(f"Claim highlights: {_claim_hl}/{_claim_total}")
    print(f"Covered candidate claims suppressed: {len(covered_claim_ids)}")
