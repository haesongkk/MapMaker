import fs from 'node:fs/promises';
const selection=JSON.parse(await fs.readFile('artifacts/assets/ram-qwen-filter-new-scenes/presentation-selection.json','utf8'));
if(selection.version!=='vision-furniture'||selection.samples.length!==3)throw Error('Final selection must contain three cases of the same method');
for(const item of selection.samples){
 const root=item.asset_root||(item.sample.startsWith('present-')?'artifacts/assets/ram-qwen-filter-presentation':'artifacts/assets/ram-qwen-filter-new-scenes');
 const captures=JSON.parse(await fs.readFile(`${root}/captures-clean.json`,'utf8'));
 const b=captures.find(c=>c.sample===item.sample&&c.version==='baseline');
 const f=captures.find(c=>c.sample===item.sample&&c.version==='vision-furniture');
 if(!b||!f||b.errors.length||f.errors.length||!b.grid_hidden||!f.grid_hidden)throw Error('Missing verified comparison capture');
 if(f.scene_sha256!==item.result.scene_sha256||b.input_sha256!==f.input_sha256)throw Error('Provenance mismatch');
 for(const key of ['camera','target'])if(b[key].some((x,i)=>Math.abs(x-f[key][i])>1e-10))throw Error('Different comparison cameras');
}
console.log('Verified: three selected scenes, one method, matching input hashes and comparison cameras.');
