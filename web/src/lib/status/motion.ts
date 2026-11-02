import { useLayoutEffect, useRef, type RefObject } from "react";

import type { EdgeView, NodeView } from "./derive";
import { eventKey, type StatusEvent } from "./types";

/**
 * Motion only for facts that just arrived: each new fact gets exactly one cue, then the page is still again.
 * - a worker picks the request or a part up: the request's information flows along the edge to the worker;
 * - a review is claimed: the reviewer's chip slides onto its step;
 * - a submit, an approval or a decision: one dot travels the edge to the next step;
 * - a plan: the parts' rows rise in;
 * - any other change: the step it changed crossfades;
 * - a real heartbeat: one ping on the holding agent's ring.
 * Nothing loops and nothing moves without a fact. With reduced motion every cue is a 120 ms opacity change on the
 * step that changed. While live updates are paused, nothing moves.
 */

const EASE_STANDARD = "cubic-bezier(0.2, 0, 0, 1)";
const EASE_ENTER = "cubic-bezier(0, 0, 0, 1)";
const EASE_TRAVEL = "cubic-bezier(0.45, 0, 0.55, 1)";
const DOT_SPEED = 200; // CSS px per second along an edge

function target(host: HTMLElement, selector: string): HTMLElement | null {
  return host.querySelector<HTMLElement>(selector);
}

function fade(element: HTMLElement | null, reduced: boolean): Animation | null {
  if (!element) return null;
  return element.animate([{ opacity: 0.4 }, { opacity: 1 }], {
    duration: reduced ? 120 : 200,
    easing: EASE_STANDARD,
  });
}

function slideIn(element: HTMLElement | null, reduced: boolean): Animation | null {
  if (!element) return null;
  if (reduced) return fade(element, true);
  return element.animate(
    [
      { opacity: 0, transform: "translateX(-12px)" },
      { opacity: 1, transform: "translateX(0)" },
    ],
    { duration: 320, easing: EASE_STANDARD },
  );
}

function rise(element: HTMLElement | null, reduced: boolean): Animation | null {
  if (!element) return null;
  if (reduced) return fade(element, true);
  return element.animate(
    [
      { opacity: 0, transform: "translateY(4px)" },
      { opacity: 1, transform: "translateY(0)" },
    ],
    { duration: 200, easing: EASE_ENTER },
  );
}

function travel(host: HTMLElement, edge: EdgeView | undefined, tone: string, fallback: HTMLElement | null, reduced: boolean): Animation | null {
  const layer = target(host, "[data-motion=dots]");
  if (!edge || !layer || reduced) return fade(fallback, reduced);
  const dot = document.createElement("span");
  dot.className = `er-dot er-dot-${tone}`;
  dot.setAttribute("aria-hidden", "true");
  dot.style.left = `${edge.x1 - 6}px`;
  dot.style.top = `${edge.y1 - 6}px`;
  layer.appendChild(dot);
  const dx = edge.x2 - edge.x1;
  const dy = edge.y2 - edge.y1;
  const length = Math.hypot(dx, dy);
  const animation = dot.animate(
    [
      { transform: "translate(0, 0)", opacity: 1 },
      { transform: `translate(${dx}px, ${dy}px)`, opacity: 1 },
    ],
    { duration: Math.max(240, (length / DOT_SPEED) * 1000), easing: EASE_TRAVEL },
  );
  const remove = () => dot.remove();
  animation.addEventListener("finish", remove);
  animation.addEventListener("cancel", remove);
  return animation;
}

function ping(host: HTMLElement, reduced: boolean): Animation | null {
  const chips = host.querySelectorAll<HTMLElement>("[data-chip-kind=agent] .er-lease");
  const ring = chips[chips.length - 1];
  if (!ring) return null;
  if (reduced) return fade(ring, true);
  const halo = document.createElement("span");
  halo.className = "er-ping";
  halo.setAttribute("aria-hidden", "true");
  ring.appendChild(halo);
  const animation = halo.animate(
    [
      { opacity: 0.4, transform: "scale(1)" },
      { opacity: 0, transform: "scale(1.6)" },
    ],
    { duration: 600, easing: EASE_STANDARD },
  );
  const remove = () => halo.remove();
  animation.addEventListener("finish", remove);
  animation.addEventListener("cancel", remove);
  return animation;
}

/** The request's information, as a small labelled packet, flowing from one step to the worker that took it. */
function flow(host: HTMLElement, from: NodeView | undefined, to: NodeView | undefined, text: string, fallback: HTMLElement | null, reduced: boolean): Animation | null {
  const layer = target(host, "[data-motion=dots]");
  if (!from || !to || !layer || reduced) return fade(fallback, reduced);
  const packet = document.createElement("span");
  packet.className = "er-packet";
  packet.setAttribute("aria-hidden", "true");
  packet.textContent = text;
  const y = to.y + to.h / 2;
  const startX = from.x + from.w / 2;
  const endX = to.x + 8;
  packet.style.left = `${startX}px`;
  packet.style.top = `${y - 13}px`;
  layer.appendChild(packet);
  const distance = endX - startX;
  const animation = packet.animate(
    [
      { transform: "translate(0, 0)", opacity: 0 },
      { transform: `translate(${distance * 0.12}px, 0)`, opacity: 1, offset: 0.12 },
      { transform: `translate(${distance * 0.88}px, 0)`, opacity: 1, offset: 0.88 },
      { transform: `translate(${distance}px, 0)`, opacity: 0 },
    ],
    { duration: Math.max(600, (Math.abs(distance) / DOT_SPEED) * 1000), easing: EASE_TRAVEL },
  );
  const remove = () => packet.remove();
  animation.addEventListener("finish", remove);
  animation.addEventListener("cancel", remove);
  return animation;
}

/** The single cue for one fact. Returns the animation it started, or null when it had nothing to move. */
export function cueFor(
  host: HTMLElement,
  event: StatusEvent,
  view: { edges: EdgeView[]; nodes: NodeView[] },
  reduced: boolean,
  packetText: string,
): Animation | null {
  const n = event.part;
  const node = (id: string) => target(host, `[data-node="${id}"]`);
  const chip = (id: string) => target(host, `[data-chip="${id}"]`);
  const edge = (id: string) => view.edges.find((e) => e.id === id);
  const box = (id: string) => view.nodes.find((each) => each.id === id);
  switch (event.type) {
    case "received":
      return null;
    case "plan_claimed":
      return flow(host, box("request"), box("plan"), packetText, node("plan"), reduced);
    case "planned":
      return rise(target(host, "[data-motion=parts]"), reduced);
    case "work_claimed":
      return flow(host, box(`queue-${n}`), box(`worker-${n}`), packetText, node(`worker-${n}`), reduced);
    case "check_claimed":
      return chip(`review-chip-${n}`) ? slideIn(chip(`review-chip-${n}`), reduced) : fade(node(`review-${n}`), reduced);
    case "work_submitted":
      return travel(host, edge(`e-worker-${n}`), "noun", node(`review-${n}`) ?? node(`worker-${n}`), reduced);
    case "check_approved":
      return travel(host, edge(`e-review-${n}`), "real", node(`result-${n}`) ?? node(`review-${n}`), reduced);
    case "plan_released":
    case "blocked":
      return fade(node("plan"), reduced);
    case "work_released":
      return fade(node(`queue-${n}`), reduced);
    case "in_review":
    case "check_refused":
    case "check_sent_back":
      return fade(node(`review-${n}`), reduced);
    case "signoff_required":
    case "signed_off":
    case "delivered":
    case "published":
    case "decided":
      return fade(node(`result-${n}`), reduced);
    case "heartbeat":
      return ping(host, reduced);
    case "queued":
      return fade(node("plan"), reduced);
    case "library_added":
      return fade(node(`result-${n}`), reduced);
    case "closed":
    case "reopened":
    case "withdrawn":
      return fade(target(host, "[data-motion=overall]"), reduced);
  }
}

/**
 * Runs one cue per fact that is new since the last render. The first render, a replay that starts over and a
 * paused page move nothing.
 */
export function useStatusMotion(
  host: RefObject<HTMLElement | null>,
  events: StatusEvent[] | null,
  view: { edges: EdgeView[]; nodes: NodeView[] } | null,
  options: { reduced: boolean; frozen: boolean; packetText: string },
): void {
  const seen = useRef<string[] | null>(null);
  useLayoutEffect(() => {
    if (!events || !view) return;
    const keys = events.map(eventKey);
    const before = seen.current;
    seen.current = keys;
    if (before === null || options.frozen || !host.current) return;
    const previous = new Set(before);
    if (keys.length < before.length || !before.every((key) => keys.includes(key))) return;
    for (const event of events) {
      if (!previous.has(eventKey(event))) cueFor(host.current, event, view, options.reduced, options.packetText);
    }
  }, [events, view, host, options.frozen, options.reduced, options.packetText]);
}
