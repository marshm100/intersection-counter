const API = {
    async _err(r) {
        let msg = `HTTP ${r.status}`;
        try { const b = await r.json(); if (b.detail) msg = b.detail; } catch(_){}
        throw new Error(msg);
    },
    async get(url) { const r = await fetch(url); if (!r.ok) await API._err(r); return r.json(); },
    async post(url, data) { const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); if (!r.ok) await API._err(r); return r.json(); },
    async put(url, data) { const r = await fetch(url, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); if (!r.ok) await API._err(r); return r.json(); },
    async patch(url, data) { const r = await fetch(url, { method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); if (!r.ok) await API._err(r); return r.json(); },
    async del(url) { const r = await fetch(url, { method:'DELETE' }); if (!r.ok) await API._err(r); return r.json(); }
};
