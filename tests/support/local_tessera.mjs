// A local Tessera for the worker tests: Tessera's own Cloudflare Worker on actual workerd (Miniflare),
// with SQLite Durable Objects and D1, anonymous sessions and requester sign-up on, outbound network denied.
// Same setup as the recorded real-run harness. TESSERA_CHECKOUT names a Tessera checkout with node_modules.
import { createRequire } from 'node:module';
const require = createRequire(process.env.TESSERA_CHECKOUT + '/package.json');
const { build } = require('esbuild');
const { Miniflare, convertV4MiniflareOptions } = require('miniflare');
const built = await build({entryPoints:[process.env.TESSERA_CHECKOUT+'/deploy/cloudflare/worker.js'],bundle:true,format:'esm',platform:'browser',write:false,external:['cloudflare:workers']});
const runtime = new Miniflare(convertV4MiniflareOptions({host:'127.0.0.1',port:0,cf:false,workers:[{name:'tessera',modules:true,script:built.outputFiles[0].text,compatibilityDate:'2026-10-01',durableObjects:{COORDINATOR:{className:'TesseraCoordinator',useSQLite:true}},d1Databases:['FABRIC_DB','BUCKETS_DB'],bindings:{STORAGE_MODE:'cloud',ANONYMOUS_ACCESS_ENABLED:'true',REQUESTER_SIGNUP_ENABLED:'true',FRAGILITY_PLANNER_ENABLED:'false',BOOTSTRAP_SECRET:process.env.TESSERA_TEST_BOOTSTRAP},outboundService:()=>{throw new Error('This local fabric may not make external network or model requests');}}]}));
const url = (await runtime.ready).toString();
// A deploy applies the D1 schemas (wrangler d1 execute); a fresh local D1 needs them applied here.
const { readFileSync } = await import('node:fs');
for (const [binding, file] of [['FABRIC_DB', 'd1-fabric.sql'], ['BUCKETS_DB', 'd1-buckets.sql']]) {
  const db = await runtime.getD1Database(binding);
  const sql = readFileSync(process.env.TESSERA_CHECKOUT + '/deploy/cloudflare/' + file, 'utf8').replace(/--[^\n]*/g, '');
  for (const statement of sql.split(';').map((s) => s.trim()).filter(Boolean)) await db.prepare(statement).run();
}
console.log(JSON.stringify({ready:true,url}));
async function stop(){await runtime.dispose();process.exit(0);}
process.on('SIGTERM',stop);process.on('SIGINT',stop);
