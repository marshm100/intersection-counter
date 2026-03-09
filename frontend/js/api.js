const API = {
    async get(url) { const r = await fetch(url); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); },
    async post(url, data) { const r = await fetch(url, { method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); },
    async put(url, data) { const r = await fetch(url, { method:'PUT', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); },
    async patch(url, data) { const r = await fetch(url, { method:'PATCH', headers:{'Content-Type':'application/json'}, body:JSON.stringify(data) }); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); },
    async del(url) { const r = await fetch(url, { method:'DELETE' }); if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.json(); }
};
