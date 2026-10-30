import {
  HELP_DOOR,
  KIT_NOUNS,
  KIT_STEPS,
  KIT_VERBS,
  NGO_DOOR,
  PERSON_ONLY,
  STATUS_AS_OF,
  STATUS_LINES,
} from "../lib/marketplace";
import type { WorkflowStep } from "../lib/types";
import { AppLink } from "../router";
import { BoundaryBadge } from "./BoundaryBadge";

/** The two front doors: equal primary buttons, each with one plain line under it. */
export function FrontDoors() {
  return (
    <div className="er-doors" role="group" aria-label="Choose your side">
      {[HELP_DOOR, NGO_DOOR].map((door) => {
        const noteId = `door-note-${door.to.slice(1)}`;
        return (
          <div key={door.to} className="er-door">
            <AppLink to={door.to} className="er-btn-primary er-btn-door" aria-describedby={noteId}>
              {door.label}
            </AppLink>
            <p id={noteId} className="er-door-note">
              {door.note}
            </p>
          </div>
        );
      })}
    </div>
  );
}

/** Check, build, review, publish. */
export function KitSteps() {
  return (
    <ol className="er-steps">
      {KIT_STEPS.map((step) => (
        <li key={step.name}>
          <h3>{step.name}</h3>
          <p className="er-muted">{step.detail}</p>
        </li>
      ))}
    </ol>
  );
}

/** What a kit holds, split into nouns (the things) and verbs (the work). */
export function KitParts() {
  return (
    <div className="er-parts">
      <section className="er-card" aria-labelledby="kit-nouns-title">
        <span className="er-chip er-chip-assists">Nouns</span>
        <h3 id="kit-nouns-title">The things your agent uses</h3>
        <dl className="er-pieces">
          {KIT_NOUNS.map((piece) => (
            <div key={piece.name}>
              <dt>{piece.name}</dt>
              <dd>{piece.detail}</dd>
            </div>
          ))}
        </dl>
      </section>
      <section className="er-card" aria-labelledby="kit-verbs-title">
        <span className="er-chip er-chip-drafts">Verbs</span>
        <h3 id="kit-verbs-title">The work</h3>
        <dl className="er-pieces">
          {KIT_VERBS.map((piece) => (
            <div key={piece.name}>
              <dt>{piece.name}</dt>
              <dd>{piece.detail}</dd>
            </div>
          ))}
        </dl>
      </section>
    </div>
  );
}

/** The steps that never go to an agent. */
export function PersonOnlyList() {
  return (
    <ul className="er-person-list">
      {PERSON_ONLY.map((line) => (
        <li key={line}>{line}</li>
      ))}
    </ul>
  );
}

/** A kit's step map: what the agent drafts or helps with, and what stays with a person. */
export function StepMap({ steps }: { steps: WorkflowStep[] }) {
  return (
    <ul className="er-stepmap">
      {steps.map((step) => (
        <li key={step.id}>
          <BoundaryBadge boundary={step.boundary} />
          <span>{step.title}</span>
        </li>
      ))}
    </ul>
  );
}

/** The dated, honest status of the marketplace. */
export function StatusNote() {
  return (
    <section className="er-status" aria-labelledby="status-title" data-testid="status-note">
      <h2 id="status-title">Where things stand, {STATUS_AS_OF}</h2>
      <ul>
        {STATUS_LINES.map((line) => (
          <li key={line}>{line}</li>
        ))}
      </ul>
    </section>
  );
}
