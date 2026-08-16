import { FormEvent, useEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import type { LineBasicMaterial, Material, MeshBasicMaterial, Scene, SpriteMaterial, Vector3, WebGLRenderer } from "three";

let THREE: typeof import("three");

type ShipClass = "frigate" | "cruiser";
type Phase = "idle" | "registration" | "countdown" | "battle" | "winner";
type ClaimStatus = "none" | "pending" | "claimed" | "expired";
type ArenaSoundCue = "toggle" | "countdown" | "battle" | "destroyed" | "winner" | "claim";

type Combatant = {
  id: string;
  name: string;
  shipClass: ShipClass;
  hp: number;
  maxHp: number;
  alive: boolean;
  kills: number;
};

type BattleRecord = {
  id: string;
  winnerName: string;
  winnerClass: ShipClass;
  durationSeconds: number;
  participants: number;
  completedAt: string;
  frigateFireRate: number;
  cruiserFireRate: number;
};

type SimulationResult = {
  rounds: number;
  participants: number;
  frigateWins: number;
  cruiserWins: number;
  averageDuration: number;
  averageShots: number;
};

type TwitchStatus = {
  configured: boolean;
  authenticated: boolean;
  connected: boolean;
  login: string;
  channel: string;
  message: string;
};

type UpdateStatus = {
  available: boolean;
  version?: string;
  name?: string;
  notes?: string;
  page_url?: string;
  asset_name?: string;
  size?: number;
};

type BackendSettings = {
  channel_login: string;
  twitch_client_id: string;
  twitch_client_secret_set: boolean;
  server_port: number;
  github_owner: string;
  github_repo: string;
  auto_update: boolean;
  open_browser_on_start: boolean;
};

type ArenaStateMessage = {
  origin: string;
  phase: Phase;
  combatants: Combatant[];
  battleId: number;
  round: number;
  countdown: number;
  winner: Combatant | null;
  winnerAllTimeWins: number;
  claimStatus: ClaimStatus;
  claimSeconds: number;
  logs: { time: string; message: string }[];
  arenaTitle: string;
  joinCommand: string;
  shipScale: number;
  frigateFireRate: number;
  cruiserFireRate: number;
  soundOn: boolean;
  updatedAt: number;
  activeRoundId: string | null;
  battleStartedAt: number | null;
  testMode: boolean;
};

type WinnerLeader = {
  name: string;
  wins: number;
  participations: number;
  last_win: string;
};

const EMPTY_TWITCH_STATUS: TwitchStatus = {
  configured: false,
  authenticated: false,
  connected: false,
  login: "",
  channel: "savox76",
  message: "Lokaler Server wird verbunden",
};

const DEFAULT_BACKEND_SETTINGS: BackendSettings = {
  channel_login: "savox76",
  twitch_client_id: "",
  twitch_client_secret_set: false,
  server_port: 8766,
  github_owner: "Savox76",
  github_repo: "savox76-giveaway",
  auto_update: true,
  open_browser_on_start: true,
};

type ArenaProps = {
  combatants: Combatant[];
  battleId: number;
  phase: Phase;
  shipScale: number;
  frigateFireRate: number;
  cruiserFireRate: number;
  readOnly: boolean;
  onSnapshot: (ships: Combatant[]) => void;
  onLog: (message: string) => void;
  onWinner: (ship: Combatant) => void;
  onSound: (cue: ArenaSoundCue) => void;
};

const CLASS_STATS = {
  frigate: { hp: 100, damage: [8, 12], fireRate: 1.55, speed: 3.9, dodge: 0.34, accent: 0x30d9ff },
  cruiser: { hp: 180, damage: [25, 32], fireRate: 2.35, speed: 2.15, dodge: 0.06, accent: 0xff9a3d },
} as const;

const BALANCED_FIRE_RATES = { frigate: 1.55, cruiser: 2.35 } as const;

let arenaAudioContext: AudioContext | null = null;

function playArenaSound(cue: ArenaSoundCue) {
  if (typeof AudioContext === "undefined") return;
  arenaAudioContext ??= new AudioContext();
  const context = arenaAudioContext;
  const patterns: Record<ArenaSoundCue, { frequency: number; end: number; delay: number; duration: number; gain: number; type: OscillatorType }[]> = {
    toggle: [{ frequency: 520, end: 760, delay: 0, duration: 0.12, gain: 0.055, type: "sine" }],
    countdown: [{ frequency: 440, end: 440, delay: 0, duration: 0.09, gain: 0.045, type: "sine" }],
    battle: [
      { frequency: 110, end: 220, delay: 0, duration: 0.38, gain: 0.055, type: "sawtooth" },
      { frequency: 330, end: 660, delay: 0.1, duration: 0.24, gain: 0.035, type: "sine" },
    ],
    destroyed: [{ frequency: 95, end: 38, delay: 0, duration: 0.32, gain: 0.07, type: "sawtooth" }],
    winner: [
      { frequency: 392, end: 392, delay: 0, duration: 0.18, gain: 0.045, type: "triangle" },
      { frequency: 523, end: 523, delay: 0.17, duration: 0.2, gain: 0.05, type: "triangle" },
      { frequency: 659, end: 784, delay: 0.35, duration: 0.42, gain: 0.055, type: "triangle" },
    ],
    claim: [
      { frequency: 620, end: 720, delay: 0, duration: 0.12, gain: 0.045, type: "sine" },
      { frequency: 820, end: 920, delay: 0.13, duration: 0.16, gain: 0.045, type: "sine" },
    ],
  };

  void context.resume().then(() => {
    const start = context.currentTime + 0.015;
    patterns[cue].forEach((tone) => {
      const oscillator = context.createOscillator();
      const volume = context.createGain();
      const toneStart = start + tone.delay;
      oscillator.type = tone.type;
      oscillator.frequency.setValueAtTime(tone.frequency, toneStart);
      oscillator.frequency.exponentialRampToValueAtTime(Math.max(20, tone.end), toneStart + tone.duration);
      volume.gain.setValueAtTime(0.0001, toneStart);
      volume.gain.exponentialRampToValueAtTime(tone.gain, toneStart + 0.018);
      volume.gain.exponentialRampToValueAtTime(0.0001, toneStart + tone.duration);
      oscillator.connect(volume).connect(context.destination);
      oscillator.start(toneStart);
      oscillator.stop(toneStart + tone.duration + 0.02);
    });
  }).catch(() => undefined);
}

const DEMO_NAMES = [
  "Voidrider", "NovaFox", "IronWolf", "Starling", "Orbital", "Nebula",
  "Valkyrie", "PixelPilot", "DarkMatter", "AstroByte", "Moonshot", "Raven",
];

const clampFireRate = (value: number, fallback: number) => Number.isFinite(value) ? Math.min(8, Math.max(0.2, value)) : fallback;

function simulateBalanceBatch(rounds: number, participantCount: number, frigateFireRate: number, cruiserFireRate: number): SimulationResult {
  let frigateWins = 0;
  let cruiserWins = 0;
  let totalDuration = 0;
  let totalShots = 0;

  for (let roundIndex = 0; roundIndex < rounds; roundIndex++) {
    const cruiserCount = Math.floor(participantCount / 4);
    const fighters = Array.from({ length: participantCount }, (_, index) => {
      const shipClass: ShipClass = index < cruiserCount ? "cruiser" : "frigate";
      const interval = shipClass === "frigate" ? frigateFireRate : cruiserFireRate;
      return { shipClass, hp: CLASS_STATS[shipClass].hp, alive: true, nextShot: 0.15 + Math.random() * interval };
    });
    let elapsed = 0;
    let shots = 0;

    while (fighters.filter((fighter) => fighter.alive).length > 1 && elapsed < 900 && shots < 30000) {
      const alive = fighters.filter((fighter) => fighter.alive);
      const attacker = alive.reduce((next, fighter) => fighter.nextShot < next.nextShot ? fighter : next);
      const targets = alive.filter((fighter) => fighter !== attacker);
      const target = targets[Math.floor(Math.random() * targets.length)];
      elapsed = attacker.nextShot;
      shots += 1;
      const interval = attacker.shipClass === "frigate" ? frigateFireRate : cruiserFireRate;
      attacker.nextShot += interval * (0.85 + Math.random() * 0.3);

      if (Math.random() <= 1 - CLASS_STATS[target.shipClass].dodge) {
        const [minDamage, maxDamage] = CLASS_STATS[attacker.shipClass].damage;
        target.hp -= minDamage + Math.random() * (maxDamage - minDamage);
        if (target.hp <= 0) target.alive = false;
      }
    }

    const survivor = fighters.find((fighter) => fighter.alive);
    if (survivor?.shipClass === "cruiser") cruiserWins += 1;
    else frigateWins += 1;
    totalDuration += elapsed;
    totalShots += shots;
  }

  return {
    rounds,
    participants: participantCount,
    frigateWins,
    cruiserWins,
    averageDuration: totalDuration / rounds,
    averageShots: totalShots / rounds,
  };
}

function createTestNames(count: number) {
  return Array.from({ length: count }, (_, index) => DEMO_NAMES[index] ?? `TestPilot_${String(index + 1).padStart(2, "0")}`);
}

function secureShuffle<T>(items: T[]) {
  const result = [...items];
  const random = new Uint32Array(result.length || 1);
  if (typeof crypto !== "undefined") crypto.getRandomValues(random);
  for (let i = result.length - 1; i > 0; i--) {
    const value = random[i] ?? Math.floor(Math.random() * 2 ** 32);
    const j = value % (i + 1);
    [result[i], result[j]] = [result[j], result[i]];
  }
  return result;
}

function balanceFleet(names: string[]): Combatant[] {
  const shuffled = secureShuffle(names);
  const cruiserCount = Math.floor(names.length / 4);
  const cruisers = new Set(shuffled.slice(0, cruiserCount).map((name) => name.toLocaleLowerCase()));
  return names.map((name, index) => {
    const shipClass: ShipClass = cruisers.has(name.toLocaleLowerCase()) ? "cruiser" : "frigate";
    const maxHp = CLASS_STATS[shipClass].hp;
    return { id: `${name.toLocaleLowerCase().replace(/[^a-z0-9]/g, "-")}-${index}`, name, shipClass, hp: maxHp, maxHp, alive: true, kills: 0 };
  });
}

function createHull(shipClass: ShipClass, accent: number) {
  const ship = new THREE.Group();
  const dark = new THREE.MeshStandardMaterial({ color: 0x334651, emissive: 0x0a1820, emissiveIntensity: 0.72, metalness: 0.84, roughness: 0.26 });
  const mid = new THREE.MeshStandardMaterial({ color: 0x71838e, emissive: 0x14222a, emissiveIntensity: 0.48, metalness: 0.72, roughness: 0.3 });
  const glow = new THREE.MeshStandardMaterial({ color: accent, emissive: accent, emissiveIntensity: 5.1, metalness: 0.24, roughness: 0.12 });
  const engine = new THREE.MeshBasicMaterial({ color: 0xc2f8ff, transparent: true, opacity: 1, blending: THREE.AdditiveBlending });

  if (shipClass === "frigate") {
    const hull = new THREE.Mesh(new THREE.ConeGeometry(0.72, 4.5, 5), dark);
    hull.rotation.z = -Math.PI / 2;
    ship.add(hull);

    const spine = new THREE.Mesh(new THREE.BoxGeometry(3.1, 0.22, 0.34), mid);
    ship.add(spine);

    [-1, 1].forEach((side) => {
      const wing = new THREE.Mesh(new THREE.BoxGeometry(1.85, 0.12, 1.35), dark);
      wing.position.set(-0.15, 0, side * 0.88);
      wing.rotation.y = side * 0.19;
      ship.add(wing);

      const strip = new THREE.Mesh(new THREE.BoxGeometry(1.15, 0.06, 0.07), glow);
      strip.position.set(-0.1, 0.11, side * 1.18);
      ship.add(strip);
    });

    const flame = new THREE.Mesh(new THREE.ConeGeometry(0.28, 1.6, 12), engine);
    flame.rotation.z = Math.PI / 2;
    flame.position.x = -2.85;
    ship.add(flame);
  } else {
    const core = new THREE.Mesh(new THREE.BoxGeometry(4.8, 1.15, 1.45), dark);
    core.rotation.x = 0.08;
    ship.add(core);

    const prow = new THREE.Mesh(new THREE.ConeGeometry(1.0, 2.6, 5), mid);
    prow.rotation.z = -Math.PI / 2;
    prow.position.x = 3.15;
    ship.add(prow);

    [-1, 1].forEach((side) => {
      const armor = new THREE.Mesh(new THREE.BoxGeometry(3.45, 0.42, 0.75), dark);
      armor.position.set(-0.25, -0.24, side * 1.08);
      ship.add(armor);

      const rail = new THREE.Mesh(new THREE.CylinderGeometry(0.11, 0.11, 2.45, 8), mid);
      rail.rotation.z = Math.PI / 2;
      rail.position.set(1.05, 0.48, side * 0.9);
      ship.add(rail);

      const strip = new THREE.Mesh(new THREE.BoxGeometry(1.8, 0.07, 0.08), glow);
      strip.position.set(0.4, 0.61, side * 0.73);
      ship.add(strip);

      const flame = new THREE.Mesh(new THREE.ConeGeometry(0.32, 1.8, 12), engine);
      flame.rotation.z = Math.PI / 2;
      flame.position.set(-3.15, 0, side * 0.63);
      ship.add(flame);
    });
  }

  ship.traverse((object) => {
    if (object instanceof THREE.Mesh) {
      object.castShadow = true;
      object.receiveShadow = true;
    }
  });
  return ship;
}

function createNameplate(entry: Combatant) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 154;
  const ctx = canvas.getContext("2d")!;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  const sprite = new THREE.Sprite(new THREE.SpriteMaterial({ map: texture, transparent: true, depthWrite: false }));
  sprite.scale.set(5.7, 1.72, 1);
  sprite.position.y = entry.shipClass === "frigate" ? 2.05 : 2.65;

  const update = (hp: number) => {
    const ratio = Math.max(0, hp / entry.maxHp);
    ctx.clearRect(0, 0, 512, 154);
    ctx.font = "700 34px Arial";
    ctx.textAlign = "center";
    ctx.fillStyle = entry.shipClass === "frigate" ? "#86efff" : "#ffc176";
    ctx.shadowColor = ctx.fillStyle;
    ctx.shadowBlur = 14;
    ctx.fillText(entry.name.toLocaleUpperCase(), 256, 48);
    ctx.shadowBlur = 0;
    ctx.font = "600 18px Arial";
    ctx.fillStyle = "rgba(222,240,246,.72)";
    ctx.fillText(entry.shipClass === "frigate" ? "FRIGATTE" : "CRUISER", 256, 77);
    ctx.fillStyle = "rgba(8,18,24,.88)";
    ctx.fillRect(106, 97, 300, 12);
    ctx.fillStyle = ratio > 0.35 ? (entry.shipClass === "frigate" ? "#35d8ee" : "#ff9a3d") : "#ff4f4f";
    ctx.fillRect(108, 99, 296 * ratio, 8);
    ctx.font = "600 15px Arial";
    ctx.fillStyle = "rgba(218,238,244,.7)";
    ctx.fillText(`${Math.ceil(Math.max(0, hp))} / ${entry.maxHp} HP`, 256, 132);
    texture.needsUpdate = true;
  };
  update(entry.hp);
  return { sprite, update };
}

function createLaser(scene: Scene, from: Vector3, to: Vector3, color: number) {
  const geometry = new THREE.BufferGeometry().setFromPoints([from.clone(), to.clone()]);
  const material = new THREE.LineBasicMaterial({ color, transparent: true, opacity: 1 });
  const laser = new THREE.Line(geometry, material);
  scene.add(laser);
  return { laser, born: performance.now(), duration: 170 };
}

function createImpact(scene: Scene, position: Vector3, color: number, large = false) {
  const geometry = new THREE.SphereGeometry(large ? 0.68 : 0.23, 12, 8);
  const material = new THREE.MeshBasicMaterial({ color, transparent: true, opacity: 0.95, blending: THREE.AdditiveBlending });
  const impact = new THREE.Mesh(geometry, material);
  impact.position.copy(position);
  scene.add(impact);
  return { impact, born: performance.now(), duration: large ? 850 : 280, large };
}

function createGlowTexture(core: string, halo: string) {
  const canvas = document.createElement("canvas");
  canvas.width = 512;
  canvas.height = 512;
  const context = canvas.getContext("2d")!;
  const gradient = context.createRadialGradient(256, 256, 4, 256, 256, 250);
  gradient.addColorStop(0, core);
  gradient.addColorStop(0.08, core);
  gradient.addColorStop(0.24, halo);
  gradient.addColorStop(0.58, "rgba(80,110,180,.12)");
  gradient.addColorStop(1, "rgba(0,0,0,0)");
  context.fillStyle = gradient;
  context.fillRect(0, 0, 512, 512);
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  return texture;
}

function createGasGiantTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 1024;
  canvas.height = 512;
  const context = canvas.getContext("2d")!;
  const image = context.createImageData(canvas.width, canvas.height);
  const data = image.data;
  for (let y = 0; y < canvas.height; y++) {
    const latitude = y / canvas.height;
    const broadBands = Math.sin(latitude * 58) * 17 + Math.sin(latitude * 143) * 7;
    for (let x = 0; x < canvas.width; x++) {
      const flow = Math.sin(x * 0.018 + y * 0.046) * 5 + Math.sin(x * 0.006 - y * 0.082) * 4;
      const grain = (Math.random() - 0.5) * 12;
      const index = (y * canvas.width + x) * 4;
      data[index] = Math.max(8, 37 + broadBands * 0.42 + flow + grain);
      data[index + 1] = Math.max(15, 69 + broadBands * 0.78 + flow * 1.5 + grain);
      data[index + 2] = Math.max(20, 84 + broadBands + flow * 2 + grain);
      data[index + 3] = 255;
    }
  }
  context.putImageData(image, 0, 0);
  context.globalAlpha = 0.28;
  context.fillStyle = "#b98a6e";
  context.beginPath();
  context.ellipse(714, 302, 92, 26, -0.12, 0, Math.PI * 2);
  context.fill();
  context.globalAlpha = 1;
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  return texture;
}

function createRockTexture() {
  const canvas = document.createElement("canvas");
  canvas.width = 768;
  canvas.height = 384;
  const context = canvas.getContext("2d")!;
  const base = context.createLinearGradient(0, 0, canvas.width, canvas.height);
  base.addColorStop(0, "#6d6963");
  base.addColorStop(0.5, "#403f3c");
  base.addColorStop(1, "#242525");
  context.fillStyle = base;
  context.fillRect(0, 0, canvas.width, canvas.height);
  for (let i = 0; i < 180; i++) {
    const x = Math.random() * canvas.width;
    const y = Math.random() * canvas.height;
    const radius = 2 + Math.random() * 17;
    const crater = context.createRadialGradient(x - radius * 0.25, y - radius * 0.25, 1, x, y, radius);
    crater.addColorStop(0, "rgba(180,177,166,.18)");
    crater.addColorStop(0.4, "rgba(44,43,41,.52)");
    crater.addColorStop(1, "rgba(10,10,10,0)");
    context.fillStyle = crater;
    context.beginPath();
    context.arc(x, y, radius, 0, Math.PI * 2);
    context.fill();
  }
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.wrapS = THREE.RepeatWrapping;
  return texture;
}

function createAsteroidGeometry(seed: number) {
  const geometry = new THREE.IcosahedronGeometry(1, 2);
  const position = geometry.attributes.position;
  const vertex = new THREE.Vector3();
  for (let index = 0; index < position.count; index++) {
    vertex.fromBufferAttribute(position, index);
    const deformation = 0.84
      + Math.sin(vertex.x * 5.7 + seed) * 0.085
      + Math.sin(vertex.y * 8.3 - seed * 1.7) * 0.06
      + Math.cos(vertex.z * 6.1 + seed * 2.4) * 0.075;
    vertex.multiplyScalar(deformation);
    position.setXYZ(index, vertex.x, vertex.y, vertex.z);
  }
  position.needsUpdate = true;
  geometry.scale(1.05 + seed * 0.035, 0.78 + seed * 0.025, 0.91 + seed * 0.02);
  geometry.computeVertexNormals();
  return geometry;
}

function SpaceArena({ combatants, battleId, phase, shipScale, frigateFireRate, cruiserFireRate, readOnly, onSnapshot, onLog, onWinner, onSound }: ArenaProps) {
  const mountRef = useRef<HTMLDivElement>(null);
  const callbacksRef = useRef({ onSnapshot, onLog, onWinner, onSound });
  const combatantsRef = useRef(combatants);
  const fleetKey = useMemo(() => combatants.map((ship) => `${ship.id}:${ship.shipClass}`).join("|"), [combatants]);

  useEffect(() => {
    callbacksRef.current = { onSnapshot, onLog, onWinner, onSound };
  }, [onSnapshot, onLog, onWinner, onSound]);

  useEffect(() => {
    combatantsRef.current = combatants;
  }, [combatants]);

  useEffect(() => {
    let cancelled = false;
    let cleanup: (() => void) | undefined;
    const mount = mountRef.current;
    if (!mount) return;

    void import("three").then((threeRuntime) => {
      if (cancelled) return;
      THREE = threeRuntime;
      mount.replaceChildren();
      delete mount.dataset.webgl;

      const probe = document.createElement("canvas");
      const webgl = probe.getContext("webgl2") || probe.getContext("webgl");
      if (!webgl) {
        mount.dataset.webgl = "unavailable";
        if (phase !== "battle" || readOnly) return;
        const fallbackFleet = combatantsRef.current.map((ship) => ({ ...ship }));
        const fallbackLastShots = new Map(fallbackFleet.map((ship) => [ship.id, performance.now()]));
        const fallbackTimer = window.setInterval(() => {
          const alive = fallbackFleet.filter((ship) => ship.alive);
          if (alive.length <= 1) {
            window.clearInterval(fallbackTimer);
            if (alive[0]) callbacksRef.current.onWinner({ ...alive[0] });
            return;
          }
          const now = performance.now();
          const ready = alive.filter((ship) => {
            const fireRate = ship.shipClass === "frigate" ? frigateFireRate : cruiserFireRate;
            return now - (fallbackLastShots.get(ship.id) ?? 0) >= fireRate * 1000;
          });
          if (ready.length === 0) return;
          const attacker = ready[Math.floor(Math.random() * ready.length)];
          fallbackLastShots.set(attacker.id, now);
          const targets = alive.filter((ship) => ship.id !== attacker.id);
          const target = targets[Math.floor(Math.random() * targets.length)];
          if (Math.random() <= 1 - CLASS_STATS[target.shipClass].dodge) {
            const [minDamage, maxDamage] = CLASS_STATS[attacker.shipClass].damage;
            target.hp = Math.max(0, target.hp - (minDamage + Math.random() * (maxDamage - minDamage)));
            if (target.hp <= 0 && target.alive) {
              target.alive = false;
              attacker.kills += 1;
              callbacksRef.current.onLog(`${attacker.name} zerstört ${target.name}`);
              callbacksRef.current.onSound("destroyed");
            }
            callbacksRef.current.onSnapshot(fallbackFleet.map((ship) => ({ ...ship })));
          }
        }, 80);
        cleanup = () => window.clearInterval(fallbackTimer);
        return;
      }

    const scene = new THREE.Scene();
    scene.fog = new THREE.FogExp2(0x010205, 0.0032);
    const camera = new THREE.PerspectiveCamera(55, 1, 0.1, 380);
    camera.position.set(0, 19, 56);
    camera.lookAt(0, 0, -5);

    let renderer: WebGLRenderer;
    try {
      renderer = new THREE.WebGLRenderer({ antialias: true, alpha: true, powerPreference: "high-performance" });
    } catch {
      mount.dataset.webgl = "unavailable";
      return;
    }
    mount.dataset.webgl = "ready";
    renderer.setPixelRatio(Math.min(window.devicePixelRatio, 1.8));
    renderer.outputColorSpace = THREE.SRGBColorSpace;
    renderer.toneMapping = THREE.ACESFilmicToneMapping;
    renderer.toneMappingExposure = 1.08;
    renderer.setClearColor(0x000000, 0);
    mount.appendChild(renderer.domElement);

    scene.add(new THREE.AmbientLight(0x8297a5, 0.72));
    scene.add(new THREE.HemisphereLight(0xd9f4ff, 0x101820, 1.05));
    const key = new THREE.DirectionalLight(0xe8f7ff, 4.9);
    key.position.set(24, 21, 18);
    scene.add(key);
    const cameraFill = new THREE.DirectionalLight(0x9bdfff, 2.1);
    cameraFill.position.set(-18, 5, 34);
    scene.add(cameraFill);
    const rim = new THREE.PointLight(0x6a79ff, 46, 68);
    rim.position.set(-23, 6, -22);
    scene.add(rim);

    const starCount = 3300;
    const positions = new Float32Array(starCount * 3);
    const starColors = new Float32Array(starCount * 3);
    for (let i = 0; i < starCount; i++) {
      const radius = 60 + Math.random() * 175;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      positions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      positions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      positions[i * 3 + 2] = radius * Math.cos(phi);
      const warmth = Math.random();
      starColors[i * 3] = warmth > 0.9 ? 1 : 0.66 + warmth * 0.22;
      starColors[i * 3 + 1] = warmth > 0.9 ? 0.78 : 0.76 + warmth * 0.16;
      starColors[i * 3 + 2] = warmth > 0.9 ? 0.6 : 1;
    }
    const starGeometry = new THREE.BufferGeometry();
    starGeometry.setAttribute("position", new THREE.BufferAttribute(positions, 3));
    starGeometry.setAttribute("color", new THREE.BufferAttribute(starColors, 3));
    const stars = new THREE.Points(starGeometry, new THREE.PointsMaterial({ vertexColors: true, size: 0.13, transparent: true, opacity: 0.68, depthWrite: false }));
    scene.add(stars);

    const brightCount = 170;
    const brightPositions = new Float32Array(brightCount * 3);
    for (let i = 0; i < brightCount; i++) {
      const radius = 68 + Math.random() * 150;
      const theta = Math.random() * Math.PI * 2;
      const phi = Math.acos(2 * Math.random() - 1);
      brightPositions[i * 3] = radius * Math.sin(phi) * Math.cos(theta);
      brightPositions[i * 3 + 1] = radius * Math.sin(phi) * Math.sin(theta);
      brightPositions[i * 3 + 2] = radius * Math.cos(phi);
    }
    const brightGeometry = new THREE.BufferGeometry();
    brightGeometry.setAttribute("position", new THREE.BufferAttribute(brightPositions, 3));
    const brightStars = new THREE.Points(brightGeometry, new THREE.PointsMaterial({ color: 0xeaf8ff, size: 0.36, transparent: true, opacity: 0.76, blending: THREE.AdditiveBlending, depthWrite: false }));
    scene.add(brightStars);

    const celestial = new THREE.Group();
    scene.add(celestial);

    const sunTexture = createGlowTexture("rgba(255,255,250,1)", "rgba(255,183,91,.86)");
    const sunHalo = new THREE.Sprite(new THREE.SpriteMaterial({ map: sunTexture, transparent: true, opacity: 0.4, blending: THREE.AdditiveBlending, depthWrite: false }));
    sunHalo.position.set(37, 23, -67);
    sunHalo.scale.set(72, 72, 1);
    sunHalo.renderOrder = 0;
    celestial.add(sunHalo);
    const sun = new THREE.Sprite(new THREE.SpriteMaterial({ map: sunTexture, transparent: true, blending: THREE.AdditiveBlending, depthWrite: false }));
    sun.position.set(37, 23, -67);
    sun.scale.set(52, 52, 1);
    sun.renderOrder = 1;
    celestial.add(sun);
    const sunLight = new THREE.PointLight(0xffd6a0, 235, 195, 1.32);
    sunLight.position.copy(sun.position);
    scene.add(sunLight);

    const planetGroup = new THREE.Group();
    planetGroup.position.set(-39, -5, -61);
    const planetTexture = createGasGiantTexture();
    const planet = new THREE.Mesh(
      new THREE.SphereGeometry(12.4, 72, 48),
      new THREE.MeshStandardMaterial({ map: planetTexture, bumpMap: planetTexture, bumpScale: 0.18, roughness: 0.96, metalness: 0 }),
    );
    planet.rotation.z = -0.17;
    planetGroup.add(planet);
    const atmosphere = new THREE.Mesh(
      new THREE.SphereGeometry(12.68, 60, 40),
      new THREE.MeshBasicMaterial({ color: 0x8ad7ec, transparent: true, opacity: 0.045, blending: THREE.AdditiveBlending, depthWrite: false, side: THREE.BackSide }),
    );
    planetGroup.add(atmosphere);
    celestial.add(planetGroup);

    const moonGroup = new THREE.Group();
    moonGroup.position.set(34, -11, -42);
    const moonTexture = createRockTexture();
    const moon = new THREE.Mesh(
      new THREE.SphereGeometry(4.8, 60, 38),
      new THREE.MeshStandardMaterial({ map: moonTexture, bumpMap: moonTexture, bumpScale: 0.34, roughness: 1, metalness: 0 }),
    );
    moonGroup.add(moon);
    celestial.add(moonGroup);

    const anomaly = new THREE.Group();
    anomaly.position.set(-4, 13, -72);
    anomaly.rotation.x = 1.04;
    const anomalyTexture = createGlowTexture("rgba(235,246,255,.96)", "rgba(91,90,255,.45)");
    const anomalyCount = 2100;
    const anomalyPositions = new Float32Array(anomalyCount * 3);
    const anomalyColors = new Float32Array(anomalyCount * 3);
    for (let i = 0; i < anomalyCount; i++) {
      const radius = Math.pow(Math.random(), 0.56) * 9.4 + 0.48;
      const arm = i % 3;
      const angle = radius * 1.52 + arm * (Math.PI * 2 / 3) + (Math.random() - 0.5) * 0.9;
      anomalyPositions[i * 3] = Math.cos(angle) * radius;
      anomalyPositions[i * 3 + 1] = (Math.random() - 0.5) * (0.25 + radius * 0.055);
      anomalyPositions[i * 3 + 2] = Math.sin(angle) * radius;
      const glow = 0.45 + Math.random() * 0.55;
      anomalyColors[i * 3] = 0.44 * glow;
      anomalyColors[i * 3 + 1] = 0.58 * glow;
      anomalyColors[i * 3 + 2] = glow;
    }
    const anomalyGeometry = new THREE.BufferGeometry();
    anomalyGeometry.setAttribute("position", new THREE.BufferAttribute(anomalyPositions, 3));
    anomalyGeometry.setAttribute("color", new THREE.BufferAttribute(anomalyColors, 3));
    const anomalyDust = new THREE.Points(anomalyGeometry, new THREE.PointsMaterial({ map: anomalyTexture, vertexColors: true, size: 0.42, transparent: true, opacity: 0.66, blending: THREE.AdditiveBlending, depthWrite: false, alphaTest: 0.01 }));
    anomaly.add(anomalyDust);
    const anomalyCore = new THREE.Mesh(new THREE.SphereGeometry(1.15, 40, 28), new THREE.MeshBasicMaterial({ color: 0x000104 }));
    anomaly.add(anomalyCore);
    const lensGlow = new THREE.Sprite(new THREE.SpriteMaterial({ map: anomalyTexture, transparent: true, opacity: 0.72, blending: THREE.AdditiveBlending, depthWrite: false }));
    lensGlow.scale.set(5.8, 5.8, 1);
    anomaly.add(lensGlow);
    const anomalyLight = new THREE.PointLight(0x6977ff, 54, 52, 1.8);
    anomaly.add(anomalyLight);
    celestial.add(anomaly);

    const asteroidDummy = new THREE.Object3D();
    const asteroidFields = [0, 1, 2].map((fieldIndex) => {
      const count = 36;
      const geometry = createAsteroidGeometry(fieldIndex + 1);
      const material = new THREE.MeshStandardMaterial({
        color: fieldIndex === 0 ? 0x8a8d8b : fieldIndex === 1 ? 0x6d7375 : 0x9a8f83,
        roughness: 0.98,
        metalness: 0.02,
        emissive: 0x080a0b,
        emissiveIntensity: 0.24,
        flatShading: true,
      });
      const mesh = new THREE.InstancedMesh(geometry, material, count);
      const data = Array.from({ length: count }, (_, index) => {
        const foreground = index < 4;
        const side = index % 2 === 0 ? -1 : 1;
        const position = foreground
          ? new THREE.Vector3(side * THREE.MathUtils.randFloat(34, 45), THREE.MathUtils.randFloat(-16, 16), THREE.MathUtils.randFloat(-8, 24))
          : new THREE.Vector3(THREE.MathUtils.randFloat(-55, 55), THREE.MathUtils.randFloat(-21, 19), THREE.MathUtils.randFloat(-84, -35));
        if (!foreground && Math.abs(position.x) < 13) position.x += position.x < 0 ? -17 : 17;
        const scale = foreground ? THREE.MathUtils.randFloat(1.7, 4.5) : THREE.MathUtils.randFloat(0.45, 2.55);
        const rotation = new THREE.Euler(Math.random() * Math.PI, Math.random() * Math.PI, Math.random() * Math.PI);
        const spin = new THREE.Vector3(
          THREE.MathUtils.randFloat(-0.055, 0.055),
          THREE.MathUtils.randFloat(-0.075, 0.075),
          THREE.MathUtils.randFloat(-0.045, 0.045),
        );
        const phase = Math.random() * Math.PI * 2;
        asteroidDummy.position.copy(position);
        asteroidDummy.rotation.copy(rotation);
        asteroidDummy.scale.setScalar(scale);
        asteroidDummy.updateMatrix();
        mesh.setMatrixAt(index, asteroidDummy.matrix);
        const tint = new THREE.Color().setHSL(0.07 + Math.random() * 0.05, 0.035 + Math.random() * 0.035, 0.56 + Math.random() * 0.2);
        mesh.setColorAt(index, tint);
        return { position, scale, rotation, spin, phase, drift: THREE.MathUtils.randFloat(0.08, 0.2) };
      });
      mesh.instanceMatrix.setUsage(THREE.DynamicDrawUsage);
      if (mesh.instanceColor) mesh.instanceColor.needsUpdate = true;
      mesh.castShadow = true;
      mesh.receiveShadow = true;
      mesh.frustumCulled = false;
      scene.add(mesh);
      return { mesh, data };
    });

    const createWaypoint = () => new THREE.Vector3(
      THREE.MathUtils.randFloat(-31, 31),
      THREE.MathUtils.randFloat(-8.5, 10.5),
      THREE.MathUtils.randFloat(-31, 21),
    );

    const source = combatantsRef.current.map((ship) => ({ ...ship }));
    const entities = source.map((entry, index) => {
      const angle = (index / Math.max(source.length, 1)) * Math.PI * 2;
      const radius = 14 + (index % 4) * 3.7;
      const wrapper = new THREE.Group();
      wrapper.position.set(Math.cos(angle) * radius, -6 + (index % 5) * 3.5, Math.sin(angle) * radius - 5);
      wrapper.rotation.y = -angle;
      const hull = createHull(entry.shipClass, CLASS_STATS[entry.shipClass].accent);
      hull.scale.setScalar((entry.shipClass === "frigate" ? 0.8 : 0.72) * shipScale);
      const label = createNameplate(entry);
      wrapper.add(hull, label.sprite);
      scene.add(wrapper);
      return {
        data: { ...entry },
        wrapper,
        label,
        velocity: new THREE.Vector3(),
        targetId: "",
        lastShot: performance.now() + Math.random() * 800,
        nextThink: 0,
        waypoint: createWaypoint(),
        nextWaypoint: performance.now() + 1800 + Math.random() * 4200,
        evadeUntil: 0,
        evasion: new THREE.Vector3(),
        rollSeed: Math.random() * Math.PI * 2,
      };
    });

    const lasers: ReturnType<typeof createLaser>[] = [];
    const impacts: ReturnType<typeof createImpact>[] = [];
    let finished = false;
    let winnerReported = false;

    const resize = () => {
      const { clientWidth, clientHeight } = mount;
      renderer.setSize(clientWidth, clientHeight, false);
      camera.aspect = clientWidth / Math.max(clientHeight, 1);
      camera.updateProjectionMatrix();
    };
    resize();
    const observer = new ResizeObserver(resize);
    observer.observe(mount);

    const snapshot = () => callbacksRef.current.onSnapshot(entities.map((entity) => ({ ...entity.data })));

    const fire = (attacker: typeof entities[number], target: typeof entities[number], now: number) => {
      const attackerStats = CLASS_STATS[attacker.data.shipClass];
      const targetStats = CLASS_STATS[target.data.shipClass];
      const shotDistance = attacker.wrapper.position.distanceTo(target.wrapper.position);
      const rangePenalty = THREE.MathUtils.clamp((shotDistance - 8) / 95, 0, 0.14);
      const hitChance = (target.data.shipClass === "frigate" ? 1 - targetStats.dodge : 0.88) - rangePenalty;
      attacker.lastShot = now;

      const incoming = target.wrapper.position.clone().sub(attacker.wrapper.position).normalize();
      const evadeSide = Math.random() > 0.5 ? 1 : -1;
      target.evasion.set(-incoming.z * evadeSide, (Math.random() - 0.35) * 0.9, incoming.x * evadeSide).normalize();
      target.evadeUntil = now + (target.data.shipClass === "frigate" ? 980 : 620);

      if (Math.random() > hitChance) {
        const missedEndpoint = target.wrapper.position.clone().addScaledVector(target.evasion, 3.6 + Math.random() * 2.8);
        lasers.push(createLaser(scene, attacker.wrapper.position, missedEndpoint, attackerStats.accent));
        return;
      }

      const [minDamage, maxDamage] = attackerStats.damage;
      const damage = minDamage + Math.random() * (maxDamage - minDamage);
      target.data.hp = Math.max(0, target.data.hp - damage);
      target.label.update(target.data.hp);
      lasers.push(createLaser(scene, attacker.wrapper.position, target.wrapper.position, attackerStats.accent));
      impacts.push(createImpact(scene, target.wrapper.position, attackerStats.accent));

      if (target.data.hp <= 0 && target.data.alive) {
        target.data.alive = false;
        attacker.data.kills += 1;
        callbacksRef.current.onLog(`${attacker.data.name} zerstört ${target.data.name}`);
        callbacksRef.current.onSound("destroyed");
        impacts.push(createImpact(scene, target.wrapper.position, 0xff7a32, true));
        window.setTimeout(() => { target.wrapper.visible = false; }, 460);
      }
      snapshot();
    };

    const fireVisual = (attacker: typeof entities[number], target: typeof entities[number], now: number) => {
      const attackerStats = CLASS_STATS[attacker.data.shipClass];
      attacker.lastShot = now;
      const incoming = target.wrapper.position.clone().sub(attacker.wrapper.position).normalize();
      const evadeSide = Math.random() > 0.5 ? 1 : -1;
      target.evasion.set(-incoming.z * evadeSide, (Math.random() - 0.35) * 0.9, incoming.x * evadeSide).normalize();
      target.evadeUntil = now + (target.data.shipClass === "frigate" ? 980 : 620);
      const hit = Math.random() < (target.data.shipClass === "frigate" ? 0.66 : 0.88);
      const endpoint = hit
        ? target.wrapper.position
        : target.wrapper.position.clone().addScaledVector(target.evasion, 3.6 + Math.random() * 2.8);
      lasers.push(createLaser(scene, attacker.wrapper.position, endpoint, attackerStats.accent));
      if (hit) impacts.push(createImpact(scene, target.wrapper.position, attackerStats.accent));
    };

    const clock = new THREE.Clock();
    let frame = 0;
    const animate = () => {
      frame = requestAnimationFrame(animate);
      const delta = Math.min(clock.getDelta(), 0.05);
      const time = clock.elapsedTime;
      const now = performance.now();
      if (readOnly) {
        const remoteFleet = new Map(combatantsRef.current.map((ship) => [ship.id, ship]));
        entities.forEach((entity) => {
          const remote = remoteFleet.get(entity.data.id);
          if (!remote) return;
          if (Math.ceil(remote.hp) !== Math.ceil(entity.data.hp)) entity.label.update(remote.hp);
          if (entity.data.alive && !remote.alive) impacts.push(createImpact(scene, entity.wrapper.position, 0xff7a32, true));
          entity.data = { ...remote };
          entity.wrapper.visible = remote.alive;
        });
      }
      stars.rotation.y = time * 0.0034;
      stars.rotation.x = Math.sin(time * 0.012) * 0.008;
      brightStars.rotation.y = -time * 0.0024;
      sun.scale.setScalar(51.8 + Math.sin(time * 0.48) * 0.8);
      sunHalo.scale.setScalar(72 + Math.sin(time * 0.38) * 1.1);
      (sunHalo.material as SpriteMaterial).opacity = 0.38 + Math.sin(time * 0.42) * 0.035;
      planet.rotation.y = time * 0.006;
      moon.rotation.y = -time * 0.011;
      anomalyDust.rotation.y = time * 0.045;
      anomaly.rotation.z = -0.18 + Math.sin(time * 0.13) * 0.025;
      (lensGlow.material as SpriteMaterial).opacity = 0.64 + Math.sin(time * 1.1) * 0.08;
      asteroidFields.forEach((field) => {
        field.data.forEach((asteroid, index) => {
          asteroid.rotation.x += asteroid.spin.x * delta;
          asteroid.rotation.y += asteroid.spin.y * delta;
          asteroid.rotation.z += asteroid.spin.z * delta;
          const parallax = asteroid.scale > 1.7 ? 0.65 : 0.28;
          asteroidDummy.position.set(
            asteroid.position.x + Math.sin(time * asteroid.drift + asteroid.phase) * parallax,
            asteroid.position.y + Math.cos(time * asteroid.drift * 0.72 + asteroid.phase) * parallax * 0.55,
            asteroid.position.z + Math.sin(time * asteroid.drift * 0.45 + asteroid.phase) * parallax * 0.35,
          );
          asteroidDummy.rotation.copy(asteroid.rotation);
          asteroidDummy.scale.setScalar(asteroid.scale);
          asteroidDummy.updateMatrix();
          field.mesh.setMatrixAt(index, asteroidDummy.matrix);
        });
        field.mesh.instanceMatrix.needsUpdate = true;
      });

      if ((phase === "battle" || phase === "registration") && !finished) {
        const combatActive = phase === "battle";
        const alive = entities.filter((entity) => entity.data.alive);
        if (!readOnly && combatActive && alive.length <= 1 && entities.length > 1) {
          finished = true;
          if (alive[0] && !winnerReported) {
            winnerReported = true;
            window.setTimeout(() => callbacksRef.current.onWinner({ ...alive[0].data }), 650);
          }
        }

        alive.forEach((entity) => {
          const speed = CLASS_STATS[entity.data.shipClass].speed;
          const flightPace = combatActive ? 1 : 0.28;
          const toWaypoint = entity.waypoint.clone().sub(entity.wrapper.position);
          if (toWaypoint.length() < 3.4 || now > entity.nextWaypoint) {
            entity.waypoint.copy(createWaypoint());
            entity.nextWaypoint = now + 2600 + Math.random() * 5200;
            toWaypoint.copy(entity.waypoint).sub(entity.wrapper.position);
          }

          const desiredVelocity = toWaypoint.normalize().multiplyScalar(speed * (entity.data.shipClass === "frigate" ? 1.08 : 0.95) * flightPace);
          const separation = new THREE.Vector3();
          alive.forEach((other) => {
            if (other.data.id === entity.data.id) return;
            const offset = entity.wrapper.position.clone().sub(other.wrapper.position);
            const gap = offset.length();
            if (gap > 0.01 && gap < 5.4) separation.add(offset.normalize().multiplyScalar((5.4 - gap) * 0.52));
          });
          desiredVelocity.addScaledVector(separation, flightPace);
          if (combatActive && now < entity.evadeUntil) {
            desiredVelocity.addScaledVector(entity.evasion, speed * (entity.data.shipClass === "frigate" ? 2.25 : 1.35));
          }
          entity.velocity.lerp(desiredVelocity, Math.min(1, delta * (entity.data.shipClass === "frigate" ? 2.6 : 1.9)));
          entity.wrapper.position.addScaledVector(entity.velocity, delta);

          let hitBoundary = false;
          if (entity.wrapper.position.x < -32 || entity.wrapper.position.x > 32) {
            entity.wrapper.position.x = THREE.MathUtils.clamp(entity.wrapper.position.x, -32, 32);
            entity.velocity.x *= -0.78;
            hitBoundary = true;
          }
          if (entity.wrapper.position.y < -9.5 || entity.wrapper.position.y > 11.5) {
            entity.wrapper.position.y = THREE.MathUtils.clamp(entity.wrapper.position.y, -9.5, 11.5);
            entity.velocity.y *= -0.78;
            hitBoundary = true;
          }
          if (entity.wrapper.position.z < -32 || entity.wrapper.position.z > 22) {
            entity.wrapper.position.z = THREE.MathUtils.clamp(entity.wrapper.position.z, -32, 22);
            entity.velocity.z *= -0.78;
            hitBoundary = true;
          }
          if (hitBoundary) {
            entity.waypoint.copy(createWaypoint());
            entity.nextWaypoint = now + 2200 + Math.random() * 3600;
          }

          if (!combatActive) {
            if (entity.velocity.lengthSq() > 0.01) {
              entity.wrapper.rotation.y = -Math.atan2(entity.velocity.z, entity.velocity.x);
              entity.wrapper.rotation.z = THREE.MathUtils.lerp(entity.wrapper.rotation.z, -entity.velocity.y * 0.045, delta * 2.2);
            }
            return;
          }

          let target = entities.find((candidate) => candidate.data.id === entity.targetId && candidate.data.alive);
          const weaponRange = entity.data.shipClass === "frigate" ? 21 : 25;
          if (target && entity.wrapper.position.distanceTo(target.wrapper.position) > weaponRange * 1.18) target = undefined;
          if (!target || now > entity.nextThink) {
            const candidates = alive
              .filter((candidate) => candidate.data.id !== entity.data.id && entity.wrapper.position.distanceTo(candidate.wrapper.position) <= weaponRange)
              .sort((a, b) => entity.wrapper.position.distanceTo(a.wrapper.position) - entity.wrapper.position.distanceTo(b.wrapper.position));
            target = candidates.length ? candidates[Math.floor(Math.random() * Math.min(candidates.length, 3))] : undefined;
            if (!target && Math.random() < 0.34) {
              const contacts = alive
                .filter((candidate) => candidate.data.id !== entity.data.id)
                .sort((a, b) => entity.wrapper.position.distanceTo(a.wrapper.position) - entity.wrapper.position.distanceTo(b.wrapper.position));
              const contact = contacts[0];
              if (contact) {
                entity.waypoint.set(
                  THREE.MathUtils.clamp(contact.wrapper.position.x + THREE.MathUtils.randFloat(-11, 11), -31, 31),
                  THREE.MathUtils.clamp(contact.wrapper.position.y + THREE.MathUtils.randFloat(-5, 5), -8.5, 10.5),
                  THREE.MathUtils.clamp(contact.wrapper.position.z + THREE.MathUtils.randFloat(-11, 11), -31, 21),
                );
                entity.nextWaypoint = now + 2400 + Math.random() * 2600;
              }
            }
            entity.targetId = target?.data.id ?? "";
            entity.nextThink = now + 480 + Math.random() * 920;
          }

          if (entity.velocity.lengthSq() > 0.06) {
            entity.wrapper.rotation.y = -Math.atan2(entity.velocity.z, entity.velocity.x);
            const evasionRoll = now < entity.evadeUntil ? (entity.data.shipClass === "frigate" ? 0.42 : 0.22) : 0;
            entity.wrapper.rotation.z = THREE.MathUtils.lerp(entity.wrapper.rotation.z, Math.sin(time * 5.2 + entity.rollSeed) * evasionRoll - entity.velocity.y * 0.055, delta * 4.2);
          }

          if (target) {
            const distance = entity.wrapper.position.distanceTo(target.wrapper.position);
            const fireDelay = (entity.data.shipClass === "frigate" ? frigateFireRate : cruiserFireRate) * 1000;
            if (distance <= weaponRange && now - entity.lastShot > fireDelay * (0.85 + Math.random() * 0.3)) {
              if (readOnly) fireVisual(entity, target, now);
              else fire(entity, target, now);
            }
          }
        });
      } else {
        entities.forEach((entity, index) => {
          entity.wrapper.position.y += Math.sin(time * 0.7 + index * 1.7) * delta * 0.08;
          entity.wrapper.rotation.z = Math.sin(time * 0.42 + index) * 0.055;
        });
      }

      for (let i = lasers.length - 1; i >= 0; i--) {
        const effect = lasers[i];
        const progress = (now - effect.born) / effect.duration;
        (effect.laser.material as LineBasicMaterial).opacity = Math.max(0, 1 - progress);
        if (progress >= 1) {
          scene.remove(effect.laser);
          effect.laser.geometry.dispose();
          (effect.laser.material as Material).dispose();
          lasers.splice(i, 1);
        }
      }
      for (let i = impacts.length - 1; i >= 0; i--) {
        const effect = impacts[i];
        const progress = (now - effect.born) / effect.duration;
        const scale = effect.large ? 1 + progress * 5.5 : 1 + progress * 2.2;
        effect.impact.scale.setScalar(scale);
        (effect.impact.material as MeshBasicMaterial).opacity = Math.max(0, 1 - progress);
        if (progress >= 1) {
          scene.remove(effect.impact);
          effect.impact.geometry.dispose();
          (effect.impact.material as Material).dispose();
          impacts.splice(i, 1);
        }
      }

      camera.position.x = Math.sin(time * 0.045) * 3.8;
      camera.position.y = 19 + Math.sin(time * 0.038) * 1.1;
      camera.position.z = 56 + Math.cos(time * 0.035) * 1.2;
      camera.lookAt(Math.sin(time * 0.022) * 1.8, -0.5, -5);
      renderer.render(scene, camera);
    };
    animate();

    cleanup = () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
      scene.traverse((object) => {
        if (object instanceof THREE.Mesh || object instanceof THREE.Points || object instanceof THREE.Line) {
          object.geometry?.dispose?.();
        }
        if (object instanceof THREE.Mesh || object instanceof THREE.Points || object instanceof THREE.Line || object instanceof THREE.Sprite) {
          const materials = Array.isArray(object.material) ? object.material : [object.material];
          materials.forEach((material) => {
            if ("map" in material && material.map instanceof THREE.Texture) material.map.dispose();
            material.dispose();
          });
        }
      });
      renderer.dispose();
      mount.replaceChildren();
    };
    }).catch(() => {
      if (!cancelled) mount.dataset.webgl = "unavailable";
    });

    return () => {
      cancelled = true;
      cleanup?.();
    };
  }, [fleetKey, battleId, phase, shipScale, frigateFireRate, cruiserFireRate, readOnly]);

  const positions = [
    [15, 25], [78, 22], [48, 47], [21, 67], [81, 60], [35, 78], [66, 33], [60, 73],
  ];

  return (
    <div className="arena-layer">
      <div ref={mountRef} className="space-canvas" aria-label="3D-Weltraumarena mit Fregatten und Cruisern" />
      <div className={`fallback-scene ${phase === "battle" ? "fallback-battle" : ""}`} aria-hidden="true">
        <div className="fallback-sun" />
        <div className="fallback-planet fallback-planet-ringed"><i /></div>
        <div className="fallback-planet fallback-moon" />
        <div className="fallback-anomaly"><i /><i /><i /><b /></div>
        <div className="fallback-asteroids">
          {Array.from({ length: 18 }, (_, index) => (
            <i key={index} style={{ left: `${(index * 37 + 5) % 94}%`, top: `${(index * 47 + 9) % 82}%`, width: `${7 + (index % 5) * 4}px`, animationDelay: `-${index * 0.63}s` }} />
          ))}
        </div>
        <div className="fallback-grid" />
        {combatants.slice(0, 8).map((entry, index) => (
          <div
            key={entry.id}
            className={`css-ship ${entry.shipClass} ${entry.alive ? "" : "destroyed"}`}
            style={{ left: `${positions[index][0]}%`, top: `${positions[index][1]}%`, animationDelay: `-${index * 0.72}s`, "--ship-scale": shipScale } as CSSProperties}
          >
            <i /><b>{entry.name}</b><span>{entry.shipClass === "frigate" ? "FRIGATTE" : "CRUISER"} · {Math.ceil(entry.hp)} HP</span>
          </div>
        ))}
      </div>
    </div>
  );
}

function formatClock(date: Date) {
  return date.toLocaleTimeString("de-DE", { minute: "2-digit", second: "2-digit" });
}

export default function Home() {
  const overlayOnly = window.location.pathname === "/overlay";
  const [combatants, setCombatants] = useState<Combatant[]>([]);
  const [phase, setPhase] = useState<Phase>("idle");
  const [battleId, setBattleId] = useState(0);
  const [round, setRound] = useState(1);
  const [countdown, setCountdown] = useState(3);
  const [winner, setWinner] = useState<Combatant | null>(null);
  const [winnerAllTimeWins, setWinnerAllTimeWins] = useState(0);
  const [claimStatus, setClaimStatus] = useState<ClaimStatus>("none");
  const [claimSeconds, setClaimSeconds] = useState(60);
  const [soundOn, setSoundOn] = useState(true);
  const [controlOpen, setControlOpen] = useState(!overlayOnly);
  const [debugOpen, setDebugOpen] = useState(false);
  const [joinName, setJoinName] = useState("");
  const [chatSender, setChatSender] = useState("");
  const [incomingChatText, setIncomingChatText] = useState("");
  const [channel, setChannel] = useState("savox76");
  const [shipScale, setShipScale] = useState(0.65);
  const [joinCommand, setJoinCommand] = useState("!join");
  const [arenaTitle, setArenaTitle] = useState("VOID ARENA");
  const [frigateFireRate, setFrigateFireRate] = useState<number>(BALANCED_FIRE_RATES.frigate);
  const [cruiserFireRate, setCruiserFireRate] = useState<number>(BALANCED_FIRE_RATES.cruiser);
  const [battleHistory, setBattleHistory] = useState<BattleRecord[]>([]);
  const [simRounds, setSimRounds] = useState(250);
  const [simParticipants, setSimParticipants] = useState(24);
  const [simulationResult, setSimulationResult] = useState<SimulationResult | null>(null);
  const [twitchStatus, setTwitchStatus] = useState<TwitchStatus>(EMPTY_TWITCH_STATUS);
  const [backendSettings, setBackendSettings] = useState<BackendSettings>(DEFAULT_BACKEND_SETTINGS);
  const [twitchMessage, setTwitchMessage] = useState("");
  const [integrationMessage, setIntegrationMessage] = useState("");
  const [updateStatus, setUpdateStatus] = useState<UpdateStatus>({ available: false });
  const [appVersion, setAppVersion] = useState("0.2.10");
  const [overlayConnectionCount, setOverlayConnectionCount] = useState(0);
  const [winnerLeaders, setWinnerLeaders] = useState<WinnerLeader[]>([]);
  const [arenaReady, setArenaReady] = useState(false);
  const [clientId] = useState(() => typeof crypto.randomUUID === "function" ? crypto.randomUUID() : `client-${Date.now()}-${Math.random()}`);
  const socketRef = useRef<WebSocket | null>(null);
  const soundOnRef = useRef(soundOn);
  const arenaStateRef = useRef<ArenaStateMessage | null>(null);
  const testModeRef = useRef(false);
  const activeRoundIdRef = useRef<string | null>(null);
  const hasRestoredArenaRef = useRef(false);
  const arenaRestoreHandlerRef = useRef<(state: ArenaStateMessage | null) => void>(() => undefined);
  const chatCommandCooldownsRef = useRef(new Map<string, number>());
  const countdownTimerRef = useRef<number | null>(null);
  const claimTimerRef = useRef<number | null>(null);
  const battleStartedAtRef = useRef<number | null>(null);
  const incomingChatHandlerRef = useRef<(sender: string, message: string) => void>(() => undefined);
  const [logs, setLogs] = useState<{ time: string; message: string }[]>([
    { time: "SYS", message: "Derzeit kein Giveaway aktiv" },
  ]);
  const [chatMessages, setChatMessages] = useState<{ time: string; message: string }[]>([
    { time: "SYS", message: "Derzeit ist kein Giveaway aktiv." },
  ]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      const storedChannel = window.localStorage.getItem("savox-twitch-channel");
      if (storedChannel) setChannel(storedChannel);
      const storedScale = Number(window.localStorage.getItem("savox-ship-scale"));
      if (storedScale >= 0.45 && storedScale <= 1) setShipScale(storedScale);
      const storedCommand = window.localStorage.getItem("savox-join-command");
      if (storedCommand) setJoinCommand(storedCommand);
      const storedTitle = window.localStorage.getItem("savox-arena-title");
      if (storedTitle) setArenaTitle(storedTitle);
      const storedFrigateRate = Number(window.localStorage.getItem("savox-frigate-fire-rate"));
      if (storedFrigateRate >= 0.2 && storedFrigateRate <= 8) setFrigateFireRate(storedFrigateRate);
      const storedCruiserRate = Number(window.localStorage.getItem("savox-cruiser-fire-rate"));
      if (storedCruiserRate >= 0.2 && storedCruiserRate <= 8) setCruiserFireRate(storedCruiserRate);
      const storedSound = window.localStorage.getItem("savox-sound-on");
      if (storedSound !== null) setSoundOn(storedSound === "true");
      const storedHistory = window.localStorage.getItem("savox-battle-history");
      if (storedHistory) {
        try {
          const parsed = JSON.parse(storedHistory) as BattleRecord[];
          if (Array.isArray(parsed)) setBattleHistory(parsed.slice(0, 100));
        } catch {
          window.localStorage.removeItem("savox-battle-history");
        }
      }
    }, 0);
    return () => window.clearTimeout(timer);
  }, []);

  useEffect(() => {
    if (overlayOnly) return;
    let active = true;
    fetch("/api/stats/winners")
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Statistik nicht erreichbar")))
      .then((payload: WinnerLeader[]) => {
        if (active) setWinnerLeaders(payload);
      })
      .catch(() => undefined);
    return () => { active = false; };
  }, [overlayOnly]);

  useEffect(() => {
    let active = true;
    Promise.all([
      fetch("/api/settings").then((response) => response.ok ? response.json() : Promise.reject(new Error("Einstellungen nicht erreichbar"))),
      fetch("/api/status").then((response) => response.ok ? response.json() : Promise.reject(new Error("Status nicht erreichbar"))),
    ]).then(([settings, status]: [BackendSettings, { version: string; twitch: TwitchStatus; update: UpdateStatus }]) => {
      if (!active) return;
      setBackendSettings(settings);
      setChannel(settings.channel_login);
      setTwitchStatus(status.twitch);
      setUpdateStatus(status.update);
      setAppVersion(status.version);
    }).catch(() => {
      if (active) setIntegrationMessage("Lokaler Python-Server ist nicht erreichbar.");
    });
    return () => { active = false; };
  }, []);

  useEffect(() => () => {
    if (countdownTimerRef.current !== null) window.clearInterval(countdownTimerRef.current);
    if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
  }, []);

  const addLog = (message: string) => {
    setLogs((current) => [{ time: formatClock(new Date()), message }, ...current].slice(0, 7));
  };

  const recordChat = (message: string) => {
    setChatMessages((current) => [{ time: formatClock(new Date()), message }, ...current].slice(0, 6));
  };

  const postChat = (message: string) => {
    recordChat(message);
    if (twitchStatus.connected) {
      void fetch("/api/twitch/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message }),
      }).catch(() => undefined);
    }
  };

  const refreshWinnerLeaders = () => {
    if (overlayOnly) return;
    void fetch("/api/stats/winners")
      .then((response) => response.ok ? response.json() : Promise.reject(new Error("Statistik nicht erreichbar")))
      .then((payload: WinnerLeader[]) => setWinnerLeaders(payload))
      .catch(() => undefined);
  };

  const handleChatCommand = (sender: string, rawMessage: string) => {
    const [rawCommand, requestedName] = rawMessage.trim().split(/\s+/, 2);
    const command = rawCommand.toLocaleLowerCase();
    if (!["!wins", "!top3", "!giveaway"].includes(command)) return false;
    const cooldownKey = command === "!wins" ? `${command}:${sender.toLocaleLowerCase()}` : command;
    const now = Date.now();
    if (now - (chatCommandCooldownsRef.current.get(cooldownKey) ?? 0) < 5000) return true;
    if (chatCommandCooldownsRef.current.size > 500) chatCommandCooldownsRef.current.clear();
    chatCommandCooldownsRef.current.set(cooldownKey, now);
    if (command === "!wins") {
      const target = (requestedName || sender).replace(/^@/, "").slice(0, 25);
      void fetch(`/api/stats/winner?name=${encodeURIComponent(target)}`)
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("Statistik nicht erreichbar")))
        .then((pilot: WinnerLeader) => {
          postChat(`@${sender}: ${pilot.name || target} hat ${pilot.wins} ${pilot.wins === 1 ? "Sieg" : "Siege"} aus ${pilot.participations} ${pilot.participations === 1 ? "Teilnahme" : "Teilnahmen"}.`);
        })
        .catch(() => postChat(`@${sender}, die Siegerstatistik ist gerade nicht erreichbar.`));
      return true;
    }
    if (command === "!top3") {
      void fetch("/api/stats/winners")
        .then((response) => response.ok ? response.json() : Promise.reject(new Error("Statistik nicht erreichbar")))
        .then((leaders: WinnerLeader[]) => {
          setWinnerLeaders(leaders);
          const top = leaders.filter((pilot) => pilot.wins > 0).slice(0, 3);
          postChat(top.length
            ? `Alltime Top ${top.length}: ${top.map((pilot, index) => `${index + 1}. ${pilot.name} (${pilot.wins})`).join(" · ")}`
            : "Noch wurden keine Alltime-Siege aufgezeichnet.");
        })
        .catch(() => postChat("Die Siegerstatistik ist gerade nicht erreichbar."));
      return true;
    }
    if (command === "!giveaway") {
      const alive = combatants.filter((entry) => entry.alive).length;
      const status = phase === "idle"
        ? "Derzeit ist kein Giveaway aktiv."
        : phase === "registration"
          ? `Giveaway offen: ${combatants.length} Piloten angemeldet. Mit ${joinCommand} teilnehmen.`
          : phase === "countdown"
            ? `Die Anmeldung ist geschlossen. Das Gefecht startet in ${countdown}.`
            : phase === "battle"
              ? `Das Gefecht läuft: ${alive} von ${combatants.length} Piloten verbleiben.`
              : claimStatus === "pending"
                ? `Gewinner ist @${winner?.name ?? "unbekannt"}. Der Claim läuft noch ${claimSeconds} Sekunden.`
                : claimStatus === "claimed"
                  ? `@${winner?.name ?? "Der Gewinner"} hat den Gewinn bestätigt.`
                  : "Der Gewinn wurde nicht rechtzeitig geclaimt. Ein Rematch ist möglich.";
      postChat(status);
      return true;
    }
    return false;
  };

  const recordRoundParticipants = (names: string[], roundId: string) => {
    if (testModeRef.current) return;
    void fetch("/api/stats/participants", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ names, round_id: roundId }),
    }).then((response) => {
      if (!response.ok) throw new Error("Teilnahmen konnten nicht gespeichert werden");
      refreshWinnerLeaders();
    }).catch(() => undefined);
  };

  const emitSoundCue = (cue: ArenaSoundCue) => {
    if (overlayOnly || !soundOnRef.current || socketRef.current?.readyState !== WebSocket.OPEN) return;
    socketRef.current.send(JSON.stringify({ type: "arena.sound", payload: { origin: clientId, cue } }));
  };

  const toggleSound = () => {
    if (overlayOnly) return;
    const next = !soundOn;
    soundOnRef.current = next;
    setSoundOn(next);
    window.localStorage.setItem("savox-sound-on", String(next));
    playArenaSound("toggle");
    if (next) {
      emitSoundCue("toggle");
    }
  };

  const registerParticipantName = (rawName: string) => {
    const clean = rawName.trim().replace(/^@/, "").slice(0, 24);
    if (!clean || phase !== "registration") return;
    if (combatants.some((entry) => entry.name.toLocaleLowerCase() === clean.toLocaleLowerCase())) {
      postChat(`@${clean}, du bist bereits für dieses Giveaway angemeldet.`);
      return;
    }
    setCombatants((current) => balanceFleet([...current.map((entry) => entry.name), clean]));
    addLog(`${clean} tritt dem Giveaway bei`);
    postChat(`@${clean}, du nimmst am Giveaway teil. Viel Glück!`);
  };

  const addParticipant = (event: FormEvent) => {
    event.preventDefault();
    registerParticipantName(joinName);
    setJoinName("");
  };

  const expireClaim = (winnerName: string) => {
    setClaimStatus("expired");
    addLog(`${winnerName} hat den Gewinn nicht geclaimt`);
    postChat(`@${winnerName} hat nicht rechtzeitig geantwortet. Eine neue Runde kann ohne Neuanmeldung gestartet werden.`);
  };

  const startClaimCountdown = (winnerName: string, initialSeconds = 60) => {
    if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
    claimTimerRef.current = null;
    let remaining = Math.max(0, Math.min(60, initialSeconds));
    setClaimSeconds(remaining);
    if (remaining <= 0) {
      expireClaim(winnerName);
      return;
    }
    claimTimerRef.current = window.setInterval(() => {
      remaining -= 1;
      setClaimSeconds(Math.max(0, remaining));
      if (remaining <= 0) {
        if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
        claimTimerRef.current = null;
        expireClaim(winnerName);
      }
    }, 1000);
  };

  const confirmClaim = (sender: string) => {
    if (phase !== "winner" || claimStatus !== "pending" || !winner || sender.toLocaleLowerCase() !== winner.name.toLocaleLowerCase()) return false;
    if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
    claimTimerRef.current = null;
    setClaimStatus("claimed");
    addLog(`${winner.name} hat den Gewinn geclaimt`);
    postChat(`@${winner.name} hat den Gewinn erfolgreich geclaimt!`);
    emitSoundCue("claim");
    return true;
  };

  const submitIncomingChat = (event: FormEvent) => {
    event.preventDefault();
    const sender = chatSender.trim().replace(/^@/, "").slice(0, 24);
    const message = incomingChatText.trim().slice(0, 140);
    if (!sender || !message) return;
    recordChat(`@${sender}: ${message}`);
    if (phase === "winner") confirmClaim(sender);
    if (handleChatCommand(sender, message)) {
      setIncomingChatText("");
      return;
    }
    if (phase === "registration" && message.toLocaleLowerCase() === joinCommand.toLocaleLowerCase()) registerParticipantName(sender);
    setIncomingChatText("");
  };

  const removeParticipant = (id: string) => {
    if (phase !== "registration") return;
    setCombatants((current) => balanceFleet(current.filter((entry) => entry.id !== id).map((entry) => entry.name)));
  };

  const startGiveaway = () => {
    testModeRef.current = false;
    activeRoundIdRef.current = null;
    battleStartedAtRef.current = null;
    if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
    claimTimerRef.current = null;
    setCombatants([]);
    setWinner(null);
    setWinnerAllTimeWins(0);
    setClaimStatus("none");
    setClaimSeconds(60);
    setPhase("registration");
    setControlOpen(false);
    addLog("Giveaway gestartet – Anmeldung offen");
    postChat(`Giveaway gestartet! Schreibe ${joinCommand}, um teilzunehmen.`);
  };

  const loadTestFleet = (count: number) => {
    if (phase === "battle" || phase === "countdown") return;
    if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
    claimTimerRef.current = null;
    testModeRef.current = true;
    activeRoundIdRef.current = null;
    battleStartedAtRef.current = null;
    setCombatants(balanceFleet(createTestNames(count)));
    setWinner(null);
    setWinnerAllTimeWins(0);
    setClaimStatus("none");
    setClaimSeconds(60);
    setPhase("registration");
    addLog(`Test-Giveaway mit ${count} Piloten geladen`);
    postChat(`Test-Giveaway gestartet: ${count} Teilnehmer sind angemeldet.`);
  };

  const launchBattle = (withSound = true) => {
    battleStartedAtRef.current = Date.now();
    setPhase("battle");
    setBattleId((value) => value + 1);
    addLog("Kampf freigegeben");
    if (withSound) emitSoundCue("battle");
  };

  const runBattleCountdown = (initialCountdown = 3, withSound = true) => {
    let remaining = Math.max(0, Math.min(3, initialCountdown));
    setCountdown(remaining);
    setPhase("countdown");
    if (withSound && remaining > 0) emitSoundCue("countdown");
    if (countdownTimerRef.current !== null) window.clearInterval(countdownTimerRef.current);
    if (remaining <= 0) {
      countdownTimerRef.current = null;
      launchBattle(withSound);
      return;
    }
    countdownTimerRef.current = window.setInterval(() => {
      remaining -= 1;
      setCountdown(Math.max(0, remaining));
      if (withSound && remaining > 0) emitSoundCue("countdown");
      if (remaining <= 0) {
        if (countdownTimerRef.current !== null) window.clearInterval(countdownTimerRef.current);
        countdownTimerRef.current = null;
        launchBattle(withSound);
      }
    }, 900);
  };

  const beginBattleCountdown = () => runBattleCountdown(3, true);

  const startBattle = () => {
    if (combatants.length < 2 || phase !== "registration") return;
    const roundId = `round-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    activeRoundIdRef.current = roundId;
    recordRoundParticipants(combatants.map((entry) => entry.name), roundId);
    setCombatants(balanceFleet(combatants.map((entry) => entry.name)));
    setWinner(null);
    setWinnerAllTimeWins(0);
    setClaimStatus("none");
    setControlOpen(false);
    addLog("Anmeldung geschlossen");
    postChat("Die Anmeldung ist geschlossen. Das Gefecht startet jetzt!");
    beginBattleCountdown();
  };

  const startRematch = () => {
    if (combatants.length < 2 || phase !== "winner" || claimStatus !== "expired") return;
    if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
    claimTimerRef.current = null;
    const roundId = `round-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    activeRoundIdRef.current = roundId;
    recordRoundParticipants(combatants.map((entry) => entry.name), roundId);
    setCombatants(balanceFleet(combatants.map((entry) => entry.name)));
    setWinner(null);
    setWinnerAllTimeWins(0);
    setClaimStatus("none");
    setClaimSeconds(60);
    setRound((value) => value + 1);
    setControlOpen(false);
    addLog("Neue Runde mit gleicher Teilnehmerliste");
    postChat("Der Gewinn wurde nicht geclaimt. Neue Runde mit denselben Teilnehmern – keine Neuanmeldung nötig!");
    beginBattleCountdown();
  };

  const endGiveaway = () => {
    if (countdownTimerRef.current !== null) window.clearInterval(countdownTimerRef.current);
    countdownTimerRef.current = null;
    if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
    claimTimerRef.current = null;
    battleStartedAtRef.current = null;
    testModeRef.current = false;
    activeRoundIdRef.current = null;
    setCombatants([]);
    setPhase("idle");
    setWinner(null);
    setWinnerAllTimeWins(0);
    setClaimStatus("none");
    setClaimSeconds(60);
    setRound((value) => value + 1);
    setBattleId((value) => value + 1);
    setControlOpen(false);
    setDebugOpen(false);
    addLog("Giveaway beendet");
    postChat("Derzeit ist kein Giveaway aktiv.");
  };

  const saveChannel = () => {
    const clean = channel.trim().replace(/^#/, "").toLocaleLowerCase();
    setChannel(clean);
    window.localStorage.setItem("savox-twitch-channel", clean);
    addLog(`Twitch-Kanal #${clean} vorgemerkt`);
  };

  const updateShipScale = (value: number) => {
    setShipScale(value);
    window.localStorage.setItem("savox-ship-scale", String(value));
  };

  const savePresentation = () => {
    const bareCommand = joinCommand.trim().replace(/^!+/, "").replace(/[^a-z0-9_]/gi, "").slice(0, 18);
    const cleanCommand = `!${(bareCommand || "join").toLocaleLowerCase()}`;
    const cleanTitle = arenaTitle.trim().slice(0, 28) || "VOID ARENA";
    setJoinCommand(cleanCommand);
    setArenaTitle(cleanTitle);
    window.localStorage.setItem("savox-join-command", cleanCommand);
    window.localStorage.setItem("savox-arena-title", cleanTitle);
    addLog(`Darstellung gespeichert: ${cleanTitle}`);
  };

  const saveIntegrationSettings = async (
    target: "integration" | "twitch" = "integration",
    showSuccess = true,
  ): Promise<BackendSettings | null> => {
    const setMessage = target === "twitch" ? setTwitchMessage : setIntegrationMessage;
    setMessage("Einstellungen werden gespeichert …");
    try {
      const response = await fetch("/api/settings", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          channel_login: channel,
          twitch_client_id: backendSettings.twitch_client_id,
          twitch_client_secret: null,
          server_port: backendSettings.server_port,
          github_owner: backendSettings.github_owner,
          github_repo: backendSettings.github_repo,
          auto_update: backendSettings.auto_update,
          open_browser_on_start: backendSettings.open_browser_on_start,
        }),
      });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Speichern fehlgeschlagen");
      const savedSettings = payload as BackendSettings;
      setBackendSettings(savedSettings);
      if (showSuccess) {
        setMessage(target === "twitch" ? "Twitch-Einstellungen lokal gespeichert." : "Sicher lokal gespeichert. Eine Portänderung wird nach dem Neustart aktiv.");
      }
      saveChannel();
      return savedSettings;
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "Speichern fehlgeschlagen");
      return null;
    }
  };

  const connectTwitch = async () => {
    if (!backendSettings.twitch_client_id.trim()) {
      setTwitchMessage("Bitte zuerst deine Twitch Client-ID eintragen. Ein Client-Secret ist nicht erforderlich.");
      document.getElementById("twitch-client-id")?.focus();
      return;
    }
    const authWindow = window.open("", "savox76-twitch", "width=720,height=820");
    if (!authWindow) {
      setTwitchMessage("Das Twitch-Fenster wurde vom Browser blockiert. Bitte Pop-ups für 127.0.0.1 erlauben.");
      return;
    }
    authWindow.document.title = "Savox76 · Twitch verbinden";
    authWindow.document.body.style.cssText = "background:#030812;color:#d7f7ff;font:16px system-ui;padding:40px";
    authWindow.document.body.textContent = "Twitch-Verbindung wird vorbereitet …";
    const saved = await saveIntegrationSettings("twitch", false);
    if (!saved) {
      authWindow.close();
      return;
    }
    setTwitchMessage("Twitch wurde geöffnet. Bitte dort den Zugriff bestätigen; das Tool verbindet den Chat danach automatisch.");
    authWindow.location.replace("/api/twitch/login");
  };

  const checkForUpdates = async () => {
    setIntegrationMessage("GitHub-Version wird geprüft …");
    try {
      const response = await fetch("/api/update/check");
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Updateprüfung fehlgeschlagen");
      setUpdateStatus(payload as UpdateStatus);
      setIntegrationMessage(payload.available ? `Version ${payload.version} ist verfügbar.` : "Diese Version ist aktuell.");
    } catch (error) {
      setIntegrationMessage(error instanceof Error ? error.message : "Updateprüfung fehlgeschlagen");
    }
  };

  const installUpdate = async () => {
    setIntegrationMessage("Update wird geladen und geprüft …");
    try {
      const response = await fetch("/api/update/install", { method: "POST" });
      const payload = await response.json();
      if (!response.ok) throw new Error(payload.detail || "Update konnte nicht gestartet werden");
      setIntegrationMessage("Update wird installiert. Das Tool startet anschließend neu.");
    } catch (error) {
      setIntegrationMessage(error instanceof Error ? error.message : "Update konnte nicht gestartet werden");
    }
  };

  useEffect(() => {
    incomingChatHandlerRef.current = (sender: string, message: string) => {
      recordChat(`@${sender}: ${message}`);
      if (phase === "winner") confirmClaim(sender);
      if (handleChatCommand(sender, message)) return;
      if (phase === "registration" && message.trim().toLocaleLowerCase() === joinCommand.toLocaleLowerCase()) {
        registerParticipantName(sender);
      }
    };
  });

  useEffect(() => {
    arenaRestoreHandlerRef.current = (remote: ArenaStateMessage | null) => {
      if (!remote) return;
      setCombatants(remote.combatants.map((entry) => ({ ...entry })));
      setBattleId(remote.battleId);
      setRound(remote.round);
      setCountdown(remote.countdown);
      setWinner(remote.winner ? { ...remote.winner } : null);
      setWinnerAllTimeWins(remote.winnerAllTimeWins);
      setClaimStatus(remote.claimStatus);
      setClaimSeconds(remote.claimSeconds);
      setLogs(remote.logs.map((entry) => ({ ...entry })));
      setArenaTitle(remote.arenaTitle);
      setJoinCommand(remote.joinCommand);
      setShipScale(remote.shipScale);
      setFrigateFireRate(remote.frigateFireRate);
      setCruiserFireRate(remote.cruiserFireRate);
      soundOnRef.current = remote.soundOn;
      setSoundOn(remote.soundOn);
      activeRoundIdRef.current = remote.activeRoundId;
      battleStartedAtRef.current = remote.battleStartedAt;
      testModeRef.current = remote.testMode;

      if (overlayOnly) {
        setPhase(remote.phase);
        return;
      }

      if (countdownTimerRef.current !== null) window.clearInterval(countdownTimerRef.current);
      if (claimTimerRef.current !== null) window.clearInterval(claimTimerRef.current);
      countdownTimerRef.current = null;
      claimTimerRef.current = null;
      const elapsedSeconds = remote.updatedAt > 0
        ? Math.max(0, Math.floor((Date.now() - remote.updatedAt) / 1000))
        : 0;
      if (remote.phase === "countdown") {
        const elapsedCountdownSteps = Math.floor(elapsedSeconds / 0.9);
        runBattleCountdown(Math.max(0, remote.countdown - elapsedCountdownSteps), false);
      } else {
        setPhase(remote.phase);
        if (remote.phase === "winner" && remote.claimStatus === "pending" && remote.winner) {
          startClaimCountdown(remote.winner.name, Math.max(0, remote.claimSeconds - elapsedSeconds));
        }
      }
    };
  });

  useEffect(() => {
    let socket: WebSocket | null = null;
    let reconnectTimer: number | null = null;
    let stopped = false;

    const connect = () => {
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${window.location.host}/ws/events`);
      socketRef.current = socket;
      socket.onmessage = (event) => {
        let message: { type: string; payload: Record<string, unknown> };
        try {
          message = JSON.parse(event.data) as { type: string; payload: Record<string, unknown> };
        } catch {
          return;
        }
        if (message.type === "chat.message") {
          if (!overlayOnly) incomingChatHandlerRef.current(String(message.payload.sender || ""), String(message.payload.message || ""));
        } else if (message.type === "twitch.status") {
          setTwitchStatus(message.payload as unknown as TwitchStatus);
        } else if (message.type === "update.status") {
          setUpdateStatus(message.payload as UpdateStatus);
        } else if (message.type === "update.installing") {
          setIntegrationMessage(`Version ${String(message.payload.version || "")} wird automatisch installiert …`);
        } else if (message.type === "update.error") {
          setIntegrationMessage(String(message.payload.message || "Updateprüfung fehlgeschlagen"));
        } else if (message.type === "overlay.status") {
          setOverlayConnectionCount(Number(message.payload.count || 0));
        } else if (message.type === "arena.restore") {
          const restored = (message.payload.state || null) as ArenaStateMessage | null;
          if (overlayOnly) {
            arenaRestoreHandlerRef.current(restored);
          } else if (!hasRestoredArenaRef.current) {
            hasRestoredArenaRef.current = true;
            arenaRestoreHandlerRef.current(restored);
          } else if (arenaStateRef.current && socket?.readyState === WebSocket.OPEN) {
            socket.send(JSON.stringify({ type: "arena.state", payload: arenaStateRef.current }));
          }
          setArenaReady(true);
        } else if (message.type === "arena.state" && overlayOnly) {
          const remote = message.payload as unknown as ArenaStateMessage;
          if (remote.origin === clientId) return;
          arenaRestoreHandlerRef.current(remote);
        } else if (message.type === "arena.sound" && overlayOnly) {
          const cue = String(message.payload.cue || "") as ArenaSoundCue;
          if (soundOnRef.current && ["toggle", "countdown", "battle", "destroyed", "winner", "claim"].includes(cue)) playArenaSound(cue);
        }
      };
      socket.onopen = () => {
        socket?.send(JSON.stringify({ type: "client.hello", payload: { origin: clientId, role: overlayOnly ? "overlay" : "control" } }));
      };
      socket.onclose = () => {
        if (socketRef.current === socket) socketRef.current = null;
        if (!stopped) reconnectTimer = window.setTimeout(connect, 2500);
      };
    };
    connect();
    const keepAlive = window.setInterval(() => {
      if (socket?.readyState === WebSocket.OPEN) socket.send("ping");
    }, 20000);
    return () => {
      stopped = true;
      window.clearInterval(keepAlive);
      if (reconnectTimer !== null) window.clearTimeout(reconnectTimer);
      socket?.close();
      socketRef.current = null;
    };
  }, [clientId, overlayOnly]);

  useEffect(() => {
    soundOnRef.current = soundOn;
    const state: ArenaStateMessage = {
      origin: clientId,
      phase,
      combatants,
      battleId,
      round,
      countdown,
      winner,
      winnerAllTimeWins,
      claimStatus,
      claimSeconds,
      logs,
      arenaTitle,
      joinCommand,
      shipScale,
      frigateFireRate,
      cruiserFireRate,
      soundOn,
      updatedAt: Date.now(),
      activeRoundId: activeRoundIdRef.current,
      battleStartedAt: battleStartedAtRef.current,
      testMode: testModeRef.current,
    };
    arenaStateRef.current = state;
    if (!overlayOnly && arenaReady && socketRef.current?.readyState === WebSocket.OPEN) {
      socketRef.current.send(JSON.stringify({ type: "arena.state", payload: state }));
    }
  }, [arenaReady, arenaTitle, battleId, claimSeconds, claimStatus, clientId, combatants, countdown, cruiserFireRate, frigateFireRate, joinCommand, logs, overlayOnly, phase, round, shipScale, soundOn, winner, winnerAllTimeWins]);

  const saveFireRates = () => {
    const frigateRate = clampFireRate(frigateFireRate, BALANCED_FIRE_RATES.frigate);
    const cruiserRate = clampFireRate(cruiserFireRate, BALANCED_FIRE_RATES.cruiser);
    setFrigateFireRate(frigateRate);
    setCruiserFireRate(cruiserRate);
    window.localStorage.setItem("savox-frigate-fire-rate", String(frigateRate));
    window.localStorage.setItem("savox-cruiser-fire-rate", String(cruiserRate));
    setSimulationResult(null);
    addLog(`Zeitwerte gespeichert: ${frigateRate.toFixed(2)} s / ${cruiserRate.toFixed(2)} s`);
  };

  const applyBalancePreset = () => {
    setFrigateFireRate(BALANCED_FIRE_RATES.frigate);
    setCruiserFireRate(BALANCED_FIRE_RATES.cruiser);
    window.localStorage.setItem("savox-frigate-fire-rate", String(BALANCED_FIRE_RATES.frigate));
    window.localStorage.setItem("savox-cruiser-fire-rate", String(BALANCED_FIRE_RATES.cruiser));
    setSimulationResult(simulateBalanceBatch(500, 24, BALANCED_FIRE_RATES.frigate, BALANCED_FIRE_RATES.cruiser));
    addLog("Balance-Startwert aktiviert: 1,55 s / 2,35 s");
  };

  const runSimulation = () => {
    setSimulationResult(simulateBalanceBatch(simRounds, simParticipants, frigateFireRate, cruiserFireRate));
  };

  const clearBattleHistory = () => {
    setBattleHistory([]);
    window.localStorage.removeItem("savox-battle-history");
  };

  const handleWinner = (ship: Combatant) => {
    const durationSeconds = battleStartedAtRef.current === null ? 0 : (Date.now() - battleStartedAtRef.current) / 1000;
    battleStartedAtRef.current = null;
    const record: BattleRecord = {
      id: activeRoundIdRef.current ?? `round-${Date.now()}-${Math.random().toString(16).slice(2)}`,
      winnerName: ship.name,
      winnerClass: ship.shipClass,
      durationSeconds,
      participants: combatants.length,
      completedAt: new Date().toISOString(),
      frigateFireRate,
      cruiserFireRate,
    };
    setBattleHistory((current) => {
      const next = [record, ...current].slice(0, 100);
      window.localStorage.setItem("savox-battle-history", JSON.stringify(next));
      return next;
    });
    setWinner(ship);
    setWinnerAllTimeWins(0);
    setPhase("winner");
    setClaimStatus("pending");
    setClaimSeconds(60);
    setChatSender(ship.name);
    addLog(`${ship.name} gewinnt Runde ${round}`);
    postChat(`@${ship.name} gewinnt! Poste innerhalb von 60 Sekunden etwas im Chat, um den Gewinn zu claimen.`);
    emitSoundCue("winner");
    if (!testModeRef.current) {
      void fetch("/api/stats/winner", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: ship.name, record_id: record.id }),
      }).then(async (response) => {
        if (!response.ok) throw new Error("Siegerstatistik konnte nicht gespeichert werden");
        return response.json() as Promise<{ wins: number }>;
      }).then((payload) => {
        setWinnerAllTimeWins(payload.wins);
        refreshWinnerLeaders();
      }).catch(() => undefined);
    }
    startClaimCountdown(ship.name, 60);
  };

  const aliveCount = combatants.filter((entry) => entry.alive).length;
  const frigates = combatants.filter((entry) => entry.shipClass === "frigate").length;
  const cruisers = combatants.filter((entry) => entry.shipClass === "cruiser").length;
  const kills = combatants.reduce((sum, entry) => sum + entry.kills, 0);
  const phaseLabel = phase === "idle" ? "DERZEIT KEIN GIVEAWAY" : phase === "registration" ? "GIVEAWAY GESTARTET" : phase === "countdown" ? "ANMELDUNG GESCHLOSSEN" : phase === "battle" ? "GEFECHT AKTIV" : claimStatus === "pending" ? "CLAIM AUSSTEHEND" : claimStatus === "claimed" ? "GEWINN GECLAIMT" : "CLAIM ABGELAUFEN";
  const hudParticipants = [...combatants].reverse().filter((entry) => phase !== "battle" || entry.alive);
  const realFrigateWins = battleHistory.filter((record) => record.winnerClass === "frigate").length;
  const realCruiserWins = battleHistory.length - realFrigateWins;
  const averageRealDuration = battleHistory.length ? battleHistory.reduce((sum, record) => sum + record.durationSeconds, 0) / battleHistory.length : 0;
  const averageRealParticipants = battleHistory.length ? battleHistory.reduce((sum, record) => sum + record.participants, 0) / battleHistory.length : 0;
  const winnerNameLength = winner ? Array.from(winner.name).length : 0;
  const winnerCardWidth = Math.min(1040, 600 + Math.max(0, winnerNameLength - 10) * 32);
  const winnerNameFontSize = Math.max(27, 58 - Math.max(0, winnerNameLength - 12) * 2.35);

  return (
    <main className={`broadcast-shell phase-${phase} ${overlayOnly ? "overlay-only" : "control-surface"}`}>
      <div className="deep-space-backdrop" aria-hidden="true" />
      <SpaceArena combatants={combatants} battleId={battleId} phase={phase} shipScale={shipScale} frigateFireRate={frigateFireRate} cruiserFireRate={cruiserFireRate} readOnly={overlayOnly} onSnapshot={setCombatants} onLog={addLog} onWinner={handleWinner} onSound={emitSoundCue} />
      <div className="nebula nebula-cyan" />
      <div className="nebula nebula-amber" />
      <div className="scanlines" />

      <header className="topbar glass-panel">
        <div className="brand-lockup">
          <div className="brand-mark"><span>S</span></div>
          <div><p className="eyebrow">SAVOX76 // GIVEAWAY SYSTEM</p><h1>{arenaTitle}</h1></div>
        </div>
        <div className="status-cluster">
          <div className={`status-pill status-${phase}`}><i /> {phaseLabel}</div>
          <button className="icon-button" type="button" onClick={toggleSound} aria-label="Sound umschalten" title={soundOn ? "Sounds aktiv – zum Ausschalten klicken" : "Sounds aus – für Testton und OBS-Sounds einschalten"}>{soundOn ? "◖))" : "◖×"}</button>
          <button className={`debug-button ${debugOpen ? "active" : ""}`} type="button" onClick={() => { setControlOpen(false); setDebugOpen((value) => !value); }}>DEBUG</button>
          <button className="control-button" type="button" onClick={() => { setDebugOpen(false); setControlOpen(true); }}>CONTROL</button>
        </div>
      </header>

      <aside className="left-hud glass-panel">
        <div className="round-label"><span>R-{String(round).padStart(2, "0")}</span> {phase === "idle" ? "OFFLINE" : phase === "battle" ? "LIVE" : phase === "winner" ? "FINAL" : "BEREIT"}</div>
        <p className="panel-kicker">LIVE TELEMETRIE</p>
        <div className="metric-row"><span>TEILNEHMER</span><strong>{String(combatants.length).padStart(2, "0")}</strong></div>
        <div className="metric-row"><span>VERBLEIBEND</span><strong className="cyan">{String(aliveCount).padStart(2, "0")}</strong></div>
        <div className="metric-row"><span>ABSCHÜSSE</span><strong>{String(kills).padStart(2, "0")}</strong></div>
        <div className="divider" />
        <p className="panel-kicker">KLASSENVERTEILUNG</p>
        <div className="class-stat"><div><span className="class-dot frigate" />FRIGATTEN</div><b>{frigates}</b></div>
        <div className="class-stat"><div><span className="class-dot cruiser" />CRUISER</div><b>{cruisers}</b></div>
        <div className="divider" />
        <p className="panel-kicker">GEFECHTSPROTOKOLL</p>
        <div className="combat-log">
          {logs.slice(0, 5).map((entry, index) => <p key={`${entry.time}-${index}`}><time>{entry.time}</time>{entry.message}</p>)}
        </div>
      </aside>

      <aside className={`right-hud participant-hud glass-panel ${phase === "battle" ? "participant-hud-compact" : ""}`}>
        <div className="participant-hud-head"><p className="panel-kicker">{phase === "battle" ? "VERBLEIBENDE PILOTEN" : "TEILNEHMERLISTE"}</p><strong>{hudParticipants.length}</strong></div>
        <div className="hud-participant-list">
          {hudParticipants.length === 0 && <p className="hud-empty">NOCH KEINE PILOTEN</p>}
          {hudParticipants.map((entry) => (
            <div className="hud-participant" key={entry.id}>
              <span className={`class-dot ${entry.shipClass}`} />
              <b>{entry.name}</b>
              <small>{phase === "battle" ? `${Math.ceil(entry.hp)} HP` : entry.shipClass === "frigate" ? "FRG" : "CR"}</small>
            </div>
          ))}
        </div>
      </aside>

      {phase === "countdown" && <div className="countdown-overlay"><span>GEFECHT STARTET</span><strong>{countdown}</strong></div>}
      {phase === "winner" && winner && (
        <div className={`winner-card glass-panel claim-${claimStatus}`} style={{ "--winner-card-width": `${winnerCardWidth}px`, "--winner-name-size": `${winnerNameFontSize}px` } as CSSProperties}>
          <p className="panel-kicker">{claimStatus === "pending" ? "GEWINN MUSS BESTÄTIGT WERDEN" : claimStatus === "claimed" ? "GEWINN ERFOLGREICH GECLAIMT" : "CLAIM-ZEIT ABGELAUFEN"}</p>
          <span className="winner-crown">◇</span>
          <h2>{winner.name}</h2>
          <p>{winner.shipClass === "frigate" ? "FRIGATTE" : "CRUISER"} · {winner.kills} ABSCHÜSSE · {Math.ceil(winner.hp)} HP{winnerAllTimeWins > 0 ? ` · ALLTIME-SIEG #${winnerAllTimeWins}` : ""}</p>
          {claimStatus === "pending" && <div className="claim-timer"><span>RESTZEIT</span><strong>00:{String(claimSeconds).padStart(2, "0")}</strong><small>@{winner.name} muss jetzt etwas im Chat posten.</small></div>}
          {claimStatus === "claimed" && <div className="claim-confirmed">✓ GEWINN BESTÄTIGT</div>}
          {claimStatus === "expired" && <p className="claim-expired-copy">Keine Antwort erhalten. Alle bisherigen Teilnehmer bleiben für die nächste Runde gespeichert.</p>}
          <div className="winner-actions">
            {claimStatus === "pending" && <button type="button" onClick={() => { setDebugOpen(false); setControlOpen(true); }}>CHAT-TEST ÖFFNEN</button>}
            {claimStatus === "expired" && <button className="rematch-action" type="button" onClick={startRematch}>NEUE RUNDE · GLEICHE TEILNEHMER</button>}
            {claimStatus !== "pending" && <button type="button" onClick={endGiveaway}>GIVEAWAY BEENDEN</button>}
          </div>
        </div>
      )}

      <section className="join-banner glass-panel">
        <div className="join-command"><span>TWITCH CHAT</span><strong>{phase === "idle" ? "OFF" : phase === "registration" ? joinCommand : phase === "battle" ? "LIVE" : phase === "winner" ? claimStatus === "pending" ? `0:${String(claimSeconds).padStart(2, "0")}` : claimStatus === "claimed" ? "OK" : "RE" : "LOCK"}</strong></div>
        <div className="join-copy">
          <b>{phase === "idle" ? "DERZEIT KEIN GIVEAWAY AKTIV" : phase === "registration" ? "GIVEAWAY GESTARTET — ANMELDUNG OFFEN" : phase === "battle" ? "FREE-FOR-ALL LÄUFT" : phase === "winner" ? claimStatus === "pending" ? `${winner?.name ?? "PILOT"} MUSS DEN GEWINN CLAIMEN` : claimStatus === "claimed" ? `${winner?.name ?? "PILOT"} HAT GECLAIMT` : "KEIN CLAIM — REMATCH BEREIT" : "ANMELDUNG GESCHLOSSEN"}</b>
          <p>{phase === "idle" ? "Starte das nächste Giveaway in der Streamer-Konsole." : phase === "registration" ? `Schreibe ${joinCommand} in den Chat. Angemeldete Schiffe fliegen bereits langsam durch das System.` : phase === "battle" ? "Jedes Schiff bewegt sich frei, weicht aus und sucht eigene Ziele." : phase === "winner" ? claimStatus === "pending" ? `@${winner?.name ?? "Gewinner"} hat 60 Sekunden Zeit, eine beliebige Chatnachricht zu senden.` : claimStatus === "claimed" ? "Der Gewinn wurde bestätigt und kann ausgegeben werden." : "Eine neue Runde kann mit der bisherigen Teilnehmerliste gestartet werden." : "Neue Teilnehmer können nicht mehr beitreten."}</p>
        </div>
        <div className="countdown"><span>RUNDE</span><strong>{String(round).padStart(2, "0")}</strong></div>
      </section>

      <div className={`debug-scrim ${debugOpen ? "open" : ""}`} onClick={() => setDebugOpen(false)} />
      <aside className={`debug-panel glass-panel ${debugOpen ? "open" : ""}`} aria-hidden={!debugOpen}>
        <div className="debug-head">
          <div><p className="panel-kicker">BALANCE LABOR</p><h2>LANGZEIT DEBUG</h2></div>
          <button type="button" onClick={() => setDebugOpen(false)} aria-label="Debug-Ansicht schließen">×</button>
        </div>

        <section className="debug-section">
          <div className="debug-section-title"><b>SCHUSSINTERVALLE</b><span>0,20–8,00 SEKUNDEN</span></div>
          <div className="debug-rate-grid">
            <label><span><i className="class-dot frigate" />FRIGATTE</span><input type="number" min="0.2" max="8" step="0.05" value={frigateFireRate} onChange={(event) => setFrigateFireRate(clampFireRate(Number(event.target.value), BALANCED_FIRE_RATES.frigate))} disabled={phase === "battle" || phase === "countdown"} /></label>
            <label><span><i className="class-dot cruiser" />CRUISER</span><input type="number" min="0.2" max="8" step="0.05" value={cruiserFireRate} onChange={(event) => setCruiserFireRate(clampFireRate(Number(event.target.value), BALANCED_FIRE_RATES.cruiser))} disabled={phase === "battle" || phase === "countdown"} /></label>
          </div>
          <div className="debug-rate-actions"><button className="debug-save" type="button" onClick={saveFireRates} disabled={phase === "battle" || phase === "countdown"}>ZEITWERTE SPEICHERN</button><button className="balance-preset" type="button" onClick={applyBalancePreset} disabled={phase === "battle" || phase === "countdown"}>BALANCE 1,55 / 2,35</button></div>
          <p className="debug-note balance-note">Empfohlener Startwert für die 3:1-Verteilung. Die Schnellsimulation liegt bei 24 Teilnehmern ungefähr bei 50:50.</p>
          {(phase === "battle" || phase === "countdown") && <p className="debug-note warning">Während eines Gefechts sind die Werte gesperrt, damit das Ergebnis vergleichbar bleibt.</p>}
        </section>

        <section className="debug-section">
          <div className="debug-section-title"><b>REALE TESTRUNDEN</b><span>LOKAL GESPEICHERT</span></div>
          <div className="debug-metrics">
            <div><span>RUNDEN</span><strong>{battleHistory.length}</strong></div>
            <div><span>Ø LAUFZEIT</span><strong>{averageRealDuration.toFixed(1)} s</strong></div>
            <div><span>Ø PILOTEN</span><strong>{averageRealParticipants.toFixed(1)}</strong></div>
            <div><span>KLASSENSIEGE</span><strong><em className="cyan-text">{realFrigateWins}</em> / <em className="amber-text">{realCruiserWins}</em></strong></div>
          </div>
          {battleHistory.length > 0 ? (
            <div className="debug-result-bar" aria-label={`${Math.round(realFrigateWins / battleHistory.length * 100)} Prozent Fregatten-Siege`}><i className="frigate-share" style={{ width: `${realFrigateWins / battleHistory.length * 100}%` }} /><i className="cruiser-share" /></div>
          ) : <p className="debug-note">Starte Testflotten aus der Control-Ansicht. Jede vollständig ausgespielte Runde wird hier protokolliert.</p>}
        </section>

        <section className="debug-section">
          <div className="debug-section-title"><b>SCHNELLSIMULATION</b><span>KLASSENBALANCE</span></div>
          <div className="debug-select-grid">
            <label><span>RUNDEN</span><select value={simRounds} onChange={(event) => setSimRounds(Number(event.target.value))}><option value={100}>100</option><option value={250}>250</option><option value={500}>500</option></select></label>
            <label><span>TEILNEHMER</span><select value={simParticipants} onChange={(event) => setSimParticipants(Number(event.target.value))}><option value={12}>12</option><option value={24}>24</option><option value={48}>48</option></select></label>
          </div>
          <button className="debug-run" type="button" onClick={runSimulation} disabled={phase === "battle" || phase === "countdown"}>SIMULATION STARTEN</button>
          <p className="debug-note">Rechnet Treffer, Schaden, Ausweichen und Schussintervalle in Sekunden durch. Flugwege und Reichweite bleiben für einen schnellen Klassenvergleich außen vor.</p>
          {simulationResult && (
            <div className="simulation-result">
              <div className="debug-result-bar"><i className="frigate-share" style={{ width: `${simulationResult.frigateWins / simulationResult.rounds * 100}%` }} /><i className="cruiser-share" /></div>
              <div className="simulation-legend"><span><i className="class-dot frigate" />FRIGATTE <b>{(simulationResult.frigateWins / simulationResult.rounds * 100).toFixed(1)} %</b></span><span><i className="class-dot cruiser" />CRUISER <b>{(simulationResult.cruiserWins / simulationResult.rounds * 100).toFixed(1)} %</b></span></div>
              <div className="simulation-totals"><span>Ø Laufzeit <b>{simulationResult.averageDuration.toFixed(1)} s</b></span><span>Ø Schüsse <b>{simulationResult.averageShots.toFixed(0)}</b></span></div>
            </div>
          )}
        </section>

        <section className="debug-section debug-history-section">
          <div className="debug-section-title"><b>LETZTE ERGEBNISSE</b><button type="button" onClick={clearBattleHistory} disabled={battleHistory.length === 0}>HISTORIE LÖSCHEN</button></div>
          <div className="debug-history">
            {battleHistory.length === 0 && <p className="debug-note">Noch keine abgeschlossene Testrunde.</p>}
            {battleHistory.slice(0, 8).map((record) => (
              <div className="debug-history-row" key={record.id}>
                <i className={`class-dot ${record.winnerClass}`} />
                <div><b>{record.winnerName}</b><span>{new Date(record.completedAt).toLocaleString("de-DE", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" })}</span></div>
                <strong>{record.durationSeconds.toFixed(1)} s</strong>
                <small>{record.participants} P · {record.frigateFireRate.toFixed(2)} / {record.cruiserFireRate.toFixed(2)}</small>
              </div>
            ))}
          </div>
        </section>
      </aside>

      <div className={`control-scrim ${controlOpen ? "open" : ""}`} onClick={() => setControlOpen(false)} />
      <aside className={`control-panel ${controlOpen ? "open" : ""}`} aria-hidden={!controlOpen}>
        <div className="control-head">
          <div><p className="panel-kicker">STREAMER KONSOLE</p><h2>VOID CONTROL</h2></div>
          <button type="button" onClick={() => setControlOpen(false)} aria-label="Steuerung schließen">×</button>
        </div>

        <section className="control-section">
          <div className="section-title"><span>01</span><div><b>TEILNEHMER</b><small>Demo-Chat und Flottenliste</small></div></div>
          <form className="join-form" onSubmit={addParticipant}>
            <input value={joinName} onChange={(event) => setJoinName(event.target.value)} placeholder="Chatter-Name simulieren" disabled={phase !== "registration"} aria-label="Chatter-Name" />
            <button type="submit" disabled={phase !== "registration"}>+ JOIN</button>
          </form>
          <div className="pilot-list">
            {[...combatants].reverse().map((entry) => (
              <div className="pilot-row" key={entry.id}>
                <span className={`class-dot ${entry.shipClass}`} />
                <b>{entry.name}</b>
                <small>{entry.shipClass === "frigate" ? "FRG" : "CR"}</small>
                <button type="button" onClick={() => removeParticipant(entry.id)} disabled={phase !== "registration"} aria-label={`${entry.name} entfernen`}>×</button>
              </div>
            ))}
          </div>
          <div className="test-fleet-actions">
            {[12, 24, 48].map((count) => <button key={count} className="secondary-action" type="button" onClick={() => loadTestFleet(count)} disabled={phase === "battle" || phase === "countdown"}>TEST {count}</button>)}
          </div>
          <p className="test-note">Mit TEST 24 oder TEST 48 kannst du die Darstellung mit mehr als zwölf Teilnehmern ohne Twitch prüfen.</p>
        </section>

        <section className="control-section">
          <div className="section-title"><span>02</span><div><b>TWITCH</b><small>EventSub-Chatverbindung über den lokalen Python-Server</small></div></div>
          <label className="field-label" htmlFor="channel">KANALNAME</label>
          <div className="channel-field">
            <span>#</span><input id="channel" value={channel} onChange={(event) => setChannel(event.target.value)} /><button type="button" onClick={() => void saveIntegrationSettings("twitch")}>SPEICHERN</button>
          </div>
          <div className="twitch-device-setup">
            <label htmlFor="twitch-client-id"><span>TWITCH CLIENT-ID</span><input id="twitch-client-id" value={backendSettings.twitch_client_id} onChange={(event) => setBackendSettings((current) => ({ ...current, twitch_client_id: event.target.value }))} placeholder="Aus der Twitch Developer Console" /></label>
            <a href="https://dev.twitch.tv/console/apps" target="_blank" rel="noreferrer">TWITCH-APP ANLEGEN ↗</a>
          </div>
          <p className="twitch-setup-note">Nur einmal nötig: Twitch-App als <b>Public Client</b> anlegen und die Client-ID einfügen. Kein Client-Secret. Falls Twitch eine Redirect URL verlangt: <b>http://localhost</b></p>
          <div className={`connection-note ${twitchStatus.connected ? "connected" : ""}`}><i /> {twitchStatus.connected ? "TWITCH LIVE VERBUNDEN" : "TWITCH NICHT VERBUNDEN"} <span>{twitchStatus.message}{twitchStatus.login ? ` · Anmeldung: ${twitchStatus.login}` : ""}</span></div>
          <div className={`connection-note overlay-connection ${overlayConnectionCount > 0 ? "connected" : ""}`}><i /> {overlayConnectionCount > 0 ? "OBS-OVERLAY VERBUNDEN" : "OBS-OVERLAY NICHT VERBUNDEN"}<span>{overlayConnectionCount > 0 ? `${overlayConnectionCount} aktive Overlay-Verbindung${overlayConnectionCount === 1 ? "" : "en"}` : "OBS-Browserquelle öffnen oder Quelle aktualisieren."}</span></div>
          <div className="integration-actions"><button type="button" onClick={() => void connectTwitch()}>{twitchStatus.connected ? "TWITCH NEU VERBINDEN" : "MIT TWITCH VERBINDEN"}</button></div>
          {twitchMessage && <p className="integration-message" aria-live="polite">{twitchMessage}</p>}
          <label className="field-label command-label" htmlFor="join-command">FREIER JOIN-BEFEHL</label>
          <div className="command-field"><input id="join-command" value={joinCommand} onChange={(event) => setJoinCommand(event.target.value)} placeholder="!join" /><button type="button" onClick={savePresentation}>SPEICHERN</button></div>
          <form className="incoming-chat-form" onSubmit={submitIncomingChat}>
            <p>EINGEHENDE CHATNACHRICHT SIMULIEREN</p>
            <div><input value={chatSender} onChange={(event) => setChatSender(event.target.value)} placeholder="Chatter-Name" aria-label="Absender der Chatnachricht" /><input value={incomingChatText} onChange={(event) => setIncomingChatText(event.target.value)} placeholder={phase === "winner" && claimStatus === "pending" ? "Beliebige Antwort zum Claimen" : joinCommand} aria-label="Chatnachricht" /><button type="submit">POSTEN</button></div>
            <small>{phase === "winner" && claimStatus === "pending" ? `Zum Testen ist @${winner?.name ?? "Gewinner"} bereits als Absender eingetragen.` : `Während der Anmeldung trägt ${joinCommand} den Absender ein.`}</small>
          </form>
          <div className="chat-preview">
            <p>LETZTE CHAT-EREIGNISSE</p>
            {chatMessages.slice(0, 4).map((entry, index) => <div key={`${entry.time}-${index}`}><time>{entry.time}</time><span>{entry.message}</span></div>)}
          </div>
        </section>

        <section className="control-section alltime-section">
          <div className="section-title"><span>03</span><div><b>ALLTIME-RANGLISTE</b><small>Reale Siege und Teilnahmen</small></div></div>
          <div className="alltime-list">
            {winnerLeaders.length === 0 && <p className="alltime-empty">Noch keine realen Giveaway-Ergebnisse gespeichert.</p>}
            {winnerLeaders.slice(0, 10).map((pilot, index) => (
              <div className="alltime-row" key={pilot.name.toLocaleLowerCase()}>
                <strong>{String(index + 1).padStart(2, "0")}</strong>
                <div><b>{pilot.name}</b><small>{pilot.last_win ? `Letzter Sieg ${new Date(pilot.last_win).toLocaleDateString("de-DE")}` : "Noch kein Sieg"}</small></div>
                <span><b>{pilot.wins}</b><small>SIEGE</small></span>
                <span><b>{pilot.participations}</b><small>RUNDEN</small></span>
              </div>
            ))}
          </div>
          <p className="test-note">Chatbefehle: !wins · !wins @Name · !top3 · !giveaway</p>
        </section>

        <section className="control-section compact-stats">
          <div><span className="class-dot frigate" /><b>FRIGATTE</b><small>100 HP · 8–12 DMG · {frigateFireRate.toFixed(2).replace(".", ",")} s</small></div>
          <div><span className="class-dot cruiser" /><b>CRUISER</b><small>180 HP · 25–32 DMG · {cruiserFireRate.toFixed(2).replace(".", ",")} s</small></div>
          <p>Die 3:1-Verteilung wird bei Kampfbeginn kryptografisch neu gemischt. Fregatten gleichen weniger HP durch Tempo und 34 % Ausweichchance aus.</p>
        </section>

        <section className="control-section visual-settings">
          <div className="section-title"><span>04</span><div><b>DARSTELLUNG</b><small>OBS-Ansicht der Flotte</small></div></div>
          <label className="field-label" htmlFor="arena-title">ARENA-NAME</label>
          <div className="command-field title-field"><input id="arena-title" value={arenaTitle} onChange={(event) => setArenaTitle(event.target.value)} maxLength={28} /><button type="button" onClick={savePresentation}>SPEICHERN</button></div>
          <div className="range-head"><label htmlFor="ship-size">SCHIFFSGRÖSSE</label><output>{Math.round(shipScale * 100)} %</output></div>
          <input id="ship-size" type="range" min="0.45" max="1" step="0.05" value={shipScale} onChange={(event) => updateShipScale(Number(event.target.value))} />
          <div className="range-labels"><span>KLEIN</span><span>STANDARD</span></div>
        </section>

        <section className="control-section update-settings">
          <div className="section-title"><span>05</span><div><b>GITHUB & UPDATES</b><small>Quellcode, Releases und automatische Aktualisierung</small></div></div>
          <div className="integration-grid">
            <label><span>GITHUB-BENUTZER</span><input value={backendSettings.github_owner} onChange={(event) => setBackendSettings((current) => ({ ...current, github_owner: event.target.value }))} /></label>
            <label><span>REPOSITORY</span><input value={backendSettings.github_repo} onChange={(event) => setBackendSettings((current) => ({ ...current, github_repo: event.target.value }))} /></label>
            <label><span>LOKALER SERVER-PORT</span><input type="number" min="1024" max="65535" value={backendSettings.server_port} onChange={(event) => setBackendSettings((current) => ({ ...current, server_port: Number(event.target.value) }))} /></label>
          </div>
          <p className="integration-note">Öffentliches Repository · Updateabruf ohne GitHub-Token · universelles Python-Paket<br />Portänderungen werden nach einem Neustart aktiv. Der neue Twitch-Geräte-Login benötigt keine Redirect-URL.</p>
          <label className="toggle-field"><input type="checkbox" checked={backendSettings.auto_update} onChange={(event) => setBackendSettings((current) => ({ ...current, auto_update: event.target.checked }))} /><span>Neue geprüfte Python-Releases automatisch installieren und neu starten</span></label>
          <div className={`update-card ${updateStatus.available ? "available" : ""}`}><div><span>INSTALLIERTE VERSION</span><b>v{appVersion}</b></div><p>{updateStatus.available ? `Version v${updateStatus.version} ist verfügbar.` : "Keine neuere geprüfte Version erkannt."}</p></div>
          <div className="integration-actions"><button type="button" onClick={() => void saveIntegrationSettings()}>EINSTELLUNGEN SPEICHERN</button><button type="button" onClick={checkForUpdates}>JETZT PRÜFEN</button>{updateStatus.available && <button className="update-now" type="button" onClick={installUpdate}>UPDATE INSTALLIEREN</button>}</div>
          {integrationMessage && <p className="integration-message">{integrationMessage}</p>}
        </section>

        <div className="control-actions">
          {phase === "idle" && <button className="primary-action" type="button" onClick={startGiveaway}>GIVEAWAY STARTEN</button>}
          {phase === "registration" && <button className="primary-action" type="button" onClick={startBattle} disabled={combatants.length < 2}>ANMELDUNG SCHLIESSEN & STARTEN</button>}
          {phase === "countdown" && <button className="primary-action" type="button" disabled>STARTSEQUENZ LÄUFT</button>}
          {phase === "winner" && claimStatus === "expired" && <button className="primary-action" type="button" onClick={startRematch}>NEUE RUNDE · GLEICHE TEILNEHMER</button>}
          {phase !== "idle" && <button className="danger-action" type="button" onClick={endGiveaway}>GIVEAWAY BEENDEN</button>}
        </div>
      </aside>

      <div className="corner corner-tl" /><div className="corner corner-tr" /><div className="corner corner-bl" /><div className="corner corner-br" />
    </main>
  );
}
