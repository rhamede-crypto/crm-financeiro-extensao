import { useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, api } from './api';
import { date, importStatus } from './domain';
import { DataList, Empty, ErrorMessage, Field, Loading, PageHeader, Panel, Resource, Tag,
  useAction, useRequestKey, useResource } from './ui';

export function ImportPage() {
  const options = useResource(api.importOptions);
  const jobs = useResource(api.jobs);
  return <>
    <PageHeader title="Importações" description="Envie planilhas e acompanhe a consolidação dos seus lançamentos." />
    <div className="split">
      <Panel title="Nova importação">
        <Resource resource={options}>{(config) => <Upload config={config} />}</Resource>
      </Panel>
      <Panel title="Histórico">
        <Resource resource={jobs}>{(data) => <DataList empty="Nenhuma importação" items={data.map((job) =>
          <li key={job.id}><div><Link to={'/importacoes/' + encodeURIComponent(job.id)}>{job.filename}</Link>
            <p>{date(job.createdAt)}</p></div><Tag>{importStatus[job.status]}</Tag></li>)} />}</Resource>
      </Panel>
    </div>
  </>;
}

function Upload({ config }) {
  const { error, busy, run } = useAction();
  const navigate = useNavigate();
  const currentKey = useRequestKey();
  const selection = useRef(0);
  const validFiles = config.extensions.map((ext) => '.' + ext).join(', ');
  const size = new Intl.NumberFormat('pt-BR', { maximumFractionDigits: 2 }).format(config.maxBytes / 1024 ** 2);
  return <form onSubmit={(event) => {
    event.preventDefault();
    const values = new FormData(event.currentTarget);
    const file = values.get('file');
    run(async () => {
      if (!file?.size || !config.extensions.includes(file.name.split('.').at(-1).toLowerCase())) {
        throw new ApiError(422, 'Selecione uma planilha válida.');
      }
      if (file.size > config.maxBytes) throw new ApiError(413, 'O arquivo ultrapassa o limite de ' + size + ' MB.');
      const job = await api.upload(values, currentKey([values.get('type'), selection.current]));
      navigate('/importacoes/' + encodeURIComponent(job.id));
    });
  }}>
    <ErrorMessage error={error} />
    <fieldset disabled={busy}>
      <Field label="Tipo de dados">
        <select name="type" defaultValue="" required><option value="" disabled>Selecione</option>
          {config.types.map(({ id, label }) => <option key={id} value={id}>{label}</option>)}
        </select>
      </Field>
      <Field label="Planilha" hint={validFiles.toUpperCase() + ' · Até ' + size + ' MB' +
        (config.maxRows ? ' · ' + config.maxRows.toLocaleString('pt-BR') + ' linhas' : '')}>
        <input type="file" name="file" accept={validFiles} required onChange={() => { selection.current++; }} />
      </Field>
      <button type="submit">{busy ? 'Enviando…' : 'Enviar planilha'}</button>
    </fieldset>
  </form>;
}

export function ImportJob() {
  const { id } = useParams();
  return <JobView key={id} id={id} />;
}

function JobView({ id }) {
  const [job, setJob] = useState(null);
  const [error, setError] = useState(null);
  const [attempt, setAttempt] = useState(0);
  useEffect(() => {
    const controller = new AbortController();
    let timer;
    async function poll() {
      try {
        const current = await api.job(id, controller.signal);
        if (controller.signal.aborted) return;
        setJob(current);
        if (['queued', 'processing'].includes(current.status)) timer = setTimeout(poll, 950);
      } catch (failure) {
        if (!controller.signal.aborted) setError(failure);
      }
    }
    poll();
    return () => { controller.abort(); clearTimeout(timer); };
  }, [id, attempt]);

  return <>
    <PageHeader title={job?.filename || 'Acompanhar importação'} action={<Link to="/importacoes">Ver importações</Link>} />
    <ErrorMessage error={error} />
    {error && <button type="button" className="secondary" onClick={() => { setError(null); setAttempt(attempt + 1); }}>
      Tentar novamente
    </button>}
    {!job && !error && <Loading />}
    {job && <div className="stack">
      <p role="status"><Tag tone={job.status === 'completed' ? 'good' : ''}>{importStatus[job.status]}</Tag></p>
      {['queued', 'processing'].includes(job.status) &&
        <Loading text="Você pode sair desta tela e retomar pela lista de importações." />}
      {job.status === 'review' && <Review job={job} onChange={setJob} />}
      {job.status === 'failed' && <ErrorMessage error={{ message: job.error || 'Não foi possível processar a planilha.' }} />}
      {job.status === 'canceled' && <Empty title="Importação cancelada" />}
      {job.status === 'completed' && <Panel title="Resumo da consolidação">
        <dl className="summary-grid">
          <div><dt>Novos</dt><dd>{job.summary?.created ?? '—'}</dd></div>
          <div><dt>Atualizados</dt><dd>{job.summary?.updated ?? '—'}</dd></div>
          <div><dt>Sem alterações</dt><dd>{job.summary?.unchanged ?? '—'}</dd></div>
          <div><dt>Rejeitados</dt><dd>{job.summary?.rejected ?? '—'}</dd></div>
        </dl>
        <Link to="/">Ver painel financeiro</Link>
      </Panel>}
    </div>}
  </>;
}

function Review({ job, onChange }) {
  const currentMapping = job.selectedMapping ||
    Object.fromEntries(Object.entries(job.mapping).map(([field, value]) => [field, value.column]));
  const [mapping, setMapping] = useState(currentMapping);
  const [resolutions, setResolutions] = useState({});
  const { error, busy, run } = useAction();
  const currentKey = useRequestKey();
  const known = new Set(job.columns.map(({ id }) => id));
  const used = Object.values(mapping).filter(Boolean);
  const mappingValid = job.fields.every((field) => !field.required || known.has(mapping[field.id])) &&
    used.every((id) => known.has(id)) && used.length === new Set(used).size;
  const sameMapping = job.fields.every(({ id }) =>
    (currentMapping[id] || '') === (mapping[id] || ''));
  const ambiguities = sameMapping ? job.ambiguities || [] : [];
  const canSubmit = mappingValid && ambiguities.every((item) => item.options.includes(resolutions[item.id]));

  return <div className="stack">
    <Panel title="Prévia da planilha">
      <div className="table-scroll" tabIndex={0} role="region" aria-label="Prévia da planilha">
        <table><thead><tr>{job.columns.map((column) => <th scope="col" key={column.id}>{column.label}</th>)}</tr></thead>
          <tbody>{job.preview.map((row, index) => <tr key={index}>{row.map((cell, position) =>
            <td key={position}>{cell || '—'}</td>)}</tr>)}</tbody>
        </table>
      </div>
    </Panel>
    <Panel title="Mapeamento de colunas">
      <form onSubmit={(event) => {
        event.preventDefault();
        if (!canSubmit) return;
        const data = { mapping, resolutions };
        run(async () => onChange(await api.confirmImport(job.id, data, currentKey(data))));
      }}>
        <ErrorMessage error={error} />
        {!mappingValid && <p className="notice">Associe uma coluna diferente a cada campo obrigatório para confirmar.</p>}
        <fieldset disabled={busy}>
          <div className="field-grid">{job.fields.map((field) => {
            const proposed = job.mapping[field.id];
            const hint = !mapping[field.id] && field.required ? 'Mapeamento obrigatório ausente.'
              : proposed?.column && proposed.confidence === 'low' && mapping[field.id] === proposed.column
                ? 'Baixa confiança. Confira esta sugestão.' : null;
            return <Field key={field.id} label={field.label + (field.required ? ' *' : '')} hint={hint}>
              <select required={field.required} value={mapping[field.id] ?? ''} onChange={(event) => {
                setMapping({ ...mapping, [field.id]: event.target.value });
                setResolutions({});
              }}>
                <option value="">Sem coluna</option>
                {job.columns.map((column) => <option key={column.id} value={column.id}>{column.label}</option>)}
              </select>
            </Field>;
          })}</div>
          {ambiguities.length > 0 && <section>
            <h3>Possíveis duplicidades</h3>
            {ambiguities.map((item) => <Field key={item.id} label={'Linha ' + item.row + ' · ' + item.description}>
              <select required value={resolutions[item.id] || ''} onChange={(event) =>
                setResolutions({ ...resolutions, [item.id]: event.target.value })}>
                <option value="">Selecione como tratar</option>
                {item.options.map((option) => <option key={option} value={option}>
                  {({ new: 'Incluir como lançamento novo', ignore: 'Manter lançamento existente' })[option] || option}
                </option>)}
              </select>
            </Field>)}
          </section>}
          <div className="actions">
            <button type="submit" disabled={!canSubmit}>{busy ? 'Aguarde…' : 'Confirmar importação'}</button>
            <button type="button" className="secondary" onClick={() => run(async () => onChange(await api.cancelImport(job.id)))}>
              Cancelar importação
            </button>
          </div>
        </fieldset>
      </form>
    </Panel>
  </div>;
}
