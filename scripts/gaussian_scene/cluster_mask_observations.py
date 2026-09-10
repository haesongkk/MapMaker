"""Cluster individual mask observations with explicit same-view cannot-links.
Unlike greedy track union, every observation retains its instance constraints.
Sampling is used only to propose correspondences, never to reduce output assets.
"""
import json,time
from pathlib import Path
from collections import defaultdict
import numpy as np
from scipy.sparse import csr_matrix
r=(Path(__file__).resolve().parents[2]/'outputs/images/A_MARCEAU/gaussian_editable');stage=r/'rendered_scene/object_scene';cache=r/'rendered_mask_support';manifest=json.loads((stage/'detection_manifest.json').read_text());nodes=[];bylabel=defaultdict(list);forbidden=[];start=time.monotonic()
for view in manifest['views']:
 record=json.loads((stage/'detections'/f'{view}.json').read_text());data=np.load(cache/f'{view}.npz');packed=np.load(stage/'detections'/f'{view}.npz');h,w=map(int,packed['shape']);local=defaultdict(list)
 for obs in record['instances']:
  support=data[f"instance_{obs['index']}"]
  if len(support)<20:continue
  index=len(nodes);label=obs['label'];stride=32 if label=='building' else 8 if label=='tree' else 1;sample=support[support%stride==0];nodes.append(dict(index=index,label=label,sample=sample,support_count=len(support),observation=dict(view=view,detection_index=obs['index'],label=label,score=obs['score'],pixels=obs['pixels'],bbox=obs['bbox'])));bylabel[label].append(index);local[label].append(index);forbidden.append(set())
 for ids in local.values():
  for i,a in enumerate(ids):
   ao=nodes[a]['observation'];am=np.unpackbits(packed['masks_packed'][ao['detection_index']],count=h*w).astype(bool)
   for b in ids[i+1:]:
    bo=nodes[b]['observation'];bm=np.unpackbits(packed['masks_packed'][bo['detection_index']],count=h*w).astype(bool);overlap=np.count_nonzero(am&bm)/min(ao['pixels'],bo['pixels'])
    if overlap<.15:forbidden[a].add(b);forbidden[b].add(a)
print('MASK_GRAPH_NODES',len(nodes),'cannot_links',sum(map(len,forbidden))//2,flush=True)
parent=list(range(len(nodes)));members=[{i} for i in range(len(nodes))];merges=[];rejected=0

def find(i):
 while parent[i]!=i:parent[i]=parent[parent[i]];i=parent[i]
 return i
for label,ids in bylabel.items():
 lengths=np.array([len(nodes[i]['sample']) for i in ids]);row=np.repeat(np.arange(len(ids)),lengths);col=np.concatenate([nodes[i]['sample'] for i in ids]);matrix=csr_matrix((np.ones(len(col),np.int32),(row,col)),shape=(len(ids),json.loads((r/'source_manifest.json').read_text())['gaussians']));overlap=(matrix@matrix.T).tocoo();edges=[];minimum=4 if label=='building' else 5 if label=='tree' else 12
 for a,b,count in zip(overlap.row,overlap.col,overlap.data):
  if a>=b or count<minimum:continue
  fraction=count/min(lengths[a],lengths[b]);iou=count/(lengths[a]+lengths[b]-count)
  if fraction>=.4:edges.append((.7*fraction+.3*iou,ids[a],ids[b]))
 print('MASK_GRAPH_EDGES',label,len(edges),round(time.monotonic()-start),flush=True)
 for score,a,b in sorted(edges,reverse=True):
  aa,bb=find(a),find(b)
  if aa==bb:continue
  if members[aa]&forbidden[bb] or members[bb]&forbidden[aa]:rejected+=1;continue
  if len(members[aa])<len(members[bb]):aa,bb=bb,aa
  parent[bb]=aa;members[aa]|=members[bb];forbidden[aa]|=forbidden[bb];members[bb]=set();forbidden[bb]=set();merges.append((a,b))
groups=defaultdict(list)
for node in nodes:groups[find(node['index'])].append(node)
objects=[]
for group in sorted(groups.values(),key=lambda group:min(node['index'] for node in group)):
 observations=[node['observation'] for node in group];views={o['view'] for o in observations}
 if len(views)<3:continue
 label=group[0]['label'];canonical=min(node['index'] for node in group);objects.append(dict(id=len(objects)+1,name=f"{label.replace(' ','_')}_{canonical:04d}",label=label,members=[node['index'] for node in group],distinct_views=len(views),observations=observations))
old=r/'rendered_gaussian_instances.json';backup=r/'greedy_gaussian_instances.json'
if old.exists() and not backup.exists():backup.write_bytes(old.read_bytes())
report=dict(views=len(manifest['views']),objects=objects,rejected_conflicting_merges=rejected,observation_nodes=len(nodes),method='Individual mask graph over shared exact Gaussian contributions, with non-overlapping same-view instance cannot-links. No output Gaussian is sampled or discarded.');old.write_text(json.dumps(report,indent=2));print('CONSTRAINED_MASK_GRAPH_COMPLETE',len(objects),'rejected',rejected,flush=True)
