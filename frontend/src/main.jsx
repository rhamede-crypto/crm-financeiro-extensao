import { StrictMode, useEffect, useState } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter, Link, NavLink, Navigate, Outlet, Route, Routes, useLocation, useNavigate } from 'react-router-dom';
import { api, isMock } from './api';
import { ErrorMessage, Field, PageHeader, Resource, useAction, useResource } from './ui';
import { ImportPage, ImportJob } from './imports';
import { Dashboard, Collection, Chat, Reminders } from './finance';
import { Contacts, Contact, Pipeline } from './crm';
import './style.css';

function returnPath(location) {
  const next = new URLSearchParams(location.search).get('retorno');
  return next === '/importacoes' ? next : '/';
}

function locationFor(path, next) {
  return path + '?retorno=' + encodeURIComponent(next);
}

function RouteFocus() {
  const { pathname } = useLocation();
  useEffect(() => {
    const main = document.getElementById('conteudo');
    if (main) main.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [pathname]);
  return null;
}

function Brand() {
  return <div className="brand"><span className="brand-mark" aria-hidden="true">CF</span><strong>CRM Financeiro</strong></div>;
}

function Access({ register, onSession }) {
  const navigate = useNavigate();
  const next = returnPath(useLocation());
  const { error, busy, run } = useAction();
  return <div className="access-shell">
    <aside className="access-aside"><Brand /><div>
      <p className="eyebrow">PROJETO DE EXTENSÃO</p>
      <p className="access-heading">Gestão financeira<br />para pequenos negócios.</p>
      <p className="access-intro">Acompanhe o caixa, importe planilhas e organize cobranças em um só lugar.</p>
    </div></aside>
    <main id="conteudo" tabIndex={-1} className="access-main"><div className="access-form">
      <PageHeader title={register ? 'Criar conta' : 'Entrar'} />
      {isMock && <p className="notice">Modo demonstração. Use apenas nomes, senhas e arquivos sintéticos.</p>}
      <ErrorMessage error={error} />
      <form onSubmit={(event) => {
        event.preventDefault();
        const data = Object.fromEntries(new FormData(event.currentTarget));
        run(async () => {
          const session = await (register ? api.register(data) : api.login(data));
          onSession(session);
          navigate(session.company ? next : locationFor('/empresa/cadastro', next), { replace: true });
        });
      }}>
        {register && <Field label="Nome"><input name="name" autoComplete="name" maxLength={120} required /></Field>}
        <Field label="E-mail"><input name="email" type="email" autoComplete="email" maxLength={254} required /></Field>
        <Field label="Senha" hint={register ? 'Mínimo de 8 caracteres.' : null}>
          <input name="password" type="password" autoComplete={register ? 'new-password' : 'current-password'}
            minLength={register ? 8 : undefined} maxLength={128} required />
        </Field>
        <button type="submit" disabled={busy}>{busy ? 'Aguarde…' : register ? 'Criar conta' : 'Entrar'}</button>
      </form>
      <p>{register ? 'Já tem conta?' : 'Primeiro acesso?'}{' '}
        <Link to={locationFor(register ? '/entrar' : '/cadastro', next)}>{register ? 'Entrar' : 'Criar conta'}</Link>
      </p>
    </div></main>
  </div>;
}

function Onboarding({ onSession }) {
  const navigate = useNavigate();
  const next = returnPath(useLocation());
  const { error, busy, run } = useAction();
  return <main id="conteudo" tabIndex={-1} className="onboarding">
    <Brand />
    <section className="panel">
      <PageHeader title="Cadastre sua empresa" description="Complete o perfil para abrir o painel." />
      <ErrorMessage error={error} />
      <form onSubmit={(event) => {
        event.preventDefault();
        const values = new FormData(event.currentTarget);
        const data = { name: values.get('name'), segment: values.get('segment') };
        if (isMock) data.sample = values.has('sample');
        run(async () => {
          onSession(await api.company(data));
          navigate(next, { replace: true });
        });
      }}>
        <Field label="Nome da empresa"><input name="name" maxLength={140} required /></Field>
        <Field label="Segmento (opcional)"><input name="segment" maxLength={120} /></Field>
        {isMock && <label className="check"><input type="checkbox" name="sample" defaultChecked /> Incluir cenário sintético</label>}
        <button type="submit" disabled={busy}>{busy ? 'Salvando…' : 'Salvar e continuar'}</button>
      </form>
    </section>
  </main>;
}

const navigation = [
  ['/', 'Visão geral'], ['/importacoes', 'Importações'], ['/chat', 'CEO IA'],
  ['/carteira', 'Carteira'], ['/negociacoes', 'Negociações'], ['/empresa', 'Empresa'],
];

function Layout({ session, onSession }) {
  const { error, busy, run } = useAction();
  const navigate = useNavigate();
  return <div className="app-shell">
    <a className="skip" href="#conteudo">Ir para o conteúdo</a>
    <aside className="sidebar">
      <Brand />
      <nav aria-label="Menu principal">{navigation.map(([path, label]) => <NavLink key={path} to={path} end={path === '/'}>{label}</NavLink>)}</nav>
      <div className="sidebar-account">
        <div><strong>{session.company.name}</strong><span>{session.user.name}</span></div>
        <button type="button" className="secondary" disabled={busy} onClick={() => run(async () => {
          await api.logout();
          onSession(null);
          navigate('/entrar', { replace: true });
        })}>Sair</button>
      </div>
    </aside>
    <main id="conteudo" tabIndex={-1}>
      {isMock && <div className="demo-bar">Modo demonstração · Use apenas dados sintéticos</div>}
      <div className="workspace"><ErrorMessage error={error} /><Outlet /></div>
    </main>
  </div>;
}

function AppRoutes({ initial }) {
  const [session, setSession] = useState(initial);
  const location = useLocation();
  const next = location.pathname.startsWith('/importacoes') ? '/importacoes' : returnPath(location);
  const root = session?.company ? '/' : locationFor('/empresa/cadastro', next);
  useEffect(() => {
    const expire = () => setSession(null);
    window.addEventListener('crm:expired', expire);
    return () => window.removeEventListener('crm:expired', expire);
  }, []);
  return <>
    <RouteFocus />
    <Routes>
      <Route path="/entrar" element={session ? <Navigate to={session.company ? next : root} replace />
        : <Access key="login" onSession={setSession} />} />
      <Route path="/cadastro" element={session ? <Navigate to={session.company ? next : root} replace />
        : <Access key="register" register onSession={setSession} />} />
      <Route path="/empresa/cadastro" element={!session ? <Navigate to={locationFor('/entrar', next)} replace />
        : session.company ? <Navigate to={next} replace /> : <Onboarding onSession={setSession} />} />
      <Route path="/" element={!session ? <Navigate to={locationFor('/entrar', next)} replace />
        : !session.company ? <Navigate to={root} replace /> : <Layout session={session} onSession={setSession} />}>
        <Route index element={<Dashboard />} />
        <Route path="importacoes" element={<ImportPage />} />
        <Route path="importacoes/:id" element={<ImportJob />} />
        <Route path="chat" element={<Chat />} />
        <Route path="empresa" element={<Reminders />} />
        <Route path="carteira" element={<Contacts />} />
        <Route path="carteira/:id" element={<Contact />} />
        <Route path="cobrancas/:id" element={<Collection />} />
        <Route path="negociacoes" element={<Pipeline />} />
        <Route path="*" element={<><PageHeader title="Página indisponível" /><Link to="/">Voltar ao painel</Link></>} />
      </Route>
    </Routes>
  </>;
}

async function loadSession(signal) {
  try {
    return await api.session(signal);
  } catch (error) {
    if (error.status === 401) return null;
    throw error;
  }
}

function App() {
  const initial = useResource(loadSession);
  if (initial.loading || initial.error) return <main className="workspace"><Resource resource={initial} /></main>;
  return <AppRoutes initial={initial.data} />;
}

createRoot(document.getElementById('root')).render(<StrictMode><BrowserRouter><App /></BrowserRouter></StrictMode>);
