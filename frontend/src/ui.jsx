import { cloneElement, useEffect, useId, useRef, useState } from 'react';
import { Link } from 'react-router-dom';

export function useResource(load) {
  const [result, setResult] = useState(null);
  const [revision, setRevision] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal).then((data) => {
      if (!controller.signal.aborted) setResult({ load, revision, data });
    }).catch((error) => {
      if (!controller.signal.aborted) setResult({ load, revision, error });
    });
    return () => controller.abort();
  }, [load, revision]);
  const current = result?.load === load && result.revision === revision ? result : null;
  return {
    data: current?.data, error: current?.error, loading: current === null,
    reload: () => setRevision((value) => value + 1),
  };
}

export function useAction() {
  const active = useRef(false);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState(null);
  async function run(action) {
    if (active.current) return;
    active.current = true;
    setBusy(true);
    setError(null);
    try {
      await action();
    } catch (failure) {
      setError(failure);
    } finally {
      active.current = false;
      setBusy(false);
    }
  }
  return { busy, error, run, clearError: () => setError(null) };
}

export function ErrorMessage({ error }) {
  if (!error) return null;
  const errors = Object.entries(error.fields || {}).flatMap(([field, value]) =>
    Array.isArray(value) ? value.map((message) => [field, message]) : [[field, value]]);
  return (
    <div className="notice danger" role="alert">
      <div>{error.message}</div>
      {errors.length > 0 && <ul>{errors.map(([field, message], index) =>
        <li key={field + index}>{fieldNames[field] ? fieldNames[field] + ' · ' : ''}{String(message)}</li>)}</ul>}
    </div>
  );
}

const fieldNames = { name: 'Nome', email: 'E-mail', password: 'Senha', amount: 'Valor', date: 'Data',
  terms: 'Termos', file: 'Arquivo', type: 'Tipo de dados', mapping: 'Mapeamento' };

export function Field({ label, children, hint }) {
  const id = useId();
  const hintId = hint ? id + '-hint' : undefined;
  return <div className="field">
    <label htmlFor={id}>{label}</label>
    {cloneElement(children, { id, 'aria-describedby': hintId })}
    {hint && <small id={hintId}>{hint}</small>}
  </div>;
}

export function Loading({ text = 'Carregando…' }) {
  return <p className="notice" role="status">{text}</p>;
}

export function Resource({ resource, children, access = false }) {
  if (resource.loading) return <Loading />;
  if (resource.error) {
    if (access && [403, 404].includes(resource.error.status)) {
      return <Empty title="Ficha indisponível" detail="Confira a carteira da sua empresa."
        action={<Link to="/carteira">Voltar para a carteira</Link>} />;
    }
    return <><ErrorMessage error={resource.error} /><button type="button" className="secondary" onClick={resource.reload}>
      Tentar novamente
    </button></>;
  }
  return children(resource.data);
}

export function Empty({ title, detail, action }) {
  return <div className="empty"><strong>{title}</strong>{detail && <p>{detail}</p>}{action}</div>;
}

export function PageHeader({ title, description, action }) {
  return <header className="page-header"><div><h1>{title}</h1>{description && <p>{description}</p>}</div>{action}</header>;
}

export function Panel({ title, children }) {
  return <section className="panel">{title && <h2>{title}</h2>}{children}</section>;
}

export function Tag({ children, tone = '' }) {
  return <span className={'tag ' + tone}>{children}</span>;
}

export function DataList({ items, empty }) {
  if (!items?.length) return <Empty title={empty} />;
  return <ul className="data-list">{items}</ul>;
}

export function useRequestKey() {
  const previous = useRef(null);
  return (payload) => {
    const signature = JSON.stringify(payload);
    if (previous.current?.signature !== signature) {
      previous.current = { signature, key: crypto.randomUUID() };
    }
    return previous.current.key;
  };
}
