import { useCallback, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from './api';
import { date, money, tones } from './domain';
import { DataList, Empty, ErrorMessage, Field, PageHeader, Panel, Resource, Tag,
  useAction, useRequestKey, useResource } from './ui';

export function Dashboard() {
  const dashboard = useResource(api.dashboard);
  return <>
    <PageHeader title="Visão geral" description="Acompanhe o caixa, o impacto das cobranças e a variação dos custos."
      action={<Link className="button" to="/importacoes">Importar planilha</Link>} />
    <Resource resource={dashboard}>{(data) => <>
      <div className="section-head"><h2>Projeção de caixa</h2>
        <p>Atualização dos dados · {data.updatedAt ? date(data.updatedAt) : 'Nenhuma importação consolidada'}</p></div>
      {data.projections.length ? <div className="projections">{data.projections.map(({ days, amount }) =>
        <div className={'projection panel' + (Number(amount) < 0 ? ' negative' : '')} key={days}>
          <span>{days} dias</span><strong>{money(amount)}</strong>
        </div>)}</div> : <Empty title="Sem histórico de caixa" detail="Importe lançamentos para começar." />}
      {data.negativeDate && <p className="notice danger">Saldo negativo previsto para {date(data.negativeDate)}.</p>}
      <div className="split finance-split">
        <Panel title="Top 5 de inadimplência">
          <DataList empty="Nenhum cliente inadimplente no ranking" items={data.ranking.map((entry, index) =>
            <li key={entry.id}>
              <div className="rank-entry"><span className="rank">{index + 1}</span>
                <div><strong>{entry.name}</strong><p>{entry.days} dias de atraso</p></div></div>
              <div className="rank-total"><strong>{money(entry.amount)}</strong>
                <Link to={'/cobrancas/' + encodeURIComponent(entry.id)} aria-label={'Preparar cobrança para ' + entry.name}>Preparar cobrança</Link></div>
            </li>)} />
        </Panel>
        <Panel title="Alertas de custos">
          <DataList empty="Nenhum alerta de custo" items={data.alerts.map((alert) =>
            <li key={alert.id}><div><strong>{alert.category}</strong>
              <p>{alert.supplier} · {alert.period}</p><p>{alert.recommendation}</p>
              {alert.supplierId && <Link to={'/carteira/' + encodeURIComponent(alert.supplierId)}>Ver fornecedor</Link>}</div>
              {alert.change != null && <Tag tone="warn">{alert.change > 0 ? '+' : ''}{alert.change.toLocaleString('pt-BR')}%</Tag>}
            </li>)} />
        </Panel>
      </div>
    </>}</Resource>
  </>;
}

export function Collection() {
  const { id } = useParams();
  return <CollectionEditor key={id} id={id} />;
}

function CollectionEditor({ id }) {
  const [tone, setTone] = useState('friendly');
  const [status, setStatus] = useState('');
  const send = useAction();
  const fetchPreview = useCallback((signal) => api.collectionPreview(id, { tone }, signal), [id, tone]);
  const preview = useResource(fetchPreview);
  return <>
    <PageHeader title="Preparar cobrança" description="Confira a mensagem e o canal antes de confirmar."
      action={<Link to="/">Voltar ao ranking</Link>} />
    <Panel>
      <Field label="Tom da mensagem">
        <select value={tone} disabled={send.busy || Boolean(status)} onChange={(event) => { send.clearError(); setTone(event.target.value); }}>
          {tones.map(([value, label]) => <option value={value} key={value}>{label}</option>)}
        </select>
      </Field>
      <Resource resource={preview} access>{(data) => data.available
        ? <CollectionMessage key={tone} id={id} tone={tone} preview={data} status={status} setStatus={setStatus} send={send} />
        : <Empty title="Canal indisponível" detail={data.reason} />}</Resource>
    </Panel>
  </>;
}

const deliveryStatus = {
  simulated: 'Envio simulado nesta demonstração.',
  queued: 'Envio registrado e aguardando processamento.',
  sent: 'Mensagem enviada.',
  delivered: 'Mensagem entregue.',
};

function CollectionMessage({ id, tone, preview, status, setStatus, send }) {
  const [text, setText] = useState(preview.text);
  const { error, busy, run } = send;
  const requestKey = useRequestKey();
  return <form onSubmit={(event) => {
    event.preventDefault();
    if (!text.trim() || status) return;
    const data = { tone, text: text.trim(), channel: preview.channelId || preview.channel };
    run(async () => {
      const result = await api.sendCollection(id, data, requestKey(data));
      setStatus(deliveryStatus[result.status] || result.reason ||
        (result.status === 'failed' ? 'Falha no envio.' : 'Estado do envio: ' + (result.status || 'indisponível')));
    });
  }}>
    <p className="notice">Canal · {preview.channel}</p>
    <ErrorMessage error={error} />
    <Field label="Mensagem">
      <textarea rows={6} required maxLength={4000} value={text} onChange={(event) => setText(event.target.value)}
        readOnly={busy || Boolean(status)} />
    </Field>
    <button type="submit" disabled={busy || Boolean(status) || !text.trim()}>{busy ? 'Enviando…' : 'Confirmar envio'}</button>
    {status && <p className="notice" role="status">{status}</p>}
  </form>;
}

export function Chat() {
  const [draft, setDraft] = useState('');
  const [messages, setMessages] = useState([]);
  const { error, busy, run } = useAction();
  const requestKey = useRequestKey();
  const attempt = useRef(0);
  const input = useRef(null);
  return <>
    <PageHeader title="CEO IA" description="Consulte os indicadores financeiros da sua empresa." />
    <Panel title="Conversa">
      <div role="log" aria-label="Mensagens da conversa" className="conversation">
        {!messages.length && <Empty title="Envie uma pergunta" detail="Exemplo: Qual é o saldo projetado para os próximos 90 dias?" />}
        {messages.map(({ id, question, response }) => <div className="message-group" key={id}>
          <div className="message question"><strong>Você</strong><p>{question}</p></div>
          <div className="message answer"><strong>CEO IA</strong>
            {response.insufficient && <Tag tone="warn">Dados insuficientes</Tag>}
            <p>{response.text}</p>
            {response.references?.length > 0 && <ul aria-label="Referências dos indicadores">
              {response.references.map((entry, index) => <li key={index}>{entry}</li>)}</ul>}
          </div>
        </div>)}
      </div>
      {busy && <p role="status">Aguardando resposta…</p>}
      <ErrorMessage error={error} />
      <form className="chat-form" onSubmit={(event) => {
        event.preventDefault();
        const question = draft.trim();
        if (!question) return;
        run(async () => {
          const id = requestKey([attempt.current, question]);
          const response = await api.ask({ question }, id);
          setMessages((current) => [...current, { id, question, response }]);
          setDraft('');
          attempt.current++;
          input.current?.focus();
        });
      }}>
        <Field label="Sua pergunta"><textarea ref={input} rows={2} maxLength={2000} required value={draft}
          readOnly={busy} onChange={(event) => setDraft(event.target.value)} /></Field>
        <button type="submit" disabled={busy || !draft.trim()}>{busy ? 'Enviando…' : error ? 'Tentar enviar de novo' : 'Enviar pergunta'}</button>
      </form>
    </Panel>
  </>;
}

const weekdays = [
  ['monday', 'Segunda-feira'], ['tuesday', 'Terça-feira'], ['wednesday', 'Quarta-feira'],
  ['thursday', 'Quinta-feira'], ['friday', 'Sexta-feira'], ['saturday', 'Sábado'], ['sunday', 'Domingo'],
];

export function Reminders() {
  const settings = useResource(api.reminders);
  return <>
    <PageHeader title="Empresa" description="Preferências para manter a planilha financeira atualizada." />
    <Panel title="Lembrete semanal">
      <Resource resource={settings}>{(data) => <ReminderForm settings={data} />}</Resource>
    </Panel>
  </>;
}

function ReminderForm({ settings }) {
  const [saved, setSaved] = useState(false);
  const [enabled, setEnabled] = useState(settings.enabled);
  const [weekday, setWeekday] = useState(settings.weekday);
  const { error, busy, run } = useAction();
  return <>
    <p>Última consolidação · {settings.lastConsolidated ? date(settings.lastConsolidated) : 'Nenhuma importação'}</p>
    <p>Canal · {settings.available ? settings.channel : settings.reason || 'Indisponível'}</p>
    <form onSubmit={(event) => {
      event.preventDefault();
      run(async () => {
        const preferences = await api.saveReminders({ enabled, weekday });
        setEnabled(preferences.enabled);
        setWeekday(preferences.weekday);
        setSaved(true);
      });
    }} onChange={() => setSaved(false)}>
      <ErrorMessage error={error} />
      <fieldset disabled={busy || !settings.available}>
        <label className="check"><input type="checkbox" checked={enabled} onChange={(event) => setEnabled(event.target.checked)} />
          Receber lembrete semanal</label>
        <Field label="Dia da semana"><select value={weekday} onChange={(event) => setWeekday(event.target.value)} disabled={!enabled}>
          {weekdays.map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></Field>
        <button type="submit">{busy ? 'Salvando…' : 'Salvar preferências'}</button>
      </fieldset>
      {saved && <p role="status" className="notice success">Preferências salvas.</p>}
    </form>
    <Link to="/importacoes">Abrir importações</Link>
  </>;
}
