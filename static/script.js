document.addEventListener('DOMContentLoaded', () => {

    // ===================== NAVIGATION =====================
    const navItems = document.querySelectorAll('.nav-item');
    const pages = document.querySelectorAll('.page');

    navItems.forEach(item => {
        item.addEventListener('click', (e) => {
            e.preventDefault();
            const target = item.dataset.page;
            navItems.forEach(n => n.classList.remove('active'));
            pages.forEach(p => p.classList.remove('active'));
            item.classList.add('active');
            document.getElementById(`page-${target}`).classList.add('active');

            if (target === 'customers') loadCustomers();
            if (target === 'inventory') loadInventory();
            if (target === 'broadcast') initBroadcast();
            if (target === 'settings') loadSettings();
        });
    });

    // ===================== DATA FETCHING =====================
    async function fetchStats() {
        try {
            const res = await fetch('/api/stats');
            const data = await res.json();

            const el = id => document.getElementById(id);

            if (el('stat-customers')) el('stat-customers').textContent = data.total_customers || 0;
            if (el('stat-vip')) el('stat-vip').textContent = data.vip_count || 0;
            if (el('stat-leads')) el('stat-leads').textContent = data.lead_count || 0;
            if (el('stat-orders')) el('stat-orders').textContent = data.orders_ready || 0;
            if (el('header-traffic')) el('header-traffic').textContent = data.today_interactions || 0;
            if (el('badge-customers')) el('badge-customers').textContent = data.total_customers || 0;

            const waEl = el('header-wa-status');
            if (waEl && data.whatsapp) {
                waEl.textContent = data.whatsapp.label;
                window.waLive = data.whatsapp.connected;
                waEl.style.color = data.whatsapp.connected ? 'var(--accent-emerald)' : '#ef4444';
            }

            const memory = data.memory_ok;
            window.mongoLive = memory;
            el('sidebar-status').textContent = memory ? 'AI CORE ONLINE' : 'DB OFFLINE';
            el('sidebar-pulse').style.background = memory ? 'var(--accent-emerald)' : '#ef4444';

        } catch (err) {
            console.error('Stats fetch error:', err);
        }
    }

    async function fetchActivity() {
        try {
            const res = await fetch('/api/activity');
            const logs = await res.json();
            const feed = document.getElementById('log-feed');
            if (!logs.length || !feed) return;

            feed.innerHTML = '';
            logs.forEach(log => {
                const item = document.createElement('div');
                item.className = `log-item type-${log.type || 'info'}`;
                item.innerHTML = `<span class="time">${log.time}</span><span class="msg">${log.message}</span>`;
                feed.appendChild(item);
            });

            const dp = document.getElementById('dp-threads');
            if (dp) dp.textContent = `Logs: ${logs.length}`;
            const lat = document.getElementById('dp-lat');
            if (lat) lat.textContent = `Lat: ${Math.floor(Math.random() * 40 + 10)}ms`;
        } catch (err) {
            console.error('Activity fetch error:', err);
        }
    }

    async function fetchAgents() {
        try {
            const res = await fetch('/api/agents');
            const agents = await res.json();
            const list = document.getElementById('agent-list');
            if (!list) return;
            list.innerHTML = '';
            agents.forEach(agent => {
                const item = document.createElement('div');
                item.className = 'agent-item';
                item.innerHTML = `
                    <div class="agent-avatar ${agent.color}">${agent.avatar}</div>
                    <div class="agent-details">
                        <strong>${agent.name}</strong>
                        <p>${agent.task}</p>
                    </div>
                    <span class="agent-status ${agent.status}"></span>
                `;
                list.appendChild(item);
            });
        } catch (err) { console.error('Agents fetch error:', err); }
    }

    // ===================== BUTTONS =====================
    const syncBtn = document.getElementById('btn-sync');
    if (syncBtn) {
        syncBtn.addEventListener('click', async () => {
            syncBtn.disabled = true;
            syncBtn.innerHTML = '⏳ Syncing...';
            try {
                const res = await fetch('/api/sync', { method: 'POST' });
                const data = await res.json();
                syncBtn.innerHTML = '✅ Synced';
                setTimeout(() => {
                    syncBtn.disabled = false;
                    syncBtn.innerHTML = `<svg class="icon-s" viewBox="0 0 24 24"><path d="M12 4V1L8 5l4 4V6c3.31 0 6 2.69 6 6 0 1.01-.25 1.97-.7 2.8l1.46 1.46C19.54 15.03 20 13.57 20 12c0-4.42-3.58-8-8-8zm0 14c-3.31 0-6-2.69-6-6 0-1.01.25-1.97.7-2.8L5.24 7.74C4.46 8.97 4 10.43 4 12c0 4.42 3.58 8 8 8v3l4-4-4-4v3z"/></svg> Sync ERP`;
                }, 2000);
            } catch (e) {
                syncBtn.disabled = false;
                syncBtn.innerHTML = 'Sync ERP';
            }
        });
    }

    // ===================== AI TEST CHAT =====================
    const testBtn = document.getElementById('btn-test');
    const testInput = document.getElementById('test-input');
    const chatBox = document.getElementById('chat-box');

    function appendChat(text, role) {
        if (!chatBox) return;
        const msg = document.createElement('div');
        msg.className = `chat-msg ${role}`;
        msg.textContent = text;
        chatBox.appendChild(msg);
        chatBox.scrollTop = chatBox.scrollHeight;
    }

    async function sendTestMessage() {
        const msg = testInput.value.trim();
        if (!msg) return;
        appendChat(msg, 'user');
        testInput.value = '';
        testBtn.disabled = true;
        testBtn.textContent = '...';
        try {
            const res = await fetch('/api/chat', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message: msg })
            });
            const data = await res.json();
            appendChat(data.reply || data.error, 'ai');
        } catch (err) {
            appendChat('Error connecting to AI.', 'ai');
        } finally {
            testBtn.disabled = false;
            testBtn.textContent = 'Send';
        }
    }

    if (testBtn) testBtn.addEventListener('click', sendTestMessage);
    if (testInput) testInput.addEventListener('keydown', e => { if (e.key === 'Enter') sendTestMessage(); });

    // ===================== INVENTORY PAGE =====================
    window.loadInventory = async function() {
        const grid = document.getElementById('inventory-grid');
        const search = document.getElementById('inventory-search')?.value || '';
        grid.innerHTML = '<div class="empty-state"><div>⏳</div><p>Loading inventory from ERP...</p></div>';
        try {
            const params = new URLSearchParams({ search });
            const res = await fetch(`/api/inventory?${params}`);
            const data = await res.json();
            const items = data.items || [];

            const countEl = document.getElementById('inventory-count');
            if (countEl) countEl.textContent = items.length;
            document.getElementById('badge-inventory').textContent = items.length;

            if (!items.length) {
                grid.innerHTML = `<div class="empty-state">
                    <div style="font-size:3rem;">📦</div>
                    <p>No inventory found.</p>
                    <p style="font-size:0.8rem;color:var(--text-secondary);margin-top:0.5rem;">Add documents to the <code>inventory</code> collection in MongoDB Atlas with fields: <code>name, type, color, size, quantity</code></p>
                </div>`;
                return;
            }

            grid.innerHTML = '';
            items.forEach(item => {
                const card = document.createElement('div');
                card.className = 'inventory-card glass';
                const qty = item.quantity || 0;
                const qtyColor = qty > 10 ? 'var(--accent-emerald)' : qty > 0 ? '#fbbf24' : '#ef4444';
                const qtyLabel = qty > 10 ? 'In Stock' : qty > 0 ? 'Low Stock' : 'Out of Stock';
                card.innerHTML = `
                    <div class="inv-type-badge">${item.type || 'Product'}</div>
                    <div class="inv-name">${item.name || 'Unnamed Item'}</div>
                    <div class="inv-details">
                        ${item.color ? `<span class="inv-tag">🎨 ${item.color}</span>` : ''}
                        ${item.size ? `<span class="inv-tag">📐 ${item.size}</span>` : ''}
                        ${item.sku ? `<span class="inv-tag">🔖 ${item.sku}</span>` : ''}
                    </div>
                    <div class="inv-stock" style="color:${qtyColor}">
                        <strong>${qty}</strong> units · ${qtyLabel}
                    </div>
                `;
                grid.appendChild(card);
            });
        } catch (err) {
            grid.innerHTML = '<div class="empty-state"><div>❌</div><p>Failed to load inventory.</p></div>';
        }
    };

    const invSearch = document.getElementById('inventory-search');
    if (invSearch) {
        let timer;
        invSearch.addEventListener('input', () => {
            clearTimeout(timer);
            timer = setTimeout(loadInventory, 400);
        });
    }

    // ===================== CUSTOMERS PAGE =====================
    window.loadCustomers = async function() {
        const grid = document.getElementById('customers-grid');
        const search = document.getElementById('customer-search')?.value || '';
        const tier = document.getElementById('tier-filter')?.value || 'all';
        grid.innerHTML = '<div class="empty-state"><div>⏳</div><p>Loading...</p></div>';
        try {
            const params = new URLSearchParams({ search, tier, limit: 60 });
            const res = await fetch(`/api/customers?${params}`);
            const data = await res.json();
            const customers = data.customers || [];

            if (!customers.length) {
                grid.innerHTML = '<div class="empty-state"><div>👥</div><p>No customers found.</p></div>';
                return;
            }

            grid.innerHTML = '';
            customers.forEach((c, i) => {
                const card = document.createElement('div');
                card.className = 'customer-card';
                card.style.animationDelay = `${i * 0.04}s`;
                const initial = (c.name || 'V')[0].toUpperCase();
                const tierClass = c.tier === 'VIP' ? 'tier-vip' : 'tier-lead';
                const helpNeeded = c.awaiting_human === true;
                
                card.innerHTML = `
                    ${helpNeeded ? '<div class="alert-badge pulse">🚨 NEEDS HELP</div>' : ''}
                    <div class="customer-avatar">${initial}</div>
                    <div class="customer-name">${c.name || 'Unknown'}</div>
                    <div class="customer-phone">📱 +${c.phone}</div>
                    <div class="customer-footer">
                        <span class="tier-badge ${tierClass}">${c.tier || 'Lead'}</span>
                        <span class="customer-last">${c.last_interaction || 'N/A'}</span>
                        ${helpNeeded ? `<button class="btn btn-outline btn-xs" onclick="event.stopPropagation(); clearFlag('${c.phone}')" style="margin-left:auto; border-color:#ef4444; color:#ef4444; padding: 2px 5px; font-size: 0.6rem;">Clear</button>` : ''}
                    </div>
                `;
                card.addEventListener('click', () => openCustomer(c));
                grid.appendChild(card);
            });
        } catch (err) {
            grid.innerHTML = '<div class="empty-state"><div>❌</div><p>Failed to load customers.</p></div>';
        }
    };

    window.openCustomer = async function(customer) {
        document.getElementById('modal-name').textContent = customer.name || 'Unknown Client';
        document.getElementById('customer-modal').style.display = 'flex';
        const body = document.getElementById('modal-body');
        body.innerHTML = `
            <div style="display: grid; grid-template-columns: 1fr 1fr; gap: 12px; margin-bottom: 1.5rem;">
                <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 10px;">
                    <div style="font-size:0.7rem;color:var(--text-secondary)">PHONE</div>
                    <div style="font-size:0.95rem;margin-top:4px">+${customer.phone}</div>
                </div>
                <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 10px;">
                    <div style="font-size:0.7rem;color:var(--text-secondary)">TIER</div>
                    <div style="font-size:0.95rem;margin-top:4px;color:${customer.tier === 'VIP' ? '#fbbf24' : 'var(--accent-emerald)'}">${customer.tier}</div>
                </div>
                <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 10px;">
                    <div style="font-size:0.7rem;color:var(--text-secondary)">JOINED</div>
                    <div style="font-size:0.95rem;margin-top:4px">${customer.created_at || 'N/A'}</div>
                </div>
                <div style="background: rgba(0,0,0,0.3); padding: 10px; border-radius: 10px;">
                    <div style="font-size:0.7rem;color:var(--text-secondary)">LAST SEEN</div>
                    <div style="font-size:0.95rem;margin-top:4px">${customer.last_interaction || 'N/A'}</div>
                </div>
            </div>
            <h4 style="margin-bottom:1rem;font-size:0.9rem;color:var(--text-secondary)">CONVERSATION HISTORY</h4>
            <div id="modal-interactions">⏳ Loading...</div>
        `;
        try {
            const res = await fetch(`/api/customers/${customer.phone}/history`);
            const data = await res.json();
            const container = document.getElementById('modal-interactions');
            if (!data.interactions.length) {
                container.innerHTML = '<p style="color:var(--text-secondary);font-size:0.85rem">No interactions recorded.</p>';
                return;
            }
            container.innerHTML = '';
            data.interactions.forEach(i => {
                const el = document.createElement('div');
                el.className = `interaction-item ${i.direction}`;
                el.innerHTML = `
                    <div style="display:flex;justify-content:space-between;margin-bottom:4px">
                        <span class="i-dir">${i.direction === 'inbound' ? '📱 CUSTOMER' : '🤖 HEIN AI'}</span>
                        <span class="i-time">${i.timestamp}</span>
                    </div>
                    <div class="i-msg">${i.message}</div>
                `;
                container.appendChild(el);
            });
        } catch {}
    };

    window.closeModal = function() {
        document.getElementById('customer-modal').style.display = 'none';
    };

    const searchInput = document.getElementById('customer-search');
    const tierFilter = document.getElementById('tier-filter');
    if (searchInput) {
        let searchTimer;
        searchInput.addEventListener('input', () => {
            clearTimeout(searchTimer);
            searchTimer = setTimeout(loadCustomers, 400);
        });
    }
    if (tierFilter) tierFilter.addEventListener('change', loadCustomers);

    // ===================== BROADCAST PAGE =====================
    window.initBroadcast = async function() {
        await previewBroadcast();
        try {
            const res = await fetch('/api/whatsapp/status');
            const data = await res.json();
            const notice = document.getElementById('wa-notice');
            if (!data.connected) {
                notice.style.display = 'block';
                notice.innerHTML = '⚠️ WhatsApp not configured. Messages will be simulated.';
            }
        } catch {}
    };

    window.previewBroadcast = async function() {
        const tier = document.getElementById('broadcast-tier')?.value || 'all';
        try {
            const res = await fetch('/api/broadcast/preview', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ tier })
            });
            const data = await res.json();
            const label = { all: 'All Customers', VIP: 'VIP Clients', Lead: 'Active Leads' }[tier] || tier;
            document.getElementById('broadcast-preview').innerHTML = `📊 Will reach <strong style="color:var(--accent-emerald)">${data.count} recipients</strong> (${label})`;
        } catch {}
    };

    window.sendBroadcast = async function() {
        const message = document.getElementById('broadcast-message').value.trim();
        const tier = document.getElementById('broadcast-tier').value;
        const btn = document.getElementById('btn-broadcast');
        const log = document.getElementById('broadcast-log');
        if (!message) { alert('Please write a message first.'); return; }
        btn.disabled = true;
        btn.textContent = '⏳ Sending...';
        try {
            const res = await fetch('/api/broadcast', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ message, tier })
            });
            const data = await res.json();
            const timestamp = new Date().toLocaleTimeString();
            const logItem = document.createElement('div');
            logItem.className = 'log-item';
            logItem.innerHTML = `<span class="time">${timestamp}</span> <span class="msg">📤 Broadcast: ${data.sent} delivered, ${data.failed} failed. Tier: ${tier}</span>`;
            log.prepend(logItem);
            btn.innerHTML = '✅ Sent!';
            setTimeout(() => {
                btn.disabled = false;
                btn.innerHTML = `<svg class="icon-s" viewBox="0 0 24 24"><path d="M20 2H4c-1.1 0-2 .9-2 2v18l4-4h14c1.1 0 2-.9 2-2V4c0-1.1-.9-2-2-2zm0 14H5.17L4 17.17V4h16v12z"/></svg> Send Broadcast`;
            }, 2500);
        } catch (err) {
            btn.disabled = false;
            btn.textContent = 'Send Broadcast';
        }
    };

    // ===================== SETTINGS PAGE =====================
    window.loadSettings = async function() {
        // Load AI Settings from MongoDB
        try {
            const res = await fetch('/api/settings');
            const data = await res.json();
            if (data.persona) {
                document.getElementById('persona-prompt').value = data.persona;
            }
            if (data.languages && data.languages.length) {
                document.getElementById('languages-input').value = data.languages.join('\n');
            }
            if (data.quick_messages && data.quick_messages.length) {
                document.getElementById('quickmsg-input').value = data.quick_messages.join('\n');
            }
            
            // Load Team Managers
            loadManagers();
        } catch {}

        // WhatsApp Status
        try {
            const res = await fetch('/api/whatsapp/status');
            const data = await res.json();
            const icon = document.getElementById('wa-icon');
            const label = document.getElementById('wa-provider-label');
            const detail = document.getElementById('wa-provider-detail');
            const qrContainer = document.getElementById('wa-qr-container');
            const qrImage = document.getElementById('wa-qr-image');

            if (data.connected) {
                icon.textContent = '✅';
                label.textContent = data.label;
                if (data.provider === 'bridge' && data.bridge_ready) {
                    detail.textContent = 'Local Bridge active. Phone linked successfully.';
                    qrContainer.style.display = 'none';
                } else if (data.qr) {
                    qrContainer.style.display = 'block';
                    qrImage.src = data.qr;
                    detail.textContent = 'Waiting for QR scan...';
                } else {
                    qrContainer.style.display = 'none';
                    detail.textContent = 'WhatsApp ready.';
                }
            } else {
                icon.textContent = '⚠️';
                label.textContent = 'Not Configured';
                detail.textContent = 'Add Meta or Twilio credentials to .env.';
                qrContainer.style.display = 'none';
            }
        } catch {}

        // DB Status
        try {
            const res = await fetch('/api/stats');
            const data = await res.json();
            const dbEl = document.getElementById('db-detail');
            const dbUri = document.getElementById('db-uri-status');
            if (data.memory_ok) {
                dbEl.textContent = `Connected — ${data.total_customers} customers stored.`;
                dbUri.style.color = 'var(--accent-emerald)';
                dbUri.textContent = 'Connected to Atlas';
                const ts = document.getElementById('db-status-card').querySelector('strong');
                if (ts) ts.innerText = 'Connected';
            }
        } catch {}

        // Set webhook URL
        const webhookEl = document.getElementById('webhook-url');
        if (webhookEl) webhookEl.textContent = `${window.location.origin}/webhook`;
    };

    window.loadManagers = async function() {
        const list = document.getElementById('manager-list');
        if (!list) return;
        try {
            const res = await fetch('/api/managers');
            const data = await res.json();
            const managers = data.managers || [];
            
            if (!managers.length) {
                list.innerHTML = '<div class="empty-state" style="padding: 1rem; width: 100%;"><p style="font-size: 0.8rem;">No notification numbers set yet.</p></div>';
                return;
            }

            list.innerHTML = '';
            managers.forEach(m => {
                const tag = document.createElement('div');
                tag.className = 'glass';
                tag.style.padding = '8px 12px';
                tag.style.borderRadius = '10px';
                tag.style.display = 'flex';
                tag.style.alignItems = 'center';
                tag.style.gap = '10px';
                tag.style.border = '1px solid var(--glass-border)';
                tag.innerHTML = `
                    <span style="font-size: 0.85rem; font-weight: 600;">${m.name}</span>
                    <span style="font-size: 0.75rem; color: var(--text-secondary);">+${m.phone}</span>
                    <button onclick="removeManager('${m.phone}')" style="background:none; border:none; color:#ef4444; cursor:pointer; font-size: 1.2rem; display: flex;">&times;</button>
                `;
                list.appendChild(tag);
            });
        } catch (err) { console.error('Managers load error:', err); }
    };

    window.addManager = async function() {
        const nameEl = document.getElementById('manager-name');
        const phoneEl = document.getElementById('manager-phone');
        const name = nameEl.value.trim();
        const phone = phoneEl.value.trim();
        
        if (!name || !phone) {
            alert('Please enter both name and phone number.');
            return;
        }

        try {
            const res = await fetch('/api/managers', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ name, phone })
            });
            if (res.ok) {
                nameEl.value = '';
                phoneEl.value = '';
                loadManagers();
            }
        } catch (err) { console.error('Add manager error:', err); }
    };

    window.removeManager = async function(phone) {
        if (!confirm('Remove this number from notifications?')) return;
        try {
            const res = await fetch('/api/managers/delete', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone })
            });
            if (res.ok) loadManagers();
        } catch (err) { console.error('Remove manager error:', err); }
    };

    window.saveAllSettings = async function() {
        const btn = document.getElementById('btn-save-all');
        btn.disabled = true;
        btn.textContent = '⏳ Saving...';

        const persona = document.getElementById('persona-prompt').value.trim();
        const languagesRaw = document.getElementById('languages-input').value.trim();
        const quickmsgsRaw = document.getElementById('quickmsg-input').value.trim();

        const languages = languagesRaw ? languagesRaw.split('\n').map(l => l.trim()).filter(Boolean) : ['English'];
        const quick_messages = quickmsgsRaw ? quickmsgsRaw.split('\n').map(l => l.trim()).filter(Boolean) : [];

        try {
            const res = await fetch('/api/settings', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ persona, languages, quick_messages })
            });
            const data = await res.json();
            if (data.status === 'saved') {
                btn.innerHTML = '✅ Saved to MongoDB!';
                document.getElementById('persona-saved').style.display = 'block';
                setTimeout(() => {
                    document.getElementById('persona-saved').style.display = 'none';
                    btn.disabled = false;
                    btn.textContent = '💾 Save All Changes';
                }, 3000);
            } else {
                throw new Error(data.error || 'Unknown error');
            }
        } catch (e) {
            btn.disabled = false;
            btn.textContent = '❌ Save Failed — Try Again';
        }
    };

    window.clearFlag = async function(phone) {
        try {
            const res = await fetch('/api/customers/flag', {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ phone, flag: false })
            });
            if (res.ok) loadCustomers();
        } catch (err) { console.error('Clear flag error:', err); }
    };

    window.copyWebhook = function() {
        const url = document.getElementById('webhook-url').textContent;
        navigator.clipboard.writeText(url).then(() => alert('Webhook URL copied!'));
    };

    // ===================== INIT =====================
    fetchStats();
    fetchActivity();
    fetchAgents();

    setInterval(fetchActivity, 3000);
    setInterval(fetchStats, 15000);
    setInterval(fetchAgents, 30000);
});
