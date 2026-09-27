import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { GLTFLoader } from "three/addons/loaders/GLTFLoader.js";
const $ = (s) => document.querySelector(s),
  viewport = $("#viewport");
let renderer, camera, controls, scene, model, runId, sourceUrl;
window.scenePreview = { ready: false };
function render() {
  if (renderer) renderer.render(scene, camera);
}
function clearModel() {
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
  scene = new THREE.Scene();
  camera = new THREE.PerspectiveCamera(45, 1, 0.01, 1000);
  scene.add(new THREE.HemisphereLight(0xe5f3ff, 0x647083, 3));
  const light = new THREE.DirectionalLight(0xffffff, 3);
  light.position.set(-3, 5, -4);
  scene.add(light);
  controls = new OrbitControls(camera, renderer.domElement);
  controls.addEventListener("change", render);
  new ResizeObserver(() => {
    const { width, height } = viewport.getBoundingClientRect();
    renderer.setSize(width, height);
    camera.aspect = width / height;
    camera.updateProjectionMatrix();
    render();
  }).observe(viewport);
}
async function showScene(meta) {
  if (!renderer) initViewer();
  clearModel();
  $("#empty").hidden = true;
  $("#scene-summary").textContent = "Loading scene...";
  const gltf = await new GLTFLoader().loadAsync(
    `/runs/${runId}/${meta.scene_asset}`,
  );
  model = gltf.scene;
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
  const distance = Math.max(size.length() * 1.35, 0.5);
  camera.near = distance / 1000;
  camera.far = distance * 100;
  camera.updateProjectionMatrix();
  camera.position
    .copy(center)
    .add(new THREE.Vector3(-0.25 * distance, 0.22 * distance, -distance));
  controls.target.copy(center);
  controls.update();
  render();
  const objects = meta.objects.filter((o) => o.status === "generated");
  $("#objects").replaceChildren();
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
    const id = document.createElement("small");
    id.textContent = obj.id.slice(-2);
    row.append(check, name, id);
    $("#objects").append(row);
  }
  $("#object-count").textContent = objects.length;
  $("#scene-summary").textContent = `${objects.length} independent objects`;
  const link = $("#export");
  link.href = `/runs/${runId}/scene.glb?download`;
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
async function poll() {
  try {
    const response = await fetch(`/api/runs/${runId}`);
    if (!response.ok) throw new Error("Could not read generation status");
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
