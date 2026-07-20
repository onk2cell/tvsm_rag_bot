# Client CRM Webhook Integration and Mock Test Harness

**Status:** Ready for agent implementation  
**Source:** Client-feedback grilling session and the existing qualification-bot architecture  
**Intended issue label:** `ready-for-agent`

## Problem Statement

The bot currently has channel-specific WhatsApp and web entry points, but the client wants customer conversations to travel through its own app and CRM. The client will call a bot webhook with customer text, image, or audio messages; the bot must look up customer details by mobile number and send text replies to a client-owned callback webhook.

The final client APIs are not yet available. Building directly against assumptions would make integration and deployment fragile. The development team needs a realistic client simulator that exercises the complete asynchronous path before client credentials or production endpoints are introduced. It must prove that webhook authentication, validation, deduplication, queueing, customer lookup, conversation processing, media handling, callback retries, and persistence work together under deployment-like conditions.

## Solution

Add a single-client CRM/app channel adapter around the existing channel-agnostic conversation engine. The adapter will accept authenticated inbound events, normalize them into conversation turns, process them asynchronously, retrieve and cache CRM customer identity, and deliver text replies to one configured client callback URL.

Build a mock client service as a first-class test harness. It will emulate both client-owned dependencies:

- A customer-details API that returns deterministic customer ID, name, and preferred language by mobile number.
- A reply callback webhook that records bot replies and can deliberately return successes, errors, or timeouts.

The mock client will also act as a test driver. It will send realistic customer events, host deterministic image/audio fixtures, expose received callbacks for assertions, and support fault scenarios. A deployment-like automated test will run the bot API, Redis, worker, and mock client together and verify behavior through HTTP boundaries rather than calling internal functions directly.

The production and mock paths will use the same interfaces and payload validation. Deployment will switch only endpoint and credential configuration, not business logic.

## User Stories

1. As a client-app customer, I want my text message delivered to the bot, so that I can continue the qualification conversation outside WhatsApp.
2. As a client-app customer, I want to send an audio message, so that the bot can transcribe it and answer in text.
3. As a client-app customer, I want to send a document image, so that the bot can recognize the document and explain the next step.
4. As a client-app customer, I want an unavailable media file to produce a clear resend request, so that I can recover without operator intervention.
5. As a client-app customer, I want unclear document images recorded as unknown and retried, so that the bot does not invent a document type.
6. As a client-app customer, I want a non-document image to receive a clear supported-use response, so that I know what the bot can process.
7. As a client-app customer, I want replies in my CRM language preference, so that the conversation is understandable.
8. As a client-app customer, I want language detection used when the CRM preference is unavailable, so that a missing field does not block the conversation.
9. As a client-app customer, I want messages processed in arrival order, so that rapid consecutive messages do not produce contradictory replies.
10. As a client-app customer, I want a fresh conversation after one hour of inactivity, so that stale context does not leak into a later enquiry.
11. As a client-app customer, I want temporary CRM or AI failures handled with retries and a clear fallback reply, so that failures do not disappear silently.
12. As a client-app customer, I want long replies delivered in ordered parts, so that the client app can render the complete answer reliably.
13. As a client integration developer, I want a documented inbound message contract, so that the client app can produce valid events.
14. As a client integration developer, I want detailed validation errors, so that malformed integrations can be corrected quickly.
15. As a client integration developer, I want an immediate asynchronous acknowledgement, so that the client webhook caller does not wait for AI processing.
16. As a client integration developer, I want acknowledgements to distinguish accepted, duplicate, and ignored events, so that delivery behavior is observable.
17. As a client integration developer, I want unique message IDs deduplicated, so that webhook retries do not create duplicate customer replies.
18. As a client integration developer, I want bot replies correlated to inbound messages, so that the app can place replies correctly.
19. As a client integration developer, I want every reply part to have a unique ID and sequence metadata, so that split replies can be ordered and deduplicated.
20. As a client integration developer, I want callback success defined as any HTTP 2xx response, so that compatible acknowledgement styles work.
21. As a client integration developer, I want unsupported event types explicitly reported as ignored, so that they are not mistaken for processed messages.
22. As a developer, I want one normalized client-channel turn path into the conversation engine, so that CRM transport logic does not duplicate qualification logic.
23. As a developer, I want client-owned HTTP dependencies behind explicit interfaces, so that production and mock implementations are interchangeable.
24. As a developer, I want a deterministic mock customer API, so that customer lookup tests do not depend on the real CRM.
25. As a developer, I want a deterministic mock callback receiver, so that reply payloads and ordering can be asserted.
26. As a developer, I want the mock callback to inject failures and delays, so that retry and timeout behavior can be tested.
27. As a developer, I want mock media URLs for text-adjacent, audio, valid-document, unclear-document, and non-document cases, so that media flows are repeatable.
28. As a developer, I want deterministic AI, transcription, and document-recognition adapters in automated system tests, so that transport failures are not confused with provider variability.
29. As a developer, I want one command to start the deployment-like test stack, so that the integration is easy to verify locally and in CI.
30. As a developer, I want health checks for the API, Redis, worker, and mock client, so that tests start only when dependencies are ready.
31. As a developer, I want the same environment configuration shape in mock and production modes, so that deployment does not require code changes.
32. As a developer, I want webhook credentials and client API credentials supplied through secrets, so that they are not committed to source control.
33. As a developer, I want media downloads protected against private-network access and unsafe redirects, so that public URLs cannot be used for server-side request forgery.
34. As a developer, I want per-mobile processing serialized, so that asynchronous workers cannot reorder one customer’s conversation.
35. As a developer, I want accepted messages recoverable from worker failures, so that an HTTP 202 does not imply silent loss.
36. As a developer, I want stable error codes in HTTP responses and stored processing records, so that failures can be diagnosed across environments.
37. As a developer, I want test data isolated from production interaction and lead data, so that deployment tests do not pollute admin reports.
38. As a QA engineer, I want a happy-path system test from inbound webhook to captured callback, so that the full integration can be accepted before client access arrives.
39. As a QA engineer, I want duplicate, authentication, validation, throttling, ordering, timeout, retry, and permanent-failure scenarios, so that webhook reliability is proven.
40. As a QA engineer, I want text, audio, clear-document, unclear-document, multiple-document, and bad-media scenarios, so that all supported content types are covered.
41. As a QA engineer, I want CRM lookup success, multiple-match, timeout, and server-error scenarios, so that customer enrichment behavior is covered.
42. As a QA engineer, I want assertions over externally observable callbacks and persisted records, so that tests do not depend on implementation details.
43. As an administrator, I want permanently failed processing or callback deliveries flagged for review, so that customer conversations can be recovered.
44. As an administrator, I want one local lead per one-hour conversation, so that returning enquiries remain historically distinct.
45. As an administrator, I want customer identity and recognized-document metadata visible in authenticated admin tools and exports, so that follow-up has sufficient context.
46. As an administrator, I want exact repeated document URLs deduplicated within a lead, so that retries do not clutter the record.
47. As a deployment operator, I want a pre-deployment smoke test using the mock client, so that configuration and service connectivity are verified before cutover.
48. As a deployment operator, I want production startup to fail clearly when required client endpoints or credentials are missing, so that a partially configured integration is not exposed.
49. As a deployment operator, I want structured logs correlated by inbound message ID, outbound message ID, mobile, and conversation ID, so that asynchronous failures can be traced.
50. As a product owner, I want production cutover blocked until the client supplies complete customer-lookup and reply-webhook contracts, so that deployment does not rely on guessed behavior.

## Implementation Decisions

### Integration boundary

- Add a client CRM/app channel adapter alongside the existing WhatsApp and web adapters.
- Keep qualification, RAG, profile extraction, and lead scoring in the existing conversation engine.
- Wire this adapter to the qualification engine, not to the legacy WhatsApp open-Q&A worker path.
- Record the channel and source as a distinct client-app value; extend existing source validation rather than misclassifying this traffic as web or WhatsApp.
- Introduce explicit customer-directory and reply-delivery interfaces. Production HTTP adapters and the mock client must implement the same behavioral contracts.
- Use one configured client integration per deployment. Multi-client routing is not required.
- Use a fixed configured callback URL. Never accept a callback destination from an inbound payload.

### Primary test seam

- The primary acceptance seam is the complete HTTP and worker boundary: mock client sends an inbound event, the real webhook validates and enqueues it, the real worker processes it, the bot calls the mock customer API and callback webhook, and the test asserts the callback and persistence.
- The deployment-like test stack must include the bot API, Redis, worker, and mock client.
- Automated tests replace Gemini generation, audio transcription, and image recognition with deterministic adapters while preserving the real transport, queue, state, retry, and persistence paths.
- A smaller conversation-engine suite remains responsible for qualification behavior. The new system suite verifies channel orchestration rather than duplicating all conversational assertions.

### Inbound webhook contract

- Protect the endpoint with HTTP Basic Authentication over HTTPS.
- Accept JSON events with required `message_id`, `type`, `mobile`, and `timestamp`.
- `mobile` must be an Indian E.164 number beginning with `+91`.
- `timestamp` is a required client-supplied string. Because its format is uncontrolled, store it as metadata but do not use it for ordering, expiry, or deduplication.
- Generate a server-owned UTC `received_at` value for operational use.
- Supported types are `text`, `image`, and `audio`.
- Text events require `content`.
- Image and audio events require `media_url`; `content` is an optional caption.
- `mime_type` is optional. When omitted, resolve from the download `Content-Type`, then from the URL extension, and reject only if no supported type can be determined.
- Limit text and captions to 4,096 characters.
- Return detailed HTTP 400 responses with stable field-level error codes for malformed JSON or invalid required fields.
- Return HTTP 401 for invalid Basic Authentication.
- Unsupported types return HTTP 202 with `status: ignored` and `reason: unsupported_type`.
- Valid events return HTTP 202 JSON containing status, message ID, and duplicate state.
- Process every previously unseen message ID regardless of the client timestamp.

### Deduplication, ordering, and throttling

- Retain inbound message IDs for seven days.
- A repeated ID must never generate another customer reply. Return an acknowledgement identifying it as a duplicate.
- Process messages sequentially per normalized mobile number in webhook-arrival order.
- Failure of one message must not permanently block later queued messages for that mobile.
- Rate-limit each mobile to 12 inbound messages per minute.
- If an event cannot be durably queued, return a retryable server error rather than HTTP 202.

### Conversation and customer identity

- Use normalized mobile as the client-facing session key.
- Conversation context uses a sliding one-hour inactivity expiry.
- Keep client-app conversation history and qualification state on the server; unlike the current browser adapter, the client must not resend authoritative history with every event.
- Each new one-hour conversation window creates a distinct local lead, even for a returning mobile number.
- Derive and persist an internal conversation identifier so historical leads from one mobile remain distinct.
- Look up customer details on the first message of each conversation and cache them for that conversation.
- The required logical customer response contains customer ID, customer name, and preferred language.
- If preferred language is missing or unsupported, detect language from customer content.
- If multiple CRM records are returned, use the first result, matching the confirmed product decision.
- Retry transient customer-lookup failures three times. After exhaustion, deliver a temporary-unavailable reply and flag the interaction for review.
- The final production URL, HTTP method, authentication mechanism, payload shape, response shape, timeout, and error mapping remain pending client documentation.

### Message processing

- Text enters the conversation engine directly.
- Audio is downloaded, validated, transcribed, and then passed to the conversation engine. Maximum size is 10 MB and maximum duration is 60 seconds.
- Images are limited to 10 MB and are used only for document recognition.
- Recognize driving licences, permits, badges, identity documents, finance documents, and vehicle documents.
- Do not extract or store visible document numbers or other field values. Record document type and the client-provided URL.
- Record every recognizable document when one image contains multiple documents.
- Save an unclear image as document type `unknown`, ask the customer for a clearer image, and flag repeated failures according to admin-review policy.
- For a non-document image, explain that only document images are supported and request relevant text or a document image.
- Deduplicate an exact repeated document URL within the same lead, while retaining different URLs for the same document type.
- Do not retain downloaded raw audio or image bytes after processing.
- Treat media, captions, transcripts, and document contents as untrusted customer data; they cannot override system instructions.
- Media fetching must allow HTTPS only, block local/private/link-local destinations, revalidate redirects, enforce byte and time limits while streaming, and verify the declared and received MIME types.
- If media is unavailable, unsafe, expired, oversized, too long, or has an invalid MIME type, record the error and send a text request to resend it.

### Reply callback contract

- Send text replies only.
- Every callback includes a new unique `message_id`, the inbound ID as `in_reply_to`, normalized `mobile`, `type: text`, `content`, and a server-generated ISO 8601 UTC `timestamp`.
- Split content longer than 4,096 characters into ordered callbacks. Each part has its own message ID plus `part_number` and `part_count`.
- Deliver split parts sequentially and wait for one part to succeed before sending the next.
- Treat any HTTP 2xx response as successful delivery.
- Use a 30-second timeout per callback attempt.
- Make three total callback attempts at fixed 30-second intervals.
- After all attempts fail, retain the reply and flag it for authenticated admin review.
- The client is expected to deduplicate outbound message IDs.
- Delivery/read receipts after a successful callback are not required.
- The final production callback URL and authentication method remain pending client documentation.

### AI and processing failures

- Make three total attempts for transient generation, transcription, and recognition failures.
- After exhaustion, send a temporary-error text reply when callback delivery remains available and flag the interaction for review.
- Continue processing later queued messages for the same mobile.
- Correlate processing attempts, errors, and callbacks without exposing credentials or sensitive request headers in logs.

### Local lead and interaction persistence

- Create the local lead after the first successful CRM lookup in a conversation.
- Maintain one local lead per one-hour conversation, not one lifetime lead per mobile.
- Update that lead as qualification and document information arrives.
- Store customer mobile, CRM customer ID, customer name, document types, document URLs, recognition status, and relevant timestamps.
- Show these fields in authenticated admin views and CSV exports.
- Keep document metadata and client URLs indefinitely.
- Do not add CRM lead notes or upload documents back to the CRM in this version.
- Do not store raw media.
- Test traffic must use isolated lead and interaction stores.
- The confirmed scope has no record-deletion mechanism. This must be listed as a deployment risk rather than silently treated as compliant retention behavior.

### Mock client service

- Emulate the customer-details API and reply callback in one independently deployable test service.
- Seed deterministic customers keyed by `+91` mobile number.
- Record every customer lookup and reply callback with timestamps and attempt counts.
- Provide test-only controls to configure customer responses, duplicate records, delays, timeouts, status codes, and sequences such as two failures followed by success.
- Host small deterministic image and audio fixtures over HTTP inside the test network; production media validation remains HTTPS-only, while the isolated test mode may explicitly trust the mock host.
- Expose a test-only inspection API that can reset state and retrieve recorded calls.
- Never enable test-control or inspection endpoints in the production bot deployment.
- Supply a test driver that emits valid and invalid inbound events and waits for correlated callbacks.

### Deployment

- Add the mock client under an explicit local/CI deployment profile so it is not started in production.
- Start tests only after API, Redis, worker, and mock-client health checks pass.
- Provide a single documented command that builds the images, starts the isolated stack, runs contract/system tests, and exits non-zero on failure.
- Keep endpoint URLs, Basic Authentication credentials, client API credentials, timeouts, and test-mode adapter selection in environment configuration.
- Decouple service startup configuration so the client-app and mock stacks can run without dummy Meta/WhatsApp credentials. WhatsApp-specific settings remain required only when the WhatsApp services are enabled.
- Production mode must reject deterministic test adapters and must not start with missing required integration settings.
- The pre-deployment smoke suite must run against the built container images, not only the developer’s host Python environment.

## Testing Decisions

### What makes a good test

- Assert behavior visible at HTTP callbacks, acknowledgement responses, admin-visible records, and durable processing state.
- Do not assert internal Redis key names, private helper calls, exact prompt text, or queue implementation details.
- Use fixed IDs, customers, media fixtures, and deterministic model outputs so failures are reproducible.
- Exercise actual JSON serialization, Basic Authentication, HTTP status handling, queue boundaries, process boundaries, timeouts, retries, and persistence.
- Keep real Gemini and real client CRM checks as optional manual or staging verification; they are not deterministic CI gates.

### Highest seam

- The main system test starts with the mock client’s inbound HTTP request and ends when the mock client records a correlated reply callback.
- It also verifies the expected interaction and lead state through authenticated public/admin behavior where available.
- This is the smallest number of seams that proves the user’s deployment goal: one end-to-end seam across the client-owned boundaries.

### Supporting seams

- Inbound contract tests cover authentication, schema validation, acknowledgement, ignored types, duplicate state, and durable-enqueue failure.
- Customer-directory contract tests cover request mapping, customer response mapping, first-record selection, caching, retries, timeout, and exhausted failure.
- Reply-delivery contract tests cover payload mapping, correlation, splitting, ordering, any-2xx success, 30-second timeout, three attempts, and admin-review exhaustion.
- Media boundary tests cover URL safety, redirects, size limits, MIME validation, audio duration, raw-file disposal, and fixture processing.
- Conversation-engine tests continue to cover qualification, language, grounded answers, profile capture, and lead scoring with a fake model.
- Persistence tests cover one lead per conversation, returning customers, document accumulation, exact-URL deduplication, and test-data isolation.

### Required system scenarios

1. Valid text event returns HTTP 202 and eventually produces one correlated text callback.
2. Duplicate inbound ID returns duplicate acknowledgement and produces no second callback.
3. Invalid Basic Authentication returns HTTP 401 and queues nothing.
4. Malformed or incomplete payload returns detailed HTTP 400 errors.
5. Unsupported type returns an explicit ignored HTTP 202 response.
6. More than 12 messages per minute for one mobile triggers throttling without affecting another mobile.
7. Rapid messages for one mobile produce callbacks in arrival order.
8. Different mobiles can progress independently.
9. First turn performs one CRM lookup; later turns in the same hour use the cached customer.
10. A turn after one hour performs a new lookup and creates a new lead.
11. Missing CRM language uses detected language.
12. Multiple CRM matches select the first record.
13. Transient CRM failure succeeds within three attempts.
14. Exhausted CRM failure sends a temporary-unavailable reply and flags review.
15. Valid audio fixture is transcribed and answered in text.
16. Oversized, overlong, unreachable, or wrong-MIME audio asks the customer to resend.
17. Valid document image records its type and URL and sends the next-step reply.
18. One image with multiple documents records all recognized types.
19. An exact repeated document URL is not appended twice.
20. An unclear document is stored as unknown and triggers a clearer-image request.
21. A non-document image receives the supported-use response.
22. Private-network, unsafe-redirect, oversized, and MIME-mismatch media URLs are rejected safely.
23. Transient AI processing succeeds within three attempts.
24. Exhausted AI processing sends the fallback reply and flags review.
25. A failed message does not block a later message from the same mobile.
26. Callback succeeds on any 2xx response.
27. Callback failures follow exactly three attempts separated by the configured fixed interval.
28. Callback success on the third attempt creates no admin-review flag.
29. Exhausted callback delivery retains the reply and flags admin review.
30. A long reply is split with unique IDs, correlation, part metadata, and sequential delivery.
31. Mock/test interactions and leads never appear in production stores.
32. The deployment-like stack starts from health checks and completes the happy-path smoke test using built images.
33. Production configuration fails safely when required endpoints or credentials are absent.
34. The client-app and mock stacks start without Meta/WhatsApp credentials when WhatsApp services are disabled.
35. Client-app events use server-owned history and are persisted under the distinct client-app channel/source.

### Prior art

- The repository already tests the public qualification endpoint through a FastAPI client with a fake LLM and isolated interaction/lead stores.
- The repository already tests worker-side successful exchanges and provider errors with external calls replaced.
- The current WhatsApp path already establishes patterns for quick webhook acknowledgement, Redis-backed deduplication, rate limiting, queue workers, and admin-review persistence.
- The existing container stack already separates the web app, webhook app, worker, and Redis, which can be extended with an isolated mock-client profile.
- The existing conversation engine is the established channel-independent business-logic seam and should remain the core behavior target.

## Out of Scope

- Replacing or removing the WhatsApp and public web channels.
- Supporting multiple client CRMs in one deployment.
- Guessing the client’s final customer API method, URL, authentication, request schema, response schema, or error semantics.
- Guessing the client’s final reply-webhook authentication scheme.
- Writing document notes or uploading document files back into the client CRM.
- Sending buttons, images, audio, or other media from the bot to the customer.
- Delivery and read receipts after the client accepts a callback.
- General-purpose image understanding outside document recognition.
- Extracting or storing document numbers, identity values, bank values, or other visible fields.
- Retaining downloaded raw audio or image files.
- Standardizing or trusting the client-provided timestamp.
- A contractual reply-time SLA; processing remains best effort.
- Customer-controlled manual conversation reset.
- A record-deletion workflow.
- Real-client production acceptance testing before the client supplies its API contracts and credentials.

## Further Notes

- The client still needs to provide the full customer-details API contract and full reply-webhook contract, including production authentication.
- The mock contract is an executable development baseline, not evidence that the client’s eventual API uses the same wire shape. Production adapters must be finalized against client examples before cutover.
- Public document URLs remain client-hosted, but this service still processes and persists them. HTTPS enforcement, SSRF protection, access logging discipline, and a documented client risk acceptance are required.
- Indefinite retention with no deletion mechanism is a known privacy and operational risk. It should be explicitly accepted before production deployment.
- Selecting the first record when a CRM lookup returns multiple customers is a confirmed behavior but can associate a conversation with the wrong customer. The mock suite must make this behavior visible.
- A 30-second callback timeout combined with three attempts and fixed 30-second waits can keep one outbound delivery active for roughly two and a half minutes. Worker capacity and per-mobile serialization tests must account for this.
- Apply the `ready-for-agent` label when this specification is published to the project issue tracker.
