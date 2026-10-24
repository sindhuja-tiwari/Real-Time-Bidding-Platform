"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * The "lava": a few thousand glowing embers drawn on one fixed canvas behind
 * the home page. Each section of the page names a shape with `data-lava="n"`.
 * As you scroll, the embers flow from one shape to the next in 3D, each on its
 * own slight delay, while the whole cloud turns a full revolution per section,
 * so every change of shape reads as the object rotating into its new form.
 *
 *   0  gavel      an auctioneer's gavel and block, right of the hero; it
 *                 strikes the block every time an auction is sold
 *   1  burst      the gavel blows outward from the middle of the screen
 *   2  stopwatch  left of "the field": speed wins; its hand keeps sweeping
 *   3  coins      right of the ledger: stacks of clearing prices
 *   4  lens       left of incidents: a magnifying glass, looking for causes
 *
 * Shapes alternate sides so the page reads in a zigzag with the copy.
 */

type Props = {
  /** The gavel is centred on this element and sized to it. */
  anchor: RefObject<HTMLElement>;
  /** Flip to true to burst the embers out from a single point. */
  start: boolean;
  /** Change this to make the gavel strike (e.g. on each auction). */
  pulse?: unknown;
  colors?: string[];
};

const FORMATIONS = 5;

type V3 = { x: number; y: number; z: number };
const rand = (a: number, b: number) => a + Math.random() * (b - a);
function ring(r: number) {
  const a = Math.random() * Math.PI * 2;
  return [Math.cos(a) * r, Math.sin(a) * r] as const;
}

/*
 * The gavel, in its own units (y up). The handle runs up the y axis from its
 * end at the origin; the head sits across the top with its axis along x. The
 * gavel turns about the handle end (PIVOT) by REST, and by STRIKE when it
 * hits the round block.
 */
const PIVOT = { x: 1.05, y: -0.45 };
const REST = 0.85;
const STRIKE = 1.46;
const MID = { x: -0.12, y: 0.08 };
const FIT = 0.64;

function gavelPoint(): V3 & { block: boolean } {
  const k = Math.random();
  if (k < 0.4) {
    const x = rand(-0.6, 0.6);
    const collar = Math.abs(Math.abs(x) - 0.42) < 0.05;
    const [y, z] = ring(collar ? 0.34 : 0.3);
    return { x, y: 1.9 + y, z, block: false };
  }
  if (k < 0.52) {
    const [y, z] = ring(0.3 * Math.sqrt(Math.random()));
    return { x: Math.random() < 0.5 ? -0.6 : 0.6, y: 1.9 + y, z, block: false };
  }
  if (k < 0.72) {
    const y = Math.random() * 1.6;
    const r = y < 0.12 ? 0.1 : 0.055 + 0.025 * (1 - y / 1.6);
    const [x, z] = ring(r);
    return { x, y, z, block: false };
  }
  const [x, z] = Math.random() < 0.55 ? ring(0.55 * Math.sqrt(Math.random())) : ring(0.55);
  const top = Math.hypot(x, z) < 0.54;
  return { x: -0.85 + x, y: -1.1 + (top ? 0.18 : Math.random() * 0.18), z, block: true };
}

/* Shapes below are in screen-like units: y points down, about unit radius. */

/** A stopwatch face-on: rim, ticks, crown, and two hands (hand > 0). */
function stopwatchPoint(): V3 & { hand: number; len: number } {
  const k = Math.random();
  const none = { hand: 0, len: 0 };
  if (k < 0.34) {
    // The case: a short cylinder.
    const [x, y] = ring(0.82);
    return { x, y: y + 0.1, z: rand(-0.12, 0.12), ...none };
  }
  if (k < 0.44) {
    // A thin bezel inside the rim.
    const [x, y] = ring(0.72);
    return { x, y: y + 0.1, z: 0.12, ...none };
  }
  if (k < 0.6) {
    // Twelve ticks; the one at 12 is longer.
    const i = Math.floor(Math.random() * 12);
    const a = (i / 12) * Math.PI * 2;
    const r = rand(i === 0 ? 0.48 : 0.56, 0.66);
    return { x: Math.sin(a) * r, y: 0.1 - Math.cos(a) * r, z: 0.12, ...none };
  }
  if (k < 0.7) {
    // Crown and its button on top.
    if (Math.random() < 0.6) {
      const [x, z] = ring(0.09);
      return { x, y: rand(-0.92, -0.74), z, ...none };
    }
    return { x: rand(-0.2, 0.2), y: rand(-1.0, -0.94), z: rand(-0.06, 0.06), ...none };
  }
  if (k < 0.75) {
    // A faint glass face.
    const [x, y] = ring(0.7 * Math.sqrt(Math.random()));
    return { x, y: y + 0.1, z: 0.13, ...none };
  }
  // The hands: 1 is the sweeping second hand, 2 the short minute hand.
  const hand = Math.random() < 0.6 ? 1 : 2;
  return { x: 0, y: 0, z: 0.14, hand, len: rand(-0.1, hand === 1 ? 0.62 : 0.4) };
}

/** Three stacks of coins of different heights, each coin drawn by its rims. */
const STACKS = [
  { x: -0.62, z: 0.05, n: 7 },
  { x: 0.18, z: 0.3, n: 4 },
  { x: 0.82, z: -0.15, n: 2 },
];
const COIN_R = 0.3;
function coinPoint(): V3 {
  const total = STACKS.reduce((s, c) => s + c.n, 0);
  let pick = Math.random() * total;
  const st = STACKS.find((c) => (pick -= c.n) < 0) ?? STACKS[0];
  const i = Math.floor(Math.random() * st.n);
  const wob = Math.sin(i * 2.3 + st.x * 5) * 0.035; // stacks are never quite straight
  const bottom = 0.8 - i * 0.17; // y down: the bottom coin sits lowest
  const top = bottom - 0.12;
  const k = Math.random();
  const last = i === st.n - 1;
  if (last && k < 0.35) {
    // The face of the top coin, with an inner ring like an embossed edge.
    const [x, z] = ring(Math.random() < 0.4 ? COIN_R * 0.78 : COIN_R * Math.sqrt(Math.random()));
    return { x: st.x + x + wob, y: top, z: st.z + z };
  }
  // Top and bottom rims, and a sparse milled side between them.
  const [x, z] = ring(COIN_R);
  const y = k < 0.7 ? top : k < 0.88 ? bottom : rand(top, bottom);
  return { x: st.x + x + wob, y, z: st.z + z };
}

/** A magnifying glass, tilted, its handle down and to the right. */
function lensPoint(): V3 {
  const k = Math.random();
  const c = { x: -0.18, y: -0.18 };
  if (k < 0.55) {
    // The rim: a torus.
    const a = Math.random() * Math.PI * 2;
    const b = Math.random() * Math.PI * 2;
    const r = 0.6 + 0.07 * Math.cos(b);
    return { x: c.x + Math.cos(a) * r, y: c.y + Math.sin(a) * r, z: 0.07 * Math.sin(b) };
  }
  if (k < 0.65) {
    // A glint of glass.
    const [x, y] = ring(0.55 * Math.sqrt(Math.random()));
    return { x: c.x + x, y: c.y + y, z: 0 };
  }
  // The handle, thicker away from the rim.
  const d = rand(0, 1);
  const len = 0.68 + d * 0.75;
  const [u, z] = ring(0.06 + 0.05 * d);
  const ax = Math.SQRT1_2;
  return { x: c.x + ax * len - ax * u, y: c.y + ax * len + ax * u, z };
}

export function LavaField({ anchor, start, pulse, colors = ["#dc5000", "#ff7a2f", "#ffb829", "#ffedd7"] }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null);
  const state = useRef({ start, startedAt: 0, pulseAt: -1e9 });

  useEffect(() => {
    if (start && !state.current.start) {
      state.current.start = true;
      state.current.startedAt = performance.now();
    }
  }, [start]);

  useEffect(() => {
    state.current.pulseAt = performance.now();
  }, [pulse]);

  useEffect(() => {
    const el = canvas.current;
    if (!el) return;
    const ctx = el.getContext("2d");
    if (!ctx) return;
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (state.current.start) state.current.startedAt = performance.now();

    // One soft glowing sprite per colour, drawn once and stamped many times.
    const SPRITE = 64;
    const sprites = colors.map((c) => {
      const s = document.createElement("canvas");
      s.width = s.height = SPRITE;
      const g = s.getContext("2d")!;
      const grad = g.createRadialGradient(SPRITE / 2, SPRITE / 2, 0, SPRITE / 2, SPRITE / 2, SPRITE / 2);
      grad.addColorStop(0, c);
      grad.addColorStop(0.25, c + "cc");
      grad.addColorStop(1, c + "00");
      g.fillStyle = grad;
      g.fillRect(0, 0, SPRITE, SPRITE);
      return s;
    });

    let w = 0;
    let h = 0;
    let dpr = 1;
    const mobile = window.innerWidth < 768;
    const N = mobile ? 1100 : 3000;

    // Per-ember constants: a point on every shape, rolled once.
    const P = Array.from({ length: N }, () => {
      const u = Math.random() * 2 - 1;
      const th = Math.random() * Math.PI * 2;
      const sq = Math.sqrt(1 - u * u);
      const g = gavelPoint();
      const sw = stopwatchPoint();
      return {
        dir: { x: sq * Math.cos(th), y: u, z: sq * Math.sin(th) }, // burst direction
        g,
        sw,
        coin: coinPoint(),
        lens: lensPoint(),
        tri: Math.random() < 0.24, // drawn as a small outlined triangle, not a glow
        a: Math.random() * Math.PI * 2,
        sx: Math.random(),
        drift: 0.2 + Math.random() * 0.8,
        jitter: (Math.random() - 0.5) * 2,
        delay: Math.random() * 0.45, // how late this ember follows a morph
        size: 0.6 + Math.pow(Math.random(), 3) * 2.4,
        color: Math.floor(Math.pow(Math.random(), 1.6) * colors.length),
        x: 0,
        y: 0,
        vx: 0,
        vy: 0,
        burst: 0.15 + Math.random() * 0.35, // stagger for the opening burst
      };
    });

    // Where each section sits, so scroll position maps to a shape number.
    let marks: { n: number; y: number }[] = [];
    const measure = () => {
      dpr = Math.min(window.devicePixelRatio || 1, 2);
      w = window.innerWidth;
      h = window.innerHeight;
      el.width = w * dpr;
      el.height = h * dpr;
      el.style.width = `${w}px`;
      el.style.height = `${h}px`;
      marks = Array.from(document.querySelectorAll<HTMLElement>("[data-lava]"))
        .map((s) => {
          const r = s.getBoundingClientRect();
          return { n: Number(s.dataset.lava), y: r.top + window.scrollY + Math.min(r.height, h) * 0.5 };
        })
        .sort((a, b) => a.y - b.y);
    };
    measure();
    const ro = new ResizeObserver(measure);
    ro.observe(document.body);
    window.addEventListener("resize", measure);

    const mouse = { x: -1e4, y: -1e4 };
    const onMove = (e: PointerEvent) => {
      mouse.x = e.clientX;
      mouse.y = e.clientY;
    };
    const onLeave = () => {
      mouse.x = mouse.y = -1e4;
    };
    window.addEventListener("pointermove", onMove, { passive: true });
    document.addEventListener("pointerleave", onLeave);

    const phaseAt = (y: number) => {
      if (!marks.length) return 0;
      if (y <= marks[0].y) return marks[0].n;
      for (let i = 0; i < marks.length - 1; i++) {
        const a = marks[i];
        const b = marks[i + 1];
        if (y <= b.y) return a.n + ((y - a.y) / (b.y - a.y)) * (b.n - a.n);
      }
      return marks[marks.length - 1].n;
    };

    const smooth = (t: number) => t * t * (3 - 2 * t);
    const expoOut = (t: number) => (t >= 1 ? 1 : 1 - Math.pow(2, -10 * t));
    let phase = phaseAt(window.scrollY + h / 2);
    let raf = 0;
    let last = performance.now();

    // Where each shape sits on screen and how big: zigzagging left and right.
    const frames = [
      { x: 0, y: 0, r: 0 },
      { x: 0, y: 0, r: 0 },
      { x: 0, y: 0, r: 0 },
      { x: 0, y: 0, r: 0 },
      { x: 0, y: 0, r: 0 },
    ];
    const layout = (box: DOMRect | undefined) => {
      const narrow = w < 1024;
      const side = (left: boolean) => (narrow ? w / 2 : w * (left ? 0.27 : 0.73));
      const R = narrow ? Math.min(w * 0.36, h * 0.28) : Math.min(w * 0.2, h * 0.36);
      frames[0] = box ? { x: box.left + box.width / 2, y: box.top + box.height / 2, r: box.width * 0.46 } : { x: side(false), y: h / 2, r: R };
      frames[1] = { x: w / 2, y: h / 2, r: Math.max(w, h) * 0.32 };
      frames[2] = { x: side(true), y: h * 0.52, r: R };
      frames[3] = { x: side(false), y: h * 0.5, r: R * 1.05 };
      frames[4] = { x: side(true), y: h * 0.5, r: R };
      // On narrow screens the later shapes sit behind the copy, so they step back.
      dim = narrow ? 0.4 : 1;
    };
    let dim = 1;

    // The gavel's swing and the stopwatch hands, updated once a frame.
    const pose = { c: 1, s: 0 };
    const hands = { s1: 0, c1: 1, s2: 0, c2: 1 };

    /** A shape's point for this ember, in its own unit space (y down). */
    const local = (p: (typeof P)[number], f: number, t: number, out: V3 & { fade: number }) => {
      out.fade = 1;
      switch (f) {
        case 0: {
          let x = p.g.x;
          let y = p.g.y;
          if (!p.g.block) {
            x = p.g.x * pose.c - p.g.y * pose.s + PIVOT.x;
            y = p.g.x * pose.s + p.g.y * pose.c + PIVOT.y;
          }
          out.x = (x - MID.x) * FIT;
          out.y = -(y - MID.y) * FIT;
          out.z = p.g.z * FIT;
          return;
        }
        case 1: {
          // Each ember flies out from the centre along its own direction and
          // wraps back: a warp field.
          const k = (((p.sx + t * 0.045 * p.drift) % 1) + 1) % 1;
          const d = 0.35 + k * k * 4.2;
          out.x = p.dir.x * d;
          out.y = p.dir.y * d;
          out.z = p.dir.z * d * 0.4;
          out.fade = Math.min(1, k * 6);
          return;
        }
        case 2: {
          const q = p.sw;
          if (q.hand) {
            const s = q.hand === 1 ? hands.s1 : hands.s2;
            const c = q.hand === 1 ? hands.c1 : hands.c2;
            out.x = s * q.len + p.jitter * 0.012;
            out.y = 0.1 - c * q.len;
            out.z = q.z;
            return;
          }
          out.x = q.x;
          out.y = q.y;
          out.z = q.z;
          return;
        }
        case 3:
          out.x = p.coin.x;
          out.y = p.coin.y;
          out.z = p.coin.z;
          return;
        default:
          out.x = p.lens.x;
          out.y = p.lens.y;
          out.z = p.lens.z;
      }
    };

    const A = { x: 0, y: 0, z: 0, fade: 1 };
    const B = { x: 0, y: 0, z: 0, fade: 1 };
    const rot = { cy: 1, sy: 0, cx: 1, sx: 0 };

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = reduce ? 0 : now / 1000;
      const s = state.current;

      layout(anchor.current?.getBoundingClientRect());
      const pulseK = Math.exp(-(now - s.pulseAt) / 500);

      // Ease the shape number toward the scroll position.
      const want = phaseAt(window.scrollY + h / 2);
      phase += (want - phase) * (reduce ? 1 : 1 - Math.pow(0.0008, dt));
      const f0 = Math.min(FORMATIONS - 2, Math.floor(phase));
      const frac = Math.min(1, Math.max(0, phase - f0));

      // Turn: a gentle sway so each shape shows its depth, plus one full
      // revolution per section, so morphs look like the object rotating.
      const ry = (reduce ? -0.3 : -0.3 + 0.45 * Math.sin(t * 0.32)) + (reduce ? 0 : phase * Math.PI * 2);
      const rx = 0.26 + (reduce ? 0 : 0.1 * Math.sin(t * 0.23));
      rot.cy = Math.cos(ry);
      rot.sy = Math.sin(ry);
      rot.cx = Math.cos(rx);
      rot.sx = Math.sin(rx);

      const sincePulse = (now - s.pulseAt) / 1000;
      const hit = reduce || sincePulse < 0 ? 0 : sincePulse < 0.14 ? Math.pow(sincePulse / 0.14, 2) : Math.exp(-(sincePulse - 0.14) / 0.35);
      const swing = REST + (STRIKE - REST) * hit + (reduce ? 0 : 0.03 * Math.sin(t * 0.9));
      pose.c = Math.cos(swing);
      pose.s = Math.sin(swing);
      const a1 = reduce ? 1.2 : t * 1.4;
      const a2 = reduce ? 4.4 : 4.4 + t * 0.05;
      hands.s1 = Math.sin(a1);
      hands.c1 = Math.cos(a1);
      hands.s2 = Math.sin(a2);
      hands.c2 = Math.cos(a2);

      const since = s.start ? (now - s.startedAt) / 1000 : 0;
      const FA = frames[f0];
      const FB = frames[f0 + 1];

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      ctx.globalCompositeOperation = "lighter";
      const tris = colors.map(() => new Path2D());
      // Fade toward `dim` as the page moves past the burst.
      const on = (s.start || reduce ? 1 : 0) * (1 - (1 - dim) * Math.min(1, Math.max(0, phase - 1)));

      for (let i = 0; i < N; i++) {
        const p = P[i];
        local(p, f0, t, A);
        local(p, f0 + 1, t, B);
        const k = smooth(Math.min(1, Math.max(0, (frac - p.delay) / (1 - 0.45))));
        // Blend in 3D, then rotate and project, so a morph turns as it goes.
        const lx = A.x + (B.x - A.x) * k;
        const ly = A.y + (B.y - A.y) * k;
        const lz = A.z + (B.z - A.z) * k;
        const ox = FA.x + (FB.x - FA.x) * k;
        const oy = FA.y + (FB.y - FA.y) * k;
        const R = FA.r + (FB.r - FA.r) * k;
        const fade = A.fade + (B.fade - A.fade) * k;

        const x1 = lx * rot.cy + lz * rot.sy;
        const z1 = -lx * rot.sy + lz * rot.cy;
        const y2 = ly * rot.cx - z1 * rot.sx;
        const z2 = ly * rot.sx + z1 * rot.cx;
        const persp = 3.2 / (3.2 + z2); // near points grow, far points shrink
        let x = ox + x1 * R * persp;
        let y = oy + y2 * R * persp;
        const depth = Math.min(1.5, persp * persp * (0.55 + 0.45 * (1 - (z2 + 1.2) / 2.4))) * fade;

        let bloom = 1;
        if (!reduce) {
          bloom = s.start ? expoOut(Math.max(0, (since - p.burst * 0.6) / 1.6)) : 0;
          x = ox + (x - ox) * bloom;
          y = oy + (y - oy) * bloom;
        }

        // Embers shy away from the cursor and drift back.
        const dx = x + p.x - mouse.x;
        const dy = y + p.y - mouse.y;
        const d2 = dx * dx + dy * dy;
        if (d2 < 140 * 140 && d2 > 1) {
          const d = Math.sqrt(d2);
          const push = (1 - d / 140) * 900 * dt;
          p.vx += (dx / d) * push;
          p.vy += (dy / d) * push;
        }
        p.vx += -p.x * 6 * dt;
        p.vy += -p.y * 6 * dt;
        p.vx *= 1 - 4 * dt;
        p.vy *= 1 - 4 * dt;
        p.x += p.vx * dt;
        p.y += p.vy * dt;
        x += p.x;
        y += p.y;

        if (x < -40 || x > w + 40 || y < -40 || y > h + 40 || depth < 0.02) continue;
        const flicker = 0.75 + 0.25 * Math.sin(t * 3 + i);
        if (p.tri) {
          // Small outlined triangles, tumbling: they give the cloud a crisp grain.
          if (depth < 0.55) continue; // only the near side shows its glyphs
          const r = (1.5 + p.size * 0.9) * depth * (0.6 + 0.4 * bloom);
          const a0 = p.a + t * 0.8 * p.jitter;
          const path = tris[p.color % tris.length];
          for (let v = 0; v < 3; v++) {
            const av = a0 + (v * Math.PI * 2) / 3;
            const tx = x + Math.cos(av) * r;
            const ty = y + Math.sin(av) * r;
            if (v === 0) path.moveTo(tx, ty);
            else path.lineTo(tx, ty);
          }
          path.closePath();
          continue;
        }
        const size = p.size * 3.6 * depth * (0.6 + 0.4 * bloom) * (1 + pulseK * 0.3);
        // Depth cue: the far side fades back, the near side glows.
        ctx.globalAlpha = Math.min(0.95, Math.max(0.06, (depth - 0.25) * 1.1) * (0.7 + 0.3 * flicker)) * on;
        ctx.drawImage(sprites[p.color], x - size / 2, y - size / 2, size, size);
      }
      ctx.globalAlpha = 0.75 * on;
      ctx.lineWidth = 1;
      tris.forEach((path, ci) => {
        ctx.strokeStyle = colors[ci];
        ctx.stroke(path);
      });
      ctx.globalAlpha = 1;
      ctx.globalCompositeOperation = "source-over";
    };
    raf = requestAnimationFrame(frame);

    const onVis = () => {
      cancelAnimationFrame(raf);
      if (!document.hidden) {
        last = performance.now();
        raf = requestAnimationFrame(frame);
      }
    };
    document.addEventListener("visibilitychange", onVis);

    return () => {
      cancelAnimationFrame(raf);
      ro.disconnect();
      window.removeEventListener("resize", measure);
      window.removeEventListener("pointermove", onMove);
      document.removeEventListener("pointerleave", onLeave);
      document.removeEventListener("visibilitychange", onVis);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return <canvas ref={canvas} aria-hidden className="pointer-events-none fixed inset-0 z-0" />;
}
