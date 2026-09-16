// Pure storage/metadata checks; no browser or real localStorage involved.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import ts from '../frontend/node_modules/typescript/lib/typescript.js';
const code=ts.transpileModule(fs.readFileSync(new URL('../frontend/src/draftResume.ts',import.meta.url),'utf8'),{compilerOptions:{module:ts.ModuleKind.ESNext,target:ts.ScriptTarget.ES2022}}).outputText;
const data=new Map();
globalThis.localStorage={getItem:k=>data.get(k)??null,setItem:(k,v)=>data.set(k,v),removeItem:k=>data.delete(k),key:i=>[...data.keys()][i]??null,get length(){return data.size}};
const {rememberDraft,forgetDraft,draftCandidates,silentLines}=await import('data:text/javascript;base64,'+Buffer.from(code).toString('base64'));
const id='a'.repeat(32),book='b'.repeat(32);
rememberDraft({draft_id:id,name:'带标题的工程',book:{id:book,index:2},silent:[0,3]});
assert.deepEqual(draftCandidates()[0],{draft_id:id,name:'带标题的工程',book:{id:book,index:2},silent:[0,3]});
forgetDraft('c'.repeat(32));assert.equal(draftCandidates()[0].draft_id,id);
forgetDraft(id);assert.equal(draftCandidates().length,0);
localStorage.setItem('voxstage-draft-'+book+'-2',id);
assert.deepEqual(draftCandidates()[0].book,{id:book,index:2});
assert.deepEqual(silentLines([{text:'标题😀\n',silent:true},{text:'\n正文\n'},{text:'第二节\n',silent:true}]),[0,3]);
assert.deepEqual(silentLines([{text:'普通对白\n'},{text:'另一段。'}]),[]);
console.log('6 resume metadata assertions passed');
