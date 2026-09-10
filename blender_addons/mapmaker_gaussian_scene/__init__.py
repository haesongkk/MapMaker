"""Synchronize object-owned Gaussian data with ordinary Blender editing."""
bl_info = {'name': 'MapMaker Gaussian Scene', 'author': 'MapMaker',
           'version': (0, 3, 0), 'blender': (4, 5, 0), 'category': '3D View'}
import bpy
import numpy as np
from bpy.app.handlers import persistent

_last = None
_dirty = set()
_arrays = {}


def material_tint(obj):
    material = obj.active_material
    if material is None:
        return (1., 1., 1., 1.)
    if material.use_nodes:
        for node in material.node_tree.nodes:
            if node.type == 'BSDF_PRINCIPLED':
                color = node.inputs['Base Color'].default_value
                return (*color[:3], node.inputs['Alpha'].default_value)
    return tuple(material.diffuse_color)


def pack(obj):
    mesh = obj.data
    n = len(mesh.vertices)
    array = np.zeros((n, 59), np.float32)
    xyz = np.empty(n * 3, np.float32)
    mesh.vertices.foreach_get('co', xyz)
    array[:, :3] = xyz.reshape(n, 3)

    def attr(name):
        values = np.empty(n, np.float32)
        mesh.attributes[name].data.foreach_get('value', values)
        return values

    array[:, 3:7] = np.column_stack([attr('rot_' + str(i)) for i in range(4)])
    array[:, 3:7] /= np.maximum(np.linalg.norm(array[:, 3:7], axis=1, keepdims=True), 1e-12)
    array[:, 7:10] = np.exp(np.column_stack([attr('scale_' + str(i)) for i in range(3)]))
    array[:, 10] = 1 / (1 + np.exp(-attr('opacity')))
    array[:, 11:14] = np.column_stack([attr('f_dc_' + str(i)) for i in range(3)])
    names = sorted([a.name for a in mesh.attributes if a.name.startswith('f_rest_')],
                   key=lambda name: int(name[7:]))
    if names:
        rest = np.column_stack([attr(name) for name in names])
        array[:, 14:14 + len(names)] = rest.reshape(n, 3, -1).transpose(0, 2, 1).reshape(n, -1)
    tint = material_tint(obj)
    if tint != (1., 1., 1., 1.):
        rgb_tint = np.asarray(tint[:3], np.float32)
        constant = .28209479177387814
        array[:, 11:14] = ((array[:, 11:14] * constant + .5) * rgb_tint - .5) / constant
        if names:
            array[:, 14:14 + len(names)] *= np.tile(rgb_tint, len(names) // 3)
        array[:, 10] *= tint[3]
    obj['mapmaker_packed_tint'] = tint
    obj['gaussian_count'] = n
    obj['sh_degree'] = 3 + len(names)
    # Packed binary ID properties can be corrupted by native duplication.
    # Mesh vertices/attributes are the sole persistent source of truth.
    if 'gaussian_data' in obj:
        del obj['gaussian_data']
    _arrays[obj.as_pointer()] = (obj.data.as_pointer(), array)
    return array


def stop_drawing():
    if hasattr(bpy, 'gaussian_draw_handle'):
        try:
            bpy.types.SpaceView3D.draw_handler_remove(bpy.gaussian_draw_handle, 'WINDOW')
        except (ValueError, ReferenceError):
            pass
        del bpy.gaussian_draw_handle


def refresh(render=False):
    import dgs_render_by_kiri_engine as backend
    objects = [obj for obj in bpy.context.scene.objects
               if obj.get('mapmaker_gaussian') and
               (not obj.hide_render if render else obj.visible_get())]
    cache = {}
    live_pointers = {obj.as_pointer() for obj in objects}
    for pointer in list(_arrays):
        if pointer not in live_pointers:
            del _arrays[pointer]
    for obj in objects:
        if obj.mode == 'EDIT':
            continue
        n = len(obj.data.vertices)
        tint_changed = tuple(obj.get('mapmaker_packed_tint', (1., 1., 1., 1.))) != material_tint(obj)
        stored = _arrays.get(obj.as_pointer())
        if (obj.name in _dirty or obj.get('gaussian_count') != n or
                stored is None or stored[0] != obj.data.as_pointer() or tint_changed):
            array = pack(obj)
        else:
            array = stored[1]
        if n:
            cache[obj.name] = {'object': obj, 'gaussian_data': array,
                               'gaussian_count': n, 'sh_degree': obj.get('sh_degree', 48)}
    bpy.gaussian_object_cache = cache
    _dirty.clear()
    bpy.gaussian_global_needs_update = True
    if cache:
        if not hasattr(bpy, 'gaussian_quad_shader'):
            backend.sna_shader_system_A4AED()
        backend.sna_texture_creation_FD1B2()
    else:
        # The upstream renderer otherwise reconstructs hidden objects from bytes.
        stop_drawing()
        bpy.gaussian_count = 0
    return len(cache)


def signature():
    return tuple((obj.name, obj.as_pointer(), obj.visible_get(), obj.hide_render,
                  obj.mode, len(obj.data.vertices), material_tint(obj))
                 for obj in bpy.context.scene.objects if obj.get('mapmaker_gaussian'))


def tick():
    global _last
    if not bpy.context.scene.get('mapmaker_gaussian_scene'):
        return 1.
    current = signature()
    if current != _last or _dirty:
        try:
            count = refresh()
            _last = current
            if count:
                import dgs_render_by_kiri_engine as backend
                backend.sna_viewport_render_A3941()
            for screen in bpy.data.screens:
                for area in screen.areas:
                    if area.type == 'VIEW_3D':
                        area.tag_redraw()
        except Exception as error:
            print('MapMaker Gaussian refresh:', repr(error))
    return .5


@persistent
def changed(scene, depsgraph):
    for update in depsgraph.updates:
        obj = update.id
        if isinstance(obj, bpy.types.Object) and obj.get('mapmaker_gaussian') and update.is_updated_geometry:
            _dirty.add(obj.name)
        elif isinstance(obj, bpy.types.Mesh):
            for owner in scene.objects:
                if owner.get('mapmaker_gaussian') and owner.data.original == obj.original:
                    _dirty.add(owner.name)


@persistent
def before_load(_):
    stop_drawing()
    bpy.gaussian_object_cache = {}
    _arrays.clear()


@persistent
def loaded(_):
    global _last
    _last = None
    _dirty.clear()
    _arrays.clear()
    if not bpy.app.background and not bpy.app.timers.is_registered(tick):
        bpy.app.timers.register(tick, first_interval=1.)


def register():
    for handlers, callback in [(bpy.app.handlers.load_pre, before_load),
                               (bpy.app.handlers.load_post, loaded),
                               (bpy.app.handlers.depsgraph_update_post, changed)]:
        if callback not in handlers:
            handlers.append(callback)
    loaded(None)


def unregister():
    for handlers, callback in [(bpy.app.handlers.load_pre, before_load),
                               (bpy.app.handlers.load_post, loaded),
                               (bpy.app.handlers.depsgraph_update_post, changed)]:
        if callback in handlers:
            handlers.remove(callback)
    if bpy.app.timers.is_registered(tick):
        bpy.app.timers.unregister(tick)
    stop_drawing()
