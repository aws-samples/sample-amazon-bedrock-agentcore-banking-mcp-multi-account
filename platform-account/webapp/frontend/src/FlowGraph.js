import React, { useMemo } from 'react';
import { ReactFlow, Background, Controls, Position } from '@xyflow/react';
import '@xyflow/react/dist/style.css';

const LOB_COLORS = { 'retail-banking': '#2196f3', 'transaction-banking': '#4caf50', 'lending-wealth': '#ff5722' };

const nodeDefaults = { sourcePosition: Position.Right, targetPosition: Position.Left };

function buildFlowData(trace) {
  if (!trace) return { nodes: [], edges: [] };
  const toolCalls = trace.tool_calls || [];
  const timings = trace.timings || {};
  const grBlocked = trace.guardrail_blocked;

  const nodes = [];
  const edges = [];
  let x = 0;
  const xGap = 200;
  const yCenter = 150;

  // User node
  nodes.push({ id: 'user', position: { x, y: yCenter }, ...nodeDefaults, data: { label: '👤 User' }, style: { background: '#263238', color: '#fff', border: '2px solid #546e7a', borderRadius: 8, padding: 10, fontSize: 12 } });
  x += xGap;

  // Guardrail Input
  const grInMs = timings.guardrail_input_ms;
  nodes.push({ id: 'gr-in', position: { x, y: yCenter }, ...nodeDefaults, data: { label: `🛡️ Guardrail\n(input${grInMs ? ` ${grInMs}ms` : ''})` }, style: { background: grBlocked ? '#c62828' : '#1b5e20', color: '#fff', border: 'none', borderRadius: 8, padding: 10, fontSize: 11, whiteSpace: 'pre-line' } });
  edges.push({ id: 'e-user-gr', source: 'user', target: 'gr-in', animated: true, type: 'smoothstep' });
  x += xGap;

  if (grBlocked) {
    nodes.push({ id: 'blocked', position: { x, y: yCenter }, ...nodeDefaults, data: { label: `🚫 Blocked\n${trace.guardrail_reason || ''}` }, style: { background: '#c62828', color: '#fff', border: 'none', borderRadius: 8, padding: 10, fontSize: 11, whiteSpace: 'pre-line' } });
    edges.push({ id: 'e-gr-blocked', source: 'gr-in', target: 'blocked', type: 'smoothstep' });
    return { nodes, edges };
  }

  // Agent node
  const agentMs = timings.agent_ms;
  nodes.push({ id: 'agent', position: { x, y: yCenter }, ...nodeDefaults, data: { label: `🎯 Agent\n${agentMs ? `${(agentMs/1000).toFixed(1)}s` : ''}` }, style: { background: '#1a237e', color: '#fff', border: '2px solid #3f51b5', borderRadius: 8, padding: 10, fontSize: 11, whiteSpace: 'pre-line' } });
  edges.push({ id: 'e-gr-agent', source: 'gr-in', target: 'agent', animated: true, type: 'smoothstep' });
  x += xGap;

  // Gateway node
  nodes.push({ id: 'gateway', position: { x, y: yCenter }, ...nodeDefaults, data: { label: '🔀 Gateway\n(MCP + OAuth)' }, style: { background: '#4a148c', color: '#fff', border: 'none', borderRadius: 8, padding: 10, fontSize: 11, whiteSpace: 'pre-line' } });
  edges.push({ id: 'e-agent-gw', source: 'agent', target: 'gateway', animated: true, type: 'smoothstep', label: 'User JWT' });
  x += xGap;

  // Group tools by LOB
  const lobGroups = {};
  toolCalls.forEach(tc => {
    const lob = tc.lob || 'unknown';
    if (!lobGroups[lob]) lobGroups[lob] = [];
    lobGroups[lob].push(tc);
  });

  // LOB nodes
  const lobNames = Object.keys(lobGroups);
  const lobStartY = yCenter - ((lobNames.length - 1) * 80) / 2;

  lobNames.forEach((lob, i) => {
    const tools = lobGroups[lob];
    const toolNames = tools.map(t => {
      const name = t.tool.includes('___') ? t.tool.split('___')[1] : t.tool;
      return name;
    });
    const uniqueTools = [...new Set(toolNames)];
    const lobId = `lob-${lob}`;
    const color = LOB_COLORS[lob] || '#757575';
    nodes.push({
      id: lobId,
      position: { x, y: lobStartY + i * 80 },
      ...nodeDefaults,
      data: { label: `${lob}\n${uniqueTools.join(', ')}` },
      style: { background: color, color: '#fff', border: 'none', borderRadius: 8, padding: 10, fontSize: 10, whiteSpace: 'pre-line', minWidth: 160 },
    });
    edges.push({ id: `e-gw-${lob}`, source: 'gateway', target: lobId, animated: true, type: 'smoothstep', style: { stroke: color } });
  });

  // Guardrail Output + Response (after LOBs)
  const xOut = x + xGap;
  const grOutMs = timings.guardrail_output_ms;
  nodes.push({ id: 'gr-out', position: { x: xOut, y: yCenter }, ...nodeDefaults, data: { label: `🛡️ Guardrail\n(output${grOutMs ? ` ${grOutMs}ms` : ''})` }, style: { background: '#1b5e20', color: '#fff', border: 'none', borderRadius: 8, padding: 10, fontSize: 11, whiteSpace: 'pre-line' } });
  edges.push({ id: 'e-agent-grout', source: 'agent', target: 'gr-out', type: 'smoothstep', style: { strokeDasharray: '5,5' } });

  nodes.push({ id: 'response', position: { x: xOut + xGap, y: yCenter }, ...nodeDefaults, data: { label: '💬 Response' }, style: { background: '#263238', color: '#fff', border: '2px solid #546e7a', borderRadius: 8, padding: 10, fontSize: 12 } });
  edges.push({ id: 'e-grout-resp', source: 'gr-out', target: 'response', type: 'smoothstep' });

  return { nodes, edges };
}

export default function FlowGraph({ trace, onClose }) {
  const { nodes, edges } = useMemo(() => buildFlowData(trace), [trace]);

  return (
    <div className="flow-modal-overlay" onClick={onClose}>
      <div className="flow-modal" onClick={e => e.stopPropagation()}>
        <div className="flow-modal-header">
          <h3>🔀 Request Flow</h3>
          <button onClick={onClose}>✕</button>
        </div>
        <div style={{ width: '100%', height: 350 }}>
          <ReactFlow nodes={nodes} edges={edges} fitView panOnDrag zoomOnScroll={false} nodesDraggable={false}>
            <Background color="#333" gap={20} />
            <Controls showInteractive={false} />
          </ReactFlow>
        </div>
      </div>
    </div>
  );
}
