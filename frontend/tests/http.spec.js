import { expect, test } from '@playwright/test';

test('o cliente REST conserva a pergunta e a chave ao repetir uma falha', async ({ page }) => {
  const requests = [];
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/session')) return route.fulfill({
      json: { user: { name: 'Pessoa Teste' }, company: { name: 'Empresa Teste' } },
    });
    if (path.endsWith('/chat')) {
      requests.push({ data: route.request().postDataJSON(), key: route.request().headers()['idempotency-key'] });
      if (requests.length === 1) return route.fulfill({ status: 503, json: { message: 'Chat temporariamente indisponível.' } });
      return route.fulfill({ json: { text: 'Resposta de teste.', references: ['Caixa'], insufficient: false } });
    }
    return route.fulfill({ status: 404, json: { message: 'Rota ausente.' } });
  });
  await page.goto('/chat');
  const question = 'Qual o saldo da empresa?';
  await page.getByLabel('Sua pergunta').fill(question);
  await page.getByRole('button', { name: 'Enviar pergunta' }).click();
  await expect(page.getByRole('alert')).toHaveText('Chat temporariamente indisponível.');
  await expect(page.getByLabel('Sua pergunta')).toHaveValue(question);
  await page.getByRole('button', { name: 'Tentar enviar de novo' }).click();
  await expect(page.getByRole('log')).toContainText('Resposta de teste.');
  expect(requests[0].key).toBeTruthy();
  expect(requests).toEqual([{ data: { question }, key: requests[0].key }, { data: { question }, key: requests[0].key }]);
});

test('sessão expirada em rota privada mantém o retorno do lembrete', async ({ page }) => {
  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path.endsWith('/session')) return route.fulfill({
      json: { user: { name: 'Pessoa Teste' }, company: { name: 'Empresa Teste' } },
    });
    return route.fulfill({ status: 401, json: { message: 'Sessão expirada.' } });
  });
  await page.goto('/importacoes');
  await expect(page.getByRole('heading', { name: 'Entrar' })).toBeVisible();
  await expect(page).toHaveURL(/\/entrar\?retorno=%2Fimportacoes/);
});
