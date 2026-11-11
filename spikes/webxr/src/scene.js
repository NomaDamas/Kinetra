// The one part and how it is grabbed. Shared by the browser page (app.js) and the offline Node test, so the geometry and
// the handle options that the emulator run exercises are the same ones the offline test checks.
import { BoxGeometry, Mesh, MeshBasicMaterial } from "three";
import { HandleStore } from "@pmndrs/handle";

/** Part: a 0.2 m cube (a stand-in for one assembly part), 1.2 m above the floor, a little right of and in front of the origin. */
export const PART = Object.freeze({ size: 0.2, start: Object.freeze([0.25, 1.2, -0.4]), color: 0x3b82f6 });

export function createPart() {
  const part = new Mesh(new BoxGeometry(PART.size, PART.size, PART.size), new MeshBasicMaterial({ color: PART.color }));
  part.position.set(...PART.start);
  part.name = "part";
  return part;
}

/**
 * Make `part` movable by a grab pointer only (controller squeeze). `pointerEventsType: { allow: 'grab' }` keeps any ray
 * pointer (trigger) from moving it. rotate/scale are off: the part is translated, never rotated or scaled, so the final
 * position is exactly start + controller displacement. `onChange` is called with the handle state each time it is applied.
 */
export function makeGrabbable(part, onChange) {
  part.pointerEventsType = { allow: "grab" };
  const handle = new HandleStore(part, () => ({
    rotate: false,
    scale: false,
    multitouch: false,
    apply(state, target) {
      target.position.copy(state.current.position);
      onChange?.(state);
    },
  }));
  const unbind = handle.bind(part);
  return { handle, dispose: unbind };
}
