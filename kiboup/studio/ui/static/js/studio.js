/* KiboStudio - Alpine.js application logic */
document.addEventListener('alpine:init', () => {

    Alpine.store('studio', {
        currentPage: window.location.pathname.replace(/\/$/, '') || '/',
        loading: false,

        isActive(path) {
            if (path === '/') return this.currentPage === '/';
            return this.currentPage.startsWith(path);
        }
    });

    /* ===== Main ADK Studio component ===== */
    Alpine.data('studioApp', () => ({
        /* State */
        agents: [],
        selectedAgent: '',
        leftTab: 'traces',
        detailTab: 'event',

        /* Sessions */
        sessions: [],
        currentSession: null,
        messages: [],
        chatInput: '',
        sending: false,

        /* Traces */
        traces: [],
        groupedTraces: [],
        selectedTrace: null,
        traceInput: null,
        traceOutput: null,
        spans: [],
        selectedSpan: null,

        /* Eval */
        evalSets: [],
        selectedEvalSet: null,
        evalCases: [],
        showCreateEvalSet: false,
        newEvalSetName: '',
        showAddToEvalSet: false,
        addToEvalSetId: '',

        async init() {
            await this.loadAgents();
            await this.loadTraces();
            document.addEventListener('graph-select', (e) => {
                const sp = this.spans.find(s => s.span_id === e.detail);
                if (sp) this.selectSpan(sp);
            });
        },

        /* -- Agents -- */
        async loadAgents() {
            try {
                const r = await fetch('/api/discovery/agents');
                const d = await r.json();
                this.agents = d.agents || [];
                if (this.agents.length > 0 && !this.selectedAgent) {
                    this.selectedAgent = this.agents[0].agent_id;
                    await this.loadSessions();
                }
            } catch { }
        },

        async onAgentChange() {
            this.currentSession = null;
            this.messages = [];
            await this.loadSessions();
            await this.loadTraces();
        },

        /* -- Sessions -- */
        async loadSessions() {
            try {
                const url = this.selectedAgent
                    ? `/api/sessions?agent_id=${this.selectedAgent}`
                    : '/api/sessions';
                const r = await fetch(url);
                const d = await r.json();
                this.sessions = d.sessions || [];
            } catch { this.sessions = []; }
        },

        async newSession() {
            if (!this.selectedAgent) return;
            try {
                const r = await fetch('/api/sessions', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ agent_id: this.selectedAgent })
                });
                const session = await r.json();
                this.currentSession = session;
                this.messages = [];
                await this.loadSessions();
            } catch { }
        },

        async selectSession(s) {
            this.currentSession = s;
            this.selectedAgent = s.agent_id || this.selectedAgent;
            await this.loadMessages();
        },

        async loadMessages() {
            if (!this.currentSession) return;
            try {
                const r = await fetch(`/api/sessions/${this.currentSession.session_id}/messages`);
                const d = await r.json();
                this.messages = (d.messages || []).map(m => ({
                    role: m.role,
                    content: m.content,
                    ts: this.formatTime(m.created_at),
                    trace_id: m.trace_id
                }));
                this.scrollToBottom();
            } catch { this.messages = []; }
        },

        /* -- Chat -- */
        async sendMessage() {
            const text = this.chatInput.trim();
            if (!text || !this.selectedAgent || this.sending) return;

            if (!this.currentSession) {
                await this.newSession();
            }

            this.messages.push({ role: 'user', content: text, ts: new Date().toLocaleTimeString() });
            this.chatInput = '';
            this.sending = true;
            this.scrollToBottom();

            try {
                const r = await fetch(`/api/sessions/${this.currentSession.session_id}/messages`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ content: text })
                });
                const d = await r.json();

                if (d.error) {
                    this.messages.push({ role: 'error', content: d.error, ts: new Date().toLocaleTimeString() });
                } else {
                    const msg = d.message || {};
                    this.messages.push({
                        role: 'assistant',
                        content: msg.content || d.response || JSON.stringify(d),
                        agent: this.selectedAgent,
                        ts: new Date().toLocaleTimeString(),
                        trace_id: msg.trace_id || d.trace_id
                    });
                    /* Refresh traces after getting response */
                    await this.loadTraces();
                }
            } catch (e) {
                this.messages.push({ role: 'error', content: 'Failed: ' + e.message, ts: new Date().toLocaleTimeString() });
            }
            this.sending = false;
            this.scrollToBottom();
        },

        scrollToBottom() {
            this.$nextTick(() => {
                const el = document.getElementById('chat-messages');
                if (el) el.scrollTop = el.scrollHeight;
            });
        },

        /* -- Traces -- */
        async loadTraces() {
            try {
                const r = await fetch('/api/traces?limit=50');
                const d = await r.json();
                this.traces = d.traces || [];
                this._buildGroupedTraces();
            } catch { this.traces = []; this.groupedTraces = []; }
        },

        _buildGroupedTraces() {
            const groups = [];
            let current = null;
            for (const t of this.traces) {
                const aid = t.agent_id || 'unknown';
                if (current && current.agent_id === aid) {
                    current.traces.push(t);
                    current.count++;
                    current.totalDuration += (t.duration_ms || 0);
                } else {
                    current = { agent_id: aid, traces: [t], count: 1, expanded: false, totalDuration: t.duration_ms || 0, latest: t };
                    groups.push(current);
                }
            }
            this.groupedTraces = groups;
        },

        toggleTraceGroup(group) {
            group.expanded = !group.expanded;
        },

        async selectTrace(t) {
            this.selectedTrace = t;
            this.selectedSpan = null;
            this.traceInput = null;
            this.traceOutput = null;
            this.detailTab = 'event';
            try {
                const r = await fetch(`/api/traces/${t.trace_id}`);
                const d = await r.json();
                this.spans = d.spans || [];
                const root = this.spans.find(s => s.kind === 'invocation') || this.spans[0];
                if (root) {
                    this.traceInput = root.input_data || null;
                    this.traceOutput = root.output_data || null;
                }
            } catch { this.spans = []; }
        },

        selectSpan(sp) {
            this.selectedSpan = this.selectedSpan?.span_id === sp.span_id ? null : sp;
            this.detailTab = 'event';
        },

        getIndent(span) {
            if (!span.parent_span_id) return 0;
            let depth = 0;
            let parentId = span.parent_span_id;
            while (parentId && depth < 10) {
                const parent = this.spans.find(s => s.span_id === parentId);
                if (!parent) break;
                parentId = parent.parent_span_id;
                depth++;
            }
            return depth;
        },

        /* -- Eval Sets -- */
        async loadEvalSets() {
            try {
                const r = await fetch('/api/eval/sets');
                const d = await r.json();
                this.evalSets = d.eval_sets || [];
            } catch { this.evalSets = []; }
        },

        async createEvalSet() {
            if (!this.newEvalSetName.trim()) return;
            await fetch('/api/eval/sets', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: this.newEvalSetName, agent_id: this.selectedAgent || null })
            });
            this.showCreateEvalSet = false;
            this.newEvalSetName = '';
            await this.loadEvalSets();
        },

        async selectEvalSet(es) {
            this.selectedEvalSet = es;
            try {
                const r = await fetch(`/api/eval/sets/${es.eval_set_id}/cases`);
                const d = await r.json();
                this.evalCases = d.cases || [];
            } catch { this.evalCases = []; }
        },

        async addSessionToEvalSet() {
            if (!this.addToEvalSetId || !this.currentSession) return;
            await fetch(`/api/eval/sets/${this.addToEvalSetId}/cases`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ session_id: this.currentSession.session_id })
            });
            this.showAddToEvalSet = false;
            this.addToEvalSetId = '';
            if (this.selectedEvalSet?.eval_set_id === this.addToEvalSetId) {
                await this.selectEvalSet(this.selectedEvalSet);
            }
        },

        async runEvalSet() {
            if (!this.selectedEvalSet) return;
            await fetch(`/api/eval/sets/${this.selectedEvalSet.eval_set_id}/run`, { method: 'POST' });
            await this.selectEvalSet(this.selectedEvalSet);
        },

        /* -- Graph (ADK-style) -- */
        buildGraph() {
            if (!this.spans || this.spans.length === 0) {
                return '<div class="empty-state" style="padding:20px;"><p>No spans</p></div>';
            }

            const darkGreen = '#0F5223';
            const lightGreen = '#69CB87';
            const lightGray = '#cccccc';
            const bgColor = '#333537';

            /* Deduplicate: if multiple spans share the same name+kind,
               keep only unique nodes for the graph (agent -> tools pattern). */
            const childrenMap = {};
            const spanMap = {};
            const roots = [];
            for (const sp of this.spans) {
                spanMap[sp.span_id] = sp;
                if (!sp.parent_span_id) {
                    roots.push(sp);
                } else {
                    if (!childrenMap[sp.parent_span_id]) childrenMap[sp.parent_span_id] = [];
                    childrenMap[sp.parent_span_id].push(sp);
                }
            }

            /* Collect graph nodes: collapse the span tree into
               agent nodes (invocation/agent_run) and leaf nodes (tool/llm/retrieval). */
            const graphNodes = [];
            const graphEdges = [];
            const seen = new Set();

            function getNodeType(sp) {
                if (sp.kind === 'invocation' || sp.kind === 'agent_run') return 'agent';
                if (sp.kind === 'tool_call') return 'tool';
                if (sp.kind === 'llm_call') return 'llm';
                if (sp.kind === 'retrieval') return 'retrieval';
                return 'custom';
            }

            function getEmoji(type) {
                if (type === 'agent') return '\uD83E\uDD16';
                if (type === 'tool') return '\uD83D\uDD27';
                if (type === 'llm') return '\uD83E\uDDE0';
                if (type === 'retrieval') return '\uD83D\uDD0E';
                return '\u2753';
            }

            function walk(sp, parentNodeId) {
                const nodeType = getNodeType(sp);
                const label = sp.name || sp.kind;
                const nodeId = sp.span_id;

                /* Agent nodes always get added; leaf nodes deduplicate by name */
                if (nodeType === 'agent') {
                    if (!seen.has(nodeId)) {
                        seen.add(nodeId);
                        graphNodes.push({ id: nodeId, label, type: nodeType, spanId: sp.span_id });
                    }
                    if (parentNodeId) {
                        graphEdges.push({ from: parentNodeId, to: nodeId });
                    }
                    const children = childrenMap[sp.span_id] || [];
                    for (const child of children) {
                        walk(child, nodeId);
                    }
                } else {
                    /* Leaf node: deduplicate by parent+name */
                    const dedup = parentNodeId + '::' + label;
                    if (!seen.has(dedup)) {
                        seen.add(dedup);
                        graphNodes.push({ id: nodeId, label, type: nodeType, spanId: sp.span_id });
                        if (parentNodeId) {
                            graphEdges.push({ from: parentNodeId, to: nodeId });
                        }
                    }
                }
            }

            for (const root of roots) {
                walk(root, null);
            }

            if (graphNodes.length === 0) {
                return '<div class="empty-state" style="padding:20px;"><p>No graph data</p></div>';
            }

            /* Layout: left-to-right. Agents on the left, children to the right. */
            const nodeW = 160;
            const nodeH = 36;
            const gapX = 60;
            const gapY = 20;
            const padX = 30;
            const padY = 24;

            /* Build adjacency for layout */
            const adjMap = {};
            for (const e of graphEdges) {
                if (!adjMap[e.from]) adjMap[e.from] = [];
                adjMap[e.from].push(e.to);
            }

            const layoutRoots = graphNodes.filter(n =>
                !graphEdges.some(e => e.to === n.id)
            );

            const positions = {};
            let yCounter = 0;

            function layoutNode(nodeId, depth) {
                const children = adjMap[nodeId] || [];
                if (children.length === 0) {
                    positions[nodeId] = { x: depth, y: yCounter };
                    yCounter++;
                } else {
                    const startY = yCounter;
                    for (const childId of children) {
                        layoutNode(childId, depth + 1);
                    }
                    const endY = yCounter - 1;
                    positions[nodeId] = { x: depth, y: (startY + endY) / 2 };
                }
            }

            for (const r of layoutRoots) {
                layoutNode(r.id, 0);
            }
            /* Nodes without position (orphans) */
            for (const n of graphNodes) {
                if (!positions[n.id]) {
                    positions[n.id] = { x: 0, y: yCounter };
                    yCounter++;
                }
            }

            const maxX = Math.max(...Object.values(positions).map(p => p.x));
            const svgW = (maxX + 1) * (nodeW + gapX) + padX * 2;
            const svgH = yCounter * (nodeH + gapY) + padY * 2;

            let svg = `<svg width="${svgW}" height="${svgH}" xmlns="http://www.w3.org/2000/svg" style="background:${bgColor}; border-radius: 8px;">`;
            svg += `<defs><marker id="arrow-gray" markerWidth="8" markerHeight="6" refX="8" refY="3" orient="auto"><polygon points="0 0, 8 3, 0 6" fill="${lightGray}"/></marker></defs>`;

            /* Edges */
            for (const e of graphEdges) {
                const from = positions[e.from];
                const to = positions[e.to];
                if (!from || !to) continue;
                const fromNode = graphNodes.find(n => n.id === e.from);
                const isAgentEdge = fromNode && fromNode.type === 'agent';
                const x1 = from.x * (nodeW + gapX) + nodeW + padX;
                const y1 = from.y * (nodeH + gapY) + nodeH / 2 + padY;
                const x2 = to.x * (nodeW + gapX) + padX;
                const y2 = to.y * (nodeH + gapY) + nodeH / 2 + padY;
                const edgeColor = lightGray;
                const mx = (x1 + x2) / 2;
                svg += `<path d="M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}" stroke="${edgeColor}" stroke-width="1.5" fill="none" marker-end="url(#arrow-gray)"/>`;
            }

            /* Nodes */
            for (const n of graphNodes) {
                const pos = positions[n.id];
                if (!pos) continue;
                const x = pos.x * (nodeW + gapX) + padX;
                const y = pos.y * (nodeH + gapY) + padY;
                const isSelected = this.selectedSpan?.span_id === n.spanId;
                const emoji = getEmoji(n.type);
                const displayLabel = n.label.length > 18 ? n.label.substring(0, 16) + '..' : n.label;

                svg += `<g class="graph-node" style="cursor:pointer" onclick="document.dispatchEvent(new CustomEvent('graph-select', {detail:'${n.spanId}'}))">`;

                if (n.type === 'agent') {
                    /* Agent: filled green ellipse (ADK style) */
                    const cx = x + nodeW / 2;
                    const cy = y + nodeH / 2;
                    const rx = nodeW / 2;
                    const ry = nodeH / 2;
                    svg += `<ellipse cx="${cx}" cy="${cy}" rx="${rx}" ry="${ry}" fill="${isSelected ? lightGreen : darkGreen}" stroke="${isSelected ? lightGreen : darkGreen}" stroke-width="2"/>`;
                    svg += `<text x="${cx}" y="${cy + 5}" text-anchor="middle" font-size="12" fill="${lightGray}" font-weight="600" font-family="system-ui, sans-serif">${emoji} ${displayLabel}</text>`;
                } else {
                    /* Tool/LLM/Retrieval: rounded rect with gray border (ADK style) */
                    const fillColor = isSelected ? '#444' : bgColor;
                    const strokeColor = isSelected ? lightGreen : lightGray;
                    svg += `<rect x="${x}" y="${y}" width="${nodeW}" height="${nodeH}" rx="8" ry="8" fill="${fillColor}" stroke="${strokeColor}" stroke-width="1.5"/>`;
                    svg += `<text x="${x + nodeW / 2}" y="${y + nodeH / 2 + 5}" text-anchor="middle" font-size="12" fill="${lightGray}" font-family="system-ui, sans-serif">${emoji} ${displayLabel}</text>`;
                }

                svg += '</g>';
            }

            svg += '</svg>';
            return svg;
        },

        /* -- Formatters -- */
        formatDuration(ms) {
            if (!ms) return '-';
            if (ms < 1) return '<1ms';
            if (ms < 1000) return Math.round(ms) + 'ms';
            return (ms / 1000).toFixed(2) + 's';
        },

        formatTime(ts) {
            if (!ts) return '-';
            try {
                const d = new Date(ts);
                return d.toLocaleTimeString();
            } catch { return ts; }
        },

        formatJson(obj) {
            if (obj === undefined || obj === null) return 'null';
            try { return JSON.stringify(obj, null, 2); }
            catch { return String(obj); }
        },

        renderMarkdown(text) {
            if (!text) return '';
            if (typeof marked !== 'undefined') {
                try { return marked.parse(text); }
                catch { return text.replace(/</g, '&lt;').replace(/>/g, '&gt;'); }
            }
            return text.replace(/</g, '&lt;').replace(/>/g, '&gt;');
        },

        getTokenInfo(span) {
            if (!span || !span.attributes) return null;
            const a = span.attributes;
            if (a['llm.total_tokens'] || a['llm.input_tokens'] || a['llm.output_tokens'] || a['llm.model']) {
                return {
                    model: a['llm.model'] || '-',
                    input: a['llm.input_tokens'] || 0,
                    output: a['llm.output_tokens'] || 0,
                    total: a['llm.total_tokens'] || 0
                };
            }
            return null;
        }
    }));

    Alpine.data('tracesPage', () => ({
        traces: [],
        loading: true,

        async init() {
            await this.loadTraces();
        },

        async loadTraces() {
            this.loading = true;
            try {
                const resp = await fetch('/api/traces?limit=100');
                const data = await resp.json();
                this.traces = data.traces || [];
            } catch (e) {
                this.traces = [];
            }
            this.loading = false;
        },

        async deleteTrace(traceId) {
            if (!confirm('Delete this trace?')) return;
            await fetch(`/api/traces/${traceId}`, { method: 'DELETE' });
            await this.loadTraces();
        },

        formatDuration(ms) {
            if (!ms) return '-';
            if (ms < 1) return '<1ms';
            if (ms < 1000) return Math.round(ms) + 'ms';
            return (ms / 1000).toFixed(2) + 's';
        },

        formatTime(ts) {
            if (!ts) return '-';
            try {
                const d = new Date(ts);
                return d.toLocaleTimeString() + ' ' + d.toLocaleDateString();
            } catch { return ts; }
        }
    }));

    Alpine.data('traceDetailPage', () => ({
        trace: null,
        spans: [],
        selectedSpan: null,
        loading: true,

        async init() {
            const traceId = this.$el.dataset.traceId;
            if (!traceId) return;
            this.loading = true;
            try {
                const resp = await fetch(`/api/traces/${traceId}`);
                const data = await resp.json();
                this.trace = data.trace;
                this.spans = data.spans || [];
            } catch (e) {
                this.trace = null;
            }
            this.loading = false;
        },

        selectSpan(span) {
            this.selectedSpan = this.selectedSpan?.span_id === span.span_id ? null : span;
        },

        getIndent(span) {
            if (!span.parent_span_id) return 0;
            let depth = 0;
            let parentId = span.parent_span_id;
            while (parentId && depth < 10) {
                const parent = this.spans.find(s => s.span_id === parentId);
                if (!parent) break;
                parentId = parent.parent_span_id;
                depth++;
            }
            return depth;
        },

        formatDuration(ms) {
            if (!ms) return '-';
            if (ms < 1) return '<1ms';
            if (ms < 1000) return Math.round(ms) + 'ms';
            return (ms / 1000).toFixed(2) + 's';
        },

        formatJson(obj) {
            if (!obj) return 'null';
            try { return JSON.stringify(obj, null, 2); }
            catch { return String(obj); }
        }
    }));

    Alpine.data('promptsPage', () => ({
        prompts: [],
        loading: true,
        showCreate: false,
        showVersions: null,
        versions: [],
        newPrompt: { name: '', description: '', content: '', tags: '' },
        newVersion: { content: '', activate: true },

        async init() {
            await this.loadPrompts();
        },

        async loadPrompts() {
            this.loading = true;
            try {
                const resp = await fetch('/api/prompts');
                const data = await resp.json();
                this.prompts = data.prompts || [];
            } catch { this.prompts = []; }
            this.loading = false;
        },

        async createPrompt() {
            const tags = this.newPrompt.tags ? this.newPrompt.tags.split(',').map(t => t.trim()) : [];
            await fetch('/api/prompts', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ ...this.newPrompt, tags })
            });
            this.showCreate = false;
            this.newPrompt = { name: '', description: '', content: '', tags: '' };
            await this.loadPrompts();
        },

        async viewVersions(promptId) {
            this.showVersions = promptId;
            const resp = await fetch(`/api/prompts/${promptId}/versions`);
            const data = await resp.json();
            this.versions = data.versions || [];
        },

        async createVersion() {
            await fetch(`/api/prompts/${this.showVersions}/versions`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify(this.newVersion)
            });
            this.newVersion = { content: '', activate: true };
            await this.viewVersions(this.showVersions);
            await this.loadPrompts();
        },

        async activateVersion(promptId, version) {
            await fetch(`/api/prompts/${promptId}/versions/${version}/activate`, { method: 'PUT' });
            await this.viewVersions(promptId);
            await this.loadPrompts();
        },

        async deletePrompt(promptId) {
            if (!confirm('Delete this prompt?')) return;
            await fetch(`/api/prompts/${promptId}`, { method: 'DELETE' });
            await this.loadPrompts();
        }
    }));

    Alpine.data('evalPage', () => ({
        results: [],
        traces: [],
        loading: true,
        selectedTrace: '',
        running: false,
        filterByTrace: true,

        async init() {
            await Promise.all([this.loadResults(), this.loadTraces()]);
        },

        async loadResults() {
            this.loading = true;
            try {
                let url = '/api/eval/results?limit=50';
                if (this.filterByTrace && this.selectedTrace) {
                    url += '&trace_id=' + this.selectedTrace;
                }
                const resp = await fetch(url);
                const data = await resp.json();
                this.results = data.evaluations || [];
            } catch { this.results = []; }
            this.loading = false;
        },

        async loadTraces() {
            try {
                const resp = await fetch('/api/traces?limit=50');
                const data = await resp.json();
                this.traces = data.traces || [];
            } catch { this.traces = []; }
        },

        async runEval() {
            if (!this.selectedTrace) return;
            this.running = true;
            this.filterByTrace = true;
            await fetch('/api/eval/run', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ trace_id: this.selectedTrace })
            });
            this.running = false;
            await this.loadResults();
        },

        showAll() {
            this.filterByTrace = false;
            this.loadResults();
        },

        getScoreColor(value) {
            if (value >= 0.8) return 'var(--success)';
            if (value >= 0.5) return 'var(--warning)';
            return 'var(--danger)';
        },

        formatScore(value) {
            if (typeof value !== 'number') return String(value);
            if (value > 100) return Math.round(value).toLocaleString();
            return (value * 100).toFixed(1) + '%';
        },

        isMetricScore(key) {
            return ['answer_relevancy', 'coherence', 'completeness',
                    'harmfulness', 'llm_time_ratio'].includes(key);
        }
    }));

    Alpine.data('discoveryPage', () => ({
        agents: [],
        loading: true,
        showRegister: false,
        form: { agent_id: '', url: '', capabilities: '', heartbeat_interval_s: 30 },

        async init() {
            await this.loadAgents();
            setInterval(() => this.loadAgents(), 10000);
        },

        async loadAgents() {
            try {
                const resp = await fetch('/api/discovery/agents');
                const data = await resp.json();
                this.agents = data.agents || [];
            } catch { }
            this.loading = false;
        },

        async registerAgent() {
            const caps = this.form.capabilities
                ? this.form.capabilities.split(',').map(c => c.trim()).filter(Boolean)
                : [];
            await fetch('/api/discovery/register', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({
                    agent_id: this.form.agent_id,
                    name: this.form.agent_id,
                    endpoint: this.form.url,
                    capabilities: caps,
                    heartbeat_interval_s: this.form.heartbeat_interval_s
                })
            });
            this.showRegister = false;
            this.form = { agent_id: '', url: '', capabilities: '', heartbeat_interval_s: 30 };
            await this.loadAgents();
        },

        async deregisterAgent(agentId) {
            if (!confirm('Deregister this agent?')) return;
            await fetch(`/api/discovery/agents/${agentId}`, { method: 'DELETE' });
            await this.loadAgents();
        }
    }));

    Alpine.data('flagsPage', () => ({
        agents: [],
        selectedAgent: '_global',
        flags: [],
        params: [],
        loading: true,
        showNewFlag: false,
        showNewParam: false,
        newFlag: { name: '', enabled: false, value: '' },
        newParam: { key: '', value: '' },

        async init() {
            await this.loadAgents();
            await this.loadFlags();
            await this.loadParams();
        },

        async loadAgents() {
            try {
                const resp = await fetch('/api/discovery/agents');
                const data = await resp.json();
                this.agents = data.agents || [];
            } catch { }
        },

        async loadFlags() {
            this.loading = true;
            try {
                const resp = await fetch(`/api/flags/${this.selectedAgent}?include_global=false`);
                const data = await resp.json();
                this.flags = data.flags || [];
            } catch { this.flags = []; }
            this.loading = false;
        },

        async loadParams() {
            try {
                const resp = await fetch(`/api/params/${this.selectedAgent}?include_global=false`);
                const data = await resp.json();
                this.params = data.params || [];
            } catch { this.params = []; }
        },

        async addFlag() {
            let value = this.newFlag.value;
            if (value === '') value = null;
            else { try { value = JSON.parse(value); } catch { } }
            await fetch(`/api/flags/${this.selectedAgent}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: this.newFlag.name, enabled: this.newFlag.enabled, value })
            });
            this.showNewFlag = false;
            this.newFlag = { name: '', enabled: false, value: '' };
            await this.loadFlags();
        },

        async addParam() {
            let value = this.newParam.value;
            try { value = JSON.parse(value); } catch { }
            await fetch(`/api/params/${this.selectedAgent}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: this.newParam.key, value })
            });
            this.showNewParam = false;
            this.newParam = { key: '', value: '' };
            await this.loadParams();
        },

        async toggleFlag(flag) {
            await fetch(`/api/flags/${this.selectedAgent}`, {
                method: 'PUT',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name: flag.name, enabled: !flag.enabled, value: flag.value })
            });
            await this.loadFlags();
        },

        async deleteFlag(flagId) {
            if (!confirm('Delete this flag?')) return;
            await fetch(`/api/flags/${this.selectedAgent}/${flagId}`, { method: 'DELETE' });
            await this.loadFlags();
        },

        async deleteParam(paramId) {
            if (!confirm('Delete this parameter?')) return;
            await fetch(`/api/params/${this.selectedAgent}/${paramId}`, { method: 'DELETE' });
            await this.loadParams();
        }
    }));

    Alpine.data('chatPage', () => ({
        agents: [],
        selectedAgent: '',
        messages: [],
        input: '',
        sending: false,
        loading: true,

        async init() {
            await this.loadAgents();
        },

        async loadAgents() {
            try {
                const resp = await fetch('/api/discovery/agents');
                const data = await resp.json();
                this.agents = data.agents || [];
                if (this.agents.length > 0 && !this.selectedAgent) {
                    this.selectedAgent = this.agents[0].agent_id;
                }
            } catch { }
            this.loading = false;
        },

        agentName() {
            const a = this.agents.find(a => a.agent_id === this.selectedAgent);
            return a ? a.name || a.agent_id : this.selectedAgent;
        },

        async sendMessage() {
            const text = this.input.trim();
            if (!text || !this.selectedAgent || this.sending) return;

            this.messages.push({ role: 'user', content: text, ts: new Date().toLocaleTimeString() });
            this.input = '';
            this.sending = true;
            this.scrollToBottom();

            try {
                const resp = await fetch(`/api/chat/${this.selectedAgent}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify({ prompt: text })
                });
                const data = await resp.json();

                if (data.error) {
                    this.messages.push({
                        role: 'error',
                        content: data.error,
                        ts: new Date().toLocaleTimeString()
                    });
                } else {
                    const reply = data.response || data.result || JSON.stringify(data);
                    this.messages.push({
                        role: 'assistant',
                        content: reply,
                        agent: this.agentName(),
                        ts: new Date().toLocaleTimeString()
                    });
                }
            } catch (e) {
                this.messages.push({
                    role: 'error',
                    content: 'Failed to reach agent: ' + e.message,
                    ts: new Date().toLocaleTimeString()
                });
            }
            this.sending = false;
            this.scrollToBottom();
        },

        scrollToBottom() {
            this.$nextTick(() => {
                const el = document.getElementById('chat-messages');
                if (el) el.scrollTop = el.scrollHeight;
            });
        },

        clearChat() {
            this.messages = [];
        }
    }));
});
