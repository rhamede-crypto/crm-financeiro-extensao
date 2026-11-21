import AxeBuilder from '@axe-core/playwright';
import { expect, test } from '@playwright/test';
import { headers, row, spreadsheet } from './fixtures';

const password = 'Sintetico-123';
const firstEmail = 'empresa-a@example.test';

async function register(page, email = firstEmail, { sample = false } = {}) {
  await page.getByRole('link', { name: 'Criar conta' }).click();
  await page.getByLabel('Nome', { exact: true }).fill('Pessoa Sintética');
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Senha').fill(password);
  await page.getByRole('button', { name: 'Criar conta' }).click();
  await page.getByLabel('Nome da empresa').fill(email === firstEmail ? 'Empresa Sintética A' : 'Empresa Sintética B');
  await page.getByLabel('Incluir cenário sintético').setChecked(sample);
  await page.getByRole('button', { name: 'Salvar e continuar' }).click();
}

async function login(page, email = firstEmail) {
  await page.getByLabel('E-mail').fill(email);
  await page.getByLabel('Senha').fill(password);
  await page.getByRole('button', { name: 'Entrar', exact: true }).click();
}

async function go(page, name) {
  await page.getByRole('navigation', { name: 'Menu principal' }).getByRole('link', { name, exact: true }).click();
}

async function upload(page, file) {
  await go(page, 'Importações');
  await page.getByLabel('Tipo de dados').selectOption('receivable');
  await page.getByLabel('Planilha').setInputFiles(file);
  const started = Date.now();
  await page.getByRole('button', { name: 'Enviar planilha' }).click();
  await expect(page.getByRole('heading', { name: file.name })).toBeVisible();
  return started;
}

function summary(page, label) {
  return page.locator('dl').filter({ has: page.getByText(label, { exact: true }) })
    .locator('div').filter({ has: page.getByText(label, { exact: true }) }).locator('dd');
}

test('MVP no celular com revisão, três formatos, baixa, reenvio e retorno pelo lembrete', async ({ page }) => {
  await page.goto('/');
  await register(page);
  await expect(page.getByRole('heading', { name: 'Visão geral' })).toBeVisible();
  await expect(page.getByText('Sem histórico de caixa')).toBeVisible();

  const unknown = [...headers];
  unknown[2] = 'Cobrado';
  unknown[3] = 'Descrição livre';
  await upload(page, spreadsheet('csv', [unknown, row('CR-01')], 'revisao'));
  await page.reload();
  await expect(page.getByText('Revisão necessária')).toBeVisible();
  await expect(page.getByText('Baixa confiança.', { exact: false })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Confirmar importação' })).toBeDisabled();
  await page.getByLabel('Valor *', { exact: true }).selectOption({ label: 'Cobrado' });
  await page.getByRole('button', { name: 'Confirmar importação' }).click();
  await expect(summary(page, 'Novos')).toHaveText('1');
  const privateJob = page.url();

  await go(page, 'Visão geral');
  await expect(page.getByText('Cliente Sintético')).toBeVisible();
  await page.getByRole('link', { name: 'Preparar cobrança para Cliente Sintético' }).click();
  await expect(page.getByText('Canal indisponível')).toBeVisible();

  const settled = [headers, row('CR-01', { status: 'Pago' })];
  await upload(page, spreadsheet('xlsx', settled, 'baixa'));
  await expect(summary(page, 'Atualizados')).toHaveText('1');
  await upload(page, spreadsheet('xls', settled, 'reenvio'));
  await expect(summary(page, 'Sem alterações')).toHaveText('1');
  await go(page, 'Visão geral');
  await expect(page.getByText('Nenhum cliente inadimplente no ranking')).toBeVisible();
  await go(page, 'Carteira');
  await page.getByRole('link', { name: 'Cliente Sintético' }).click();
  await expect(page.getByText('Pagamento efetivo')).toBeVisible();
  const privateContact = page.url();

  await go(page, 'CEO IA');
  await page.getByLabel('Sua pergunta').fill('Qual é a projeção de caixa?');
  await page.getByRole('button', { name: 'Enviar pergunta' }).click();
  await expect(page.getByText('Dados insuficientes', { exact: true })).toBeVisible();

  await go(page, 'Empresa');
  await page.getByLabel('Receber lembrete semanal').check();
  await page.getByLabel('Dia da semana').selectOption('friday');
  await page.getByRole('button', { name: 'Salvar preferências' }).click();
  await expect(page.getByText('Preferências salvas.')).toBeVisible();
  await expect(page.getByText(/Última consolidação · \d/)).toBeVisible();
  await page.getByRole('button', { name: 'Sair', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Entrar' })).toBeVisible();
  await page.goto('/importacoes');
  await expect(page.getByRole('heading', { name: 'Entrar' })).toBeVisible();
  await login(page);
  await expect(page.getByRole('heading', { name: 'Importações' })).toBeVisible();
  await expect(page.getByRole('link', { name: 'reenvio.xls' })).toBeVisible();

  await page.getByRole('button', { name: 'Sair', exact: true }).click();
  await register(page, 'empresa-b@example.test');
  await page.goto(privateJob);
  await expect(page.getByRole('alert')).toHaveText('Importação não encontrada.');
  await page.goto(privateContact);
  await expect(page.getByText('Ficha indisponível', { exact: true })).toBeVisible();
  await go(page, 'Importações');
  await expect(page.getByText('Nenhuma importação')).toBeVisible();
});

test('carteira, cobrança editável, Kanban, acordo e promessa', async ({ page }) => {
  await page.goto('/');
  await register(page, firstEmail, { sample: true });
  await expect(page.getByText('Saldo negativo previsto', { exact: false })).toBeVisible();

  await page.getByRole('link', { name: 'Preparar cobrança para Mercado Horizonte' }).click();
  await page.getByLabel('Tom da mensagem').selectOption('negotiation');
  await expect(page.getByLabel('Mensagem', { exact: true })).toHaveValue(/combinar uma nova data/);
  await page.getByLabel('Mensagem', { exact: true }).fill('Mensagem de cobrança sintética editada.');
  await page.getByRole('button', { name: 'Confirmar envio' }).click();
  await expect(page.getByRole('status')).toHaveText('Envio simulado nesta demonstração.');
  await expect(page.getByRole('button', { name: 'Confirmar envio' })).toBeDisabled();

  await go(page, 'Negociações');
  await page.getByLabel('Mover para').selectOption('negotiating');
  await page.getByRole('button', { name: 'Mover cartão' }).press('Enter');
  await expect(page.getByRole('status')).toContainText('Em negociação');
  await page.reload();
  await expect(page.locator('section').filter({ has: page.getByRole('heading', { name: /Em negociação/ }) })
    .getByRole('heading', { name: 'Fatura F-018' })).toBeVisible();

  await go(page, 'Carteira');
  await page.getByLabel('Nome', { exact: true }).fill('Horizonte');
  await page.getByRole('button', { name: 'Pesquisar' }).click();
  await expect(page.getByRole('link', { name: 'Distribuidora Aurora' })).toHaveCount(0);
  await page.getByRole('link', { name: 'Mercado Horizonte' }).click();
  await expect(page.getByText('Atraso Recorrente')).toBeVisible();
  await page.getByLabel('Nova nota').fill('Cliente propôs pagar R$ 500,00 em 2027-01-21.');
  await page.getByRole('button', { name: 'Adicionar nota' }).click();
  await expect(page.getByLabel('Valor (R$)')).toHaveValue('500.00');
  await page.getByLabel('Valor (R$)').fill('550');
  await page.getByLabel('Data da promessa').fill('2027-02-25');
  await page.getByRole('button', { name: 'Confirmar promessa' }).click();
  await expect(page.getByText('Promessa confirmada')).toBeVisible();
  await expect(page.getByText('Pagamento efetivo')).toBeVisible();
  await expect(page.getByText('25/02/2027', { exact: false })).toBeVisible();

  await go(page, 'Visão geral');
  await page.getByRole('link', { name: 'Ver fornecedor' }).click();
  await expect(page.getByText('Sem preço comparável', { exact: false })).toHaveCount(2);
  await page.getByLabel('Termos do acordo').fill('Ajustar o preço no próximo pedido.');
  await page.getByLabel('Alerta (opcional)').selectOption('alerta-amostra');
  await page.getByRole('button', { name: 'Registrar acordo' }).click();
  await expect(page.getByText('Ajustar o preço no próximo pedido.')).toBeVisible();
});

test('limite de 10.000 linhas e medição de mapeamento com amostra sintética', async ({ page }, info) => {
  await page.goto('/');
  await register(page);
  const bulk = Array.from({ length: 10_000 }, (_, i) => row('LOTE-' + i, { status: 'Pago' }));
  const inputs = [
    spreadsheet('csv', [headers, ...bulk], 'dez-mil'),
    spreadsheet('xlsx', [headers, row('AUTO-01')], 'automatico-xlsx'),
    spreadsheet('xls', [headers, row('AUTO-02')], 'automatico-xls'),
    spreadsheet('csv', [['data', 'origem', 'descricao'], ['2024-01-01', 'sintético', 'sem valor']], 'manual'),
  ];
  const evidence = [];
  let automatic = 0;
  for (const [index, fixture] of inputs.entries()) {
    const started = await upload(page, fixture);
    if (index < 3) {
      await expect(summary(page, 'Novos')).toHaveText(index === 0 ? '10000' : '1');
      automatic++;
    } else {
      await expect(page.getByText('Revisão necessária')).toBeVisible();
    }
    evidence.push({ file: fixture.name, elapsedMs: Date.now() - started, automatic: index < 3 });
  }
  expect(automatic).toBe(3);
  await info.attach('evidencia-mock.json', {
    body: JSON.stringify({ scope: 'Somente demonstração local', automatic, total: inputs.length, evidence }, null, 2),
    contentType: 'application/json',
  });
  console.log('Métricas da demonstração:', JSON.stringify(evidence));
});

test('teclado, foco visível, largura estreita e auditoria automatizada', async ({ page }) => {
  await page.setViewportSize({ width: 320, height: 700 });
  await page.goto('/');
  await register(page, firstEmail, { sample: true });
  await expect(page.getByRole('heading', { name: 'Visão geral' })).toBeVisible();
  const dashboardResults = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(dashboardResults.violations).toEqual([]);
  await go(page, 'CEO IA');
  await expect(page.getByRole('main')).toBeFocused();
  await page.keyboard.press('Tab');
  await expect(page.getByLabel('Sua pergunta')).toBeFocused();
  await expect(page.getByLabel('Sua pergunta')).toHaveCSS('outline-width', '3px');
  await page.keyboard.type('Qual o saldo de caixa?');
  await page.keyboard.press('Tab');
  await expect(page.getByRole('button', { name: 'Enviar pergunta' })).toBeFocused();
  await page.keyboard.press('Enter');
  await expect(page.getByRole('log')).toContainText('Projeção de caixa');
  await expect(page.getByLabel('Sua pergunta')).toBeFocused();
  expect(await page.evaluate(() => document.documentElement.scrollWidth)).toBe(320);
  const chatResults = await new AxeBuilder({ page }).withTags(['wcag2a', 'wcag2aa', 'wcag21a', 'wcag21aa']).analyze();
  expect(chatResults.violations).toEqual([]);
});
