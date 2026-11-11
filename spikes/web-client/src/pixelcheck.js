/** First-frame check for the share page: the pixels at the car's projected position must be car-body red (chassis rgba 0.8 0.1 0.1
 *  after Lambert shading), not ground, sky or an empty canvas. `block` is a w x h RGBA readPixels block centred on the car;
 *  `corner` is one RGBA pixel far from the car (must NOT look like the car, so a canvas painted all red cannot pass). */
export const isCarRed = (r, g, b) => r > 60 && r > 1.8 * g && r > 1.8 * b;

export function checkFirstFrame(block, corner, minFraction = 0.5) {
  const n = block.length / 4;
  let red = 0;
  for (let i = 0; i < n; i++) if (isCarRed(block[i * 4], block[i * 4 + 1], block[i * 4 + 2])) red++;
  const cornerIsCar = isCarRed(corner[0], corner[1], corner[2]);
  return { ok: n > 0 && red / n >= minFraction && !cornerIsCar, red_fraction: n ? red / n : 0, corner_is_car_colored: cornerIsCar };
}
