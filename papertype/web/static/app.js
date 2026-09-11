/* PaperType 前端：无框架，hash 路由。页面：首页 / 导入 / 校正 / 整卷预览 / 分题作答 / 汇总 / 设置 */
'use strict';
const $ = (s, el = document) => el.querySelector(s);
const app = $('#app');
const TYPE = { single: '单选', multi: '多选', judge: '判断', blank: '填空', essay: '简答' };
const esc = s => String(s ?? '').replace(/[&<>"]/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;' }[c]));
const key = q => `${q.unit}|${q.no}`;
const L = i => String.fromCharCode(65 + i);

async function api(path, opt = {}) {
  const r = await fetch(path, opt);
  if (!r.ok) {
    let msg = r.statusText;
    try { msg = (await r.json()).detail || msg; } catch (e) { }
    throw new Error(msg);
  }
  return r.json();
}
const json = (m, body) => ({ method: m, headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });

let toastT;
function toast(msg, ms = 2200) {
  const t = $('#toast'); t.textContent = msg; t.hidden = false;
  clearTimeout(toastT); toastT = setTimeout(() => t.hidden = true, ms);
}
function modal(html) {
  const m = $('#modal'); m.innerHTML = `<div class="box">${html}</div>`; m.hidden = false;
  m.onclick = e => { if (e.target === m) closeModal(); };
  return m;
}
function closeModal() { $('#modal').hidden = true; $('#modal').innerHTML = ''; }
function confirmBox(text, okLabel = '确定') {
  return new Promise(res => {
    const m = modal(`<p>${esc(text)}</p><div class="row" style="justify-content:flex-end"><button class="btn" id="mc">取消</button><button class="btn primary" id="mo">${esc(okLabel)}</button></div>`);
    $('#mc', m).onclick = () => { closeModal(); res(false); };
    $('#mo', m).onclick = () => { closeModal(); res(true); };
  });
}

/* ---------------- 路由 ---------------- */
const routes = [
  [/^#\/?$/, home],
  [/^#\/import$/, importPage],
  [/^#\/review\/([^/]+)$/, review],
  [/^#\/paper\/([^/]+)$/, paperHome],
  [/^#\/paper\/([^/]+)\/preview$/, (id) => take(id, 'preview')],
  [/^#\/paper\/([^/]+)\/take$/, (id) => take(id, 'take')],
  [/^#\/paper\/([^/]+)\/summary\/([^/]+)$/, summary],
  [/^#\/settings$/, settings],
];
function route() {
  const h = location.hash || '#/';
  for (const [re, fn] of routes) {
    const m = h.match(re);
    if (m) { stopTake(); fn(...m.slice(1)).catch(e => { app.innerHTML = `<p class="muted">出错了：${esc(e.message)}</p>`; }); return; }
  }
  location.hash = '#/';
}
window.addEventListener('hashchange', route);
window.addEventListener('DOMContentLoaded', route);

/* 回到顶部：页面滚过一屏的一半才显示 */
const totop = document.getElementById('totop');
window.addEventListener('scroll', () => { totop.hidden = window.scrollY < window.innerHeight / 2; }, { passive: true });
totop.onclick = () => window.scrollTo({ top: 0, behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'auto' : 'smooth' });

/* ---------------- 首页 ---------------- */
async function home() {
  const d = await api('/api/papers');
  const item = (p, kind) => `<div class="item">
    <div><div class="t">${esc(p.title)} ${kind === 'drafts' ? '<span class="tag warn">草稿</span>' : ''}${p.to_review ? `<span class="tag seal">待核对 ${p.to_review}</span>` : ''}</div>
    <div class="muted" style="font-size:13px">${p.count} 题 · ${esc(p.import_path)} · ${esc(p.created_at)}${kind === 'papers' && p.attempts ? ` · 已作答 ${p.attempts} 次` : ''}</div></div>
    <div class="row">${kind === 'drafts'
      ? `<a class="btn small" href="#/review/${p.id}">继续校正</a>`
      : `<a class="btn small primary" href="#/paper/${p.id}/take">分题作答</a><a class="btn small" href="#/paper/${p.id}/preview">整卷预览</a><a class="btn small" href="#/paper/${p.id}">详情</a>`}
      <button class="btn small danger" data-del="${kind}/${p.id}">删除</button></div></div>`;
  app.innerHTML = `<h1>试卷</h1>
    <div class="row" style="margin-bottom:8px"><a class="btn primary" href="#/import">导入试卷</a><span class="muted">导入后先校正，再作答。系统只汇总答案，不判分。</span></div>
    ${d.drafts.length ? `<h2>待校正的草稿</h2><div class="plist">${d.drafts.map(p => item(p, 'drafts')).join('')}</div>` : ''}
    <h2>已生成的试卷</h2>
    <div class="plist">${d.papers.length ? d.papers.map(p => item(p, 'papers')).join('') : '<p class="muted">还没有试卷。点上面的「导入试卷」开始。</p>'}</div>`;
  app.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (!await confirmBox('删除后不可恢复，连同作答记录一起删除。确定删除？', '删除')) return;
    await api('/api/' + b.dataset.del, { method: 'DELETE' }); toast('已删除'); home();
  });
}

/* ---------------- 导入 ---------------- */
async function importPage() {
  const st = await api('/api/settings');
  let mode = 'file';
  const render = () => {
    app.innerHTML = `<h1>导入试卷</h1>
    <div class="tabs">
      <button class="${mode === 'file' ? 'on' : ''}" data-m="file">导入文件（Word / PDF）</button>
      <button class="${mode === 'ocr' ? 'on' : ''}" data-m="ocr">OCR 识图（图片 / 扫描件）</button>
      <button class="${mode === 'text' ? 'on' : ''}" data-m="text">粘贴文本</button>
    </div>
    <div class="grid2">
      <div>
        ${mode === 'text' ? `<textarea id="txt" style="min-height:320px" placeholder="把试卷文本贴进来。豆包转出的文本也走这里。&#10;题号必须有；选项每个一行或同行都可以。"></textarea>`
        : `<div class="drop" id="drop"><p>${mode === 'file' ? '拖入一份 .docx 或 .pdf' : '拖入一张或多张图片（jpg / png），或扫描版 pdf；多张按文件名顺序'}</p>
            <input type="file" id="files" ${mode === 'ocr' ? 'multiple accept=".jpg,.jpeg,.png,.pdf"' : 'accept=".docx,.pdf"'}>
            <p class="muted" id="flist"></p></div>`}
        <div class="f" style="margin-top:12px"><label class="muted">试卷名（可留空，自动取卷首标题）</label><input type="text" id="title"></div>
      </div>
      <div class="card">
        <h3 style="margin-top:0">识别方式</h3>
        <div class="tiers">
          <label><input type="radio" name="tier" value="rules" checked> 仅规则（默认）<br><span class="muted">本地秒出，零费用，不联网。待核对的题在校正页手动改。</span></label>
          <label><input type="radio" name="tier" value="flagged" ${st.llm_available ? '' : 'disabled'}> 规则优先，失败才问大模型<br><span class="muted">只把待核对的题送去重切，送之前会先确认。${st.llm_available ? '' : '（设置里未启用大模型）'}</span></label>
        </div>
        ${mode === 'ocr' ? '<p class="muted">OCR 在本机离线运行，清晰截图和扫描件准确率接近文字层；手机斜拍效果会差，识别后可在校正页点「OCR 整理」交给大模型修正。</p>' : ''}
        <button class="btn primary" id="go" style="margin-top:8px">开始识别</button>
        <p class="muted" id="prog"></p>
      </div>
    </div>`;
    app.querySelectorAll('.tabs button').forEach(b => b.onclick = () => { mode = b.dataset.m; render(); });
    const drop = $('#drop');
    if (drop) {
      const fi = $('#files');
      const show = () => $('#flist').textContent = [...fi.files].map(f => f.name).join('，');
      fi.onchange = show;
      drop.ondragover = e => { e.preventDefault(); drop.classList.add('over'); };
      drop.ondragleave = () => drop.classList.remove('over');
      drop.ondrop = e => { e.preventDefault(); drop.classList.remove('over'); fi.files = e.dataTransfer.files; show(); };
    }
    $('#go').onclick = async () => {
      const fd = new FormData();
      fd.append('mode', mode); fd.append('title', $('#title').value);
      if (mode === 'text') fd.append('text', $('#txt').value);
      else for (const f of $('#files').files) fd.append('files', f);
      if (mode !== 'text' && !$('#files').files.length) return toast('先选择文件');
      $('#go').disabled = true; $('#prog').textContent = mode === 'ocr' ? '正在 OCR 识别，每页约 3 秒…' : '正在解析…';
      try {
        const r = await api('/api/import', { method: 'POST', body: fd });
        const s = r.stats;
        toast(`共 ${s.count} 题，${s.to_review} 题待核对，${s.with_image} 题带图`, 4000);
        const tier = app.querySelector('input[name=tier]:checked').value;
        if (tier === 'flagged' && s.to_review > 0) {
          if (await confirmBox(`将把 ${s.to_review} 道待核对题发送给大模型重切，其余不动。继续？`, '发送')) {
            await runLLM('drafts', r.paper.id, 'flagged');
          }
        }
        location.hash = `#/review/${r.paper.id}`;
      } catch (e) { toast('导入失败：' + e.message, 5000); $('#go').disabled = false; $('#prog').textContent = ''; }
    };
  };
  render();
}

async function runLLM(kind, id, scope) {
  const r = await api(`/api/${kind}/${id}/llm`, json('POST', { scope }));
  const m = modal(`<p>大模型处理中… 已完成 <span id="jp">0/1</span> 块<br><span class="muted">每块最多 20 题，多块并行；一块通常 20 到 60 秒。</span></p><div class="row" style="justify-content:flex-end"><button class="btn" id="jc">取消</button></div>`);
  let cancelled = false;
  $('#jc', m).onclick = async () => { cancelled = true; await api(`/api/jobs/${r.job}`, { method: 'DELETE' }); closeModal(); toast('已取消，试卷未改动'); };
  while (!cancelled) {
    await new Promise(r => setTimeout(r, 1500));
    const j = await api(`/api/jobs/${r.job}`);
    if (cancelled) break;
    $('#jp', m).textContent = j.progress;
    if (j.done) { closeModal(); if (j.error) throw new Error(j.error); toast(j.result.message, 4000); return j.result; }
  }
  throw new Error('已取消');
}

/* ---------------- 校正页 ---------------- */
async function review(id) {
  let kind = 'drafts';
  let d;
  try { d = await api(`/api/drafts/${id}`); } catch (e) { kind = 'papers'; d = await api(`/api/papers/${id}`); }
  const paper = d.paper;
  let cur = Math.max(0, paper.questions.findIndex(q => !q.reviewed));
  let dirty = false;

  const render = () => {
    const qs = paper.questions;
    const bad = qs.filter(q => !q.reviewed).length;
    let lastUnit = null;
    const list = qs.map((q, i) => {
      let h = '';
      if (q.unit !== lastUnit) { lastUnit = q.unit; h += `<div class="u">${esc(q.unit || '（无单元）')}</div>`; }
      h += `<div class="q ${i === cur ? 'on' : ''} ${q.reviewed ? '' : 'bad'}" data-i="${i}"><span class="no">${q.no}</span><span class="s">${esc(q.stem || (q.image ? '[图片题]' : ''))}</span><span class="muted">${TYPE[q.type]}</span></div>`;
      return h;
    }).join('');
    app.innerHTML = `<div class="row" style="justify-content:space-between;margin-bottom:10px">
      <div><input type="text" id="ptitle" value="${esc(paper.title)}" style="font-size:18px;font-weight:600;width:420px"></div>
      <div class="row">
        <span class="muted">${qs.length} 题${bad ? `，<span style="color:var(--seal)">${bad} 题待核对</span>` : '，全部已核对'}</span>
        <button class="btn" id="llmf" ${d.llm && bad ? '' : 'disabled'} title="只把待核对的题送去重切">标红题重切</button>
        <button class="btn" id="llma" ${d.llm ? '' : 'disabled'}>整卷重切</button>
        <button class="btn" id="llmo" ${d.llm ? '' : 'disabled'}>OCR 整理</button>
        <button class="btn" id="save">保存草稿</button>
        <button class="btn primary" id="confirm">确认生成试卷</button>
      </div></div>
      <div class="review"><div class="qlist" id="qlist">${list}</div><div class="editor" id="editor"></div></div>`;
    $('#qlist').querySelectorAll('.q').forEach(el => el.onclick = () => { cur = +el.dataset.i; render(); });
    $('#ptitle').oninput = e => { paper.title = e.target.value; dirty = true; };
    $('#save').onclick = () => save(false);
    $('#confirm').onclick = async () => {
      if (bad && !await confirmBox(`还有 ${bad} 题标为待核对。确认生成后它们都按当前内容使用。继续？`, '生成')) return;
      await api(`/api/drafts/${id}/confirm`, json('POST', body()));
      toast('试卷已生成'); location.hash = `#/paper/${id}`;
    };
    const llm = (scope, label) => async () => {
      if (dirty) await save(true);
      if (!await confirmBox(label)) return;
      try { await runLLM(kind, id, scope); review(id); } catch (e) { toast('大模型失败：' + e.message, 5000); }
    };
    $('#llmf').onclick = llm('flagged', `把 ${bad} 道待核对题发送给大模型重切，其余不动。继续？`);
    $('#llma').onclick = llm('all', '把整卷原文发送给大模型重新切题，会覆盖当前全部题目（保留裁图）。继续？');
    $('#llmo').onclick = llm('ocr_tidy', '把整卷 OCR 文本发送给大模型修正错字并重切，会覆盖当前全部题目。继续？');
    renderEditor();
    const on = $('#qlist .q.on'); if (on) on.scrollIntoView({ block: 'nearest' });
  };
  const body = () => ({ title: paper.title, questions: paper.questions });
  const save = async (quiet) => {
    const r = await api(`/api/${kind}/${id}`, json('PUT', body()));
    paper.questions = r.paper.questions; paper.units = r.paper.units; dirty = false;
    if (!quiet) { toast('已保存'); render(); }
  };

  const renderEditor = () => {
    const q = paper.questions[cur];
    const ed = $('#editor');
    if (!q) { ed.innerHTML = '<p class="muted">没有题目</p>'; return; }
    const img = q.crop ? `<img class="crop" src="/assets/${id}/${encodeURIComponent(q.crop)}" alt="原文裁图">` : '';
    ed.innerHTML = `
      <div class="row" style="justify-content:space-between;margin-bottom:8px">
        <div><b>第 ${cur + 1} / ${paper.questions.length} 题</b> ${q.reviewed ? '<span class="tag ok">已核对</span>' : '<span class="tag seal">待核对</span>'}</div>
        <div class="row"><button class="btn small" id="prev">上一题</button><button class="btn small" id="next">下一题</button>
          <button class="btn small" id="merge" title="把本题的题干和选项并入上一题">并入上一题</button>
          <button class="btn small" id="add">在后面新增一题</button>
          <button class="btn small danger" id="del">删除本题</button></div></div>
      ${q.issues && q.issues.length ? `<div class="issues">${q.issues.map(esc).join('；')}</div>` : ''}
      ${img}
      <div class="inline">
        <div class="f"><label>单元</label><input type="text" id="e_unit" value="${esc(q.unit)}"></div>
        <div class="f"><label>题号</label><input type="number" id="e_no" value="${q.no}"></div>
        <div class="f"><label>题型</label><select id="e_type">${Object.entries(TYPE).map(([k, v]) => `<option value="${k}" ${q.type === k ? 'selected' : ''}>${v}</option>`).join('')}</select></div>
        <div class="f"><label>空数（填空题）</label><input type="number" id="e_blanks" value="${q.blanks || 0}" min="0"></div>
      </div>
      ${q.material !== undefined && q.material !== null ? `<div class="f"><label>材料（本组共用）</label><textarea id="e_material">${esc(q.material)}</textarea></div>` : ''}
      <div class="f"><label>题干</label><textarea id="e_stem" style="min-height:90px">${esc(q.stem)}</textarea></div>
      <div class="f"><label>选项 <label style="display:inline;font-size:12px"><input type="checkbox" id="e_image" ${q.image ? 'checked' : ''}> 图片题（作答时显示裁图，按字母选）</label></label>
        <div id="opts">${q.options.map((o, i) => `<div class="opt"><span class="L">${L(i)}</span><input type="text" data-o="${i}" value="${esc(o)}"><button class="btn small" data-ro="${i}" title="删除选项">×</button></div>`).join('')}</div>
        <button class="btn small" id="addopt">＋ 加选项</button></div>
      <div class="row"><button class="btn primary" id="ok">标为已核对并下一题</button><span class="kbd">Ctrl+Enter 同样效果</span></div>`;
    const upd = () => {
      q.unit = $('#e_unit').value.trim(); q.no = +$('#e_no').value || q.no; q.type = $('#e_type').value;
      q.blanks = +$('#e_blanks').value || 0; q.stem = $('#e_stem').value;
      if ($('#e_material')) q.material = $('#e_material').value;
      q.options = [...ed.querySelectorAll('[data-o]')].map(i => i.value);
      const wasImg = !!q.image; const img = $('#e_image').checked;
      if (img && !wasImg) q.image = q.crop || 'yes'; if (!img) q.image = null;
      dirty = true;
      const li = $('#qlist').querySelectorAll('.q')[cur]; if (li) li.querySelector('.s').textContent = q.stem || (q.image ? '[图片题]' : '');
    };
    ed.querySelectorAll('input,select,textarea').forEach(el => el.addEventListener('input', upd));
    ed.querySelectorAll('[data-ro]').forEach(b => b.onclick = () => { upd(); q.options.splice(+b.dataset.ro, 1); renderEditor(); });
    $('#addopt').onclick = () => { upd(); q.options.push(''); renderEditor(); };
    $('#prev').onclick = () => { if (cur > 0) { cur--; render(); } };
    $('#next').onclick = () => { if (cur < paper.questions.length - 1) { cur++; render(); } };
    $('#ok').onclick = () => { upd(); q.reviewed = true; q.issues = []; if (cur < paper.questions.length - 1) cur++; render(); };
    ed.onkeydown = e => { if (e.ctrlKey && e.key === 'Enter') { e.preventDefault(); $('#ok').click(); } };
    $('#del').onclick = async () => { if (!await confirmBox('删除本题？', '删除')) return; paper.questions.splice(cur, 1); cur = Math.min(cur, paper.questions.length - 1); dirty = true; render(); };
    $('#add').onclick = () => { upd(); paper.questions.splice(cur + 1, 0, { unit: q.unit, no: q.no + 1, type: 'single', stem: '', options: ['', '', '', ''], blanks: 0, image: null, crop: null, group: null, material: null, reviewed: false, issues: ['新增的题'], page: q.page, y0: q.y0, end_page: q.end_page, y1: q.y1, source: q.source }); cur++; dirty = true; render(); };
    $('#merge').onclick = () => {
      if (cur === 0) return toast('已是第一题');
      upd(); const p = paper.questions[cur - 1];
      p.stem = (p.stem + '\n' + q.stem).trim(); p.options = p.options.concat(q.options.filter(o => o));
      paper.questions.splice(cur, 1); cur--; dirty = true; render();
    };
  };
  render();
  window.onbeforeunload = () => dirty ? '有未保存的修改' : null;
}

/* ---------------- 试卷详情 ---------------- */
async function paperHome(id) {
  const d = await api(`/api/papers/${id}`);
  const a = await api(`/api/papers/${id}/attempts`);
  const p = d.paper, s = d.stats;
  app.innerHTML = `<h1>${esc(p.title)}</h1>
    <p class="muted">${s.count} 题 · ${Object.entries(s.types).map(([k, v]) => `${k} ${v}`).join('，')} · ${s.with_image} 题带图 · 来源 ${esc(p.source)}（${esc(p.import_path)}）</p>
    <div class="row"><a class="btn primary" href="#/paper/${id}/take">分题作答</a><a class="btn" href="#/paper/${id}/preview">整卷预览</a>
      <a class="btn" href="/api/papers/${id}/export.xlsx">导出试卷 Excel</a><button class="btn" id="reopen">回到校正页修改</button></div>
    <h2>历次作答</h2>
    ${a.attempts.length ? `<table><tr><th>提交时间</th><th>已作答</th><th></th></tr>${a.attempts.map(x => `<tr><td>${esc(x.submitted_at)}</td><td class="n">${x.answered} / ${x.total}</td><td><a href="#/paper/${id}/summary/${x.id}">查看汇总</a></td></tr>`).join('')}</table>` : '<p class="muted">还没有提交过。</p>'}`;
  $('#reopen').onclick = async () => { await api(`/api/papers/${id}/reopen`, { method: 'POST' }); location.hash = `#/review/${id}`; };
}

/* ---------------- 作答（整卷预览 / 分题） ---------------- */
let takeState = null;
const ANSWER_CACHE = {};   // 切换整卷预览 / 分题作答时在内存里保住作答记录，同时立即落盘
function stopTake() {
  if (takeState) { clearInterval(takeState.timer); clearTimeout(takeState.debounce); document.onkeydown = null; takeState.persist(); takeState = null; }
}

async function take(id, mode) {
  const d = await api(`/api/papers/${id}`);
  const saved = await api(`/api/papers/${id}/answers`);
  const p = d.paper, qs = p.questions;
  const cached = ANSWER_CACHE[id];
  const st = takeState = { answers: cached ? cached.answers : (saved.answers || {}), marks: new Set(cached ? cached.marks : (saved.marks || [])), cur: 0, dirty: !!cached, timer: null, debounce: null };
  ANSWER_CACHE[id] = { answers: st.answers, marks: [] };
  const materialOf = q => { if (!q.group) return null; const first = qs.find(x => x.group === q.group && (x.material || x.material_crop)); return first ? (first.material || '') : null; };
  const materialImg = q => { if (!q.group) return ''; const first = qs.find(x => x.group === q.group && x.material_crop); return first ? `<img class="pic" src="/assets/${id}/${encodeURIComponent(first.material_crop)}" alt="材料原图">` : ''; };
  const persist = async () => { if (ANSWER_CACHE[id]) ANSWER_CACHE[id].marks = [...st.marks]; if (!st.dirty) return; st.dirty = false; try { await api(`/api/papers/${id}/answers`, json('PUT', { answers: st.answers, marks: [...st.marks], mode })); } catch (e) { st.dirty = true; } };
  st.persist = persist;
  st.timer = setInterval(persist, 10000);
  const touch = () => { st.dirty = true; if (ANSWER_CACHE[id]) ANSWER_CACHE[id].marks = [...st.marks]; clearTimeout(st.debounce); st.debounce = setTimeout(persist, 1500); };
  const set = (q, v) => { st.answers[key(q)] = v; touch(); };
  const answered = q => { const a = st.answers[key(q)]; if (a == null) return false; if (Array.isArray(a)) return a.some(x => x && String(x).trim()); return String(a).trim() !== ''; };

  const optionsHtml = (q, i) => {
    const a = st.answers[key(q)];
    const pic = q.image ? `<img class="pic" src="/assets/${id}/${encodeURIComponent(q.image)}" alt="题图">` : '';
    if (q.type === 'single' || q.type === 'multi' || (q.type === 'judge' && q.options.length)) {
      const sel = new Set(Array.isArray(a) ? a : (a ? [a] : []));
      return pic + `<div class="opts" data-i="${i}">${q.options.map((o, k) => `<div class="o ${sel.has(L(k)) ? 'on' : ''}" data-k="${k}"><span class="L">${L(k)}</span><span>${esc(o)}</span><span class="k">${k + 1}</span></div>`).join('')}</div>`;
    }
    if (q.type === 'judge') {
      return pic + `<div class="opts" data-i="${i}">${['正确', '错误'].map((o, k) => `<div class="o ${a === o ? 'on' : ''}" data-v="${o}"><span class="L">${k + 1}</span><span>${o}</span></div>`).join('')}</div>`;
    }
    if (q.type === 'blank') {
      const vals = Array.isArray(a) ? a : [];
      const n = Math.max(1, q.blanks || 1);
      return pic + `<div class="blanks" data-i="${i}">${Array.from({ length: n }, (_, k) => `<div><span class="muted">第 ${k + 1} 空</span> <input type="text" data-b="${k}" value="${esc(vals[k] || '')}" autocomplete="off"></div>`).join('')}</div>`;
    }
    return pic + `<div class="blanks" data-i="${i}"><textarea data-b="0" style="max-width:640px">${esc(Array.isArray(a) ? a[0] : (a || ''))}</textarea></div>`;
  };
  const bind = (root) => {
    root.querySelectorAll('.opts .o').forEach(el => el.onclick = () => {
      const q = qs[+el.parentElement.dataset.i];
      if (el.dataset.v !== undefined) { set(q, el.dataset.v); }
      else {
        const letter = L(+el.dataset.k);
        if (q.type === 'multi') { const cur = new Set(st.answers[key(q)] || []); cur.has(letter) ? cur.delete(letter) : cur.add(letter); set(q, [...cur].sort()); }
        else set(q, letter);
      }
      refresh();
    });
    root.querySelectorAll('.blanks [data-b]').forEach(el => el.oninput = () => {
      const q = qs[+el.parentElement.parentElement.dataset.i] || qs[+el.parentElement.dataset.i];
      const box = el.closest('.blanks');
      const vals = [...box.querySelectorAll('[data-b]')].map(x => x.value);
      set(qs[+box.dataset.i], vals); refreshCard();
    });
  };
  const cardHtml = () => {
    let h = '', lastUnit = null;
    qs.forEach((q, i) => {
      if (q.unit !== lastUnit) { lastUnit = q.unit; h += `${h ? '</div>' : ''}<div class="u">${esc(q.unit || '全部')}</div><div class="nums">`; }
      else if (i === 0) h += '<div class="nums">';
      h += `<div class="n ${answered(q) ? 'done' : ''} ${st.marks.has(key(q)) ? 'mark' : ''} ${mode === 'take' && i === st.cur ? 'cur' : ''}" data-j="${i}">${q.no}</div>`;
    });
    return h + '</div>';
  };
  const submitFlow = async () => {
    await persist();
    const c = await api(`/api/papers/${id}/check`, json('POST', { answers: st.answers, marks: [...st.marks] }));
    const go = async () => { const r = await api(`/api/papers/${id}/submit`, json('POST', { answers: st.answers, marks: [...st.marks] })); delete ANSWER_CACHE[id]; st.dirty = false; closeModal(); location.hash = `#/paper/${id}/summary/${r.id}`; };
    if (c.unanswered.length) {
      const m = modal(`<h3 style="margin-top:0">还有 ${c.unanswered.length} 题未作答</h3><p style="word-break:break-all">${c.unanswered.map(esc).join('、')}</p>
        <div class="row" style="justify-content:flex-end"><button class="btn" id="back">返回补做</button><button class="btn primary" id="go">直接提交</button></div>`);
      $('#back', m).onclick = () => { closeModal(); const first = qs.findIndex(q => !answered(q)); if (mode === 'take' && first >= 0) { st.cur = first; refresh(); } };
      $('#go', m).onclick = go;
    } else if (await confirmBox(`全部 ${c.total} 题已作答，提交并生成汇总？`, '提交')) go();
  };

  const refreshCard = () => { const c = $('#acard'); if (c) { c.innerHTML = cardHtml(); c.querySelectorAll('.n').forEach(el => el.onclick = () => jump(+el.dataset.j)); } };
  const jump = (j) => { if (mode === 'take') { st.cur = j; refresh(); } else { const el = app.querySelector(`.sheet .q[data-i="${j}"]`); el && el.scrollIntoView({ behavior: 'smooth', block: 'start' }); } };
  const refresh = () => { if (mode === 'take') renderTake(); else { app.querySelectorAll('.sheet .q').forEach(box => { const i = +box.dataset.i; const q = qs[i]; box.querySelector('.ans').innerHTML = optionsHtml(q, i); bind(box); box.querySelector('.mk').textContent = st.marks.has(key(q)) ? '★ 已标记' : '☆ 标记'; }); refreshCard(); } };

  const side = `<div class="card-side"><div class="acard"><div class="row" style="justify-content:space-between"><b>答题卡</b><span class="muted" id="cnt"></span></div><div id="acard">${cardHtml()}</div>
    <div class="legend"><span class="n done" style="display:inline-block;width:22px"></span> 已答 　<span class="n mark" style="display:inline-block;width:22px"></span> 标记 　<span class="n" style="display:inline-block;width:22px"></span> 未答</div></div>
    <div class="bar"><button class="btn primary" id="submit">提交汇总</button><a class="btn" href="#/paper/${id}/${mode === 'take' ? 'preview' : 'take'}">${mode === 'take' ? '整卷预览' : '分题作答'}</a></div></div>`;

  const renderTake = () => {
    const q = qs[st.cur], i = st.cur;
    const mat = materialOf(q);
    app.innerHTML = `<div class="take"><div>
      <div class="qbox"><div class="head"><span>${esc(q.unit || p.title)} · 第 ${q.no} 题 · ${TYPE[q.type]}${q.type === 'multi' ? '（可多选）' : ''}</span><button class="btn small" id="mark">${st.marks.has(key(q)) ? '★ 已标记' : '☆ 标记'}</button></div>
        ${mat !== null ? `${mat ? `<details class="material" ${materialImg(q) ? '' : 'open'}><summary>材料文字（点开 / 收起）</summary>${esc(mat)}</details>` : ''}${materialImg(q)}` : ''}
        <div class="stem"><span class="muted">${q.no}.</span> ${esc(q.stem)}</div>
        <div class="ans">${optionsHtml(q, i)}</div></div>
      <div class="bar"><button class="btn" id="prev" ${i === 0 ? 'disabled' : ''}>上一题</button><button class="btn" id="next" ${i === qs.length - 1 ? 'disabled' : ''}>下一题</button>
        <span class="sp"></span><span class="kbd">数字键选选项 · Enter 下一题 · ← → 切题 · M 标记</span></div>
      </div>${side}</div>`;
    bind(app);
    $('#prev').onclick = () => { st.cur--; refresh(); };
    $('#next').onclick = () => { st.cur++; refresh(); };
    $('#mark').onclick = () => { const k = key(q); st.marks.has(k) ? st.marks.delete(k) : st.marks.add(k); touch(); refresh(); };
    $('#submit').onclick = submitFlow;
    refreshCard(); $('#cnt').textContent = `${qs.filter(answered).length} / ${qs.length}`;
    const firstInput = app.querySelector('.blanks input,.blanks textarea'); if (firstInput) firstInput.focus();
  };
  const renderPreview = () => {
    let lastUnit = null;
    app.innerHTML = `<div class="take"><div class="sheet"><h1>${esc(p.title)}</h1>
      ${qs.map((q, i) => { let h = ''; if (q.unit !== lastUnit) { lastUnit = q.unit; h += `<div class="unit">${esc(q.unit)}</div>`; }
        const mat = (q.group && qs.find(x => x.group === q.group) === q) ? (q.material || '') : null;
        return h + `${mat !== null ? `${mat ? `<details class="material" ${materialImg(q) ? '' : 'open'}><summary>材料文字（点开 / 收起）</summary>${esc(mat)}</details>` : ''}${materialImg(q)}` : ''}<div class="q" data-i="${i}"><div class="qhead"><div class="stem"><span class="no">${q.no}.</span>${esc(q.stem)} <span class="muted">[${TYPE[q.type]}]</span></div><button class="btn small mk">${st.marks.has(key(q)) ? '★ 已标记' : '☆ 标记'}</button></div><div class="ans">${optionsHtml(q, i)}</div></div>`; }).join('')}
      </div>${side}</div>`;
    bind(app);
    app.querySelectorAll('.sheet .q .mk').forEach(b => b.onclick = () => { const q = qs[+b.closest('.q').dataset.i]; const k = key(q); st.marks.has(k) ? st.marks.delete(k) : st.marks.add(k); touch(); refresh(); });
    $('#submit').onclick = submitFlow;
    refreshCard();
  };
  document.onkeydown = e => {
    if (mode !== 'take' || e.target.matches('input,textarea') && !(e.key === 'Enter' && e.target.matches('input'))) return;
    const q = qs[st.cur];
    if (/^[1-7]$/.test(e.key) && (q.type === 'single' || q.type === 'multi' || q.type === 'judge')) {
      const el = app.querySelectorAll('.opts .o')[+e.key - 1]; if (el) { el.click(); if (q.type !== 'multi') { } } e.preventDefault();
    } else if (e.key === 'Enter' || e.key === 'ArrowRight') { if (st.cur < qs.length - 1) { st.cur++; refresh(); } e.preventDefault(); }
    else if (e.key === 'ArrowLeft') { if (st.cur > 0) { st.cur--; refresh(); } e.preventDefault(); }
    else if (e.key.toLowerCase() === 'm') { $('#mark').click(); }
  };
  if (mode === 'take') renderTake(); else renderPreview();
  window.onbeforeunload = () => { persist(); return null; };
}

/* ---------------- 汇总 ---------------- */
async function summary(id, ts) {
  const a = await api(`/api/papers/${id}/attempts/${ts}`);
  const d = await api(`/api/papers/${id}`);
  const rows = a.rows;
  const hasUnit = rows.some(r => r.unit);
  app.innerHTML = `<h1>答案汇总</h1><p class="muted">${esc(d.paper.title)} · 提交于 ${esc(a.submitted_at)} · 已作答 ${rows.filter(r => r.answer).length} / ${rows.length}${a.unanswered.length ? ` · <span style="color:var(--seal)">未作答：${a.unanswered.map(esc).join('、')}</span>` : ''}</p>
    <div class="row" style="margin-bottom:10px"><button class="btn primary" id="copy">一键复制</button><a class="btn" href="/api/papers/${id}/attempts/${ts}/export.xlsx">导出 Excel</a><a class="btn" href="#/paper/${id}">返回试卷</a></div>
    <div class="sum"><table><tr>${hasUnit ? '<th>单元</th>' : ''}<th>题号</th><th>题型</th><th>我的答案</th><th>标记</th></tr>
    ${rows.map(r => `<tr>${hasUnit ? `<td>${esc(r.unit)}</td>` : ''}<td class="n">${r.no}</td><td>${esc(r.type)}</td><td class="${r.answer ? '' : 'miss'}">${r.answer ? esc(r.answer) : '未作答'}</td><td>${r.marked ? '★' : ''}</td></tr>`).join('')}</table></div>`;
  $('#copy').onclick = async () => {
    const text = [(hasUnit ? '单元\t' : '') + '题号\t题型\t我的答案'].concat(rows.map(r => `${hasUnit ? r.unit + '\t' : ''}${r.no}\t${r.type}\t${r.answer || '未作答'}`)).join('\n');
    try { await navigator.clipboard.writeText(text); toast('已复制到剪贴板'); } catch (e) { modal(`<textarea style="min-height:300px">${esc(text)}</textarea>`); }
  };
}

/* ---------------- 设置 ---------------- */
async function settings() {
  const s = await api('/api/settings');
  app.innerHTML = `<h1>设置</h1><div class="card" style="max-width:640px">
    <h3 style="margin-top:0">大模型（商汤网关，OpenAI 兼容）</h3>
    <label><input type="checkbox" id="en" ${s.llm_enabled ? 'checked' : ''}> 启用大模型。关闭时程序不会发出任何外部请求。</label>
    <div class="f" style="margin-top:10px"><label class="muted">接口地址</label><input type="text" id="url" value="${esc(s.llm_base_url)}"></div>
    <div class="f"><label class="muted">密钥（留原样表示不改）</label><input type="password" id="key" value="${esc(s.llm_api_key)}"></div>
    <div class="f"><label class="muted">模型名</label><input type="text" id="model" value="${esc(s.llm_model)}"></div>
    <h3>浏览器</h3>
    <label><input type="checkbox" id="appwin" ${s.app_window ? 'checked' : ''}> 应用窗口模式（下次启动生效：用 Edge / Chrome 无地址栏窗口打开，更像考试软件）</label>
    <div class="row" style="margin-top:14px"><button class="btn primary" id="save">保存</button><button class="btn" id="ping">测试连接</button><span class="muted" id="msg"></span></div></div>`;
  $('#save').onclick = async () => {
    await api('/api/settings', json('PUT', { llm_enabled: $('#en').checked, llm_base_url: $('#url').value, llm_api_key: $('#key').value, llm_model: $('#model').value, app_window: $('#appwin').checked }));
    toast('已保存'); settings();
  };
  $('#ping').onclick = async () => { $('#msg').textContent = '连接中…'; const r = await api('/api/settings/ping', { method: 'POST' }); $('#msg').textContent = r.ok ? '连接正常：' + r.reply : '失败：' + r.error; };
}
