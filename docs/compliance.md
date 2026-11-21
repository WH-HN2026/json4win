# LLM API Compliance Check (Brief Requirement)

**Date:** 2026-11-21
**Brief requirement** ([`README.md`](../README.md), *Parametry maszyny…* & §5 *Wymagania techniczne*):
- Open-source components only, including **open-weight** LLMs.
- LLM API provided by a company that states the **scope and place of data processing in its Privacy Policy**, operating **from servers in the EU/EEA**.

Assessed setup ([`docs/architecture.md`](architecture.md) D11): **Mistral La Plateforme** (Mistral AI, Paris, France), currently configured at `https://api.mistral.ai/v1`, comparing **`zai-glm-5-3-flash`** (Z.ai GLM-5.3-Flash) and **`deepseek-v4-1-flash-1017`** (DeepSeek V4.1 Flash 1017).

---

## 1. Mistral Privacy Policy: Scope and Place of Processing for API Data

### Scope
Mistral AI is incorporated in Paris, France (*15 rue des Halles, 75001 Paris*). Its [Privacy Policy](https://legal.mistral.ai/terms/privacy-policy) (effective September 3, 2026) covers *"Mistral AI Products such as Vibe or Mistral AI Studio"* but **carves out business/controller use**:

> "Scope of this Privacy Policy. This Privacy Policy does not apply if you use our Mistral AI Products to process personal data in the context of your business activities. In this case, you are the data controller, and Mistral AI is the data processor processing on your behalf." — [Privacy Policy](https://legal.mistral.ai/terms/privacy-policy)

For commercial API usage, Mistral acts as **Data Controller** for account, billing, and operational data under the Privacy Policy, and as **Data Processor** for personal data inside API inputs/outputs under the [Commercial Terms of Service](https://legal.mistral.ai/terms/commercial-terms-of-service) (effective September 25, 2026, §12.2–12.3) and [Data Processing Addendum (DPA)](https://legal.mistral.ai/terms/data-processing-addendum) (effective July 27, 2026):

> "12.3. Mistral AI as Data Processor. If Customer uses the Mistral AI Products on Mistral Infrastructure, Mistral AI may Process Personal Data on behalf of Customer as a Data Processor. In such case, the Data Processing Agreement available at https://legal.mistral.ai/terms/data-processing-addendum ... will apply between the Parties." — [Commercial Terms of Service §12.3](https://legal.mistral.ai/terms/commercial-terms-of-service)

Despite the carve-out, Privacy Policy §3 and §5 explicitly describe API data scope (service delivery, debugging, abuse monitoring, and training unless opted out):

> "Data we use to provide our APIs to you: Except for specific APIs, we keep your Input and Output for the period necessary to generate the Output and then for thirty (30) rolling days to monitor abuse (unless zero data retention is activated)." — [Privacy Policy §5](https://legal.mistral.ai/terms/privacy-policy)

### Place of Processing
The Privacy Policy does **not** commit to EU-only processing or name server countries. It states a preference for EU providers while allowing non-EU transfers under GDPR Art. 46 / SCCs:

> "7. Do we transfer Your Personal Data Outside of the European Union? We prioritize selecting providers within the European Union that strictly adhere to the GDPR. However, in exceptional cases, we may opt for non-EU providers that meet our high standards of data security and Personal Data protection. We take the necessary steps to ensure that all contracts with service providers who process personal data outside the European Union have adequate safeguards in compliance with Article 46 of the GDPR." — [Privacy Policy §7](https://legal.mistral.ai/terms/privacy-policy)

The [DPA §8.1](https://legal.mistral.ai/terms/data-processing-addendum) likewise authorizes international transfers to adequate countries or under SCCs, and DPA Exhibit 1 delegates infrastructure locations to the [Trust Center Subprocessors list](https://trust.mistral.ai/subprocessors).

---

## 2. Default Processing & Storage Location, and Third-Party Models

### Default Hosting vs. Global (`api.mistral.ai`) vs. EU Endpoint (`api.eu.mistral.ai`)
Mistral's [Help Center](https://help.mistral.ai/en/articles/347629-where-do-you-store-my-data-or-my-organization-s-data) states:

> "By default, your data is hosted in the European Economic Area (EEA). You may, however, explicitly use our US API endpoint, in which case your inference requests are processed in the United States. ... Depending on the feature you use, your data can be temporarily transferred outside of the European Union, to the locations listed in the 'Subprocessors' tab of our Trust Center."

However, Mistral's [Regional Inference documentation](https://docs.mistral.ai/inference/regional-inference) reveals a critical distinction for the **`https://api.mistral.ai/v1`** endpoint we currently configure:

| Endpoint | Region | Upcharge | Geography | Commitment |
|---|---|---|---|---|
| `api.mistral.ai` | Global | None | Not region-specific | *"Mistral does not commit to a specific inference location for requests sent to this endpoint."* |
| `api.eu.mistral.ai` | EU | 1.1× (10%) | *"Multiple data centers in EU and EFTA countries"* | *"Use the EU regional endpoint to support inference processing within the European Union."* |

Regional Inference also notes a control-plane caveat:

> "Regional inference does not provide regional storage for all control-plane data. For example, account configuration, API keys, billing, access management, usage analytics, and other operational metadata may still be handled by Mistral systems outside the selected inference geography." — [Regional Inference](https://docs.mistral.ai/inference/regional-inference)

**Specific EU/EEA countries:** **Not stated** in the Privacy Policy, DPA, or Regional Inference docs (beyond *"EU and EFTA countries"*). Note: `https://trust.mistral.ai/subprocessors` is a JS-rendered Vanta page requiring signed client requests and could not be scraped statically; Mistral's public Trust Center disclosures (via web index) list cloud infrastructure subprocessors including Microsoft (Sweden, Norway), Google (Netherlands, Belgium, and United States for US endpoints), and Mistral Compute.

### Third-Party Models (`zai-glm-5-3-flash`, `deepseek-v4-1-flash-1017`)
- **Hosted by Mistral, not routed to Z.ai or DeepSeek:** Both models are hosted directly on Mistral AI Infrastructure under Mistral's Commercial Terms (§1.3), not proxied to Z.ai or DeepSeek APIs:
  - [`zai-glm-5-3-flash`](https://docs.mistral.ai/models/zai-glm-5-3-flash): tagged `GA` · `Third-party` · `MIT`. *"The model is served without Mistral modifications."*
  - [`deepseek-v4-flash-1017`](https://docs.mistral.ai/models/deepseek-v4-flash-1017): tagged `Public Preview` · `Third-party` · `MIT`. *"DeepSeek V4.1 Flash 1017 is a third-party open weight model from DeepSeek, hosted by Mistral, with support for text and image inputs. ... The model is served without Mistral modifications."*
  - Under [Additional Product Terms §6](https://legal.mistral.ai/terms/additional-terms), Mistral disclaims ownership, warranties, and IP indemnification for *"Third-Party Technologies"* (such as third-party models), without altering Mistral's data-processing role on Mistral Infrastructure.
- **EU regional availability (`api.eu.mistral.ai`):** **Not stated** in the documentation. Regional Inference warns: *"Available models vary by region. ... Regional endpoints only serve models hosted in that region. ... To list available models, call `models.list` against the regional base URL or the SDK server value for the region."* (Not tested here, as API calls were out of scope.)

---

## 3. Retention and Training Use of API Inputs (Legal Documents)

Because our pipeline sends scanned KIO appeals, powers of attorney, and bank-transfer confirmations (containing personal data: names, PESELs, addresses, bank accounts), retention and training rules are decisive:

1. **Default API retention (30 days):** Unless Zero Data Retention (ZDR) is active, Mistral retains stateless API inputs/outputs for **30 rolling days** for abuse monitoring ([Privacy Policy §5](https://legal.mistral.ai/terms/privacy-policy)).
2. **Zero Data Retention (ZDR):** Available only on **pay-as-you-go** for stateless endpoints (`/v1/chat/completions`, etc.), requires a support request with legitimate reasons and discretionary approval, and **excludes Labs and Public Preview models** ([ZDR docs](https://docs.mistral.ai/admin/monitor-comply/zero-data-retention); [ZDR Help article](https://help.mistral.ai/en/articles/347612-can-i-activate-zero-data-retention-zdr)).
3. **Training opt-out (GA vs. Public Preview):**
   - For standard **GA** API models (`zai-glm-5-3-flash`), customers can opt out of training at any time via *Admin Panel → Privacy → Data usage for improving our services* ([Opt-out Help article](https://help.mistral.ai/en/articles/455207-can-i-opt-out-of-my-input-or-output-data-being-used-for-training); [Commercial Terms §4.2](https://legal.mistral.ai/terms/commercial-terms-of-service)).
   - For **Public Preview** models (`deepseek-v4-1-flash-1017`), opt-out and ZDR are **disabled by contract and lifecycle policy**:
     > "Public Preview ... Don't support data collection opt-out. Don't support Zero Data Retention (ZDR)." — [Model Lifecycle Policy](https://docs.mistral.ai/inference/model-lifecycle)
     > "By using Labs or Preview Models, you acknowledge that (i) Mistral AI may use Customer Data and Outputs generated from Labs or Preview Models to train its artificial intelligence models and (ii) the opt-out preferences you selected for other Mistral AI Products (including through zero data retention) does not apply to Labs or Preview Models. If you do not want your data or outputs used for training, do not use Labs or Preview Models." — [Commercial Terms §4.3](https://legal.mistral.ai/terms/commercial-terms-of-service)

---

## 4. Licences and Parameter Counts (Open Weights)

| Model (Mistral API ID) | Open Weights (Hugging Face) | Licence | Parameter Count |
|---|---|---|---|
| **GLM-5.3-Flash** (`zai-glm-5-3-flash`) | Yes: [`zai-org/GLM-5.3-Flash`](https://huggingface.co/zai-org/GLM-5.3-Flash) | **MIT** ([LICENSE](https://huggingface.co/zai-org/GLM-5.3-Flash/blob/main/LICENSE), `Copyright (c) 2026 Z.AI Co., Ltd`) | **320B total / 18B active** MoE ([Mistral docs](https://docs.mistral.ai/models/zai-glm-5-3-flash), HF README; safetensors metadata: `321,323,031,390`) |
| **DeepSeek V4.1 Flash** (`deepseek-v4-1-flash-1017`) | Yes: [`deepseek-ai/DeepSeek-V4.1-Flash-1017`](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017) & [`DeepSeek-V4.1-Flash`](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash) | **MIT** ([LICENSE](https://huggingface.co/deepseek-ai/DeepSeek-V4.1-Flash-1017/blob/main/LICENSE), `Copyright (c) 2023 DeepSeek`) | **763B total / 37B active** on [Mistral docs](https://docs.mistral.ai/models/deepseek-v4-flash-1017) (matching HF safetensors `763,205,315,794`); base HF README cites **552B backbone + 196B Engram** (748B) and **8B prefill / 16B decode active** |

---

## 5. Verdicts & What to Tell the Jury

| Model | Verdict | Why |
|---|---|---|
| **`zai-glm-5-3-flash`** (GLM-5.3-Flash) | **Unclear** *(Non-compliant on current `api.mistral.ai`; potentially compliant on `api.eu.mistral.ai`)* | Open-weight MIT licence and **GA** status (supports training opt-out and ZDR). However, `https://api.mistral.ai/v1` makes **no inference location commitment**, and Mistral's docs do not state whether `zai-glm-5-3-flash` is served on `https://api.eu.mistral.ai/v1` or whether all control-plane/abuse logs stay in the EU/EEA. |
| **`deepseek-v4-1-flash-1017`** (DeepSeek V4.1 Flash) | **Not compliant** | Although open-weight MIT, it is a **Public Preview** model on Mistral La Plateforme. Under Commercial Terms §4.3 and Model Lifecycle Policy, it **cannot opt out of model training** and **does not support ZDR**, which is unacceptable for legal documents with personal data—plus it shares the same unverified EU endpoint availability. *(Also 763B/552B total, penalised under Stage 2 model-size scoring.)* |

### Questions to Resolve with Mistral (and via `api.eu.mistral.ai`) before Submission
1. **Model availability on EU endpoint:** Check `GET https://api.eu.mistral.ai/v1/models` (or ask Mistral support) to confirm whether `zai-glm-5-3-flash` is hosted on the EU regional endpoint. *(If not, switch to a GA Mistral open-weight model confirmed on `api.eu.mistral.ai`, e.g., `mistral-small-*` / `ministral-*`, which also improves Stage 2 size score.)*
2. **Control-plane & abuse-log residency:** Ask Mistral support / account team whether API abuse-monitoring logs (30-day default) and control-plane metadata for `api.eu.mistral.ai` organizations are processed exclusively in EU/EFTA data centers, and request **Zero Data Retention (ZDR)** on the jury organization.
3. **Account privacy toggle:** Verify in the jury organization's Studio Admin Panel (*Privacy → Data usage for improving our services*) that model training is **OFF** (opted out).

### What to State to the Jury in the Submission
- **API provider & EU/EEA jurisdiction:** We use **Mistral La Plateforme** operated by **Mistral AI** (Paris, France), governed by GDPR with a published [Privacy Policy](https://legal.mistral.ai/terms/privacy-policy) and [DPA](https://legal.mistral.ai/terms/data-processing-addendum).
- **EU endpoint & data controls:** Requests are routed to Mistral's EU regional inference endpoint (`https://api.eu.mistral.ai/v1`, EU/EFTA data centers), with API model training disabled (opted out) in the organization's Privacy settings (and ZDR requested for stateless `/v1/chat/completions` calls; otherwise 30-day rolling abuse-monitoring retention applies, and Mistral notes control-plane operational metadata may be handled outside the inference region).
- **Model & open-weight licence:** **`zai-glm-5-3-flash`** (Z.ai GLM-5.3-Flash, **MIT** open-weight licence, **320B total / 18B active** MoE parameters), hosted directly on Mistral's infrastructure (not routed to Z.ai). `deepseek-v4-1-flash-1017` was excluded because its Public Preview status prohibits training opt-out and ZDR.

---

## Coordinator follow-up (2026-11-21)

- Verified with the dev key: `GET https://api.eu.mistral.ai/v1/models` lists `zai-glm-5-3-flash` (and
  `deepseek-v4-1-flash-1017`), and a JSON-mode chat completion with `zai-glm-5-3-flash` on the EU endpoint returns
  `finish_reason: stop`. The app now defaults to `https://api.eu.mistral.ai/v1` (`LLM_BASE_URL`).
- DeepSeek V4.1 Flash is dropped from the comparison (Public Preview: no opt-out, no ZDR).
- Before delivery (task D1, user action): in the Mistral admin panel opt out of training (*Privacy → Data usage
  for improving our services*), consider requesting ZDR, and create the separate jury key on that organisation.
