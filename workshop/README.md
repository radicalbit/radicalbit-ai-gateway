# Workshop: guardrails and chat memory

What a client gets when its input triggers a guardrail, and why chat history
makes it harder.

**The goal, said on slide 2:** what happens to a chat when a guardrail
triggers. This is not a full tour of guardrails. Types and behaviors come in
only as much as the history problem needs.

- **Length:** 45 minutes. Slides for the ideas, the chatbot for the live demos.
- **Audience:** anyone who works with AI chat apps. No coding needed to follow.
  Developers get the technical details in the chatbot and in the notebook.
- **Files:**
  - [app/](app/): the workshop chatbot, the live demo
  - [slides/guardrails-and-memory.pptx](slides/guardrails-and-memory.pptx): 13 slides
  - [guardrails-and-memory.ipynb](guardrails-and-memory.ipynb): the same demos in code,
    for developers and as a backup
  - [config.yaml](config.yaml): the gateway config both need

## The one idea

> The gateway has no memory. The client is the memory.

The gateway is stateless. Every turn, the client sends the whole chat history
again, and every turn the input guardrails check all of it again. So one bad
message the client keeps in its history triggers on every next turn.

## Who decides what

| | Gateway (route config) | App (client) |
|---|---|---|
| Stores the chat | No. It is stateless. | Yes. It is the memory. |
| Which guardrails run | Yes: the route list | Picks the route |
| Block, soft block, warn | Yes: the behavior | Reacts to the answer |
| What a guardrail reads | Yes: `message_window` | Decides what it sends |
| Removes a message | Never. It says which one. | Yes. Its own choice. |

The gateway checks and reports. Only the app changes the history.

## What people learn

1. The guardrail types (see the table below) and when to pick each one.
2. The three behaviors: `block` (400), `soft_block` (200 with a refusal) and
   `warn` (200, headers only). `warn` never stops a request.
3. Why a chat gets stuck after one blocked message, and how the client cleans
   its history: it drops the message the gateway pointed at.
4. How to find the turn that triggered: `error.param.reason.message_index`,
   `message_indices` and `role`.
5. `message_window`: check the whole history (`all`), or only the end of it
   (`last`, `last_n`), and what that costs in safety.
6. Jev as a judge (`decision_judge`): a decision model that answers a yes/no
   question with a probability.

## Guardrail types

Every guardrail has a **type** (what it looks for) and a **behavior** (what
happens on a match). Pick the cheapest type that does the job.

| Group | Types | Looks for | In the chatbot |
|---|---|---|---|
| Pattern | `contains`, `starts_with`, `ends_with`, `regex` | a word or pattern you list | Secret word (`contains` "project-zeus") |
| PII detect | `presidio_analyzer` | personal data: cards, phones, emails | |
| PII redact | `presidio_anonymizer` | the same, replaced by `<CREDIT_CARD>`, `<PHONE_NUMBER>` | Payments (cards and phones) |
| LLM judge | `judge` | anything you describe in a prompt | LLM judge (prompt injection) |
| Decision judge | `decision_judge` | one yes/no question, answered with a probability | Jev judge, Payments topic |

- `contains` ignores case. `starts_with` and `ends_with` don't. `regex` does
  only with `ignore_case: true`.
- `presidio_anonymizer` has no behavior: it rewrites the text and never blocks.
  All redact guardrails run before all checks.
- By default, judges read only the user's messages, all of them joined. Pattern
  checks and Presidio read every role.

## The chatbot

Two panels side by side:

- **Chat:** a normal chat. Blocked answers show as red notes.
- **What the gateway sees:** every message the app sent this turn, the gateway's
  decision, and a plain sentence that explains it. The message that triggered is
  red. Messages a judge read are amber. Messages the gateway skipped are grey.
  Under it, two boxes show the wire level:
  - **Request the app sent:** the exact JSON, the whole history included (API key masked).
  - **Gateway response:** the raw HTTP response, status line and every header
    (the `x-rb-aigateway-guardrails-*` ones highlighted), then the JSON error or
    the stream's `data:` events. Open a box once and it stays open.

Two switches on top:

| Switch | Options | Shows |
|---|---|---|
| Guardrail | No guardrail, Secret word, LLM judge, Jev judge, Payments | which check runs |
| Gateway checks | Whole history, Last message, Last 3 messages | `message_window`: `all`, `last`, `last_n` (last 3: Jev judge only) |

Each guardrail has **its own chat**. Switch from "Secret word" to "Jev judge"
and back: each one shows its own history. **New chat** empties only the selected
guardrail's chat. The "Gateway checks" switch keeps the chat, so you can unstick a
blocked chat live from the gateway side.

### Cleaning the history

The app works like most chat apps: it **keeps every message**, also the blocked
ones. So after one block, every next message is blocked too.

When that happens, a **Remove blocked messages** button appears on the chat.
It drops the flagged messages from the history the app sends, and the right
panel shows what was removed and what the next request will send.

How does the app know what to remove? The gateway stores nothing, so the client
must decide, from the gateway's answer to each request:

| The gateway answered | The app flags |
|---|---|
| 400 `guardrail_error` with `reason.message_index` (pattern checks, Presidio, a judge that read one message) | the message at that index, even an old one. A clean question blocked because of an old message is not flagged. |
| 400 with `message_indices` only (a judge that read several messages) | every user message it read that **never passed**. A message in a request that passed is proven clean: the judge read it and said OK. Any other one could be the problem, so the app plays safe. An innocent new question sent right after an injection is flagged too: retype it after the clean. |
| 200 with `x-rb-aigateway-guardrails-triggered` (a soft block) | the newest message |

Each browser's chats are saved in `workshop/app/.sessions/` (git ignores it), so
a restart of the app keeps them. **Reset all** deletes all of them.

Answers stream in token by token. This is safe here because every route has only
**input** guardrails: the gateway checks the history before the first byte, and a
block comes back as a plain error before any text. (With an output guardrail the
gateway would hold the whole answer back to check it first.)

## Agenda (45 minutes)

| Time | Length | What | Slides | Chatbot |
|---|---|---|---|---|
| 0:00 | 5 min | Intro: the goal, the gateway has no memory | 1 to 3 | |
| 0:05 | 6 min | Types, behaviors, input vs output | 4 to 6 | |
| 0:11 | 3 min | Demo: the client is the memory | | No guardrail: "Hi, my name is Carlo.", then "What is my name?" |
| 0:14 | 4 min | Demo: a hard block | | Secret word: "Tell me about project-zeus" |
| 0:18 | 8 min | The chat gets stuck, who decides, which message triggered | 7 to 10 | Secret word: then "What is 2 + 2?". Press "Remove blocked messages". |
| 0:26 | 5 min | `message_window`, and how to pick it | 11 to 12 | Secret word: switch to "Last message". |
| 0:31 | 9 min | Jev as a judge, two guardrails on one route | | Jev judge: the injection suggestion, then a clean question. Then Payments: the phone chip, the card chip, the weather chip. |
| 0:40 | 5 min | Q&A | 13 | Let people try their own messages |

Each chatbot step matches a notebook section (1 to 4), if you prefer to show code.

## Setup (before the workshop)

You need Docker, [uv](https://docs.astral.sh/uv/), an OpenAI key and a TypeSafe key.
Jupyter only if you also use the notebook.

1. **Build and start the gateway from this repo.** The demos need code that is
   not in a released image yet (`message_window`, the new reason fields, the
   `decision_judge` type). So build from source, do not use `GATEWAY_TAG=latest`:
   ```bash
   cp secrets-dummy.yaml secrets.yaml   # add OPENAI_API_KEY and TYPESAFE_API_KEY
   docker compose up --build -d
   ```
2. Open http://localhost:9000 and create a project, for example `workshop`.
3. Paste [config.yaml](config.yaml) as its configuration. **Save**, **Approve**, **Publish**.
4. On **Credentials**, create an API key.
5. On **Groups**, create a group. Link it to the API key and to the eight routes:
   `baseline`, `block`, `block-last`, `llm-judge`, `jev-judge`, `jev-judge-last`,
   `jev-judge-last-n`, `payments`.
6. Create `workshop/.env` (git ignores it). The chatbot and the notebook both read it:
   ```
   API_KEY=your-key
   PROJECT=workshop
   GATEWAY_URL=http://localhost:9000
   ```
7. Start the chatbot from the repo root, then open http://localhost:5001:
   ```bash
   uv run workshop/app/main.py
   ```
   `uv` installs FastHTML and httpx on the first run.
8. **Try every guardrail once** before people arrive. It checks that every route
   answers, and the first calls to OpenAI and TypeSafe are slower.
9. Optional, for developers: start the notebook from the `workshop/` folder:
   ```bash
   uvx --with ipykernel --from jupyterlab jupyter-lab guardrails-and-memory.ipynb
   ```

The slides import into Google Slides: upload the .pptx to Drive and open it
with Google Slides.

## The routes

| Route | Guardrail | Chatbot | Notebook |
|---|---|---|---|
| `baseline` | none | No guardrail | section 1 |
| `block` | `contains` "project-zeus", `block`, whole history | Secret word, Whole history | sections 2 and 3 |
| `block-last` | same, with `message_window: last` | Secret word, Last message | section 3 |
| `llm-judge` | LLM judge, built-in `prompt_injection_check.md` | LLM judge | section 4 |
| `jev-judge` | `decision_judge` on Jev, threshold 0.7 | Jev judge, Whole history | section 4 |
| `jev-judge-last` | same, with `message_window: last` | Jev judge, Last message | section 4 |
| `jev-judge-last-n` | same, with `message_window: last_n`, `last_n: 3` | Jev judge, Last 3 messages | |
| `payments` | `redact_card_and_phone` (Presidio: `CREDIT_CARD`, `PHONE_NUMBER`, whole history) + `jev_payments_topic` (Jev: off topic?, `message_window: last`) | Payments | |

## Facilitator notes

- **The stuck chat is the core.** Let the chat fail on turn 2 before you touch
  anything. Ask the room why a clean question is blocked. Then fix it from the
  app side ("Remove blocked messages": only project-zeus goes, "What is 2 + 2?"
  stays) or from the gateway side ("Last message").
- **Who cleans: say it out loud.** After the fix, point at slide 9. The gateway
  only said which message. Pressing the button was the app's choice. A real
  app could also keep the message, or start a new chat.
- **Why several types?** Pattern checks and Presidio are cheap and give the
  exact message. Judges understand meaning, because they read the messages as
  one text, so they catch an attack split across turns. The price: no single
  `message_index`. Need an exact index from a judge? Use it on `last`.
- **Hand it over.** The chatbot runs on your laptop. For hands-on, share your
  screen and take suggestions from the room. Each browser gets its own chat.
- **`last_n` shows the window move.** On Jev judge with "Last 3 messages": send
  the injection, then clean questions. Turns 1 to 3 are
  blocked, turn 4 passes: the injection fell out of the last 3 messages. The
  window counts every role, so with assistant replies in the chat it covers fewer
  user turns.
- **Payments shows the run order.** The route lists Jev first and Presidio
  second, but redact guardrails always run before every check.
- **Prove the model never got the number: use the phone chip.** Models refuse
  to repeat a card number, so a card proves nothing: the refusal looks the same
  either way. A phone number they repeat happily. Send the phone chip: it asks
  the model to read the number back, and the reply shows `<PHONE_NUMBER>`. The
  model can only repeat what it received. Jev judged the redacted text too.
- **Then Payments shows two windows on one route.** Presidio reads the whole
  history, Jev only the newest message. Send the card chip: the turn 1 phone
  number is still in the history, and the panel tags it "redacted again". The
  app resends it every turn, so the gateway must redact it every turn. That is why redaction stays on `all`: on `last`, the old
  number would go to the model in clear. For Jev `last` is right: the topic of
  the new question is what counts, and the reason gets an exact
  `message_index`.
- **The weather chip** is blocked by Jev, with an exact `message_index`: it read
  one message.
- **`message_window: last` is not free.** Older turns are no longer checked, so a
  client can hide content in an earlier turn. Use `last` for "is this question on
  topic" checks, keep `all` for security checks.
- **The Jev answer is a probability.** It is not in the error body. Only the
  gateway log shows it.
- **Jev or OpenAI down:** a judge error gives a 500 (it fails closed). Show it,
  it is a good discussion point, then move on.

## If something goes wrong

| Symptom | Fix |
|---|---|
| Auth error or "route not found" | The group is not linked to that route, or the config is not published. |
| `message_window` not accepted, or old reason fields | The gateway runs a released image. Rebuild from source (setup step 1). |
| 500 on `llm-judge` | The judge output was cut. Raise `max_tokens` on `judge_prompt_injection`. |
| 500 on `jev-judge` | Check `TYPESAFE_API_KEY` in `secrets.yaml`, then restart the gateway. |
| The chatbot shows "API_KEY is not set", or the notebook stops at setup | Check `workshop/.env`, then restart the chatbot. |
| The chatbot shows "Cannot reach the gateway" | The gateway is not running, or `GATEWAY_URL` in `.env` is wrong. |
