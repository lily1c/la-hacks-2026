import { test } from 'node:test'
import assert from 'node:assert/strict'
import { readFileSync } from 'node:fs'
import vm from 'node:vm'
import ts from 'typescript'
const source = readFileSync(new URL('../src/main.ts', import.meta.url), 'utf8')
const refresh = source.slice(source.indexOf('async function refresh() {'), source.indexOf('// Send the map image'))
function harness(ok, expired=false) {
 const reports=[]
 const context=vm.createContext({Date,console,Number,Object,Error,
  refreshing:false,summary:{id:'frame-1',timestamp:new Date(Date.now()-(expired?60000:0)).toISOString()},
  STALE_MS:15000,lastDisplayedId:'old-frame',layout:'text',shown:{},lastSdkRefresh:0,
  HEAD_ID:2,MAIN_ID:1,NAMES:{1:'main'},mapShown:null,
  render:()=>({1:'rendered text'}),pushMap:()=>{},page:x=>x,
  TextContainerUpgrade:class {constructor(x){Object.assign(this,x)}},RebuildPageContainer:class {},
  bridge:{textContainerUpgrade:async()=>ok,rebuildPageContainer:async()=>ok},
  reportDisplay:async(...args)=>reports.push(args)})
 vm.runInContext('function activeSummary(){return summary} function activeMapUrl(){return summary?.mapUrl ?? null}',context)
 vm.runInContext(ts.transpileModule(refresh,{compilerOptions:{target:ts.ScriptTarget.ES2022}}).outputText,context)
 return {context,reports}
}
test('reports text only after SDK accepts update',async()=>{const {context,reports}=harness(true);await context.refresh();assert.deepEqual(reports[0],['frame-1','rendered text','sdk_accepted'])})
test('failed SDK update reports failure and permits retry',async()=>{const {context,reports}=harness(false);await context.refresh();assert.equal(reports[0][2],'failed');assert.equal(Object.keys(context.shown).length,0)})
test('expired alert is cleared before rendering',async()=>{const {context,reports}=harness(true,true);await context.refresh();assert.equal(context.summary,null);assert.equal(reports[0][2],'cleared')})
