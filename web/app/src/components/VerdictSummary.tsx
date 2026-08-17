// Thin re-export shim. The old plain-<dl> `VerdictSummary` markup is
// superseded by `TheCall` (web/app/src/components/research/TheCall.tsx),
// which ports the reskinned verdict card from web/design/research/index.html.
//
// RunView.tsx still imports `VerdictSummary` at this point in the plan
// (Task 9) — Task 11 is what switches that call site over to importing
// `TheCall` directly. Deleting this file now would break every task's build
// in between. Task 11 should delete this shim once it updates RunView's
// import — it exists to be removed, not preserved.
export { TheCall as VerdictSummary } from './research/TheCall';
