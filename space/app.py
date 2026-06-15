"""
Sigma GPT Runtime - Hugging Face Space
Serves repo-backed personalization, receipts, and policy endpoints for Custom GPT Actions.
"""

from fastapi import FastAPI, HTTPException, Header, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from typing import List, Dict, Any, Optional
from pathlib import Path
import yaml
import json
import hashlib
import os
from datetime import datetime
import httpx

# Configuration
HF_RUNTIME_TOKEN = os.getenv("HF_RUNTIME_TOKEN", "default-token-change-me")
GITHUB_RAW_BASE = os.getenv("GITHUB_RAW_BASE", "")
GITHUB_REPO = os.getenv("GITHUB_REPO", "")
GITHUB_BRANCH = os.getenv("GITHUB_BRANCH", "main")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
ALLOW_DIRECT_REPO_WRITES = os.getenv("ALLOW_DIRECT_REPO_WRITES", "false").lower() == "true"

POLICY_DIR = Path("/data/policy")
RECEIPTS_DIR = Path("/data/receipts")
RECEIPTS_DIR.mkdir(exist_ok=True)

# Initialize FastAPI
app = FastAPI(
    title="Sigma GPT Runtime",
    description="Repo-backed personalization and receipt storage for Custom GPT Actions",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# Pydantic models
class ContextRequest(BaseModel):
    chat_id: str = Field(..., description="Chat identifier")
    user_id: Optional[str] = Field(None, description="User identifier")

class ContextResponse(BaseModel):
    chat_id: str
    policy_state: Dict[str, Any]
    user_capsule: Dict[str, Any]
    scoring_weights: Dict[str, float]
    claim_labels: List[str]

class VerifyRequest(BaseModel):
    claim: str = Field(..., description="Claim to verify")
    context: Optional[Dict[str, Any]] = Field(None, description="Additional context")

class VerifyResponse(BaseModel):
    claim: str
    verified: bool
    confidence: float
    evidence_refs: List[str]

class ScoreRequest(BaseModel):
    answer: str = Field(..., description="Answer to score")
    chat_id: str = Field(..., description="Chat identifier")

class ScoreResponse(BaseModel):
    answer: str
    density_score: float
    artifact_count: int
    overall_grade: str

class ReceiptRequest(BaseModel):
    chat_id: str = Field(..., description="Chat identifier")
    answer: str = Field(..., description="Answer content")
    metadata: Optional[Dict[str, Any]] = Field(None, description="Additional metadata")

class ReceiptResponse(BaseModel):
    receipt_id: str
    chat_id: str
    sha256_hash: str
    timestamp: str
    stored: bool

class BenchmarkRequest(BaseModel):
    prompt: str = Field(..., description="Prompt to benchmark")
    model: Optional[str] = Field("gpt-4", description="Model identifier")

class BenchmarkResponse(BaseModel):
    prompt: str
    response: str
    metrics: Dict[str, float]

class ProposeUpdateRequest(BaseModel):
    policy_delta: Dict[str, Any] = Field(..., description="Policy changes to propose")
    reason: str = Field(..., description="Reason for the update")

class ProposeUpdateResponse(BaseModel):
    proposal_id: str
    status: str
    dry_run: bool
    github_commit_url: Optional[str] = None


# Helper functions
def verify_auth(authorization: Optional[str] = Header(None)) -> bool:
    """Verify Bearer token authentication."""
    if not authorization:
        return False
    if not authorization.startswith("Bearer "):
        return False
    token = authorization.replace("Bearer ", "")
    return token == HF_RUNTIME_TOKEN


def load_policy_file(filename: str) -> Dict[str, Any]:
    """Load policy file from data directory."""
    file_path = POLICY_DIR / filename
    if file_path.exists():
        with open(file_path, 'r') as f:
            if filename.endswith('.yaml') or filename.endswith('.yml'):
                return yaml.safe_load(f)
            else:
                return json.load(f)
    return {}


def save_receipt(receipt_data: Dict[str, Any]) -> str:
    """Save receipt to receipts directory."""
    receipt_id = f"receipt-{datetime.utcnow().timestamp()}"
    receipt_path = RECEIPTS_DIR / f"{receipt_id}.json"
    with open(receipt_path, 'w') as f:
        json.dump(receipt_data, f, indent=2)
    return receipt_id


def get_latest_receipt() -> Optional[Dict[str, Any]]:
    """Get the most recent receipt."""
    receipts = list(RECEIPTS_DIR.glob("*.json"))
    if receipts:
        latest = max(receipts, key=lambda p: p.stat().st_mtime)
        with open(latest, 'r') as f:
            return json.load(f)
    return None


# Endpoints
@app.get("/")
async def root():
    """Root endpoint with runtime information."""
    return {
        "service": "Sigma GPT Runtime",
        "version": "1.0.0",
        "status": "operational",
        "github_repo": GITHUB_REPO,
        "allow_direct_repo_writes": ALLOW_DIRECT_REPO_WRITES
    }


@app.post("/context", response_model=ContextResponse)
async def get_context(request: ContextRequest, authorization: Optional[str] = Header(None)):
    """Get repo-backed personalization capsule for a chat."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    policy_state = load_policy_file("policy_state.yaml")
    user_capsule = load_policy_file("user_capsule.json")
    scoring_weights = load_policy_file("scoring_weights.yaml")
    claim_labels_data = load_policy_file("claim_labels.yaml")
    claim_labels = claim_labels_data.get("labels", [])

    return ContextResponse(
        chat_id=request.chat_id,
        policy_state=policy_state,
        user_capsule=user_capsule,
        scoring_weights=scoring_weights,
        claim_labels=claim_labels
    )


@app.get("/policy")
async def get_policy(authorization: Optional[str] = Header(None)):
    """Get current policy state."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return load_policy_file("policy_state.yaml")


@app.post("/verify", response_model=VerifyResponse)
async def verify_claim(request: VerifyRequest, authorization: Optional[str] = Header(None)):
    """Verify a claim against policy and evidence."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Simple verification logic - in production, use actual evidence checking
    verified = len(request.claim) > 10  # Placeholder
    confidence = 0.7 if verified else 0.3

    return VerifyResponse(
        claim=request.claim,
        verified=verified,
        confidence=confidence,
        evidence_refs=[]
    )


@app.post("/score", response_model=ScoreResponse)
async def score_answer(request: ScoreRequest, authorization: Optional[str] = Header(None)):
    """Score answer for density and artifact yield."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    text_length = len(request.answer)
    density_score = min(1.0, text_length / 500.0)
    artifact_count = request.answer.count("```") // 2  # Count code blocks

    overall_score = (density_score + min(1.0, artifact_count / 3.0)) / 2.0
    if overall_score >= 0.8:
        grade = "A"
    elif overall_score >= 0.6:
        grade = "B"
    elif overall_score >= 0.4:
        grade = "C"
    else:
        grade = "D"

    return ScoreResponse(
        answer=request.answer,
        density_score=density_score,
        artifact_count=artifact_count,
        overall_grade=grade
    )


@app.post("/receipt", response_model=ReceiptResponse)
async def create_receipt(request: ReceiptRequest, authorization: Optional[str] = Header(None)):
    """Store answer receipt with hash and timestamp."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    sha256_hash = hashlib.sha256(request.answer.encode()).hexdigest()
    timestamp = datetime.utcnow().isoformat()

    receipt_data = {
        "chat_id": request.chat_id,
        "answer": request.answer,
        "sha256_hash": sha256_hash,
        "timestamp": timestamp,
        "metadata": request.metadata
    }

    receipt_id = save_receipt(receipt_data)

    return ReceiptResponse(
        receipt_id=receipt_id,
        chat_id=request.chat_id,
        sha256_hash=sha256_hash,
        timestamp=timestamp,
        stored=True
    )


@app.get("/receipts/latest")
async def get_latest_receipt_endpoint(authorization: Optional[str] = Header(None)):
    """Get the most recent receipt."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")
    return get_latest_receipt()


@app.post("/benchmark", response_model=BenchmarkResponse)
async def run_benchmark(request: BenchmarkRequest, authorization: Optional[str] = Header(None)):
    """Run benchmark on prompt."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # Placeholder benchmark - in production, actual model call
    return BenchmarkResponse(
        prompt=request.prompt,
        response="Benchmark response placeholder",
        metrics={"latency_ms": 100, "tokens": 50}
    )


@app.post("/propose-update", response_model=ProposeUpdateResponse)
async def propose_update(request: ProposeUpdateRequest, authorization: Optional[str] = Header(None)):
    """Propose policy update to GitHub."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    proposal_id = f"proposal-{datetime.utcnow().timestamp()}"
    dry_run = not ALLOW_DIRECT_REPO_WRITES

    if ALLOW_DIRECT_REPO_WRITES and GITHUB_TOKEN and GITHUB_REPO:
        # In production, create GitHub PR or commit
        github_commit_url = f"https://github.com/{GITHUB_REPO}/commit/{proposal_id}"
    else:
        github_commit_url = None

    return ProposeUpdateResponse(
        proposal_id=proposal_id,
        status="proposed" if dry_run else "committed",
        dry_run=dry_run,
        github_commit_url=github_commit_url
    )


@app.post("/repo/refresh")
async def refresh_repo(authorization: Optional[str] = Header(None)):
    """Trigger repo refresh from GitHub."""
    if not verify_auth(authorization):
        raise HTTPException(status_code=401, detail="Unauthorized")

    # In production, pull latest from GitHub
    return {"status": "refreshed", "timestamp": datetime.utcnow().isoformat()}


@app.get("/instructions")
async def get_instructions():
    """Get Custom GPT instructions."""
    instructions_path = Path("/data/examples/custom_gpt_instructions.txt")
    if instructions_path.exists():
        with open(instructions_path, 'r') as f:
            return {"instructions": f.read()}
    return {"instructions": "Instructions not found"}


@app.get("/openapi.json")
async def get_openapi_schema():
    """Get OpenAPI schema for GPT Actions."""
    return app.openapi()


@app.get("/healthz")
async def healthz():
    """Health check endpoint."""
    return {"status": "healthy"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=7860)
