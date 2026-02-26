async function loadProjectList() {
    const section = document.getElementById('page-projects');
    let projects = [];
    try {
        projects = await API.get('/api/projects');
    } catch (e) {
        section.innerHTML = '<p class="empty-message">Could not connect to backend.</p>';
        return;
    }

    let html = '<h2>Projects</h2>';

    html += '<div class="project-controls">';
    html += '<input type="text" id="new-project-name" placeholder="New project name..." />';
    html += '<button onclick="createProject()">Create</button>';
    html += '</div>';

    if (projects.length === 0) {
        html += '<p class="empty-message">No projects yet</p>';
    } else {
        html += '<div class="project-list">';
        for (const p of projects) {
            const created = p.created_at ? new Date(p.created_at).toLocaleString() : '';
            html += '<div class="project-card">';
            html += '<div class="project-info">';
            html += `<div class="project-name">${escapeHtml(p.name)}</div>`;
            html += `<div class="project-meta">Status: ${escapeHtml(p.status)} &middot; Created: ${escapeHtml(created)}</div>`;
            html += '</div>';
            html += '<div class="project-actions">';
            html += `<button class="btn-open" onclick="openProject('${p.project_id}')">Open</button>`;
            html += `<button class="btn-delete" onclick="deleteProject('${p.project_id}', '${escapeHtml(p.name)}')">Delete</button>`;
            html += '</div>';
            html += '</div>';
        }
        html += '</div>';
    }

    section.innerHTML = html;

    const input = document.getElementById('new-project-name');
    input.addEventListener('keydown', (e) => {
        if (e.key === 'Enter') createProject();
    });
}

async function createProject() {
    const input = document.getElementById('new-project-name');
    const name = input.value.trim();
    if (!name) return;
    await API.post('/api/projects', { name });
    input.value = '';
    await loadProjectList();
}

async function deleteProject(projectId, projectName) {
    if (!window.confirm(`Delete project '${projectName}'? This cannot be undone.`)) return;
    await API.del(`/api/projects/${projectId}`);
    await loadProjectList();
}

function openProject(projectId) {
    AppState.currentProject = projectId;
    showPage('page-setup');
}

function escapeHtml(text) {
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}
