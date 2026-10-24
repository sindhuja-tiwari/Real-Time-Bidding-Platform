"use client";

import { useEffect, useRef, type RefObject } from "react";

/**
 * The "lava": a few thousand glowing embers drawn on one fixed canvas behind
 * the home page. Each section of the page names a formation with
 * `data-lava="n"`, and as you scroll the embers flow from one formation to the
 * next, each on its own slight delay so the shape melts rather than snaps.
 *
 *   0  gavel    an auctioneer's gavel and block in 3D, on the right of the
 *               hero; it turns slowly, turns further as you scroll, and
 *               strikes the block every time an auction is sold
 *   1  burst    the gavel slides to the middle of the screen and blows
 *               outward from there, a warp-field streaming toward you
 *   2  lanes    five streams, one per DSP, each at its own speed
 *   3  line     everything settles into the 100 ms deadline
 */

type Props = {
  /** The orb is centred on this element and sized to it. */
  anchor: RefObject<HTMLElement>;
  /** Flip to true to burst the orb out from a single point. */
  start: boolean;
  /** Change this to send a pulse through the orb (e.g. on each auction). */
  pulse?: unknown;
  colors?: string[];
};

const FORMATIONS = 4;

/*
 * The gavel, in its own units. The handle runs up the y axis from its end at
 * the origin; the head sits across the top with its axis along x. The whole
 * gavel then turns about the handle end (PIVOT) by REST, and by STRIKE at the
 * moment it hits the round block.
 */
const PIVOT = { x: 1.05, y: -0.45 };
const REST = 0.85;
const STRIKE = 1.46;
const MID = { x: -0.12, y: 0.08 }; // centre of the whole scene
const FIT = 0.64; // scales the scene to roughly a unit radius

function ring(r: number) {
  const a = Math.random() * Math.PI * 2;
  return [Math.cos(a) * r, Math.sin(a) * r] as const;
}

function gavelPoint(): { x: number; y: number; z: number; block: boolean } {
  const k = Math.random();
  if (k < 0.4) {
    // Head barrel: a cylinder along x, with raised collars near each end.
    const x = (Math.random() * 2 - 1) * 0.6;
    const collar = Math.abs(Math.abs(x) - 0.42) < 0.05;
    const [y, z] = ring(collar ? 0.34 : 0.3);
    return { x, y: 1.9 + y, z, block: false };
  }
  if (k < 0.52) {
    // Head faces: the two flat striking ends.
    const [y, z] = ring(0.3 * Math.sqrt(Math.random()));
    return { x: Math.random() < 0.5 ? -0.6 : 0.6, y: 1.9 + y, z, block: false };
  }
  if (k < 0.72) {
    // Handle, a little thicker at the grip, with a knob at the end.
    const y = Math.random() * 1.6;
    const r = y < 0.12 ? 0.1 : 0.055 + 0.025 * (1 - y / 1.6);
    const [x, z] = ring(r);
    return { x, y, z, block: false };
  }
  // The sound block: a low round base where the head lands.
  const top = Math.random() < 0.55;
  const bx = -0.85;
  const by = -1.1;
  if (top) {
    const [x, z] = ring(0.55 * Math.sqrt(Math.random()));
    return { x: bx + x, y: by + 0.18, z, block: true };
  }
  const [x, z] = ring(0.55);
  return { x: bx + x, y: by + Math.random() * 0.18, z, block: true };
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

    // Per-ember constants: everything a formation needs, rolled once.
    const P = Array.from({ length: N }, (_, i) => {
      const lane = i % 5;
      // A random direction for the burst, and a point on the gavel or its block.
      const u = Math.random() * 2 - 1;
      const th = Math.random() * Math.PI * 2;
      const sq = Math.sqrt(1 - u * u);
      const g = gavelPoint();
      return {
        bx: sq * Math.cos(th),
        by: u,
        bz: sq * Math.sin(th),
        gx: g.x,
        gy: g.y,
        gz: g.z,
        block: g.block,
        tri: Math.random() < 0.24, // drawn as a small outlined triangle, not a glow
        a: Math.random() * Math.PI * 2, // angle on the orb
        r: 0.62 + 0.38 * Math.pow(Math.random(), 0.7), // radius within the ring
        sx: Math.random(), // scatter position
        sy: Math.random(),
        drift: 0.2 + Math.random() * 0.8,
        lane,
        lx: Math.random(), // position along a lane
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

    // Where each section sits, so scroll position maps to a formation number.
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

    // Rotate a unit-space point by the current spin, then project it.
    const rot = { cy: 1, sy: 0, cx: 1, sx: 0 };
    const project = (x: number, y: number, z: number, ox: number, oy: number, R: number, out: { x: number; y: number; s: number }) => {
      const x1 = x * rot.cy + z * rot.sy;
      const z1 = -x * rot.sy + z * rot.cy;
      const y2 = y * rot.cx - z1 * rot.sx;
      const z2 = y * rot.sx + z1 * rot.cx;
      const persp = 3.2 / (3.2 + z2); // near points grow, far points shrink
      out.x = ox + x1 * R * persp;
      out.y = oy + y2 * R * persp;
      out.s = persp * persp * (0.55 + 0.45 * (1 - (z2 + 1.2) / 2.4));
    };

    const target = (p: (typeof P)[number], f: number, t: number, cx: number, cy: number, R: number, out: { x: number; y: number; s: number }) => {
      switch (f) {
        case 0: {
          // The gavel swings about the end of its handle; the block stays put.
          let x = p.gx;
          let y = p.gy;
          if (!p.block) {
            x = p.gx * pose.c - p.gy * pose.s + PIVOT.x;
            y = p.gx * pose.s + p.gy * pose.c + PIVOT.y;
          }
          const j = 0.008 * Math.sin(t * 1.3 + p.a * 5); // a faint shimmer
          project((x - MID.x) * FIT + j, -(y - MID.y) * FIT + j, p.gz * FIT, cx, cy, R, out);
          return;
        }
        case 1: {
          // Every ember flies straight out from the middle of the screen along
          // its own direction, wrapping back to the centre: a warp field.
          const k = (((p.sx + t * 0.045 * p.drift) % 1) + 1) % 1;
          const d = 0.35 + k * k * 4.2;
          project(p.bx * d, p.by * d, p.bz * d * 0.4, w / 2, h / 2, Math.max(w, h) * 0.32, out);
          out.s *= Math.min(1, k * 6) * (0.6 + k * 0.9);
          return;
        }
        case 2: {
          // Five lanes, each its own speed. Lane C crawls: it's the DSP that misses the deadline.
          const speed = [0.05, 0.075, 0.018, 0.06, 0.04][p.lane];
          const x = (((p.lx + t * speed) % 1) + 1) % 1;
          const y0 = h * (0.3 + p.lane * 0.1);
          out.x = x * w * 1.1 - w * 0.05;
          out.y = y0 + p.jitter * 7 + Math.sin(x * 9 + t + p.lane) * 5;
          out.s = 1;
          return;
        }
        default: {
          // A long glowing horizon: the deadline.
          const x = p.sx;
          out.x = w * (0.04 + x * 0.92);
          out.y = h * 0.58 + p.jitter * (3 + 14 * Math.pow(Math.abs(x - 0.5) * 2, 3)) + Math.sin(x * 14 + t * 1.4) * 3;
          out.s = 1;
        }
      }
    };

    // The gavel's swing: resting raised, it comes down on each sale and lifts again.
    const pose = { c: 1, s: 0 };
    const A = { x: 0, y: 0, s: 1 };
    const B = { x: 0, y: 0, s: 1 };
    const scrollSpin = () => window.scrollY * 0.0026;

    const frame = (now: number) => {
      raf = requestAnimationFrame(frame);
      const dt = Math.min(0.05, (now - last) / 1000);
      last = now;
      const t = reduce ? 0 : now / 1000;
      const s = state.current;

      // Orb geometry follows its anchor (so it scrolls up with the hero).
      const box = anchor.current?.getBoundingClientRect();
      const cx = box ? box.left + box.width / 2 : w / 2;
      const cy = box ? box.top + box.height / 2 : h / 2;
      const pulseK = Math.exp(-(now - s.pulseAt) / 500);
      const R = box ? box.width * 0.46 : Math.min(w, h) * 0.3;
      // Turn: a slow sway of its own, plus a full turn as you scroll.
      // It sways through a three-quarter view rather than spinning all the way
      // round, so the swing of the gavel always faces you.
      const ry = (reduce ? -0.35 : -0.35 + 0.5 * Math.sin(t * 0.32)) + scrollSpin();
      const rx = 0.28 + (reduce ? 0 : 0.12 * Math.sin(t * 0.23)) + window.scrollY * 0.0005;
      const sincePulse = (now - s.pulseAt) / 1000;
      const hit = reduce || sincePulse < 0 ? 0 : sincePulse < 0.14 ? Math.pow(sincePulse / 0.14, 2) : Math.exp(-(sincePulse - 0.14) / 0.35);
      const swing = REST + (STRIKE - REST) * hit + (reduce ? 0 : 0.03 * Math.sin(t * 0.9));
      pose.c = Math.cos(swing);
      pose.s = Math.sin(swing);
      rot.cy = Math.cos(ry);
      rot.sy = Math.sin(ry);
      rot.cx = Math.cos(rx);
      rot.sx = Math.sin(rx);

      // Ease the formation number toward the scroll position.
      const want = phaseAt(window.scrollY + h / 2);
      phase += (want - phase) * (reduce ? 1 : 1 - Math.pow(0.0008, dt));
      const f0 = Math.min(FORMATIONS - 2, Math.floor(phase));
      const frac = Math.min(1, Math.max(0, phase - f0));

      // Opening burst: everything starts at the centre and blooms out.
      const since = s.start ? (now - s.startedAt) / 1000 : 0;

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      const tris = colors.map(() => new Path2D());
      ctx.globalCompositeOperation = "lighter";

      for (let i = 0; i < N; i++) {
        const p = P[i];
        target(p, f0, t, cx, cy, R, A);
        target(p, f0 + 1, t, cx, cy, R, B);
        const k = smooth(Math.min(1, Math.max(0, (frac - p.delay) / (1 - 0.45))));
        let x = A.x + (B.x - A.x) * k;
        let y = A.y + (B.y - A.y) * k;
        const depth = Math.min(1.5, A.s + (B.s - A.s) * k);

        let bloom = 1;
        if (!reduce) {
          bloom = s.start ? expoOut(Math.max(0, (since - p.burst * 0.6) / 1.6)) : 0;
          x = cx + (x - cx) * bloom;
          y = cy + (y - cy) * bloom;
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
        const on = s.start || reduce ? 1 : 0;
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
        const size = p.size * 3.6 * depth * (0.6 + 0.4 * bloom) * (1 + pulseK * 0.4);
        // Depth cue: the far side of the cloud fades back, the near side glows.
        ctx.globalAlpha = Math.min(0.95, Math.max(0.06, (depth - 0.25) * 1.1) * (0.7 + 0.3 * flicker)) * on;
        ctx.drawImage(sprites[p.color], x - size / 2, y - size / 2, size, size);
      }
      ctx.globalAlpha = (s.start || reduce ? 0.75 : 0);
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
