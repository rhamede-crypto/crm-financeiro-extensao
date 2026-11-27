import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api } from './api';
import { date, entryLabels, money, stages, today } from './domain';
import { DataList, Empty, ErrorMessage, Field, PageHeader, Panel, Resource, Tag,
  useAction, useRequestKey, useResource } from './ui';

const contactTypes = { customer: 'Cliente', supplier: 'Fornecedor' };

export function Contacts() {
  const [filters, setFilters] = useState({ query: '', type: '' });
  const load = useCallback((signal) => api.contacts(filters.query, filters.type, signal), [filters]);
  const contacts = useResource(load);
  return <>
    <PageHeader title="Carteira" description="Consulte as fichas de clientes e fornecedores." />
    <Panel>
      <form className="filters" onSubmit={(event) => {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        setFilters({ query: values.get('query').trim(), type: values.get('type') });
      }}>
        <Field label="Nome"><input type="search" name="query" maxLength={140} /></Field>
        <Field label="Tipo"><select name="type"><option value="">Todos</option>
          <option value="customer">Clientes</option><option value="supplier">Fornecedores</option></select></Field>
        <button type="submit">Pesquisar</button>
      </form>
      <Resource resource={contacts}>{(items) =>
        <DataList empty="Nenhum contato encontrado" items={items.map((person) => <li key={person.id}>
          <Link to={'/carteira/' + encodeURIComponent(person.id)}>{person.name}</Link><Tag>{contactTypes[person.type]}</Tag>
        </li>)} />}
      </Resource>
    </Panel>
  </>;
}

export function Contact() {
  const { id } = useParams();
  const load = useCallback((signal) => api.contact(id, signal), [id]);
  const contact = useResource(load);
  return <Resource resource={contact} access>{(item) =>
    <ContactView key={id} contact={item} id={id} />}
  </Resource>;
}

function ContactView({ contact, id }) {
  return <>
    <PageHeader title={contact.name} description={contactTypes[contact.type]}
      action={<Link to="/carteira">Voltar à carteira</Link>} />
    <div className="stack">
      {contact.type === 'supplier' ? <Supplier contact={contact} /> : <Customer contact={contact} />}
      <Timeline id={id} />
    </div>
  </>;
}

function Customer({ contact }) {
  return <>
    <Panel title="Indicadores do cliente">
      <dl className="summary-grid">
        <div><dt>LTV · total pago</dt><dd>{money(contact.metrics?.ltv)}</dd></div>
        <div><dt>Ticket médio</dt><dd>{money(contact.metrics?.average)}</dd></div>
        <div><dt>Pontualidade</dt><dd><Tag>{contact.metrics?.score || 'Sem histórico'}</Tag></dd></div>
      </dl>
    </Panel>
    <div className="split">
      <Panel title="Faturas em aberto"><DataList empty="Sem faturas abertas" items={contact.invoices?.map((invoice, index) =>
        <li key={invoice.id + ':' + index}><div><strong>{invoice.label}</strong>
          <p>Vencimento · {date(invoice.due)}</p></div><strong>{money(invoice.amount)}</strong></li>)} /></Panel>
      <Panel title="Histórico financeiro"><DataList empty="Sem lançamentos no histórico" items={contact.history?.map((item, index) =>
        <li key={item.id || index}><div><strong>{item.label}</strong>
          <p>{date(item.date)}</p></div><strong>{money(item.amount)}</strong></li>)} /></Panel>
    </div>
  </>;
}

function month(value) {
  if (!/^\d{4}-\d{2}$/.test(value || '')) return value || '—';
  const [year, month] = value.split('-');
  return month + '/' + year;
}

function Supplier({ contact }) {
  const [agreements, setAgreements] = useState(contact.agreements || []);
  const { error, busy, run } = useAction();
  return <>
    <div className="split">
      <Panel title="Histórico de custos">
        <DataList empty="Sem períodos disponíveis" items={contact.costHistory?.map((item) =>
          <li className="cost-period" key={item.period}><strong>{month(item.period)}</strong>
            <div><p>Gasto mensal · {item.spending == null ? 'Sem dados' : money(item.spending)}</p>
              <p>Preço unitário · {item.unitPrice == null ? 'Sem preço comparável' :
                money(item.unitPrice) + (item.unit ? ' por ' + item.unit : '')}</p></div></li>)} />
      </Panel>
      <Panel title="Alertas associados">
        <DataList empty="Sem alertas para este fornecedor" items={contact.alerts?.map((alert) =>
          <li key={alert.id}><div><strong>{alert.category}</strong><p>{alert.period}</p><p>{alert.recommendation}</p></div>
            {alert.change != null && <Tag tone="warn">{alert.change.toLocaleString('pt-BR')}%</Tag>}</li>)} />
      </Panel>
    </div>
    <Panel title="Acordos de renegociação">
      <DataList empty="Nenhum acordo registrado" items={agreements.map((agreement) =>
        <li key={agreement.id}><div><strong>{date(agreement.date)}</strong><p className="wrap-text">{agreement.terms}</p></div>
          {agreement.alertId && <Tag>{contact.alerts?.find(({ id }) => id === agreement.alertId)?.category || 'Alerta associado'}</Tag>}
        </li>)} />
      <form onSubmit={(event) => {
        event.preventDefault();
        const form = event.currentTarget;
        const values = Object.fromEntries(new FormData(form));
        run(async () => {
          const saved = await api.agreements(contact.id, { ...values, alertId: values.alertId || null });
          setAgreements((list) => [saved, ...list]);
          form.reset();
        });
      }}>
        <ErrorMessage error={error} />
        <fieldset disabled={busy}>
          <Field label="Data do acordo"><input type="date" name="date" defaultValue={today()} required /></Field>
          <Field label="Termos do acordo"><textarea name="terms" rows={3} maxLength={3000} required /></Field>
          {contact.alerts?.length > 0 && <Field label="Alerta (opcional)">
            <select name="alertId"><option value="">Sem vínculo</option>
              {contact.alerts.map((alert) => <option key={alert.id} value={alert.id}>{alert.category} · {alert.period}</option>)}
            </select>
          </Field>}
          <button type="submit">{busy ? 'Registrando…' : 'Registrar acordo'}</button>
        </fieldset>
      </form>
    </Panel>
  </>;
}

function Timeline({ id }) {
  const load = useCallback((signal) => api.timeline(id, signal), [id]);
  const timeline = useResource(load);
  return <Panel title="Timeline"><Resource resource={timeline}>{(entries) => <TimelineEditor id={id} initial={entries} />}</Resource></Panel>;
}

function TimelineEditor({ id, initial }) {
  const [entries, setEntries] = useState(initial);
  const [draft, setDraft] = useState('');
  const { error, busy, run } = useAction();
  const sorted = [...entries].sort((first, second) => (second.createdAt || second.date || '')
    .localeCompare(first.createdAt || first.date || ''));
  return <>
    <DataList empty="Nenhuma atividade registrada" items={sorted.map((entry) => <li key={entry.id} className="timeline-entry">
      <div className="timeline-heading">
        <Tag tone={entry.kind === 'payment' ? 'good' : entry.kind === 'promise' ? 'warn' : ''}>
          {entryLabels[entry.kind] || 'Atividade'}
        </Tag>
        <span>{date(entry.date || entry.createdAt)}{entry.author && ' · ' + entry.author}</span>
      </div>
      <p className="wrap-text">{entry.text}</p>
      {entry.amount != null && <strong>{money(entry.amount)}</strong>}
      {entry.suggestion && <PromiseEditor id={id} entry={entry} onConfirm={(saved) => setEntries((list) =>
        [...list.map((item) => item.id === entry.id ? { ...item, suggestion: null } : item), saved])} />}
    </li>)} />
    <form onSubmit={(event) => {
      event.preventDefault();
      if (!draft.trim()) return;
      run(async () => {
        const saved = await api.note(id, { text: draft.trim() });
        setEntries((list) => [...list, saved]);
        setDraft('');
      });
    }}>
      <ErrorMessage error={error} />
      <Field label="Nova nota"><textarea rows={3} maxLength={3000} required value={draft} readOnly={busy}
        onChange={(event) => setDraft(event.target.value)} /></Field>
      <button type="submit" disabled={busy || !draft.trim()}>{busy ? 'Salvando…' : 'Adicionar nota'}</button>
    </form>
  </>;
}

function PromiseEditor({ id, entry, onConfirm }) {
  const { error, busy, run } = useAction();
  const requestKey = useRequestKey();
  return <form className="promise-form" onSubmit={(event) => {
    event.preventDefault();
    const data = Object.fromEntries(new FormData(event.currentTarget));
    run(async () => onConfirm(await api.confirmPromise(id, entry.id, data, requestKey(data))));
  }}>
    <h3>Promessa sugerida</h3>
    <p>Confira os dados antes de incluir a promessa na projeção de caixa.</p>
    <ErrorMessage error={error} />
    <fieldset disabled={busy}>
      <div className="field-grid">
        <Field label="Título"><input name="title" required maxLength={140} defaultValue={entry.suggestion.title} /></Field>
        <Field label="Valor (R$)"><input name="amount" type="number" min="0.01" step="0.01" inputMode="decimal"
          defaultValue={entry.suggestion.amount} required /></Field>
        <Field label="Data da promessa"><input name="date" type="date" defaultValue={entry.suggestion.date} required /></Field>
      </div>
      <button type="submit">{busy ? 'Confirmando…' : 'Confirmar promessa'}</button>
    </fieldset>
  </form>;
}

export function Pipeline() {
  const deals = useResource(api.deals);
  return <>
    <PageHeader title="Negociações" description="Acompanhe as etapas de recuperação de crédito." />
    <Resource resource={deals}>{(items) => <Board initial={items} onReload={deals.reload} />}</Resource>
  </>;
}

function Board({ initial, onReload }) {
  const [items, setItems] = useState(initial);
  const [failed, setFailed] = useState(false);
  const [announcement, setAnnouncement] = useState('');
  const [focusedId, setFocusedId] = useState(null);
  const buttons = useRef(new Map());
  const dragId = useRef(null);
  const { error, busy, run } = useAction();
  useEffect(() => {
    if (focusedId && !busy) buttons.current.get(focusedId)?.focus();
  }, [focusedId, items, busy]);

  function move(item, stage) {
    if (!item || item.stage === stage || busy || failed) return;
    setAnnouncement('');
    run(async () => {
      try {
        const saved = await api.moveDeal(item.id, { stage, version: item.version });
        setFocusedId(saved.id);
        setItems((deals) => deals.map((deal) => deal.id === saved.id ? saved : deal));
        setAnnouncement(saved.title + ' movida para ' + stages.find(([value]) => value === stage)?.[1] + '.');
      } catch (failure) {
        setFailed(true);
        throw failure;
      }
    });
  }

  return <>
    <ErrorMessage error={error} />
    {failed && <button type="button" className="secondary" onClick={onReload}>Recarregar quadro</button>}
    <p role="status" className={announcement ? 'notice success' : 'sr-only'}>{announcement}</p>
    <div className="board">
      {stages.map(([stage, label]) => {
        const deals = items.filter((item) => item.stage === stage);
        return <section className="board-stage" key={stage} onDragOver={(event) => {
          if (dragId.current && !busy && !failed) event.preventDefault();
        }} onDrop={(event) => {
          event.preventDefault();
          move(items.find(({ id }) => id === dragId.current), stage);
          dragId.current = null;
        }}>
          <h2>{label} <span aria-label={deals.length + ' negociações'}>{deals.length}</span></h2>
          {deals.length ? <ul>{deals.map((item) =>
            <li key={item.id} className="deal-card" draggable={!busy && !failed}
              onDragStart={(event) => { dragId.current = item.id; event.dataTransfer.effectAllowed = 'move';
                event.dataTransfer.setData('text/plain', 'negociação'); }}
              onDragEnd={() => { dragId.current = null; }}>
              <h3>{item.title}</h3>
              <p>{item.name}</p>
              <strong>{money(item.amount)}</strong>
              <details><summary>Detalhes</summary><p>Vencimento · {date(item.due)}</p>
                {item.contactId && <Link to={'/carteira/' + encodeURIComponent(item.contactId)}>Abrir ficha</Link>}
              </details>
              <form onSubmit={(event) => {
                event.preventDefault();
                move(item, new FormData(event.currentTarget).get('stage'));
              }}>
                <Field label="Mover para">
                  <select name="stage" defaultValue={stage} disabled={busy || failed}>
                    {stages.map(([value, name]) => <option key={value} value={value}>{name}</option>)}
                  </select>
                </Field>
                <button className="secondary" type="submit" disabled={busy || failed} ref={(button) => {
                  if (button) buttons.current.set(item.id, button);
                  else buttons.current.delete(item.id);
                }}>Mover cartão</button>
              </form>
            </li>)}</ul> : <Empty title="Sem negociações" />}
        </section>;
      })}
    </div>
  </>;
}
