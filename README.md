# inTrust - Trustworthiness Assessment Tool

## Overview

**inTrust** is a tool developed within the **INTEND** project, designed to assist users in assessing the trustworthiness of executing intents within the computing continuum. Trustworthiness in this context is an overarching concept that includes multiple key aspects such as **security, privacy, and trust**. The primary goal of **inTrust** is to generate a natural language **trustworthiness report**, helping users make informed decisions regarding intent execution.

To achieve this, **inTrust** collects various trustworthiness metrics from multiple sources, including its own assessments and data provided by other INTEND tools. The system then interprets these metrics to generate comprehensive reports.

## Key Features

- **Trustworthiness Assessment**: Evaluates intents based on security, privacy, and trust considerations.
- **REST API**: Provides an interface for external tools to trigger assessments.
- **Message Bus Integration**: Publishes assessment results via a pub-sub mechanism for interested parties.

## Interactions with Other INTEND Tools

Currently, **inTrust** does not directly interact with any other INTEND tools. However, it is designed to share its trustworthiness reports with interested tools via a **publish-subscribe (pub-sub) mechanism**. For example:

- **iExplain** could subscribe to inTrust notifications and receive updates when a new assessment is available.
- **inGraph** might be used to store static trustworthiness-related information about the continuum or specific pipelines (details pending further specification).

## API & Integration

### REST API

**inTrust** will expose a REST API allowing external tools to trigger trustworthiness assessments. The API will accept various parameters based on the **inTrust taxonomy**, including:

```yaml
parameters:
  - name: target_application
    description: The application or process being assessed.
  - name: type_of_assessment
    description: Defines the scope (e.g., security, privacy, overall trustworthiness).
  - name: timeliness
    description: Specifies assessment urgency.
  - name: output_format
    description: Defines the preferred format for the trustworthiness report.
```

A detailed API specification will be provided as development progresses.

### Message Bus Integration

```json
{
  "event": "trustworthiness_assessment",
  "data": {
    "assessment_id": "12345",
    "status": "completed",
    "report_url": "https://example.com/report/12345"
  }
}
```

- **inTrust** will publish trustworthiness assessments via a **pub-sub message queue** (likely using **MQTT**).
- Interested tools (such as **iExplain**) can subscribe to receive updates when new assessments are available.

## Data Sharing & Configuration

- **Data Shared**: Trustworthiness assessment reports.
- **Storage**: Some trustworthiness-related information may be stored in **inGraph**, though this is not yet finalized.
- **Configuration**: The configuration details are still under discussion.

## Authentication & Security

Authentication and access control mechanisms are yet to be fully defined and will be detailed in future updates.

---

**inTrust** is under active development, and more details will be provided as the tool evolves within the INTEND framework.

