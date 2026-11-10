// Input-integrity gate for the A0-01b measurement. A measurement whose inputs are not the reference inputs is
// not a measurement of "WASM vs native", so any mismatch throws and the page / runner report an error, never a result.

export async function sha256Bytes(bytes) {
  const d = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(d)].map((b) => b.toString(16).padStart(2, "0")).join("");
}

/**
 * The model the page loaded must be byte-identical to the reference model: the sha256 of the served file must equal
 * manifest.model_sha256 (hash of the file the native run used) and manifest.legacy_model_hash (the legacy-v0
 * traj_8000.json `model_hash`).
 */
export function checkModelHash(modelSha256, manifest) {
  const problems = [];
  if (modelSha256 !== manifest.model_sha256) problems.push(`served model sha256 ${modelSha256} != manifest.model_sha256 ${manifest.model_sha256}`);
  if (modelSha256 !== manifest.legacy_model_hash) problems.push(`served model sha256 ${modelSha256} != legacy model_hash ${manifest.legacy_model_hash}`);
  if (problems.length) throw new Error("model integrity: " + problems.join("; "));
}

/** The native reference trajectory actually fetched (float64 bytes of one scenario) must hash to the manifest's `qpos_sha256`. */
export function checkReferenceHash(scenarioId, fetchedSha256, manifestSha256) {
  if (typeof manifestSha256 !== "string" || fetchedSha256 !== manifestSha256) {
    throw new Error(`reference integrity: scenario ${scenarioId} native qpos sha256 ${fetchedSha256} != manifest ${manifestSha256}`);
  }
}

/** Every scenario that has controls: the rebuilt control schedule's hash must equal the native reference's `ctrl_sha256`. */
export function checkControlHash(scenarioId, wasmCtrlSha256, nativeCtrlSha256) {
  if (typeof nativeCtrlSha256 !== "string" || wasmCtrlSha256 !== nativeCtrlSha256) {
    throw new Error(`control integrity: scenario ${scenarioId} control sha256 ${wasmCtrlSha256} != native ${nativeCtrlSha256}`);
  }
}
