# ClickSense Vertex AI Setup Guide

## Prerequisites

1. **GCP Project**: `neon-citizen-491605-n8`
2. **Region**: `us-central1`
3. **Vertex AI API** must be enabled

## Authentication Setup

### Option 1: Application Default Credentials (ADC) - Recommended for Local Development

1. **Install Google Cloud SDK**:
   ```bash
   # Windows (using Chocolatey)
   choco install gcloudsdk

   # Or download from: https://cloud.google.com/sdk/docs/install
   ```

2. **Initialize and authenticate**:
   ```bash
   gcloud init
   gcloud auth application-default login
   ```

3. **Enable Vertex AI API** (if not already enabled):
   ```bash
   gcloud services enable aiplatform.googleapis.com --project=neon-citizen-491605-n8
   ```

4. **Test authentication**:
   ```bash
   gcloud auth application-default print-access-token
   ```

### Option 2: Service Account Key - Recommended for Docker/Production

1. **Create Service Account**:
   ```bash
   gcloud iam service-accounts create clicksense-backend \
     --project=neon-citizen-491605-n8 \
     --display-name="ClickSense Backend"
   ```

2. **Grant necessary roles**:
   ```bash
   gcloud projects add-iam-policy-binding neon-citizen-491605-n8 \
     --member="serviceAccount:clicksense-backend@neon-citizen-491605-n8.iam.gserviceaccount.com" \
     --role="roles/aiplatform.user"

   gcloud projects add-iam-policy-binding neon-citizen-491605-n8 \
     --member="serviceAccount:clicksense-backend@neon-citizen-491605-n8.iam.gserviceaccount.com" \
     --role="roles/serviceusage.serviceUsageConsumer"
   ```

3. **Create and download key**:
   ```bash
   gcloud iam service-accounts keys create service-account.json \
     --project=neon-citizen-491605-n8 \
     --iam-account=clicksense-backend@neon-citizen-491605-n8.iam.gserviceaccount.com
   ```

4. **Move key to project directory**:
   ```bash
   # For local development
   mv service-account.json C:\Users\KIIT0001\clicksenseV2\backend\

   # For Docker
   mv service-account.json C:\Users\KIIT0001\clicksenseV2\
   ```

5. **Update .env file**:
   ```bash
   GOOGLE_APPLICATION_CREDENTIALS=C:\Users\KIIT0001\clicksenseV2\backend\service-account.json
   ```

## Installation

1. **Install dependencies**:
   ```bash
   cd C:\Users\KIIT0001\clicksenseV2\backend
   pip install -r requirements.txt
   ```

2. **Update .env file**:
   ```bash
   GCP_PROJECT_ID=neon-citizen-491605-n8
   GCP_LOCATION=us-central1
   REDIS_URL=redis://localhost:6379
   ```

## Running Locally

### With ADC (Option 1):
```bash
cd C:\Users\KIIT0001\clicksenseV2\backend
python main.py
```

### With Service Account Key (Option 2):
```bash
cd C:\Users\KIIT0001\clicksenseV2\backend
set GOOGLE_APPLICATION_CREDENTIALS=service-account.json
python main.py
```

## Running with Docker

### With Service Account Key (Recommended):
1. **Place service account key**:
   ```bash
   cp service-account.json C:\Users\KIIT0001\clicksenseV2\
   ```

2. **Uncomment service account lines in docker-compose.yml**:
   ```yaml
   environment:
     - GOOGLE_APPLICATION_CREDENTIALS=/app/credentials/service-account.json
   volumes:
     - ./service-account.json:/app/credentials/service-account.json:ro
   ```

3. **Start services**:
   ```bash
   cd C:\Users\KIIT0001\clicksenseV2
   docker-compose up --build
   ```

### With Workload Identity (Advanced):
For production on GKE, use Workload Identity Federation instead of service account keys.

## Troubleshooting

### Error: "Could not automatically determine credentials"
**Solution**: Run `gcloud auth application-default login` or set `GOOGLE_APPLICATION_CREDENTIALS`

### Error: "Vertex AI API not enabled"
**Solution**: Enable the API:
```bash
gcloud services enable aiplatform.googleapis.com --project=neon-citizen-491605-n8
```

### Error: "Permission denied"
**Solution**: Ensure your service account has the `roles/aiplatform.user` role

### Error: "Quota exceeded"
**Solution**: Check your GCP quotas in the console and request increases if needed

## Model Information

- **Model**: `gemini-2.0-flash` (auto-updated alias)
- **Alternative models**: `gemini-2.5-flash`, `gemini-2.5-pro`, `gemini-1.5-pro-001`
- **Region**: `us-central1`
- **Project**: `neon-citizen-491605-n8`

**Sources:**
- [Google models documentation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models)
- [Gemini 2.5 Flash documentation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/models/gemini/2-5-flash)
- [Model versions documentation](https://docs.cloud.google.com/vertex-ai/generative-ai/docs/learn/model-versions)

## Cost Monitoring

Monitor your Vertex AI costs:
```bash
gcloud billing projects describe neon-citizen-491605-n8
```

Check usage in GCP Console: https://console.cloud.google.com/ai/platform
