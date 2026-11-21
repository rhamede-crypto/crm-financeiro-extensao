import { ApiError } from './api';
import { money, normalize, stages } from './domain';
import {
  analyzeTable, companyContacts, companyDashboard, deduplicate, importConfig, mappedRows, sampleCompany,
} from './mockData';

const storeKey = 'crm-financeiro:demo:v1';
const now = () => new Date().toISOString();
const fail = (status, message, fields) => { throw new ApiError(status, message, fields); };

function read() {
  return JSON.parse(localStorage.getItem(storeKey) || '{"users":{},"session":null}');
}

function save(db) {
  try {
    localStorage.setItem(storeKey, JSON.stringify(db));
  } catch (error) {
    if (error.name !== 'QuotaExceededError') throw error;
    fail(507, 'O navegador ficou sem espaço para os dados sintéticos.');
  }
}

function session(user) {
  if (!user) return null;
  return { user: { name: user.name, email: user.email }, company: user.company };
}

async function hashPassword(password, salt) {
  const bytes = new TextEncoder().encode(salt + ':' + password);
  const hash = await crypto.subtle.digest('SHA-256', bytes);
  return [...new Uint8Array(hash)].map((byte) => byte.toString(16).padStart(2, '0')).join('');
}

async function authenticate(path, data) {
  const email = data.email.trim().toLowerCase();
  const db = read();
  const user = Object.hasOwn(db.users, email) ? db.users[email] : null;
  if (path === '/auth/login') {
    if (!user || await hashPassword(data.password, user.salt) !== user.hash) {
      fail(401, 'E-mail ou senha inválidos.');
    }
    const current = read();
    current.session = email;
    save(current);
    return session(current.users[email]);
  }

  if (!data.name.trim() || !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) || data.password.length < 8) {
    fail(422, 'Confira os dados do cadastro.');
  }
  const salt = crypto.randomUUID();
  const hash = await hashPassword(data.password, salt);
  const current = read();
  if (Object.hasOwn(current.users, email)) fail(422, 'Confira os dados do cadastro.', { email: ['E-mail já cadastrado.'] });
  current.users[email] = { name: data.name.trim(), email, salt, hash, company: null };
  current.session = email;
  save(current);
  return session(current.users[email]);
}

function companyState(useSample) {
  const sample = useSample ? sampleCompany() : null;
  return {
    sample, jobs: [], ledger: [], lastConsolidated: null, requests: {}, agreements: {},
    reminders: { available: true, channel: 'E-mail de demonstração', enabled: false, weekday: 'monday' },
    timeline: sample?.timeline || {}, deals: sample?.deals || [],
  };
}

function requireUser(db) {
  const user = db.session && db.users[db.session];
  if (!user) fail(401, 'Sua sessão expirou.');
  return user;
}

function publicJob({ rows, ...job }) {
  return job;
}

function finish(state, job, resolutions) {
  const result = deduplicate(state.ledger, mappedRows(job, job.selectedMapping), resolutions);
  if (result.ambiguity.length) {
    job.status = 'review';
    job.ambiguities = result.ambiguity;
    return;
  }
  state.ledger = result.ledger;
  state.lastConsolidated = now();
  job.status = 'completed';
  job.summary = result.summary;
  job.ambiguities = [];
  delete job.rows;
}

function advance(state, job) {
  if (job.status === 'queued' && Date.now() - job.createdMs >= 250) job.status = 'processing';
  if (job.status !== 'processing' || Date.now() - job.createdMs < 850) return;
  const review = job.fields.some(({ id, required }) =>
    (required && !job.mapping[id].column) || (job.mapping[id].column && job.mapping[id].confidence !== 'high'));
  if (review) {
    job.status = 'review';
    return;
  }
  finish(state, job);
}

function csvText(bytes) {
  try {
    return new TextDecoder('utf-8', { fatal: true }).decode(bytes);
  } catch {
    return new TextDecoder('windows-1252').decode(bytes);
  }
}

async function newJob(data, signal) {
  const file = data.get('file');
  const type = data.get('type');
  if (!importConfig.types.some(({ id }) => id === type)) fail(422, 'Selecione o tipo de dados.');
  const extension = file?.name.split('.').pop().toLowerCase();
  if (!importConfig.extensions.includes(extension)) fail(422, 'Envie um arquivo CSV, XLSX ou XLS.');
  if (!file.size || file.size > importConfig.maxBytes) fail(413, 'O arquivo está vazio ou ultrapassa o limite de tamanho.');

  const job = { id: crypto.randomUUID(), type, filename: file.name, createdAt: now(), createdMs: Date.now(), status: 'queued' };
  try {
    const { read: readWorkbook, utils } = await import('@e965/xlsx');
    const bytes = new Uint8Array(await file.arrayBuffer());
    signal?.throwIfAborted();
    const zip = bytes[0] === 0x50 && bytes[1] === 0x4b;
    const legacy = bytes[0] === 0xd0 && bytes[1] === 0xcf && bytes[2] === 0x11 && bytes[3] === 0xe0;
    if ((extension === 'xlsx' && !zip) || (extension === 'xls' && !legacy) ||
        (extension === 'csv' && (zip || legacy || bytes.includes(0)))) {
      throw new Error('O conteúdo não corresponde ao formato selecionado.');
    }
    const options = { cellDates: true, sheetRows: importConfig.maxRows + 2 };
    const workbook = extension === 'csv'
      ? readWorkbook(csvText(bytes), { ...options, type: 'string', raw: true })
      : readWorkbook(bytes, options);
    const sheet = workbook.Sheets[workbook.SheetNames[0]];
    const analysis = analyzeTable(utils.sheet_to_json(sheet, { header: 1, blankrows: false }));
    if (!analysis.rows.length) throw new Error('A primeira aba deve ter cabeçalhos e pelo menos uma linha de dados.');
    if (analysis.rows.length > importConfig.maxRows) throw new Error('O arquivo excede o limite de 10.000 linhas.');
    Object.assign(job, analysis, {
      rowCount: analysis.rows.length,
      selectedMapping: Object.fromEntries(Object.entries(analysis.mapping).map(([id, item]) => [id, item.column])),
    });
  } catch (error) {
    if (error.name === 'AbortError') throw error;
    job.status = 'failed';
    job.error = error.message || 'Não foi possível ler o conteúdo da planilha.';
  }
  return job;
}

function idempotent(state, path, key, run) {
  if (!key) return run();
  const id = path + ':' + key;
  if (!Object.hasOwn(state.requests, id)) state.requests[id] = run();
  return state.requests[id];
}

function requiredText(text, message) {
  if (!text?.trim()) fail(422, message);
  return text.trim();
}

function suggestion(text) {
  const amount = text.match(/R\$\s*([\d.]+(?:,\d{1,2})?)/)?.[1];
  const date = text.match(/\b\d{4}-\d{2}-\d{2}\b/)?.[0];
  if (!amount && !date) return null;
  return { title: 'Acordo de pagamento', amount: amount?.replaceAll('.', '').replace(',', '.') || '', date: date || '' };
}

export async function mockRequest(input, method, data, key, signal) {
  const url = new URL(input, 'https://demo.local');
  const path = url.pathname;
  let db = read();
  if (path === '/session') return session(db.session && db.users[db.session]);
  if (path === '/auth/login' || path === '/auth/register') return authenticate(path, data);

  let user = requireUser(db);
  if (path === '/auth/logout') {
    db.session = null;
    save(db);
    return null;
  }
  if (path === '/company' && method === 'POST') {
    if (user.company) fail(409, 'A empresa já está cadastrada.');
    const name = requiredText(data.name, 'Informe o nome da empresa.');
    user.company = { name, segment: data.segment?.trim() || '' };
    user.state = companyState(data.sample);
    save(db);
    return session(user);
  }
  if (!user.company) fail(403, 'Cadastre a empresa para continuar.');

  let state = user.state;
  if (path === '/imports/options') return importConfig;
  if (path === '/imports' && method === 'GET') {
    let changed = false;
    for (const job of [...state.jobs].reverse()) {
      const previous = job.status;
      advance(state, job);
      changed ||= previous !== job.status;
    }
    if (changed) save(db);
    return state.jobs.map(publicJob);
  }
  if (path === '/imports') {
    const email = db.session;
    const job = await newJob(data, signal);
    db = read();
    if (db.session !== email) fail(409, 'A sessão mudou durante o envio.');
    user = requireUser(db);
    state = user.state;
    const result = idempotent(state, path, key, () => {
      state.jobs.unshift(job);
      return publicJob(job);
    });
    save(db);
    return result;
  }
  if (path.startsWith('/imports/')) {
    const [, , id, action] = path.split('/');
    const job = state.jobs.find((item) => item.id === decodeURIComponent(id));
    if (!job) fail(404, 'Importação não encontrada.');
    if (!action) {
      const status = job.status;
      advance(state, job);
      if (status !== job.status) save(db);
      return publicJob(job);
    }
    if (action === 'cancel') {
      if (job.status !== 'review') fail(409, 'A importação já mudou de estado.');
      job.status = 'canceled';
      delete job.rows;
      save(db);
      return publicJob(job);
    }
    if (action === 'confirm') {
      const result = idempotent(state, path, key, () => {
        if (job.status !== 'review') fail(409, 'A importação já mudou de estado.');
        const used = Object.values(data.mapping).filter(Boolean);
        const known = new Set(job.columns.map(({ id: column }) => column));
        if (job.fields.some(({ id: field, required }) => required && !known.has(data.mapping[field])) ||
            used.some((column) => !known.has(column)) || new Set(used).size !== used.length) {
          fail(422, 'Associe uma coluna distinta a cada campo obrigatório.');
        }
        job.selectedMapping = data.mapping;
        finish(state, job, data.resolutions);
        return publicJob(job);
      });
      save(db);
      return result;
    }
  }
  if (path === '/dashboard') return companyDashboard(state);
  if (path === '/chat') {
    requiredText(data.question, 'Escreva uma pergunta.');
    const result = idempotent(state, path, key, () => {
      const dashboard = companyDashboard(state);
      const hasCash = normalize(data.question).match(/caixa|saldo|projecao/) && dashboard.projections.length;
      if (hasCash) return { text: 'No cenário de demonstração, o saldo projetado em 90 dias é ' +
        money(dashboard.projections.at(-1).amount) + '.', references: ['Projeção de caixa • 90 dias'], insufficient: false };
      return { text: 'A demonstração não tem dados ou referências suficientes para responder a essa pergunta.',
        references: [], insufficient: true };
    });
    save(db);
    return result;
  }
  if (path === '/reminders') {
    if (method === 'PUT') {
      if (!state.reminders.available) fail(409, 'O canal está indisponível.');
      if (!['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday'].includes(data.weekday)) {
        fail(422, 'Selecione um dia da semana.');
      }
      state.reminders = { ...state.reminders, enabled: Boolean(data.enabled), weekday: data.weekday };
      save(db);
    }
    return { ...state.reminders, lastConsolidated: state.lastConsolidated };
  }
  if (path === '/contacts') {
    const query = normalize(url.searchParams.get('query'));
    const type = url.searchParams.get('type');
    return companyContacts(state).filter((item) => (!type || item.type === type) && normalize(item.name).includes(query))
      .map(({ id, name, type: itemType }) => ({ id, name, type: itemType }));
  }
  if (path.startsWith('/contacts/')) {
    const [, , rawId, action, subaction, finalAction] = path.split('/');
    const id = decodeURIComponent(rawId);
    const contact = companyContacts(state).find((item) => item.id === id);
    if (!contact) fail(404, 'Ficha indisponível.');
    if (!action) {
      return { ...contact, alerts: (state.sample?.alerts || []).filter((item) => item.supplierId === id),
        agreements: state.agreements[id] || [] };
    }
    if (action === 'agreements') {
      if (contact.type !== 'supplier') fail(422, 'Esta ficha não é de um fornecedor.');
      const agreement = { id: crypto.randomUUID(), date: requiredText(data.date, 'Informe a data do acordo.'),
        terms: requiredText(data.terms, 'Informe os termos.'), alertId: data.alertId || null };
      (state.agreements[id] ||= []).unshift(agreement);
      save(db);
      return agreement;
    }
    if (action === 'timeline') {
      const entries = state.timeline[id] ||= [];
      if (!subaction) {
        const payments = state.ledger.flatMap((row, index) => {
          const type = row.type === 'payable' ? 'supplier' : 'customer';
          if (!row.settled || type !== contact.type || normalize(row.party) !== normalize(contact.name)) return [];
          return [{ id: 'import-payment-' + index, kind: 'payment', date: row.date,
            text: row.description, amount: (row.cents / 100).toFixed(2) }];
        });
        return [...entries, ...payments];
      }
      if (subaction === 'notes') {
        const text = requiredText(data.text, 'Escreva uma nota.');
        const entry = { id: crypto.randomUUID(), kind: 'note', text, createdAt: now(), author: user.name,
          suggestion: suggestion(text) };
        entries.push(entry);
        save(db);
        return entry;
      }
      if (finalAction === 'confirm') {
        const result = idempotent(state, path, key, () => {
          const note = entries.find((item) => item.id === decodeURIComponent(subaction) && item.kind === 'note');
          if (!note?.suggestion) fail(409, 'A sugestão não está mais disponível.');
          if (!(Number(data.amount) > 0) || !/^\d{4}-\d{2}-\d{2}$/.test(data.date)) {
            fail(422, 'Informe um valor positivo e a data.');
          }
          const entry = { id: crypto.randomUUID(), kind: 'promise', amount: data.amount, date: data.date,
            text: requiredText(data.title, 'Informe um título.'), createdAt: now(), author: user.name };
          entries.push(entry);
          note.suggestion = null;
          return entry;
        });
        save(db);
        return result;
      }
    }
    if (action === 'collections') {
      if (contact.id !== 'cliente-amostra') {
        return { available: false, reason: 'O cliente não tem destinatário e canal configurados na demonstração.' };
      }
      if (subaction === 'preview') {
        const introductions = { friendly: 'Olá! Podemos confirmar a previsão de pagamento?',
          firm: 'Solicitamos a regularização da fatura em aberto.',
          negotiation: 'Podemos combinar uma nova data para o pagamento?' };
        return { available: true, channel: 'E-mail de demonstração', text: 'Olá, ' + contact.name + '. ' +
          (introductions[data.tone] || introductions.friendly) + ' Valor em aberto: ' + money(contact.invoices[0].amount) + '.' };
      }
      if (subaction === 'send') {
        requiredText(data.text, 'Revise a mensagem antes de enviar.');
        const result = idempotent(state, path, key, () => ({ status: 'simulated' }));
        save(db);
        return result;
      }
    }
  }
  if (path === '/deals') return state.deals;
  if (path.startsWith('/deals/')) {
    const item = state.deals.find((deal) => deal.id === decodeURIComponent(path.split('/')[2]));
    if (!item) fail(404, 'Negociação indisponível.');
    if (item.version !== data.version) fail(409, 'O cartão mudou. O quadro foi recarregado.');
    if (!stages.some(([stage]) => stage === data.stage)) fail(422, 'Etapa inválida.');
    item.stage = data.stage;
    item.version++;
    save(db);
    return item;
  }
  fail(404, 'Operação indisponível.');
}
