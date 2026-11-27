# Front-end do CRM Financeiro

## Executar

Com Node.js 22.12 ou superior:

```sh
cd frontend
npm ci
npm run dev
```

Abra o endereço exibido pelo Vite. Crie uma conta sintética e escolha se quer carregar um cenário pronto durante o cadastro da empresa. O modo demonstração guarda os dados de teste neste navegador. Use somente dados sintéticos. O navegador lê a primeira aba das planilhas enviadas e aplica regras de exemplo para a revisão e a consolidação. As respostas do chat e os envios de cobranças e lembretes são simulados.

O link de retorno dos lembretes aponta para `/importacoes`. Quando a sessão expira, o aplicativo leva à tela de login e retorna às importações depois de autenticar.

## Integrar a API

Copie `.env.example` para `.env.local`, ajuste `VITE_API_MODE=rest` e informe o prefixo em `VITE_API_BASE_URL`. O padrão é `/api/v1`. Para autenticação com sessão Django, sirva os dois serviços na mesma origem, encaminhe esse prefixo ao Django e configure o cookie CSRF indicado em `VITE_API_CSRF_COOKIE`. O cliente envia cookies com a requisição e o token CSRF em `X-CSRFToken` nas operações de escrita. Em produção, encaminhe as rotas da interface para `index.html` e mantenha as rotas da API no back-end.

A interface usa um contrato provisório enquanto o OpenAPI da [BE02](https://github.com/rhamede-crypto/crm-financeiro-extensao/issues/3) está pendente. Centralize a adaptação de caminhos, tipos e erros em [`src/api.js`](src/api.js) quando o contrato for publicado. O escopo da empresa deve vir da sessão no servidor. Uma chamada de escrita não envia identificador de empresa. Use valores monetários decimais em texto, datas civis em `AAAA-MM-DD` e instantes no formato ISO 8601. Respostas de erro usam `{ "message": "...", "errors": { "campo": ["..."] } }`. Responda com 401 quando a sessão expirar e com 403 ou 404 para fichas sem acesso.

| Rotas provisórias | Dados consumidos pela interface |
| --- | --- |
| `GET /session`, `POST /auth/register`, `POST /auth/login`, `POST /auth/logout`, `POST /company` | Sessão com `user` e `company` (nula antes do onboarding). `GET /session` inicializa também o cookie CSRF quando aplicável. |
| `GET /imports/options`, `GET/POST /imports` | Limites, formatos, tipos e lista de lotes. O upload usa formulário multipart com `file` e `type`. |
| `GET /imports/:id`, `POST /imports/:id/confirm`, `POST /imports/:id/cancel` | Estados `queued`, `processing`, `review`, `completed`, `failed` e `canceled`. Revisão com `columns`, `fields`, `mapping`, `preview` e `ambiguities`. Confirmação recebe `mapping` e `resolutions`. A consolidação retorna `summary`. |
| `GET /dashboard`, `POST /chat` | Projeções, alerta de saldo negativo, atualização, ranking e alertas de custos. O chat recebe `question` e retorna `text`, `references` e `insufficient`. |
| `GET/PUT /reminders` | `available`, `channel`, `enabled`, `weekday` e `lastConsolidated`. O link encaminhado pelo canal aponta para a rota React `/importacoes`. |
| `GET /contacts?query=&type=`, `GET /contacts/:id`, `POST /contacts/:id/agreements` | Pesquisa, ficha de cliente (`metrics`, `invoices`, `history`) ou fornecedor (`costHistory`, `alerts`, `agreements`). |
| `GET /contacts/:id/timeline`, `POST /contacts/:id/timeline/notes`, `POST /contacts/:id/timeline/:noteId/confirm` | Eventos `note`, `promise` e `payment`. Uma nota pode trazer `suggestion` com título, valor e data revisáveis. |
| `POST /contacts/:id/collections/preview`, `POST /contacts/:id/collections/send` | Prévia com `available`, `channel`, `channelId`, `text` e motivo de indisponibilidade. Envio confirmado retorna estado de entrega. |
| `GET /deals`, `PATCH /deals/:id` | Cartões com etapa e versão. A transição recebe `stage` e `version` para detectar mudanças concorrentes. |

Upload, confirmação da importação, chat, envio de cobrança e confirmação de promessa usam `Idempotency-Key` para repetir uma tentativa sem duplicá-la. As garantias de processamento, fila, autorização e envio pertencem à API.

## Verificar

```sh
npm run build
npx playwright install chromium
npm test
```

A suíte Playwright usa Chromium com perfil móvel. Ela cobre cadastro, importação, revisão, baixa, reenvio, retorno pelo lembrete, carteira, negociação e timeline. No modo REST, respostas HTTP controladas exercitam erros e sessão expirada. Os testes de acessibilidade automatizada e de teclado cobrem o painel e o chat.

O cenário de volume anexa a amostra e os tempos em `evidencia-mock.json` nos resultados do Playwright. Repita a FE08 com a API Django, uma amostra variada nos três formatos e duas empresas de teste. Meça o tempo entre o aceite do upload e a solicitação de revisão ou o resultado consolidado, e registre a proporção de arquivos corretamente processados sem intervenção. Registre também o ambiente e valide o chat com leitor de tela em dispositivo móvel.
