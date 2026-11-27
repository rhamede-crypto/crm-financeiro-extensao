import { normalize, today } from './domain';

export const importConfig = {
  maxBytes: 5 * 1024 * 1024,
  maxRows: 10_000,
  extensions: ['csv', 'xlsx', 'xls'],
  types: [
    { id: 'receivable', label: 'Contas a receber' },
    { id: 'payable', label: 'Contas a pagar' },
    { id: 'settled', label: 'Lançamentos efetivados' },
  ],
};

const fields = [
  { id: 'reference', label: 'Identificador de origem', aliases: ['id', 'identificador', 'referencia'] },
  { id: 'date', label: 'Data', required: true, aliases: ['data', 'emissao', 'competencia'] },
  { id: 'amount', label: 'Valor', required: true, aliases: ['valor', 'total', 'quantia'] },
  { id: 'description', label: 'Descrição', required: true, aliases: ['descricao', 'historico', 'lancamento'] },
  { id: 'party', label: 'Cliente ou fornecedor', aliases: ['cliente', 'fornecedor', 'contato', 'contraparte'] },
  { id: 'status', label: 'Status', aliases: ['status', 'situacao'] },
  { id: 'due', label: 'Vencimento', aliases: ['vencimento', 'data de vencimento'] },
];

export function analyzeTable(table) {
  const [head, ...rows] = table.filter((row) => row.some((cell) => String(cell ?? '').trim()))
    .map((row) => row.map((cell) => cell instanceof Date ? cell.toISOString().slice(0, 10) : cell));
  const columns = (head || []).map((label, index) => ({ id: String(index), label: String(label || 'Coluna ' + (index + 1)) }));
  const mapping = Object.fromEntries(fields.map((field) => {
    const exact = columns.filter((column) => field.aliases.includes(normalize(column.label)));
    const approximate = columns.filter((column) => field.aliases.some((alias) => normalize(column.label).includes(alias)));
    const match = exact.length === 1 ? exact[0] : approximate.length === 1 ? approximate[0] : null;
    return [field.id, { column: match?.id ?? '', confidence: exact.length === 1 ? 'high' : 'low' }];
  }));
  return { columns, fields, mapping, rows, preview: rows.slice(0, 4).map((row) =>
    columns.map(({ id }) => String(row[id] ?? '').slice(0, 120))) };
}

function isoDate(value) {
  if (value instanceof Date && !Number.isNaN(value.getTime())) return value.toISOString().slice(0, 10);
  const text = String(value ?? '').trim();
  const local = text.match(/^(\d{1,2})[/.-](\d{1,2})[/.-](\d{4})$/);
  const iso = local ? [local[3], local[2].padStart(2, '0'), local[1].padStart(2, '0')].join('-') : text;
  if (!/^\d{4}-\d{2}-\d{2}$/.test(iso)) return '';
  const parsed = new Date(iso);
  return !Number.isNaN(parsed.getTime()) && parsed.toISOString().slice(0, 10) === iso ? iso : '';
}

function cents(value) {
  let decimal = String(value ?? '').trim().replace(/^R\$\s*/, '').replace(/\s/g, '');
  if (decimal.includes(',')) decimal = decimal.replace(/\./g, '').replace(',', '.');
  if (!/^-?\d+(\.\d{1,2})?$/.test(decimal)) return null;
  const result = Math.round(Number(decimal) * 100);
  return Number.isSafeInteger(result) && Math.abs(result) <= 10_000_000_000 ? result : null;
}

export function mappedRows(job, mapping) {
  return job.rows.map((row) => {
    const read = (id) => row[mapping[id]];
    const value = cents(read('amount'));
    const description = String(read('description') ?? '').trim();
    const date = isoDate(read('date'));
    if (value == null || !description || !date) return null;
    const status = normalize(read('status'));
    return {
      reference: String(read('reference') ?? '').trim(), date, due: isoDate(read('due')),
      cents: value, description, party: String(read('party') ?? '').trim(),
      settled: ['pago', 'recebido', 'baixado', 'quitado', 'paid'].includes(status) || job.type === 'settled',
      type: job.type,
    };
  });
}

export const rowMatch = (row) => [row.type, row.date, row.cents, normalize(row.description), normalize(row.party)].join('|');

export function deduplicate(previous, incoming, resolutions = {}) {
  const byReference = new Map();
  const byMatch = new Map();
  const ledger = [...previous];
  const ambiguity = [];
  const summary = { created: 0, updated: 0, unchanged: 0, rejected: 0 };
  function indexRow(row, index) {
    if (row.reference) byReference.set(row.type + ':' + row.reference, index);
    const match = rowMatch(row);
    let matches = byMatch.get(match);
    if (!matches) byMatch.set(match, matches = new Set());
    matches.add(index);
  }
  ledger.forEach(indexRow);
  incoming.forEach((row, index) => {
    if (!row) {
      summary.rejected++;
      return;
    }
    const match = rowMatch(row);
    const candidates = byMatch.get(match);
    let target = row.reference ? byReference.get(row.type + ':' + row.reference) : undefined;
    if (target === undefined && !row.reference && candidates?.size) {
      const id = String(index);
      const decision = resolutions[id];
      if (decision === 'ignore') {
        summary.unchanged++;
        return;
      }
      if (decision !== 'new') {
        ambiguity.push({ id, row: index + 2, description: row.description, options: ['new', 'ignore'] });
        return;
      }
    }
    if (target === undefined) {
      indexRow(row, ledger.push(row) - 1);
      summary.created++;
    } else {
      const existing = ledger[target];
      if (JSON.stringify(existing) === JSON.stringify(row)) {
        summary.unchanged++;
        return;
      }
      byMatch.get(rowMatch(existing)).delete(target);
      ledger[target] = row;
      indexRow(row, target);
      summary.updated++;
    }
  });
  return { ledger, summary, ambiguity };
}

export function sampleCompany() {
  const client = {
    id: 'cliente-amostra', name: 'Mercado Horizonte', type: 'customer',
    metrics: { ltv: '48200.00', average: '9640.00', score: 'Atraso Recorrente' },
    invoices: [{ id: 'F-018', label: 'Fatura F-018', amount: '8450.00', due: '2026-10-30' }],
    history: [{ date: '2026-10-12', label: 'Fatura F-013', amount: '16000.00' }],
  };
  const supplier = {
    id: 'fornecedor-amostra', name: 'Distribuidora Aurora', type: 'supplier',
    costHistory: [
      { period: '2026-08', spending: '3800.00', unitPrice: null },
      { period: '2026-09', spending: null, unitPrice: null },
      { period: '2026-10', spending: '4620.00', unitPrice: '46.20', unit: 'caixa' },
    ],
    agreements: [],
  };
  const alert = {
    id: 'alerta-amostra', supplierId: supplier.id, supplier: supplier.name,
    category: 'Embalagens', period: 'Set–Out 2026', change: 21.6,
    recommendation: 'Revisar o preço por caixa na próxima compra.',
  };
  return {
    contacts: [client, supplier],
    alerts: [alert],
    deals: [{ id: 'neg-amostra', contactId: client.id, title: 'Fatura F-018', name: client.name,
      amount: '8450.00', due: '2026-10-30', stage: 'identified', version: 1 }],
    timeline: { [client.id]: [
      { id: 'pagamento-amostra', kind: 'payment', date: '2026-10-12', createdAt: '2026-10-12T12:00:00Z',
        text: 'Fatura F-013', amount: '16000.00' },
    ] },
    projection: [{ days: 30, amount: '24500.00' }, { days: 60, amount: '18760.00' }, { days: 90, amount: '-840.00' }],
  };
}

export function companyDashboard(state) {
  const { ledger, sample } = state;
  const overdue = new Map();
  for (const row of ledger) {
    if (row.type !== 'receivable' || row.settled || !row.due || row.due >= today() || !row.party) continue;
    const id = 'contato-' + normalize(row.party);
    const days = Math.round((Date.parse(today()) - Date.parse(row.due)) / 86_400_000);
    const current = overdue.get(id) || { id, name: row.party, cents: 0, days: 0 };
    current.cents += row.cents;
    current.days = Math.max(current.days, days);
    overdue.set(id, current);
  }
  if (sample) {
    overdue.set('cliente-amostra', { id: 'cliente-amostra', name: 'Mercado Horizonte', cents: 845000, days: 22 });
  }
  const ranking = [...overdue.values()].sort((first, second) => second.cents - first.cents).slice(0, 5)
    .map(({ id, name, cents, days }) => ({ id, name, amount: (cents / 100).toFixed(2), days }));
  return {
    projections: sample?.projection || [],
    negativeDate: sample ? '2027-02-15' : null,
    updatedAt: state.lastConsolidated,
    ranking,
    alerts: sample?.alerts || [],
  };
}

export function companyContacts(state) {
  const contacts = new Map((state.sample?.contacts || []).map((item) => [item.id, structuredClone(item)]));
  for (const row of state.ledger) {
    if (!row.party) continue;
    const type = row.type === 'payable' ? 'supplier' : 'customer';
    const id = 'contato-' + normalize(row.party) + (type === 'supplier' ? '-fornecedor' : '');
    if (!contacts.has(id)) contacts.set(id, { id, name: row.party, type, invoices: [], history: [], costHistory: [] });
    const contact = contacts.get(id);
    const entry = { id: row.reference || rowMatch(row), label: row.description, amount: (row.cents / 100).toFixed(2),
      date: row.date, due: row.due };
    if (row.settled) contact.history.push(entry);
    else if (type === 'customer') contact.invoices.push(entry);
  }
  return [...contacts.values()];
}
