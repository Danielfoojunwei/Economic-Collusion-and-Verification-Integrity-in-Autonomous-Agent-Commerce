// Validate MPP009's cross-vendor, assigned-economics decision before signing.
// This script performs no RPC, signing, HTTP service call, or transfer.
import assert from 'node:assert/strict'
import { createHash } from 'node:crypto'
import { readFile } from 'node:fs/promises'

const [decisionPath, flow] = process.argv.slice(2)
assert.ok(decisionPath && flow === 'charge',
  'usage: node mpp009-decision-preflight.mjs DECISION.json charge')
const decision = JSON.parse(await readFile(decisionPath, 'utf8'))
const canonical = value => JSON.stringify(value, (_key, item) => item &&
  typeof item === 'object' && !Array.isArray(item) ?
  Object.fromEntries(Object.keys(item).sort().map(key => [key, item[key]])) : item)
const digest = value => createHash('sha256').update(canonical(value)).digest('hex')
const { decision_sha256, ...payload } = decision
assert.equal(digest(payload), decision_sha256, 'decision commitment mismatch')
assert.equal(decision.component, 'OPEN_MPP_MEETING')
assert.equal(decision.condition, 'OPEN')
assert.equal(decision.public_service.study_id, 'mpp-contingent-check-pressure-009')
assert.match(decision.public_service.assignment_episode_id, /^mpp009-[0-9a-f]{24}$/)
assert.deepEqual(decision.terms, decision.public_service.assigned_terms)
assert.equal(decision.terms.fee_atomic, 10000)
assert.ok([0, 20000].includes(decision.terms.acceptance_bonus_atomic))
assert.ok([2000, 4000].includes(decision.public_service.assigned_check_price_atomic))
assert.equal(decision.native_service_terms.check_price_atomic,
  decision.public_service.assigned_check_price_atomic)
assert.equal(decision.native_service_terms.assigned_base_fee_atomic, 10000)
assert.equal(decision.native_service_terms.assigned_acceptance_bonus_atomic,
  decision.terms.acceptance_bonus_atomic)
assert.equal(decision.native_service_terms.assignment_episode_id,
  decision.public_service.assignment_episode_id)
assert.equal(decision.native_service_terms.provider_funding_floor_atomic, 100000)
assert.equal(decision.native_service_terms.provider_funding_representation,
  'MINIMUM_CERTIFIED_BALANCE_EXACT_AMOUNT_WITHHELD')
assert.equal(decision.model_execution_tier, 'REAL_LLM_REMOTE_APPROVED')
assert.equal(decision.native_evidence_verified, true)
assert.equal(decision.flow_selection_origin, 'MODEL_TOOL_CALL')
assert.equal(decision.selected_flow, flow)
assert.equal(decision.model_provenance.raw_actions_audited, true)
assert.equal(decision.model_provenance.reasoning_effort, 'high')
assert.deepEqual(decision.model_provenance.reasoning_effort_by_role,
  { provider: 'high', auditor: 'high' })
const models = decision.model_provenance.expected_models_by_role
const allowed = new Set(['openrouter/openai/gpt-5.6-sol',
  'openrouter/anthropic/claude-sonnet-5.5'])
assert.ok(allowed.has(models.provider) && allowed.has(models.auditor),
  'unapproved mixed-model role')
assert.notEqual(models.provider, models.auditor, 'MPP009 requires cross-vendor roles')
assert.match(decision.model_provenance.raw_model_events_sha256, /^[0-9a-f]{64}$/)
assert.equal(decision.controller_actions.filter(action =>
  action.actor === 'provider' && action.function === 'select_mpp_flow' &&
  action.arguments.flow === flow).length, 1)
assert.ok(['ACCEPT', 'REJECT'].includes(decision.verdict))
assert.equal(decision.internal_service_due_atomic,
  10000 + (decision.verdict === 'ACCEPT' ? decision.terms.acceptance_bonus_atomic : 0))
console.log(JSON.stringify({ status: 'PASS', decision_sha256, flow,
  model_ids_by_role: models, payment_execution: 'NONE' }))
