import React, { useState, useRef, useEffect, useCallback } from 'react';
import { signIn, getCurrentSession, signOut } from './auth';
import FlowGraph from './FlowGraph';
import './App.css';

const API = process.env.REACT_APP_API_URL || '/api';

const LOB_COLORS = { 'retail-banking': '#2196f3', 'transaction-banking': '#4caf50', 'lending-wealth': '#ff5722' };
const LOB_ICONS = { 'retail-banking': '🏦', 'transaction-banking': '💳', 'lending-wealth': '🏠' };
const LOB_LABELS = { 'retail-banking': 'Retail Banking', 'transaction-banking': 'Transaction Banking', 'lending-wealth': 'Lending & Wealth' };

function fmtMs(ms) {
  if (ms === null || ms === undefined) return '—';
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
}

/* ─── Login ─── */
function LoginScreen() {
  useEffect(() => { signIn(); }, []);
  return (
    <div className="login-screen">
      <div className="login-box">
        <h2>🏦 Multi-Account Banking Agent</h2>
        <p>Redirecting to Okta login...</p>
      </div>
    </div>
  );
}

/* ─── Trace Panel ─── */
function TracePanel({ trace }) {
  if (!trace) return (
    <div className="trace-panel">
      <h3>Agent Trace</h3>
      <div className="trace-empty">
        Send a message to see the agent trace. Click 📊 on any past response to view its trace.
        <div className="trace-legend" style={{marginTop:16}}>
          {Object.entries(LOB_LABELS).map(([k, v]) => (
            <div key={k}><span className="dot" style={{ background: LOB_COLORS[k] }} /> {v}</div>
          ))}
        </div>
      </div>
    </div>
  );

  const toolCalls = trace.tool_calls || [];
  const timings = trace.timings || {};
  const e2e = timings.end_to_end_ms || trace.end_to_end_ms;
  const agentMs = timings.agent_ms;
  const criticalPath = timings.critical_path_ms;
  const overhead = timings.overhead_ms;
  const toolsTotal = timings.tools_total_ms;
  const grInputMs = timings.guardrail_input_ms;
  const grOutputMs = timings.guardrail_output_ms;
  const discoveredLobs = trace.discovered_lobs || [];

  // Group tools by LOB
  const lobGroups = {};
  toolCalls.forEach(tc => {
    const lob = tc.lob || 'unknown';
    if (!lobGroups[lob]) lobGroups[lob] = [];
    lobGroups[lob].push(tc);
  });

  return (
    <div className="trace-panel">
      <h3>Agent Trace</h3>

      {/* Timing grid */}
      <div className="trace-item timings">
        <div className="label">⏱ Timing</div>
        <div className="timing-grid">
          <span>End-to-end</span><span>{fmtMs(e2e)}</span>
          <span>Agent (LLM + tools)</span><span>{fmtMs(agentMs)}</span>
          <span>Critical path</span><span>{fmtMs(criticalPath)}</span>
          <span>Orchestrator overhead</span><span>{fmtMs(overhead)}</span>
          <span>Tool work (cumulative)</span><span>{fmtMs(toolsTotal)}</span>
          {grInputMs > 0 && <><span>Guardrail (input)</span><span>{fmtMs(grInputMs)}</span></>}
          {grOutputMs > 0 && <><span>Guardrail (output)</span><span>{fmtMs(grOutputMs)}</span></>}
        </div>
      </div>

      {/* Auth */}
      <div className="trace-item">
        <div className="label">🔐 Okta JWT Auth</div>
        <div className="detail">Verified ✅</div>
      </div>

      {/* Registry discovery */}
      {discoveredLobs.length > 0 && (
        <div className="trace-item">
          <div className="label">🔍 Registry Discovery</div>
          <div className="detail">{discoveredLobs.length} LOBs discovered at startup</div>
        </div>
      )}

      {/* Agent */}
      <div className="trace-item">
        <div className="label">🎯 Banking Agent (AgentCore Runtime) <span className="duration-badge">{fmtMs(agentMs)}</span></div>
        <div className="detail">Claude Sonnet 4.5 • MCP Protocol</div>
        <div className="detail">LOBs accessed: {Object.keys(lobGroups).length} • Tools called: {toolCalls.length}</div>
      </div>

      {/* Tool calls by LOB */}
      {Object.entries(lobGroups).map(([lob, tools]) => (
        <div key={lob} className="trace-lob-group">
          <div className={`trace-lob-header ${lob}`}>
            <span className="tag-mcp">MCP</span>
            {LOB_ICONS[lob] || '🔗'} {LOB_LABELS[lob] || lob}
            <span className="duration-badge">{tools.length} tool{tools.length > 1 ? 's' : ''}</span>
          </div>
          <div className="trace-lob-tools">
            {tools.map((tc, i) => {
              const toolName = tc.tool.includes('___') ? tc.tool.split('___')[1] : tc.tool;
              const cedarDenied = tc.cedar_denied;
              return (
                <div key={i} className="trace-tool-item">
                  <span className="trace-tool-name">{toolName}</span>
                  {tc.duration_ms != null && <span className="duration-badge">{fmtMs(tc.duration_ms)}</span>}
                  {cedarDenied
                    ? <span className="cedar-badge denied">🚫 Cedar DENIED</span>
                    : <span className="trace-tool-status">✅</span>
                  }
                </div>
              );
            })}
          </div>
        </div>
      ))}

      {toolCalls.length === 0 && !trace.guardrail_blocked && (
        <div className="trace-item">
          <div className="label">🧠 Agent Reasoning</div>
          <div className="detail">No LOB tools invoked</div>
        </div>
      )}

      {/* Auth chain */}
      {toolCalls.length > 0 && (
        <div className="trace-item">
          <div className="label">🔑 Cross-Account Auth</div>
          <div className="detail">Agent → Okta M2M → Gateway → LOB MCP ✅</div>
        </div>
      )}

      {/* Governance Summary — Guardrail + Cedar */}
      <div className="trace-item">
        <div className="label">🛡️ Bedrock Guardrail</div>
        {trace.guardrail_blocked ? (
          <span className="guardrail-badge blocked">{trace.guardrail_reason}</span>
        ) : (
          <span className="guardrail-badge clear">Passed ✅</span>
        )}
      </div>

      <div className="trace-item">
        <div className="label">🔒 Cedar Policy (Gateway)</div>
        {toolCalls.some(tc => tc.cedar_denied) ? (
          <span className="guardrail-badge blocked">DENIED — {toolCalls.filter(tc => tc.cedar_denied).map(tc => tc.tool.includes('___') ? tc.tool.split('___')[1] : tc.tool).join(', ')}</span>
        ) : toolCalls.length > 0 ? (
          <span className="guardrail-badge clear">ENFORCE — All tools authorized ✅</span>
        ) : trace.response && /cannot|not authorized|not permitted|blocked|denied|delete.*not.*allowed/i.test(trace.response) ? (
          <span className="guardrail-badge blocked">ENFORCE — Destructive action blocked 🚫</span>
        ) : (
          <span className="guardrail-badge clear">ENFORCE ✅</span>
        )}
      </div>
    </div>
  );
}

/* ─── Main App ─── */
export default function App() {
  const [auth, setAuth] = useState(null);
  const [authLoading, setAuthLoading] = useState(true);
  const [scenarios, setScenarios] = useState([]);
  const [customers, setCustomers] = useState([]);
  const [customerId, setCustomerId] = useState('C001');
  const [messages, setMessages] = useState([]);
  const [input, setInput] = useState('');
  const [loading, setLoading] = useState(false);
  const [elapsed, setElapsed] = useState(0);
  const [trace, setTrace] = useState(null);
  const [flowTrace, setFlowTrace] = useState(null);
  const [activeScenario, setActiveScenario] = useState(null);
  const messagesEnd = useRef(null);

  // Check existing session (backend handles Okta callback at /api/callback)
  useEffect(() => {
    (async () => {
      const session = await getCurrentSession();
      if (session) setAuth(session);
      setAuthLoading(false);
    })();
  }, []);

  const getHeaders = useCallback(async () => {
    const session = await getCurrentSession();
    if (!session) { setAuth(null); return null; }  // session gone → LoginScreen re-inits signIn()
    if (session.token !== auth?.token) setAuth(session);
    return { 'Content-Type': 'application/json' };
  }, [auth]);

  useEffect(() => {
    if (!auth) return;
    fetch(`${API}/scenarios`, { credentials: 'include' }).then(r => r.json()).then(setScenarios).catch(() => {});
    fetch(`${API}/customers`, { credentials: 'include' }).then(r => r.json()).then(setCustomers).catch(() => {});
  }, [auth]);

  useEffect(() => { messagesEnd.current?.scrollIntoView({ behavior: 'smooth' }); }, [messages]);

  useEffect(() => {
    if (!loading) { setElapsed(0); return; }
    const t = setInterval(() => setElapsed(e => e + 1), 1000);
    return () => clearInterval(t);
  }, [loading]);

  // Logout: let signOut() drive the single navigation to Okta /v1/logout so SSO is
  // cleared. Do NOT setAuth(null) here — it mounts <LoginScreen/>, whose useEffect
  // fires signIn() and wins the race, re-authenticating via still-valid Okta SSO
  // and bouncing the user straight back to the main screen.
  const handleLogout = () => { signOut(); };

  const sendMessage = async (prompt, sendCustomerId) => {
    if (!prompt.trim() || loading) return;
    setInput('');
    setMessages(prev => [...prev, { role: 'user', content: prompt }]);
    setLoading(true);
    setTrace(null);
    try {
      const h = await getHeaders();
      if (!h) return;
      const cid = sendCustomerId !== undefined ? sendCustomerId : customerId;
      const res = await fetch(`${API}/chat`, {
        method: 'POST', headers: h, credentials: 'include',
        body: JSON.stringify({ prompt, ...(cid ? { customer_id: cid } : {}) }),
      });
      if (res.status === 401) { setAuth(null); return; }  // expired → LoginScreen re-inits signIn()
      if (!res.ok) throw new Error('Request failed');
      const data = await res.json();
      setMessages(prev => [...prev, { role: 'assistant', content: data.response, trace: data }]);
      setTrace(data);
    } catch (err) {
      setMessages(prev => [...prev, { role: 'assistant', content: `Error: ${err.message}` }]);
    } finally {
      setLoading(false);
    }
  };

  if (authLoading) return <div className="login-screen"><div className="login-box"><h2>🏦 Multi-Account Banking Agent</h2><p>Loading...</p></div></div>;
  if (!auth) return <LoginScreen />;

  return (
    <div className="app-layout">
      <div className="header">
        <div className="header-left">
          <h1>🏦 Multi-Account Banking Agent</h1>
          <span className="tag">1 Agent · 3 LOBs · 4 AWS Accounts · 15 Tools</span>
        </div>
        <div className="header-right">
          <span className="user-badge">{auth.name || auth.email}</span>
          <button onClick={handleLogout}>Logout</button>
        </div>
      </div>

      <div className="main-content">
        <div className="sidebar">
          <div className="section">
            <h3>Demo Scenarios</h3>
            {scenarios.map(s => (
              <button key={s.id} className={`scenario-btn${activeScenario === s.id ? ' active' : ''}`} onClick={() => {
                setActiveScenario(s.id);
                const cust = customers.find(c => c.id === customerId) || { id: customerId, name: customerId };
                const prompt = (s.prompt_template || s.prompt || '')
                  .replace(/\{cid\}/g, cust.id)
                  .replace(/\{name\}/g, cust.name);
                sendMessage(prompt, customerId);
              }}>
                {s.label}
                <span className="desc">{s.description}</span>
              </button>
            ))}
          </div>
          <div className="section">
            <h3>Customer</h3>
            <select className="customer-select" value={customerId} onChange={e => setCustomerId(e.target.value)}>
              {customers.map(c => (
                <option key={c.id} value={c.id}>{c.id} — {c.name} ({c.segment})</option>
              ))}
            </select>
          </div>
        </div>

        <div className="chat-area">
          <div className="messages">
            {messages.length === 0 && (
              <div style={{ color: '#546e7a', textAlign: 'center', marginTop: 60, fontSize: 14 }}>
                Select a demo scenario or type a question about a customer.
              </div>
            )}
            {messages.map((m, i) => (
              <div key={i} className={`msg ${m.role}`}>
                <div className="role">{m.role}</div>
                <div className="bubble">{m.content}</div>
                {m.role === 'assistant' && m.trace && (
                  <div className="trace-buttons">
                    <button className={`trace-footer${trace === m.trace ? ' active' : ''}`} onClick={() => setTrace(m.trace)}>
                      📊 Trace
                      {m.trace.tool_calls?.length ? ` · ${m.trace.tool_calls.length} tool${m.trace.tool_calls.length > 1 ? 's' : ''}` : ''}
                      {m.trace.end_to_end_ms ? ` · ${(m.trace.end_to_end_ms / 1000).toFixed(1)}s` : ''}
                    </button>
                    <button className="trace-footer flow-btn" onClick={() => setFlowTrace(m.trace)}>
                      🔀 Flow
                    </button>
                  </div>
                )}
              </div>
            ))}
            {loading && <div className="typing-indicator">⏳ Working... {elapsed}s — {elapsed < 10 ? 'Agent is processing your request' : elapsed < 40 ? 'Querying LOB tools across accounts' : elapsed < 90 ? 'Still working — multi-LOB queries take 60-120s' : 'Almost done — synthesizing results'}</div>}
            <div ref={messagesEnd} />
          </div>
          <div className="chat-input">
            <input
              placeholder={`Ask about customer ${customerId}...`}
              value={input}
              onChange={e => setInput(e.target.value)}
              onKeyDown={e => e.key === 'Enter' && sendMessage(input)}
              disabled={loading}
            />
            <button onClick={() => sendMessage(input)} disabled={loading || !input.trim()}>Send</button>
          </div>
        </div>

        <TracePanel trace={trace} />
      </div>
      {flowTrace && <FlowGraph trace={flowTrace} onClose={() => setFlowTrace(null)} />}
    </div>
  );
}
