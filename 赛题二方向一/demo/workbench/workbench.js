'use strict';

(() => {
  const $ = (id) => document.getElementById(id);
  const ui = {
    modeProtocol: $('mode-protocol'), modeDeepseek: $('mode-deepseek'), modeNote: $('mode-note'),
    connectionDot: $('connection-dot'), connectionLabel: $('connection-label'), reconnect: $('reconnect'),
    alert: $('service-alert'), revision: $('revision-label'), calls: $('metric-calls'), repairs: $('metric-repairs'),
    evidenceMetric: $('metric-evidence'), models: $('metric-models'), taskId: $('task-id'), goal: $('goal'),
    preset: $('preset'), reset: $('reset-task'), scope: $('scope-label'), window: $('window-label'),
    missing: $('toggle-missing'), archive: $('toggle-archive'), changeData: $('change-data'), openScope: $('open-scope'), scopeControls: $('scope-controls'),
    statePill: $('state-pill'), step: $('step'), auto: $('auto-run'), runStatus: $('run-status'),
    feedback: $('feedback'), feedbackCode: $('feedback-code'), feedbackIcon: $('feedback-icon'),
    feedbackTitle: $('feedback-title'), feedbackMessage: $('feedback-message'), feedbackFacts: $('feedback-facts'),
    feedbackOptions: $('feedback-options'), decision: $('decision'), decisionLabel: $('decision-label'),
    decisionReason: $('decision-reason'), decisionTool: $('decision-tool'), decisionModel: $('decision-model'),
    trace: $('trace'), traceCount: $('trace-count'), evidence: $('evidence'), evidenceCount: $('evidence-count'),
    evidenceVersion: $('evidence-version'), weight: $('east-weight'), east: $('east-value'), south: $('south-value'),
    weight20: $('weight-20'), weight80: $('weight-80'), weightNote: $('weight-note'), reuse: $('reuse-note'),
    comparison: $('comparison'), rateA: $('rate-a'), rateB: $('rate-b'), barA: $('rate-bar-a'), barB: $('rate-bar-b'),
    reading: $('comparison-reading'), coverage: $('comparison-coverage'), claim: $('claim-card'),
    claimStatus: $('claim-status'), claimSummary: $('claim-summary'), conditions: $('claim-conditions'),
    unresolved: $('claim-unresolved'), finalize: $('finalize'), export: $('export'), footer: $('footer-status'),
    announcement: $('announcement')
  };

  const stateLabels = {
    needs_evidence: {label: '需要取证', title: '从数据请求继续任务', tone: 'neutral'},
    needs_repair: {label: '需要修复', title: '冲突已定位，任务可以继续', tone: 'warning'},
    needs_clarification: {label: '等待选择', title: '证据不足，需要你的明确选择', tone: 'warning'},
    ready: {label: '可以定稿', title: '比较证据已齐备', tone: 'good'},
    finalized: {label: '结论已定稿', title: '描述性结论已完成', tone: 'good'},
    stale: {label: '证据已失效', title: '数据版本改变，需要重新取证', tone: 'warning'}
  };
  let currentState = null;
  let mode = 'protocol';
  let connected = false;
  let busy = false;
  let autoRunning = false;
  let autoStopRequested = false;
  let autoCount = 0;
  let goalDirty = false;
  let weightDirty = false;
  let reuseMessage = '';
  let lastStatus = '';

  function element(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined && text !== null) node.textContent = String(text);
    return node;
  }

  function plain(value) {
    if (value === undefined || value === null) return '—';
    if (typeof value === 'object') return JSON.stringify(value);
    return String(value);
  }

  function numeric(value) {
    return typeof value === 'number' && Number.isFinite(value);
  }

  function decimal(value, digits = 2) {
    return numeric(value) ? new Intl.NumberFormat('zh-CN', {maximumFractionDigits: digits}).format(value) : '—';
  }

  function percent(value) {
    return numeric(value) ? decimal(value * 100) + '%' : '—';
  }

  function announce(message) {
    ui.announcement.textContent = message;
  }

  function detail(title, value) {
    const details = element('details', 'json-details');
    details.append(element('summary', '', title));
    const pre = element('pre');
    const code = element('code', '', typeof value === 'string' ? value : JSON.stringify(value, null, 2));
    pre.append(code);
    details.append(pre);
    return details;
  }

  function signalConnection(value) {
    connected = value;
    ui.connectionDot.className = 'connection-dot ' + (value ? 'online' : 'offline');
    ui.connectionLabel.textContent = value ? '本地后端已连接' : '后端尚未连接';
    ui.footer.textContent = value ? '本地执行 · API 响应已接入' : '需要启动本地服务';
  }

  function showError(error) {
    ui.alert.replaceChildren();
    const title = element('strong', '', '请求未完成。');
    ui.alert.append(title, document.createTextNode(' ' + (error.message || '无法连接本地服务。')));
    if (!connected || !currentState) {
      ui.alert.append(document.createElement('br'), document.createTextNode('请在项目目录启动 '),
        element('code', '', 'python scripts/run_workbench.py'), document.createTextNode('，再通过服务地址打开此页面并重新连接。'));
    }
    ui.alert.hidden = false;
    ui.runStatus.textContent = '请求失败 · 可重新连接';
    announce('请求未完成：' + error.message);
  }

  async function request(path, body) {
    const controller = new AbortController();
    const timeout = window.setTimeout(() => controller.abort(), 180000);
    try {
      const response = await fetch(path, {
        method: body === undefined ? 'GET' : 'POST',
        headers: body === undefined ? {Accept: 'application/json'} : {'Content-Type': 'application/json', Accept: 'application/json'},
        body: body === undefined ? undefined : JSON.stringify(body),
        signal: controller.signal,
        cache: 'no-store'
      });
      const text = await response.text();
      let payload;
      try { payload = JSON.parse(text); }
      catch (_) { throw new Error('后端没有返回有效的 JSON。请确认页面由 run_workbench.py 提供服务。'); }
      if (!response.ok) {
        const failure = payload.error || payload.message || ('HTTP ' + response.status);
        throw new Error(typeof failure === 'object' ? plain(failure) : String(failure));
      }
      const state = payload.task ? payload : payload.state;
      if (!state || typeof state !== 'object' || !state.task || !Array.isArray(state.trace)) {
        throw new Error('返回数据缺少任务状态或真实执行轨迹。');
      }
      signalConnection(true);
      ui.alert.hidden = true;
      return state;
    } catch (error) {
      if (error.name === 'AbortError') throw new Error('等待后端超过 3 分钟。请求可能仍在服务端执行，请重新连接查看真实状态。');
      if (error instanceof TypeError) {
        signalConnection(false);
        throw new Error('无法访问同源 /api 服务。');
      }
      throw error;
    } finally {
      window.clearTimeout(timeout);
    }
  }

  function updateControls() {
    const blocked = busy || autoRunning || !connected;
    ui.reset.disabled = blocked;
    ui.preset.disabled = busy || autoRunning;
    ui.goal.disabled = busy || autoRunning;
    const stopped = currentState && (['finalized', 'needs_clarification'].includes(currentState.state) || (currentState.state === 'ready' && Boolean(currentState.comparison)));
    ui.step.disabled = blocked || !currentState || ['finalized', 'needs_clarification'].includes(currentState.state);
    ui.step.textContent = currentState && currentState.state === 'ready' && currentState.comparison ? '由规划器定稿 →' : '执行下一步 →';
    ui.auto.disabled = !autoRunning && (blocked || !currentState || stopped);
    ui.auto.textContent = autoRunning ? (autoStopRequested ? '完成本次后停止' : '停止自动运行') : '自动运行 ↗';
    ui.modeProtocol.disabled = busy || autoRunning;
    ui.modeDeepseek.disabled = busy || autoRunning;
    ui.reconnect.disabled = busy || autoRunning;
    for (const control of [ui.missing, ui.archive, ui.changeData, ui.openScope, ui.weight, ui.weight20, ui.weight80]) {
      control.disabled = blocked || !currentState;
    }
    ui.finalize.disabled = blocked || !currentState || currentState.state !== 'ready' || !currentState.comparison;
    for (const button of ui.feedbackOptions.querySelectorAll('button')) button.disabled = blocked;
    ui.export.setAttribute('aria-disabled', String(!connected || !currentState || busy || autoRunning));
    $('workspace').setAttribute('aria-busy', String(busy));
  }

  function setMode(next) {
    mode = next;
    for (const [button, key] of [[ui.modeProtocol, 'protocol'], [ui.modeDeepseek, 'deepseek']]) {
      button.classList.toggle('selected', mode === key);
      button.setAttribute('aria-pressed', String(mode === key));
    }
    ui.modeNote.textContent = mode === 'deepseek' ? '外部 DeepSeek API · 独立计费 · 每步真实调用' : '有限确定性策略 · 未调用语言模型';
    announce(mode === 'deepseek' ? '已选择真实 DeepSeek，后续执行通过外部 API 独立计费。' : '已选择协议规划，采用有限确定性策略。');
  }

  function drawWeight(value, preview = false) {
    const east = Math.round(Number(value));
    ui.weight.value = String(east);
    ui.weight.style.setProperty('--split', east + '%');
    ui.weight.setAttribute('aria-valuetext', '华东 ' + east + '%，华南 ' + (100 - east) + '%');
    ui.east.replaceChildren(document.createTextNode(String(east)), element('span', '', '%'));
    ui.south.replaceChildren(document.createTextNode(String(100 - east)), element('span', '', '%'));
    for (const [button, preset] of [[ui.weight20, 20], [ui.weight80, 80]]) {
      button.classList.toggle('active', east === preset);
      button.setAttribute('aria-pressed', String(east === preset));
    }
    ui.weightNote.textContent = preview ? '待提交的新目标。松开滑块后由后端重新计算；下方仍是当前结果。' : '修改的是任务目标；原始区域计数无需再次获取。';
  }

  function renderFeedback(state) {
    const feedback = state.feedback || {};
    const status = stateLabels[state.state] || {label: plain(state.state), title: '查看平台反馈', tone: 'neutral'};
    ui.statePill.className = 'status-pill ' + status.tone;
    ui.statePill.textContent = state.state === 'ready' && !state.comparison ? '可以计算' : status.label;
    ui.feedback.className = 'feedback ' + status.tone;
    ui.feedbackCode.textContent = feedback.code || state.state || 'PLATFORM FEEDBACK';
    ui.feedbackIcon.textContent = status.tone === 'warning' ? '↻' : status.tone === 'good' ? '✓' : '↗';
    ui.feedbackTitle.textContent = state.state === 'ready' && !state.comparison ? '计数齐备，复用证据继续计算' : status.title;
    ui.feedbackMessage.textContent = feedback.message || '平台尚未提供额外反馈。';
    ui.feedbackFacts.replaceChildren();
    const missing = Array.isArray(feedback.missing) ? feedback.missing : [];
    for (const item of missing) {
      ui.feedbackFacts.append(element('span', 'fact', (item.carrier ? item.carrier + ' · ' : '') + (item.region || '区域未知') + '缺证' + (numeric(item.weight) ? ' / 目标权重 ' + percent(item.weight) : '')));
    }
    const conflicts = Array.isArray(feedback.conflicts) ? feedback.conflicts : [];
    if (conflicts.length) ui.feedbackFacts.append(detail('查看 ' + conflicts.length + ' 项实际冲突', conflicts));
    if (Array.isArray(feedback.counterexamples) && feedback.counterexamples.length) ui.feedbackFacts.append(detail('查看平台反例', feedback.counterexamples));
    ui.feedbackOptions.replaceChildren();
    const options = Array.isArray(feedback.options) ? feedback.options : [];
    for (const option of options) {
      if (!option.tool || option.tool === 'finalize_claim') continue;
      const button = element('button', 'button secondary', option.label || option.tool);
      button.type = 'button';
      button.title = option.tool + ' ' + plain(option.arguments || {});
      if (option.tool === 'authorize_scope') button.setAttribute('aria-label', (option.label || '授权缩小范围') + '。这是对任务范围的明确授权。');
      button.addEventListener('click', () => perform('/api/action', {tool: option.tool, arguments: option.arguments || {}}, option.tool === 'authorize_scope' ? '提交你的范围授权' : '执行选定的恢复动作'));
      ui.feedbackOptions.append(button);
    }
    if (options.some((option) => option.tool === 'authorize_scope')) {
      ui.feedbackOptions.append(element('p', 'option-help', '缩小范围需要你的明确授权。选择后，结论只覆盖获准区域；未覆盖区域仍保留为缺口。'));
    }
  }

  function renderDecision(state) {
    const decision = state.last_decision;
    ui.decision.hidden = !decision;
    if (!decision) return;
    ui.decisionLabel.textContent = decision.mode === 'deepseek' ? '模型返回的选择理由' : decision.mode === 'human' ? '你的明确选择' : '有限协议的选择依据';
    ui.decisionReason.textContent = decision.reason || '后端未返回理由摘要。';
    ui.decisionTool.textContent = (decision.tool || '—') + ' ' + plain(decision.arguments || {});
    ui.decisionModel.textContent = decision.model || (decision.mode === 'protocol' ? 'deterministic protocol' : plain(decision.mode));
  }

  function traceTone(status) {
    const text = String(status || '').toLowerCase();
    if (/(conflict|invalid|missing|stale|blocked|reject|error|repair|incomplete|needs)/.test(text)) return 'warning';
    if (/(ok|success|valid|ready|complete|repaired|finalized)/.test(text)) return 'good';
    return '';
  }

  function renderTrace(state) {
    const traces = state.trace;
    const openSteps = new Set(Array.from(ui.trace.querySelectorAll('details[open]')).map((node) => node.dataset.traceKey));
    ui.traceCount.textContent = String(traces.length);
    ui.trace.replaceChildren();
    if (!traces.length) {
      const empty = element('div', 'empty-state');
      empty.append(element('span', 'empty-icon', '↗'), element('p', '', '请求已准备好。'), element('small', '', '执行下一步，查看平台如何获取证据与恢复任务。'));
      ui.trace.append(empty);
      return;
    }
    // Most recent first keeps the actual recovery decision visible without an animated timeline.
    [...traces].reverse().forEach((trace, index) => {
      const card = element('article', 'trace-card');
      const heading = element('div', 'trace-heading');
      const actor = element('span', 'trace-actor');
      actor.append(element('span', 'trace-step', String(trace.step ?? traces.length - index).padStart(2, '0')), document.createTextNode(trace.actor || 'platform'));
      heading.append(actor, element('span', 'trace-status ' + traceTone(trace.result_status), trace.result_status || '返回状态未提供'));
      card.append(heading, element('h4', 'trace-tool', trace.tool || '未提供工具名'), element('p', 'trace-summary', trace.summary || '后端未提供调用摘要。'));
      card.append(element('p', 'trace-args', plain(trace.arguments || {})));
      const raw = detail('参数 / 返回结果 / 决策 JSON', trace);
      raw.dataset.traceKey = String(trace.step ?? traces.length - index) + ':' + (trace.tool || '');
      raw.open = openSteps.has(raw.dataset.traceKey);
      card.append(raw);
      ui.trace.append(card);
    });
  }

  function evidenceSql(evidence, trace) {
    if (Array.isArray(evidence.queries) && evidence.queries.some((query) => typeof query.sql === 'string')) return evidence.queries;
    if (typeof evidence.sql === 'string') return evidence.sql;
    if (evidence.result && typeof evidence.result.sql === 'string') return evidence.result.sql;
    for (let index = trace.length - 1; index >= 0; index--) {
      const result = trace[index].result;
      if (!result || typeof result !== 'object') continue;
      const candidate = result.evidence || result;
      const candidates = Array.isArray(candidate) ? candidate : [candidate];
      for (const item of candidates) {
        if (!item || item.id !== evidence.id) continue;
        if (typeof item.sql === 'string') return item.sql;
        if (typeof result.sql === 'string') return result.sql;
      }
    }
    return null;
  }

  function renderEvidence(state) {
    const evidence = Array.isArray(state.evidence) ? state.evidence : [];
    const valid = evidence.filter((item) => item.valid === true);
    ui.evidenceCount.textContent = String(evidence.length);
    ui.evidenceMetric.textContent = String(valid.length);
    ui.evidenceVersion.textContent = valid.length + ' 有效 / ' + (evidence.length - valid.length) + ' 失效或未验证';
    const openEvidence = new Set(Array.from(ui.evidence.querySelectorAll('details[open]')).map((node) => node.dataset.evidenceKey));
    ui.evidence.replaceChildren();
    if (!evidence.length) {
      ui.evidence.append(element('p', 'empty-evidence', '尚未获取数据证据'));
      return;
    }
    for (const item of evidence) {
      const incompatible = item.valid === true && item.variant !== state.task.required_variant;
      const card = element('article', 'evidence-card' + (item.valid === true ? '' : ' stale') + (incompatible ? ' incompatible' : ''));
      const heading = element('div', 'evidence-heading');
      heading.append(element('strong', '', '承运商 ' + (item.carrier || '—')), element('span', 'evidence-status', incompatible ? '口径不符' : item.valid === true ? '版本有效' : item.valid === false ? '已失效' : '未验证'));
      card.append(heading, element('p', 'evidence-meta', plain(item.id) + ' · v' + plain(item.revision)), element('p', 'evidence-contract', (item.variant === 'delivered_only' ? '已妥投口径' : plain(item.variant)) + ' · ' + plain(item.source)));
      if (item.time_window) card.append(element('p', 'evidence-meta', plain(item.time_window)));
      if (Array.isArray(item.rows) && item.rows.length) {
        const table = element('table', 'evidence-table');
        table.setAttribute('aria-label', '承运商 ' + plain(item.carrier) + ' 的原始区域证据');
        const head = element('thead');
        const headerRow = element('tr');
        for (const label of ['区域', item.variant === 'delivered_only' ? '已妥投' : '分母', '超时', '超时率']) {
          const cell = element('th', '', label); cell.scope = 'col'; headerRow.append(cell);
        }
        head.append(headerRow);
        const body = element('tbody');
        for (const row of item.rows) {
          const tr = element('tr');
          const denominator = item.variant === 'delivered_only' ? row.delivered : row.total;
          for (const value of [row.region, decimal(denominator, 0), decimal(row.delayed, 0), percent(row.rate)]) tr.append(element('td', '', value));
          body.append(tr);
        }
        table.append(head, body); card.append(table);
      }
      const raw = detail('完整证据 JSON', item);
      raw.dataset.evidenceKey = String(item.id) + ':json'; raw.open = openEvidence.has(raw.dataset.evidenceKey);
      card.append(raw);
      const sql = evidenceSql(item, state.trace);
      if (sql) {
        const sqlDetail = detail('实际执行 SQL', sql);
        sqlDetail.dataset.evidenceKey = String(item.id) + ':sql'; sqlDetail.open = openEvidence.has(sqlDetail.dataset.evidenceKey);
        card.append(sqlDetail);
      }
      ui.evidence.append(card);
    }
    const windows = [...new Set(valid.map((item) => plain(item.time_window)).filter((value) => value !== '—'))];
    ui.window.textContent = windows.length === 1 ? windows[0] : windows.length > 1 ? '多个窗口，见证据' : '以证据为准';
  }

  function drawRate(node, value) {
    node.replaceChildren();
    if (numeric(value)) node.append(document.createTextNode(decimal(value * 100)), element('small', '', '%'));
    else node.textContent = '—';
  }

  function renderComparison(state) {
    const comparison = state.comparison;
    const stale = state.state === 'stale';
    ui.comparison.classList.toggle('stale', Boolean(stale));
    if (!comparison || !comparison.rates) {
      drawRate(ui.rateA, null); drawRate(ui.rateB, null);
      ui.barA.style.width = '0%'; ui.barB.style.width = '0%';
      ui.reading.textContent = state.state === 'needs_clarification' ? '当前证据不足以完成目标范围的比较。' : '证据齐备后，由后端计算比较结果。';
      ui.coverage.textContent = '';
      return;
    }
    drawRate(ui.rateA, comparison.rates.A); drawRate(ui.rateB, comparison.rates.B);
    // Bars only encode backend-returned rates; no carrier or aggregate rates are calculated here.
    const scale = Math.max(comparison.rates.A || 0, comparison.rates.B || 0, 0.001) * 1.15;
    ui.barA.style.width = numeric(comparison.rates.A) ? Math.max(0, Math.min(100, comparison.rates.A / scale * 100)) + '%' : '0%';
    ui.barB.style.width = numeric(comparison.rates.B) ? Math.max(0, Math.min(100, comparison.rates.B / scale * 100)) + '%' : '0%';
    const better = comparison.better_carrier;
    const difference = numeric(comparison.difference_pp) ? ' · 相差 ' + decimal(Math.abs(comparison.difference_pp)) + ' 个百分点' : '';
    ui.reading.textContent = stale ? '历史比较已过期，不能用于当前版本定稿。' : better === 'A' || better === 'B' ? better + ' 的描述性超时率更低' + difference : better === 'tie' || better === null ? '在当前目标构成下，两者超时率相同。' : '比较已返回，请查看实际结论。';
    const coverage = comparison.coverage;
    let coverageText = '';
    if (Array.isArray(coverage)) coverageText = '覆盖：' + coverage.map(plain).join(' / ');
    else if (numeric(coverage)) coverageText = '目标覆盖 ' + percent(coverage);
    else if (coverage !== undefined && coverage !== null) coverageText = '覆盖：' + plain(coverage);
    if (comparison.weights) coverageText += (coverageText ? ' · ' : '') + '实际权重 ' + Object.entries(comparison.weights).map(([region, weight]) => region + ' ' + percent(weight)).join(' / ');
    ui.coverage.textContent = coverageText;
  }

  function conditionLabels(conditions) {
    if (Array.isArray(conditions)) return conditions.map(plain);
    if (conditions && typeof conditions === 'object') return Object.entries(conditions).map(([key, value]) => key + ': ' + plain(value));
    return conditions ? [plain(conditions)] : [];
  }

  function renderClaim(state) {
    const claim = state.claim;
    const stale = state.state === 'stale' || (claim && claim.valid === false);
    const tone = stale ? 'warning' : claim && claim.valid === true ? 'good' : state.state === 'ready' ? 'good' : 'neutral';
    ui.claim.className = 'claim-card ' + tone;
    ui.claimStatus.textContent = stale ? state.state === 'ready' && state.comparison ? '旧结论失效 · 可重新定稿' : '已失效 · 等待恢复' : state.state === 'finalized' && claim && claim.valid === true ? '已定稿 · 当前有效' : claim && claim.valid === true ? '当前有效' : state.state === 'ready' && state.comparison ? '待你定稿' : '尚未生成';
    ui.claimSummary.textContent = claim && claim.summary ? claim.summary : state.state === 'ready' && state.comparison ? '比较已完成，可以定稿描述性结论。' : '结论需要使用条件。';
    ui.conditions.replaceChildren();
    if (claim) {
      if (claim.id) ui.conditions.append(element('span', 'condition', claim.id));
      if (claim.type) ui.conditions.append(element('span', 'condition', claim.type));
      for (const label of conditionLabels(claim.conditions)) ui.conditions.append(element('span', 'condition', label));
    }
    if (stale) ui.unresolved.textContent = ((claim && claim.invalidation_reason) || '这份结论属于旧证据或旧条件。') + (state.state === 'ready' && state.comparison ? ' 当前比较已重新计算，可以重新定稿。' : ' 完成取证与比较后，才能形成当前结论。');
    else if (claim && claim.unresolved) ui.unresolved.textContent = Array.isArray(claim.unresolved) ? claim.unresolved.map(plain).join('；') : plain(claim.unresolved);
    else ui.unresolved.textContent = '区域比较完成后，效果与成本问题仍需独立证据。';
    ui.finalize.textContent = state.state === 'finalized' && claim && claim.valid === true ? '描述性结论已定稿 ✓' : '定稿描述性结论 ↗';
  }

  function render(state) {
    currentState = state;
    const metrics = state.metrics || {};
    ui.calls.textContent = plain(metrics.tool_calls);
    ui.repairs.textContent = plain(metrics.repairs);
    ui.models.textContent = plain(metrics.model_calls);
    ui.revision.textContent = 'DATA / v' + plain(metrics.current_revision);
    ui.taskId.textContent = state.task.id || '当前任务';
    ui.taskId.title = state.task.id || '';
    if (!goalDirty) ui.goal.value = state.task.goal || '';
    ui.scope.textContent = state.task.require_full === false ? '仅华东 · 明确授权' : '完整区域';
    const provider = state.provider || {};
    ui.scopeControls.hidden = !provider.missing_B_south || state.task.require_full === false || state.task.allow_scope_change === true;
    ui.missing.querySelector('strong').textContent = provider.missing_B_south ? '恢复 B · 华南' : '移除 B · 华南';
    ui.missing.querySelector('small').textContent = provider.missing_B_south ? '让原始视图重新提供区域证据' : '让完整比较遇到证据缺口';
    ui.missing.querySelector('.scenario-symbol').textContent = provider.missing_B_south ? '+' : '−';
    ui.archive.querySelector('strong').textContent = provider.archive_enabled === false ? '启用备选视图' : '关闭备选视图';
    ui.archive.querySelector('small').textContent = provider.archive_enabled === false ? '允许从备选来源补齐缺失证据' : '检验能否补证或请求授权';
    if (!weightDirty && numeric(state.task.east_weight)) drawWeight(state.task.east_weight * 100);
    renderFeedback(state); renderDecision(state); renderTrace(state); renderEvidence(state); renderComparison(state); renderClaim(state);
    ui.reuse.hidden = !reuseMessage; ui.reuse.textContent = reuseMessage;
    updateControls();
    const nextStatus = state.state + ':' + ((state.feedback || {}).code || '');
    if (nextStatus !== lastStatus) {
      announce((stateLabels[state.state] || {label: plain(state.state)}).label + '。' + ((state.feedback || {}).message || ''));
      lastStatus = nextStatus;
    }
  }

  async function perform(path, body, label = '等待后端执行', options = {}) {
    if (busy || (autoRunning && !options.fromAuto)) return false;
    busy = true;
    ui.runStatus.textContent = label;
    updateControls();
    try {
      const before = currentState;
      const result = await request(path, body);
      if (path === '/api/weights') {
        const previous = new Set((before && before.evidence || []).filter((item) => item.valid === true).map((item) => plain(item.id) + ':' + plain(item.revision)));
        const reused = (result.evidence || []).filter((item) => item.valid === true && previous.has(plain(item.id) + ':' + plain(item.revision))).length;
        const beforeTraceCount = before && before.trace ? before.trace.length : 0;
        const newRequests = result.trace.slice(beforeTraceCount).filter((trace) => trace.tool === 'request_evidence').length;
        reuseMessage = '后端已接受新目标 · 复用 ' + reused + ' 份有效证据 · 新取证 ' + newRequests + ' 次';
        weightDirty = false;
      } else {
        reuseMessage = '';
      }
      if (path === '/api/reset') {goalDirty = false; weightDirty = false; ui.reset.nextElementSibling.textContent = '重置会清空当前轨迹和结论。默认不授权缩小任务范围。';}
      render(result);
      ui.runStatus.textContent = options.fromAuto ? '已完成 ' + autoCount + ' / 10 步' : '后端已返回真实状态';
      return true;
    } catch (error) {
      showError(error);
      if (path === '/api/weights') {weightDirty = false; if (currentState && numeric(currentState.task.east_weight)) drawWeight(currentState.task.east_weight * 100);}
      return false;
    } finally {
      busy = false;
      updateControls();
    }
  }

  async function connect() {
    if (busy || autoRunning) return;
    busy = true;
    ui.connectionLabel.textContent = '正在连接';
    updateControls();
    try { render(await request('/api/state')); ui.runStatus.textContent = '按真实反馈推进'; }
    catch (error) { signalConnection(false); showError(error); }
    finally { busy = false; updateControls(); }
  }

  async function runAutomatically() {
    if (autoRunning) {
      autoStopRequested = true; updateControls();
      ui.runStatus.textContent = '本次真实请求完成后停止';
      return;
    }
    if (busy || !connected || !currentState) return;
    autoRunning = true; autoStopRequested = false; autoCount = 0;
    updateControls();
    try {
      while (autoCount < 10 && !autoStopRequested) {
        if (['needs_clarification', 'finalized'].includes(currentState.state) || (currentState.state === 'ready' && currentState.comparison)) break;
        autoCount++;
        const ok = await perform('/api/step', {mode}, mode === 'deepseek' ? '第 ' + autoCount + ' 步 · 等待真实 DeepSeek API' : '第 ' + autoCount + ' 步 · 等待协议与工具返回', {fromAuto: true});
        if (!ok) break;
      }
      if (ui.alert.hidden) {
        ui.runStatus.textContent = autoStopRequested ? '已停止 · ' + autoCount + ' 次实际步骤' : autoCount >= 10 ? '已达 10 步上限 · 可继续' : currentState.state === 'needs_clarification' ? '已暂停 · 等待你的明确选择' : currentState.state === 'ready' ? '已暂停 · 可以定稿' : currentState.state === 'finalized' ? '任务已完成' : '自动运行已停止';
      }
    } finally { autoRunning = false; autoStopRequested = false; updateControls(); }
  }

  async function submitWeight(value) {
    if (busy || autoRunning || !currentState) return;
    const east = Math.max(0, Math.min(100, Number(value)));
    weightDirty = false;
    drawWeight(east);
    await perform('/api/weights', {east_weight: east / 100}, '声明新目标 · 等待后端比较');
  }

  ui.modeProtocol.addEventListener('click', () => setMode('protocol'));
  ui.modeDeepseek.addEventListener('click', () => setMode('deepseek'));
  ui.reconnect.addEventListener('click', connect);
  ui.goal.addEventListener('input', () => {goalDirty = true; ui.reset.nextElementSibling.textContent = '目标文字已修改，将在开启 / 重置任务时提交。当前任务仍使用原目标。';});
  ui.reset.addEventListener('click', () => perform('/api/reset', {
    preset: ui.preset.value, east_weight: Number(ui.weight.value) / 100,
    archive_enabled: currentState && currentState.provider ? currentState.provider.archive_enabled !== false : true,
    allow_scope_change: false, goal: ui.goal.value.trim()
  }, '开启任务 · 等待后端初始化'));
  ui.step.addEventListener('click', () => perform('/api/step', {mode}, mode === 'deepseek' ? '等待真实 DeepSeek API 与工具返回' : '等待协议选择与工具返回'));
  ui.auto.addEventListener('click', runAutomatically);
  ui.missing.addEventListener('click', () => perform('/api/mutate', {kind: currentState.provider && currentState.provider.missing_B_south ? 'restore_region' : 'missing_region'}, '修改数据现场 · 等待后端'));
  ui.archive.addEventListener('click', () => perform('/api/mutate', {kind: 'archive_toggle', value: !(currentState.provider && currentState.provider.archive_enabled)}, '切换备选视图 · 等待后端'));
  ui.changeData.addEventListener('click', () => perform('/api/mutate', {kind: 'data_change'}, '导入更新 · 检查证据版本'));
  ui.openScope.addEventListener('click', () => perform('/api/mutate', {kind: 'scope_toggle', value: true}, '由你开放范围变更选项'));
  ui.weight.addEventListener('input', () => {weightDirty = true; drawWeight(ui.weight.value, true);});
  ui.weight.addEventListener('change', () => submitWeight(ui.weight.value));
  ui.weight20.addEventListener('click', () => submitWeight(20));
  ui.weight80.addEventListener('click', () => submitWeight(80));
  ui.finalize.addEventListener('click', () => perform('/api/action', {tool: 'finalize_claim', arguments: {}}, '核验使用条件 · 定稿结论'));
  ui.export.addEventListener('click', (event) => {if (ui.export.getAttribute('aria-disabled') === 'true') event.preventDefault();});
  updateControls();
  if (location.protocol === 'file:') {
    signalConnection(false);
    showError(new Error('此页面需要通过本地 HTTP 服务打开，不能直接双击 HTML。'));
  } else {
    connect();
  }
})();
