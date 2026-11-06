# CRM Financeiro de Extensão

Projeto de extensão para pequenos negócios. O MVP importa planilhas financeiras, projeta o saldo de caixa, prioriza cobranças, sinaliza custos em alta e oferece um chat de consultoria. A expansão acrescenta carteira, fichas, pipeline e histórico de relacionamento.

| Área | Responsável | Stack |
| --- | --- | --- |
| Front-end | Rhámede (`rhamede-crypto`) | React e consumo da API REST |
| Back-end | Nicolas (`Niconfisk`) | Python, Django REST, PostgreSQL, Docker, Celery e Redis |

## Primeira entrega

1. Rhámede começa pela [FE01](../../issues/1), montando a base React e os mocks.
2. Nicolas começa pela [BE01](../../issues/2) e segue para a [BE02](../../issues/3), com o contrato OpenAPI, os estados de importação, os erros e o isolamento por empresa.
3. Com os exemplos do contrato, implementar cadastro e onboarding ([BE03](../../issues/4) e [FE02](../../issues/7)). Em seguida, integrar upload, revisão e consolidação ([BE04](../../issues/6), [BE05](../../issues/9), [BE06](../../issues/11), [FE03](../../issues/10) e [FE04](../../issues/13)).

## Backlog

Cada issue indica os requisitos atendidos, os critérios de aceite e os links das dependências. Os marcos agrupam as entregas por fase.

### 1. [Fundação](../../milestone/1)

| Issue | Entrega | Responsável |
| --- | --- | --- |
| [BE01](../../issues/2) | Base Django, PostgreSQL e Docker | Nicolas |
| [BE02](../../issues/3) | Contrato inicial da API REST e isolamento por empresa | Nicolas |
| [FE01](../../issues/1) | Base React e cliente da API REST | Rhámede |

### 2. [MVP financeiro](../../milestone/2)

| Issue | Entrega | Responsável |
| --- | --- | --- |
| [BE03](../../issues/4) | Autenticação, cadastro e onboarding de empresa | Nicolas |
| [FE02](../../issues/7) | Telas de login, cadastro e onboarding | Rhámede |
| [BE04](../../issues/6) | API de upload e processamento assíncrono de planilhas | Nicolas |
| [BE05](../../issues/9) | Mapeamento de colunas por IA e revisão pela API | Nicolas |
| [BE06](../../issues/11) | Consolidação idempotente e deduplicação de lançamentos | Nicolas |
| [FE03](../../issues/10) | Importação de planilhas e acompanhamento do processamento | Rhámede |
| [FE04](../../issues/13) | Revisão de mapeamento e confirmação da importação | Rhámede |
| [BE07](../../issues/15) | Motor de projeção de caixa de 30, 60 e 90 dias | Nicolas |
| [BE08](../../issues/19) | Ranking dos cinco clientes inadimplentes com maior impacto | Nicolas |
| [BE09](../../issues/16) | Detecção de sangramento financeiro e recomendações | Nicolas |
| [FE05](../../issues/23) | Dashboard de caixa, inadimplência e alertas de custos | Rhámede |
| [BE10](../../issues/5) | Adaptador de IA e proteção de dados financeiros | Nicolas |
| [BE11](../../issues/21) | API do chat de consultoria financeira | Nicolas |
| [FE06](../../issues/25) | Chat mobile do CEO IA | Rhámede |
| [BE12](../../issues/8) | Lembretes semanais para atualizar a planilha | Nicolas |
| [FE07](../../issues/12) | Preferências de lembrete e retorno para importação | Rhámede |
| [FE08](../../issues/29) | Validar o fluxo do MVP no celular com dados sintéticos | Rhámede |

### 3. [Expansão CRM](../../milestone/3)

| Issue | Entrega | Responsável |
| --- | --- | --- |
| [BE13](../../issues/14) | Gerar carteira de clientes e fornecedores no ETL | Nicolas |
| [BE14](../../issues/20) | Calcular indicadores e score da ficha do cliente | Nicolas |
| [FE09](../../issues/24) | Carteira e ficha do cliente | Rhámede |
| [BE15](../../issues/22) | Gerar mensagens e registrar envios de cobrança | Nicolas |
| [FE10](../../issues/28) | Preparar e enviar cobrança a partir do Top 5 | Rhámede |
| [BE16](../../issues/18) | Persistir negociações e etapas do pipeline | Nicolas |
| [FE11](../../issues/27) | Kanban de recuperação de crédito e negociações | Rhámede |
| [BE17](../../issues/17) | Histórico de custos e acordos por fornecedor | Nicolas |
| [FE12](../../issues/26) | Ficha de fornecedor e registro de renegociação | Rhámede |
| [BE18](../../issues/30) | Timeline e promessas de pagamento nas projeções | Nicolas |
| [FE13](../../issues/31) | Timeline nas fichas e confirmação de promessas | Rhámede |

## Pontos para alinhar na implementação

- No contrato REST, documentar autenticação, escopo de empresa, representação de dinheiro e datas, erros e estados de processamento. Manter exemplos sincronizados com os mocks do React.
- Medir a meta de 80% com planilhas variadas, contando arquivos importados corretamente sem revisão humana sobre o total avaliado. Para arquivos de até 10.000 linhas, medir a meta de 30 segundos entre o aceite do upload e o resultado ou a solicitação de revisão. Registrar ambiente e amostra.
- Documentar as premissas de recorrência, a política de deduplicação e as condições para disparar alertas. O back-end calcula os valores financeiros em código. A IA interpreta os dados e sugere ações.
- Usar planilhas sintéticas no desenvolvimento e na demonstração. Validar isolamento entre empresas, criptografia, minimização de dados e políticas de retenção antes de integrar um provedor de IA a dados reais.
- Escolher o canal inicial dos lembretes e da cobrança dentro das issues correspondentes. Registrar na timeline as promessas confirmadas como previsões de recebimento separadas dos valores pagos.

## Rastreabilidade

| Código | Requisito | Issues |
| --- | --- | --- |
| RF01 | Cadastro, autenticação e perfil de empresa | [BE02](../../issues/3), [BE03](../../issues/4), [FE02](../../issues/7), [FE08](../../issues/29) |
| RF02 | Upload CSV, XLSX e XLS | [BE04](../../issues/6), [BE06](../../issues/11), [FE03](../../issues/10), [FE08](../../issues/29) |
| RF03 | ETL e mapeamento semântico | [BE05](../../issues/9), [BE06](../../issues/11), [BE10](../../issues/5), [FE08](../../issues/29) |
| RF04 | Revisão assistida e meta de 80% | [BE05](../../issues/9), [FE04](../../issues/13), [FE08](../../issues/29) |
| RF05 | Runway 30/60/90 dias e alerta | [BE07](../../issues/15), [FE05](../../issues/23), [FE08](../../issues/29) |
| RF06 | Top 5 de inadimplência | [BE08](../../issues/19), [FE05](../../issues/23), [FE08](../../issues/29) |
| RF07 | Anomalias de custo e renegociação | [BE09](../../issues/16), [FE05](../../issues/23), [BE10](../../issues/5), [FE08](../../issues/29) |
| RF08 | Chat de consultoria | [BE10](../../issues/5), [BE11](../../issues/21), [FE06](../../issues/25), [FE08](../../issues/29) |
| RF09 | Lembrete semanal | [BE12](../../issues/8), [FE07](../../issues/12), [FE08](../../issues/29) |
| RF10 | Carteira gerada pelo ETL | [BE13](../../issues/14), [FE09](../../issues/24) |
| RF11 | Ficha e score do cliente | [BE14](../../issues/20), [FE09](../../issues/24) |
| RF12 | Mensagens e envio de cobrança | [BE15](../../issues/22), [FE10](../../issues/28) |
| RF13 | Kanban de recuperação e negociações | [BE16](../../issues/18), [FE11](../../issues/27) |
| RF14 | Histórico de fornecedores e acordos | [BE17](../../issues/17), [FE12](../../issues/26) |
| RF15 | Timeline e promessas de pagamento | [BE18](../../issues/30), [FE13](../../issues/31) |
| RNF01 | Arquitetura hexagonal | [BE01](../../issues/2), [BE02](../../issues/3), [BE05](../../issues/9), [BE10](../../issues/5) |
| RNF02 | Django e Docker | [BE01](../../issues/2) |
| RNF03 | Cálculos determinísticos | [BE06](../../issues/11), [BE07](../../issues/15), [BE08](../../issues/19), [BE09](../../issues/16), [BE10](../../issues/5), [BE11](../../issues/21), [FE08](../../issues/29), [BE14](../../issues/20), [BE17](../../issues/17), [BE18](../../issues/30) |
| RNF04 | Fila e desempenho | [BE01](../../issues/2), [BE04](../../issues/6), [BE05](../../issues/9), [FE03](../../issues/10), [BE12](../../issues/8), [FE08](../../issues/29) |
| RNF05 | Multi-tenancy, segurança e LGPD | [BE02](../../issues/3), [BE03](../../issues/4), [BE04](../../issues/6), [BE05](../../issues/9), [BE06](../../issues/11), [BE10](../../issues/5), [BE11](../../issues/21), [BE12](../../issues/8), [FE08](../../issues/29), [BE13](../../issues/14), [BE14](../../issues/20), [BE15](../../issues/22), [BE16](../../issues/18), [BE17](../../issues/17), [BE18](../../issues/30) |
| RNF06 | Mobile-first | [FE01](../../issues/1), [FE02](../../issues/7), [FE03](../../issues/10), [FE04](../../issues/13), [FE05](../../issues/23), [FE06](../../issues/25), [FE07](../../issues/12), [FE08](../../issues/29), [FE09](../../issues/24), [FE10](../../issues/28), [FE11](../../issues/27), [FE12](../../issues/26), [FE13](../../issues/31) |
| RN01 | Deduplicação de lançamentos | [BE06](../../issues/11), [FE04](../../issues/13), [FE08](../../issues/29) |
| RN02 | Prioridade de cobrança | [BE08](../../issues/19), [FE08](../../issues/29) |
| RN03 | Limite de anomalias de custo | [BE09](../../issues/16), [FE08](../../issues/29) |
