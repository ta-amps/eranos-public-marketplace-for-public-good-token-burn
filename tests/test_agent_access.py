"""Public agent access never bypasses canonical fabric governance."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from eranos.api.app import app

ROOT = Path(__file__).resolve().parents[1]


def test_browser_onboarding_and_cors() -> None:
    client = TestClient(app)
    for path in ["/mcp", "/api/health", "/connect.json"]:
        response = client.options(
            path,
            headers={
                "Origin": "https://assistant.example.com",
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type, X-Agent-Label",
            },
        )
        assert response.status_code in (200, 204)
        assert response.headers["access-control-allow-origin"] == "*"
    descriptor = client.get("/connect.json").json()
    assert descriptor["fabric_connect_url"] == "https://tessera.ta-amps.workers.dev/connect"
    assert descriptor["surface_persistence"] is False
    card = client.get("/.well-known/agent-card.json").json()
    tools = client.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"}).json()[
        "result"
    ]["tools"]
    assert {skill["id"] for skill in card["skills"]} == {tool["name"] for tool in tools}


def test_worker_governance_and_agent_access() -> None:
    script = r"""
import { DatabaseSync } from 'node:sqlite';
import worker from WORKER;
const db = new DatabaseSync(':memory:');
// Relevant canonical D1 columns; this regression runs on a standalone checkout.
// Composite namespace keys mirror the fabric schema and let the query prove its join.
db.exec(`CREATE TABLE records (
 namespace TEXT NOT NULL DEFAULT 'main', store TEXT NOT NULL, key TEXT NOT NULL,
 version INTEGER NOT NULL, value TEXT NOT NULL, created_at REAL NOT NULL,
 producer_surface TEXT NOT NULL DEFAULT 'surface:tessera',
 visibility_scope TEXT NOT NULL DEFAULT 'public_commons',
 allowed_surfaces TEXT NOT NULL DEFAULT '[]', target_cohorts TEXT NOT NULL DEFAULT '["all"]',
 tags TEXT NOT NULL DEFAULT '[]', owner_key_id TEXT,
 PRIMARY KEY(namespace,store,key,version));
 CREATE TABLE record_heads (
 namespace TEXT NOT NULL DEFAULT 'main', store TEXT NOT NULL, key TEXT NOT NULL,
 version INTEGER NOT NULL, producer_surface TEXT NOT NULL DEFAULT 'surface:tessera',
 visibility_scope TEXT NOT NULL DEFAULT 'public_commons',
 allowed_surfaces TEXT NOT NULL DEFAULT '[]', target_cohorts TEXT NOT NULL DEFAULT '["all"]',
 tags TEXT NOT NULL DEFAULT '[]', owner_key_id TEXT,
 PRIMARY KEY(namespace,store,key));`);
function put(ns,store,key,value,visibility,tags,producer) {
 const tagJson=JSON.stringify(tags);
 db.prepare('INSERT INTO records(namespace,store,key,version,value,created_at,visibility_scope,tags,producer_surface) VALUES (?,?,?,1,?,0,?,?,?)').run(ns,store,key,JSON.stringify(value),visibility,tagJson,producer);
 db.prepare('INSERT INTO record_heads(namespace,store,key,version,visibility_scope,tags,producer_surface) VALUES (?,?,?,1,?,?,?)').run(ns,store,key,visibility,tagJson,producer);
}
const surface=SURFACE;
const store=surface==='eranos'?'eranos.catalog':'shamash.cases';
const privateId=surface==='eranos'?'KIT-SECRET-99':'C-FS-PH-99';
const publicId=surface==='eranos'?'KIT-PUBLIC-98':'C-FS-PH-98';
const route=surface==='eranos'?'/api/catalog/':'/api/cases/';
const privateValue={synthetic:true,visibility_scope:'public_commons',tags:['status:verified'],target_cohorts:['all'],kit:{kit_id:privateId},case:{id:privateId}};
put('sandbox_alpha',store,privateId,privateValue,'private',['status:quarantined'],'surface:'+surface);
put('main',store,publicId,{...privateValue,kit:{kit_id:publicId},case:{id:publicId}},'public_commons',['status:verified','synthetic:true'],'surface:'+surface);
put('main',store,'KIT-ALLOW-97',{...privateValue,visibility_scope:'allowlist_surfaces'},'allowlist_surfaces',['status:verified'],'surface:'+surface);
const env={FABRIC_DB:{prepare(sql){const stmt=db.prepare(sql);return {bind(...args){return {async first(){return stmt.get(...args)||null},async all(){return {results:stmt.all(...args)}}}}}}}};
const results={};
for(const [key,path,method] of [['private',route+privateId,'GET'],['public',route+publicId,'GET'],['connect','/connect.json','GET'],['cors','/mcp','OPTIONS']]){
 const r=await worker.fetch(new Request('https://example.com'+path,{method,headers:{Origin:'https://assistant.example.com','Access-Control-Request-Method':'POST'}}),env);results[key]={status:r.status,headers:Object.fromEntries(r.headers),body:r.status===204?null:await r.json()};
}
if(surface==='eranos'){const r=await worker.fetch(new Request('https://example.com/api/catalog/KIT-ALLOW-97'),env);results.allowlist=r.status;}
const card = await (await worker.fetch(new Request('https://example.com/.well-known/agent-card.json'),env)).json();
const tools = await (await worker.fetch(new Request('https://example.com/mcp',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({jsonrpc:'2.0',id:1,method:'tools/list'})}),env)).json();
results.cardTools = card.skills.map((s)=>s.id).sort(); results.liveTools = tools.result.tools.map((t)=>t.name).sort();
console.log(JSON.stringify(results));
"""
    script = script.replace(
        "WORKER", json.dumps((ROOT / "deploy/cloudflare/worker.js").as_uri())
    ).replace("SURFACE", json.dumps("eranos"))
    run = subprocess.run(
        ["node", "--input-type=module", "-e", script], check=True, capture_output=True, text=True
    )
    data = json.loads(run.stdout)
    assert data["cardTools"] == data["liveTools"]
    assert data["private"]["status"] == 404
    assert data["public"]["status"] == 200
    assert data["connect"]["body"]["surface_persistence"] is False
    assert data["cors"]["status"] == 204
    assert data["cors"]["headers"]["access-control-allow-origin"] == "*"
    if "allowlist" in data:
        assert data["allowlist"] == 404
