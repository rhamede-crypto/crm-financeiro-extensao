const currency = new Intl.NumberFormat('pt-BR', { style: 'currency', currency: 'BRL' });
const dates = new Intl.DateTimeFormat('pt-BR');
export const money = (value) => value == null || !Number.isFinite(Number(value)) ? '—' : currency.format(Number(value));
export const date = (value) => {
  if (!value) return '—';
  const result = new Date(value.length === 10 ? value + 'T12:00:00' : value);
  return Number.isNaN(result.getTime()) ? '—' : dates.format(result);
};
export const today = () => {
  const local = new Date();
  return [local.getFullYear(), local.getMonth() + 1, local.getDate()]
    .map((part) => String(part).padStart(2, '0')).join('-');
};
export const normalize = (value) => String(value ?? '').trim().normalize('NFD')
  .replace(/\p{Diacritic}/gu, '').toLowerCase();
export const importStatus = {
  queued: 'Na fila',
  processing: 'Em processamento',
  review: 'Revisão necessária',
  completed: 'Consolidada',
  failed: 'Falhou',
  canceled: 'Cancelada',
};
export const stages = [
  ['identified', 'Identificado pela IA'],
  ['contacted', 'Cobrança enviada'],
  ['negotiating', 'Em negociação'],
  ['promised', 'Promessa de pagamento'],
  ['paid', 'Pago'],
];
export const entryLabels = {
  note: 'Nota',
  promise: 'Promessa confirmada',
  payment: 'Pagamento efetivo',
};
export const tones = [
  ['friendly', 'Amigável'],
  ['firm', 'Firme'],
  ['negotiation', 'Negociação'],
];
