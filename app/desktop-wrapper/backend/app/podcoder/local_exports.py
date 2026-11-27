"""Self-contained local reports and portable agent templates. No sharing/upload."""
import html
import json
import uuid
from pathlib import Path


def report(state, owner, title, text):
    if len(text) > 2_000_000:
        raise ValueError('report too large')
    doc = ('<!doctype html><html lang="en"><meta charset="utf-8">'
           '<meta name="viewport" content="width=device-width, initial-scale=1">'
           '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
           '<style>body{font:17px system-ui;max-width:900px;margin:40px auto;padding:20px}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style>'
           '<title>'+html.escape(title[:200])+'</title><h1>'+html.escape(title[:200])+'</h1><pre>'+html.escape(text)+'</pre></html>')
    folder = state/'exports'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/('report-'+uuid.uuid4().hex+'.html')
    path.write_text(doc,encoding='utf-8')
    return {'ok':True,'path':str(path),'content':doc,'filename':path.name,'shared':False}


def validate_template(doc):
    if not isinstance(doc,dict) or set(doc) - {'format','version','name','agents'}:
        raise ValueError('unknown template fields; credentials and tools are not portable')
    if doc.get('format') != 'simko-agent-template' or doc.get('version') != 1:
        raise ValueError('unsupported template version')
    if not isinstance(doc.get('name'),str) or not 1 <= len(doc['name']) <= 100:
        raise ValueError('template name required')
    agents = doc.get('agents')
    if not isinstance(agents,list) or not 1 <= len(agents) <= 4:
        raise ValueError('template requires 1–4 agents')
    for agent in agents:
        if not isinstance(agent,dict) or set(agent) - {'name','instructions','model'}:
            raise ValueError('unknown agent fields')
        if not isinstance(agent.get('name'),str) or not 1 <= len(agent['name']) <= 40:
            raise ValueError('agent name required')
        if not isinstance(agent.get('instructions'),str) or len(agent['instructions']) > 12000:
            raise ValueError('bounded instructions required')
        if 'model' in agent and (not isinstance(agent['model'],str) or len(agent['model']) > 64):
            raise ValueError('invalid model')
    if len({a['name'] for a in agents}) != len(agents):
        raise ValueError('duplicate agent names')
    return doc


def export_template(state, name, agents):
    doc = validate_template({'format':'simko-agent-template','version':1,'name':name,'agents':agents})
    folder = state/'templates'
    folder.mkdir(parents=True,exist_ok=True)
    path = folder/(uuid.uuid4().hex+'.simko-template.json')
    content = json.dumps(doc,indent=2)
    path.write_text(content,encoding='utf-8')
    return {'ok':True,'path':str(path),'filename':path.name,'content':content}


def import_template(state, content):
    if len(content) > 100000:
        raise ValueError('template too large')
    doc = validate_template(json.loads(content))
    return export_template(state,doc['name'],doc['agents'])


def apply_template(state, owner, content, *, owner_confirmed=False):
    """Activate instructions, never credentials/tools or an automatic agent run.

    Append revisions rather than overwriting user configurations. Import and apply
    both revalidate the complete document; filenames/paths are never accepted.
    """
    import sqlite3
    if owner_confirmed is not True or not owner:
        return {'ok': False, 'error': 'explicit template application confirmation required'}
    if len(content) > 100000:
        raise ValueError('template too large')
    doc = validate_template(json.loads(content))
    state.mkdir(parents=True, exist_ok=True)
    ident = uuid.uuid4().hex
    with sqlite3.connect(state/'agent_templates.sqlite') as conn:
        conn.execute('create table if not exists applied (seq integer primary key autoincrement, id text unique, owner text, content text)')
        conn.execute('insert into applied(id,owner,content) values (?,?,?)', (ident, owner, json.dumps(doc)))
    return {'ok': True, 'id': ident, 'template': doc, 'started': False}


def active_template(state, owner):
    import sqlite3
    if not (state/'agent_templates.sqlite').exists():
        return {'ok': False, 'error': 'no applied template'}
    with sqlite3.connect(state/'agent_templates.sqlite') as conn:
        row = conn.execute('select id,content from applied where owner=? order by seq desc limit 1', (owner,)).fetchone()
    if not row:
        return {'ok': False, 'error': 'no applied template'}
    return {'ok': True, 'id': row[0], 'template': validate_template(json.loads(row[1]))}


def template_history(state, owner, limit=50):
    """Owner-scoped, newest-first list of applied revisions (names only, no content)."""
    import sqlite3
    if not owner or not (state/'agent_templates.sqlite').exists():
        return {'ok': True, 'revisions': []}
    with sqlite3.connect(state/'agent_templates.sqlite') as conn:
        rows = conn.execute('select seq,id,content from applied where owner=? order by seq desc limit ?',
                            (owner, max(1, min(int(limit), 200)))).fetchall()
    out = []
    for seq, ident, content in rows:
        doc = json.loads(content)
        out.append({'id': ident, 'revision': seq, 'name': doc.get('name'), 'agents': [a['name'] for a in doc.get('agents', [])]})
    if out:
        out[0]['active'] = True
    return {'ok': True, 'revisions': out}


def rollback_template(state, owner, revision_id, *, owner_confirmed=False):
    """Re-activate an earlier revision by appending it again; history is never rewritten."""
    import sqlite3
    if owner_confirmed is not True or not owner:
        return {'ok': False, 'error': 'explicit template application confirmation required'}
    if not (state/'agent_templates.sqlite').exists():
        return {'ok': False, 'error': 'revision not found'}
    with sqlite3.connect(state/'agent_templates.sqlite') as conn:
        row = conn.execute('select content from applied where owner=? and id=?', (owner, str(revision_id))).fetchone()
    if not row:
        return {'ok': False, 'error': 'revision not found'}
    result = apply_template(state, owner, row[0], owner_confirmed=True)
    result['restored_from'] = str(revision_id)
    return result
