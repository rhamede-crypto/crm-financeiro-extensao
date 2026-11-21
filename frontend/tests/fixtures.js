import { utils, write } from '@e965/xlsx';

export const headers = ['id', 'data', 'valor', 'descricao', 'cliente', 'status', 'vencimento'];
export const row = (id, { client = 'Cliente Sintético', status = 'Aberto', amount = 125 } = {}) =>
  [id, '2024-01-12', amount, 'Lançamento ' + id, client, status, '2024-02-12'];

export function spreadsheet(type, content, name = 'financeiro') {
  const sheet = utils.aoa_to_sheet(content);
  const workbook = utils.book_new(sheet, 'Lançamentos');
  const buffer = type === 'csv' ? Buffer.from(utils.sheet_to_csv(sheet), 'utf8')
    : write(workbook, { bookType: type, type: 'buffer' });
  const mimeType = { csv: 'text/csv', xlsx: 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
    xls: 'application/vnd.ms-excel' }[type];
  return { name: name + '.' + type, mimeType, buffer };
}
