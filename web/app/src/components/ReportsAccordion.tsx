// Thin re-export shim. RunView.tsx still imports `ReportsAccordion` and
// passes `reports={...}` — Task 11 will switch that call site over to
// `ReportsRecord` directly and delete this file. Do not delete before then
// (same retire-not-delete rule Task 9 applied to its own predecessor).
export { ReportsRecord as ReportsAccordion } from './research/ReportsRecord';
