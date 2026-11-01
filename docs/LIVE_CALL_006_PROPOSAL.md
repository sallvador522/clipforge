# LIVE-CALL 006 — Plan-Only Proposal (PREPARED, NOT EXECUTED)

**Status:** Prepared only. **No request was made.** Execution requires Salvador's explicit
approval after reviewing this proposal.

## Exact instruction

> “Keep me sharp, blur the people behind me and replace the background with a cinematic
> Luanda sunset.”

Source video metadata (no video bytes are sent): **360×640, 30 FPS, 6.177 s, 177 frames,
audio present**.

## Request shape

- Protocol: Chat Completions, `POST https://api.meta.ai/v1/chat/completions`
- Wire schema: `ProfessionalEditingPlanLite` (**1,948 bytes**, zero `$refs`)
- Full playbook: **10,294 chars**
- Developer message (playbook + lite registry summary + output rules): **11,096 chars**
- User message (transcript + metadata + echo rules): **705 chars**
- Full request JSON: **14,369 chars**
- Input token estimate (chars/4, not a billing figure): **2,950 tokens**
- Expected output: **2,400 completion tokens** (prior 5-operation live plan used 2,293)
- `max_completion_tokens`: **16,000**
- `reasoning_effort`: `medium`
- No tools, no web search, no audio/video bytes, no `previous_response_id`, no `text.format`

Exact prepared payloads (generated locally, gitignored, contain no credentials):

- `storage/live_call_006_request_standard.json`
- `storage/live_call_006_request_contributor.json`

Reproduce with:

```powershell
python scripts/prepare_live_call_006.py
```

The script uses an `httpx.MockTransport` that raises if any request is attempted, and never
calls `create_plan`.

## Billing modes and estimates

| Mode | Model | Expected cost | Worst case at 16k cap |
|---|---|---|---|
| **Standard** (code default) | `muse-spark-1.3` | **$0.013888** | **$0.071688** |
| **Contributor** (current live path, ADR-012) | `muse-spark-1.3-contributor` | **$0.000775** | **$0.003495** |

- Standard rates: $1.25/1M input + $4.25/1M output.
- Contributor rates: $0.10/1M input + $0.20/1M output.
- Contributor is **not** activated automatically. The code default remains Standard; the
  current factory live path uses Contributor only because ADR-012 approved it explicitly.
- This proposal does not change privacy, data-sharing or billing settings.

## Expected response

One `ProfessionalEditingPlan` for inspection, with:

- `subject.isolate` — keep the speaker sharp (mock masks; **not SAM**)
- `background.replace` — local/mock compositing; **not Muse Image**
- `audio.preserve`
- `video.render_mp4`
- `output.verify`
- `approval_status: required` because `background.replace` requires approval

The “cinematic Luanda sunset” is an asset/prompt description for the local/mock replace
capability, not a Muse Image generation request. If the model names the planned
`background.generate` capability (Muse Image), the plan must be rejected as unavailable.

The test will **only generate and validate the plan**. It will not execute the EDL, invoke
SAM or Muse Image, or render a video.

## Data transmitted

- Confirmed transcript text (English instruction)
- Video metadata: 360×640, 30 FPS, 6.177 s, 177 frames, audio present
- Request id / raw instruction echo
- Playbook and capability registry summary

Not transmitted: audio bytes, video bytes, images, credentials in the body, user identity,
web-search context. The API key is only the Authorization header and is never logged.

## Approval gate

Do not execute until Salvador explicitly approves this proposal. The previous approved
live run (LIVE-E2E 006) is documented separately; it is not a retry of this test.
