# job-lifecycle Specification

## Purpose

Job lifecycle for graph execution: `JobStore` `QUEUED → RUNNING → terminal` transitions plus per-node log accumulation, replacing the stub that short-circuits every job to `SUCCEEDED`.

## Requirements

### Requirement: Status transition to terminal state

A `GRAPH_EXECUTE` job MUST observe the transitions `QUEUED → RUNNING → SUCCEEDED` (on success) or `QUEUED → RUNNING → FAILED` (on failure). It MUST NOT jump straight from `QUEUED` to `SUCCEEDED`.

#### Scenario: Successful graph reaches SUCCEEDED

- GIVEN a valid graph that executes without error
- WHEN the job is submitted
- THEN the final snapshot has status `SUCCEEDED`

#### Scenario: Failing graph reaches FAILED

- GIVEN a graph that fails validation or execution
- WHEN the job is submitted
- THEN the final snapshot has status `FAILED` with an error message

#### Scenario: Intermediate RUNNING state is observable

- GIVEN a job that executes and completes within the request
- WHEN execution progresses
- THEN the job transitions through `RUNNING` before reaching a terminal state

### Requirement: Graph execution delegation

`InMemoryJobStore.submit()` MUST delegate `GRAPH_EXECUTE` jobs to the injected `GraphExecutor` rather than returning a canned success.

#### Scenario: Store delegates to executor

- GIVEN an `InMemoryJobStore` wired with an executor
- WHEN a `GRAPH_EXECUTE` job is submitted with a graph payload
- THEN the executor is invoked and its result fills the job snapshot

### Requirement: Per-node log accumulation

Logs emitted during execution MUST be accumulated on the job's `logs` field in order, replacing the single stub log line.

#### Scenario: Job logs contain per-node entries

- GIVEN a multi-node graph that executes successfully
- WHEN the job completes
- THEN `job.logs` contains one entry per node in execution order

### Requirement: Failure captures error detail

A failed job MUST populate `error` with a non-empty failure reason.

#### Scenario: Failed job includes error detail

- GIVEN a graph whose node raises during execution
- WHEN the job completes
- THEN `job.error` is non-empty and describes the failing node

### Requirement: Cancellation semantics preserved

`cancel()` MUST continue to mark a non-terminal job `CANCELLED` and return `False` for unknown or already-terminal jobs.

#### Scenario: Cancel non-terminal job

- GIVEN a job not yet terminal
- WHEN `cancel` is called
- THEN the job becomes `CANCELLED` and `cancel` returns `True`

#### Scenario: Cancel succeeded job returns False

- GIVEN a job already `SUCCEEDED`
- WHEN `cancel` is called
- THEN it returns `False` and the status is unchanged
