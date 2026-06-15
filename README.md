# Sigma GPT Runtime - Gate.io Calibration

**GitHub → Hugging Face Space → Custom GPT Action** loop for repo-backed personalization, Gate.io market data research, and receipt storage.

## Architecture

```
GitHub repo = source of truth
GitHub Actions = validates + syncs repo to Hugging Face
Hugging Face Space = serves live API endpoints
Custom GPT Action = calls those endpoints during chat
/receipt + /propose-update = stores answer receipts and policy deltas
Gate.io WebSocket = public market data collection (research-only)
```

## Components

### Hugging Face Space Endpoints

#### Account Cognition
- `GET /healthz` - Health check
- `POST /context` - Get repo-backed personalization capsule
- `GET /policy` - Get current policy state
- `POST /verify` - Verify claims against policy
- `POST /score` - Score answer for density and artifact yield
- `POST /receipt` - Store answer receipt with hash
- `GET /receipts/latest` - Get most recent receipt

#### Gate.io Market Stream (Research-Only)
- `GET /gate/config` - Gate.io API configuration
- `POST /gate/candles` - Pull public futures candles from Gate REST
- `POST /gate/backtest` - Run SMA-cross research baseline
- `POST /gate/ws-sample` - Sample WebSocket messages
- `POST /gateio/stream/start` - Start Gate.io futures public market-data collector
- `POST /gateio/stream/stop` - Stop Gate.io stream collector
- `GET /gateio/stream/status` - Get current stream collector status
- `GET /gateio/snapshot` - Get latest compressed Gate.io stream snapshot
- `GET /gateio/features` - Get computed stream features for a symbol/window
- `POST /gateio/replay` - Replay recorded Gate.io stream data

#### Prompt Calibration
- `POST /prompt/calibrate` - Convert raw user prompt into calibrated artifact-first prompt
- `POST /calibrate/prompt` - V2 endpoint for prompt calibration

#### Signal & Accounting
- `POST /signal/fuse` - Combine backtest result + live snapshot + latent history capsule
- `POST /cost-savings/estimate` - Estimate user-side AI-assisted work savings
- `POST /benchmark/compare` - Compare multiple benchmark runs
- `POST /residue/score` - Calculate artifact residue score
- `GET /benchmarks/latest` - Get latest benchmark results

#### System
- `POST /benchmark` - Run benchmark on prompt
- `POST /propose-update` - Propose policy update to GitHub
- `POST /repo/refresh` - Trigger repo refresh from GitHub
- `GET /instructions` - Get Custom GPT instructions
- `GET /openapi.json` - Get OpenAPI schema for GPT Actions

### Policy Files

- `policy_state.yaml` - Core principles, boundaries, output preferences
- `user_capsule.json` - User preferences and project context
- `scoring_weights.yaml` - Answer evaluation weights
- `claim_labels.yaml` - Claim classification taxonomy

### GitHub Workflows

- `validate.yml` - Validates policy YAML files and OpenAPI schema
- `sync-to-huggingface.yml` - Syncs space and policy files to Hugging Face

## Setup

### 1. Upload to GitHub

Upload the contents of this directory to a new GitHub repository.

### 2. Create Hugging Face Space

Create a new Docker Space on Hugging Face.

### 3. Configure GitHub Secrets

Add the following secret to your GitHub repository:

```
HF_TOKEN = your-huggingface-token
```

### 4. Configure Sync Workflow

Edit `.github/workflows/sync-to-huggingface.yml`:

Replace `YOUR_HF_USERNAME/YOUR_SPACE_NAME` with your actual Hugging Face Space repo ID.

### 5. Configure Hugging Face Space Secrets

Add these secrets to your Hugging Face Space (optional but recommended):

```
HF_RUNTIME_TOKEN = long-random-token
GITHUB_RAW_BASE = https://raw.githubusercontent.com/OWNER/REPO/main
GITHUB_REPO = OWNER/REPO
GITHUB_BRANCH = main
GITHUB_TOKEN = github-fine-grained-token
ALLOW_DIRECT_REPO_WRITES = false
```

**Important**: Keep `ALLOW_DIRECT_REPO_WRITES=false` initially. This means the runtime proposes repo updates without committing them. Enable only after testing.

### 6. Configure Custom GPT Action

1. Create a new Custom GPT in ChatGPT
2. Go to Actions → Create new action
3. Import OpenAPI schema: `https://YOUR_HF_USERNAME-YOUR_SPACE_NAME.hf.space/openapi.json`
4. Configure authentication: Bearer token (use `HF_RUNTIME_TOKEN`)
5. Paste the instruction capsule from `examples/custom_gpt_instructions.txt`

## Safe Loop

1. User sends prompt
2. GPT calls `/context` to get repo-backed personalization
3. GPT answers using policy guidance
4. GPT calls `/verify` for risky claims
5. GPT calls `/score` for quality assessment
6. GPT calls `/receipt` to store answer with hash
7. GPT calls `/propose-update` for policy improvements
8. GitHub stores policy/receipts/deltas
9. GitHub Actions validates
10. GitHub Actions syncs updated runtime to Hugging Face
11. Next chat sees improved external runtime

## Security Boundaries

- Does NOT update OpenAI model weights
- Does NOT expose hidden chain-of-thought
- Does NOT secretly write to GitHub
- Updates external repo/Hugging Face runtime only when configured endpoint is called
- Requires Bearer token authentication
- Repo writes are dry-run by default

## What This Gives You

- Repo-managed personalization
- Live Hugging Face API surface
- Custom GPT Action compatibility
- Answer receipts with hash verification
- Policy deltas through proper channels
- Benchmark schema
- Claim verification
- Artifact-density scoring
- GitHub CI/CD validation
- HF deployment sync

## QA Receipt

```yaml
created:
  - sigma-gpt-runtime scaffold
  - HF Space with all endpoints
  - GitHub workflows for validation and sync
  - Policy files and OpenAPI schema
  - Custom GPT instructions

verified:
  - Hugging Face Spaces are Git-backed and rebuild on commits
  - GitHub Actions can sync to Hugging Face using huggingface_hub
  - GPT Actions can call external REST APIs with OpenAPI schema

inferred:
  - Financeability scoring and AI interaction property recovery
  - Portable second-brain runtime architecture

blocked:
  - Hidden OpenAI model-weight updates
  - Automatic repo writes without credentials
  - Automatic persistence of every chat unless /receipt is called

next_repo_delta:
  file: sigma-gpt-runtime/
  commit: "sepf: update ledger — SIGMA_RUNTIME — gpt_action_scaffold"

next_proof_upgrade:
  - Deploy to Hugging Face Space
  - Configure Custom GPT Action
  - Test endpoint behavior and safety boundaries
```

## References

- [Hugging Face Spaces Overview](https://huggingface.co/docs/hub/en/spaces-overview)
- [Spaces as MCP Servers](https://huggingface.co/docs/hub/spaces-mcp-servers)
- [Managing Spaces with GitHub Actions](https://huggingface.co/docs/hub/spaces-github-actions)
- [GPT Actions Introduction](https://developers.openai.com/api/docs/actions/introduction)
- [Manage Your Space](https://huggingface.co/docs/huggingface_hub/en/guides/manage-spaces)
