import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
const $ = (s) => document.querySelector(s),
  viewport = $("#viewport");
let renderer, camera, controls, scene, model, runId, sourceUrl;
let grid, axisCanvas;
let sceneDownloadUrl;
let autoFrameModel = true;
function fitSceneCamera() {
  if (!model) return;
  const box = new THREE.Box3().setFromObject(model);
  if (box.isEmpty()) return;
  const center = box.getCenter(new THREE.Vector3());
  const direction = new THREE.Vector3(-0.25, 0.22, -1).normalize();
  const right = new THREE.Vector3().crossVectors(camera.up, direction).normalize();
  const up = new THREE.Vector3().crossVectors(direction, right);
  const tangentY = Math.tan(THREE.MathUtils.degToRad(camera.fov / 2));
  const tangentX = tangentY * Math.max(camera.aspect, 0.001);
  let distance = 0.5;
  for (const x of [box.min.x, box.max.x])
    for (const y of [box.min.y, box.max.y])
      for (const z of [box.min.z, box.max.z]) {
        const offset = new THREE.Vector3(x, y, z).sub(center);
        distance = Math.max(distance, offset.dot(direction) + 1.12 * Math.max(
          Math.abs(offset.dot(right)) / tangentX, Math.abs(offset.dot(up)) / tangentY));
      }
  camera.near = distance / 1000;
  camera.far = distance * 100;
  camera.updateProjectionMatrix();
  camera.position.copy(center).addScaledVector(direction, distance);
  controls.target.copy(center);
  controls.update();
}
async function loadSceneBytes(url, size) {
  const parts = [];
  const chunk = 8 * 1024 * 1024;
  for (let start = 0; start < size; start += chunk) {
    const end = Math.min(start + chunk, size) - 1;
    let response;
    for (let attempt = 0; attempt < 4; attempt++) {
      try {
        response = await fetch(url, { headers: { Range: `bytes=${start}-${end}` } });
        if (response.ok) break;
      } catch (error) { if (attempt === 3) throw error; }
      await new Promise(resolve => setTimeout(resolve, 1500));
    }
    if (!response?.ok) throw new Error('Could not download scene');
    const data = await response.arrayBuffer();
    if (data.byteLength !== end - start + 1) throw new Error('Incomplete scene download');
    parts.push(data);
  }
  return new Blob(parts, { type: 'model/gltf-binary' });
}
function drawAxes() {
  if (!axisCanvas) return;
  const ctx = axisCanvas.getContext('2d');
  ctx.clearRect(0, 0, 112, 112);
  ctx.fillStyle = '#101b2bd9';
  ctx.beginPath(); ctx.arc(56, 56, 51, 0, Math.PI * 2); ctx.fill();
  const inverse = camera.quaternion.clone().invert();
  const axes = [
    ['X', '#ff7777', new THREE.Vector3(1, 0, 0)],
    ['Y', '#85e6a0', new THREE.Vector3(0, 1, 0)],
    ['Z', '#7bb8ff', new THREE.Vector3(0, 0, 1)],
  ].map(([label, color, vector]) => ({ label, color, v: vector.applyQuaternion(inverse) }));
  ctx.font = 'bold 13px system-ui'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
  for (const {label, color, v} of axes.sort((a, b) => a.v.z - b.v.z)) {
    ctx.strokeStyle = color; ctx.fillStyle = color; ctx.lineWidth = 2;
    ctx.setLineDash([3, 4]); ctx.globalAlpha = .4;
    ctx.beginPath(); ctx.moveTo(56, 56); ctx.lineTo(56-v.x*27, 56+v.y*27); ctx.stroke();
    ctx.globalAlpha = 1; ctx.setLineDash([]);
    ctx.beginPath(); ctx.moveTo(56, 56); ctx.lineTo(56+v.x*30, 56-v.y*30); ctx.stroke();
    ctx.fillText(label, 56+v.x*41, 56-v.y*41);
  }
}
window.scenePreview = { ready: false };
function render() {
  if (renderer) renderer.render(scene, camera);
  if (camera) drawAxes();
}
function clearModel() {
  if (grid) {
    scene.remove(grid); grid.geometry.dispose(); grid.material.dispose(); grid = null;
  }
  if (!model) return;
  scene.remove(model);
  model.traverse((o) => {
    o.geometry?.dispose();
    for (const m of [o.material].flat().filter(Boolean)) {
      for (const value of Object.values(m)) {
        if (value?.isTexture) value.dispose();
      }
      m.dispose();
    }
  });
  model = null;
  render();
}
function initViewer() {
  renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 2));
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  viewport.append(renderer.domElement);
  axisCanvas = document.createElement('canvas');
  axisCanvas.width = axisCanvas.height = 112;
  axisCanvas.className = 'axis-indicator';
  axisCanvas.setAttribute('role', 'img');
  axisCanvas.setAttribute('aria-label', 'World axes: X red, Y green, Z blue. Solid lines indicate positive directions.');
  viewport.append(axisCanvas);
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
  scene.add(new THREE.HemisphereLight(0xe5f3ff, 0x647083, 3));
  const light = new THREE.DirectionalLight(0xffffff, 3);
  light.position.set(-3, 5, -4);
  scene.add(light);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.addEventListener("start", () => { autoFrameModel = false; });
  controls.addEventListener("change", render);
  new ResizeObserver(() => {
    const { width, height } = viewport.getBoundingClientRect();
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    if (autoFrameModel) fitSceneCamera();
    render();
  }).observe(viewport);
}
async function showScene(meta) {
  if (!renderer) initViewer();
  clearModel();
  autoFrameModel = true;
  $("#empty").hidden = true;
  $("#scene-summary").textContent = "Loading scene...";
  const assetPath = `/runs/${runId}/${meta.scene_asset}`;
  if (sceneDownloadUrl) URL.revokeObjectURL(sceneDownloadUrl);
  sceneDownloadUrl = null;
  let gltf;
  if (meta.scene_bytes) {
    const blob = await loadSceneBytes(assetPath, meta.scene_bytes);
    sceneDownloadUrl = URL.createObjectURL(blob);
    gltf = await new GLTFLoader().parseAsync(await blob.arrayBuffer(), '');
  } else {
    gltf = await new GLTFLoader().loadAsync(meta.scene_url || assetPath);
  }
  model = gltf.scene;
  // Older saved scenes may contain the former generated slab.
  const oldFloor = model.getObjectByName('background_floor');
  if (oldFloor) oldFloor.removeFromParent();
  scene.add(model);
  model.traverse((o) => {
    if (o.isMesh && o.material) {
      for (const m of [o.material].flat()) {
        m.metalness = 0;
        m.roughness = 0.85;
      }
    }
  });
  const box = new THREE.Box3().setFromObject(model),
    center = box.getCenter(new THREE.Vector3()),
    size = box.getSize(new THREE.Vector3());
  const span = Math.max(size.x, size.z, 0.1) * 1.8;
  const step = 10 ** Math.floor(Math.log10(span / 20));
  const divisions = Math.ceil(span / step);
  grid = new THREE.GridHelper(divisions * step, divisions, 0x536e87, 0x314458);
  grid.name = 'viewer_ground_grid';
  grid.position.set(Math.round(center.x / step) * step, 0, Math.round(center.z / step) * step);
  grid.material.transparent = true;
  grid.material.opacity = .55;
  grid.material.depthWrite = false;
  scene.add(grid);
  fitSceneCamera();
  render();
  const objects = meta.objects.filter((o) => o.status === "generated");
  $("#objects").replaceChildren();
  const surfaces = meta.structure?.surfaces || [];
  if (surfaces.length) {
    const row = document.createElement('label');
    row.className = 'object-row';
    const check = document.createElement('input');
    check.type = 'checkbox'; check.checked = true; check.id = 'show-room';
    const label = document.createElement('span'); label.textContent = 'Room surfaces';
    const cutaway = document.createElement('button');
    cutaway.type = 'button'; cutaway.id = 'room-cutaway'; cutaway.textContent = 'Cutaway';
    let cut = false;
    const kinds = { floor: true, wall: true, ceiling: true, observed: true };
    const update = () => {
      for (const surface of surfaces) {
        const node = model.getObjectByName(surface.node);
        if (node) node.visible = check.checked && kinds[surface.kind] && (!cut || surface.kind === 'floor');
      }
      cutaway.setAttribute('aria-pressed', String(cut));
      render();
    };
    check.addEventListener('change', update);
    cutaway.addEventListener('click', () => { cut = !cut; update(); });
    row.append(check, label); $("#objects").append(row, cutaway);
    for (const kind of ['floor', 'wall', 'ceiling', 'observed']) {
      const group = surfaces.filter(s => s.kind === kind);
      if (!group.length) continue;
      const item = document.createElement('label'); item.className = 'object-row';
      const toggle = document.createElement('input'); toggle.type = 'checkbox'; toggle.checked = true;
      toggle.dataset.surfaceKind = kind;
      toggle.addEventListener('change', () => {
        kinds[kind] = toggle.checked; update();
      });
      const text = document.createElement('span'); text.textContent = kind === 'observed' ? 'Observed context' : kind;
      item.append(toggle, text); $("#objects").append(item);
    }
    update();
  }
  for (const obj of objects) {
    const node = model.getObjectByName(obj.id);
    if (!node) throw new Error(`Scene node missing: ${obj.id}`);
    const row = document.createElement("label");
    row.className = "object-row";
    const check = document.createElement("input");
    check.type = "checkbox";
    check.checked = true;
    check.dataset.objectId = obj.id;
    check.addEventListener("change", () => {
      node.visible = check.checked;
      render();
    });
    const name = document.createElement("span");
    name.textContent = obj.name;
    if (obj.geometry_source === 'observed_mask_residual') {
      name.title = 'Visible surface from the image; hidden shape is unknown';
      const detail = document.createElement('small');
      detail.textContent = 'observed surface';
      name.append(document.createElement('br'), detail);
    }
    const id = document.createElement("small");
    id.textContent = obj.id.slice(-2);
    row.append(check, name, id);
    $("#objects").append(row);
  }
  $("#object-count").textContent = objects.length;
  $("#scene-summary").textContent = `${objects.length} independent objects · ${surfaces.length ? surfaces.length + ' observed room patches' : 'Grid Y=0'}`;
  const link = $("#export");
  link.href = sceneDownloadUrl || `/runs/${runId}/scene.glb?download`;
  link.download = "scene.glb";
  link.classList.remove("disabled");
  link.setAttribute("aria-disabled", "false");
  window.scenePreview = {
    ready: true,
    model,
    camera,
    controls,
    renderer,
    scene,
    grid,
    runId,
  };
}
$("#image").addEventListener("change", () => {
  const file = $("#image").files[0];
  if (!file) return;
  if (sourceUrl) URL.revokeObjectURL(sourceUrl);
  sourceUrl = URL.createObjectURL(file);
  $("#source-preview").src = sourceUrl;
  $("#source-preview").hidden = false;
  $("#upload-hint").hidden = true;
  $("#generate").disabled = false;
  $("#status").textContent = "Ready to generate";
});
const stages = {
  queued: 0,
  analyzing: 1,
  segmenting: 2,
  segmented: 2,
  loading: 3,
  reconstructing: 3,
  assembling: 4,
  exporting: 5,
  done: 6,
};
let statusFailures = 0;
async function poll() {
  try {
    const response = await fetch(`/api/runs/${runId}`);
    if ([429, 502, 503, 504].includes(response.status) && statusFailures++ < 12) {
      $("#status").textContent = "Reconnecting to server...";
      setTimeout(poll, 5000);
      return;
    }
    if (!response.ok) throw new Error("Could not read generation status");
    statusFailures = 0;
    const state = await response.json();
    $("#status").textContent = state.message;
    $("#progress").value = stages[state.stage] ?? 0;
    $("#detail").textContent =
      state.stage === "loading"
        ? "Preparing the model for its first generation."
        : state.object_id || "";
    document.body.dataset.stage = state.stage;
    document.body.dataset.runId = runId;
    if (state.stage === "failed") throw new Error(state.message);
    if (state.stage === "done") {
      $("#warnings").textContent = state.metadata.errors.length
        ? `${state.metadata.errors.length} processing issue(s); see scene_metadata.json for details.`
        : "";
      await showScene(state.metadata);
      $("#generate").disabled = !$("#image").files.length;
      $("#image").disabled = false;
      return;
    }
    setTimeout(poll, 1500);
  } catch (error) {
    $("#status").textContent = error.message;
    $("#generate").disabled = !$("#image").files.length;
    $("#image").disabled = false;
    $("#scene-summary").textContent = "Generation failed";
    $("#empty p").textContent = "Generation stopped. Select an image to try again.";
    document.body.dataset.stage = "failed";
    console.error(error);
  }
}
$("#generate").addEventListener("click", async () => {
  const file = $("#image").files[0];
  if (!file) return;
  $("#generate").disabled = true;
  $("#image").disabled = true;
  $("#export").classList.add("disabled");
  $("#export").setAttribute("aria-disabled", "true");
  $("#warnings").textContent = "";
  $("#status").textContent = "Uploading image...";
  window.scenePreview.ready = false;
  clearModel();
  $("#objects").replaceChildren();
  $("#object-count").textContent = "0";
  $("#scene-summary").textContent = "Generating...";
  $("#empty").hidden = false;
  $("#empty p").textContent =
    "Your scene is being generated. Follow the stages on the left.";
  try {
    const response = await fetch("/api/runs", {
      method: "POST",
      headers: { "Content-Type": file.type || "application/octet-stream" },
      body: file,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error);
    runId = data.run_id;
    history.replaceState(null, "", `?run=${runId}`);
    await poll();
  } catch (error) {
    $("#status").textContent = error.message;
    $("#generate").disabled = false;
    $("#image").disabled = false;
    $("#scene-summary").textContent = "Generation failed";
    $("#empty p").textContent = "Generation stopped. Select an image to try again.";
    document.body.dataset.stage = "failed";
  }
});

// Also useful for read-only validation of a running job without launching it twice.
export function watchRun(id) {
  runId = id;
  $("#generate").disabled = true;
  $("#image").disabled = true;
  $("#scene-summary").textContent = "Generating...";
  $("#empty p").textContent = "Your scene is being generated. Follow the stages on the left.";
  return poll();
}

// Reopen a long-running or completed scene without submitting another GPU job.
const savedRun = new URLSearchParams(location.search).get("run");
if (/^[a-f0-9]{32}$/.test(savedRun || "")) {
  $("#source-preview").src = `/runs/${savedRun}/input/source_image.png`;
  $("#source-preview").hidden = false;
  $("#upload-hint").hidden = true;
  watchRun(savedRun);
}
