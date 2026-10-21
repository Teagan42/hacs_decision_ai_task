# AI Task: Generate Description

Adds a **Generate description** action, `ai_task.generate_description`, to Home Assistant's
built-in [AI Task](https://www.home-assistant.io/integrations/ai_task) integration.

You give it a prompt, some entities and/or devices, and optional typed questions. It sends the
current state of those entities to your AI Task entity and returns a free-text description plus
an answer to each question, checked against the question's type.

It works with any AI Task provider that supports **Generate data** (OpenAI, Anthropic, Google,
Ollama, …). You don't need to change the provider.

## Installation

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/teagan42/hacs_decision_ai_task`
   as an **Integration**.
2. Install **AI Task: Generate Description** and restart Home Assistant.
3. **Settings → Devices & services → Add integration → AI Task: Generate Description**.

Requires Home Assistant 2026.1 or newer and an AI Task entity that supports generating data.

## Usage

```yaml
action: ai_task.generate_description
data:
  task_name: bedtime check
  entity_id: ai_task.openai_ai_task # optional; defaults to the preferred AI Task entity
  prompt: Is the house ready for bed? Describe anything that still needs attention.
  entities:
    - lock.front_door
    - binary_sensor.garage_door
  devices:
    - 4f1c0a… # every enabled entity of the device is included
  questions:
    - type: boolean
      key: secure
      question: Is the house secure?
    - type: choice
      key: priority
      question: What needs attention first?
      options: [doors, lights, climate, nothing]
    - type: score
      key: readiness
      question: How ready is the house for bed?
      min: 0
      max: 10
response_variable: result
```

Response:

```yaml
conversation_id: 01JB…
description: The front door is unlocked and the garage door is open.
answers:
  secure: false
  priority: doors
  readiness: 3
```

### Questions

`questions` is a list of objects. Each one has a `type` that decides which other fields apply:

| `type`    | Answer                     | Extra fields                                                                 |
| --------- | -------------------------- | ---------------------------------------------------------------------------- |
| `boolean` | `true` / `false`           | none                                                                         |
| `choice`  | one option, or a list      | `options` (required, at least 2, unique), `multiple` (default `false`)       |
| `score`   | number within the range    | `min` (default `0`), `max` (default `10`), `step` (default `1`)              |

All types also accept:

- `question` (required): what to ask.
- `key`: where the answer goes under `answers`. If you leave it out, it's derived from the question
  text (`Is it on?` → `is_it_on`). `description` is reserved.
- `required` (default `true`): whether the model must answer.

If you set a field that doesn't belong to the type (for example `options` on a `boolean`), the
call fails. Scores whose `min`, `max` and `step` are all whole numbers come back as integers.

If the model's answers don't fit the questions (a score out of range, an option that isn't in
the list), the action raises an error instead of returning the bad data.

## Providers: implementing the task natively

By default, `generate_description` runs on top of the provider's `generate_data` support. A
provider can take over the task by overriding the hook this integration adds to `AITaskEntity`:

```python
from custom_components.decision_ai_task import GenDescriptionTask, GenDescriptionTaskResult

class MyAITaskEntity(AITaskEntity):
    async def _async_generate_description(
        self, task: GenDescriptionTask, chat_log: ChatLog
    ) -> GenDescriptionTaskResult:
        # task.instructions is already the user content of chat_log;
        # task.structure is the voluptuous schema for the expected output.
        data = ...  # call your model
        return task.result_from_data(chat_log.conversation_id, data)
```

Other integrations can also call it from Python:
`custom_components.decision_ai_task.async_generate_description(hass, task_name=..., prompt=..., ...)`.

## How it works

`ai_task` belongs to Home Assistant core and has no extension point for new task types, so this
integration patches it while its config entry is loaded:

- It registers `generate_description` in the `ai_task` domain and sets the action's description
  from this integration's `services.yaml`.
- It adds `internal_async_generate_description` and an overridable `_async_generate_description`
  to `AITaskEntity`.
- It hooks core's translation and icon loaders so the action's strings and icon appear under
  `ai_task`, the same as core's own actions.

All of this is undone when you remove the integration. The translation and icon hooks rely on
private core helpers. If a future core release changes them, the hooks are skipped with a
warning and the action still works, just with untranslated labels.

## Branding

The `brand/` folder contains core's AI Task brand: `mdi:star-four-points` in Home Assistant blue,
rendered the same way the [brands](https://github.com/home-assistant/brands) build renders
`core_integrations/ai_task/icon.txt`.

## Development

```bash
python -m venv .venv && . .venv/bin/activate
pip install -r requirements_test.txt
pytest
```
