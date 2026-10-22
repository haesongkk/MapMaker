"""Join unmodified GLB buffers under official pose nodes with bounded memory."""
import copy
import json
import struct
from pathlib import Path

import numpy as np
from trimesh.transformations import quaternion_from_matrix


def read_header(path):
    with Path(path).open('rb') as stream:
        magic, version, length = struct.unpack('<4sII', stream.read(12))
        if magic != b'glTF' or version != 2 or length != Path(path).stat().st_size:
            raise ValueError('Invalid source GLB header')
        size, kind = struct.unpack('<II', stream.read(8))
        if kind != 0x4E4F534A or size > 32*1024**2:
            raise ValueError('Invalid GLB JSON chunk')
        document = json.loads(stream.read(size))
        size, kind = struct.unpack('<II', stream.read(8))
        if kind != 0x004E4942 or stream.tell()+size != length:
            raise ValueError('Expected one embedded binary GLB chunk')
        return document, stream.tell(), size


def assemble_streamed(run, objects, *, matrix_for_pose=None):
    if matrix_for_pose is None:
        from .scene_assembly import object_matrix
        matrix_for_pose = object_matrix
    arrays = ('accessors','bufferViews','meshes','materials','textures','images','samplers','nodes','cameras')
    result = {key: [] for key in arrays}
    result.update(asset={'version':'2.0','generator':'MapMaker lossless baseline assembly'},
                  scene=0,scenes=[{'nodes':[0]}],buffers=[{'byteLength':0}])
    result['nodes']=[{'name':'Scene','children':[]}]
    chunks=[]; binary_size=0; checks=[]; geometry_nodes=0
    for obj in objects:
        path=Path(run)/obj['asset']; source,offset,size=read_header(path)
        if source.get('skins') or source.get('animations') or source.get('extensionsRequired'):
            raise ValueError('Unsupported animated/compressed source GLB')
        if len(source.get('buffers',[]))!=1 or source['buffers'][0].get('uri'):
            raise ValueError('Expected one embedded source buffer')
        bases={key:len(result[key]) for key in arrays}
        matrix=np.asarray(matrix_for_pose(obj['pose']),dtype=float)
        if matrix.shape!=(4,4) or not np.isfinite(matrix).all():
            raise ValueError('Invalid official pose matrix')
        # Copy JSON only; vertex/index/texture payloads stay on disk until export.
        source=copy.deepcopy(source)
        for view in source.get('bufferViews',[]):
            if view.get('buffer',0)!=0:raise ValueError('Unexpected buffer reference')
            view['byteOffset']=view.get('byteOffset',0)+binary_size
        for accessor in source.get('accessors',[]):
            if 'bufferView' in accessor:accessor['bufferView']+=bases['bufferViews']
            for field in ('indices','values'):
                if field in accessor.get('sparse',{}):accessor['sparse'][field]['bufferView']+=bases['bufferViews']
        for image in source.get('images',[]):
            if 'uri' in image:raise ValueError('External image is not embedded')
            image['bufferView']+=bases['bufferViews']
        for texture in source.get('textures',[]):
            if 'source' in texture:texture['source']+=bases['images']
            if 'sampler' in texture:texture['sampler']+=bases['samplers']
        def remap_textures(value):
            if isinstance(value,dict):
                for key,item in value.items():
                    if key.endswith('Texture') and isinstance(item,dict) and 'index' in item:
                        item['index']+=bases['textures']
                    remap_textures(item)
            elif isinstance(value,list):
                for item in value:remap_textures(item)
        for material in source.get('materials',[]):remap_textures(material)
        for mesh in source.get('meshes',[]):
            for primitive in mesh['primitives']:
                primitive['attributes']={k:v+bases['accessors'] for k,v in primitive['attributes'].items()}
                for target in primitive.get('targets',[]):
                    for key in target:target[key]+=bases['accessors']
                if 'indices' in primitive:primitive['indices']+=bases['accessors']
                if 'material' in primitive:primitive['material']+=bases['materials']
        for index,node in enumerate(source.get('nodes',[])):
            node['name']=f"{obj['id']}__{index}"
            if 'mesh' in node:node['mesh']+=bases['meshes'];geometry_nodes+=1
            if 'camera' in node:node['camera']+=bases['cameras']
            if 'children' in node:node['children']=[n+bases['nodes'] for n in node['children']]
        for key in arrays:result[key].extend(source.get(key,[]))
        root=len(result['nodes'])
        result['nodes'].append(dict(name=obj['id'],matrix=matrix.T.reshape(-1).tolist(),
            children=[n+bases['nodes'] for n in source['scenes'][source.get('scene',0)]['nodes']]))
        result['nodes'][0]['children'].append(root)
        scale=np.linalg.norm(matrix[:3,:3],axis=0)
        if np.any(scale<=0):raise ValueError('Invalid pose scale')
        rotation=np.eye(4);rotation[:3,:3]=matrix[:3,:3]/scale[None,:]
        obj['transform']=dict(position=matrix[:3,3].tolist(),rotation_quaternion_wxyz=quaternion_from_matrix(rotation).tolist(),
            scale=scale.tolist(),matrix=matrix.tolist(),matrix_convention='column vectors; official pose composed with inverse GLB export axis rotation')
        checks.append(dict(object=obj['id'],official_pose_matrix_used=True,source_binary_bytes_preserved=size))
        for extension in source.get('extensionsUsed',[]):
            if extension not in result.setdefault('extensionsUsed',[]):result['extensionsUsed'].append(extension)
        chunks.append((path,offset,size));binary_size+=size
    result['buffers'][0]['byteLength']=binary_size
    result={key:value for key,value in result.items() if value!=[]}
    encoded=json.dumps(result,separators=(',',':'),allow_nan=False).encode('utf-8')
    encoded+=b' '*((-len(encoded))%4)
    total=12+8+len(encoded)+8+binary_size
    if total>=2**32:raise ValueError('Combined scene exceeds the GLB 4 GiB format limit')
    target=Path(run)/'scene.glb';temporary=target.with_suffix('.glb.part')
    with temporary.open('wb') as output:
        output.write(struct.pack('<4sII',b'glTF',2,total));output.write(struct.pack('<II',len(encoded),0x4E4F534A));output.write(encoded)
        output.write(struct.pack('<II',binary_size,0x004E4942))
        for path,offset,size in chunks:
            with path.open('rb') as source:
                source.seek(offset);remaining=size
                while remaining:
                    data=source.read(min(1024**2,remaining))
                    if not data:raise ValueError('Source GLB truncated during assembly')
                    output.write(data);remaining-=len(data)
    temporary.replace(target)
    return dict(independent_object_nodes=[o['id'] for o in objects],geometry_nodes=geometry_nodes,
                coordinate_validation=checks,method='official pose; original GLB buffers streamed without geometry edits')
